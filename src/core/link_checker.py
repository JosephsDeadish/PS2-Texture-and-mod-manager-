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

import logging
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from typing import Dict, List, Optional

from src.core.catalogue_loader import is_placeholder_author

logger = logging.getLogger(__name__)


_REPO_ROOT = Path(__file__).parent.parent.parent
_CAT_DIR   = _REPO_ROOT / "data" / "catalogue"

# URL fields that may appear in a catalogue entry
_URL_FIELDS = ("url", "author_url", "direct_download_url", "thumbnail_url")

# File/type kinds where missing author credits are data-quality problems.
_CATALOGUE_KINDS = frozenset({
    "texture_pack",
    "save_file",
    "cheat",
    "cover_art",
    "pnach",
})

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
    "disk.yandex.ru",
    "mega.nz",
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


def _split_url_host_path(url: str) -> tuple[str, str]:
    """Return the host/path pair for *url* (normalising ``www.`` prefixes)."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host, parts.path.lower()


def _user_catalogue_dir() -> Path:
    from src.core.config_manager import get_exe_dir

    return get_exe_dir() / "user_catalogue"


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
    issue_type: str   # "malformed", "bad_domain", "suspicious_domain", "empty_required", "empty_author", "placeholder_author"
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
        # Extract host and path from URL so path-scoped bad-domain rules can
        # match entries like ``gamefaqs.gamespot.com/ps2/invalid``.
        host, path = _split_url_host_path(url)
        if not host:
            return None
        host_and_path = host + path
        for bad in _BAD_DOMAINS:
            if "/" in bad:
                if host_and_path == bad or host_and_path.startswith(bad + "/"):
                    return bad
                continue
            if host == bad or host.endswith("." + bad):
                return bad
        return None

    def _is_trusted_domain(self, url: str) -> bool:
        """Return True if *url* uses one of the known trusted domains."""
        host, _path = _split_url_host_path(url)
        if not host:
            return False
        for trusted in _TRUSTED_DOMAINS:
            if host == trusted or host.endswith("." + trusted):
                return True
        return False

    def _is_suspicious_domain(self, url: str) -> Optional[str]:
        """Return the host if *url* looks valid but points to an untrusted domain."""
        if self._is_malformed(url):
            return None
        if self._is_bad_domain(url):
            return None
        if self._is_trusted_domain(url):
            return None
        host, _path = _split_url_host_path(url)
        return host or None

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
        source_kind = {
            "cheats": "cheat",
            "saves": "save_file",
            "texture_packs": "texture_pack",
            "cover_art": "cover_art",
        }.get(Path(source_file).stem.lower(), Path(source_file).stem.lower())
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                logger.warning(
                    "Skipping malformed catalogue entry in %s[%s]: expected a JSON object, got %r",
                    source_file,
                    idx,
                    entry,
                )
                issues.append(LinkIssue(
                    source_file=source_file,
                    entry_index=idx,
                    field_name="(entry)",
                    url="",
                    issue_type="malformed_entry",
                    detail="catalogue entry must be a JSON object",
                ))
                continue
            entry_kind = str(entry.get("type", "")).lower() or source_kind
            if (entry_kind in _CATALOGUE_KINDS or source_kind in _CATALOGUE_KINDS) and not entry.get("is_hub", False):
                author = entry.get("author", "")
                if not isinstance(author, str) or not author.strip():
                    issues.append(LinkIssue(
                        source_file=source_file,
                        entry_index=idx,
                        field_name="author",
                        url="",
                        issue_type="empty_author",
                        detail="missing author credit",
                    ))
                elif is_placeholder_author(author):
                    issues.append(LinkIssue(
                        source_file=source_file,
                        entry_index=idx,
                        field_name="author",
                        url="",
                        issue_type="placeholder_author",
                        detail=(
                            "generic placeholder author; replace with a credited author "
                            "or a more specific source-page label"
                        ),
                    ))
            if required_url_fields and entry_kind in {"pnach", "cheat", "save_file"}:
                for field_name in required_url_fields:
                    raw_required = entry.get(field_name, "")
                    if isinstance(raw_required, str) and raw_required.strip():
                        continue
                    issues.append(LinkIssue(
                        source_file=source_file,
                        entry_index=idx,
                        field_name=field_name,
                        url="",
                        issue_type="empty_required",
                        detail=f"missing required {field_name!r} for {entry_kind} entry",
                    ))
            for field_name in _URL_FIELDS:
                raw = entry.get(field_name, "")
                if raw in ("", None):
                    continue
                if not isinstance(raw, str):
                    issues.append(LinkIssue(
                        source_file=source_file,
                        entry_index=idx,
                        field_name=field_name,
                        url="",
                        issue_type="malformed",
                        detail="expected a string URL",
                    ))
                    continue
                raw = raw.strip()
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
                    continue
                suspicious_dom = self._is_suspicious_domain(raw)
                if suspicious_dom:
                    issues.append(LinkIssue(
                        source_file=source_file,
                        entry_index=idx,
                        field_name=field_name,
                        url=raw,
                        issue_type="suspicious_domain",
                        detail=(
                            f"host {suspicious_dom!r} is not on the trusted catalogue "
                            "domain list"
                        ),
                    ))
        return issues

    # ------------------------------------------------------------------
    # Catalogue-level checking
    # ------------------------------------------------------------------

    def check_file(
        self,
        path: Path,
        source_file: Optional[str] = None,
        *,
        required_url_fields: Optional[List[str]] = None,
    ) -> List[LinkIssue]:
        """Check all URL fields in a single JSON catalogue file."""
        label = source_file or path.name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not parse catalogue link file %s: %s", path, exc)
            return [LinkIssue(
                source_file=label,
                entry_index=-1,
                field_name="(file)",
                url="",
                issue_type="parse_error",
                detail=str(exc),
            )]
        if not isinstance(data, list):
            logger.warning(
                "Could not parse catalogue link file %s: expected a JSON array at the top level",
                path,
            )
            return [LinkIssue(
                source_file=label,
                entry_index=-1,
                field_name="(file)",
                url="",
                issue_type="parse_error",
                detail="expected a JSON array at the top level",
            )]
        return self.check_entries(
            data,
            source_file=label,
            required_url_fields=required_url_fields,
        )

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
            all_issues.extend(
                self.check_file(
                    path,
                    source_file=fname,
                    required_url_fields=["direct_download_url"],
                )
            )

        if self._cat_dir == _CAT_DIR:
            user_dir = _user_catalogue_dir()
            if user_dir.is_dir():
                try:
                    user_files = sorted(user_dir.glob("*.json"))
                except Exception as exc:
                    logger.warning("Could not list user catalogue files under %s: %s", user_dir, exc)
                    user_files = []
                for path in user_files:
                    label = f"user_catalogue/{path.name}"
                    checked.append(label)
                    all_issues.extend(
                        self.check_file(
                            path,
                            source_file=label,
                            required_url_fields=["direct_download_url"],
                        )
                    )

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
