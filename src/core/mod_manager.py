"""Mod database and management logic for PS2 Mod Manager."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import src.core.config_manager as _cfg
from src.core.archive import ArchiveError, extract_archive, is_archive
from src.models.mod import ConflictInfo, ModInfo, ModStatus, ModType


# ---------------------------------------------------------------------------
# Texture pack folder-structure helpers
# ---------------------------------------------------------------------------

#: Matches a PS2 disc serial in any valid form, e.g. SLUS-20062, SLES-54053,
#: SCUS-97131 (2-4 uppercase letters, dash, 3-5 digits).
_PS2_SERIAL_RE = re.compile(r'^[A-Z]{2,4}-\d{3,5}$', re.IGNORECASE)


def _folder_has_serial_structure(folder: Path) -> bool:
    """Return True if *folder* contains any direct sub-directory named like a
    PS2 disc serial (e.g. ``SLUS-20062``).  These packs are already in the
    correct PCSX2 layout and need no further normalization."""
    try:
        return any(
            child.is_dir() and _PS2_SERIAL_RE.match(child.name) is not None
            for child in folder.iterdir()
        )
    except PermissionError:
        return False


def _atomic_json_write(path: Path, data) -> None:
    """Write *data* as JSON to *path* atomically.

    Writes to a sibling temporary file first, then replaces the target using
    :func:`os.replace` which is atomic on POSIX and best-effort on Windows.
    If writing fails the temporary file is removed and the exception is
    re-raised, leaving the original file intact.
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
                # Load entries individually so a single corrupt record does not
                # wipe the entire mod database.
                mods: Dict[str, ModInfo] = {}
                for k, v in raw.items():
                    try:
                        mods[k] = ModInfo.from_dict(v)
                    except (KeyError, TypeError, ValueError):
                        pass  # skip corrupt individual entries
                self._mods = mods
            except (json.JSONDecodeError, TypeError):
                self._mods = {}

    def save(self):
        db_file = _cfg.MODS_DB_FILE
        db_file.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self._mods.items()}
        _atomic_json_write(db_file, data)

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
    # Installed-content sync
    # ------------------------------------------------------------------

    def auto_import_unmanaged_content(self, config) -> int:
        """Import unmanaged installed PCSX2 content into the mod database.

        Returns the number of new items imported.
        """
        try:
            from src.core.config_manager import get_data_dir
            from src.core.installed_scanner import scan_all
            from src.core.game_registry import normalise_serial
        except Exception:
            return 0

        storage = (getattr(config, "mods_storage_path", "") or "").strip()
        if not storage:
            storage = str(get_data_dir() / "mods")
        Path(storage).mkdir(parents=True, exist_ok=True)

        unmanaged = scan_all(config)
        if not unmanaged:
            return 0

        crc_re = re.compile(r'^([0-9A-Fa-f]{8})\.pnach$')
        known_signatures: set[tuple[str, str]] = set()

        def _add_sig(kind: str, value: str):
            if kind and value:
                known_signatures.add((kind, value.upper()))

        # Build signatures from already tracked mods so we don't re-import.
        for mod in self.db.all():
            if mod.mod_type == ModType.TEXTURE_PACK:
                serial = normalise_serial(mod.game_id) if mod.game_id else ""
                if serial:
                    _add_sig("texture_pack", serial)
            elif mod.mod_type == ModType.COVER_ART:
                serial = normalise_serial(mod.game_id) if mod.game_id else ""
                if serial:
                    _add_sig("cover_art", serial)
            elif mod.mod_type in (ModType.PNACH, ModType.CHEAT):
                p = Path(mod.path)
                if p.is_file():
                    m = crc_re.match(p.name)
                    if m:
                        _add_sig(mod.mod_type.value, m.group(1))
                elif p.is_dir():
                    try:
                        for pf in p.rglob("*.pnach"):
                            m = crc_re.match(pf.name)
                            if m:
                                _add_sig(mod.mod_type.value, m.group(1))
                    except OSError:
                        pass

        imported = 0
        for item in unmanaged:
            if item.item_type == ModType.TEXTURE_PACK:
                serial = (item.serial or "").upper()
                sig = ("texture_pack", serial) if serial else ("texture_pack_path", str(item.path.resolve()).upper())
                name = f"{serial} Texture Pack (Detected)" if serial else f"{item.name} (Detected)"
            elif item.item_type == ModType.COVER_ART:
                serial = (item.serial or "").upper()
                sig = ("cover_art", serial) if serial else ("cover_art_path", str(item.path.resolve()).upper())
                name = f"{serial} Cover Art (Detected)" if serial else f"{item.name} (Detected)"
            elif item.item_type in (ModType.PNACH, ModType.CHEAT):
                crc = (item.crc or "").upper()
                sig = (item.item_type.value, crc) if crc else (f"{item.item_type.value}_path", str(item.path.resolve()).upper())
                name = f"{item.name} (Detected)"
            else:
                continue

            if sig in known_signatures:
                continue

            try:
                self.install_from_folder(
                    source_path=str(item.path),
                    mod_type=item.item_type,
                    dest_base=storage,
                    name=name,
                    author="Existing Installation",
                    description="Auto-detected from existing PCSX2 content.",
                    game_id=(item.serial or "").upper(),
                )
                known_signatures.add(sig)
                imported += 1
            except Exception:
                # Best-effort import — ignore individual failures.
                continue

        return imported

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
        version: str = "",
        description: str = "",
        game_id: str = "",
        source_url: str = "",
    ) -> ModInfo:
        """
        Copy a folder or file into managed storage and register it as a mod.

        Archive files (.zip, .7z) are extracted automatically; their contents
        land in the destination directory rather than the archive file itself.

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
        elif is_archive(str(source)):
            # Extract archive contents into the destination directory
            try:
                extract_archive(str(source), str(dest_dir))
            except ArchiveError as exc:
                shutil.rmtree(str(dest_dir), ignore_errors=True)
                raise
        else:
            shutil.copy2(str(source), str(dest_dir / source.name))

        # ── Normalise texture pack folder layout ──────────────────────────
        # Many texture packs ship with a folder named "replacement" or
        # "replacements" rather than the PS2 disc serial.  When a game_id is
        # known we reorganise the contents into the structure PCSX2 expects:
        #     <dest_dir>/<SERIAL>/replacements/<texture_files>
        if mod_type == ModType.TEXTURE_PACK and game_id:
            self._normalize_texture_structure(dest_dir, game_id)

        files = self._list_files(dest_dir)
        size = sum(f.stat().st_size for f in dest_dir.rglob("*") if f.is_file())

        # Auto-fetch thumbnail from GameTDB if a game_id is provided
        thumbnail_path = ""
        if game_id:
            thumbnail_path = self._fetch_thumbnail(game_id) or ""

        mod = ModInfo(
            id=mod_id,
            name=name or source.name,
            mod_type=mod_type,
            path=str(dest_dir),
            enabled=True,
            author=author,
            version=version or "1.0.0",
            description=description,
            game_id=game_id,
            source_url=source_url,
            thumbnail_path=thumbnail_path,
            files=files,
            size_bytes=size,
        )
        self.db.add(mod)
        return mod

    def remove_mod(self, mod_id: str, delete_files: bool = True):
        """Remove a mod from the database and optionally delete its files."""
        mod = self.db.get(mod_id)
        if mod and delete_files:
            p = Path(mod.path)
            if p.is_dir():
                shutil.rmtree(str(p), ignore_errors=True)
            elif p.is_file():
                p.unlink(missing_ok=True)
        self.db.remove(mod_id)

    # ------------------------------------------------------------------
    # Enable / Disable  (always triggers deploy / undeploy immediately)
    # ------------------------------------------------------------------

    def set_enabled(
        self,
        mod_id: str,
        enabled: bool,
        config=None,
    ) -> Tuple[int, List[str]]:
        """
        Toggle a mod on or off and immediately deploy/undeploy it.

        When *enabled* is ``True`` the mod's type is re-deployed to the
        appropriate PCSX2 folder (all currently-enabled mods of that type are
        written, which correctly handles priority ordering and PNACH merging).

        When *enabled* is ``False`` the mod is removed from the PCSX2 target
        folder and the remaining enabled mods are re-deployed so nothing is lost.

        *config* must be an :class:`~src.models.mod.AppConfig` instance so the
        target path can be resolved.  If *config* is ``None`` (e.g. in tests
        that only check the DB state) the method still toggles the flag but
        skips the filesystem deploy.

        Returns ``(deployed_count, warnings)`` — same as :meth:`deploy`.
        """
        mod = self.db.get(mod_id)
        if not mod:
            return 0, []

        mod.enabled = enabled
        self.db.update(mod)

        if config is None:
            return 0, []

        from src.core.pcsx2_layout import get_deploy_path
        target_path = get_deploy_path(config, mod.mod_type)
        if not target_path:
            return 0, [
                f"No target path configured for {mod.mod_type.value}. "
                "Check Settings → PCSX2 Paths."
            ]

        if enabled:
            # Re-deploy all enabled mods of this type (applies priority order)
            return self.deploy(mod.mod_type, target_path)
        else:
            # Remove this mod's files then re-deploy remaining enabled mods
            return self.undeploy_mod(mod_id, config)

    def undeploy_mod(self, mod_id: str, config) -> Tuple[int, List[str]]:
        """
        Remove a single mod's deployed files from the PCSX2 target folder then
        re-deploy all remaining *enabled* mods so nothing is accidentally lost.

        Returns ``(deployed_count, warnings)`` from the re-deploy step.
        """
        mod = self.db.get(mod_id)
        if not mod:
            return 0, []

        from src.core.pcsx2_layout import get_deploy_path
        target_path = get_deploy_path(config, mod.mod_type)
        if not target_path:
            return 0, []

        target = Path(target_path)
        if target.exists():
            # Remove files that belong to this mod from the target folder
            mod_src = Path(mod.path)
            if mod_src.is_dir():
                for f in mod_src.rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(mod_src)
                        deployed_file = target / rel
                        if deployed_file.exists():
                            try:
                                deployed_file.unlink()
                            except OSError:
                                pass
            elif mod_src.is_file():
                deployed_file = target / mod_src.name
                if deployed_file.exists():
                    try:
                        deployed_file.unlink()
                    except OSError:
                        pass

        # Re-deploy remaining enabled mods so priority ordering is honoured
        return self.deploy(mod.mod_type, target_path)

    def set_priority(self, mod_id: str, priority: int):
        mod = self.db.get(mod_id)
        if mod:
            mod.priority = priority
            self.db.update(mod)

    # ------------------------------------------------------------------
    # Metadata update
    # ------------------------------------------------------------------

    def update_metadata(
        self,
        mod_id: str,
        name: str = "",
        author: str = "",
        description: str = "",
        game_id: str = "",
        version: str = "",
        source_url: str = "",
        tags: Optional[List[str]] = None,
    ):
        """Update editable metadata fields on an existing mod."""
        mod = self.db.get(mod_id)
        if not mod:
            return
        if name:
            mod.name = name
        if author is not None:
            mod.author = author
        if description is not None:
            mod.description = description
        if version:
            mod.version = version
        if source_url is not None:
            mod.source_url = source_url
        if tags is not None:
            mod.tags = tags

        # If game_id changed and we don't have a thumbnail yet, fetch one
        if game_id is not None and game_id != mod.game_id:
            mod.game_id = game_id
            if game_id and not mod.thumbnail_path:
                mod.thumbnail_path = self._fetch_thumbnail(game_id) or ""
        elif game_id is not None:
            mod.game_id = game_id

        self.db.update(mod)

    # ------------------------------------------------------------------
    # Thumbnail helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_thumbnail(game_id: str, region: str = "EN") -> Optional[str]:
        """
        Try to download a cover art thumbnail from GameTDB.
        Returns local file path on success, None on failure.
        Runs synchronously; callers that want non-blocking behaviour should
        call this in a background thread.
        """
        try:
            from src.core.downloader import fetch_gametdb_art
            thumb_dir = str(_cfg.THUMBNAILS_DIR)
            return fetch_gametdb_art(game_id, thumb_dir, region)
        except Exception:
            return None

    @staticmethod
    def _normalize_texture_structure(dest_dir: Path, game_id: str) -> None:
        """Reorganise an imported texture pack so it matches PCSX2's expected layout::

                <dest_dir>/<SERIAL>/replacements/<texture_files>

        Handles three common pack patterns that authors use:

        * **replacement/replacements subfolder** (depth 0 or depth 1 inside a
          single outer wrapper folder): the subfolder's contents are moved into
          ``<serial>/replacements/``.
        * **Flat folder** of texture files (no replacements subfolder): every
          file/directory is moved into ``<serial>/replacements/``.
        * **Already correct structure** (a ``<SERIAL>/`` subdirectory is already
          present): no action taken.

        This means a user can import a pack whose zip contains::

            replacement/
                <hash1>.png
                <hash2>.png

        and the app will automatically place those files where PCSX2 looks for
        them::

            textures/SLUS-21228/replacements/<hash1>.png
            textures/SLUS-21228/replacements/<hash2>.png
        """
        from src.core.game_registry import normalise_serial

        serial = normalise_serial(game_id) if game_id else ""
        if not serial:
            return  # Can't normalise without a valid serial

        # Already has the correct serial structure — nothing to do.
        if (dest_dir / serial).exists():
            return
        if _folder_has_serial_structure(dest_dir):
            return

        # ── Locate the source of texture files ────────────────────────────
        replacements_src: Optional[Path] = None

        # Depth 0: "replacements" or "replacement" directly under dest_dir
        for sub_name in ("replacements", "replacement"):
            p = dest_dir / sub_name
            if p.is_dir():
                replacements_src = p
                break

        # Depth 1: single outer wrapper folder containing a replacements subfolder
        # (common when a zip file has an outer named folder, e.g. Eragon_HD_v1/)
        if replacements_src is None:
            try:
                subdirs = [d for d in dest_dir.iterdir() if d.is_dir()]
            except PermissionError:
                return
            if len(subdirs) == 1:
                for sub_name in ("replacements", "replacement"):
                    p = subdirs[0] / sub_name
                    if p.is_dir():
                        replacements_src = p
                        break

        # ── Move files into <serial>/replacements/ ─────────────────────────
        target = dest_dir / serial / "replacements"
        target.mkdir(parents=True, exist_ok=True)

        if replacements_src is not None:
            # Move each item from the replacement folder into the target
            for item in list(replacements_src.iterdir()):
                shutil.move(str(item), str(target / item.name))
            # Clean up the now-empty wrapper/replacement folder
            try:
                outer = replacements_src.parent
                if outer != dest_dir:
                    shutil.rmtree(str(outer), ignore_errors=True)
                else:
                    replacements_src.rmdir()
            except OSError:
                pass
        else:
            # Flat structure: move all top-level items into target
            for item in list(dest_dir.iterdir()):
                if item.name != serial:  # don't move the serial folder we just created
                    shutil.move(str(item), str(target / item.name))

    def refresh_thumbnail(self, mod_id: str, region: str = "EN") -> bool:
        """Re-fetch the thumbnail for *mod_id* from GameTDB. Returns True on success."""
        mod = self.db.get(mod_id)
        if not mod or not mod.game_id:
            return False
        path = self._fetch_thumbnail(mod.game_id, region)
        if path:
            mod.thumbnail_path = path
            self.db.update(mod)
            return True
        return False

    # ------------------------------------------------------------------
    # Apply mods (deploy to PCSX2 folders)
    # ------------------------------------------------------------------

    def deploy(self, mod_type: ModType, target_path: str) -> Tuple[int, List[str]]:
        """
        Copy enabled mods of *mod_type* into *target_path* in priority order.

        For ``ModType.PNACH`` and ``ModType.CHEAT``: PNACH files for the *same
        game CRC* are automatically **merged** into a single output file so that
        patch lines from multiple enabled mods are all applied.  Files that have
        no CRC in their filename (non-standard names) are copied as-is.

        For ``ModType.COVER_ART``: files are renamed to ``{SERIAL}.png``
        (e.g. ``SLUS-20062.png``) so PCSX2 can find them automatically.
        Only the highest-priority cover art for each game serial is deployed.

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

        # ── PNACH / Cheat: merge by game CRC ─────────────────────────────
        if mod_type in (ModType.PNACH, ModType.CHEAT):
            return self._deploy_pnach(mods, target, warnings)

        # ── Cover Art: rename to {SERIAL}.png, one per game serial ────────
        if mod_type == ModType.COVER_ART:
            return self._deploy_cover_art(mods, target, warnings)

        # ── All other types: copy in priority order ───────────────────────
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

    def _deploy_cover_art(
        self,
        mods: List,
        target: Path,
        warnings: List[str],
    ) -> Tuple[int, List[str]]:
        """
        Deploy cover art mods to *target*, renaming each file to the PCSX2
        format: ``{SERIAL}.png``  (e.g. ``SLUS-20062.png``).

        PCSX2 loads cover art from its covers directory by looking for a file
        named exactly after the game's disc serial.  Only the highest-priority
        cover art for each serial is copied; lower-priority duplicates are
        skipped with a warning.
        """
        from src.core.game_registry import (
            detect_game_serial,
            detect_serial_from_path,
            normalise_serial,
        )

        deployed = 0
        # Track which serials have already been deployed (highest priority first)
        deployed_serials: set = set()

        for mod in mods:
            src = Path(mod.path)
            if not src.exists():
                warnings.append(f"Missing path for mod '{mod.name}': {mod.path}")
                continue

            # Determine the serial: prefer stored game_id, then filename, then path
            serial = ""
            if mod.game_id:
                serial = normalise_serial(mod.game_id)
            if not serial:
                serial = detect_game_serial(str(src))
            if not serial:
                serial = detect_serial_from_path(str(src))

            if not serial:
                # No serial detected — copy with original filename but warn
                dest_name = src.name
                if not any(dest_name.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
                    warnings.append(
                        f"Cover art '{mod.name}' has no game serial set; "
                        "copied with original filename. PCSX2 may not find it."
                    )
                shutil.copy2(str(src), str(target / dest_name))
                deployed += 1
                continue

            if serial in deployed_serials:
                warnings.append(
                    f"Cover art '{mod.name}' skipped — a higher-priority cover "
                    f"for {serial} was already deployed."
                )
                continue

            # Determine source image (use src directly if it's a file)
            img_src: Optional[Path] = None
            if src.is_file():
                img_src = src
            elif src.is_dir():
                # Look for an image in the folder
                for img in src.iterdir():
                    if img.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        img_src = img
                        break

            if img_src is None:
                warnings.append(f"Cover art '{mod.name}' has no image file.")
                continue

            # Always save as PNG to match PCSX2 expectations
            dest = target / f"{serial}.png"
            if img_src.suffix.lower() == ".png":
                shutil.copy2(str(img_src), str(dest))
            else:
                # Convert to PNG via Pillow if available, otherwise copy as-is
                try:
                    from PIL import Image
                    with Image.open(str(img_src)) as im:
                        im.save(str(dest), "PNG")
                except ImportError:
                    shutil.copy2(str(img_src), str(dest))
                    warnings.append(
                        f"Pillow not installed; '{mod.name}' copied without format conversion."
                    )

            deployed_serials.add(serial)
            deployed += 1

        return deployed, warnings

    def detect_cover_art_conflicts(self) -> List[Tuple[str, List]]:
        """
        Return a list of ``(serial, [mod_list])`` tuples where more than one
        *enabled* cover art mod targets the same game serial.
        """
        from src.core.game_registry import normalise_serial, detect_game_serial

        by_serial: Dict[str, List] = {}
        for mod in self.db.by_type(ModType.COVER_ART):
            if not mod.enabled:
                continue
            serial = normalise_serial(mod.game_id) if mod.game_id else detect_game_serial(mod.path)
            if serial:
                by_serial.setdefault(serial, []).append(mod)

        return [(s, mods) for s, mods in by_serial.items() if len(mods) > 1]

    def _deploy_pnach(
        self,
        mods: List,
        target: Path,
        warnings: List[str],
    ) -> Tuple[int, List[str]]:
        """
        Deploy PNACH/Cheat mods, merging multiple files for the same game CRC.

        Strategy:
        1. Collect all .pnach files from enabled mods, grouped by CRC.
        2. For each CRC group with >1 file: merge into a combined .pnach.
        3. For each CRC group with 1 file: copy directly.
        4. Files without a recognisable CRC filename are copied as-is.
        """
        from src.core.pnach import extract_game_crc, merge_pnach_files
        import tempfile

        # Map CRC → [(priority, pnach_file_path), …]
        crc_files: Dict[str, List[Tuple[int, str]]] = {}
        no_crc_files: List[Tuple[int, str]] = []
        deployed = 0

        for mod in mods:
            src = Path(mod.path)
            if not src.exists():
                warnings.append(f"Missing path for mod '{mod.name}': {mod.path}")
                continue

            # Collect all .pnach files from mod
            if src.is_dir():
                pnach_files = list(src.rglob("*.pnach"))
            elif src.suffix.lower() == ".pnach":
                pnach_files = [src]
            else:
                pnach_files = []

            for pf in pnach_files:
                crc = extract_game_crc(str(pf))
                if crc:
                    crc_files.setdefault(crc, []).append((mod.priority, str(pf)))
                else:
                    no_crc_files.append((mod.priority, str(pf)))

        # Sort each CRC group by priority (highest first)
        for crc, entries in crc_files.items():
            entries.sort(key=lambda e: e[0], reverse=True)
            paths = [e[1] for e in entries]

            if len(paths) == 1:
                shutil.copy2(paths[0], str(target / f"{crc}.pnach"))
                deployed += 1
            else:
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        merged = merge_pnach_files(paths, tmp, game_crc=crc)
                        shutil.copy2(merged, str(target / f"{crc}.pnach"))
                    deployed += 1
                except Exception as exc:
                    warnings.append(
                        f"Failed to merge PNACH for CRC {crc}: {exc}. "
                        "Using highest-priority file instead."
                    )
                    shutil.copy2(paths[0], str(target / f"{crc}.pnach"))
                    deployed += 1

        # Copy no-CRC files directly
        for _prio, path in no_crc_files:
            shutil.copy2(path, str(target / Path(path).name))
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

    def detect_shadowed_mods(self, mod_type: Optional[ModType] = None) -> Dict[str, List[str]]:
        """
        Return mods whose every file is overridden by a higher-priority enabled mod.

        A mod is *completely shadowed* when every path in ``mod.files`` is also
        claimed by at least one enabled mod with a **higher** priority.  Disabled
        mods and mods with an empty file list are never considered shadowed.

        Returns a ``{mod_id: [shadowing_mod_id, ...]}`` dict for each shadowed mod.
        """
        mods = self.db.by_type(mod_type) if mod_type else self.db.all()
        enabled = [m for m in mods if m.enabled and m.files]

        # Build a map: relative_path → list of (priority, mod_id) sorted high→low
        file_owners: Dict[str, List[tuple]] = {}
        for mod in enabled:
            for rel_path in mod.files:
                file_owners.setdefault(rel_path, []).append((mod.priority, mod.id))

        for owners in file_owners.values():
            owners.sort(key=lambda x: x[0], reverse=True)

        shadowed: Dict[str, List[str]] = {}
        for mod in enabled:
            if not mod.files:
                continue
            shadowers: set = set()
            fully_shadowed = True
            for rel_path in mod.files:
                owners = file_owners.get(rel_path, [])
                higher = [mid for prio, mid in owners if prio > mod.priority and mid != mod.id]
                if not higher:
                    fully_shadowed = False
                    break
                shadowers.update(higher)
            if fully_shadowed:
                shadowed[mod.id] = list(shadowers)

        return shadowed

    def detect_pnach_conflicts(
        self, mod_type: Optional[ModType] = None
    ) -> List[dict]:
        """
        Detect address-level conflicts in PNACH/Cheat mods.

        Returns a list of dicts with keys:
        ``address``, ``processor``, ``mod_a_id``, ``value_a``,
        ``mod_b_id``, ``value_b``.
        """
        from src.core.pnach import find_pnach_conflicts, extract_game_crc
        from pathlib import Path as _Path

        pnach_types = (ModType.PNACH, ModType.CHEAT)
        types_to_check = [mod_type] if mod_type and mod_type in pnach_types else pnach_types

        result = []
        for mt in types_to_check:
            enabled = [m for m in self.db.by_type(mt) if m.enabled]
            for mod in enabled:
                src = _Path(mod.path)
                pnach_files = (
                    list(src.rglob("*.pnach")) if src.is_dir()
                    else [src] if src.suffix.lower() == ".pnach" else []
                )
                for pf in pnach_files:
                    crc = extract_game_crc(str(pf))
                    if not crc:
                        continue
                    # Find other mods that also have a file for this CRC
                    siblings = []
                    for other in enabled:
                        if other.id == mod.id:
                            continue
                        other_src = _Path(other.path)
                        ofiles = (
                            list(other_src.rglob("*.pnach")) if other_src.is_dir()
                            else [other_src] if other_src.suffix.lower() == ".pnach" else []
                        )
                        for opf in ofiles:
                            if extract_game_crc(str(opf)) == crc:
                                siblings.append((other.id, str(opf)))

                    if siblings:
                        for sibling_id, sibling_path in siblings:
                            conflicts = find_pnach_conflicts([str(pf), sibling_path])
                            for c in conflicts:
                                result.append({
                                    "address": c.address,
                                    "processor": c.processor,
                                    "mod_a_id": mod.id,
                                    "value_a": c.value_a,
                                    "mod_b_id": sibling_id,
                                    "value_b": c.value_b,
                                    "game_crc": crc,
                                })
        # Deduplicate
        seen_keys = set()
        deduped = []
        for r in result:
            key = (r["address"], r["processor"], r["game_crc"],
                   tuple(sorted([r["mod_a_id"], r["mod_b_id"]])))
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(r)
        return deduped

    def validate_all_pnach(self) -> Dict[str, list]:
        """
        Run :func:`src.core.pnach.validate_pnach_file` on all enabled
        PNACH and CHEAT mods.

        Returns a dict mapping ``mod_id`` → list of
        :class:`~src.core.pnach.ValidationIssue`.  Only mods with at least
        one issue are included; mods that pass cleanly are omitted.
        """
        from src.core.pnach import validate_pnach_file
        from pathlib import Path as _Path

        results: Dict[str, list] = {}
        for mt in (ModType.PNACH, ModType.CHEAT):
            for mod in self.db.by_type(mt):
                if not mod.enabled:
                    continue
                src = _Path(mod.path)
                pnach_files = (
                    list(src.rglob("*.pnach")) if src.is_dir()
                    else [src] if src.suffix.lower() == ".pnach" else []
                )
                all_issues = []
                for pf in pnach_files:
                    try:
                        issues = validate_pnach_file(str(pf))
                        all_issues.extend(issues)
                    except Exception:
                        pass
                if all_issues:
                    results[mod.id] = all_issues
        return results

    def resolve_conflict(
        self,
        conflict: ConflictInfo,
        winner_id: str,
    ) -> bool:
        """
        Resolve a conflict by giving *winner_id* a higher priority than the
        other mod in the conflict pair.

        Returns ``True`` if the resolution was applied, ``False`` if either
        mod is not found in the database.
        """
        loser_id = (
            conflict.mod_b_id if winner_id == conflict.mod_a_id else conflict.mod_a_id
        )
        winner = self.db.get(winner_id)
        loser = self.db.get(loser_id)
        if not winner or not loser:
            return False
        winner.priority = max(winner.priority, loser.priority) + 1
        self.db.update(winner)
        return True

    def resolve_conflict_disable_loser(
        self,
        conflict: ConflictInfo,
        winner_id: str,
    ) -> bool:
        """
        Resolve a conflict by **disabling** the losing mod entirely.

        Returns ``True`` if the resolution was applied, ``False`` if either
        mod is not found.
        """
        loser_id = (
            conflict.mod_b_id if winner_id == conflict.mod_a_id else conflict.mod_a_id
        )
        loser = self.db.get(loser_id)
        if not loser:
            return False
        loser.enabled = False
        self.db.update(loser)
        return True

    def summary_for_game(self, serial: str) -> dict:
        """
        Return a summary dict for the given PS2 game serial containing:
        ``total``, ``enabled``, ``disabled``, ``conflicts`` counts,
        and ``mods`` (list of ModInfo).

        Useful for the Library panel and dashboard game-specific views.
        """
        serial = (serial or "").upper()
        mods = [m for m in self.db.all() if (m.game_id or "").upper() == serial]
        enabled = [m for m in mods if m.enabled]
        disabled = [m for m in mods if not m.enabled]
        conflicts = self.detect_conflicts()
        mod_ids = {m.id for m in mods}
        game_conflicts = [
            c for c in conflicts
            if c.mod_a_id in mod_ids or c.mod_b_id in mod_ids
        ]
        return {
            "total": len(mods),
            "enabled": len(enabled),
            "disabled": len(disabled),
            "conflicts": len(game_conflicts),
            "mods": mods,
        }

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
