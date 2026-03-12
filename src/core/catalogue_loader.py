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
from pathlib import Path
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
}


def _validate_and_fill(entry: dict, type_str: str, source_file: Path) -> dict:
    """Validate *entry* from *source_file*, inject *type_str*, fill defaults.

    Raises ``ValueError`` on schema violations so bad entries are caught
    early rather than causing mysterious runtime errors.
    """
    entry = dict(entry)  # shallow copy — don't mutate the caller's dict

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
            entry[field] = default

    # Basic type checks on critical fields
    if not isinstance(entry["id"], str) or not entry["id"]:
        raise ValueError(
            f"[{source_file.name}] 'id' must be a non-empty string; "
            f"got {entry['id']!r}"
        )
    if not isinstance(entry["name"], str) or not entry["name"]:
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'name' must be a non-empty string"
        )
    if not isinstance(entry.get("tags", []), list):
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: 'tags' must be a list"
        )
    if not isinstance(entry.get("is_hub", False), bool):
        raise ValueError(
            f"[{source_file.name}] entry {entry['id']!r}: "
            f"'is_hub' must be a bool"
        )

    return entry


def _load_from_dir(
    base: Path,
    type_files: Optional[Dict[str, str]],
    entries: List[dict],
    seen_ids: set,
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
            json_files = sorted(base.glob("*.json"))
        except Exception:
            json_files = []
        file_iter = [(f.name, None) for f in json_files]

    for filename, fixed_type_str in file_iter:
        path = base / filename
        if not path.exists():
            log.debug("Catalogue file not found, skipping: %s", path)
            continue

        try:
            raw: List[dict] = json.loads(path.read_text(encoding="utf-8"))
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
            if eid in seen_ids:
                msg = f"Duplicate catalogue ID {eid!r} found in {path.name}"
                if strict:
                    raise ValueError(msg)
                log.warning(msg + " — keeping first occurrence")
                continue

            seen_ids.add(eid)
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
        When *False* (the default), bad entries are logged via the module
        logger and silently skipped so the rest of the catalogue still loads.
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
    seen_ids: set = set()

    # 1. Load built-in catalogue files
    _load_from_dir(base, _TYPE_FILES, entries, seen_ids, strict=strict)

    # 2. Load user catalogue files (next to exe)
    if user_catalogue_dir is not False:  # False means "skip entirely" (tests)
        if user_catalogue_dir is None:
            try:
                from src.core.config_manager import get_user_catalogue_dir
                user_catalogue_dir = get_user_catalogue_dir()
            except Exception as exc:
                log.debug("Could not resolve user_catalogue_dir: %s", exc)
                user_catalogue_dir = None

        if user_catalogue_dir is not None:
            _load_from_dir(
                Path(user_catalogue_dir),
                None,  # type comes from each entry
                entries,
                seen_ids,
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
    seen_ids: set = set()
    _load_from_dir(
        Path(user_catalogue_dir),
        None,
        entries,
        seen_ids,
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
