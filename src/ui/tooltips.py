"""Tooltip text for PS2 Mod Manager UI elements.

Issue #31: The user can choose between three tooltip modes in Settings:
  * ``normal``      — clear, helpful tips.
  * ``dumbed_down`` — simplified language with a bit of personality.
  * ``no_filter``   — direct/blunt but always useful.

Call :func:`get_tip` anywhere in the UI to retrieve the correct tooltip for
the current mode.  Pass ``config.tooltip_mode`` (or ``"normal"`` as default)
as *mode*.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tip dictionary  — key → {mode: text}
# Every key must define all three modes.
# ---------------------------------------------------------------------------

_TIPS: dict[str, dict[str, str]] = {
    # ── Mod item: enable/disable toggle ────────────────────────────────────
    "toggle": {
        "normal": (
            "Toggle this mod on or off.\n"
            "When enabled the mod is deployed to your PCSX2 folder automatically."
        ),
        "dumbed_down": (
            "Click this to turn the mod on or off.\n"
            "On = it's in PCSX2.  Off = it's out.  Simple!"
        ),
        "no_filter": (
            "Flip this switch to enable or disable the mod.\n"
            "Enabled mods get copied to PCSX2 — disabled ones stay out."
        ),
    },

    # ── Mod item: remove/delete ─────────────────────────────────────────────
    "remove": {
        "normal": (
            "Remove this mod from the manager.\n"
            "The original files are deleted from your mod storage folder."
        ),
        "dumbed_down": (
            "Nuke this mod. Gone. Bye bye.\n"
            "This removes it from the manager AND deletes the files."
        ),
        "no_filter": (
            "Permanently delete this mod.\n"
            "Wipes the files from your storage folder — there's no undo."
        ),
    },

    # ── Mod item: priority up ───────────────────────────────────────────────
    "priority_up": {
        "normal": (
            "Increase priority — this mod's files will win\n"
            "over lower-priority mods when both are enabled."
        ),
        "dumbed_down": (
            "Move this mod up the pecking order.\n"
            "Higher priority = this mod's textures show up instead of the other one's."
        ),
        "no_filter": (
            "Bump priority up — this mod beats the ones below it in a conflict.\n"
            "Higher number wins."
        ),
    },

    # ── Mod item: priority down ─────────────────────────────────────────────
    "priority_down": {
        "normal": "Decrease priority — lower-priority mods are overridden by higher-priority ones.",
        "dumbed_down": "Shove this mod down the queue.  Lower = loses to higher mods.",
        "no_filter": "Drop priority — this mod loses to anything ranked higher.",
    },

    # ── Mod item: details (ℹ button) ────────────────────────────────────────
    "details": {
        "normal": "View full details for this mod: files, source URL, description, and quick-navigation links.",
        "dumbed_down": "Tap here to see everything about this mod — files, where it came from, all that.",
        "no_filter": "Open the mod's detail view — files, source, the whole picture.",
    },

    # ── Mod item: edit metadata (✏ button) ──────────────────────────────────
    "edit": {
        "normal": "Edit this mod's metadata: name, author, version, game ID, description, and source URL.",
        "dumbed_down": "Change the mod's name/author/description etc.  Purely cosmetic — doesn't move any files.",
        "no_filter": "Edit the mod's info fields (name, author, etc.).  Nothing moves on disk.",
    },

    # ── Mod item: author filter (👤 button) ─────────────────────────────────
    "author_filter": {
        "normal": "Filter this panel to show only mods by this author.",
        "dumbed_down": "Show only mods from this person.  Click again (or clear) to see all mods.",
        "no_filter": "Filter by this author — tap again to clear the filter.",
    },

    # ── Mod panel: Import button ────────────────────────────────────────────
    "import": {
        "normal": (
            "Import a mod file from your computer.\n"
            "Supports ZIP, 7z, RAR archives, PNACH files, images, and save files."
        ),
        "dumbed_down": (
            "Add a mod you already downloaded.\n"
            "Pick a ZIP, 7z, PNACH, or image file and the app does the rest."
        ),
        "no_filter": (
            "Import a mod from disk — ZIP/7z/RAR, PNACH, image, save, you name it.\n"
            "Drag it in or browse."
        ),
    },

    # ── Mod panel: Conflicts button ─────────────────────────────────────────
    "conflicts": {
        "normal": (
            "Show and resolve conflicts between your enabled mods.\n"
            "Conflicts occur when two mods replace the same file or PNACH address."
        ),
        "dumbed_down": (
            "Some of your mods are fighting over the same files.\n"
            "Click here to see what's clashing and pick a winner."
        ),
        "no_filter": (
            "Open the conflict resolver.\n"
            "Two mods want the same files — you decide who wins."
        ),
    },

    # ── Mod panel: Enable All ───────────────────────────────────────────────
    "enable_all": {
        "normal": "Enable all mods in the current list at once.",
        "dumbed_down": "Turn everything on.  May cause conflicts if packs overlap!",
        "no_filter": "Enable all mods.  Watch out for conflicts if you stack incompatible packs.",
    },

    # ── Mod panel: Disable All ──────────────────────────────────────────────
    "disable_all": {
        "normal": "Disable all mods in the current list at once.",
        "dumbed_down": "Turn everything off.  Safe to do any time.",
        "no_filter": "Disable all mods — undeploys everything from PCSX2.",
    },

    # ── Mod panel: My Library Only ──────────────────────────────────────────
    "library_only": {
        "normal": (
            "Show only mods whose game serial matches a disc image\n"
            "in your Game Library folder (configure in Settings)."
        ),
        "dumbed_down": (
            "Only show mods for games you actually own.\n"
            "Set your game folder in Settings to make this work."
        ),
        "no_filter": (
            "Filter to mods matching games in your library folder.\n"
            "Useless if you haven't set a library path in Settings."
        ),
    },

    # ── Import dialog: mod type selector ───────────────────────────────────
    "mod_type": {
        "normal": "Select the type of mod you are importing so it is stored and deployed correctly.",
        "dumbed_down": "Pick what kind of mod this is.  Wrong type = wrong folder = won't work in PCSX2.",
        "no_filter": "Pick the mod type.  Get it wrong and PCSX2 won't see it.",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_tip(key: str, mode: str = "normal") -> str:
    """Return the tooltip text for *key* in the given *mode*.

    Falls back to ``"normal"`` if *mode* is not recognised, and to an empty
    string if *key* is not found.
    """
    entry = _TIPS.get(key)
    if not entry:
        return ""
    if mode not in entry:
        mode = "normal"
    return entry[mode]
