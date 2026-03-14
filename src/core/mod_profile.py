"""Mod Profiles for PS2 Mod Manager.

Allows users to save named mod configurations (profiles) and switch
between them instantly.  A profile captures which mods are enabled and
their load order for each game.

Example profiles::

    "Vanilla+"   — only bug-fix patches, no visual changes
    "HD Graphics" — all texture packs + widescreen PNACH enabled
    "Hardcore"   — gameplay-altering cheats + new character models

Persistence
-----------
Profiles are stored as JSON::

    {
      "version": 1,
      "active_profile": "HD Graphics",
      "profiles": {
        "Vanilla+": {
          "description": "Bug-fix patches only",
          "enabled_mods": ["uuid-pnach-bugfix"],
          "load_order": { "SLUS-20062": ["uuid-pnach-bugfix"] }
        },
        "HD Graphics": {
          "description": "All HD texture packs enabled",
          "enabled_mods": ["uuid-pack-hd-env", "uuid-pack-char"],
          "load_order": {
            "SLUS-20062": ["uuid-pack-hd-env", "uuid-pack-char"]
          }
        }
      }
    }

Public API::

    from src.core.mod_profile import ModProfileManager, ModProfile

    pm = ModProfileManager("/path/to/profiles.json")
    pm.create_profile("HD Graphics", description="All HD packs")
    pm.add_mod_to_profile("HD Graphics", "uuid-pack-hd-env")
    pm.set_active("HD Graphics")
    active = pm.get_active()
    pm.save()
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ModProfile:
    """A named collection of enabled mods with an optional load order.

    Attributes
    ----------
    name:
        Human-readable profile name (e.g. ``"HD Graphics"``).
    description:
        Optional short description shown in the UI.
    enabled_mods:
        List of mod UUIDs/IDs that are enabled in this profile.
    load_order:
        Per-serial load order: ``{serial: [pack_id, …]}``.
        Items are ordered from lowest priority (index 0) to highest.
    """

    name: str
    description: str = ""
    enabled_mods: List[str] = field(default_factory=list)
    load_order: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "enabled_mods": list(self.enabled_mods),
            "load_order": {k: list(v) for k, v in self.load_order.items()},
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "ModProfile":
        enabled = data.get("enabled_mods", [])
        if not isinstance(enabled, list):
            enabled = []
        lo = data.get("load_order", {})
        if not isinstance(lo, dict):
            lo = {}
        return cls(
            name=name,
            description=str(data.get("description", "")),
            enabled_mods=[str(x) for x in enabled],
            load_order={k: [str(x) for x in v] for k, v in lo.items()
                        if isinstance(v, list)},
        )

    def is_mod_enabled(self, mod_id: str) -> bool:
        """Return ``True`` if *mod_id* is part of this profile."""
        return mod_id in self.enabled_mods

    def add_mod(self, mod_id: str) -> bool:
        """Add *mod_id* to the profile's enabled list.

        Returns ``True`` if added, ``False`` if already present.
        """
        if mod_id not in self.enabled_mods:
            self.enabled_mods.append(mod_id)
            return True
        return False

    def remove_mod(self, mod_id: str) -> bool:
        """Remove *mod_id* from the profile.

        Returns ``True`` if removed.
        """
        if mod_id in self.enabled_mods:
            self.enabled_mods.remove(mod_id)
            # Also remove from any load orders
            for serial in list(self.load_order):
                lo = self.load_order[serial]
                if mod_id in lo:
                    lo.remove(mod_id)
                    if not lo:
                        del self.load_order[serial]
            return True
        return False

    def set_load_order(self, serial: str, order: List[str]) -> None:
        """Set the load order for *serial* within this profile."""
        seen: set = set()
        deduped: List[str] = []
        for item in order:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        self.load_order[serial] = deduped

    def get_load_order(self, serial: str) -> List[str]:
        """Return the load order for *serial* (copy, or ``[]`` if unset)."""
        return list(self.load_order.get(serial, []))


# ---------------------------------------------------------------------------
# Profile manager
# ---------------------------------------------------------------------------

class ModProfileManager:
    """Manages named mod profiles and the currently active one.

    Parameters
    ----------
    profiles_file:
        Path to the JSON persistence file.
    """

    _VERSION = 1

    def __init__(self, profiles_file: str) -> None:
        self._path = Path(profiles_file)
        self._profiles: Dict[str, ModProfile] = {}
        self._active: Optional[str] = None
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for pname, pdata in raw.get("profiles", {}).items():
                if isinstance(pdata, dict):
                    self._profiles[pname] = ModProfile.from_dict(pname, pdata)
            active = raw.get("active_profile")
            if active and active in self._profiles:
                self._active = active
        except (json.JSONDecodeError, TypeError):
            pass

    def save(self) -> None:
        """Persist all profiles to disk atomically."""
        payload = json.dumps({
            "version": self._VERSION,
            "active_profile": self._active or "",
            "profiles": {
                name: prof.to_dict()
                for name, prof in self._profiles.items()
            },
        }, indent=2)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".profiles_tmp_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, str(self._path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    def create_profile(
        self,
        name: str,
        description: str = "",
        enabled_mods: Optional[List[str]] = None,
    ) -> ModProfile:
        """Create a new empty profile.

        Parameters
        ----------
        name:
            Profile name.  Must be unique; raises ``ValueError`` if a
            profile with this name already exists.
        description:
            Short optional description.
        enabled_mods:
            Optional initial list of enabled mod IDs.

        Returns
        -------
        ModProfile
            The newly created profile.

        Raises
        ------
        ValueError
            If a profile named *name* already exists.
        """
        if name in self._profiles:
            raise ValueError(f"Profile already exists: {name!r}")
        profile = ModProfile(
            name=name,
            description=description,
            enabled_mods=list(enabled_mods or []),
        )
        self._profiles[name] = profile
        return profile

    def get_profile(self, name: str) -> Optional[ModProfile]:
        """Return the profile named *name*, or ``None``."""
        return self._profiles.get(name)

    def delete_profile(self, name: str) -> bool:
        """Delete the profile named *name*.

        Returns ``True`` if it existed and was removed.  If the deleted
        profile was active, the active profile is cleared.
        """
        if name not in self._profiles:
            return False
        del self._profiles[name]
        if self._active == name:
            self._active = None
        return True

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        """Rename a profile.

        Returns ``False`` if *old_name* does not exist or *new_name*
        already exists.
        """
        if old_name not in self._profiles:
            return False
        if new_name in self._profiles and new_name != old_name:
            return False
        profile = self._profiles.pop(old_name)
        profile.name = new_name
        self._profiles[new_name] = profile
        if self._active == old_name:
            self._active = new_name
        return True

    def list_profiles(self) -> List[str]:
        """Return a sorted list of all profile names."""
        return sorted(self._profiles.keys())

    def profile_count(self) -> int:
        """Return the total number of saved profiles."""
        return len(self._profiles)

    # ------------------------------------------------------------------
    # Active profile
    # ------------------------------------------------------------------

    def set_active(self, name: str) -> bool:
        """Set the active profile to *name*.

        Returns ``False`` if *name* does not exist.
        """
        if name not in self._profiles:
            return False
        self._active = name
        return True

    def get_active_name(self) -> Optional[str]:
        """Return the name of the currently active profile, or ``None``."""
        return self._active

    def get_active(self) -> Optional[ModProfile]:
        """Return the currently active :class:`ModProfile`, or ``None``."""
        if self._active:
            return self._profiles.get(self._active)
        return None

    def clear_active(self) -> None:
        """Deactivate the current profile (set active to ``None``)."""
        self._active = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def add_mod_to_profile(self, profile_name: str, mod_id: str) -> bool:
        """Add *mod_id* to the named profile.

        Returns ``False`` if the profile does not exist.
        """
        profile = self._profiles.get(profile_name)
        if profile is None:
            return False
        profile.add_mod(mod_id)
        return True

    def remove_mod_from_profile(self, profile_name: str, mod_id: str) -> bool:
        """Remove *mod_id* from the named profile.

        Returns ``False`` if the profile does not exist.
        """
        profile = self._profiles.get(profile_name)
        if profile is None:
            return False
        return profile.remove_mod(mod_id)

    def is_mod_in_active_profile(self, mod_id: str) -> bool:
        """Return ``True`` if *mod_id* is enabled in the active profile."""
        active = self.get_active()
        if active is None:
            return False
        return active.is_mod_enabled(mod_id)

    def duplicate_profile(self, source_name: str, new_name: str) -> Optional[ModProfile]:
        """Create a copy of *source_name* under *new_name*.

        Returns the new profile, or ``None`` if *source_name* does not
        exist or *new_name* already exists.
        """
        source = self._profiles.get(source_name)
        if source is None:
            return None
        if new_name in self._profiles:
            return None
        clone = ModProfile(
            name=new_name,
            description=source.description,
            enabled_mods=list(source.enabled_mods),
            load_order={k: list(v) for k, v in source.load_order.items()},
        )
        self._profiles[new_name] = clone
        return clone
