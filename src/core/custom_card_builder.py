"""Custom catalogue card builder for PS2 Mod Manager.

This module provides the logic to create, validate, and persist user-defined
catalogue entries (cards) for content that was not installed through the mod
manager — for example, a texture pack the user downloaded manually.

Entries created here are written to the ``user_catalogue/`` directory next to
the application executable.  They are automatically merged with the built-in
catalogue at load time by :func:`src.core.catalogue_loader.load_catalogue`.

Usage::

    from src.core.custom_card_builder import build_entry, save_entry

    entry = build_entry(
        mod_type="texture_pack",
        name="My Sly 2 HD Pack",
        game="Sly 2: Band of Thieves",
        game_serial="SCUS-97264",
        author="Me",
        url="",
        description="Personal HD texture pack",
        source="Personal",
    )
    save_entry(entry)          # writes to user_catalogue/ next to exe
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def generate_id(name: str, game_serial: str) -> str:
    """Generate a short unique ID string for a catalogue entry.

    The ID is built from a slugified *name* + *game_serial* + a short random
    hex suffix to avoid collisions between similarly-named user packs.

    Parameters
    ----------
    name:
        Display name of the entry.
    game_serial:
        PS2 disc serial (e.g. ``"SCUS-97264"``).

    Returns
    -------
    str
        A URL-safe, lower-case, hyphen-separated string suitable for use as
        a catalogue entry ``id`` field.
    """
    slug_name   = _SLUG_RE.sub('-', name.lower()).strip('-')[:32]
    slug_serial = game_serial.lower().replace(' ', '')
    suffix      = uuid.uuid4().hex[:6]
    parts = [p for p in [slug_name, slug_serial, suffix] if p]
    return '-'.join(parts) or f"user-{suffix}"


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------

#: Valid mod-type strings accepted by build_entry()
VALID_MOD_TYPES = frozenset({
    "texture_pack",
    "pnach",
    "save_file",
    "cheat",
    "cover_art",
})


def build_entry(
    mod_type: str,
    name: str,
    game: str,
    game_serial: str,
    author: str,
    url: str,
    description: str,
    source: str = "Personal",
    *,
    size_label: str = "",
    context: str = "",
    author_url: str = "",
    thumbnail_url: str = "",
    tags: Optional[list] = None,
    is_free: bool = True,
    is_complete: bool = True,
    entry_id: Optional[str] = None,
) -> dict:
    """Build and validate a catalogue entry dict for a user-created card.

    Parameters
    ----------
    mod_type:
        One of ``"texture_pack"``, ``"pnach"``, ``"save_file"``,
        ``"cheat"``, ``"cover_art"``.
    name:
        Display name shown in the UI.
    game:
        Full game title (e.g. ``"Sly 2: Band of Thieves"``).
    game_serial:
        PS2 disc serial (e.g. ``"SCUS-97264"``).
    author:
        Creator / uploader name.
    url:
        Link to mod page or download.  May be empty for personal packs.
    description:
        Short description shown in the UI.
    source:
        Source label (e.g. ``"Personal"``, ``"GameFront"``).  Defaults to
        ``"Personal"`` for user-created cards.
    size_label:
        Human-readable size string (e.g. ``"~250 MB"``).  Optional.
    context:
        Extra context text displayed in the card.  Optional.
    author_url:
        Link to author's profile or page.  Optional.
    thumbnail_url:
        URL of a thumbnail image.  Optional.
    tags:
        List of tag strings.  Defaults to ``[]``.
    is_free:
        Whether the content is free.  Defaults to ``True``.
    is_complete:
        Whether the content is a complete / released pack.  Defaults to
        ``True``.
    entry_id:
        Override the auto-generated ID.  Must be a non-empty string if given.

    Returns
    -------
    dict
        A fully validated catalogue entry dict ready to be passed to
        :func:`save_entry` or directly appended to a user catalogue JSON file.

    Raises
    ------
    ValueError
        If any required field is invalid.
    """
    # Normalise
    mod_type     = mod_type.strip().lower()
    name         = name.strip()
    game         = game.strip()
    game_serial  = game_serial.strip().upper()
    author       = author.strip()
    description  = description.strip()
    source       = source.strip() or "Personal"

    # Validate mod_type
    if mod_type not in VALID_MOD_TYPES:
        raise ValueError(
            f"mod_type must be one of {sorted(VALID_MOD_TYPES)!r}, got {mod_type!r}"
        )
    # Required string fields
    if not name:
        raise ValueError("'name' must not be empty")
    if not game:
        raise ValueError("'game' must not be empty")
    if not game_serial:
        raise ValueError("'game_serial' must not be empty")

    # ID
    eid = (entry_id or "").strip()
    if not eid:
        eid = generate_id(name, game_serial)

    entry: dict = {
        "id":           eid,
        "type":         mod_type,
        "name":         name,
        "game":         game,
        "game_serial":  game_serial,
        "author":       author,
        "url":          url or "",
        "source":       source,
        "description":  description,
        "size_label":   size_label or "",
        "context":      context or "",
        "author_url":   author_url or "",
        "thumbnail_url": thumbnail_url or "",
        "tags":         list(tags) if tags else [],
        "is_free":      bool(is_free),
        "is_complete":  bool(is_complete),
        "is_hub":       False,
        "nsfw":         False,
        "requires_account": False,
        "download_action":  "",
        "direct_download_url": "",
        "upscale_tech":     "",
    }
    return entry


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_entry(
    entry: dict,
    user_catalogue_dir: Optional[Path] = None,
    filename: str = "my_cards.json",
) -> Path:
    """Append *entry* to a JSON file inside *user_catalogue_dir*.

    If the JSON file already exists it is read, *entry* is appended (duplicate
    IDs are skipped with a warning), and the file is rewritten atomically.
    If the file does not exist it is created with *entry* as the sole element.

    Parameters
    ----------
    entry:
        A catalogue entry dict as returned by :func:`build_entry`.
    user_catalogue_dir:
        Directory to write to.  When ``None`` the default
        ``user_catalogue/`` folder next to the exe is used (via
        :func:`~src.core.config_manager.get_user_catalogue_dir`).
    filename:
        Name of the JSON file to write/append to.  Defaults to
        ``"my_cards.json"``.

    Returns
    -------
    Path
        Path to the JSON file that was written.

    Raises
    ------
    ValueError
        If *entry* has no ``"id"`` field or the dict is not serialisable.
    """
    if not entry.get("id"):
        raise ValueError("entry must have a non-empty 'id' field")

    if user_catalogue_dir is None:
        from src.core.config_manager import get_user_catalogue_dir
        user_catalogue_dir = get_user_catalogue_dir()

    user_catalogue_dir = Path(user_catalogue_dir)
    user_catalogue_dir.mkdir(parents=True, exist_ok=True)

    out_path = user_catalogue_dir / filename

    # Load existing entries
    existing: list = []
    if out_path.exists():
        try:
            raw = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                existing = raw
        except (json.JSONDecodeError, OSError):
            pass

    # Check for duplicate IDs
    existing_ids = {e.get("id") for e in existing if isinstance(e, dict)}
    if entry["id"] in existing_ids:
        # Generate a new unique ID to avoid the clash
        entry = dict(entry)
        entry["id"] = generate_id(entry.get("name", ""), entry.get("game_serial", ""))

    # Write a serialisable copy (strip non-JSON types like ModType enums)
    saveable = _make_serialisable(entry)
    existing.append(saveable)
    out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def _make_serialisable(entry: dict) -> dict:
    """Return a copy of *entry* where enum values are replaced by their string value."""
    result = {}
    for k, v in entry.items():
        # ModType enum → string
        if hasattr(v, "value") and hasattr(v, "name"):
            result[k] = v.value
        else:
            result[k] = v
    return result
