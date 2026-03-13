"""Catalogue link checker — validates URLs stored across all catalogue JSON files.

Provides static validation (format, domain, known-bad patterns) that runs
without making network requests, plus a convenience ``check_all_catalogues()``
function that returns a structured report.

Usage::

    from src.core.link_checker import LinkChecker

    lc = LinkChecker()
    report = lc.check_all_catalogues()
    print(report["summary"])

    # Check a single list of entries
    issues = lc.check_entries(my_list, source_file="saves.json")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


_REPO_ROOT = Path(__file__).parent.parent.parent
_CAT_DIR   = _REPO_ROOT / "data" / "catalogue"

# URL fields that may appear in a catalogue entry
_URL_FIELDS = ("url", "author_url", "download_url", "direct_download_url",
               "thumbnail_url", "cover_url")

# Domains known to be fake/deprecated in this project's history
_BAD_DOMAINS = frozenset({
    "gamesavedfiles.com",
    "ps2saves.com",
    "ps2hd.com",
    "gamefaqs.gamespot.com/ps2/invalid",
})

# Domains that are always considered trustworthy — URL format check still
# applies, but these domains will never trigger the "suspicious domain" warning.
_TRUSTED_DOMAINS = frozenset({
    "github.com",
    "raw.githubusercontent.com",
    "gbatemp.net",
    "nexusmods.com",
    "patreon.com",
    "mediafire.com",
    "drive.google.com",
    "docs.google.com",
    "archive.org",
    "pcsx2.net",
    "youtube.com",
    "youtu.be",
    "wikia.com",
    "fandom.com",
    "gamefaqs.gamespot.com",
    "codejunkies.com",
    "gamehacking.org",
    "pnach.net",
    "reddit.com",
    "discord.gg",
    "twitter.com",
    "x.com",
    "ps2wide.net",
    "retroachievements.org",
    "hackandslash.net",
    "github.githubassets.com",
})

# Very basic HTTP/HTTPS URL validation regex
_URL_RE = re.compile(
    r'^https?://'                          # scheme
    r'([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'  # host
    r'(/[^\s]*)?$',                        # path (optional)
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class LinkIssue:
    """A URL problem found while checking a catalogue file."""
    source_file: str
    entry_index: int
    field_name: str
    url: str
    issue_type: str   # "malformed", "bad_domain", "empty_required"
    detail: str = ""

    def __str__(self) -> str:
        return (
            f"{self.source_file}[{self.entry_index}].{self.field_name}: "
            f"{self.issue_type} — {self.url!r}"
            + (f" ({self.detail})" if self.detail else "")
        )


# ---------------------------------------------------------------------------
# LinkChecker
# ---------------------------------------------------------------------------

class LinkChecker:
    """Static URL validator for PS2 mod-manager catalogue files.

    Parameters
    ----------
    cat_dir:
        Override the default catalogue directory (useful in tests).
    """

    def __init__(self, cat_dir: Optional[Path] = None) -> None:
        self._cat_dir = Path(cat_dir) if cat_dir else _CAT_DIR

    # ------------------------------------------------------------------
    # Core validators
    # ------------------------------------------------------------------

    def _is_malformed(self, url: str) -> bool:
        """Return True if *url* does not match the expected HTTP/HTTPS format."""
        return not bool(_URL_RE.match(url))

    def _is_bad_domain(self, url: str) -> Optional[str]:
        """Return the offending domain if *url* uses a known-bad domain, else None."""
        # Extract host from URL
        m = re.match(r'^https?://([^/]+)', url, re.IGNORECASE)
        if not m:
            return None
        host = m.group(1).lower().lstrip("www.")
        for bad in _BAD_DOMAINS:
            if host == bad or host.endswith("." + bad):
                return bad
        return None

    # ------------------------------------------------------------------
    # Entry-level checking
    # ------------------------------------------------------------------

    def check_entries(
        self,
        entries: List[dict],
        source_file: str = "catalogue",
        *,
        required_url_fields: Optional[List[str]] = None,
    ) -> List[LinkIssue]:
        """Validate URL fields in a list of catalogue entry dicts.

        Parameters
        ----------
        entries:
            List of catalogue dicts (from a JSON file).
        source_file:
            Label used in issue messages (typically the filename).
        required_url_fields:
            If provided, entries of type ``"pnach"`` or ``"cheat"`` must have
            non-empty values in these fields.

        Returns
        -------
        List[LinkIssue]
            All issues found.
        """
        issues: List[LinkIssue] = []
        for idx, entry in enumerate(entries):
            for field_name in _URL_FIELDS:
                raw = entry.get(field_name, "")
                if not raw:
                    continue
                # Malformed URL check
                if self._is_malformed(raw):
                    issues.append(LinkIssue(
                        source_file=source_file,
                        entry_index=idx,
                        field_name=field_name,
                        url=raw,
                        issue_type="malformed",
                        detail="does not match http(s)://host/path pattern",
                    ))
                    continue
                # Known-bad domain check
                bad_dom = self._is_bad_domain(raw)
                if bad_dom:
                    issues.append(LinkIssue(
                        source_file=source_file,
                        entry_index=idx,
                        field_name=field_name,
                        url=raw,
                        issue_type="bad_domain",
                        detail=f"domain {bad_dom!r} is known fake/deprecated",
                    ))
        return issues

    # ------------------------------------------------------------------
    # Catalogue-level checking
    # ------------------------------------------------------------------

    def check_file(self, path: Path, source_file: Optional[str] = None) -> List[LinkIssue]:
        """Check all URL fields in a single JSON catalogue file."""
        label = source_file or path.name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return [LinkIssue(
                source_file=label,
                entry_index=-1,
                field_name="(file)",
                url="",
                issue_type="parse_error",
                detail=str(exc),
            )]
        if not isinstance(data, list):
            return []
        return self.check_entries(data, source_file=label)

    def check_all_catalogues(self) -> Dict:
        """Check all standard catalogue files and return a structured report.

        Returns a dict with:

        - ``"catalogues_checked"`` — list of filenames checked
        - ``"total_issues"`` — total issue count
        - ``"issues_by_file"`` — mapping of filename → issue list (as dicts)
        - ``"issue_count_by_type"`` — breakdown by issue_type
        - ``"summary"`` — human-readable one-liner
        """
        catalogue_files = [
            "texture_packs.json",
            "pnach.json",
            "saves.json",
            "cover_art.json",
            "cheats.json",
        ]
        all_issues: List[LinkIssue] = []
        checked: List[str] = []

        for fname in catalogue_files:
            path = self._cat_dir / fname
            if not path.is_file():
                continue
            checked.append(fname)
            all_issues.extend(self.check_file(path, source_file=fname))

        # Count by type
        type_counts: Dict[str, int] = {}
        for issue in all_issues:
            type_counts[issue.issue_type] = type_counts.get(issue.issue_type, 0) + 1

        # Group by file
        by_file: Dict[str, List[dict]] = {}
        for issue in all_issues:
            by_file.setdefault(issue.source_file, []).append({
                "entry_index": issue.entry_index,
                "field":       issue.field_name,
                "url":         issue.url,
                "issue_type":  issue.issue_type,
                "detail":      issue.detail,
            })

        total = len(all_issues)
        if total == 0:
            summary = f"✅ All {len(checked)} catalogues passed link checks — 0 issues."
        else:
            summary = (
                f"⚠️  {total} link issue(s) found across {len(checked)} catalogues: "
                + ", ".join(f"{t}×{n}" for t, n in sorted(type_counts.items()))
            )

        return {
            "catalogues_checked": checked,
            "total_issues": total,
            "issues_by_file": by_file,
            "issue_count_by_type": type_counts,
            "summary": summary,
        }
