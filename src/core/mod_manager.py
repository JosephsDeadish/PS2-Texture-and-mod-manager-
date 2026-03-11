"""Mod database and management logic for PS2 Mod Manager."""

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import src.core.config_manager as _cfg
from src.models.mod import ConflictInfo, ModInfo, ModStatus, ModType


class ModDatabase:
    """Persistent mod database backed by JSON."""

    def __init__(self):
        _cfg.ensure_dirs()
        self._mods: Dict[str, ModInfo] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        db_file = _cfg.MODS_DB_FILE
        if db_file.exists():
            try:
                with open(db_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._mods = {k: ModInfo.from_dict(v) for k, v in raw.items()}
            except (json.JSONDecodeError, KeyError, TypeError):
                self._mods = {}

    def save(self):
        db_file = _cfg.MODS_DB_FILE
        db_file.parent.mkdir(parents=True, exist_ok=True)
        with open(db_file, "w", encoding="utf-8") as f:
            json.dump({k: v.to_dict() for k, v in self._mods.items()}, f, indent=2)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, mod: ModInfo):
        self._mods[mod.id] = mod
        self.save()

    def remove(self, mod_id: str):
        self._mods.pop(mod_id, None)
        self.save()

    def get(self, mod_id: str) -> Optional[ModInfo]:
        return self._mods.get(mod_id)

    def all(self) -> List[ModInfo]:
        return list(self._mods.values())

    def by_type(self, mod_type: ModType) -> List[ModInfo]:
        return [m for m in self._mods.values() if m.mod_type == mod_type]

    def update(self, mod: ModInfo):
        self._mods[mod.id] = mod
        self.save()


class ModManager:
    """High-level mod management operations."""

    def __init__(self, db: ModDatabase):
        self.db = db

    # ------------------------------------------------------------------
    # Install / Remove
    # ------------------------------------------------------------------

    def install_from_folder(
        self,
        source_path: str,
        mod_type: ModType,
        dest_base: str,
        name: str = "",
        author: str = "",
        description: str = "",
        game_id: str = "",
        source_url: str = "",
    ) -> ModInfo:
        """
        Copy a folder or file into managed storage and register it as a mod.

        If *source_path* is a directory it is copied recursively using
        dirs_exist_ok=True, meaning any pre-existing files at the destination
        will be overwritten by source files.  This is intentional: the dest
        directory is a freshly-created UUID-named folder under *dest_base* so
        overwriting only occurs on re-import of the same physical files.
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source path not found: {source_path}")

        mod_id = str(uuid.uuid4())
        dest_dir = Path(dest_base) / mod_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        if source.is_dir():
            shutil.copytree(str(source), str(dest_dir), dirs_exist_ok=True)
        else:
            shutil.copy2(str(source), str(dest_dir / source.name))

        files = self._list_files(dest_dir)
        size = sum(f.stat().st_size for f in dest_dir.rglob("*") if f.is_file())

        mod = ModInfo(
            id=mod_id,
            name=name or source.name,
            mod_type=mod_type,
            path=str(dest_dir),
            enabled=True,
            author=author,
            description=description,
            game_id=game_id,
            source_url=source_url,
            files=files,
            size_bytes=size,
        )
        self.db.add(mod)
        return mod

    def remove_mod(self, mod_id: str, delete_files: bool = True):
        """Remove a mod from the database and optionally delete its files."""
        mod = self.db.get(mod_id)
        if mod and delete_files and Path(mod.path).exists():
            shutil.rmtree(mod.path, ignore_errors=True)
        self.db.remove(mod_id)

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    def set_enabled(self, mod_id: str, enabled: bool):
        mod = self.db.get(mod_id)
        if mod:
            mod.enabled = enabled
            self.db.update(mod)

    def set_priority(self, mod_id: str, priority: int):
        mod = self.db.get(mod_id)
        if mod:
            mod.priority = priority
            self.db.update(mod)

    # ------------------------------------------------------------------
    # Apply mods (deploy to PCSX2 folders)
    # ------------------------------------------------------------------

    def deploy(self, mod_type: ModType, target_path: str) -> Tuple[int, List[str]]:
        """
        Copy enabled mods of *mod_type* into *target_path* in priority order.
        Returns (count_deployed, warnings).
        """
        target = Path(target_path)
        target.mkdir(parents=True, exist_ok=True)

        mods = sorted(
            [m for m in self.db.by_type(mod_type) if m.enabled],
            key=lambda m: m.priority,
            reverse=True,
        )

        deployed = 0
        warnings: List[str] = []

        for mod in mods:
            src = Path(mod.path)
            if not src.exists():
                warnings.append(f"Missing path for mod '{mod.name}': {mod.path}")
                continue
            if src.is_dir():
                shutil.copytree(str(src), str(target), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src), str(target / src.name))
            deployed += 1

        return deployed, warnings

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def detect_conflicts(self, mod_type: Optional[ModType] = None) -> List[ConflictInfo]:
        """Detect file-level conflicts between enabled mods."""
        mods = self.db.by_type(mod_type) if mod_type else self.db.all()
        enabled = [m for m in mods if m.enabled]

        file_owners: Dict[str, List[str]] = {}
        for mod in enabled:
            for rel_path in mod.files:
                file_owners.setdefault(rel_path, []).append(mod.id)

        conflicts: List[ConflictInfo] = []
        seen = set()

        for rel_path, owners in file_owners.items():
            if len(owners) > 1:
                for i in range(len(owners)):
                    for j in range(i + 1, len(owners)):
                        pair = tuple(sorted([owners[i], owners[j]]))
                        if pair not in seen:
                            seen.add(pair)
                            conflicts.append(
                                ConflictInfo(
                                    mod_a_id=pair[0],
                                    mod_b_id=pair[1],
                                    conflicting_files=[rel_path],
                                )
                            )
                        else:
                            for c in conflicts:
                                if c.mod_a_id == pair[0] and c.mod_b_id == pair[1]:
                                    c.conflicting_files.append(rel_path)

        return conflicts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _list_files(directory: Path) -> List[str]:
        """Return relative file paths inside *directory*."""
        result = []
        if directory.is_dir():
            for f in directory.rglob("*"):
                if f.is_file():
                    result.append(str(f.relative_to(directory)))
        return result

    @staticmethod
    def file_hash(path: str) -> str:
        """SHA-256 hash of a file (first 64KB for performance)."""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                h.update(f.read(65536))
        except OSError:
            pass
        return h.hexdigest()
