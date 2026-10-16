"""Catalogue loader — reads per-type JSON files from ``data/catalogue/``.

This module replaces the hard-coded ``CATALOGUE`` list that used to live in
``src/ui/browse_panel.py``.  Splitting the data into JSON files makes it
straightforward to add hundreds or thousands of entries without touching
Python source code.

Folder layout::

    data/
      catalogue/
        texture_packs.json   — ModType.TEXTURE_PACK entries
        pnach.json            — ModType.PNACH entries
        saves.json            — ModType.SAVE_FILE entries
        cheats.json           — ModType.CHEAT entries
        cover_art.json        — ModType.COVER_ART entries

Each JSON file is a **list of entry dicts**.  Every entry must satisfy the
schema defined in ``ENTRY_SCHEMA`` below (missing optional keys are filled
with sensible defaults).  The ``type`` field is injected automatically from
the file it was loaded from, so you do not need to repeat it in every record.

Public API::

    from src.core.catalogue_loader import load_catalogue, CATALOGUE, ALL_SOURCES

    entries = load_catalogue()          # fresh load from disk every call
    entries = CATALOGUE                 # module-level cached list
    sources = ALL_SOURCES               # sorted list of unique source strings
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Dict, List, Optional

from src.models.mod import ModType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

#: Root of the repository (two levels above this file's package)
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent

#: Directory that contains the per-type JSON catalogue files
CATALOGUE_DIR: Path = _REPO_ROOT / "data" / "catalogue"

# ---------------------------------------------------------------------------
# Type → filename mapping  (order also determines display order in Browse)
# ---------------------------------------------------------------------------

_TYPE_FILES: Dict[str, str] = {
    "texture_pack": "texture_packs.json",
    "pnach":        "pnach.json",
    "save_file":    "saves.json",
    "cheat":        "cheats.json",
    "cover_art":    "cover_art.json",
}

# ---------------------------------------------------------------------------
# Required and optional fields with defaults
# ---------------------------------------------------------------------------

#: Fields every entry MUST have (loader will raise ValueError if missing)
_REQUIRED_FIELDS = frozenset({
    "id",
    "name",
    "description",
    "author",
    "url",
    "source",
    "game",
    "game_serial",
})

#: Optional fields and their default values
_OPTIONAL_DEFAULTS: Dict[str, object] = {
    "context":            "",
    "author_url":         "",
    "is_hub":             False,
    "nsfw":               False,
    "thumbnail_url":      "",
    "tags":               [],
    "download_action":    "",
    "direct_download_url": "",
    "upscale_tech":       "",
    "is_free":            True,
    "requires_account":   False,
    "is_complete":        True,
    "size_label":         "",
}

# Valid download actions used by the shipped catalogue and supported by the UI.
VALID_DOWNLOAD_ACTIONS = frozenset({
    "",
    "cover_by_id",
    "cover_by_url",
    "download_save",
    "gdrive",
    "manual",
    "manual_mega",
    "pnach_crc",
    "yandex",
})


def _clone_default(value: object) -> object:
    if isinstance(value, list):
        return list(value)
    return value

_SOURCE_ALIASES = {
    "gbatemp": "GBAtemp",
    "gbatempnet": "GBAtemp",
    "github": "GitHub",
    "githubcom": "GitHub",
    "pcsx2cheatdb": "PCSX2 CheatDB",
    "personal": "Personal",
}

_PLACEHOLDER_THUMBNAIL_HOSTS = frozenset({
    "dummyimage.com",
    "placehold.co",
    "placehold.it",
    "via.placeholder.com",
})

# Catalogue names often use em dashes to separate variant labels, so only
# explicit "by <name>" suffixes and matching profile URLs are treated as
# author cues.
_AUTHOR_BY_RE = re.compile(r"\bby\s+(.+?)\s*$", re.IGNORECASE)
_GBATEMP_MEMBER_RE = re.compile(r"gbatemp\.net/members/([^./#?]+)", re.IGNORECASE)
_PLACEHOLDER_AUTHORS = {
    "unknown": "Unknown",
    "anonymous": "Anonymous",
}


def is_placeholder_author(author: object) -> bool:
    """Return True when *author* is one of the generic placeholder labels."""
    if not isinstance(author, str):
        return False
    return author.strip().casefold() in _PLACEHOLDER_AUTHORS


def _normalise_author_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _normalise_mod_type(type_str: str) -> str:
    if not isinstance(type_str, str):
        raise ValueError(f"mod type must be a string, got {type(type_str).__name__}")
    return re.sub(r"[\s\-]+", "_", type_str.strip().lower())


def _normalise_source(source: str) -> str:
    source = source.strip()
    if not source:
        return "Personal"
    key = re.sub(r"[^a-z0-9]+", "", source.casefold())
    return _SOURCE_ALIASES.get(key, source)


def _normalise_url(url: str, *, preserve_fragment: bool = False) -> str:
    url = url.strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if preserve_fragment or not parts.fragment:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _placeholder_thumbnail_reason(url: str) -> str:
    """Return a human-readable reason when *url* is obviously placeholder art."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "github.githubassets.com" and parts.path.lower().startswith("/favicons/favicon"):
        return "generic favicon placeholder"
    if host in _PLACEHOLDER_THUMBNAIL_HOSTS:
        return "generic placeholder image host"
    return ""


def _is_placeholder_thumbnail_url(url: str) -> bool:
    """Return True for generic placeholder thumbnail URLs."""
    return bool(_placeholder_thumbnail_reason(url))


def _infer_author(name: str, author_url: str) -> str:
    match = _AUTHOR_BY_RE.search(name)
    if match:
        author = match.group(1).strip()
        if author:
            return author

    match = _GBATEMP_MEMBER_RE.search(author_url)
    if match:
        author = match.group(1).strip()
        prefix_match = re.match(r"^\s*(.+?)\s+[–—]\s+", name)
        if prefix_match:
            prefix = prefix_match.group(1).strip()
            if prefix and _normalise_author_token(prefix) == _normalise_author_token(author):
                return prefix
        return author

    return ""


def _placeholder_author(author: str) -> str:
    return _PLACEHOLDER_AUTHORS.get(author.strip().casefold(), "")


def _validate_and_fill(entry: dict, type_str: str, source_file: Path) -> dict:
    """Validate *entry* from *source_file*, inject *type_str*, fill defaults.

    Raises ``ValueError`` on schema violations so bad entries are caught
    early rather than causing mysterious runtime errors.
    """
    entry = dict(entry)  # shallow copy — don't mutate the caller's dict

    # Normalise common text fields before validation so user catalogue files
    # can recover from stray whitespace and older naming conventions.
    for field in (
        "id",
        "name",
        "description",
        "author",
        "url",
        "game",
        "game_serial",
        "context",
        "author_url",
        "thumbnail_url",
        "download_action",
        "direct_download_url",
        "upscale_tech",
        "size_label",
    ):
        if isinstance(entry.get(field), str):
            entry[field] = entry[field].strip()

    for field in (
        "id",
        "name",
        "description",
        "author",
        "url",
        "source_url",
        "source",
        "game",
        "game_serial",
        "context",
        "author_url",
        "thumbnail_url",
        "download_action",
        "direct_download_url",
        "upscale_tech",
        "size_label",
    ):
        if field in entry and entry[field] is not None and not isinstance(entry[field], str):
            raise ValueError(
                f"[{source_file.name}] entry {entry.get('id', '?')!r}: "
                f"{field!r} must be a string"
            )

    if not entry.get("url") and isinstance(entry.get("source_url"), str) and entry["source_url"]:
        log.warning(
            "[%s] entry %r: url missing; using source_url as a fallback",
            source_file.name,
            entry.get("id", "?"),
        )
        entry["url"] = entry["source_url"]

    for field in ("url", "author_url", "thumbnail_url", "source_url"):
        if isinstance(entry.get(field), str):
            entry[field] = _normalise_url(entry[field])
    if isinstance(entry.get("thumbnail_url"), str) and _is_placeholder_thumbnail_url(entry["thumbnail_url"]):
        # Generic placeholder images are not useful cover art and only add
        # noise when the game-specific cover lookup fails, so treat them as absent.
        reason = _placeholder_thumbnail_reason(entry["thumbnail_url"])
        log.warning(
            "[%s] entry %r: thumbnail_url uses a %s; clearing it",
            source_file.name,
            entry.get("id", "?"),
            reason or "generic placeholder",
        )
        entry["thumbnail_url"] = ""
    if isinstance(entry.get("direct_download_url"), str):
        # Preserve fragments for hosts such as MEGA where the file key lives in
        # the URL fragment and is required for the link to keep working.
        entry["direct_download_url"] = _normalise_url(
            entry["direct_download_url"],
            preserve_fragment=True,
        )
    for field in ("url", "author_url", "thumbnail_url", "direct_download_url", "source_url"):
        value = entry.get(field, "")
        if value and isinstance(value, str):
            lowered = value.lower()
            if not lowered.startswith(("http://", "https://")):
                raise ValueError(
                    f"[{source_file.name}] entry {entry.get('id', '?')!r}: "
                    f"{field!r} must be an http(s) URL"
                )
    if isinstance(entry.get("game_serial"), str):
        from src.core.game_registry import is_valid_serial, normalise_serial
        entry["game_serial"] = normalise_serial(entry["game_serial"])
        if entry["game_serial"] and not is_valid_serial(entry["game_serial"]):
            raise ValueError(
                f"[{source_file.name}] entry {entry.get('id', '?')!r}: "
                f"invalid game_serial {entry['game_serial']!r}"
            )
    if isinstance(entry.get("download_action"), str):
        entry["download_action"] = entry["download_action"].lower()
        if entry["download_action"] not in VALID_DOWNLOAD_ACTIONS:
            raise ValueError(
                f"[{source_file.name}] entry {entry.get('id', '?')!r}: "
                f"unknown download_action {entry['download_action']!r}"
            )
    if isinstance(entry.get("source"), str):
        raw_source = entry["source"]
        normalised_source = _normalise_source(raw_source)
        if raw_source and normalised_source != raw_source:
            log.warning(
                "[%s] entry %r: source %r normalized to %r",
                source_file.name,
                entry.get("id", "?"),
                raw_source,
                normalised_source,
            )
        entry["source"] = normalised_source
    if isinstance(entry.get("tags"), list):
        entry["tags"] = [tag.strip() for tag in entry["tags"] if isinstance(tag, str) and tag.strip()]
    author = entry.get("author", "")
    if isinstance(author, str):
        author = author.strip()
    else:
        author = ""
    placeholder_author = _placeholder_author(author) if author else ""
    is_hub = bool(entry.get("is_hub", False))
    if placeholder_author:
        author = ""
    if not author:
        author = _infer_author(
            entry.get("name", ""),
            entry.get("author_url", ""),
        )
        if not author and not is_hub:
            author = placeholder_author
    entry["author"] = author
    type_str = _normalise_mod_type(type_str)

    # Inject type from the file name as a ModType enum (callers do not need
    # to repeat it in every record, and the UI compares against enum values).
    try:
        entry["type"] = ModType(type_str)
    except ValueError:
        raise ValueError(
            f"[{source_file.name}] unknown mod type {type_str!r}"
        )

    # Check required fields
    for field in _REQUIRED_FIELDS:
        if field not in entry:
            raise ValueError(
                f"[{source_file.name}] entry {entry.get('id', '?')!r} "
                f"is missing required field {field!r}"
            )

    # Fill optional fields with defaults
    for field, default in _OPTIONAL_DEFAULTS.items():
        if field not in entry:
            entry[field] = _clone_default(default)

    # Basic type checks on critical fields
    if not entry["id"].strip():
        raise ValueError(
            f"[{source_file.name}] 'id' must be a non-empty string; "
            f"got {entry['id']!r}"
        )
    if not entry["name"].strip():
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'name' must be a non-empty string"
        )
    if not entry["description"].strip():
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'description' must be a non-empty string"
        )
    if not entry["url"].strip():
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'url' must be a non-empty string"
        )
    if not entry["source"].strip():
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'source' must be a non-empty string"
        )
    if not entry["author"].strip() and not entry.get("is_hub", False):
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'author' must be a non-empty string for non-hub entries"
        )
    if not isinstance(entry.get("tags", []), list):
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: 'tags' must be a list"
        )
    for flag in ("is_hub", "nsfw", "is_free", "requires_account", "is_complete"):
        if not isinstance(entry.get(flag, False), bool):
            raise ValueError(
                f"[{source_file.name}] entry {entry['id']!r}: "
                f"'{flag}' must be a bool"
            )
    if not isinstance(entry.get("download_action", ""), str):
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'download_action' must be a string"
        )

    return entry


def _load_from_dir(
    base: Path,
    type_files: Optional[Dict[str, str]],
    entries: List[dict],
    seen_entries: Dict[str, dict],
    *,
    strict: bool = False,
) -> None:
    """Internal helper: read catalogue JSON files from *base* into *entries*.

    When *type_files* is provided, only those filenames are read (each mapped
    to a fixed mod type string).  When *type_files* is ``None``, every
    ``*.json`` file in *base* is read and the ``"type"`` field is taken from
    each entry dict (required in that case).
    """
    if type_files is not None:
        # Built-in catalogue: filename → type_str mapping
        file_iter = [(filename, type_str) for type_str, filename in type_files.items()]
    else:
        # User catalogue: each .json file may contain mixed types
        try:
            json_files = [
                path
                for path in sorted(base.glob("*.json"))
                # Ignore helper manifests like _index.json; only actual entry files belong here.
                if not path.name.startswith("_")
            ]
        except Exception as exc:
            log.warning("Could not list catalogue files under %s: %s", base, exc)
            json_files = []
        file_iter = [(f.name, None) for f in json_files]

    for filename, fixed_type_str in file_iter:
        path = base / filename
        if not path.exists():
            log.debug("Catalogue file not found, skipping: %s", path)
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            msg = f"Failed to read catalogue file {path}: {exc}"
            if strict:
                raise ValueError(msg) from exc
            log.warning(msg)
            continue

        try:
            raw: List[dict] = json.loads(text)
        except json.JSONDecodeError as exc:
            msg = f"Failed to parse catalogue file {path}: {exc}"
            if strict:
                raise ValueError(msg) from exc
            log.warning(msg)
            continue

        if not isinstance(raw, list):
            msg = f"Catalogue file {path} must contain a JSON array at the top level"
            if strict:
                raise ValueError(msg)
            log.warning(msg)
            continue

        for item in raw:
            if not isinstance(item, dict):
                log.warning("Skipping non-dict item in %s: %r", path.name, item)
                continue

            # Determine mod type
            type_str = fixed_type_str
            if type_str is None:
                # User catalogue: type must come from the entry itself
                type_str = item.get("type", "")
                if not type_str:
                    log.warning(
                        "Skipping entry in %s: missing 'type' field — %r",
                        path.name, item.get("id", "?"),
                    )
                    continue

            try:
                entry = _validate_and_fill(item, type_str, path)
            except ValueError as exc:
                if strict:
                    raise
                log.warning("Skipping invalid entry in %s: %s", path.name, exc)
                continue

            eid = entry["id"]
            if eid in seen_entries:
                msg = f"Duplicate catalogue ID {eid!r} found in {path.name}"
                existing = seen_entries[eid]
                differing_fields = sorted(
                    field for field in set(existing) | set(entry)
                    if existing.get(field) != entry.get(field)
                )
                if differing_fields:
                    preview = ", ".join(differing_fields[:8])
                    if len(differing_fields) > 8:
                        preview += ", ..."
                    msg += f" — fields differ: {preview}"
                if strict:
                    raise ValueError(msg)
                log.warning(msg + " — keeping first occurrence")
                continue

            seen_entries[eid] = entry
            entries.append(entry)


def load_catalogue(
    catalogue_dir: Optional[Path] = None,
    *,
    strict: bool = False,
    user_catalogue_dir: Optional[Path] = None,
) -> List[dict]:
    """Load and return all catalogue entries from *catalogue_dir*.

    Parameters
    ----------
    catalogue_dir:
        Override the default ``data/catalogue/`` directory.  Useful in tests.
    strict:
        When *True*, any schema violation (missing required field, duplicate ID,
        unparseable JSON) raises ``ValueError`` immediately and stops loading.
        When *False* (the default), bad entries or unreadable files are logged
        via the module logger and skipped so the rest of the catalogue still
        loads.
    user_catalogue_dir:
        Override the user catalogue directory.  When ``None`` the default
        ``user_catalogue/`` folder next to the exe is used (via
        :func:`~src.core.config_manager.get_user_catalogue_dir`).  Pass an
        explicit :class:`~pathlib.Path` to disable auto-detection (useful in
        tests that do not want side-effects from the config manager).

    Returns
    -------
    list[dict]
        Entries across all type files, in the order defined by
        :data:`_TYPE_FILES`, followed by any user catalogue entries.
        Each entry dict always contains every field listed in
        :data:`_REQUIRED_FIELDS` and :data:`_OPTIONAL_DEFAULTS`,
        plus the ``type`` key injected from the file name.
    """
    base = Path(catalogue_dir) if catalogue_dir else CATALOGUE_DIR
    entries: List[dict] = []
    seen_entries: dict[str, dict] = {}

    # 1. Load built-in catalogue files
    _load_from_dir(base, _TYPE_FILES, entries, seen_entries, strict=strict)

    # 2. Load user catalogue files (next to exe)
    if user_catalogue_dir is not False:  # False means "skip entirely" (tests)
        if user_catalogue_dir is None:
            try:
                from src.core.config_manager import get_user_catalogue_dir
                user_catalogue_dir = get_user_catalogue_dir()
            except Exception as exc:
                log.warning("Could not resolve user catalogue directory: %s", exc)
                user_catalogue_dir = None

        if user_catalogue_dir is not None:
            _load_from_dir(
                Path(user_catalogue_dir),
                None,  # type comes from each entry
                entries,
                seen_entries,
                strict=False,  # user files never cause strict failures
            )

    return entries


def load_user_catalogue(
    user_catalogue_dir: Optional[Path] = None,
    *,
    strict: bool = False,
) -> List[dict]:
    """Load and return entries from the user catalogue directory only.

    Parameters
    ----------
    user_catalogue_dir:
        Path to the directory containing user JSON files.  When ``None`` the
        default ``user_catalogue/`` folder next to the exe is used.
    strict:
        When *True* bad entries raise :exc:`ValueError`.  Defaults to
        *False*.

    Returns
    -------
    list[dict]
        Validated entries from all ``*.json`` files in the directory.
    """
    if user_catalogue_dir is None:
        from src.core.config_manager import get_user_catalogue_dir
        user_catalogue_dir = get_user_catalogue_dir()

    entries: List[dict] = []
    seen_entries: dict[str, dict] = {}
    _load_from_dir(
        Path(user_catalogue_dir),
        None,
        entries,
        seen_entries,
        strict=strict,
    )
    return entries


# ---------------------------------------------------------------------------
# Module-level singletons (loaded once at import time)
# ---------------------------------------------------------------------------

#: All catalogue entries.  Import this directly in the Browse panel instead of
#: the old hard-coded list.
CATALOGUE: List[dict] = load_catalogue()

#: Sorted list of unique source strings for the filter dropdown.
ALL_SOURCES: List[str] = sorted({e["source"] for e in CATALOGUE})
