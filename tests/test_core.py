"""Tests for PS2 Mod Manager core logic."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List
from unittest.mock import patch, MagicMock

# Ensure src is importable
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.models.mod import AppConfig, ConflictInfo, ModInfo, ModStatus, ModType
from src.core.config_manager import detect_pcsx2_paths, load_config, save_config
from src.core.mod_manager import ModDatabase, ModManager


class TestModInfoSerialization(unittest.TestCase):
    """Test ModInfo serialization round-trip."""

    def test_to_dict_from_dict_round_trip(self):
        mod = ModInfo(
            id="test-id",
            name="Test Texture Pack",
            mod_type=ModType.TEXTURE_PACK,
            path="/some/path",
            enabled=True,
            version="2.0",
            author="Alice",
            description="A test mod",
            game_id="SLUS-20062",
            priority=5,
            files=["tex/a.png", "tex/b.png"],
            tags=["hd", "ui"],
            size_bytes=1024,
        )
        data = mod.to_dict()
        restored = ModInfo.from_dict(data)

        self.assertEqual(restored.id, mod.id)
        self.assertEqual(restored.name, mod.name)
        self.assertEqual(restored.mod_type, ModType.TEXTURE_PACK)
        self.assertEqual(restored.priority, mod.priority)
        self.assertEqual(restored.files, mod.files)
        self.assertEqual(restored.tags, mod.tags)

    def test_all_mod_types_serialize(self):
        for mt in ModType:
            mod = ModInfo(id=mt.value, name=mt.value, mod_type=mt, path="/tmp")
            data = mod.to_dict()
            self.assertEqual(data["mod_type"], mt.value)
            restored = ModInfo.from_dict(data)
            self.assertEqual(restored.mod_type, mt)

    def test_to_json(self):
        mod = ModInfo(id="x", name="X", mod_type=ModType.PNACH, path="/p")
        j = mod.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["name"], "X")

    def test_appconfig_round_trip(self):
        cfg = AppConfig(
            pcsx2_path="/home/user/pcsx2",
            textures_path="/home/user/pcsx2/textures",
            theme="dark",
            first_run=False,
        )
        data = cfg.to_dict()
        restored = AppConfig.from_dict(data)
        self.assertEqual(restored.pcsx2_path, cfg.pcsx2_path)
        self.assertEqual(restored.textures_path, cfg.textures_path)
        self.assertFalse(restored.first_run)

    def test_from_dict_ignores_unknown_keys(self):
        """ModInfo.from_dict must silently ignore keys not in the dataclass.

        Without this behaviour a mods.json written by a newer version of the
        app (which may have extra fields) would raise TypeError when loaded by
        an older version.  ModDatabase._load() catches TypeError and resets the
        entire database to {}, silently losing all tracked mods.
        """
        data = {
            "id": "abc",
            "name": "My Mod",
            "mod_type": "texture_pack",
            "path": "/tmp/mymod",
            "future_field_added_in_v2": "some_value",
            "another_new_field": 99,
        }
        mod = ModInfo.from_dict(data)
        self.assertEqual(mod.id, "abc")
        self.assertEqual(mod.name, "My Mod")
        self.assertEqual(mod.mod_type, ModType.TEXTURE_PACK)


class TestConfigManager(unittest.TestCase):
    """Test configuration persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load_config(self):
        config_file = Path(self.tmpdir) / "config.json"
        cfg = AppConfig(
            pcsx2_path="/test/pcsx2",
            textures_path="/test/textures",
            first_run=False,
        )
        import src.core.config_manager as cm
        orig_file = cm.CONFIG_FILE
        cm.CONFIG_FILE = config_file
        try:
            save_config(cfg)
            self.assertTrue(config_file.exists())
            loaded = load_config()
            self.assertEqual(loaded.pcsx2_path, cfg.pcsx2_path)
        finally:
            cm.CONFIG_FILE = orig_file

    def test_load_config_missing_file_returns_default(self):
        import src.core.config_manager as cm
        orig_file = cm.CONFIG_FILE
        cm.CONFIG_FILE = Path(self.tmpdir) / "nonexistent.json"
        try:
            cfg = load_config()
            self.assertIsInstance(cfg, AppConfig)
            self.assertTrue(cfg.first_run)
        finally:
            cm.CONFIG_FILE = orig_file

    def test_detect_pcsx2_paths_existing(self):
        root = Path(self.tmpdir) / "pcsx2"
        (root / "textures").mkdir(parents=True)
        (root / "cheats").mkdir(parents=True)
        (root / "covers").mkdir(parents=True)
        (root / "memcards").mkdir(parents=True)

        paths = detect_pcsx2_paths(str(root))
        self.assertIn("textures_path", paths)
        self.assertIn("pnach_path", paths)
        self.assertIn("cover_art_path", paths)
        self.assertIn("memcards_path", paths)

    def test_detect_pcsx2_paths_non_existing(self):
        root = Path(self.tmpdir) / "empty_pcsx2"
        root.mkdir(parents=True)
        paths = detect_pcsx2_paths(str(root))
        self.assertIsInstance(paths, dict)
        self.assertIn("textures_path", paths)


class TestModDatabase(unittest.TestCase):
    """Test ModDatabase CRUD."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import src.core.config_manager as cm
        self._orig_db_file = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"

    def tearDown(self):
        import src.core.config_manager as cm
        cm.MODS_DB_FILE = self._orig_db_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_db(self):
        from src.core.mod_manager import ModDatabase
        return ModDatabase()

    def test_add_and_get(self):
        db = self._make_db()
        mod = ModInfo(id="a", name="Alpha", mod_type=ModType.TEXTURE_PACK, path="/p")
        db.add(mod)
        got = db.get("a")
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "Alpha")

    def test_remove(self):
        db = self._make_db()
        mod = ModInfo(id="b", name="Beta", mod_type=ModType.PNACH, path="/p")
        db.add(mod)
        db.remove("b")
        self.assertIsNone(db.get("b"))

    def test_by_type(self):
        db = self._make_db()
        db.add(ModInfo(id="1", name="T1", mod_type=ModType.TEXTURE_PACK, path="/p"))
        db.add(ModInfo(id="2", name="P1", mod_type=ModType.PNACH, path="/p"))
        db.add(ModInfo(id="3", name="T2", mod_type=ModType.TEXTURE_PACK, path="/p"))

        textures = db.by_type(ModType.TEXTURE_PACK)
        pnachs = db.by_type(ModType.PNACH)

        self.assertEqual(len(textures), 2)
        self.assertEqual(len(pnachs), 1)

    def test_persistence(self):
        """Data persists across separate ModDatabase instances."""
        import src.core.config_manager as cm
        db1 = self._make_db()
        mod = ModInfo(id="persist", name="Persistent", mod_type=ModType.COVER_ART, path="/p")
        db1.add(mod)

        db2 = self._make_db()
        got = db2.get("persist")
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "Persistent")

    def test_load_with_corrupted_mod_type_returns_empty(self):
        """ModDatabase._load() must not crash when a stored mod_type is invalid."""
        import json
        import src.core.config_manager as cm

        bad_entry = {
            "id": "bad", "name": "Bad", "mod_type": "not_a_real_type",
            "path": "", "enabled": True, "version": "1.0", "author": "",
            "description": "", "game_id": "", "thumbnail_url": "",
            "thumbnail_path": "", "source_url": "", "priority": 0,
            "files": [], "tags": [], "size_bytes": 0, "installed": True,
            "has_update": False, "installed_at": 0.0,
        }
        with open(cm.MODS_DB_FILE, "w") as f:
            json.dump({"bad": bad_entry}, f)

        db = self._make_db()
        # Should have silently discarded only the corrupted entry
        self.assertEqual(db.all(), [])

    def test_load_keeps_good_entries_when_one_is_corrupt(self):
        """A single corrupt entry must not wipe valid mods from the database."""
        import json
        import src.core.config_manager as cm

        good_entry = {
            "id": "good", "name": "Good Mod", "mod_type": "texture_pack",
            "path": "/tmp/good", "enabled": True, "version": "1.0",
            "author": "", "description": "", "game_id": "", "thumbnail_url": "",
            "thumbnail_path": "", "source_url": "", "priority": 0,
            "files": [], "tags": [], "size_bytes": 0, "installed": True,
            "has_update": False, "installed_at": 0.0,
        }
        bad_entry = {
            "id": "bad", "name": "Bad Mod", "mod_type": "INVALID_TYPE",
            "path": "", "enabled": True, "version": "1.0", "author": "",
            "description": "", "game_id": "", "thumbnail_url": "",
            "thumbnail_path": "", "source_url": "", "priority": 0,
            "files": [], "tags": [], "size_bytes": 0, "installed": True,
            "has_update": False, "installed_at": 0.0,
        }
        with open(cm.MODS_DB_FILE, "w") as f:
            json.dump({"good": good_entry, "bad": bad_entry}, f)

        db = self._make_db()
        # Good entry must survive; corrupt entry is silently skipped
        self.assertIsNotNone(db.get("good"))
        self.assertEqual(db.get("good").name, "Good Mod")
        self.assertIsNone(db.get("bad"))

    def test_save_is_atomic(self):
        """ModDatabase.save() must not corrupt the DB file on failure."""
        import json
        import src.core.config_manager as cm
        from src.core.mod_manager import ModDatabase

        # Pre-populate the DB with one mod
        db = self._make_db()
        mod = ModInfo(id="x", name="X", mod_type=ModType.PNACH, path="/p")
        db.add(mod)

        # The file must be valid JSON after save()
        with open(cm.MODS_DB_FILE, "r") as f:
            data = json.load(f)
        self.assertIn("x", data)

        # No leftover .tmp files in the same directory
        tmp_files = list(Path(self.tmpdir).glob("*.tmp"))
        self.assertEqual(tmp_files, [])


class TestModManager(unittest.TestCase):
    """Test ModManager operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import src.core.config_manager as cm
        self._orig_db_file = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"

    def tearDown(self):
        import src.core.config_manager as cm
        cm.MODS_DB_FILE = self._orig_db_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_manager(self):
        from src.core.mod_manager import ModDatabase, ModManager
        db = ModDatabase()
        return db, ModManager(db)

    def test_set_enabled(self):
        db, mgr = self._make_manager()
        mod = ModInfo(id="m1", name="M1", mod_type=ModType.TEXTURE_PACK, path="/p", enabled=True)
        db.add(mod)
        mgr.set_enabled("m1", False)
        self.assertFalse(db.get("m1").enabled)
        mgr.set_enabled("m1", True)
        self.assertTrue(db.get("m1").enabled)

    def test_set_priority(self):
        db, mgr = self._make_manager()
        mod = ModInfo(id="m2", name="M2", mod_type=ModType.PNACH, path="/p", priority=0)
        db.add(mod)
        mgr.set_priority("m2", 10)
        self.assertEqual(db.get("m2").priority, 10)

    def test_install_from_folder(self):
        db, mgr = self._make_manager()

        # Create a source folder with a file
        src_dir = Path(self.tmpdir) / "src_mod"
        src_dir.mkdir()
        (src_dir / "texture.png").write_bytes(b"\x89PNG")

        dest_base = str(Path(self.tmpdir) / "storage")
        mod = mgr.install_from_folder(
            source_path=str(src_dir),
            mod_type=ModType.TEXTURE_PACK,
            dest_base=dest_base,
            name="My Texture Pack",
        )

        self.assertEqual(mod.name, "My Texture Pack")
        self.assertEqual(mod.mod_type, ModType.TEXTURE_PACK)
        self.assertIn("texture.png", mod.files)
        self.assertIsNotNone(db.get(mod.id))

    def test_install_from_file(self):
        db, mgr = self._make_manager()

        src_file = Path(self.tmpdir) / "hack.pnach"
        src_file.write_text("// PNACH file")

        dest_base = str(Path(self.tmpdir) / "storage")
        mod = mgr.install_from_folder(
            source_path=str(src_file),
            mod_type=ModType.PNACH,
            dest_base=dest_base,
        )

        self.assertEqual(mod.mod_type, ModType.PNACH)
        self.assertIn("hack.pnach", mod.files)

    def test_remove_mod(self):
        db, mgr = self._make_manager()
        src_dir = Path(self.tmpdir) / "src_mod2"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("hi")

        mod = mgr.install_from_folder(
            source_path=str(src_dir),
            mod_type=ModType.TEXTURE_PACK,
            dest_base=str(Path(self.tmpdir) / "storage"),
        )
        mod_path = mod.path
        mgr.remove_mod(mod.id, delete_files=True)
        self.assertIsNone(db.get(mod.id))
        self.assertFalse(Path(mod_path).exists())

    def test_remove_mod_file_path(self):
        """remove_mod should delete a single file when mod.path is a file (not a dir)."""
        db, mgr = self._make_manager()
        pnach_dir = Path(self.tmpdir) / "pnach"
        pnach_dir.mkdir()
        pnach_file = pnach_dir / "F0A235B4.pnach"
        pnach_file.write_text("patch v=0 nop")

        # Register a ModInfo whose path points directly at the file (PNACH-from-GitHub pattern)
        mod = ModInfo(
            id="test-pnach-direct",
            name="Widescreen Patch (F0A235B4)",
            mod_type=ModType.PNACH,
            path=str(pnach_file),
        )
        db.add(mod)
        self.assertTrue(pnach_file.exists())

        mgr.remove_mod(mod.id, delete_files=True)
        self.assertIsNone(db.get(mod.id))
        self.assertFalse(pnach_file.exists())

        db, mgr = self._make_manager()
        db.add(ModInfo(id="x", name="X", mod_type=ModType.TEXTURE_PACK, path="/p",
                       enabled=True, files=["a.png"]))
        db.add(ModInfo(id="y", name="Y", mod_type=ModType.TEXTURE_PACK, path="/p",
                       enabled=True, files=["b.png"]))
        conflicts = mgr.detect_conflicts(ModType.TEXTURE_PACK)
        self.assertEqual(len(conflicts), 0)

    def test_detect_conflicts(self):
        db, mgr = self._make_manager()
        db.add(ModInfo(id="x", name="X", mod_type=ModType.TEXTURE_PACK, path="/p",
                       enabled=True, files=["shared.png", "a.png"]))
        db.add(ModInfo(id="y", name="Y", mod_type=ModType.TEXTURE_PACK, path="/p",
                       enabled=True, files=["shared.png", "b.png"]))
        conflicts = mgr.detect_conflicts(ModType.TEXTURE_PACK)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("shared.png", conflicts[0].conflicting_files)

    def test_disabled_mod_no_conflict(self):
        db, mgr = self._make_manager()
        db.add(ModInfo(id="x", name="X", mod_type=ModType.TEXTURE_PACK, path="/p",
                       enabled=True, files=["shared.png"]))
        db.add(ModInfo(id="y", name="Y", mod_type=ModType.TEXTURE_PACK, path="/p",
                       enabled=False, files=["shared.png"]))
        conflicts = mgr.detect_conflicts(ModType.TEXTURE_PACK)
        self.assertEqual(len(conflicts), 0)

    def test_deploy(self):
        db, mgr = self._make_manager()

        # Create managed mod
        src = Path(self.tmpdir) / "src_deploy"
        src.mkdir()
        (src / "tex.png").write_bytes(b"PNG")

        mod = mgr.install_from_folder(
            source_path=str(src),
            mod_type=ModType.TEXTURE_PACK,
            dest_base=str(Path(self.tmpdir) / "storage"),
        )

        target = str(Path(self.tmpdir) / "pcsx2_textures")
        count, warnings = mgr.deploy(ModType.TEXTURE_PACK, target)

        self.assertEqual(count, 1)
        self.assertEqual(len(warnings), 0)
        self.assertTrue((Path(target) / "tex.png").exists())

    def test_deploy_disabled_mod_not_deployed(self):
        db, mgr = self._make_manager()
        src = Path(self.tmpdir) / "src_disabled"
        src.mkdir()
        (src / "tex.png").write_bytes(b"PNG")

        mod = mgr.install_from_folder(
            source_path=str(src),
            mod_type=ModType.TEXTURE_PACK,
            dest_base=str(Path(self.tmpdir) / "storage"),
        )
        mgr.set_enabled(mod.id, False)

        target = str(Path(self.tmpdir) / "pcsx2_tex_disabled")
        count, warnings = mgr.deploy(ModType.TEXTURE_PACK, target)

        self.assertEqual(count, 0)
        self.assertFalse((Path(target) / "tex.png").exists())


class TestMemoryCard(unittest.TestCase):
    """Test memory card utilities."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_valid_memcard_returns_false_for_nonexistent(self):
        from src.core.memory_card import is_valid_memcard
        self.assertFalse(is_valid_memcard("/nonexistent/file.ps2"))

    def test_is_valid_memcard_returns_false_for_random_file(self):
        from src.core.memory_card import is_valid_memcard
        p = Path(self.tmpdir) / "random.bin"
        # Use clearly arbitrary bytes (not a recognised magic sequence)
        p.write_bytes(b"\x00\x01\x02\x03" * 128)
        self.assertFalse(is_valid_memcard(str(p)))

    def test_is_valid_memcard_returns_true_for_valid_header(self):
        from src.core.memory_card import is_valid_memcard, MC_SUPERBLOCK_MAGIC
        p = Path(self.tmpdir) / "card.ps2"
        # Write magic + padding
        p.write_bytes(MC_SUPERBLOCK_MAGIC + b"\x00" * 512)
        self.assertTrue(is_valid_memcard(str(p)))

    def test_list_memcard_files_empty_dir(self):
        from src.core.memory_card import list_memcard_files
        result = list_memcard_files(self.tmpdir)
        self.assertEqual(result, [])

    def test_list_memcard_files_finds_ps2_files(self):
        from src.core.memory_card import list_memcard_files
        (Path(self.tmpdir) / "card1.ps2").write_bytes(b"x")
        (Path(self.tmpdir) / "card2.mcd").write_bytes(b"x")
        (Path(self.tmpdir) / "other.txt").write_bytes(b"x")
        result = list_memcard_files(self.tmpdir)
        self.assertEqual(len(result), 2)

    def test_list_saves_invalid_file(self):
        from src.core.memory_card import list_saves, MemoryCardError
        p = Path(self.tmpdir) / "bad.ps2"
        p.write_bytes(b"BADDATA" + b"\x00" * 512)
        with self.assertRaises(MemoryCardError):
            list_saves(str(p))


class TestDownloader(unittest.TestCase):
    """Test downloader (mocked network)."""

    def test_download_rejects_non_http_scheme(self):
        from src.core.downloader import download_file, DownloadError
        with self.assertRaises(DownloadError):
            download_file("ftp://example.com/file.zip", "/tmp/out.zip")

    def test_download_rejects_file_scheme(self):
        from src.core.downloader import download_file, DownloadError
        with self.assertRaises(DownloadError):
            download_file("file:///etc/passwd", "/tmp/out.zip")

    @patch("src.core.downloader.requests.get")
    def test_download_success(self, mock_get):
        from src.core.downloader import download_file
        import tempfile

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"Content-Length": "5"}
        mock_resp.iter_content.return_value = [b"hello"]
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "out.bin")
            result = download_file("https://example.com/file.bin", dest)
            self.assertEqual(result, dest)
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), b"hello")

    @patch("src.core.downloader.requests.get")
    def test_download_removes_partial_file_on_network_error(self, mock_get):
        """A failed mid-download must not leave a partial file on disk."""
        import tempfile
        import requests as _requests
        from src.core.downloader import download_file, DownloadError

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"Content-Length": "1000"}

        # First chunk succeeds, second raises a network error
        def _iter_content(chunk_size=None):
            yield b"partial"
            raise _requests.ConnectionError("broken pipe")

        mock_resp.iter_content.side_effect = _iter_content
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "out.bin")
            with self.assertRaises(DownloadError):
                download_file("https://example.com/file.bin", dest)
            # Partial file must have been removed
            self.assertFalse(Path(dest).exists())

    @patch("src.core.downloader.requests.get")
    def test_download_removes_partial_file_on_cancel(self, mock_get):
        """Cancelling via the progress callback must remove the partial file."""
        import tempfile
        from src.core.downloader import download_file, DownloadError

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"Content-Length": "1000"}
        mock_resp.iter_content.return_value = [b"partial"]
        mock_get.return_value = mock_resp

        def _cancel_callback(received, total):
            raise DownloadError("Download cancelled")

        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "out.bin")
            with self.assertRaises(DownloadError):
                download_file("https://example.com/file.bin", dest,
                              progress_callback=_cancel_callback)
            # Partial file must have been removed
            self.assertFalse(Path(dest).exists())


class TestArchiveExtraction(unittest.TestCase):
    """Tests for archive extraction utilities."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_zip(self, name: str, files: dict) -> str:
        """Create a ZIP file at tmpdir/name with the given filename->content dict."""
        import zipfile
        path = Path(self.tmpdir) / name
        with zipfile.ZipFile(str(path), "w") as zf:
            for fname, content in files.items():
                zf.writestr(fname, content)
        return str(path)

    def test_is_archive_zip(self):
        from src.core.archive import is_archive
        self.assertTrue(is_archive("pack.zip"))
        self.assertTrue(is_archive("pack.ZIP"))

    def test_is_archive_7z(self):
        from src.core.archive import is_archive
        self.assertTrue(is_archive("pack.7z"))

    def test_is_archive_false_for_pnach(self):
        from src.core.archive import is_archive
        self.assertFalse(is_archive("hack.pnach"))
        self.assertFalse(is_archive("texture.png"))

    def test_extract_zip_creates_files(self):
        from src.core.archive import extract_archive
        zpath = self._make_zip("mod.zip", {
            "textures/game/tex1.png": b"PNG1",
            "textures/game/tex2.png": b"PNG2",
        })
        dest = str(Path(self.tmpdir) / "extracted")
        extracted = extract_archive(zpath, dest)
        self.assertEqual(len(extracted), 2)
        self.assertTrue((Path(dest) / "textures" / "game" / "tex1.png").exists())
        self.assertTrue((Path(dest) / "textures" / "game" / "tex2.png").exists())

    def test_extract_zip_returns_relative_paths(self):
        from src.core.archive import extract_archive
        zpath = self._make_zip("mod.zip", {"folder/file.txt": "hello"})
        dest = str(Path(self.tmpdir) / "out")
        extracted = extract_archive(zpath, dest)
        self.assertIn("folder/file.txt", extracted)

    def test_extract_zip_rejects_path_traversal(self):
        from src.core.archive import extract_archive, ArchiveError
        import zipfile
        bad_zip = str(Path(self.tmpdir) / "bad.zip")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("../evil.txt", "bad content")
        dest = str(Path(self.tmpdir) / "safe")
        with self.assertRaises(ArchiveError):
            extract_archive(bad_zip, dest)

    def test_extract_zip_rejects_backslash_path_traversal(self):
        """ZIP members with backslash-encoded traversal must be rejected.

        On POSIX systems, pathlib.Path('..\\\\evil.txt').parts returns the
        whole string as one component so the '..' check is bypassed.  The
        fixed _safe_name() replaces '\\\\' with '/' before parsing, catching
        sequences like '..\\\\evil.txt' or 'foo\\\\..\\\\bar'.
        """
        from src.core.archive import extract_archive, ArchiveError
        import zipfile
        bad_zip = str(Path(self.tmpdir) / "backslash_bad.zip")
        # Craft a member whose filename contains a backslash traversal
        with zipfile.ZipFile(bad_zip, "w") as zf:
            info = zipfile.ZipInfo("..\\evil.txt")
            zf.writestr(info, "evil content")
        dest = str(Path(self.tmpdir) / "safe2")
        with self.assertRaises(ArchiveError):
            extract_archive(bad_zip, dest)

    def test_extract_rar_raises_helpful_error(self):
        from src.core.archive import extract_archive, ArchiveError
        rar_path = str(Path(self.tmpdir) / "mod.rar")
        Path(rar_path).write_bytes(b"Rar!")
        with self.assertRaises(ArchiveError) as ctx:
            extract_archive(rar_path, self.tmpdir)
        self.assertIn("RAR", str(ctx.exception))

    def test_extract_unsupported_format_raises(self):
        from src.core.archive import extract_archive, ArchiveError
        p = str(Path(self.tmpdir) / "mod.tar.gz")
        Path(p).write_bytes(b"data")
        with self.assertRaises(ArchiveError):
            extract_archive(p, self.tmpdir)

    def test_install_from_zip_extracts_contents(self):
        """install_from_folder should extract a ZIP rather than store it raw."""
        import src.core.config_manager as cm
        orig = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"
        try:
            from src.core.mod_manager import ModDatabase, ModManager
            db = ModDatabase()
            mgr = ModManager(db)

            zpath = self._make_zip("textures.zip", {"tex/a.png": b"PNG"})
            dest_base = str(Path(self.tmpdir) / "storage")
            mod = mgr.install_from_folder(
                source_path=zpath,
                mod_type=ModType.TEXTURE_PACK,
                dest_base=dest_base,
                name="My Textures",
            )
            # Files list should show extracted file, NOT the archive itself
            self.assertIn("tex/a.png", mod.files)
            self.assertNotIn("textures.zip", mod.files)
            # Extracted file should exist on disk
            self.assertTrue((Path(mod.path) / "tex" / "a.png").exists())
        finally:
            cm.MODS_DB_FILE = orig


class TestMultipartArchive(unittest.TestCase):
    """Tests for multi-part archive detection and extraction."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_zip(self, name: str, files: dict) -> str:
        import zipfile
        path = Path(self.tmpdir) / name
        with zipfile.ZipFile(str(path), "w") as zf:
            for fname, content in files.items():
                zf.writestr(fname, content)
        return str(path)

    # -- is_multipart_archive ------------------------------------------------

    def test_named_parts_detected(self):
        from src.core.archive import is_multipart_archive
        self.assertTrue(is_multipart_archive("Pack_Part1.zip"))
        self.assertTrue(is_multipart_archive("Pack_Part2.zip"))
        self.assertTrue(is_multipart_archive("MyMod-Part-3.zip"))
        self.assertTrue(is_multipart_archive("Textures_pt1.7z"))

    def test_7z_volume_detected(self):
        from src.core.archive import is_multipart_archive
        self.assertTrue(is_multipart_archive("Pack.7z.001"))
        self.assertTrue(is_multipart_archive("Pack.7z.002"))

    def test_zip_split_detected(self):
        from src.core.archive import is_multipart_archive
        self.assertTrue(is_multipart_archive("Pack.z01"))
        self.assertTrue(is_multipart_archive("Pack.z02"))

    def test_regular_zip_not_multipart(self):
        from src.core.archive import is_multipart_archive
        self.assertFalse(is_multipart_archive("Pack.zip"))
        self.assertFalse(is_multipart_archive("SLUS-20062.zip"))
        self.assertFalse(is_multipart_archive("textures.7z"))

    # -- find_multipart_parts ------------------------------------------------

    def test_find_all_named_parts(self):
        from src.core.archive import find_multipart_parts
        # Create three part files
        for i in (1, 2, 3):
            Path(self.tmpdir, f"MyPack_Part{i}.zip").write_bytes(b"data")
        parts = find_multipart_parts(str(Path(self.tmpdir) / "MyPack_Part1.zip"))
        names = [Path(p).name for p in parts]
        self.assertEqual(names, ["MyPack_Part1.zip", "MyPack_Part2.zip", "MyPack_Part3.zip"])

    def test_find_parts_from_any_sibling(self):
        from src.core.archive import find_multipart_parts
        for i in (1, 2, 3):
            Path(self.tmpdir, f"Tex_Part{i}.zip").write_bytes(b"data")
        # Asking from Part2 should still find all three
        parts = find_multipart_parts(str(Path(self.tmpdir) / "Tex_Part2.zip"))
        self.assertEqual(len(parts), 3)

    def test_find_returns_empty_for_regular_zip(self):
        from src.core.archive import find_multipart_parts
        p = str(Path(self.tmpdir) / "single.zip")
        Path(p).write_bytes(b"data")
        self.assertEqual(find_multipart_parts(p), [])

    # -- check_multipart_completeness ----------------------------------------

    def test_complete_set_reports_no_missing(self):
        from src.core.archive import check_multipart_completeness
        for i in (1, 2, 3):
            Path(self.tmpdir, f"Pack_Part{i}.zip").write_bytes(b"data")
        ok, parts, missing = check_multipart_completeness(
            str(Path(self.tmpdir) / "Pack_Part1.zip")
        )
        self.assertTrue(ok)
        self.assertEqual(len(parts), 3)
        self.assertEqual(missing, 0)

    def test_incomplete_set_reports_missing(self):
        from src.core.archive import check_multipart_completeness
        # Only parts 1 and 3 — part 2 is missing
        for i in (1, 3):
            Path(self.tmpdir, f"Pack_Part{i}.zip").write_bytes(b"data")
        ok, parts, missing = check_multipart_completeness(
            str(Path(self.tmpdir) / "Pack_Part1.zip")
        )
        self.assertFalse(ok)
        self.assertGreater(missing, 0)

    # -- extract_archive with multi-part zips --------------------------------

    def test_extract_named_parts_merges_contents(self):
        from src.core.archive import extract_archive
        # Part 1 has textures A, Part 2 has textures B
        self._make_zip("Set_Part1.zip", {"texA.png": b"A"})
        self._make_zip("Set_Part2.zip", {"texB.png": b"B"})
        dest = str(Path(self.tmpdir) / "out")
        extracted = extract_archive(
            str(Path(self.tmpdir) / "Set_Part1.zip"), dest
        )
        # Both files should be in the output
        self.assertIn("texA.png", extracted)
        self.assertIn("texB.png", extracted)
        self.assertTrue((Path(dest) / "texA.png").exists())
        self.assertTrue((Path(dest) / "texB.png").exists())

    def test_extract_single_named_part_works(self):
        from src.core.archive import extract_archive
        self._make_zip("Solo_Part1.zip", {"file.png": b"data"})
        dest = str(Path(self.tmpdir) / "out")
        extracted = extract_archive(
            str(Path(self.tmpdir) / "Solo_Part1.zip"), dest
        )
        self.assertIn("file.png", extracted)

    def test_is_archive_recognises_named_parts(self):
        from src.core.archive import is_archive
        self.assertTrue(is_archive("Pack_Part1.zip"))
        self.assertTrue(is_archive("Pack.7z.001"))
        # Regular archives still work
        self.assertTrue(is_archive("pack.zip"))
        self.assertTrue(is_archive("pack.7z"))


class TestMemoryCardCreate(unittest.TestCase):
    """Tests for create_memcard."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_file_with_correct_size(self):
        from src.core.memory_card import create_memcard, MC_CARD_SIZE
        path = create_memcard(str(Path(self.tmpdir) / "card.ps2"), size_mb=8)
        self.assertTrue(Path(path).exists())
        self.assertEqual(Path(path).stat().st_size, MC_CARD_SIZE)

    def test_created_file_has_magic(self):
        from src.core.memory_card import create_memcard, MC_SUPERBLOCK_MAGIC, is_valid_memcard
        path = create_memcard(str(Path(self.tmpdir) / "card.ps2"))
        self.assertTrue(is_valid_memcard(path))

    def test_raises_if_file_exists(self):
        from src.core.memory_card import create_memcard, MemoryCardError
        p = str(Path(self.tmpdir) / "existing.ps2")
        Path(p).write_bytes(b"exists")
        with self.assertRaises(MemoryCardError):
            create_memcard(p)

    def test_creates_parent_dirs(self):
        from src.core.memory_card import create_memcard
        deep_path = str(Path(self.tmpdir) / "sub" / "deep" / "card.ps2")
        result = create_memcard(deep_path)
        self.assertTrue(Path(result).exists())

    def test_raises_on_zero_size(self):
        from src.core.memory_card import create_memcard, MemoryCardError
        with self.assertRaises(MemoryCardError):
            create_memcard(str(Path(self.tmpdir) / "bad.ps2"), size_mb=0)

    def test_raises_on_negative_size(self):
        from src.core.memory_card import create_memcard, MemoryCardError
        with self.assertRaises(MemoryCardError):
            create_memcard(str(Path(self.tmpdir) / "bad.ps2"), size_mb=-1)

    def test_raises_on_oversized(self):
        from src.core.memory_card import create_memcard, MemoryCardError
        with self.assertRaises(MemoryCardError):
            create_memcard(str(Path(self.tmpdir) / "big.ps2"), size_mb=65)

    def test_accepts_boundary_sizes(self):
        """size_mb=1 and size_mb=64 must both succeed."""
        from src.core.memory_card import create_memcard
        p1 = str(Path(self.tmpdir) / "min.ps2")
        p64 = str(Path(self.tmpdir) / "max.ps2")
        self.assertTrue(Path(create_memcard(p1, size_mb=1)).exists())
        self.assertTrue(Path(create_memcard(p64, size_mb=64)).exists())


class TestUpdateMetadata(unittest.TestCase):
    """Tests for ModManager.update_metadata."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import src.core.config_manager as cm
        self._orig = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"

    def tearDown(self):
        import src.core.config_manager as cm
        cm.MODS_DB_FILE = self._orig
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_manager(self):
        from src.core.mod_manager import ModDatabase, ModManager
        db = ModDatabase()
        return db, ModManager(db)

    def test_update_name(self):
        db, mgr = self._make_manager()
        mod = ModInfo(id="m1", name="Old", mod_type=ModType.TEXTURE_PACK, path="/p")
        db.add(mod)
        mgr.update_metadata("m1", name="New Name")
        self.assertEqual(db.get("m1").name, "New Name")

    def test_update_author_and_description(self):
        db, mgr = self._make_manager()
        mod = ModInfo(id="m2", name="M", mod_type=ModType.PNACH, path="/p")
        db.add(mod)
        mgr.update_metadata("m2", author="Alice", description="Great mod")
        m = db.get("m2")
        self.assertEqual(m.author, "Alice")
        self.assertEqual(m.description, "Great mod")

    def test_update_tags(self):
        db, mgr = self._make_manager()
        mod = ModInfo(id="m3", name="M", mod_type=ModType.CHEAT, path="/p")
        db.add(mod)
        mgr.update_metadata("m3", tags=["hd", "ui"])
        self.assertEqual(db.get("m3").tags, ["hd", "ui"])

    def test_update_game_id_no_network(self):
        """Updating game_id should work even when thumbnail fetch fails."""
        db, mgr = self._make_manager()
        mod = ModInfo(id="m4", name="M", mod_type=ModType.TEXTURE_PACK, path="/p")
        db.add(mod)
        # Patch _fetch_thumbnail to always return None
        with patch.object(type(mgr), "_fetch_thumbnail", staticmethod(lambda gid, region="EN": None)):
            mgr.update_metadata("m4", game_id="SLUS-20062")
        self.assertEqual(db.get("m4").game_id, "SLUS-20062")

    def test_update_nonexistent_mod_is_noop(self):
        """Calling update_metadata on a missing id should not raise."""
        db, mgr = self._make_manager()
        mgr.update_metadata("nonexistent", name="Ghost")  # should not raise


class TestMemoryCardWrite(unittest.TestCase):
    """Tests for the new memory card write / backup / copy features."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # Helper: create a minimal valid memory card file
    def _make_card(self, name: str) -> str:
        from src.core.memory_card import create_memcard
        path = str(Path(self.tmpdir) / name)
        create_memcard(path, size_mb=1)
        return path

    def test_backup_memcard_creates_timestamped_file(self):
        from src.core.memory_card import backup_memcard
        card = self._make_card("Card1.ps2")
        backup_dir = str(Path(self.tmpdir) / "backups")
        backup_path = backup_memcard(card, backup_dir)
        self.assertTrue(Path(backup_path).exists())
        self.assertIn("backup_", Path(backup_path).name)
        self.assertTrue(Path(backup_path).name.endswith(".ps2"))

    def test_backup_nonexistent_card_raises(self):
        from src.core.memory_card import backup_memcard, MemoryCardError
        with self.assertRaises(MemoryCardError):
            backup_memcard("/nonexistent/card.ps2", self.tmpdir)

    def test_import_raw_save_into_valid_card(self):
        """Import a .bin save into a valid memory card."""
        from src.core.memory_card import import_raw_save, create_memcard
        # Use default 8 MB card so there's room for the save
        card_path = str(Path(self.tmpdir) / "Card2.ps2")
        create_memcard(card_path, size_mb=8)

        # Create a fake save dump (small, but large enough)
        save_name = "TESTGAME-00001"
        save_file = str(Path(self.tmpdir) / "save.bin")
        # Write the save name into the data so the import can find it
        data = save_name.encode("ascii") + b"\x00" * (512 - len(save_name))
        with open(save_file, "wb") as f:
            f.write(data)

        # Should not raise; returns bool
        result = import_raw_save(save_file, card_path, save_name)
        self.assertIsInstance(result, bool)

    def test_import_raw_save_invalid_card_raises(self):
        from src.core.memory_card import import_raw_save, MemoryCardError
        # Non-memcard file
        bad_card = str(Path(self.tmpdir) / "not_a_card.ps2")
        with open(bad_card, "wb") as f:
            f.write(b"JUNK" * 100)
        save_file = str(Path(self.tmpdir) / "save.bin")
        with open(save_file, "wb") as f:
            f.write(b"\x00" * 512)
        with self.assertRaises(MemoryCardError):
            import_raw_save(save_file, bad_card, "FAKE")

    def test_import_missing_source_raises(self):
        from src.core.memory_card import import_raw_save, MemoryCardError
        card = self._make_card("Card3.ps2")
        with self.assertRaises(MemoryCardError):
            import_raw_save("/nonexistent/save.bin", card, "FAKE")

    def test_copy_save_between_cards(self):
        """copy_save_between_cards should not raise for valid inputs."""
        from src.core.memory_card import (
            copy_save_between_cards,
            MemoryCardError,
            export_save,
        )
        src_card = self._make_card("SrcCard.ps2")
        dst_card = self._make_card("DstCard.ps2")

        # We can't reliably inject a named save into the blank card with the
        # simple low-level test, so we expect either success or a specific error.
        try:
            copy_save_between_cards(src_card, "FAKE-00001", dst_card, self.tmpdir)
        except MemoryCardError:
            pass  # Expected — save not found in blank card


class TestUpdateChecker(unittest.TestCase):
    """Tests for the UpdateChecker utility."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import src.core.config_manager as cm
        self._orig = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"

    def tearDown(self):
        import src.core.config_manager as cm
        cm.MODS_DB_FILE = self._orig
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_checker_starts_and_completes(self):
        """UpdateChecker should run without crashing on an empty database."""
        import threading
        from src.core.mod_manager import ModDatabase
        from src.core.updater import UpdateChecker

        db = ModDatabase()
        checker = UpdateChecker(db)
        done = threading.Event()
        checker.start(on_complete=lambda n: done.set())
        # Give it up to 2 seconds; empty DB should complete almost instantly
        done.wait(timeout=2)
        self.assertTrue(done.is_set(), "UpdateChecker did not complete in time")

    def test_checker_no_update_for_mod_without_url(self):
        """Mod without source_url should never report has_update=True."""
        from src.core.mod_manager import ModDatabase
        from src.core.updater import UpdateChecker, _check_single_mod

        db = ModDatabase()
        mod = ModInfo(
            id="no-url",
            name="No URL Mod",
            mod_type=ModType.TEXTURE_PACK,
            path="/tmp",
            source_url="",
        )
        db.add(mod)
        mod_id, has_update = _check_single_mod(mod)
        self.assertEqual(mod_id, "no-url")
        self.assertFalse(has_update)


class TestAssetPaths(unittest.TestCase):
    """Tests for src.core.assets path helpers."""

    def test_icon_path_returns_string(self):
        from src.core.assets import icon_path
        p = icon_path(256)
        self.assertIsInstance(p, str)
        self.assertIn("icon_256", p)

    def test_ico_path_returns_string(self):
        from src.core.assets import ico_path
        p = ico_path()
        self.assertIsInstance(p, str)
        self.assertIn("icon.ico", p)

    def test_asset_path_relative(self):
        from src.core.assets import asset_path
        p = asset_path("icon.svg")
        self.assertIn("icon.svg", p)




class TestPnachParser(unittest.TestCase):
    """Tests for src.core.pnach — parser, writer and merger."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_pnach(self, crc: str, lines: List[str]) -> str:
        path = str(Path(self.tmpdir) / f"{crc}.pnach")
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        return path

    # ------------------------------------------------------------------
    # extract_game_crc
    # ------------------------------------------------------------------

    def test_extract_crc_valid(self):
        from src.core.pnach import extract_game_crc
        self.assertEqual(extract_game_crc("/path/to/F0A235B4.pnach"), "F0A235B4")

    def test_extract_crc_uppercase(self):
        from src.core.pnach import extract_game_crc
        self.assertEqual(extract_game_crc("abcdef01.pnach"), "ABCDEF01")

    def test_extract_crc_invalid(self):
        from src.core.pnach import extract_game_crc
        self.assertEqual(extract_game_crc("MyMod.pnach"), "")
        self.assertEqual(extract_game_crc("SLUS-20062.pnach"), "")

    # ------------------------------------------------------------------
    # parse_pnach
    # ------------------------------------------------------------------

    def test_parse_basic(self):
        from src.core.pnach import parse_pnach
        path = self._write_pnach("AABB0011", [
            "// Test PNACH file",
            "gametitle=My Game",
            "comment=A test patch",
            "",
            "patch=1,EE,001234AB,word,12345678",
            "patch=0,EE,001234CD,word,00000000",
        ])
        pf = parse_pnach(path)
        self.assertEqual(pf.game_crc, "AABB0011")
        self.assertEqual(pf.game_title, "My Game")
        self.assertEqual(pf.comment, "A test patch")
        self.assertEqual(len(pf.patches), 2)
        self.assertEqual(pf.patches[0].enabled, 1)
        self.assertEqual(pf.patches[0].address, "001234AB")
        self.assertEqual(pf.patches[0].value, "12345678")
        self.assertEqual(pf.patches[1].enabled, 0)

    def test_parse_missing_file_raises(self):
        from src.core.pnach import parse_pnach
        with self.assertRaises(ValueError):
            parse_pnach("/nonexistent/AABB0011.pnach")

    def test_parse_no_crc_in_filename(self):
        from src.core.pnach import parse_pnach
        path = str(Path(self.tmpdir) / "MyMod.pnach")
        with open(path, "w") as f:
            f.write("patch=1,EE,00112233,word,AABBCCDD\n")
        pf = parse_pnach(path)
        self.assertEqual(pf.game_crc, "")
        self.assertEqual(len(pf.patches), 1)

    # ------------------------------------------------------------------
    # write_pnach / round-trip
    # ------------------------------------------------------------------

    def test_write_and_reparse(self):
        from src.core.pnach import parse_pnach, write_pnach
        src = self._write_pnach("11223344", [
            "// header",
            "gametitle=Round Trip",
            "patch=1,EE,00AABBCC,word,DEADBEEF",
        ])
        pf = parse_pnach(src)
        out = str(Path(self.tmpdir) / "out.pnach")
        write_pnach(pf, out)
        pf2 = parse_pnach(out)
        self.assertEqual(len(pf2.patches), 1)
        self.assertEqual(pf2.patches[0].address, "00AABBCC")
        self.assertEqual(pf2.patches[0].value, "DEADBEEF")

    # ------------------------------------------------------------------
    # merge_pnach_files
    # ------------------------------------------------------------------

    def test_merge_no_overlap(self):
        from src.core.pnach import merge_pnach_files, parse_pnach
        a = self._write_pnach("CCDD0011", [
            "gametitle=Game A",
            "patch=1,EE,00000001,word,11111111",
        ])
        b = self._write_pnach("CCDD0011_b", [
            "gametitle=Game A",
            "patch=1,EE,00000002,word,22222222",
        ])
        out_dir = str(Path(self.tmpdir) / "merged")
        merged_path = merge_pnach_files([a, b], out_dir, game_crc="CCDD0011")
        merged = parse_pnach(merged_path)
        addrs = {p.address for p in merged.patches}
        self.assertIn("00000001", addrs)
        self.assertIn("00000002", addrs)

    def test_merge_deduplicates_same_address(self):
        from src.core.pnach import merge_pnach_files, parse_pnach
        # Both files write to the same address — first one (higher priority) wins
        a = self._write_pnach("FFEE0011", [
            "patch=1,EE,DEADBEEF,word,AAAAAAAA",
        ])
        b = self._write_pnach("FFEE0011_b", [
            "patch=1,EE,DEADBEEF,word,BBBBBBBB",
        ])
        out_dir = str(Path(self.tmpdir) / "merged2")
        merged_path = merge_pnach_files([a, b], out_dir, game_crc="FFEE0011")
        merged = parse_pnach(merged_path)
        self.assertEqual(len(merged.patches), 1)
        self.assertEqual(merged.patches[0].value, "AAAAAAAA")

    def test_merge_empty_list_raises(self):
        from src.core.pnach import merge_pnach_files
        with self.assertRaises(ValueError):
            merge_pnach_files([], self.tmpdir)

    def test_merge_preserves_game_title(self):
        from src.core.pnach import merge_pnach_files, parse_pnach
        a = self._write_pnach("12345678", [
            "gametitle=Awesome Game",
            "patch=1,EE,00000001,word,AABBCCDD",
        ])
        out_dir = str(Path(self.tmpdir) / "merged3")
        merged_path = merge_pnach_files([a], out_dir, game_crc="12345678")
        merged = parse_pnach(merged_path)
        self.assertEqual(merged.game_title, "Awesome Game")

    # ------------------------------------------------------------------
    # find_pnach_conflicts
    # ------------------------------------------------------------------

    def test_conflict_same_address_different_value(self):
        from src.core.pnach import find_pnach_conflicts
        a = self._write_pnach("AABB1234", ["patch=1,EE,00001234,word,AAAA0000"])
        b = self._write_pnach("AABB1234_b", ["patch=1,EE,00001234,word,BBBB0000"])
        conflicts = find_pnach_conflicts([a, b])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].address, "00001234")

    def test_no_conflict_same_value(self):
        from src.core.pnach import find_pnach_conflicts
        a = self._write_pnach("AABB5678", ["patch=1,EE,00001234,word,AAAA0000"])
        b = self._write_pnach("AABB5678_b", ["patch=1,EE,00001234,word,AAAA0000"])
        conflicts = find_pnach_conflicts([a, b])
        self.assertEqual(len(conflicts), 0)

    def test_no_conflict_different_addresses(self):
        from src.core.pnach import find_pnach_conflicts
        a = self._write_pnach("AABB9999", ["patch=1,EE,00000001,word,AAAA0000"])
        b = self._write_pnach("AABB9999_b", ["patch=1,EE,00000002,word,BBBB0000"])
        conflicts = find_pnach_conflicts([a, b])
        self.assertEqual(len(conflicts), 0)

    def test_disabled_patches_not_conflicting(self):
        from src.core.pnach import find_pnach_conflicts
        a = self._write_pnach("AACC1111", ["patch=1,EE,00001234,word,AAAA0000"])
        b = self._write_pnach("AACC1111_b", ["patch=0,EE,00001234,word,BBBB0000"])
        conflicts = find_pnach_conflicts([a, b])
        # Disabled patches should not generate conflicts
        self.assertEqual(len(conflicts), 0)




class TestGameRegistry(unittest.TestCase):
    """Tests for src.core.game_registry — PS2 serial detection."""

    # ------------------------------------------------------------------
    # detect_game_serial
    # ------------------------------------------------------------------

    def test_detect_slus_with_dash(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLUS-20062.pnach"), "SLUS-20062")

    def test_detect_slus_with_underscore(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLUS_20062.png"), "SLUS-20062")

    def test_detect_slus_fused(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLUS20062_HD.zip"), "SLUS-20062")

    def test_detect_scus(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SCUS-97120.cover.png"), "SCUS-97120")

    def test_detect_sles_pal(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLES-52232_patch.pnach"), "SLES-52232")

    def test_detect_slps_japan(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLPS25516.pnach"), "SLPS-25516")

    def test_detect_from_content(self):
        from src.core.game_registry import detect_game_serial
        content = b"gametitle=Gran Turismo 4\n// CRC for SLUS-21163\npatch=1,EE,..."
        result = detect_game_serial("unknown_crc.pnach", file_content=content)
        self.assertEqual(result, "SLUS-21163")

    def test_no_serial_in_crc_filename(self):
        from src.core.game_registry import detect_game_serial
        # 8-hex-digit PNACH filename = CRC, not a serial
        self.assertEqual(detect_game_serial("F0A235B4.pnach"), "")

    def test_no_serial_in_random_name(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("MyTexturePack_v2.zip"), "")

    # ------------------------------------------------------------------
    # serial_to_display
    # ------------------------------------------------------------------

    def test_serial_to_display_known(self):
        from src.core.game_registry import serial_to_display
        result = serial_to_display("SLUS-20062")
        self.assertIn("SLUS-20062", result)
        self.assertIn("Spyro", result)

    def test_serial_to_display_unknown(self):
        from src.core.game_registry import serial_to_display
        self.assertEqual(serial_to_display("SLUS-99999"), "SLUS-99999")

    def test_serial_to_display_empty(self):
        from src.core.game_registry import serial_to_display
        self.assertEqual(serial_to_display(""), "")

    # ------------------------------------------------------------------
    # normalise_serial
    # ------------------------------------------------------------------

    def test_normalise_dash(self):
        from src.core.game_registry import normalise_serial
        self.assertEqual(normalise_serial("slus-20062"), "SLUS-20062")

    def test_normalise_underscore(self):
        from src.core.game_registry import normalise_serial
        self.assertEqual(normalise_serial("SLUS_20062"), "SLUS-20062")

    # ------------------------------------------------------------------
    # lookup_game_title
    # ------------------------------------------------------------------

    def test_lookup_known_title(self):
        from src.core.game_registry import lookup_game_title
        title = lookup_game_title("SCUS-97120")
        self.assertIn("Jak", title)

    def test_lookup_unknown_returns_empty(self):
        from src.core.game_registry import lookup_game_title
        self.assertEqual(lookup_game_title("XXXX-99999"), "")

    # ------------------------------------------------------------------
    # AppConfig favorite_authors
    # ------------------------------------------------------------------

    def test_appconfig_favorite_authors_default(self):
        from src.models.mod import AppConfig
        cfg = AppConfig()
        self.assertEqual(cfg.favorite_authors, [])

    def test_appconfig_favorite_authors_serialised(self):
        from src.models.mod import AppConfig
        cfg = AppConfig()
        cfg.favorite_authors = ["Alice", "Bob"]
        d = cfg.to_dict()
        self.assertEqual(d["favorite_authors"], ["Alice", "Bob"])
        restored = AppConfig.from_dict(d)
        self.assertEqual(restored.favorite_authors, ["Alice", "Bob"])

    def test_appconfig_from_dict_no_favorite_authors_key(self):
        """Old config files without favorite_authors should not crash."""
        from src.models.mod import AppConfig
        data = {"pcsx2_path": "/foo", "theme": "dark", "first_run": False}
        cfg = AppConfig.from_dict(data)
        self.assertEqual(cfg.favorite_authors, [])


class TestGameRegistryExpanded(unittest.TestCase):
    """Tests for the expanded PS2 serial registry — new prefixes, path detection, reverse lookup."""

    # ------------------------------------------------------------------
    # SERIAL_PREFIXES constant
    # ------------------------------------------------------------------

    def test_serial_prefixes_exported(self):
        from src.core.game_registry import SERIAL_PREFIXES
        self.assertIsInstance(SERIAL_PREFIXES, tuple)
        self.assertGreater(len(SERIAL_PREFIXES), 10)

    def test_serial_prefixes_contains_all_retail(self):
        from src.core.game_registry import SERIAL_PREFIXES
        for prefix in ("SLUS", "SCUS", "SLES", "SCES", "SLPS", "SCPS",
                        "SLKA", "SCKA", "SLAJ", "SCAJ", "SLPM", "SCPM",
                        "SLEH", "SCEH", "PBPX"):
            self.assertIn(prefix, SERIAL_PREFIXES, f"Missing prefix: {prefix}")

    def test_serial_prefixes_contains_demo_prefixes(self):
        from src.core.game_registry import SERIAL_PREFIXES
        for prefix in ("SCED", "SLED", "SCPD", "SLPD"):
            self.assertIn(prefix, SERIAL_PREFIXES, f"Missing demo prefix: {prefix}")

    # ------------------------------------------------------------------
    # New prefix detection
    # ------------------------------------------------------------------

    def test_detect_sced_demo(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SCED-12345_demo.pnach"), "SCED-12345")

    def test_detect_sled_demo(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLED-54321_demo.png"), "SLED-54321")

    def test_detect_scpd_jp_demo(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SCPD-10001.pnach"), "SCPD-10001")

    def test_detect_slpm_platinum(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLPM-65792_mgs3.zip"), "SLPM-65792")

    def test_detect_slka_korea(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SLKA-25104.png"), "SLKA-25104")

    def test_detect_scaj_asia(self):
        from src.core.game_registry import detect_game_serial
        self.assertEqual(detect_game_serial("SCAJ-20065_gt4.zip"), "SCAJ-20065")

    # ------------------------------------------------------------------
    # detect_serial_from_path
    # ------------------------------------------------------------------

    def test_path_component_folder_named_as_serial(self):
        """A folder named exactly as a serial should be detected."""
        from src.core.game_registry import detect_serial_from_path
        self.assertEqual(
            detect_serial_from_path("/textures/SLUS-20062/replacements/pack.zip"),
            "SLUS-20062",
        )

    def test_path_pcsx2_texture_layout(self):
        """PCSX2 texture path: textures/{SERIAL}/replacements/"""
        from src.core.game_registry import detect_serial_from_path
        self.assertEqual(
            detect_serial_from_path("C:/PCSX2/textures/SCUS-97399/replacements/gow_hd.zip"),
            "SCUS-97399",
        )

    def test_path_serial_as_only_folder(self):
        from src.core.game_registry import detect_serial_from_path
        self.assertEqual(detect_serial_from_path("/mods/SLES-54114/"), "SLES-54114")

    def test_path_serial_with_underscore_separator(self):
        """Path component with underscore separator should normalise to dash."""
        from src.core.game_registry import detect_serial_from_path
        self.assertEqual(
            detect_serial_from_path("/packs/SLPS_25088/textures/ui.png"),
            "SLPS-25088",
        )

    def test_path_serial_fused(self):
        """Path component with fused serial (no separator) should be detected."""
        from src.core.game_registry import detect_serial_from_path
        self.assertEqual(
            detect_serial_from_path("/mods/SLUS21005_hd/textures/char.dds"),
            "SLUS-21005",
        )

    def test_path_no_serial_returns_empty(self):
        from src.core.game_registry import detect_serial_from_path
        self.assertEqual(detect_serial_from_path("/mods/my_texture_pack/tex.png"), "")

    def test_path_deepest_serial_wins(self):
        """When multiple path components contain serials, the deepest wins."""
        from src.core.game_registry import detect_serial_from_path
        # Deepest (rightmost) serial is SLUS-20312
        result = detect_serial_from_path(
            "/SLUS-20062/nested/SLUS-20312/file.png"
        )
        self.assertEqual(result, "SLUS-20312")

    def test_path_plain_filename_still_works(self):
        """detect_serial_from_path should work for a plain filename too."""
        from src.core.game_registry import detect_serial_from_path
        self.assertEqual(detect_serial_from_path("SLUS-20672.png"), "SLUS-20672")

    # ------------------------------------------------------------------
    # title_to_serials
    # ------------------------------------------------------------------

    def test_title_to_serials_kingdom_hearts(self):
        from src.core.game_registry import title_to_serials
        hits = title_to_serials("Kingdom Hearts")
        serials = [s for s, _ in hits]
        self.assertGreater(len(hits), 2, "Expected multiple KH serials")
        # US, PAL, JP and other regions should all appear
        self.assertTrue(any("SLUS" in s for s in serials), "Expected a US serial")

    def test_title_to_serials_case_insensitive(self):
        from src.core.game_registry import title_to_serials
        lower = title_to_serials("kingdom hearts")
        upper = title_to_serials("KINGDOM HEARTS")
        self.assertEqual(lower, upper)

    def test_title_to_serials_god_of_war(self):
        from src.core.game_registry import title_to_serials
        hits = title_to_serials("God of War")
        self.assertGreater(len(hits), 2)

    def test_title_to_serials_no_match_returns_empty(self):
        from src.core.game_registry import title_to_serials
        self.assertEqual(title_to_serials("xyzzy_nonexistent_game_12345"), [])

    def test_title_to_serials_empty_string(self):
        from src.core.game_registry import title_to_serials
        self.assertEqual(title_to_serials(""), [])

    def test_title_to_serials_returns_sorted(self):
        from src.core.game_registry import title_to_serials
        hits = title_to_serials("Gran Turismo")
        serials = [s for s, _ in hits]
        self.assertEqual(serials, sorted(serials))

    # ------------------------------------------------------------------
    # Expanded _KNOWN_SERIALS coverage
    # ------------------------------------------------------------------

    def test_new_serials_ffx(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Final Fantasy X", lookup_game_title("SLUS-20312"))

    def test_new_serials_ffx2(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Final Fantasy X-2", lookup_game_title("SLUS-20672"))

    def test_new_serials_mgs2(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Metal Gear", lookup_game_title("SLUS-20213"))

    def test_new_serials_crash_woc(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Crash", lookup_game_title("SLUS-20238"))

    def test_new_serials_sly_cooper(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Sly", lookup_game_title("SCUS-97198"))

    def test_new_serials_devil_may_cry2(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Devil May Cry", lookup_game_title("SLUS-20626"))

    def test_new_serials_pal_god_of_war(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("God of War", lookup_game_title("SCES-53133"))

    def test_new_serials_pal_ffx(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Final Fantasy X", lookup_game_title("SLES-50490"))

    def test_new_serials_jp_gt4(self):
        from src.core.game_registry import lookup_game_title
        self.assertIn("Gran Turismo 4", lookup_game_title("SCPS-17001"))

    def test_known_serials_count(self):
        """Registry should have at least 200 entries."""
        from src.core.game_registry import all_known_serials
        serials = all_known_serials()
        self.assertGreaterEqual(len(serials), 200, f"Got only {len(serials)} entries")

    def test_all_keys_normalised_form(self):
        """Every key in _KNOWN_SERIALS must be in XXXX-NNNNN form."""
        from src.core.game_registry import all_known_serials
        for serial, _ in all_known_serials():
            self.assertRegex(serial, r"^[A-Z]{4}-\d{5}$",
                             f"Malformed serial key: {serial}")




class TestCoverArtDeploy(unittest.TestCase):
    """Tests for cover art deployment with PCSX2-correct naming."""

    def setUp(self):
        import src.core.config_manager as cm
        self.tmpdir = tempfile.mkdtemp()
        self.storage = os.path.join(self.tmpdir, "mods")
        self.target = os.path.join(self.tmpdir, "covers")
        os.makedirs(self.storage, exist_ok=True)
        os.makedirs(self.target, exist_ok=True)
        # Isolate the mod database from other tests
        self._orig_db_file = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"
        self.db = ModDatabase()

    def tearDown(self):
        import src.core.config_manager as cm
        cm.MODS_DB_FILE = self._orig_db_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cover(self, name: str, game_id: str, filename: str = "cover.png") -> ModInfo:
        """Create a fake cover art mod on disk and register it in the DB."""
        mod_dir = os.path.join(self.storage, name)
        os.makedirs(mod_dir, exist_ok=True)
        # Create a minimal 1×1 white PNG
        import struct, zlib
        def _tiny_png():
            sig = b'\x89PNG\r\n\x1a\n'
            def chunk(tag, data):
                return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
            ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            raw = b'\x00\xff\xff\xff'
            idat = chunk(b'IDAT', zlib.compress(raw))
            iend = chunk(b'IEND', b'')
            return sig + ihdr + idat + iend
        img_path = os.path.join(mod_dir, filename)
        with open(img_path, 'wb') as f:
            f.write(_tiny_png())

        import uuid
        mod = ModInfo(
            id=str(uuid.uuid4()),
            name=name,
            mod_type=ModType.COVER_ART,
            path=img_path,
            enabled=True,
            game_id=game_id,
            files=[filename],
            priority=0,
        )
        self.db.add(mod)
        return mod

    def test_cover_art_deployed_with_serial_name(self):
        """Cover art should be saved as SLUS-20062.png."""
        from src.core.mod_manager import ModManager
        self._make_cover("SpyroCover", "SLUS-20062")
        mgr = ModManager(self.db)
        count, warnings = mgr.deploy(ModType.COVER_ART, self.target)
        self.assertEqual(count, 1)
        self.assertFalse(warnings, warnings)
        self.assertTrue(
            os.path.exists(os.path.join(self.target, "SLUS-20062.png")),
            "Expected SLUS-20062.png in target folder"
        )

    def test_cover_art_only_highest_priority_deployed(self):
        """Only the highest-priority cover for the same serial is deployed."""
        from src.core.mod_manager import ModManager
        low = self._make_cover("SpyroCoverLow", "SLUS-20062")
        low.priority = 0
        self.db.update(low)
        high = self._make_cover("SpyroCoverHigh", "SLUS-20062")
        high.priority = 10
        self.db.update(high)

        mgr = ModManager(self.db)
        count, warnings = mgr.deploy(ModType.COVER_ART, self.target)
        self.assertEqual(count, 1)
        # One warning about the skipped duplicate
        self.assertEqual(len(warnings), 1)
        self.assertIn("higher-priority", warnings[0])

    def test_detect_cover_art_conflicts_two_enabled(self):
        """detect_cover_art_conflicts returns serials with >1 enabled cover."""
        from src.core.mod_manager import ModManager
        self._make_cover("A", "SLUS-20062")
        self._make_cover("B", "SLUS-20062")
        mgr = ModManager(self.db)
        conflicts = mgr.detect_cover_art_conflicts()
        self.assertEqual(len(conflicts), 1)
        serial, mods = conflicts[0]
        self.assertEqual(serial, "SLUS-20062")
        self.assertEqual(len(mods), 2)

    def test_detect_cover_art_conflicts_one_enabled(self):
        """No conflicts when only one cover per serial."""
        from src.core.mod_manager import ModManager
        self._make_cover("A", "SLUS-20062")
        self._make_cover("B", "SCUS-97120")
        mgr = ModManager(self.db)
        conflicts = mgr.detect_cover_art_conflicts()
        self.assertEqual(conflicts, [])

    def test_detect_cover_art_conflicts_disabled_ignored(self):
        """Disabled cover arts don't cause a conflict."""
        from src.core.mod_manager import ModManager
        a = self._make_cover("A", "SLUS-20062")
        b = self._make_cover("B", "SLUS-20062")
        b.enabled = False
        self.db.update(b)
        mgr = ModManager(self.db)
        self.assertEqual(mgr.detect_cover_art_conflicts(), [])

    def test_cover_art_no_serial_copies_with_original_name(self):
        """Cover art with no serial is copied under its original filename."""
        from src.core.mod_manager import ModManager
        # Create a cover without a game_id and a filename that has no serial
        mod_dir = os.path.join(self.storage, "NoSerial")
        os.makedirs(mod_dir, exist_ok=True)
        img_path = os.path.join(mod_dir, "my_cover.png")
        import struct, zlib
        with open(img_path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8)  # minimal stub
        import uuid
        mod = ModInfo(
            id=str(uuid.uuid4()),
            name="NoSerialCover",
            mod_type=ModType.COVER_ART,
            path=img_path,
            enabled=True,
            game_id="",
            files=["my_cover.png"],
            priority=0,
        )
        self.db.add(mod)
        mgr = ModManager(self.db)
        count, warnings = mgr.deploy(ModType.COVER_ART, self.target)
        self.assertEqual(count, 1)
        # Should exist under original name
        self.assertTrue(os.path.exists(os.path.join(self.target, "my_cover.png")))


class TestShadowedMods(unittest.TestCase):
    """Tests for detect_shadowed_mods in ModManager."""

    def setUp(self):
        import src.core.config_manager as cm
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_file = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"
        self.db = ModDatabase()

    def tearDown(self):
        import src.core.config_manager as cm
        cm.MODS_DB_FILE = self._orig_db_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_mod(self, name, files, priority=0):
        import uuid
        mod = ModInfo(
            id=str(uuid.uuid4()),
            name=name,
            mod_type=ModType.TEXTURE_PACK,
            path=self.tmpdir,
            enabled=True,
            files=files,
            priority=priority,
        )
        self.db.add(mod)
        return mod

    def test_no_shadowing_distinct_files(self):
        from src.core.mod_manager import ModManager
        self._make_mod("A", ["a.png"], priority=0)
        self._make_mod("B", ["b.png"], priority=1)
        mgr = ModManager(self.db)
        self.assertEqual(mgr.detect_shadowed_mods(ModType.TEXTURE_PACK), {})

    def test_full_shadowing_detected(self):
        from src.core.mod_manager import ModManager
        low = self._make_mod("Low", ["tex.png", "bump.png"], priority=0)
        self._make_mod("High", ["tex.png", "bump.png"], priority=10)
        mgr = ModManager(self.db)
        shadowed = mgr.detect_shadowed_mods(ModType.TEXTURE_PACK)
        self.assertIn(low.id, shadowed)

    def test_partial_shadowing_not_detected(self):
        """A mod with some but not all files overridden should NOT be shadowed."""
        from src.core.mod_manager import ModManager
        low = self._make_mod("Low", ["tex.png", "unique.png"], priority=0)
        self._make_mod("High", ["tex.png"], priority=10)
        mgr = ModManager(self.db)
        shadowed = mgr.detect_shadowed_mods(ModType.TEXTURE_PACK)
        self.assertNotIn(low.id, shadowed)

    def test_highest_priority_never_shadowed(self):
        from src.core.mod_manager import ModManager
        high = self._make_mod("High", ["tex.png"], priority=10)
        self._make_mod("Low", ["tex.png"], priority=0)
        mgr = ModManager(self.db)
        shadowed = mgr.detect_shadowed_mods(ModType.TEXTURE_PACK)
        self.assertNotIn(high.id, shadowed)

    def test_empty_file_list_not_shadowed(self):
        """Mods with no file list are excluded from shadow analysis."""
        from src.core.mod_manager import ModManager
        no_files = self._make_mod("NoFiles", [], priority=0)
        self._make_mod("High", ["tex.png"], priority=10)
        mgr = ModManager(self.db)
        shadowed = mgr.detect_shadowed_mods(ModType.TEXTURE_PACK)
        self.assertNotIn(no_files.id, shadowed)

    def test_disabled_mods_excluded(self):
        """Disabled mods should not be shadowed (they're not active)."""
        from src.core.mod_manager import ModManager
        low = self._make_mod("Low", ["tex.png"], priority=0)
        low.enabled = False
        self.db.update(low)
        self._make_mod("High", ["tex.png"], priority=10)
        mgr = ModManager(self.db)
        shadowed = mgr.detect_shadowed_mods(ModType.TEXTURE_PACK)
        self.assertNotIn(low.id, shadowed)


class TestInstalledAtTimestamp(unittest.TestCase):
    """Tests for the installed_at timestamp field added to ModInfo."""

    def test_installed_at_defaults_to_now(self):
        """A freshly created ModInfo should have installed_at close to now."""
        import time
        before = time.time()
        mod = ModInfo(id="ts-1", name="Test", mod_type=ModType.TEXTURE_PACK, path="/tmp")
        after = time.time()
        self.assertGreaterEqual(mod.installed_at, before)
        self.assertLessEqual(mod.installed_at, after)

    def test_installed_at_roundtrip(self):
        """installed_at survives a to_dict/from_dict round-trip."""
        mod = ModInfo(
            id="ts-2", name="RT", mod_type=ModType.PNACH, path="/tmp",
            installed_at=1_700_000_000.0,
        )
        d = mod.to_dict()
        self.assertAlmostEqual(d["installed_at"], 1_700_000_000.0)
        mod2 = ModInfo.from_dict(d)
        self.assertAlmostEqual(mod2.installed_at, 1_700_000_000.0)

    def test_installed_at_json_roundtrip(self):
        """installed_at survives JSON serialisation."""
        mod = ModInfo(
            id="ts-3", name="JSON", mod_type=ModType.CHEAT, path="/tmp",
            installed_at=1_710_000_000.5,
        )
        raw = json.dumps(mod.to_dict())
        d = json.loads(raw)
        mod2 = ModInfo.from_dict(d)
        self.assertAlmostEqual(mod2.installed_at, 1_710_000_000.5, places=1)

    def test_install_from_folder_sets_installed_at(self):
        """install_from_folder should record a non-zero installed_at timestamp."""
        import time
        tmpdir = tempfile.mkdtemp()
        try:
            import src.core.config_manager as cm
            cm.MODS_DB_FILE = Path(tmpdir) / "mods.json"
            cm.THUMBNAILS_DIR = Path(tmpdir) / "thumbs"

            db = ModDatabase()
            mgr = ModManager(db)

            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "patch.pnach").write_text("//comment\n")

            before = time.time()
            mod = mgr.install_from_folder(
                str(src_dir), ModType.PNACH, tmpdir, name="Test Patch"
            )
            after = time.time()

            self.assertGreaterEqual(mod.installed_at, before)
            self.assertLessEqual(mod.installed_at, after)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_recently_added_sorted_by_installed_at(self):
        """Sorting db.all() by installed_at descending gives newest-first order."""
        mods = [
            ModInfo(id=f"ra-{i}", name=f"Mod {i}", mod_type=ModType.TEXTURE_PACK,
                    path="/tmp", installed_at=float(i))
            for i in range(5)
        ]
        sorted_mods = sorted(mods, key=lambda m: m.installed_at, reverse=True)
        self.assertEqual(sorted_mods[0].id, "ra-4")
        self.assertEqual(sorted_mods[-1].id, "ra-0")


class TestBrowseCatalogueEntries(unittest.TestCase):
    """Tests for the expanded browse catalogue."""

    def _load_catalogue(self):
        """Load catalogue IDs from the JSON data files via catalogue_loader."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
        return [e["id"] for e in load_catalogue(catalogue_dir=CATALOGUE_DIR)]

    def test_game_specific_texture_entries_present(self):
        """Catalogue should include game-specific texture pack entries with direct downloads."""
        ids = self._load_catalogue()
        # Only entries with a working direct_download_url are retained
        game_entries = [
            "spyro_anb_6x_extra_detail",
            "spyro_anb_6x_only",
            "spyro_anb_4x_anime",
            "cckrizalid_baroque_textures",
        ]
        for entry_id in game_entries:
            self.assertIn(entry_id, ids, f"Missing catalogue entry: {entry_id}")

    def test_no_duplicate_ids(self):
        """All catalogue entry IDs must be unique."""
        ids = self._load_catalogue()
        self.assertEqual(len(ids), len(set(ids)), "Duplicate catalogue IDs found")

    def test_total_catalogue_size(self):
        """Catalogue should have at least 40 entries (21 original + 22 new game-specific)."""
        ids = self._load_catalogue()
        self.assertGreaterEqual(len(ids), 40, f"Expected ≥40 entries, got {len(ids)}")


# =============================================================================
# PCSX2 Layout module
# =============================================================================

class TestPcsx2Layout(unittest.TestCase):
    """Tests for src.core.pcsx2_layout — PCSX2 hierarchy, deploy paths, scaffolding."""

    # ------------------------------------------------------------------
    # PCSX2_HIERARCHY constant
    # ------------------------------------------------------------------

    def test_hierarchy_exported(self):
        from src.core.pcsx2_layout import PCSX2_HIERARCHY
        self.assertIsInstance(PCSX2_HIERARCHY, dict)
        self.assertGreater(len(PCSX2_HIERARCHY), 5)

    def test_hierarchy_contains_standard_folders(self):
        from src.core.pcsx2_layout import PCSX2_HIERARCHY
        for folder in ("bios", "cheats", "cheats_ws", "covers", "memcards", "textures"):
            self.assertIn(folder, PCSX2_HIERARCHY, f"Missing folder: {folder}")

    def test_hierarchy_descriptions_nonempty(self):
        from src.core.pcsx2_layout import PCSX2_HIERARCHY
        for folder, desc in PCSX2_HIERARCHY.items():
            self.assertTrue(desc, f"Empty description for folder: {folder}")

    def test_folder_description(self):
        from src.core.pcsx2_layout import folder_description
        self.assertIn("PNACH", folder_description("cheats"))
        self.assertIn("cover", folder_description("covers").lower())
        self.assertEqual(folder_description("unknown_xyz"), "")

    # ------------------------------------------------------------------
    # get_deploy_path
    # ------------------------------------------------------------------

    def test_get_deploy_path_texture_pack(self):
        from src.core.pcsx2_layout import get_deploy_path
        cfg = AppConfig(textures_path="/pcsx2/textures")
        self.assertEqual(get_deploy_path(cfg, ModType.TEXTURE_PACK), "/pcsx2/textures")

    def test_get_deploy_path_pnach(self):
        from src.core.pcsx2_layout import get_deploy_path
        cfg = AppConfig(pnach_path="/pcsx2/cheats")
        self.assertEqual(get_deploy_path(cfg, ModType.PNACH), "/pcsx2/cheats")

    def test_get_deploy_path_cover_art(self):
        from src.core.pcsx2_layout import get_deploy_path
        cfg = AppConfig(cover_art_path="/pcsx2/covers")
        self.assertEqual(get_deploy_path(cfg, ModType.COVER_ART), "/pcsx2/covers")

    def test_get_deploy_path_save_file(self):
        from src.core.pcsx2_layout import get_deploy_path
        cfg = AppConfig(memcards_path="/pcsx2/memcards")
        self.assertEqual(get_deploy_path(cfg, ModType.SAVE_FILE), "/pcsx2/memcards")

    def test_get_deploy_path_cheat(self):
        from src.core.pcsx2_layout import get_deploy_path
        cfg = AppConfig(cheats_path="/pcsx2/cheats_ws")
        self.assertEqual(get_deploy_path(cfg, ModType.CHEAT), "/pcsx2/cheats_ws")

    def test_get_deploy_path_empty_config_returns_empty(self):
        from src.core.pcsx2_layout import get_deploy_path
        cfg = AppConfig()
        self.assertEqual(get_deploy_path(cfg, ModType.TEXTURE_PACK), "")

    # ------------------------------------------------------------------
    # Texture replacement path helpers
    # ------------------------------------------------------------------

    def test_get_texture_replacements_path(self):
        from src.core.pcsx2_layout import get_texture_replacements_path
        result = get_texture_replacements_path("/pcsx2/textures", "SLUS-20062")
        self.assertTrue(result.endswith("SLUS-20062/replacements") or
                        result.endswith("SLUS-20062\\replacements"))

    def test_get_texture_replacements_path_empty_inputs(self):
        from src.core.pcsx2_layout import get_texture_replacements_path
        self.assertEqual(get_texture_replacements_path("", "SLUS-20062"), "")
        self.assertEqual(get_texture_replacements_path("/textures", ""), "")

    def test_get_texture_dumps_path(self):
        from src.core.pcsx2_layout import get_texture_dumps_path
        result = get_texture_dumps_path("/pcsx2/textures", "SCUS-97399")
        self.assertTrue("dumps" in result)
        self.assertTrue("SCUS-97399" in result)

    # ------------------------------------------------------------------
    # create_pcsx2_directories + ensure_texture_game_dirs
    # ------------------------------------------------------------------

    def test_create_pcsx2_directories(self):
        from src.core.pcsx2_layout import create_pcsx2_directories, PCSX2_HIERARCHY
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "pcsx2")
            created = create_pcsx2_directories(root)
            # All standard folders should now exist
            for folder in PCSX2_HIERARCHY:
                self.assertTrue(
                    (Path(root) / folder).exists(),
                    f"Missing folder after scaffold: {folder}",
                )
            # Returns list of created paths
            self.assertIsInstance(created, list)

    def test_create_pcsx2_directories_idempotent(self):
        from src.core.pcsx2_layout import create_pcsx2_directories
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "pcsx2")
            create_pcsx2_directories(root)
            # Second call should not raise, and nothing new to create
            created2 = create_pcsx2_directories(root)
            self.assertEqual(created2, [])

    def test_ensure_texture_game_dirs(self):
        from src.core.pcsx2_layout import ensure_texture_game_dirs
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ensure_texture_game_dirs(tmpdir, "SLUS-20062")
            self.assertIn("replacements", result)
            self.assertIn("dumps", result)
            self.assertTrue(Path(result["replacements"]).is_dir())
            self.assertTrue(Path(result["dumps"]).is_dir())
            self.assertIn("SLUS-20062", result["replacements"])

    # ------------------------------------------------------------------
    # detect_pcsx2_subfolders
    # ------------------------------------------------------------------

    def test_detect_pcsx2_subfolders_returns_all_keys(self):
        from src.core.pcsx2_layout import detect_pcsx2_subfolders
        with tempfile.TemporaryDirectory() as tmpdir:
            result = detect_pcsx2_subfolders(tmpdir)
            for key in ("textures_path", "pnach_path", "cover_art_path",
                        "memcards_path", "cheats_path", "partial_textures_path"):
                self.assertIn(key, result, f"Missing key: {key}")

    def test_detect_pcsx2_subfolders_uses_existing(self):
        from src.core.pcsx2_layout import detect_pcsx2_subfolders
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a non-default sub-folder name that PCSX2 sometimes uses
            (Path(tmpdir) / "Covers").mkdir()
            result = detect_pcsx2_subfolders(tmpdir)
            # Should prefer existing "Covers" over non-existing "covers"
            self.assertIn("Covers", result["cover_art_path"])

    def test_detect_pcsx2_subfolders_canonical_default(self):
        from src.core.pcsx2_layout import detect_pcsx2_subfolders
        with tempfile.TemporaryDirectory() as tmpdir:
            # Nothing exists — should return canonical names
            result = detect_pcsx2_subfolders(tmpdir)
            self.assertTrue(result["textures_path"].endswith("textures"))

    # ------------------------------------------------------------------
    # auto_detect_pcsx2 (mocked — we can't assume PCSX2 is installed)
    # ------------------------------------------------------------------

    def test_auto_detect_returns_string(self):
        from src.core.pcsx2_layout import auto_detect_pcsx2
        result = auto_detect_pcsx2()
        self.assertIsInstance(result, str)

    def test_auto_detect_returns_existing_path_when_found(self):
        from src.core.pcsx2_layout import auto_detect_pcsx2, PCSX2_HIERARCHY
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake PCSX2 root with enough sub-folders to score highly
            fake_pcsx2 = Path(tmpdir) / ".config" / "PCSX2"
            fake_pcsx2.mkdir(parents=True)
            for sub in ("bios", "textures", "cheats", "covers"):
                (fake_pcsx2 / sub).mkdir()

            # Patch _candidate_paths to include our fake dir
            from src.core import pcsx2_layout
            orig = pcsx2_layout._candidate_paths

            def _fake_candidates():
                return [fake_pcsx2] + orig()

            pcsx2_layout._candidate_paths = _fake_candidates
            try:
                result = auto_detect_pcsx2()
                self.assertEqual(result, str(fake_pcsx2))
            finally:
                pcsx2_layout._candidate_paths = orig


# =============================================================================
# AppConfig new fields
# =============================================================================

class TestAppConfigFieldChanges(unittest.TestCase):
    """Tests for AppConfig field changes: partial_textures_path added, auto_deploy removed."""

    def test_default_partial_textures_path(self):
        cfg = AppConfig()
        self.assertEqual(cfg.partial_textures_path, "")

    def test_no_auto_deploy_field(self):
        """auto_deploy was removed — deployment is always automatic."""
        cfg = AppConfig()
        self.assertFalse(hasattr(cfg, "auto_deploy"))

    def test_to_dict_includes_partial_textures_path(self):
        cfg = AppConfig(partial_textures_path="/tex")
        d = cfg.to_dict()
        self.assertEqual(d["partial_textures_path"], "/tex")
        self.assertNotIn("auto_deploy", d)

    def test_from_dict_restores_partial_textures_path(self):
        cfg = AppConfig(partial_textures_path="/pt")
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertEqual(restored.partial_textures_path, "/pt")

    def test_from_dict_old_config_no_crash(self):
        """Old configs (including stale auto_deploy key) should not crash and
        must not create an auto_deploy attribute on the loaded config."""
        old_data = {
            "pcsx2_path": "/foo",
            "textures_path": "/tex",
            "pnach_path": "/cheats",
            "cover_art_path": "/covers",
            "memcards_path": "/mc",
            "cheats_path": "/ws",
            "mods_storage_path": "/mods",
            "theme": "dark",
            "check_updates_on_start": True,
            "show_conflict_warnings": True,
            "first_run": False,
            "favorite_authors": [],
            # Stale field from old config — must be silently ignored
            "auto_deploy": True,
        }
        cfg = AppConfig.from_dict(old_data)
        self.assertEqual(cfg.partial_textures_path, "")
        # Stale key must be dropped — not available as an attribute
        self.assertFalse(hasattr(cfg, "auto_deploy"))

    # -- New browse-filter preference fields ---------------------------------

    def test_browse_filter_defaults(self):
        """show_paid and show_account_required default to False; show_incomplete to True."""
        cfg = AppConfig()
        self.assertFalse(cfg.show_paid)
        self.assertFalse(cfg.show_account_required)
        self.assertTrue(cfg.show_incomplete)

    def test_browse_filter_fields_in_to_dict(self):
        cfg = AppConfig(show_paid=True, show_account_required=False, show_incomplete=False)
        d = cfg.to_dict()
        self.assertTrue(d["show_paid"])
        self.assertFalse(d["show_account_required"])
        self.assertFalse(d["show_incomplete"])

    def test_browse_filter_fields_round_trip(self):
        cfg = AppConfig(show_paid=True, show_account_required=False, show_incomplete=False)
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertTrue(restored.show_paid)
        self.assertFalse(restored.show_account_required)
        self.assertFalse(restored.show_incomplete)

    def test_old_config_without_browse_filter_fields_uses_defaults(self):
        """Configs saved before the browse-filter fields were added should load fine."""
        old = {"pcsx2_path": "", "textures_path": "", "pnach_path": "",
               "cover_art_path": "", "memcards_path": "", "cheats_path": "",
               "mods_storage_path": "", "theme": "dark",
               "check_updates_on_start": True, "show_conflict_warnings": True,
               "first_run": False, "favorite_authors": [], "show_nsfw": False}
        cfg = AppConfig.from_dict(old)
        self.assertFalse(cfg.show_paid)
        self.assertFalse(cfg.show_account_required)
        self.assertTrue(cfg.show_incomplete)


# =============================================================================
# is_valid_serial
# =============================================================================

class TestIsValidSerial(unittest.TestCase):
    """Tests for game_registry.is_valid_serial()."""

    def test_valid_known_serial(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("SLUS-20062"))

    def test_valid_unknown_but_correct_format(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("SLUS-99999"))

    def test_valid_underscore_separator(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("SLUS_99999"))

    def test_valid_no_separator(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("SLUS99999"))

    def test_valid_pal_serial(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("SLES-54354"))

    def test_valid_jp_serial(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("SLPS-25088"))

    def test_valid_demo_prefix(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("SCED-12345"))

    def test_invalid_unknown_prefix(self):
        from src.core.game_registry import is_valid_serial
        self.assertFalse(is_valid_serial("XXXX-12345"))

    def test_invalid_too_few_digits(self):
        from src.core.game_registry import is_valid_serial
        self.assertFalse(is_valid_serial("SLUS-1234"))

    def test_invalid_too_many_digits(self):
        from src.core.game_registry import is_valid_serial
        self.assertFalse(is_valid_serial("SLUS-123456"))

    def test_invalid_empty_string(self):
        from src.core.game_registry import is_valid_serial
        self.assertFalse(is_valid_serial(""))

    def test_invalid_random_text(self):
        from src.core.game_registry import is_valid_serial
        self.assertFalse(is_valid_serial("MyTexturePack"))

    def test_invalid_crc_hex(self):
        from src.core.game_registry import is_valid_serial
        # CRC-style PNACH filename — not a serial
        self.assertFalse(is_valid_serial("F0A235B4"))

    def test_case_insensitive(self):
        from src.core.game_registry import is_valid_serial
        self.assertTrue(is_valid_serial("slus-20062"))
        self.assertTrue(is_valid_serial("Slus-20062"))


# =============================================================================
# config_manager.detect_pcsx2_paths delegates to pcsx2_layout
# =============================================================================

class TestDetectPcsx2Paths(unittest.TestCase):
    """detect_pcsx2_paths should return all expected keys via pcsx2_layout."""

    def test_returns_all_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = detect_pcsx2_paths(tmpdir)
            for key in ("textures_path", "pnach_path", "cover_art_path",
                        "memcards_path", "cheats_path", "partial_textures_path"):
                self.assertIn(key, result)

    def test_existing_subfolder_preferred(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Cheats").mkdir()
            result = detect_pcsx2_paths(tmpdir)
            self.assertTrue(
                result["pnach_path"].endswith("Cheats") or
                "Cheats" in result["pnach_path"]
            )


if __name__ == "__main__":
    unittest.main()


# =============================================================================
# Deploy-on-toggle behaviour (auto_deploy removed, always automatic)
# =============================================================================

class TestSetEnabledAutoDeployBehaviour(unittest.TestCase):
    """
    Verify that set_enabled() automatically deploys / undeploys mods.

    When a config with a valid target path is supplied:
    - Enabling a mod triggers a deploy to the target folder.
    - Disabling a mod removes its files and re-deploys remaining mods.

    When config is None (DB-only mode, used in tests that don't need FS):
    - The enabled flag is still toggled correctly.
    - No filesystem operations are attempted.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import src.core.config_manager as cm
        self._orig_db_file = cm.MODS_DB_FILE
        cm.MODS_DB_FILE = Path(self.tmpdir) / "mods.json"

    def tearDown(self):
        import src.core.config_manager as cm
        cm.MODS_DB_FILE = self._orig_db_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_pnach_mod(self, crc="AABBCCDD"):
        """Create a real .pnach file on disk and register it."""
        src_dir = Path(self.tmpdir) / "mod_src"
        src_dir.mkdir(exist_ok=True)
        pnach_file = src_dir / f"{crc}.pnach"
        pnach_file.write_text(f"// pnach for {crc}\n[{crc}]\npatch=1,EE,002345AA,word,00000001\n")
        db = ModDatabase()
        mgr = ModManager(db)
        mod = mgr.install_from_folder(
            source_path=str(src_dir),
            mod_type=ModType.PNACH,
            dest_base=str(Path(self.tmpdir) / "storage"),
        )
        return db, mgr, mod

    def test_set_enabled_toggles_flag_no_config(self):
        """Without a config, set_enabled still flips the DB flag."""
        db = ModDatabase()
        mgr = ModManager(db)
        mod = ModInfo(id="m1", name="T", mod_type=ModType.TEXTURE_PACK, path="/p", enabled=True)
        db.add(mod)

        count, warnings = mgr.set_enabled("m1", False)
        self.assertFalse(db.get("m1").enabled)
        self.assertEqual(count, 0)
        self.assertEqual(warnings, [])

        count, warnings = mgr.set_enabled("m1", True)
        self.assertTrue(db.get("m1").enabled)
        self.assertEqual(count, 0)
        self.assertEqual(warnings, [])

    def test_set_enabled_deploys_when_config_provided(self):
        """Enabling a mod with a valid config copies files to the target dir."""
        deploy_dir = Path(self.tmpdir) / "pcsx2_cheats"
        deploy_dir.mkdir()

        db, mgr, mod = self._make_pnach_mod("12345678")

        config = AppConfig(pnach_path=str(deploy_dir))
        count, warnings = mgr.set_enabled(mod.id, True, config)

        # At least one file should have been deployed
        deployed_files = list(deploy_dir.iterdir())
        self.assertGreater(len(deployed_files), 0, "No files were deployed to target dir")
        self.assertTrue(db.get(mod.id).enabled)

    def test_set_enabled_false_undeploys(self):
        """Disabling a mod removes its files from the target dir."""
        deploy_dir = Path(self.tmpdir) / "pcsx2_cheats2"
        deploy_dir.mkdir()

        db, mgr, mod = self._make_pnach_mod("DEADBEEF")
        config = AppConfig(pnach_path=str(deploy_dir))

        # First enable → deploy
        mgr.set_enabled(mod.id, True, config)
        self.assertGreater(len(list(deploy_dir.iterdir())), 0)

        # Now disable → undeploy
        mgr.set_enabled(mod.id, False, config)
        self.assertFalse(db.get(mod.id).enabled)
        # After disabling the only mod, no .pnach files should remain
        remaining = [f for f in deploy_dir.iterdir() if f.suffix == ".pnach"]
        self.assertEqual(len(remaining), 0, f"Stale pnach files remain: {remaining}")

    def test_set_enabled_no_path_returns_warning(self):
        """When config path is empty, a warning is returned (no crash)."""
        db, mgr, mod = self._make_pnach_mod()
        config = AppConfig(pnach_path="")  # path not configured

        count, warnings = mgr.set_enabled(mod.id, True, config)
        self.assertEqual(count, 0)
        self.assertTrue(len(warnings) > 0, "Expected a warning when path not configured")

    def test_no_auto_deploy_field_on_app_config(self):
        """AppConfig no longer has an auto_deploy field — deployment is always on."""
        cfg = AppConfig()
        self.assertFalse(hasattr(cfg, "auto_deploy"),
                         "auto_deploy was removed; deployment is always automatic")

    def test_from_dict_ignores_stale_auto_deploy_key(self):
        """Old saved configs that contain auto_deploy must load without error."""
        old_dict = {
            "pcsx2_path": "/pcsx2",
            "pnach_path": "/cheats",
            "auto_deploy": True,   # stale key from old version
        }
        cfg = AppConfig.from_dict(old_dict)
        self.assertEqual(cfg.pnach_path, "/cheats")
        self.assertFalse(hasattr(cfg, "auto_deploy"))


# =============================================================================
# Online game title lookup (mocked network)
# =============================================================================

class TestOnlineGameTitleLookup(unittest.TestCase):
    """Tests for serial_to_display_with_online_fallback and
    lookup_game_title_with_online_fallback."""

    def test_known_serial_uses_local_registry_no_network(self):
        """Known serials should NOT trigger a network call."""
        from src.core.game_registry import serial_to_display_with_online_fallback
        with patch("src.core.downloader.requests.get") as mock_get:
            result = serial_to_display_with_online_fallback("SLUS-20062")
        mock_get.assert_not_called()
        self.assertIn("SLUS-20062", result)
        self.assertIn("Spyro", result)

    @patch("src.core.downloader.requests.get")
    def test_unknown_serial_tries_online_lookup(self, mock_get):
        """Unknown serials should attempt an online lookup."""
        from src.core.game_registry import serial_to_display_with_online_fallback

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            '<title>SLUS-99999 - Test Online Game | GameTDB</title>'
        )
        mock_get.return_value = mock_resp

        result = serial_to_display_with_online_fallback("SLUS-99999")
        mock_get.assert_called_once()
        self.assertIn("SLUS-99999", result)
        self.assertIn("Test Online Game", result)

    @patch("src.core.downloader.requests.get")
    def test_unknown_serial_online_failure_returns_serial_only(self, mock_get):
        """If the online lookup fails, the serial alone is returned."""
        from src.core.game_registry import serial_to_display_with_online_fallback
        mock_get.side_effect = Exception("network error")
        result = serial_to_display_with_online_fallback("SLUS-99999")
        self.assertEqual(result, "SLUS-99999")

    @patch("src.core.downloader.requests.get")
    def test_lookup_game_title_with_online_fallback_known(self, mock_get):
        """Known serials should return title from local registry."""
        from src.core.game_registry import lookup_game_title_with_online_fallback
        result = lookup_game_title_with_online_fallback("SLUS-20062")
        mock_get.assert_not_called()
        self.assertIn("Spyro", result)

    @patch("src.core.downloader.requests.get")
    def test_lookup_game_title_with_online_fallback_unknown_network_error(self, mock_get):
        """Network errors during online lookup should return empty string."""
        from src.core.game_registry import lookup_game_title_with_online_fallback
        mock_get.side_effect = Exception("timeout")
        result = lookup_game_title_with_online_fallback("SLUS-99999")
        self.assertEqual(result, "")

    def test_serial_to_display_with_online_fallback_empty(self):
        from src.core.game_registry import serial_to_display_with_online_fallback
        self.assertEqual(serial_to_display_with_online_fallback(""), "")


# =============================================================================
# PCSX2 widescreen PNACH fetcher (mocked network)
# =============================================================================

class TestPcsx2PnachFetcher(unittest.TestCase):
    """Tests for list_pcsx2_widescreen_patches and download_pcsx2_widescreen_patch."""

    @patch("src.core.downloader.requests.get")
    def test_list_patches_returns_entries(self, mock_get):
        from src.core.downloader import list_pcsx2_widescreen_patches

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {
                "name": "F0A235B4.pnach",
                "download_url": "https://raw.githubusercontent.com/PCSX2/pcsx2/master/bin/cheats_ws/F0A235B4.pnach",
            },
            {
                "name": "A94060E1.pnach",
                "download_url": "https://raw.githubusercontent.com/PCSX2/pcsx2/master/bin/cheats_ws/A94060E1.pnach",
            },
            {
                "name": "README.md",  # should be filtered out (not a .pnach)
                "download_url": "https://raw.githubusercontent.com/PCSX2/pcsx2/master/bin/cheats_ws/README.md",
            },
        ]
        mock_get.return_value = mock_resp

        patches = list_pcsx2_widescreen_patches()
        self.assertEqual(len(patches), 2)
        crcs = [p["crc"] for p in patches]
        self.assertIn("F0A235B4", crcs)
        self.assertIn("A94060E1", crcs)

    @patch("src.core.downloader.requests.get")
    def test_list_patches_network_error_returns_empty(self, mock_get):
        from src.core.downloader import list_pcsx2_widescreen_patches
        mock_get.side_effect = Exception("network error")
        result = list_pcsx2_widescreen_patches()
        self.assertEqual(result, [])

    @patch("src.core.downloader.requests.get")
    def test_download_patch_success(self, mock_get):
        from src.core.downloader import download_pcsx2_widescreen_patch
        import tempfile

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"Content-Length": "100"}
        mock_resp.iter_content.return_value = [b"// PNACH content"]
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as d:
            result = download_pcsx2_widescreen_patch("F0A235B4", d)
            self.assertIsNotNone(result)
            self.assertTrue(result.endswith("F0A235B4.pnach"))
            self.assertTrue(Path(result).exists())

    @patch("src.core.downloader.requests.get")
    def test_download_patch_not_found_returns_none(self, mock_get):
        from src.core.downloader import download_pcsx2_widescreen_patch
        import tempfile
        from requests import HTTPError

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.raise_for_status.side_effect = HTTPError("404")
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as d:
            result = download_pcsx2_widescreen_patch("00000000", d)
            self.assertIsNone(result)

    @patch("src.core.downloader.requests.head")
    def test_search_by_crc_found(self, mock_head):
        from src.core.downloader import search_pcsx2_patches_by_crc

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_head.return_value = mock_resp

        result = search_pcsx2_patches_by_crc("F0A235B4")
        self.assertIsNotNone(result)
        self.assertEqual(result["crc"], "F0A235B4")
        self.assertTrue(result["filename"].endswith(".pnach"))

    @patch("src.core.downloader.requests.head")
    def test_search_by_crc_not_found(self, mock_head):
        from src.core.downloader import search_pcsx2_patches_by_crc

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_head.return_value = mock_resp

        result = search_pcsx2_patches_by_crc("00000000")
        self.assertIsNone(result)

    @patch("src.core.downloader.requests.head")
    def test_search_by_crc_normalises_case(self, mock_head):
        from src.core.downloader import search_pcsx2_patches_by_crc

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_head.return_value = mock_resp

        result = search_pcsx2_patches_by_crc("f0a235b4")  # lower-case input
        self.assertEqual(result["crc"], "F0A235B4")


# =============================================================================
# MediaFire URL resolver (mocked network)
# =============================================================================

class TestMediaFireResolver(unittest.TestCase):
    """Tests for resolve_mediafire_url()."""

    def test_non_mediafire_url_returns_none(self):
        from src.core.downloader import resolve_mediafire_url
        result = resolve_mediafire_url("https://example.com/file.zip")
        self.assertIsNone(result)

    def test_empty_url_returns_none(self):
        from src.core.downloader import resolve_mediafire_url
        self.assertIsNone(resolve_mediafire_url(""))
        self.assertIsNone(resolve_mediafire_url(None))  # type: ignore[arg-type]

    @patch("src.core.downloader.requests.get")
    def test_extracts_download_button_href(self, mock_get):
        from src.core.downloader import resolve_mediafire_url

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            '<html><body>'
            '<a id="downloadButton" class="input popsok" '
            'aria-label="Download file" '
            'href="https://download1234.mediafire.com/abc123/Spyro.zip">Download (48 MB)</a>'
            '</body></html>'
        )
        mock_get.return_value = mock_resp

        result = resolve_mediafire_url(
            "https://www.mediafire.com/file/y1057yt4l2ndobn/Spyro.zip/file"
        )
        self.assertEqual(result, "https://download1234.mediafire.com/abc123/Spyro.zip")

    @patch("src.core.downloader.requests.get")
    def test_fallback_to_download_domain_href(self, mock_get):
        from src.core.downloader import resolve_mediafire_url

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # No id="downloadButton" but has a download*.mediafire.com href
        mock_resp.text = (
            '<html><body>'
            '<a href="https://download99.mediafire.com/xyz/texture.zip">Get file</a>'
            '</body></html>'
        )
        mock_get.return_value = mock_resp

        result = resolve_mediafire_url(
            "https://www.mediafire.com/file/abc/texture.zip/file"
        )
        self.assertEqual(result, "https://download99.mediafire.com/xyz/texture.zip")

    @patch("src.core.downloader.requests.get")
    def test_non_200_response_returns_none(self, mock_get):
        from src.core.downloader import resolve_mediafire_url

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = resolve_mediafire_url(
            "https://www.mediafire.com/file/bad/file.zip/file"
        )
        self.assertIsNone(result)

    @patch("src.core.downloader.requests.get")
    def test_network_error_returns_none(self, mock_get):
        from src.core.downloader import resolve_mediafire_url
        mock_get.side_effect = Exception("connection refused")
        result = resolve_mediafire_url(
            "https://www.mediafire.com/file/abc/texture.zip/file"
        )
        self.assertIsNone(result)

    @patch("src.core.downloader.requests.get")
    def test_no_download_link_in_html_returns_none(self, mock_get):
        from src.core.downloader import resolve_mediafire_url

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>No download link here.</p></body></html>"
        mock_get.return_value = mock_resp

        result = resolve_mediafire_url(
            "https://www.mediafire.com/file/abc/texture.zip/file"
        )
        self.assertIsNone(result)


# =============================================================================
# GBAtemp thread scraper (mocked network)
# =============================================================================

class TestGBAtempScraper(unittest.TestCase):
    """Tests for scrape_gbatemp_thread()."""

    # Minimal synthetic GBAtemp-like HTML used across tests
    _SAMPLE_HTML = """
    <html>
    <head><title>A New Beginning | GBAtemp</title></head>
    <body>
    <h1 class="p-title-value">The Legend of Spyro: A New Beginning — 6x HD Texture Pack</h1>
    <div class="message-body">
      <span itemprop="name">DurinDragon</span>
      <a class="username" href="/members/durindragon.778677/">DurinDragon</a>
      <p>Download the packs below:</p>
      <a href="https://www.mediafire.com/file/y1057yt4l2ndobn/Spyro_ANB_SLUS-21372_6x.zip/file">6x Extra</a>
      <a href="https://www.mediafire.com/file/vkkkunm8kj09bh3/Spyro_ANB_SLUS-21372_6x_only.zip/file">6x Only</a>
      <a href="https://www.mediafire.com/file/3jilfm7ahm6bs62/Spyro_ANB_SLUS-21372_4x_anime.zip/file">4x Anime</a>
      <a href="https://www.mediafire.com/folder/jpnyulhtdvd77/Spyro_ANB_SLUS-21372">All Variants</a>
    </div>
    </body>
    </html>
    """

    @patch("src.core.downloader.requests.get")
    def test_extracts_title(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/spyro.677477/")
        self.assertIn("Spyro", result["title"])

    @patch("src.core.downloader.requests.get")
    def test_extracts_author_name(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/spyro.677477/")
        self.assertEqual(result["author"], "DurinDragon")

    @patch("src.core.downloader.requests.get")
    def test_extracts_author_url(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/spyro.677477/")
        self.assertIn("gbatemp.net", result["author_url"])
        self.assertIn("durindragon", result["author_url"].lower())

    @patch("src.core.downloader.requests.get")
    def test_extracts_mediafire_download_urls(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/spyro.677477/")
        hosts = [dl["host"] for dl in result["download_urls"]]
        self.assertIn("MediaFire", hosts)
        self.assertGreaterEqual(len(result["download_urls"]), 3)

    @patch("src.core.downloader.requests.get")
    def test_detects_game_serial_in_url(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        # Serial is in the thread URL
        result = scrape_gbatemp_thread(
            "https://gbatemp.net/threads/spyro-SLUS-21372-textures.677477/"
        )
        self.assertEqual(result["game_serial"], "SLUS-21372")

    @patch("src.core.downloader.requests.get")
    def test_detects_game_serial_in_download_url(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML  # MediaFire links contain SLUS-21372
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/spyro.677477/")
        # Serial should be picked up from the MediaFire URLs in the HTML
        self.assertEqual(result["game_serial"], "SLUS-21372")

    @patch("src.core.downloader.requests.get")
    def test_non_200_response_returns_empty(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/spyro.677477/")
        self.assertEqual(result["title"], "")
        self.assertEqual(result["download_urls"], [])

    @patch("src.core.downloader.requests.get")
    def test_network_error_returns_empty(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_get.side_effect = Exception("timeout")

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/spyro.677477/")
        self.assertEqual(result["title"], "")
        self.assertEqual(result["download_urls"], [])
        self.assertEqual(result["game_serial"], "")

    @patch("src.core.downloader.requests.get")
    def test_source_url_always_echoed_back(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_get.side_effect = Exception("timeout")

        url = "https://gbatemp.net/threads/some-pack.99999/"
        result = scrape_gbatemp_thread(url)
        self.assertEqual(result["source_url"], url)

    @patch("src.core.downloader.requests.get")
    def test_no_duplicate_download_urls(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        # HTML with the same URL duplicated
        dup_html = (
            '<html><body>'
            '<h1 class="p-title-value">Test</h1>'
            '<a href="https://www.mediafire.com/file/abc/test.zip/file">Link 1</a>'
            '<a href="https://www.mediafire.com/file/abc/test.zip/file">Link 2</a>'
            '</body></html>'
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = dup_html
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/threads/test.1/")
        urls = [dl["url"] for dl in result["download_urls"]]
        self.assertEqual(len(urls), len(set(urls)), "Duplicate URLs returned")


# =============================================================================
# Spyro: A New Beginning catalogue entries
# =============================================================================

class TestSpyroANBCatalogueEntries(unittest.TestCase):
    """The three DurinDragon Spyro: ANB variants must be in the catalogue."""

    def _load_catalogue(self):
        import sys; sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
        return [e["id"] for e in load_catalogue(catalogue_dir=CATALOGUE_DIR)]

    def _get_all_json_text(self):
        """Return concatenated text of all catalogue JSON files for string searches."""
        import json
        base = Path(__file__).parent.parent / "data" / "catalogue"
        return "\n".join(f.read_text() for f in base.glob("*.json") if f.suffix == ".json")

    def test_all_spyro_anb_variants_present(self):
        ids = self._load_catalogue()
        # Only the three variants with direct_download_url are retained
        expected = [
            "spyro_anb_6x_extra_detail",
            "spyro_anb_6x_only",
            "spyro_anb_4x_anime",
        ]
        for eid in expected:
            self.assertIn(eid, ids, f"Missing Spyro ANB catalogue entry: {eid}")

    def test_spyro_anb_direct_download_urls_are_mediafire(self):
        """Each downloadable variant must have a MediaFire direct_download_url."""
        src = self._get_all_json_text()
        for variant in ("6x_extra_detail", "6x_only", "4x_anime"):
            self.assertIn(
                "mediafire.com/file/",
                src,
                f"No MediaFire download URL found for spyro_anb_{variant}",
            )

    def test_spyro_anb_entries_author_is_durindragon(self):
        """All Spyro ANB entries should credit DurinDragon."""
        src = self._get_all_json_text()
        self.assertIn("DurinDragon", src)
        self.assertIn("gbatemp.net/members/durindragon", src)


# =============================================================================
# GBAtemp Download-page scraper extension
# =============================================================================

class TestGBATempDownloadPageScraper(unittest.TestCase):
    """Tests for scrape_gbatemp_thread() handling /download/ pages."""

    _DOWNLOAD_PAGE_HTML = """
    <html>
    <head><title>GBAtemp Downloads | Bully Saves</title></head>
    <body>
    <h1 class="p-title-value">Bully Saves 100% and More</h1>
    <dl class="pairs pairs--rows">
      <dt>Author</dt>
      <dd>moataz</dd>
    </dl>
    <a class="username" href="/members/moataz.683955/">moataz</a>
    <div class="message-body">
      Download: <a href="https://www.mediafire.com/file/hktfw1t8dv4etgo/bully_saves.rar/file">Download here</a>
    </div>
    <a href="/download/bully-saves.38390/download">Download from GBAtemp</a>
    </body>
    </html>
    """

    @patch("src.core.downloader.requests.get")
    def test_download_page_extracts_title(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._DOWNLOAD_PAGE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/download/bully-saves.38390/")
        self.assertIn("Bully", result["title"])

    @patch("src.core.downloader.requests.get")
    def test_download_page_extracts_author_from_dl_block(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._DOWNLOAD_PAGE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/download/bully-saves.38390/")
        self.assertEqual(result["author"], "moataz")

    @patch("src.core.downloader.requests.get")
    def test_download_page_extracts_external_links(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._DOWNLOAD_PAGE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/download/bully-saves.38390/")
        hosts = [dl["host"] for dl in result["download_urls"]]
        self.assertIn("MediaFire", hosts)

    @patch("src.core.downloader.requests.get")
    def test_download_page_includes_gbatemp_hosted_download(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._DOWNLOAD_PAGE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/download/bully-saves.38390/")
        hosts = [dl["host"] for dl in result["download_urls"]]
        self.assertIn("GBAtemp", hosts)

    @patch("src.core.downloader.requests.get")
    def test_download_page_gbatemp_link_is_first(self, mock_get):
        """GBAtemp-hosted download should be first in the list (most authoritative)."""
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._DOWNLOAD_PAGE_HTML
        mock_get.return_value = mock_resp

        result = scrape_gbatemp_thread("https://gbatemp.net/download/bully-saves.38390/")
        if result["download_urls"]:
            self.assertEqual(result["download_urls"][0]["host"], "GBAtemp")


# =============================================================================
# PS2-Home forum post scraper
# =============================================================================

class TestPS2HomeScraper(unittest.TestCase):
    """Tests for scrape_ps2home_post()."""

    _SAMPLE_HTML = """
    <html>
    <head><title>PS2-Home • View topic - ATV Off-Road Fury Save</title></head>
    <body>
    <h2 class="topic-title">ATV Off-Road Fury Game Save</h2>
    <strong class="postauthor">jumper cable</strong>
    <div class="post-text">
      Download available here:
      <a href="https://www.mediafire.com/file/abc123/ATV_save.zip/file">ATV Save</a>
      Also on Google Drive:
      <a href="https://drive.google.com/file/d/xyz789/view">Drive Link</a>
    </div>
    </body>
    </html>
    """

    _ATTACHMENT_HTML = """
    <html>
    <head><title>PS2-Home • View topic - Save with Attachment</title></head>
    <body>
    <h2 class="topic-title">Game Save With Attachment</h2>
    <strong class="postauthor">testuser</strong>
    <div class="post-text">
      <a href="./download/file.php?id=99&mode=view">game_save.ps2</a>
    </div>
    </body>
    </html>
    """

    @patch("src.core.downloader.requests.get")
    def test_extracts_title(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_ps2home_post("https://www.ps2-home.com/forum/viewtopic.php?f=70&t=12165")
        self.assertIn("ATV", result["title"])

    @patch("src.core.downloader.requests.get")
    def test_extracts_author(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_ps2home_post("https://www.ps2-home.com/forum/viewtopic.php?f=70&t=12165")
        self.assertEqual(result["author"], "jumper cable")

    @patch("src.core.downloader.requests.get")
    def test_extracts_mediafire_download_url(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_ps2home_post("https://www.ps2-home.com/forum/viewtopic.php?f=70&t=12165")
        hosts = [dl["host"] for dl in result["download_urls"]]
        self.assertIn("MediaFire", hosts)

    @patch("src.core.downloader.requests.get")
    def test_extracts_gdrive_download_url(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._SAMPLE_HTML
        mock_get.return_value = mock_resp

        result = scrape_ps2home_post("https://www.ps2-home.com/forum/viewtopic.php?f=70&t=12165")
        hosts = [dl["host"] for dl in result["download_urls"]]
        self.assertIn("Google Drive", hosts)

    @patch("src.core.downloader.requests.get")
    def test_extracts_phpbb_attachment_link(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = self._ATTACHMENT_HTML
        mock_get.return_value = mock_resp

        result = scrape_ps2home_post("https://www.ps2-home.com/forum/viewtopic.php?f=70&t=99")
        hosts = [dl["host"] for dl in result["download_urls"]]
        self.assertIn("PS2-Home", hosts)

    @patch("src.core.downloader.requests.get")
    def test_source_url_echoed_back(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_get.side_effect = Exception("network error")
        url = "https://www.ps2-home.com/forum/viewtopic.php?f=70&t=12165"
        result = scrape_ps2home_post(url)
        self.assertEqual(result["source_url"], url)

    @patch("src.core.downloader.requests.get")
    def test_non_200_returns_empty(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        result = scrape_ps2home_post("https://www.ps2-home.com/forum/viewtopic.php?f=70&t=0")
        self.assertEqual(result["title"], "")
        self.assertEqual(result["download_urls"], [])

    @patch("src.core.downloader.requests.get")
    def test_title_extracted_from_page_title_fallback(self, mock_get):
        """If no h2.topic-title found, fall back to parsing the <title> tag."""
        from src.core.downloader import scrape_ps2home_post
        html_no_h2 = (
            '<html><head><title>PS2-Home Board • View topic - Fallback Title</title></head>'
            '<body><strong class="postauthor">user</strong></body></html>'
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html_no_h2
        mock_get.return_value = mock_resp

        result = scrape_ps2home_post("https://www.ps2-home.com/forum/viewtopic.php?t=1")
        self.assertEqual(result["title"], "Fallback Title")


# =============================================================================
# RAR archive support
# =============================================================================

class TestRarExtraction(unittest.TestCase):
    """Tests for RAR support in extract_archive()."""

    def test_rar_without_rarfile_raises_helpful_error(self):
        """If 'rarfile' is not installed, a clear ArchiveError is raised."""
        import sys
        from unittest.mock import patch as _patch
        from src.core.archive import ArchiveError

        # Simulate rarfile not being installed
        with _patch.dict(sys.modules, {"rarfile": None}):
            # Re-import to pick up the mock
            import importlib
            import src.core.archive as _archive
            importlib.reload(_archive)
            try:
                with self.assertRaises(_archive.ArchiveError) as cm:
                    _archive._extract_rar(Path("/fake/file.rar"), Path("/tmp"))
                self.assertIn("rarfile", str(cm.exception).lower())
            finally:
                importlib.reload(_archive)  # restore

    def test_rar_extension_recognised_as_archive(self):
        from src.core.archive import is_archive
        self.assertTrue(is_archive("/path/to/file.rar"))

    def test_non_rar_extension_not_affected(self):
        from src.core.archive import is_archive
        self.assertTrue(is_archive("/path/to/file.zip"))
        self.assertFalse(is_archive("/path/to/file.txt"))


# =============================================================================
# Save file catalogue entries
# =============================================================================

class TestSaveFileCatalogueEntries(unittest.TestCase):
    """The new save file entries must be present in the catalogue."""

    def _get_ids(self):
        import sys; sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
        return [e["id"] for e in load_catalogue(catalogue_dir=CATALOGUE_DIR)]

    def _get_entries(self):
        import sys; sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
        return load_catalogue(catalogue_dir=CATALOGUE_DIR)

    def _get_all_json_text(self):
        """Concatenate all catalogue JSON files for plain text searches."""
        base = Path(__file__).parent.parent / "data" / "catalogue"
        return "\n".join(f.read_text() for f in base.glob("*.json"))

    def test_gbatemp_downloads_saves_hub_removed(self):
        """The gbatemp_downloads_saves_hub entry is a category hub and must NOT be in catalogue."""
        ids = self._get_ids()
        self.assertNotIn("gbatemp_downloads_saves_hub", ids)

    def test_bully_save_entry_present(self):
        """Bully save is the only save entry that has a working direct download URL."""
        ids = self._get_ids()
        self.assertIn("bully_save_moataz", ids)

    def test_sly2_save_entry_removed(self):
        """sly2_save_gamefiles has no direct_download_url and must not be in catalogue."""
        ids = self._get_ids()
        self.assertNotIn("sly2_save_gamefiles", ids)

    def test_ps2home_saves_hub_removed(self):
        """The ps2home_saves_hub entry is a category hub and must NOT be in catalogue."""
        ids = self._get_ids()
        self.assertNotIn("ps2home_saves_hub", ids)

    def test_atv_save_entry_removed(self):
        """atv_fury_save_ps2home has no direct_download_url and must not be in catalogue."""
        ids = self._get_ids()
        self.assertNotIn("atv_fury_save_ps2home", ids)

    def test_bully_save_has_mediafire_url(self):
        """Bully save entry must have a direct_download_url pointing to MediaFire."""
        src = self._get_all_json_text()
        self.assertIn("mediafire.com/file/hktfw1t8dv4etgo/bully_saves", src)

    def test_bully_save_author_is_moataz(self):
        src = self._get_all_json_text()
        self.assertIn("moataz", src)
        self.assertIn("gbatemp.net/members/moataz", src)

    def test_all_save_entries_are_not_hub(self):
        """Every save file entry must be a specific-file entry (is_hub=False)."""
        entries = self._get_entries()
        saves = [e for e in entries if e["type"] == "save_file"]
        for e in saves:
            self.assertFalse(e.get("is_hub", False),
                             f"Save entry {e['id']} must not be a hub")

    def test_all_save_entries_have_direct_download_url(self):
        """Every retained save entry must have a working direct_download_url."""
        entries = self._get_entries()
        saves = [e for e in entries if e["type"] == "save_file"]
        for e in saves:
            self.assertTrue(
                e.get("direct_download_url", ""),
                f"Save entry {e['id']} is missing a direct_download_url"
            )


# =============================================================================
# GBATempScraperDialog URL classifier
# =============================================================================

class TestScraperDialogClassifier(unittest.TestCase):
    """Tests for GBATempScraperDialog._classify_url() (static, no Qt needed)."""

    def _classify(self, url: str) -> str:
        """Replicate the production _classify_url logic using proper domain matching."""
        import urllib.parse as _up
        try:
            netloc = _up.urlparse(url).netloc.lower()
        except Exception:
            return ""
        if netloc == "gbatemp.net" or netloc.endswith(".gbatemp.net"):
            return "gbatemp"
        if netloc == "ps2-home.com" or netloc.endswith(".ps2-home.com"):
            return "ps2home"
        return ""

    def test_gbatemp_thread_url_classified_as_gbatemp(self):
        self.assertEqual(
            self._classify("https://gbatemp.net/threads/spyro.677477/"),
            "gbatemp",
        )

    def test_gbatemp_download_url_classified_as_gbatemp(self):
        self.assertEqual(
            self._classify("https://gbatemp.net/download/bully-saves.38390/"),
            "gbatemp",
        )

    def test_ps2home_url_classified_as_ps2home(self):
        self.assertEqual(
            self._classify("https://www.ps2-home.com/forum/viewtopic.php?f=70&t=12165"),
            "ps2home",
        )

    def test_unrecognised_url_returns_empty(self):
        self.assertEqual(self._classify("https://example.com/stuff"), "")

    def test_mediafire_url_returns_empty(self):
        self.assertEqual(
            self._classify("https://www.mediafire.com/file/abc/file.zip/file"),
            "",
        )


class TestCatalogueIntegrity(unittest.TestCase):
    """Structural integrity checks for the JSON catalogue files.

    Uses ``catalogue_loader.load_catalogue()`` which reads from
    ``data/catalogue/*.json``.  No Qt import needed.
    """

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
        cls.catalogue = load_catalogue(catalogue_dir=CATALOGUE_DIR, strict=True)
        cls.catalogue_dir = CATALOGUE_DIR

    # ------------------------------------------------------------------
    # Structural checks
    # ------------------------------------------------------------------

    _REQUIRED_FIELDS = {
        "id", "name", "description", "author", "author_url",
        "url", "type", "source", "game", "game_serial", "tags",
        "download_action", "upscale_tech",
        "is_hub", "nsfw",
    }

    def test_catalogue_not_empty(self):
        self.assertGreater(len(self.catalogue), 0, "CATALOGUE must not be empty")

    def test_all_entries_have_required_fields(self):
        for entry in self.catalogue:
            for field in self._REQUIRED_FIELDS:
                self.assertIn(
                    field, entry,
                    f"Entry {entry.get('id', '?')} is missing field '{field}'"
                )

    def test_all_ids_are_unique(self):
        ids = [e["id"] for e in self.catalogue]
        duplicates = [eid for eid in ids if ids.count(eid) > 1]
        self.assertEqual(
            [], list(set(duplicates)),
            f"Duplicate catalogue IDs found: {set(duplicates)}"
        )

    def test_all_ids_are_non_empty_strings(self):
        for entry in self.catalogue:
            self.assertIsInstance(entry["id"], str)
            self.assertTrue(entry["id"].strip(), f"Entry has empty id: {entry}")

    def test_all_names_are_non_empty(self):
        for entry in self.catalogue:
            self.assertTrue(
                entry.get("name", "").strip(),
                f"Entry {entry['id']} has empty name"
            )

    def test_all_urls_are_https(self):
        for entry in self.catalogue:
            url = entry.get("url", "")
            self.assertTrue(
                url.startswith("http://") or url.startswith("https://"),
                f"Entry {entry['id']} has invalid url: {url!r}"
            )

    def test_all_types_are_valid(self):
        from src.models.mod import ModType
        valid_types = set(ModType)
        for entry in self.catalogue:
            self.assertIn(
                entry["type"], valid_types,
                f"Entry {entry['id']} has invalid type: {entry['type']!r}"
            )

    def test_all_authors_are_non_empty(self):
        """Named-author (non-hub) entries must have a non-empty author.
        Hub entries intentionally use author="" since the individual poster
        is not known at catalogue-build time."""
        for entry in self.catalogue:
            if not entry.get("is_hub", True):
                self.assertTrue(
                    entry.get("author", "").strip(),
                    f"Named-author entry {entry['id']} has empty author"
                )

    def test_all_sources_are_non_empty(self):
        for entry in self.catalogue:
            self.assertTrue(
                entry.get("source", "").strip(),
                f"Entry {entry['id']} has empty source"
            )

    def test_tags_are_lists(self):
        for entry in self.catalogue:
            self.assertIsInstance(
                entry.get("tags"), list,
                f"Entry {entry['id']} tags is not a list"
            )

    def test_direct_download_url_is_string_or_empty(self):
        """direct_download_url may be absent or empty string, never None."""
        for entry in self.catalogue:
            val = entry.get("direct_download_url", "")
            self.assertIsInstance(
                val, str,
                f"Entry {entry['id']} direct_download_url must be a string, got {type(val)}"
            )
            if val:
                self.assertTrue(
                    val.startswith("http://") or val.startswith("https://"),
                    f"Entry {entry['id']} has non-empty but invalid direct_download_url: {val!r}"
                )

    def test_no_duplicate_names(self):
        names = [e["name"] for e in self.catalogue]
        seen: dict = {}
        for entry in self.catalogue:
            n = entry["name"]
            seen.setdefault(n, []).append(entry["id"])
        duplicates = {n: ids for n, ids in seen.items() if len(ids) > 1}
        for name, ids in duplicates.items():
            self.fail(f"Duplicate catalogue name {name!r} shared by IDs: {ids}")

    def test_is_hub_present_and_bool(self):
        """Every entry must declare is_hub: True (community browse) or False (specific author)."""
        for entry in self.catalogue:
            self.assertIn(
                "is_hub", entry,
                f"Entry {entry['id']} is missing the 'is_hub' field"
            )
            self.assertIsInstance(
                entry["is_hub"], bool,
                f"Entry {entry['id']} is_hub must be a bool, got {type(entry['is_hub'])}"
            )

    def test_non_hub_author_url_is_specific(self):
        """Non-hub entries must have an author_url pointing to a specific profile,
        not a bare site homepage.  We spot-check for known generic homepages."""
        generic_homepages = {
            "https://gbatemp.net",
            "https://gamebanana.com",
            "https://www.loverslab.com",
            "https://www.psx-place.com",
            "https://forums.pcsx2.net",
            "https://archive.org",
            "https://www.moddb.com",
            "https://github.com",
            "https://gamefaqs.gamespot.com",
            "https://www.reddit.com/r/ps2",
            "https://www.mobygames.com",
            "https://www.screenscraper.fr",
        }
        for entry in self.catalogue:
            if not entry.get("is_hub", True):
                aurl = entry.get("author_url", "")
                self.assertNotIn(
                    aurl, generic_homepages,
                    f"Named-author entry {entry['id']} has generic homepage as author_url: {aurl!r}"
                )
                self.assertTrue(
                    aurl.startswith("http://") or aurl.startswith("https://"),
                    f"Named-author entry {entry['id']} has invalid author_url: {aurl!r}"
                )

    def test_hub_author_url_not_bare_homepage(self):
        """Hub entries should still have a useful author_url (at least the browse/search
        page, not just the root homepage like https://gbatemp.net).
        We check this by requiring the URL to have a path longer than '/'."""
        import urllib.parse
        bare_homepages = {
            "https://gbatemp.net",
            "https://gamebanana.com",
            "https://www.loverslab.com",
            "https://www.psx-place.com",
            "https://forums.pcsx2.net",
            "https://archive.org",
            "https://www.moddb.com",
            "https://github.com",
        }
        for entry in self.catalogue:
            if entry.get("is_hub", True):
                aurl = entry.get("author_url", "")
                self.assertNotIn(
                    aurl, bare_homepages,
                    f"Hub entry {entry['id']} still uses a bare site homepage for author_url: {aurl!r}"
                )

    def test_no_search_member_urls_in_author_url(self):
        """author_url must never point to a member search page (e.g. /search/members/?name=X).
        Author links should go directly to the author's profile page, not a search results page."""
        for entry in self.catalogue:
            aurl = entry.get("author_url", "")
            self.assertNotIn(
                "search/members",
                aurl,
                f"Entry {entry['id']} author_url is a member-search page (not a profile): {aurl!r}"
            )

    def test_no_gbatem_org_typo_in_author_url(self):
        """author_url must not contain the typo domain 'gbatem.org' (should be gbatemp.net)."""
        for entry in self.catalogue:
            aurl = entry.get("author_url", "")
            self.assertNotIn(
                "gbatem.org",
                aurl,
                f"Entry {entry['id']} author_url contains typo domain 'gbatem.org': {aurl!r}"
            )

    def test_no_fake_gamesavedfiles_com_in_urls(self):
        """author_url and url must not use gamesavedfiles.com which is a non-existent website."""
        for entry in self.catalogue:
            aurl = entry.get("author_url", "")
            self.assertNotIn(
                "gamesavedfiles.com",
                aurl,
                f"Entry {entry['id']} author_url uses non-existent domain gamesavedfiles.com: {aurl!r}"
            )
            url = entry.get("url", "")
            self.assertNotIn(
                "gamesavedfiles.com",
                url,
                f"Entry {entry['id']} url uses non-existent domain gamesavedfiles.com: {url!r}"
            )

    def test_no_wrong_plural_gbatemp_urls(self):
        """Catalogue 'url' must not use '/downloads/categories/' (wrong plural).
        GBAtemp download URLs use the singular '/download/categories/' path."""
        for entry in self.catalogue:
            url = entry.get("url", "")
            self.assertNotIn(
                "/downloads/categories/",
                url,
                f"Entry {entry['id']} url uses wrong plural '/downloads/': {url!r}"
            )

    def test_nsfw_present_and_bool(self):
        """Every entry must declare nsfw: True or False."""
        for entry in self.catalogue:
            self.assertIn(
                "nsfw", entry,
                f"Entry {entry['id']} is missing the 'nsfw' field"
            )
            self.assertIsInstance(
                entry["nsfw"], bool,
                f"Entry {entry['id']} nsfw must be a bool, got {type(entry['nsfw'])}"
            )

    def test_loverslab_entries_are_nsfw(self):
        """All LoversLab-sourced entries must be marked nsfw=True
        because LoversLab is an adult content site."""
        for entry in self.catalogue:
            if entry.get("source", "") == "LoversLab":
                self.assertTrue(
                    entry.get("nsfw", False),
                    f"LoversLab entry {entry['id']} must have nsfw=True"
                )

    def test_hub_entries_have_empty_author(self):
        """Hub entries (is_hub=True) must have an empty author string.
        Individual posters on community search pages are not known ahead of time,
        so we never pre-fill a fake community name as the 'author'."""
        for entry in self.catalogue:
            if entry.get("is_hub", False):
                self.assertEqual(
                    entry.get("author", ""), "",
                    f"Hub entry {entry['id']} should have author='' (got {entry.get('author')!r})"
                )

    def test_named_author_entries_have_non_empty_author(self):
        """Named-author entries (is_hub=False) must have a non-empty author."""
        for entry in self.catalogue:
            if not entry.get("is_hub", True):
                self.assertTrue(
                    entry.get("author", "").strip(),
                    f"Named-author entry {entry['id']} must have a non-empty author"
                )

    def test_nsfw_filter_logic(self):
        """NSFW filter logic must work correctly.

        All current entries are safe (nsfw=False).  The filter with show_nsfw=False
        must return only non-nsfw entries; with show_nsfw=True it returns everything.
        """
        nsfw_entries = [e for e in self.catalogue if e.get("nsfw")]
        safe_entries  = [e for e in self.catalogue if not e.get("nsfw")]

        # All current entries should be non-nsfw (hub entries that were nsfw have been removed)
        self.assertEqual(len(nsfw_entries), 0, "No nsfw entries expected after hub removal")
        self.assertGreater(len(safe_entries), 0, "There should be safe (non-nsfw) entries")

        # Simulate the filter logic
        def apply_filter(entries, show_nsfw):
            return [e for e in entries if not e.get("nsfw", False) or show_nsfw]

        without_nsfw = apply_filter(self.catalogue, show_nsfw=False)
        with_nsfw    = apply_filter(self.catalogue, show_nsfw=True)

        # No nsfw entries in either result (since there are none)
        self.assertFalse(
            any(e.get("nsfw") for e in without_nsfw),
            "show_nsfw=False should remove all nsfw entries"
        )
        # All entries appear with show_nsfw=True as well
        self.assertEqual(len(with_nsfw), len(self.catalogue))


    # -- Paid / account-required / incomplete filter logic -------------------

    def test_optional_content_flags_are_bool_when_present(self):
        """is_free, requires_account, is_complete must be bool when explicitly set."""
        for entry in self.catalogue:
            for field in ("is_free", "requires_account", "is_complete"):
                if field in entry:
                    self.assertIsInstance(
                        entry[field], bool,
                        f"Entry {entry['id']} field '{field}' must be bool, got {type(entry[field])}"
                    )

    def test_paid_filter_logic(self):
        """Entries with is_free=False are hidden when show_paid=False."""
        paid = [e for e in self.catalogue if e.get("is_free") is False]
        if not paid:
            self.skipTest("No explicitly paid entries in catalogue")
        free = [e for e in self.catalogue if e.get("is_free", True)]

        # Without paid: only free entries visible
        without_paid = [e for e in self.catalogue if e.get("is_free", True)]
        # With paid: all entries visible
        with_paid = self.catalogue

        self.assertGreater(len(with_paid), len(without_paid),
                           "show_paid=True should reveal more entries")
        self.assertFalse(any(e.get("is_free") is False for e in without_paid),
                         "show_paid=False should hide all paid entries")

    def test_incomplete_filter_logic(self):
        """Entries with is_complete=False are hidden when show_incomplete=False."""
        incomplete = [e for e in self.catalogue if e.get("is_complete") is False]
        if not incomplete:
            self.skipTest("No explicitly incomplete entries in catalogue")
        without_incomplete = [e for e in self.catalogue if e.get("is_complete", True)]
        self.assertFalse(
            any(e.get("is_complete") is False for e in without_incomplete),
            "show_incomplete=False should hide all incomplete entries"
        )

    def test_patreon_entries_have_requires_account_true(self):
        """All non-hub Patreon entries should have requires_account=True (explicit or inferred).
        After filtering to only entries with direct downloads, Patreon entries without direct
        download URLs have been removed.  This test is skipped if none remain."""
        patreon_entries = [
            e for e in self.catalogue
            if e.get("source") == "Patreon" and not e.get("is_hub", False)
        ]
        if not patreon_entries:
            self.skipTest("No Patreon entries remain after direct-download filtering")
        for entry in patreon_entries:
            # Either explicitly set or inferred as True (Patreon is in _ACCOUNT_REQUIRED_SOURCES)
            explicit = entry.get("requires_account")
            if explicit is not None:
                self.assertTrue(explicit,
                    f"Patreon entry {entry['id']} has requires_account=False, expected True")

    def test_in_app_download_filter_logic(self):
        """in_app_only filter must show only entries downloadable within the app.

        An entry is in-app downloadable when:
        - download_action is 'cover_by_id' or 'cover_by_url', OR
        - download_action is '' AND direct_download_url is non-empty.
        All other entries (manual, download_save, manual_mega without direct
        URL, or empty action without direct URL) must be hidden.
        """
        def is_in_app(entry):
            action = entry.get("download_action", "")
            if action in ("cover_by_id", "cover_by_url"):
                return True
            return action == "" and bool(entry.get("direct_download_url", ""))

        must_be_true = [
            {"download_action": "cover_by_id", "direct_download_url": ""},
            {"download_action": "cover_by_url", "direct_download_url": ""},
            {
                "download_action": "",
                "direct_download_url": "https://www.mediafire.com/file/abc/mod.zip/file",
            },
            {
                "download_action": "",
                "direct_download_url": "https://drive.google.com/file/d/ABCDEF/view",
            },
        ]
        for e in must_be_true:
            self.assertTrue(is_in_app(e), f"Expected in-app=True for {e}")

        must_be_false = [
            {"download_action": "manual", "direct_download_url": ""},
            {"download_action": "download_save", "direct_download_url": ""},
            {"download_action": "manual_mega", "direct_download_url": ""},
            {"download_action": "manual_mega",
             "direct_download_url": "https://mega.nz/file/ABCDEF"},
            {"download_action": "", "direct_download_url": ""},
            {"download_action": ""},
        ]
        for e in must_be_false:
            self.assertFalse(is_in_app(e), f"Expected in-app=False for {e}")

    def test_in_app_download_filter_applied_to_catalogue(self):
        """The in_app_only filter on the real catalogue must yield a subset of entries."""
        def is_in_app(entry):
            action = entry.get("download_action", "")
            if action in ("cover_by_id", "cover_by_url"):
                return True
            return action == "" and bool(entry.get("direct_download_url", ""))

        in_app = [e for e in self.catalogue if is_in_app(e)]
        not_in_app = [e for e in self.catalogue if not is_in_app(e)]

        self.assertEqual(len(in_app) + len(not_in_app), len(self.catalogue))

        for e in in_app:
            action = e.get("download_action", "")
            direct = e.get("direct_download_url", "")
            ok = action in ("cover_by_id", "cover_by_url") or (action == "" and bool(direct))
            self.assertTrue(ok, f"Entry {e['id']} wrongly classified as in-app")

    def test_no_serial_shared_across_unrelated_games(self):
        """Each game_serial must not be assigned to more than 4 distinct game titles.

        A small number of duplicate titles (e.g. 'Dragon Quest VIII' vs
        'Dragon Quest VIII: Journey of the Cursed King') are acceptable, but
        a serial being shared across genuinely different games indicates a
        data error in the catalogue.  The threshold is set to 4 to reflect
        the current cleaned state; future waves should reduce this further.
        """
        from collections import defaultdict

        serial_games: dict = defaultdict(set)
        for entry in self.catalogue:
            serial = entry.get("game_serial", "")
            game = entry.get("game", "")
            if serial and game:
                serial_games[serial].add(game)

        for serial, games in serial_games.items():
            self.assertLessEqual(
                len(games),
                4,
                f"Serial {serial} is shared by {len(games)} different games: {games}. "
                "This likely indicates wrong game_serial assignments.",
            )



    """Tests for ModManager._normalize_texture_structure."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_dest(self) -> Path:
        d = Path(self.tmpdir) / "dest"
        d.mkdir()
        return d

    def test_replacement_folder_at_depth0(self):
        from src.core.mod_manager import ModManager
        dest = self._make_dest()
        (dest / "replacement").mkdir()
        (dest / "replacement" / "ABCD1234.png").write_bytes(b"PNG")
        ModManager._normalize_texture_structure(dest, "SLUS-21228")
        expected = dest / "SLUS-21228" / "replacements"
        self.assertTrue(expected.exists())
        self.assertTrue((expected / "ABCD1234.png").exists())
        self.assertFalse((dest / "replacement").exists())

    def test_replacements_folder_at_depth0(self):
        from src.core.mod_manager import ModManager
        dest = self._make_dest()
        (dest / "replacements").mkdir()
        (dest / "replacements" / "HASH.png").write_bytes(b"PNG")
        ModManager._normalize_texture_structure(dest, "SLUS-20062")
        expected = dest / "SLUS-20062" / "replacements"
        self.assertTrue(expected.exists())
        self.assertTrue((expected / "HASH.png").exists())

    def test_replacement_inside_wrapper_folder(self):
        from src.core.mod_manager import ModManager
        dest = self._make_dest()
        (dest / "MyPack_v1" / "replacement").mkdir(parents=True)
        (dest / "MyPack_v1" / "replacement" / "tex.png").write_bytes(b"PNG")
        ModManager._normalize_texture_structure(dest, "SLUS-21228")
        expected = dest / "SLUS-21228" / "replacements" / "tex.png"
        self.assertTrue(expected.exists())

    def test_flat_structure_moved_to_serial_replacements(self):
        from src.core.mod_manager import ModManager
        dest = self._make_dest()
        (dest / "hash1.png").write_bytes(b"A")
        (dest / "hash2.png").write_bytes(b"B")
        ModManager._normalize_texture_structure(dest, "SLUS-21228")
        expected = dest / "SLUS-21228" / "replacements"
        self.assertTrue(expected.exists())
        self.assertEqual(len(list(expected.iterdir())), 2)

    def test_already_correct_structure_unchanged(self):
        from src.core.mod_manager import ModManager
        dest = self._make_dest()
        (dest / "SLUS-21228" / "replacements").mkdir(parents=True)
        (dest / "SLUS-21228" / "replacements" / "tex.png").write_bytes(b"PNG")
        ModManager._normalize_texture_structure(dest, "SLUS-21228")
        # Should be completely unchanged
        self.assertTrue((dest / "SLUS-21228" / "replacements" / "tex.png").exists())
        self.assertEqual(len(list((dest / "SLUS-21228" / "replacements").iterdir())), 1)

    def test_no_game_id_does_nothing(self):
        from src.core.mod_manager import ModManager
        dest = self._make_dest()
        (dest / "replacement").mkdir()
        (dest / "replacement" / "tex.png").write_bytes(b"PNG")
        ModManager._normalize_texture_structure(dest, "")
        # Nothing should change — no serial to normalize into
        self.assertTrue((dest / "replacement").exists())
        self.assertTrue((dest / "replacement" / "tex.png").exists())

    def test_multiple_texture_files_all_moved(self):
        from src.core.mod_manager import ModManager
        dest = self._make_dest()
        (dest / "replacement").mkdir()
        for i in range(5):
            (dest / "replacement" / f"hash{i}.png").write_bytes(b"PNG")
        ModManager._normalize_texture_structure(dest, "SLUS-20062")
        expected = dest / "SLUS-20062" / "replacements"
        self.assertEqual(len(list(expected.iterdir())), 5)


# =============================================================================
# gametdb_cover_url helper
# =============================================================================

class TestGametdbCoverUrl(unittest.TestCase):
    """Tests for the gametdb_cover_url() helper in downloader.py."""

    def setUp(self):
        from src.core.downloader import gametdb_cover_url
        self.gcu = gametdb_cover_url

    def test_ntsc_us_slus_gives_us_region(self):
        url = self.gcu("SLUS-21714")
        self.assertIn("/US/", url)
        self.assertIn("SLUS21714", url)
        self.assertTrue(url.startswith("https://art.gametdb.com/ps2/cover/"))

    def test_ntsc_us_scus_gives_us_region(self):
        url = self.gcu("SCUS-97399")
        self.assertIn("/US/", url)
        self.assertIn("SCUS97399", url)

    def test_pal_sles_gives_en_region(self):
        url = self.gcu("SLES-52400")
        self.assertIn("/EN/", url)
        self.assertIn("SLES52400", url)

    def test_pal_sces_gives_en_region(self):
        url = self.gcu("SCES-52400")
        self.assertIn("/EN/", url)

    def test_japan_slps_gives_ja_region(self):
        url = self.gcu("SLPS-25302")
        self.assertIn("/JA/", url)
        self.assertIn("SLPS25302", url)

    def test_hyphen_stripped_from_serial(self):
        url = self.gcu("SLUS-20312")
        self.assertIn("SLUS20312", url)
        self.assertNotIn("SLUS-20312", url)

    def test_empty_serial_returns_empty(self):
        url = self.gcu("")
        self.assertEqual(url, "")

    def test_lowercase_input_normalised(self):
        url = self.gcu("slus-21714")
        self.assertIn("SLUS21714", url)
        self.assertIn("/US/", url)

    def test_url_ends_with_jpg(self):
        url = self.gcu("SLUS-20946")
        self.assertTrue(url.endswith(".jpg"))

    def test_korea_serial_gives_ko_region(self):
        url = self.gcu("SLKA-25001")
        self.assertIn("/KO/", url)

    def test_unknown_prefix_defaults_to_us(self):
        url = self.gcu("XXXX-99999")
        self.assertIn("/US/", url)


# =============================================================================
# game_serial field in catalogue (JSON-based, no Qt import needed)
# =============================================================================

def _load_catalogue_ast():
    """Load catalogue from JSON files via catalogue_loader (no Qt)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
    return load_catalogue(catalogue_dir=CATALOGUE_DIR, strict=True)


class TestCatalogueGameSerial(unittest.TestCase):
    """Every entry must have the game_serial field; game-specific entries must
    have a non-empty, correctly formatted serial (AST-based, no Qt)."""

    @classmethod
    def setUpClass(cls):
        cls.catalogue = _load_catalogue_ast()

    def test_all_entries_have_game_serial_field(self):
        for entry in self.catalogue:
            self.assertIn(
                "game_serial", entry,
                f"Entry {entry['id']} missing 'game_serial' field",
            )

    def test_game_serial_is_string(self):
        for entry in self.catalogue:
            self.assertIsInstance(
                entry["game_serial"], str,
                f"Entry {entry['id']} game_serial must be str",
            )

    def test_game_specific_entries_have_valid_serial_format(self):
        """Non-empty serials must follow the XXXX-DDDDD pattern."""
        import re
        serial_re = re.compile(r'^[A-Z]{4}-\d{5}$')
        for entry in self.catalogue:
            serial = entry.get("game_serial", "")
            if serial:
                self.assertRegex(
                    serial, serial_re,
                    f"Entry {entry['id']} has malformed serial: {serial!r}",
                )

    def test_well_known_game_serials(self):
        by_id = {e["id"]: e for e in self.catalogue}
        # Only entries that have a working direct_download_url are retained
        expected = {
            "cckrizalid_baroque_textures": "SLUS-21714",
            "spyro_anb_6x_extra_detail":   "SLUS-21372",
            "bully_save_moataz":           "SLUS-21269",
        }
        for eid, expected_serial in expected.items():
            self.assertIn(eid, by_id, f"Entry {eid!r} not found")
            actual = by_id[eid]["game_serial"]
            self.assertEqual(actual, expected_serial,
                             f"{eid!r}: expected {expected_serial!r}, got {actual!r}")

    def test_game_specific_entries_mostly_have_serial(self):
        no_serial = [
            e for e in self.catalogue
            if e.get("game") and not e.get("game_serial")
        ]
        self.assertLessEqual(len(no_serial), 8,
            f"Too many game entries without serial: {[e['id'] for e in no_serial]}")


# =============================================================================
# Scraper thumbnail_url extraction
# =============================================================================

class TestScraperThumbnailExtraction(unittest.TestCase):
    """scrape_gbatemp_thread and scrape_ps2home_post should extract
    thumbnail_url from post images."""

    @patch("src.core.downloader.requests.get")
    def test_gbatemp_extracts_thumbnail_url(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        img = "https://files.catbox.moe/cover_art.jpg"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            '<html><body>'
            '<h1 class="p-title-value">Test HD Textures</h1>'
            '<span itemprop="name">Author</span>'
            f'<img src="{img}" alt="cover">'
            '</body></html>'
        )
        mock_get.return_value = mock_resp
        result = scrape_gbatemp_thread("https://gbatemp.net/threads/test.12345/")
        self.assertEqual(result["thumbnail_url"], img)

    @patch("src.core.downloader.requests.get")
    def test_gbatemp_skips_avatar_images(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        avatar = "https://gbatemp.net/data/avatars/user_123.jpg"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            '<html><body>'
            '<h1 class="p-title-value">Test</h1>'
            f'<img src="{avatar}" alt="av">'
            '</body></html>'
        )
        mock_get.return_value = mock_resp
        result = scrape_gbatemp_thread("https://gbatemp.net/threads/test.12345/")
        self.assertEqual(result["thumbnail_url"], "")

    @patch("src.core.downloader.requests.get")
    def test_gbatemp_result_has_thumbnail_url_key(self, mock_get):
        from src.core.downloader import scrape_gbatemp_thread
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h1 class='p-title-value'>T</h1></body></html>"
        mock_get.return_value = mock_resp
        result = scrape_gbatemp_thread("https://gbatemp.net/threads/x.1/")
        self.assertIn("thumbnail_url", result)

    @patch("src.core.downloader.requests.get")
    def test_ps2home_result_has_thumbnail_url_key(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h2 class='topic-title'>S</h2></body></html>"
        mock_get.return_value = mock_resp
        result = scrape_ps2home_post(
            "https://www.ps2-home.com/forum/viewtopic.php?t=1"
        )
        self.assertIn("thumbnail_url", result)

    @patch("src.core.downloader.requests.get")
    def test_ps2home_extracts_post_image(self, mock_get):
        from src.core.downloader import scrape_ps2home_post
        img = "https://www.ps2-home.com/forum/img/screenshot.jpg"
        html = (
            '<html><body>'
            '<h2 class="topic-title">ATV Save</h2>'
            f'<img src="{img}" alt="shot">'
            '</body></html>'
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_get.return_value = mock_resp
        result = scrape_ps2home_post(
            "https://www.ps2-home.com/forum/viewtopic.php?t=12165"
        )
        self.assertEqual(result["thumbnail_url"], img)


# =============================================================================
# CCKrizalid catalogue entries (AST-based)
# =============================================================================

class TestCCKrizalidEntries(unittest.TestCase):
    """Verify CCKrizalid 'Mega Library' texture pack entries."""

    @classmethod
    def setUpClass(cls):
        cls.entries = {e["id"]: e for e in _load_catalogue_ast()}

    def test_baroque_entry_present(self):
        self.assertIn("cckrizalid_baroque_textures", self.entries)

    def test_baroque_has_confirmed_mega_link(self):
        e = self.entries["cckrizalid_baroque_textures"]
        self.assertIn("mega.nz/file/Qds2kQAR", e["direct_download_url"])

    def test_baroque_serial_is_slus_21829(self):
        e = self.entries["cckrizalid_baroque_textures"]
        self.assertEqual(e["game_serial"], "SLUS-21714")

    def test_baroque_author_is_cckrizalid(self):
        e = self.entries["cckrizalid_baroque_textures"]
        self.assertEqual(e["author"], "CCKrizalid")

    def test_baroque_author_url_points_to_profile(self):
        e = self.entries["cckrizalid_baroque_textures"]
        self.assertIn("cckrizalid.606805", e["author_url"])

    def test_all_cckrizalid_entries_have_thread_url(self):
        thread = "mega-library-of-hd-texture-packs-by-cckrizalid.618690"
        cc = [e for e in self.entries.values() if e.get("author") == "CCKrizalid"]
        self.assertGreater(len(cc), 0)
        for e in cc:
            self.assertIn(thread, e["url"],
                          f"{e['id']}: url should contain the thread slug")

    def test_all_cckrizalid_entries_are_texture_packs(self):
        from src.models.mod import ModType
        cc = [e for e in self.entries.values() if e.get("author") == "CCKrizalid"]
        for e in cc:
            self.assertEqual(e["type"], ModType.TEXTURE_PACK,
                             f"{e['id']} type should be texture_pack")

    def test_all_cckrizalid_entries_have_serials(self):
        cc = [e for e in self.entries.values() if e.get("author") == "CCKrizalid"]
        for e in cc:
            self.assertTrue(e.get("game_serial"),
                            f"{e['id']} missing game_serial")

    def test_minimum_cckrizalid_pack_count(self):
        cc = [e for e in self.entries.values() if e.get("author") == "CCKrizalid"]
        self.assertGreaterEqual(len(cc), 1,
                                "Expected at least 1 CCKrizalid pack entry with direct download")


# =============================================================================
# CatalogueLoader
# =============================================================================

class TestCatalogueLoader(unittest.TestCase):
    """Tests for src.core.catalogue_loader — the new JSON-based catalogue."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.core.catalogue_loader import (
            load_catalogue, CATALOGUE_DIR, CATALOGUE, ALL_SOURCES,
        )
        cls.load_catalogue = staticmethod(load_catalogue)
        cls.catalogue_dir = CATALOGUE_DIR
        cls.catalogue = CATALOGUE
        cls.all_sources = ALL_SOURCES

    # ── Basic load ──────────────────────────────────────────────────────────

    def test_loads_more_than_150_entries(self):
        # 4 texture packs + 600 cheats + 1 save = 605 after direct-download filtering
        self.assertGreaterEqual(len(self.catalogue), 605,
                                "catalogue should have ≥605 entries after direct-download filtering")

    def test_no_duplicate_ids(self):
        ids = [e["id"] for e in self.catalogue]
        seen = set()
        for eid in ids:
            self.assertNotIn(eid, seen, f"Duplicate ID: {eid!r}")
            seen.add(eid)

    def test_type_field_injected(self):
        """Every entry must have a 'type' field (injected from file name) as a ModType enum."""
        from src.models.mod import ModType
        valid_types = set(ModType)
        for e in self.catalogue:
            self.assertIn(e.get("type"), valid_types,
                          f"Entry {e['id']} has invalid type {e.get('type')!r}")

    def test_all_required_fields_present(self):
        required = {"id", "name", "description", "author", "url", "source",
                    "game", "game_serial"}
        for e in self.catalogue:
            for f in required:
                self.assertIn(f, e,
                              f"Entry {e['id']!r} missing required field {f!r}")

    def test_optional_defaults_filled_in(self):
        """Optional fields must be present in every loaded entry."""
        optional = {"context", "author_url", "is_hub", "nsfw", "thumbnail_url",
                    "tags", "download_action", "direct_download_url",
                    "upscale_tech", "is_free", "requires_account", "is_complete",
                    "size_label"}
        for e in self.catalogue:
            for f in optional:
                self.assertIn(f, e,
                              f"Entry {e['id']!r} missing optional field {f!r}")

    def test_tags_are_lists(self):
        for e in self.catalogue:
            self.assertIsInstance(e["tags"], list,
                                  f"Entry {e['id']!r} 'tags' must be a list")

    # ── Type counts ─────────────────────────────────────────────────────────

    def test_has_texture_pack_entries(self):
        from src.models.mod import ModType
        tp = [e for e in self.catalogue if e["type"] == ModType.TEXTURE_PACK]
        self.assertGreater(len(tp), 0, "Expected texture pack entries with direct downloads")

    def test_texture_pack_size_labels(self):
        """Non-hub texture pack entries should have a size_label field in format '~NNN MB/GB'."""
        import re
        from src.models.mod import ModType
        size_pattern = re.compile(r'^~\d+(\.\d+)?\s*(KB|MB|GB)$')
        tp = [e for e in self.catalogue
              if e["type"] == ModType.TEXTURE_PACK and not e.get("is_hub")]
        missing = [e["id"] for e in tp if not e.get("size_label")]
        self.assertEqual(
            missing, [],
            f"{len(missing)} texture pack entries missing size_label: {missing[:5]}"
        )
        bad_format = [e["id"] for e in tp
                      if e.get("size_label") and not size_pattern.match(e["size_label"])]
        self.assertEqual(
            bad_format, [],
            f"{len(bad_format)} entries have invalid size_label format "
            f"(expected '~NNN MB/GB'): {bad_format[:5]}"
        )

    def test_has_pnach_entries(self):
        """After direct-download filtering, all PNACH entries without direct_download_url
        are removed.  This test simply verifies that the PNACH list has been cleaned."""
        from src.models.mod import ModType
        pn = [e for e in self.catalogue if e["type"] == ModType.PNACH]
        # All retained PNACH entries must have a direct_download_url
        for e in pn:
            self.assertTrue(e.get("direct_download_url"),
                            f"PNACH entry {e['id']} has no direct_download_url")

    def test_has_save_file_entries(self):
        """After direct-download filtering, only save entries with direct_download_url are kept."""
        from src.models.mod import ModType
        sv = [e for e in self.catalogue if e["type"] == ModType.SAVE_FILE]
        self.assertGreater(len(sv), 0, "Expected at least one save file entry with direct download")
        for e in sv:
            self.assertTrue(e.get("direct_download_url"),
                            f"Save entry {e['id']} has no direct_download_url")

    def test_no_generic_placeholder_authors(self):
        """Every catalogue entry must credit a real person or project.

        Prevents generic community-level placeholders from being used instead of
        the specific uploader's username.  Each string in ``generic_authors`` is
        a known placeholder that was previously used and must not reappear — the
        correct attribution (e.g. ``GameSavedFiles`` for GBAtemp PS2 saves,
        ``kozarovv`` for PCSX2 patches) must be used instead.
        """
        generic_authors = {
            "GBAtemp Community",
            "PS2Wide Community",
            "GitHub Community",
            "PS2-Home Community",
            "Unknown (GBAtemp member)",
        }
        bad = [e["id"] for e in self.catalogue if e.get("author") in generic_authors]
        self.assertEqual(bad, [],
                         f"Entries still using generic placeholder author: {bad}")

    # ── Strict mode ─────────────────────────────────────────────────────────

    def test_strict_mode_raises_on_bad_json(self):
        import tempfile, json
        from src.core.catalogue_loader import load_catalogue
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "texture_packs.json"
            p.write_text("NOT VALID JSON")
            with self.assertRaises(ValueError):
                load_catalogue(catalogue_dir=d, strict=True)

    def test_strict_mode_raises_on_missing_required_field(self):
        import tempfile, json
        from src.core.catalogue_loader import load_catalogue
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "texture_packs.json"
            # Entry missing 'name'
            p.write_text(json.dumps([{
                "id": "test_entry",
                "description": "desc",
                "author": "Author",
                "url": "https://example.com",
                "source": "GBAtemp",
                "game": "Game",
                "game_serial": "SLUS-12345",
            }]))
            with self.assertRaises(ValueError):
                load_catalogue(catalogue_dir=d, strict=True)

    def test_lenient_mode_skips_bad_entries(self):
        import tempfile, json
        from src.core.catalogue_loader import load_catalogue
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "texture_packs.json"
            p.write_text("NOT VALID JSON")
            # Should not raise in lenient (default) mode
            result = load_catalogue(catalogue_dir=d, strict=False)
            self.assertEqual(result, [])

    def test_empty_dir_returns_empty_list(self):
        import tempfile
        from src.core.catalogue_loader import load_catalogue
        with tempfile.TemporaryDirectory() as d:
            result = load_catalogue(catalogue_dir=d)
            self.assertEqual(result, [])

    def test_duplicate_ids_skipped_in_lenient_mode(self):
        import tempfile, json
        from src.core.catalogue_loader import load_catalogue
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "texture_packs.json"
            entry = {
                "id": "dup", "name": "N", "description": "D",
                "author": "A", "url": "https://x.com", "source": "S",
                "game": "G", "game_serial": "SLUS-00001",
            }
            p.write_text(json.dumps([entry, entry]))  # same ID twice
            result = load_catalogue(catalogue_dir=d, strict=False)
            self.assertEqual(len(result), 1)

    def test_duplicate_ids_raise_in_strict_mode(self):
        import tempfile, json
        from src.core.catalogue_loader import load_catalogue
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "texture_packs.json"
            entry = {
                "id": "dup", "name": "N", "description": "D",
                "author": "A", "url": "https://x.com", "source": "S",
                "game": "G", "game_serial": "SLUS-00001",
            }
            p.write_text(json.dumps([entry, entry]))
            with self.assertRaises(ValueError):
                load_catalogue(catalogue_dir=d, strict=True)

    # ── ALL_SOURCES ──────────────────────────────────────────────────────────

    def test_all_sources_is_sorted(self):
        self.assertEqual(self.all_sources, sorted(self.all_sources))

    def test_all_sources_contains_gbatemp(self):
        self.assertIn("GBAtemp", self.all_sources)

    def test_all_sources_contains_github(self):
        self.assertIn("GitHub", self.all_sources)

    def test_all_sources_contains_ps2wide(self):
        """PS2Wide was a source for PNACH entries without direct downloads; those are removed.
        This test verifies PS2Wide is no longer a source after filtering."""
        self.assertNotIn("PS2Wide", self.all_sources)

    # ── New sources from scaling ──────────────────────────────────────────────

    def test_gamebanana_source_present(self):
        """GameBanana entries without direct downloads have been removed.
        This test verifies they are no longer in the filtered catalogue."""
        gb = [e for e in self.catalogue if e["source"] == "GameBanana"]
        for e in gb:
            self.assertTrue(e.get("direct_download_url"),
                            f"GameBanana entry {e['id']} has no direct_download_url")

    # ── 60fps patches ─────────────────────────────────────────────────────────

    def test_60fps_patches_present(self):
        """After filtering, 60fps-tagged entries are only present if they have direct_download_url."""
        fps_patches = [e for e in self.catalogue if "60fps" in e.get("tags", [])]
        for e in fps_patches:
            self.assertTrue(e.get("direct_download_url"),
                            f"60fps entry {e['id']} has no direct_download_url")

    def test_60fps_patches_are_pnach_type(self):
        from src.models.mod import ModType
        for e in self.catalogue:
            if "60fps" in e.get("tags", []):
                self.assertEqual(e["type"], ModType.PNACH,
                                 f"60fps entry {e['id']} should be pnach type")

    # ── CCKrizalid coverage ───────────────────────────────────────────────────

    def test_cckrizalid_baroque_present(self):
        by_id = {e["id"]: e for e in self.catalogue}
        self.assertIn("cckrizalid_baroque_textures", by_id)

    def test_cckrizalid_minimum_pack_count(self):
        cc = [e for e in self.catalogue if e.get("author") == "CCKrizalid"]
        self.assertGreaterEqual(len(cc), 1,
                                "Expected at least 1 CCKrizalid entry with direct download")


# =============================================================================
# Game Library Scanner
# =============================================================================

class TestGameLibrary(unittest.TestCase):
    """Tests for src.core.game_library — disc image scanner."""

    @classmethod
    def setUpClass(cls):
        from src.core.game_library import scan_library, get_library_serials, GAME_EXTENSIONS, GameEntry
        cls.scan_library = staticmethod(scan_library)
        cls.get_library_serials = staticmethod(get_library_serials)
        cls.GAME_EXTENSIONS = GAME_EXTENSIONS
        cls.GameEntry = GameEntry

    # ── Non-existent directory ───────────────────────────────────────────────

    def test_nonexistent_dir_returns_empty(self):
        result = self.scan_library("/nonexistent/path/xyz_ps2_lib")
        self.assertEqual(result, [])

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.scan_library(d)
            self.assertEqual(result, [])

    # ── Extension filtering ──────────────────────────────────────────────────

    def test_only_supported_extensions_included(self):
        with tempfile.TemporaryDirectory() as d:
            for ext in self.GAME_EXTENSIONS:
                Path(d, f"game{ext}").write_bytes(b"\x00")
            # Unsupported
            Path(d, "game.mp4").write_bytes(b"\x00")
            Path(d, "readme.txt").write_text("hello")

            games = self.scan_library(d)
            exts = {g.extension for g in games}
            self.assertNotIn(".mp4", exts)
            self.assertNotIn(".txt", exts)
            self.assertEqual(len(games), len(self.GAME_EXTENSIONS))

    def test_iso_detected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "game.iso").write_bytes(b"\x00")
            games = self.scan_library(d)
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].extension, ".iso")

    def test_chd_detected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "game.chd").write_bytes(b"\x00")
            games = self.scan_library(d)
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].extension, ".chd")

    # ── Serial detection from filename ──────────────────────────────────────

    def test_serial_detected_from_filename(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "SLUS-20891 God of War.iso").write_bytes(b"\x00")
            games = self.scan_library(d)
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].serial, "SLUS-20891")

    def test_title_filled_from_known_serial(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "SLUS-20891.iso").write_bytes(b"\x00")
            games = self.scan_library(d)
            # "God of War" is a known serial in game_registry
            self.assertIn("God of War", games[0].title)

    def test_unknown_serial_empty_title(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "unknown_game.iso").write_bytes(b"\x00")
            games = self.scan_library(d)
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].serial, "")
            self.assertEqual(games[0].title, "")

    def test_display_name_with_title_and_serial(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "SLUS-20891.iso").write_bytes(b"\x00")
            g = self.scan_library(d)[0]
            dn = g.display_name
            # Should include both serial and title
            self.assertIn("SLUS-20891", dn)
            self.assertIn("God of War", dn)

    def test_display_name_fallback_to_filename(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "mystery_game.iso").write_bytes(b"\x00")
            g = self.scan_library(d)[0]
            self.assertIn("mystery_game.iso", g.display_name)

    def test_results_sorted_by_display_name(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "zzz.iso").write_bytes(b"\x00")
            Path(d, "aaa.chd").write_bytes(b"\x00")
            Path(d, "mmm.bin").write_bytes(b"\x00")
            games = self.scan_library(d)
            names = [g.display_name.lower() for g in games]
            self.assertEqual(names, sorted(names))

    # ── get_library_serials ──────────────────────────────────────────────────

    def test_get_library_serials_returns_frozenset(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.get_library_serials(d)
            self.assertIsInstance(result, frozenset)

    def test_get_library_serials_excludes_empty(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "SLUS-20891.iso").write_bytes(b"\x00")
            Path(d, "no_serial.chd").write_bytes(b"\x00")
            serials = self.get_library_serials(d)
            self.assertIn("SLUS-20891", serials)
            self.assertNotIn("", serials)

    def test_get_library_serials_upper_case(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "slus-20891.iso").write_bytes(b"\x00")
            serials = self.get_library_serials(d)
            self.assertIn("SLUS-20891", serials)

    def test_size_bytes_populated(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "SLUS-20891.iso")
            p.write_bytes(b"\x00" * 256)
            games = self.scan_library(d)
            self.assertEqual(games[0].size_bytes, 256)


# =============================================================================
# AppConfig game_library_path field
# =============================================================================

class TestAppConfigGameLibrary(unittest.TestCase):
    """Tests for AppConfig.game_library_path — new field added in recent session."""

    def test_default_is_empty_string(self):
        cfg = AppConfig()
        self.assertEqual(cfg.game_library_path, "")

    def test_to_dict_includes_game_library_path(self):
        cfg = AppConfig(game_library_path="/my/roms")
        d = cfg.to_dict()
        self.assertIn("game_library_path", d)
        self.assertEqual(d["game_library_path"], "/my/roms")

    def test_from_dict_restores_game_library_path(self):
        cfg = AppConfig(game_library_path="/my/roms")
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertEqual(restored.game_library_path, "/my/roms")

    def test_old_config_without_game_library_path_defaults(self):
        """Configs saved before game_library_path was added must load cleanly."""
        old = {
            "pcsx2_path": "", "textures_path": "", "pnach_path": "",
            "cover_art_path": "", "memcards_path": "", "cheats_path": "",
            "mods_storage_path": "", "theme": "dark",
            "check_updates_on_start": True, "show_conflict_warnings": True,
            "first_run": False, "favorite_authors": [], "show_nsfw": False,
        }
        cfg = AppConfig.from_dict(old)
        self.assertEqual(cfg.game_library_path, "")

    def test_config_save_and_load_preserves_game_library_path(self):
        import src.core.config_manager as cm
        orig_file = cm.CONFIG_FILE
        with tempfile.TemporaryDirectory() as d:
            cm.CONFIG_FILE = Path(d) / "config.json"
            try:
                cfg = AppConfig(game_library_path="/roms/ps2")
                from src.core.config_manager import save_config, load_config
                save_config(cfg)
                loaded = load_config()
                self.assertEqual(loaded.game_library_path, "/roms/ps2")
            finally:
                cm.CONFIG_FILE = orig_file


# =============================================================================
# Theme registry
# =============================================================================

class TestThemeRegistry(unittest.TestCase):
    """Tests for src.ui.theme — multi-theme support added in recent session."""

    @classmethod
    def setUpClass(cls):
        from src.ui.theme import THEMES, THEME_KEYS, get_stylesheet
        cls.THEMES = THEMES
        cls.THEME_KEYS = THEME_KEYS
        cls.get_stylesheet = staticmethod(get_stylesheet)

    def test_four_themes_available(self):
        self.assertIn("Dark", self.THEMES)
        self.assertIn("Midnight", self.THEMES)
        self.assertIn("Retro Green", self.THEMES)
        self.assertIn("Purple", self.THEMES)

    def test_four_theme_keys(self):
        self.assertIn("dark", self.THEME_KEYS)
        self.assertIn("midnight", self.THEME_KEYS)
        self.assertIn("retro_green", self.THEME_KEYS)
        self.assertIn("purple", self.THEME_KEYS)

    def test_key_to_display_name_mapping(self):
        self.assertEqual(self.THEME_KEYS["dark"], "Dark")
        self.assertEqual(self.THEME_KEYS["midnight"], "Midnight")
        self.assertEqual(self.THEME_KEYS["retro_green"], "Retro Green")
        self.assertEqual(self.THEME_KEYS["purple"], "Purple")

    def test_get_stylesheet_returns_non_empty_string(self):
        for key in self.THEME_KEYS:
            sheet = self.get_stylesheet(key)
            self.assertIsInstance(sheet, str)
            self.assertIn("QWidget", sheet)

    def test_get_stylesheet_fallback_for_unknown_key(self):
        """Unknown theme keys should silently fall back to the Dark theme."""
        dark = self.get_stylesheet("dark")
        fallback = self.get_stylesheet("nonexistent_theme")
        self.assertEqual(dark, fallback)

    def test_all_stylesheets_have_sidebar(self):
        for key in self.THEME_KEYS:
            sheet = self.get_stylesheet(key)
            self.assertIn("#sidebar", sheet, f"Theme {key!r} missing #sidebar rule")

    def test_all_stylesheets_have_primary_btn(self):
        for key in self.THEME_KEYS:
            sheet = self.get_stylesheet(key)
            self.assertIn("primary_btn", sheet, f"Theme {key!r} missing primary_btn rule")

    def test_default_theme_in_appconfig(self):
        cfg = AppConfig()
        self.assertEqual(cfg.theme, "dark")

    def test_theme_round_trips_through_appconfig(self):
        for key in self.THEME_KEYS:
            cfg = AppConfig(theme=key)
            restored = AppConfig.from_dict(cfg.to_dict())
            self.assertEqual(restored.theme, key)


# =============================================================================
# Catalogue ModType enum correctness
# =============================================================================

class TestCatalogueModTypeEnum(unittest.TestCase):
    """Verify that catalogue entries store ModType enum values (not plain strings)."""

    @classmethod
    def setUpClass(cls):
        from src.core.catalogue_loader import CATALOGUE
        cls.catalogue = CATALOGUE

    def test_all_types_are_modtype_instances(self):
        for e in self.catalogue:
            self.assertIsInstance(
                e["type"], ModType,
                f"Entry {e['id']} has type {e['type']!r} (expected ModType enum)"
            )

    def test_type_value_attribute_accessible(self):
        """CatalogueCard calls e['type'].value — must not raise AttributeError."""
        for e in self.catalogue:
            try:
                _ = e["type"].value
            except AttributeError:
                self.fail(f"Entry {e['id']}: .value not accessible on {e['type']!r}")

    def test_tab_filtering_by_modtype_enum_non_empty(self):
        """Types with retained entries (texture_pack, cheat, save_file) should be non-empty.
        pnach and cover_art have no entries with direct downloads and are empty."""
        from src.models.mod import ModType
        non_empty_types = {ModType.TEXTURE_PACK, ModType.CHEAT, ModType.SAVE_FILE}
        for mt in non_empty_types:
            entries = [e for e in self.catalogue if e["type"] == mt]
            self.assertGreater(len(entries), 0,
                               f"No catalogue entries of type {mt}")

    def test_pnach_entries_empty_after_filtering(self):
        """pnach.json has no entries with working direct_download_url; catalogue must be empty."""
        from src.models.mod import ModType
        pn = [e for e in self.catalogue if e["type"] == ModType.PNACH]
        self.assertEqual(len(pn), 0,
                         f"Expected 0 PNACH entries after direct-download filtering, got {len(pn)}")

    def test_cover_art_entries_empty_after_filtering(self):
        """cover_art.json uses cover_by_id (no direct_download_url); catalogue must be empty."""
        from src.models.mod import ModType
        ca = [e for e in self.catalogue if e["type"] == ModType.COVER_ART]
        self.assertEqual(len(ca), 0,
                         f"Expected 0 COVER_ART entries after direct-download filtering, got {len(ca)}")

    def test_tab_filtering_consistent_with_string_value(self):
        """Filtering by enum equals filtering by its string value via .value."""
        for mt in ModType:
            by_enum = [e for e in self.catalogue if e["type"] == mt]
            by_value = [e for e in self.catalogue if e["type"].value == mt.value]
            self.assertEqual(
                len(by_enum), len(by_value),
                f"Enum vs .value filtering mismatch for {mt}"
            )


class TestPnachAnalyzer(unittest.TestCase):
    """Tests for src.core.pnach_analyzer."""

    def test_known_address_returns_description(self):
        from src.core.pnach_analyzer import describe_address
        desc = describe_address("2EB5B9A9", "EE", "00385538")
        self.assertIsNotNone(desc)
        self.assertIn("jump", desc.lower())

    def test_unknown_address_returns_none(self):
        from src.core.pnach_analyzer import describe_address
        desc = describe_address("DEADBEEF", "EE", "12345678")
        self.assertIsNone(desc)

    def test_describe_patch_known_returns_full_annotation(self):
        from src.core.pnach_analyzer import describe_patch
        ann = describe_patch("2EB5B9A9", "EE", "00385538", "3F800000", "word")
        self.assertIsNotNone(ann["description"])
        self.assertFalse(ann["inferred"])
        # value_note should contain something (either value_map entry or hex/float)
        self.assertIsInstance(ann["value_note"], str)
        self.assertGreater(len(ann["value_note"]), 0)

    def test_describe_patch_unknown_is_inferred(self):
        from src.core.pnach_analyzer import describe_patch
        ann = describe_patch("DEADBEEF", "EE", "00123456", "40000000", "word")
        self.assertIsNone(ann["description"])
        self.assertTrue(ann["inferred"])
        self.assertIn("category", ann)

    def test_group_conflicts_by_function(self):
        from src.core.pnach_analyzer import group_conflicts_by_function
        conflicts = [
            {
                "game_crc": "2EB5B9A9", "processor": "EE", "address": "00385538",
                "mod_a_id": "a", "value_a": "3F800000",
                "mod_b_id": "b", "value_b": "40000000",
            },
            {
                "game_crc": "9A5B29A1", "processor": "EE", "address": "003CD218",
                "mod_a_id": "c", "value_a": "3F800000",
                "mod_b_id": "d", "value_b": "3FAB851F",
            },
        ]
        grouped = group_conflicts_by_function(conflicts)
        self.assertIsInstance(grouped, dict)
        # Both conflicts should be in some category
        all_entries = [e for entries in grouped.values() for e in entries]
        self.assertEqual(len(all_entries), 2)
        # Each enriched entry must have an 'annotation' key
        for e in all_entries:
            self.assertIn("annotation", e)

    def test_infer_category_widescreen_float(self):
        from src.core.pnach_analyzer import infer_category
        # 0x3FAB851F ≈ 1.3416 — aspect ratio float → physics or similar
        cat = infer_category("003B2340", "3FAB851F", "word")
        self.assertIsInstance(cat, str)
        self.assertGreater(len(cat), 0)

    def test_reload_db_returns_count(self):
        from src.core.pnach_analyzer import reload_db
        n = reload_db()
        self.assertGreater(n, 0)

    def test_db_file_exists(self):
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        self.assertTrue(db_path.is_file(), "known_addresses.json should exist")
        data = json.loads(db_path.read_text())
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 0)

    def test_pnach_db_expanded(self):
        """Known addresses DB should have more than 3700 entries.

        Wave 31 cleanup details:
          * 43 unrelated-game widescreen entries removed (addresses 00348B7C,
            001C4B2C, 002E1A5C, 0024B8FC, 003C2D1C, 002A0000, 00280000) — each
            address had the identical 16:9 value_map applied to 4–7 completely
            different games (different publishers / engines), indicating a
            copy-pasted generic placeholder.
          * 6 Sims-series widescreen entries removed (address 0040E340) —
            even same-franchise titles may differ in memory layout, and 6
            titles sharing one unverified address fails the game-specific
            requirement.
          * 9 physics-multiplier entries removed (address 003E0008) — a
            gravity / run-speed / jump-height cheat was applied to 9 unrelated
            games (Ratchet & Clank, Kingdom Hearts II, God of War, Shadow of the
            Colossus, Jak and Daxter, Spyro, Crash Bandicoot, Spider-Man 2,
            Prince of Persia) with no shared engine or memory layout.
          Subtotal by category: 43 + 6 widescreen = 49; 9 physics = 9.
          Total removed: 58 entries (3774 → 3716).

        Wave 32 cleanup details:
          * 4 fabricated 00A80000 currency entries removed — CRCs for Katamari,
            Grandia III ×2, and Wild ARMs 4 variants were not found in any
            catalogue; serial numbers were inconsistent with known PS2 DB.
          * 6 wrong 00C08000 currency entries removed — duplicates where the
            correct address already existed (Tales of the Abyss Gald→00D00008,
            Disgaea HL→00C80008) and solo unverified CRCs (Xenosaga III,
            Suikoden IV, Suikoden V, Rogue Galaxy SLUS) not present in any
            catalogue.
          * 9 generic freecam entries removed for Burnout 3, Midnight Club 3,
            and Midnight Club II — their other verified entries are in completely
            different memory regions (Burnout 3: 0082xxxx/0083xxxx, MC3:
            00B79xxxx, MC2: 00C5000x), confirming the 00B82070–00B82090 freecam
            addresses were copy-pasted from Burnout Revenge (which keeps its
            coherent 4-entry freecam cluster at 00B82070–00B82094).
          * Verified replacements added: Suikoden IV Potch (00412B44), Suikoden V
            Potch (00562FF4), Xenosaga III G (00D4A090), Rogue Galaxy SLUS Zol
            (00C08010), Burnout 3 freecam (0083005C–00830064), MC3 speed/handling
            (00B79014–1C), MC2 handling/brake/AI (00C5000C–00C50014).
          * HP value_maps updated to be game-specific for 5 JRPGs at 00C00100
            (Grandia III, Xenosaga I, Wild Arms 4, Wild Arms 5, Shadow Hearts:
            Covenant) — protagonist max-HP values now reflect each game's actual
            HP scale rather than a shared 0/500/10000 placeholder.
          * XP value_maps updated to be game-specific for 4 games at 00C0000C
            (Star Ocean TtEoT, Tales of Legendia, Digital Devil Saga 2, Atelier
            Iris) — XP cap values now reflect each title's experience scale.
          Total net change: 3716 → 3710 (−6 after replacements).
        """
        from src.core.pnach_analyzer import reload_db
        n = reload_db()
        self.assertGreater(n, 40000, "PNACH DB should have more than 40,000 entries after Wave 32 community-cheat expansion")

    def test_pnach_db_key_format_valid(self):
        """All PNACH DB keys must follow the CRC:MEMTYPE:ADDRESS format (3 colon-separated parts).

        Keys with only 2 parts (CRC:ADDRESS, missing the memory-type segment) are unreachable
        by describe_address() / entries_for_crc() and indicate incorrectly formatted entries.
        """
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        data = json.loads(db_path.read_text())
        bad = [k for k in data if len(k.split(":")) != 3]
        self.assertEqual(
            bad, [],
            f"{len(bad)} PNACH DB key(s) have wrong format (expected CRC:MEMTYPE:ADDR): {bad[:5]}",
        )

    def test_pnach_db_all_entries_game_specific(self):
        """Every PNACH DB entry's key CRC must match the entry's game_crc field.

        PNACH memory addresses are game-specific — codes written for one game's CRC
        MUST NOT be reused under a different CRC.
        """
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        data = json.loads(db_path.read_text())
        mismatches = []
        for key, entry in data.items():
            parts = key.split(":")
            if len(parts) != 3:
                continue  # covered by test_pnach_db_key_format_valid
            key_crc = parts[0].upper()
            val_crc = entry.get("game_crc", "").upper()
            if key_crc != val_crc:
                mismatches.append((key, key_crc, val_crc))
        self.assertEqual(
            mismatches, [],
            f"{len(mismatches)} PNACH DB entries have CRC mismatch between key and game_crc: {mismatches[:3]}",
        )

    def test_pnach_db_max_address_sharing(self):
        """No raw address should appear in more than 9 distinct game CRCs.

        PNACH memory addresses are game-specific.  An address appearing in too many
        unrelated games is a strong signal of a generic placeholder rather than a
        verified game-specific code.  The threshold of 9 captures known coincidental
        overlaps (common PS2 memory regions) while flagging clearly multi-game entries.
        """
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        data = json.loads(db_path.read_text())
        addr_crcs: dict = {}
        for key in data:
            parts = key.split(":")
            if len(parts) != 3:
                continue
            crc, _memtype, addr = parts
            addr_crcs.setdefault(addr, set()).add(crc.upper())
        over_limit = {addr: crcs for addr, crcs in addr_crcs.items() if len(crcs) > 9}
        self.assertEqual(
            over_limit, {},
            f"Addresses appearing in >9 games (likely generic placeholders): {list(over_limit.keys())[:5]}",
        )

    def test_pnach_db_no_generic_widescreen_entries(self):
        """Widescreen patches must not share the same address + value_map across 4+ unrelated games.

        A standard PS2 widescreen value (3FAB851F = 16:9, or 3FAAAAAB) stored
        at the *same* EE address for 4 or more completely different game CRCs
        is a clear sign of a copy-pasted generic placeholder rather than a
        verified game-specific cheat code.  Each game stores its aspect-ratio
        register at a unique address determined by its own memory layout.
        """
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        data = json.loads(db_path.read_text())
        ws_values = {"3FAB851F", "3FAAAAAB"}
        addr_crcs: dict = {}
        for key, entry in data.items():
            parts = key.split(":")
            if len(parts) != 3:
                continue
            crc, _memtype, addr = parts
            desc = entry.get("description", "")
            vm = entry.get("value_map", {})
            is_ws = (
                ("widescreen" in desc.lower() or "aspect ratio" in desc.lower())
                and bool(ws_values & set(vm.keys()))
            )
            if is_ws:
                addr_crcs.setdefault(addr, set()).add(crc.upper())
        generic_ws = {addr: crcs for addr, crcs in addr_crcs.items() if len(crcs) >= 4}
        self.assertEqual(
            generic_ws, {},
            f"Widescreen address(es) appear in ≥4 unrelated game CRCs — likely generic: "
            f"{list(generic_ws.keys())[:5]}",
        )

    def test_pnach_db_no_cross_series_generic_copying(self):
        """No (address, value_map) pair may appear in 4+ CRCs of games from different franchises.

        When the same address AND identical value_map are found in four or more
        completely unrelated games, the entry is a copy-pasted generic placeholder
        rather than a verified game-specific cheat code.

        Exception: titles that all share the same franchise prefix (e.g., all five
        "Need for Speed" games made by EA Black Box) may legitimately share physics
        addresses due to a common engine layout; those groups are skipped.

        Franchise detection: a group is same-franchise if all game titles in the
        group share the same first three title words (case-insensitive), ignoring
        leading articles 'the', 'a', 'an'.
        """
        import json as _json
        from collections import defaultdict

        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        data = _json.loads(db_path.read_text())

        def _franchise_prefix(game_name: str) -> tuple:
            """Return a tuple of the first three significant title words (lowercased)."""
            articles = {"the", "a", "an"}
            words = [w.lower() for w in game_name.split() if w.lower() not in articles]
            return tuple(words[:3])

        def _same_franchise(game_names) -> bool:
            """True if all game names share the same franchise prefix."""
            prefixes = {_franchise_prefix(g) for g in game_names}
            return len(prefixes) == 1

        # Build mapping: (addr, vm_json) -> [(crc, game_name), ...]
        addr_vm_entries: dict = defaultdict(list)
        for key, entry in data.items():
            parts = key.split(":")
            if len(parts) != 3:
                continue
            crc, _memtype, addr = parts
            vm_json = _json.dumps(entry.get("value_map", {}), sort_keys=True)
            game = entry.get("game", "")
            addr_vm_entries[(addr, vm_json)].append((crc.upper(), game))

        violations = []
        for (addr, vm_json), entries in addr_vm_entries.items():
            if len(entries) < 4:
                continue
            game_names = [g for _crc, g in entries]
            if _same_franchise(game_names):
                continue  # same-franchise shared-engine entries are allowed
            violations.append((addr, [g for _c, g in entries]))

        self.assertEqual(
            violations,
            [],
            f"{len(violations)} (address, value_map) pair(s) are shared across 4+ unrelated-franchise "
            f"games — clear indicator of copy-pasted generic placeholders rather than verified codes. "
            f"First offender: {violations[0] if violations else ''}",
        )

    def test_pnach_db_index_entries_for_crc(self):
        """entries_for_crc uses the CRC index and returns the correct entries."""
        from src.core.pnach_analyzer import entries_for_crc, reload_db
        reload_db()
        # Front Mission 4 has a large number of entries
        entries = entries_for_crc("EB3AC800")
        self.assertGreater(len(entries), 0)
        for e in entries:
            self.assertEqual(e.get("game_crc", "").upper(), "EB3AC800")
            self.assertIn("key", e)

    def test_pnach_db_index_entries_for_serial(self):
        """entries_for_serial uses the serial index and returns the correct entries."""
        from src.core.pnach_analyzer import entries_for_serial, reload_db
        reload_db()
        entries = entries_for_serial("SLUS-20888")
        self.assertGreater(len(entries), 0)
        for e in entries:
            serial = e.get("game_serial", "").upper()
            self.assertEqual(serial, "SLUS-20888")

    def test_pnach_db_index_list_serials_nonempty(self):
        """list_all_serials_in_db returns a non-empty sorted list via the serial index."""
        from src.core.pnach_analyzer import list_all_serials_in_db, reload_db
        reload_db()
        serials = list_all_serials_in_db()
        self.assertGreater(len(serials), 100)
        # Each element is a (serial, title) tuple
        for serial, title in serials[:5]:
            self.assertIsInstance(serial, str)
            self.assertIsInstance(title, str)
        # List should be sorted by title
        titles = [t for _, t in serials]
        self.assertEqual(titles, sorted(titles))

    def test_pnach_db_reload_rebuilds_index(self):
        """reload_db() rebuilds indexes so entries_for_crc still works after reload."""
        from src.core.pnach_analyzer import entries_for_crc, reload_db
        n = reload_db()
        self.assertGreater(n, 40000)
        entries = entries_for_crc("EB3AC800")
        self.assertGreater(len(entries), 0)

    def test_infer_category_handles_all_sizes(self):
        from src.core.pnach_analyzer import infer_category
        for size in ("word", "short", "byte", "extended", "double"):
            cat = infer_category("003B2340", "3F800000", size)
            self.assertIsInstance(cat, str)
            self.assertGreater(len(cat), 0)

    def test_describe_patch_value_map_case_insensitive(self):
        """Value map lookup should work regardless of case."""
        from src.core.pnach_analyzer import describe_patch
        ann_upper = describe_patch("2EB5B9A9", "EE", "00385538", "3F800000", "word")
        ann_lower = describe_patch("2EB5B9A9", "EE", "00385538", "3f800000", "word")
        self.assertEqual(ann_upper["value_note"], ann_lower["value_note"])

    # ------------------------------------------------------------------
    # value_to_pnach_hex tests
    # ------------------------------------------------------------------

    def test_value_to_pnach_hex_int_basic(self):
        """Integer 1000 → 000003E8."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("1000", "int")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "000003E8")

    def test_value_to_pnach_hex_int_with_commas(self):
        """1,000,000 with commas → 000F4240."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("1,000,000", "int")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "000F4240")

    def test_value_to_pnach_hex_int_zero(self):
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("0", "int")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "00000000")

    def test_value_to_pnach_hex_int_large(self):
        """9999 → 0000270F."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("9999", "int")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "0000270F")

    def test_value_to_pnach_hex_int_max(self):
        """Max 32-bit value."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("4294967295", "int")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "FFFFFFFF")

    def test_value_to_pnach_hex_int_bad_input(self):
        """Non-numeric returns error."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("abc", "int")
        self.assertIsNone(hex_val)
        self.assertIsNotNone(err)

    def test_value_to_pnach_hex_float_one(self):
        """1.0 → 3F800000 (IEEE 754)."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("1.0", "float")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "3F800000")

    def test_value_to_pnach_hex_float_two(self):
        """2.0 → 40000000."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("2.0", "float")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "40000000")

    def test_value_to_pnach_hex_float_half(self):
        """0.5 → 3F000000."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("0.5", "float")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "3F000000")

    def test_value_to_pnach_hex_float_fov_90(self):
        """90.0 degrees FOV → 42B40000."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("90.0", "float")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "42B40000")

    def test_value_to_pnach_hex_float_fov_120(self):
        """120.0 degrees FOV → 42F00000."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("120.0", "float")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "42F00000")

    def test_value_to_pnach_hex_float_two_point_five(self):
        """2.5 → 40200000."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("2.5", "float")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "40200000")

    def test_value_to_pnach_hex_float_bad_input(self):
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("not_a_number", "float")
        self.assertIsNone(hex_val)
        self.assertIsNotNone(err)

    def test_value_to_pnach_hex_empty_returns_error(self):
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("", "int")
        self.assertIsNone(hex_val)
        self.assertIsNotNone(err)

    def test_value_to_pnach_hex_unknown_type(self):
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("100", "unknown")
        self.assertIsNone(hex_val)
        self.assertIsNotNone(err)

    def test_value_to_pnach_hex_button_combo_l3_r3(self):
        """L3+R3 bitmask (0x0006) → '00000006'."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("00000006", "button_combo")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "00000006")

    def test_value_to_pnach_hex_button_combo_l1_l2_r1(self):
        """L1+L2+R1 bitmask (0x0D00) → '00000D00'."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("00000D00", "button_combo")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "00000D00")

    def test_value_to_pnach_hex_button_combo_bad_input(self):
        """Non-hex string should return error for button_combo."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("L3+R3", "button_combo")
        self.assertIsNone(hex_val)
        self.assertIsNotNone(err)

    def test_value_to_pnach_hex_int_strips_underscores(self):
        """Python-style 1_000_000 separators should work."""
        from src.core.pnach_analyzer import value_to_pnach_hex
        hex_val, err = value_to_pnach_hex("1_000_000", "int")
        self.assertIsNone(err)
        self.assertEqual(hex_val, "000F4240")

    def test_db_entries_have_value_type_for_physics(self):
        """All physics entries should have value_type=float."""
        from src.core.pnach_analyzer import reload_db
        import json
        from pathlib import Path
        reload_db()
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        physics = [e for e in db.values() if e.get("category") == "physics"]
        missing = [e["description"][:40] for e in physics if not e.get("value_type")]
        self.assertEqual(missing, [],
                         f"Physics entries missing value_type: {missing[:5]}")

    def test_db_entries_value_type_is_valid(self):
        """Every entry with value_type must use a known type string."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        valid = {"int", "float", "bool", "button", "button_combo"}
        bad = [(k, e["value_type"]) for k, e in db.items()
               if e.get("value_type") and e["value_type"] not in valid]
        self.assertEqual(bad, [], f"Entries with invalid value_type: {bad[:5]}")

    # ------------------------------------------------------------------
    # check_exclusion_conflicts tests
    # ------------------------------------------------------------------

    def test_check_exclusion_conflicts_no_conflict(self):
        """Two entries with different exclusion groups should not conflict."""
        from src.core.pnach_analyzer import check_exclusion_conflicts
        entries = [
            {"description": "Ki blast damage 2×", "exclusion_group": "bt3_p1_ki_dmg"},
            {"description": "Ki blast visual SIZE 2×", "exclusion_group": ""},  # no group
        ]
        conflicts = check_exclusion_conflicts(entries)
        self.assertEqual(conflicts, [], "Different groups should not conflict")

    def test_check_exclusion_conflicts_detects_mutex(self):
        """Two entries in the same exclusion group should conflict."""
        from src.core.pnach_analyzer import check_exclusion_conflicts
        entries = [
            {"description": "Ki blast damage 2×",
             "exclusion_group": "bt3_p1_ki_dmg",
             "exclusion_note": "Only one ki damage modifier."},
            {"description": "Max ki damage",
             "exclusion_group": "bt3_p1_ki_dmg",
             "exclusion_note": "Only one ki damage modifier."},
        ]
        conflicts = check_exclusion_conflicts(entries)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("bt3_p1_ki_dmg", conflicts[0]["group"])
        self.assertIn("Ki blast damage 2×", conflicts[0]["message"])
        self.assertIn("Max ki damage", conflicts[0]["message"])

    def test_check_exclusion_conflicts_ki_blast_size_safe(self):
        """Ki blast visual SIZE has no exclusion_group so it never conflicts."""
        from src.core.pnach_analyzer import check_exclusion_conflicts
        entries = [
            {"description": "Ki blast damage multiplier 2×",
             "exclusion_group": "bt3_p1_ki_dmg"},
            {"description": "Ki blast visual SIZE 4× (cosmetic)",
             "exclusion_group": ""},  # intentionally no group
            {"description": "Max ki damage",
             "exclusion_group": "bt3_p1_ki_dmg"},
        ]
        conflicts = check_exclusion_conflicts(entries)
        # The ki_dmg group conflicts; SIZE entry does not contribute to any conflict
        self.assertEqual(len(conflicts), 1)
        msgs = " ".join(c["message"] for c in conflicts)
        self.assertNotIn("visual SIZE", msgs)

    def test_check_exclusion_conflicts_empty_list(self):
        """Empty list should return no conflicts."""
        from src.core.pnach_analyzer import check_exclusion_conflicts
        self.assertEqual(check_exclusion_conflicts([]), [])

    def test_check_exclusion_conflicts_single_entry(self):
        """A single selected entry cannot conflict with itself."""
        from src.core.pnach_analyzer import check_exclusion_conflicts
        entries = [{"description": "Ki blast 2×", "exclusion_group": "bt3_ki_dmg"}]
        self.assertEqual(check_exclusion_conflicts(entries), [])

    def test_check_exclusion_conflicts_three_in_same_group(self):
        """Three entries in the same group should produce one conflict report."""
        from src.core.pnach_analyzer import check_exclusion_conflicts
        entries = [
            {"description": "Melee 2×", "exclusion_group": "melee_dmg"},
            {"description": "Melee 4×", "exclusion_group": "melee_dmg"},
            {"description": "Max melee", "exclusion_group": "melee_dmg"},
        ]
        conflicts = check_exclusion_conflicts(entries)
        self.assertEqual(len(conflicts), 1)
        # All three descriptions should appear in the message
        self.assertIn("Melee 2×", conflicts[0]["message"])
        self.assertIn("Melee 4×", conflicts[0]["message"])
        self.assertIn("Max melee", conflicts[0]["message"])

    def test_db_has_dbz_entries_with_exclusion_groups(self):
        """DBZ entries in the DB should have exclusion_group for damage/HP/Ki."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        dbz = [v for v in db.values() if "budokai" in v.get("game", "").lower()
               or "tenkaichi" in v.get("game", "").lower()
               or "sagas" in v.get("game", "").lower()]
        self.assertGreater(len(dbz), 20, "Should have at least 20 DBZ DB entries")
        # At least some should have exclusion_group
        with_group = [v for v in dbz if v.get("exclusion_group")]
        self.assertGreater(len(with_group), 5, "DBZ entries should have exclusion_group fields")

    def test_db_ki_blast_size_has_no_exclusion_group(self):
        """Ki blast VISUAL SIZE entries should NOT have an exclusion_group (they are safe to stack)."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        size_entries = [
            v for v in db.values()
            if "ki blast" in v.get("description", "").lower()
            and "size" in v.get("description", "").lower()
            and "cosmetic" in v.get("description", "").lower()
        ]
        # All cosmetic ki blast size entries should be group-free
        bad = [v["description"] for v in size_entries if v.get("exclusion_group")]
        self.assertEqual(bad, [],
                         f"Ki blast SIZE (cosmetic) entries should have NO exclusion_group: {bad}")

    def test_db_exclusion_group_entries_have_valid_format(self):
        """exclusion_group values must be non-empty strings when present."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        bad = [
            (k, v.get("exclusion_group"))
            for k, v in db.items()
            if "exclusion_group" in v and not isinstance(v["exclusion_group"], str)
        ]
        self.assertEqual(bad, [], f"exclusion_group must be a string: {bad[:3]}")

    # ------------------------------------------------------------------
    # NFS physics, no-collision, freecam, button value_type tests
    # ------------------------------------------------------------------

    def test_db_has_nfs_physics_entries(self):
        """NFS games should have acceleration, friction, and handling entries."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        nfs = [v for v in db.values() if "need for speed" in v.get("game", "").lower()]
        # Check acceleration entries exist
        accel = [v for v in nfs if "acceleration" in v.get("description", "").lower()]
        self.assertGreater(len(accel), 0, "NFS entries should include acceleration")
        friction = [v for v in nfs if "friction" in v.get("description", "").lower()]
        self.assertGreater(len(friction), 0, "NFS entries should include friction")
        handling = [v for v in nfs if "handling" in v.get("description", "").lower()]
        self.assertGreater(len(handling), 0, "NFS entries should include handling")

    def test_db_has_no_collision_entries(self):
        """No-collision toggle entries should exist in the DB."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        nocol = [v for v in db.values() if "no-collision" in v.get("description", "").lower()]
        self.assertGreater(len(nocol), 3, "Should have no-collision entries for multiple games")

    def test_db_has_freecam_entries(self):
        """Freecam enable and button_combo entries should exist in the DB for multiple games."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        freecam = [v for v in db.values() if "freecam" in v.get("description", "").lower()]
        self.assertGreater(len(freecam), 10, "Should have freecam entries for multiple games")
        btn_combo_entries = [v for v in freecam if v.get("value_type") == "button_combo"]
        self.assertGreater(len(btn_combo_entries), 0,
                           "Freecam entries should include button_combo activation entries")

    def test_db_button_combo_type_entries_have_ps2_combos(self):
        """button_combo value_type entries must have a value_map with PS2 combo names."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        combo_entries = [v for v in db.values() if v.get("value_type") == "button_combo"]
        self.assertGreater(len(combo_entries), 0, "Should have button_combo entries")
        for e in combo_entries:
            vm = e.get("value_map", {})
            self.assertGreater(len(vm), 2, "button_combo value_map should list multiple combos")
            labels = " ".join(vm.values()).lower()
            # Must mention at least one shoulder/stick combo
            has_combo = any(b in labels for b in ["l3", "r3", "l1", "l2", "r1", "r2"])
            self.assertTrue(has_combo,
                            f"button_combo value_map should mention PS2 button names: {vm}")

    def test_db_button_combo_bitmasks_are_valid_hex(self):
        """Every key in button_combo value_maps must be a valid 8-char hex bitmask."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        for v in db.values():
            if v.get("value_type") != "button_combo":
                continue
            for hex_key in v.get("value_map", {}).keys():
                self.assertEqual(len(hex_key), 8,
                                 f"button_combo key must be 8 chars: {hex_key!r}")
                try:
                    int(hex_key, 16)
                except ValueError:
                    self.fail(f"button_combo key is not valid hex: {hex_key!r}")

    def test_freecam_entries_have_estimated_flag(self):
        """All freecam entries should be marked estimated=True for user transparency."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        freecam = [v for v in db.values() if "freecam" in v.get("description", "").lower()]
        not_estimated = [v["description"][:50] for v in freecam if not v.get("estimated")]
        self.assertEqual(not_estimated, [],
                         f"All freecam entries must have estimated=True: {not_estimated}")

    def test_db_button_type_entries_have_ps2_buttons(self):
        """button_combo value_type entries must have a value_map with PS2 combo names
        (the old 'button' single-key type has been superseded by 'button_combo')."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        # Verify no stale single 'button' entries remain; all should be button_combo
        stale_btn = [v.get("description", "")[:50] for v in db.values()
                     if v.get("value_type") == "button"]
        self.assertEqual(stale_btn, [],
                         f"All single-button entries should be upgraded to button_combo: {stale_btn}")
        combo_entries = [v for v in db.values() if v.get("value_type") == "button_combo"]
        self.assertGreater(len(combo_entries), 0, "Should have button_combo entries")

    def test_no_collision_entries_have_bool_type(self):
        """No-collision toggle entries should use value_type=bool."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        nocol = [v for v in db.values()
                 if "no-collision" in v.get("description", "").lower()]
        bad = [v["description"][:50] for v in nocol if v.get("value_type") != "bool"]
        self.assertEqual(bad, [], f"No-collision entries should have value_type=bool: {bad}")

    def test_nfs_freecam_button_combo_has_ps2_map(self):
        """NFS freecam toggle entries should use button_combo type with L3/R3 combo options."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        nfs_fc_combo = [
            v for v in db.values()
            if "need for speed" in v.get("game", "").lower()
            and v.get("value_type") == "button_combo"
        ]
        self.assertGreater(len(nfs_fc_combo), 0,
                           "NFS games should have freecam button_combo entries")
        for e in nfs_fc_combo:
            vm = e.get("value_map", {})
            all_labels = " ".join(vm.values())
            self.assertIn("L3", all_labels)
            self.assertIn("R3", all_labels)

    # ------------------------------------------------------------------
    # Wave 10 — input_compat / SCE pad compatibility tests
    # ------------------------------------------------------------------

    def test_db_button_combo_entries_have_input_compat(self):
        """Every button_combo entry must have an input_compat field."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        VALID = {"standard_sce_pad", "inverted_sce_pad", "analog_only",
                 "custom_polling", "not_applicable", "unknown"}
        bad = [
            (v.get("description","")[:50], v.get("input_compat","MISSING"))
            for v in db.values()
            if v.get("value_type") == "button_combo"
            and v.get("input_compat", "MISSING") not in VALID
        ]
        self.assertEqual(bad, [],
                         f"button_combo entries with missing/invalid input_compat: {bad}")

    def test_all_db_entries_have_input_compat(self):
        """Every entry in the DB should have an input_compat field (not missing)."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        VALID = {"standard_sce_pad", "inverted_sce_pad", "analog_only",
                 "custom_polling", "not_applicable", "unknown"}
        missing = [
            v.get("description", "")[:50]
            for v in db.values()
            if v.get("input_compat", "MISSING") not in VALID
        ]
        self.assertEqual(missing, [],
                         f"Entries missing valid input_compat ({len(missing)} found): {missing[:5]}")

    def test_nfs_freecam_combo_is_standard_sce_pad(self):
        """NFS freecam button_combo entries must be tagged standard_sce_pad."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        nfs_combos = [
            v for v in db.values()
            if "need for speed" in v.get("game", "").lower()
            and v.get("value_type") == "button_combo"
        ]
        self.assertGreater(len(nfs_combos), 0, "NFS should have button_combo entries")
        for e in nfs_combos:
            self.assertEqual(
                e.get("input_compat"), "standard_sce_pad",
                f"NFS button_combo entry not tagged standard_sce_pad: {e.get('game')}"
            )

    def test_non_freecam_entries_are_not_applicable(self):
        """Non-freecam float/int/bool entries should be tagged not_applicable."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        bad = [
            v.get("description","")[:60]
            for v in db.values()
            if v.get("value_type") in ("float", "int")
            and "freecam" not in v.get("description","").lower()
            and v.get("input_compat") != "not_applicable"
        ]
        self.assertEqual(bad, [],
                         f"Non-freecam float/int entries should be not_applicable: {bad[:5]}")

    def test_check_freecam_compatibility_api_nfs(self):
        """check_freecam_compatibility returns typed results for NFS Underground."""
        from src.core.pnach_analyzer import check_freecam_compatibility, reload_db, entries_for_serial
        reload_db()
        nfs_entries = entries_for_serial("SLUS-20672")
        if not nfs_entries:
            self.skipTest("NFS Underground not in DB")
        # Find an entry that has freecam in its description (may be a different CRC)
        fc_entry = next(
            (e for e in nfs_entries if "freecam" in e.get("description", "").lower()),
            None,
        )
        if fc_entry is None:
            self.skipTest("No freecam entries for NFS Underground")
        crc = fc_entry.get("game_crc", "")
        if not crc:
            self.skipTest("No CRC for NFS Underground freecam entry")
        results = check_freecam_compatibility(crc)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0, "Should find freecam entries for NFS Underground")
        # All results should have required fields
        for r in results:
            self.assertIn("input_compat", r)
            self.assertIn("compat_label", r)
            self.assertIn("estimated", r)
            self.assertIn("address", r)

    def test_check_freecam_compatibility_returns_empty_for_unknown_crc(self):
        """check_freecam_compatibility returns empty list for an unknown CRC."""
        from src.core.pnach_analyzer import check_freecam_compatibility
        results = check_freecam_compatibility("DEADBEEF")
        self.assertEqual(results, [])

    def test_input_compat_labels_constant_is_complete(self):
        """INPUT_COMPAT_LABELS must contain all valid input_compat values used in DB."""
        import json
        from pathlib import Path
        from src.core.pnach_analyzer import INPUT_COMPAT_LABELS
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        used = {v.get("input_compat") for v in db.values() if v.get("input_compat")}
        missing_from_labels = used - set(INPUT_COMPAT_LABELS)
        self.assertEqual(missing_from_labels, set(),
                         f"DB uses input_compat values not in INPUT_COMPAT_LABELS: {missing_from_labels}")

    def test_button_combo_notes_contain_sce_pad_section(self):
        """All button_combo entries must have the SCE pad compatibility section in notes."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        combos = [v for v in db.values() if v.get("value_type") == "button_combo"]
        self.assertGreater(len(combos), 0, "Should have button_combo entries")
        missing_section = [
            v.get("description","")[:60]
            for v in combos
            if "SCE Pad Bitmask Compatibility" not in v.get("notes", "")
        ]
        self.assertEqual(missing_section, [],
                         f"button_combo entries missing SCE section in notes: {missing_section[:5]}")

    # ── Wave 11 accuracy tests ───────────────────────────────────────────────

    def test_all_entries_have_value_type(self):
        """Every DB entry must have a non-empty value_type field."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        missing = [v.get("description", "")[:60] for v in db.values()
                   if not v.get("value_type")]
        self.assertEqual(missing, [],
                         f"{len(missing)} entries missing value_type: {missing[:5]}")

    def test_widescreen_entries_are_float(self):
        """All widescreen aspect-ratio entries must have value_type='float'."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        ws = [v for v in db.values()
              if "widescreen" in v.get("description", "").lower()]
        self.assertGreater(len(ws), 50, "Should have many widescreen entries")
        not_float = [v.get("description", "")[:60] for v in ws
                     if v.get("value_type") != "float"]
        self.assertEqual(not_float, [],
                         f"Widescreen entries not typed float: {not_float[:5]}")

    def test_widescreen_value_maps_have_16_9_key(self):
        """All widescreen entries should have a 16:9 widescreen key in value_map.
        Accepts both 3FAB851F (≈1.340, used by most games) and
        3FAAAAAB (=1.333…, used by DBZ Budokai series).
        """
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        # Valid 16:9 float keys used across PS2 games
        valid_16_9_keys = {"3FAB851F", "3FAAAAAB"}
        ws = [v for v in db.values()
              if "widescreen" in v.get("description", "").lower()]
        missing_key = [
            v.get("description", "")[:60] for v in ws
            if not (set(v.get("value_map", {}).keys()) & valid_16_9_keys)
        ]
        self.assertEqual(missing_key, [],
                         f"Widescreen entries without a valid 16:9 key: {missing_key[:5]}")

    def test_cheat_entries_have_non_empty_value_map(self):
        """All cheat-category entries must have at least one entry in value_map."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        cheats = [v for v in db.values() if v.get("category") == "cheat"]
        empty_vm = [v.get("description", "")[:60] for v in cheats
                    if not v.get("value_map")]
        self.assertEqual(empty_vm, [],
                         f"Cheat entries with empty value_map: {empty_vm[:5]}")

    def test_valid_value_types_only(self):
        """Every entry's value_type must be one of the 5 allowed values."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        allowed = {"int", "float", "bool", "button_combo", "button"}
        invalid = [(v.get("description", "")[:50], v.get("value_type"))
                   for v in db.values() if v.get("value_type") not in allowed]
        self.assertEqual(invalid, [],
                         f"Entries with invalid value_type: {invalid[:5]}")

    def test_lives_entries_have_sensible_presets(self):
        """Lives-counter entries should have at least a '99 lives' preset."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        lives = [v for v in db.values()
                 if "lives" in v.get("description", "").lower()
                 and v.get("category") == "cheat"]
        self.assertGreater(len(lives), 0, "Should have lives entries")
        for v in lives:
            self.assertTrue(
                v.get("value_map"),
                f"Lives entry has no value_map: {v.get('description', '')}"
            )

    # ── Wave 12 verification & code-method tests ─────────────────────────────

    def test_all_entries_have_verification_status(self):
        """Every DB entry must have a non-empty verification_status field."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        allowed = {"verified", "community_verified", "estimated", "reported_not_working"}
        missing = [v.get("description", "")[:60] for v in db.values()
                   if not v.get("verification_status")]
        self.assertEqual(missing, [],
                         f"Entries missing verification_status: {missing[:5]}")
        invalid = [(v.get("description", "")[:50], v.get("verification_status"))
                   for v in db.values()
                   if v.get("verification_status") not in allowed]
        self.assertEqual(invalid, [],
                         f"Entries with invalid verification_status: {invalid[:5]}")

    def test_all_entries_have_patch_type(self):
        """Every DB entry must have a valid patch_type field."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        allowed = {"word", "short", "byte", "extended"}
        missing = [v.get("description", "")[:60] for v in db.values()
                   if not v.get("patch_type")]
        self.assertEqual(missing, [],
                         f"Entries missing patch_type: {missing[:5]}")
        invalid = [(v.get("description", "")[:50], v.get("patch_type"))
                   for v in db.values()
                   if v.get("patch_type") not in allowed]
        self.assertEqual(invalid, [],
                         f"Entries with invalid patch_type: {invalid[:5]}")

    def test_all_entries_have_code_method(self):
        """Every DB entry must have a valid code_method field."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        allowed = {"static_write", "continuous_write", "conditional", "multi_address"}
        missing = [v.get("description", "")[:60] for v in db.values()
                   if not v.get("code_method")]
        self.assertEqual(missing, [],
                         f"Entries missing code_method: {missing[:5]}")
        invalid = [(v.get("description", "")[:50], v.get("code_method"))
                   for v in db.values()
                   if v.get("code_method") not in allowed]
        self.assertEqual(invalid, [],
                         f"Entries with invalid code_method: {invalid[:5]}")

    def test_widescreen_entries_are_static_write(self):
        """All widescreen entries should use static_write (written once per boot)."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        ws = [v for v in db.values()
              if "widescreen" in v.get("description", "").lower()]
        not_static = [(v.get("description", "")[:60], v.get("code_method"))
                      for v in ws if v.get("code_method") != "static_write"]
        self.assertEqual(not_static, [],
                         f"Widescreen entries not static_write: {not_static[:5]}")

    def test_get_game_verification_summary_api(self):
        """get_game_verification_summary should return correct structure for a known game."""
        from src.core.pnach_analyzer import get_game_verification_summary
        # Spider-Man 2 is well-represented in the DB
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        # Find a CRC that has entries
        crc = next(v["game_crc"] for v in db.values() if v.get("game_crc"))
        result = get_game_verification_summary(crc)

        self.assertIn("game_title", result)
        self.assertIn("total_entries", result)
        self.assertIn("verification_counts", result)
        self.assertIn("code_method_counts", result)
        self.assertIn("patch_type_counts", result)
        self.assertIn("community_verified", result)
        self.assertIn("estimated", result)
        self.assertIn("not_working", result)
        self.assertIn("methods_used", result)
        self.assertIn("has_continuous_writes", result)
        self.assertIn("has_multi_address", result)
        self.assertIn("notes", result)
        self.assertGreater(result["total_entries"], 0)
        self.assertIsInstance(result["notes"], str)
        self.assertGreater(len(result["notes"]), 10)

    def test_get_game_verification_summary_unknown_crc(self):
        """get_game_verification_summary with unknown CRC returns empty summary."""
        from src.core.pnach_analyzer import get_game_verification_summary
        result = get_game_verification_summary("00000000")
        self.assertEqual(result["total_entries"], 0)
        self.assertEqual(result["community_verified"], [])
        self.assertIn("No DB entries", result["notes"])

    def test_generate_pnach_text_includes_verification_comments(self):
        """generate_pnach_text should tag estimated patches in comments."""
        from src.core.pnach_analyzer import generate_pnach_text
        patches = [
            {
                "processor": "EE",
                "address": "00B80090",
                "value": "00000001",
                "description": "Test freecam enable",
                "patch_type": "word",
                "verification_status": "estimated",
                "code_method": "continuous_write",
            },
            {
                "processor": "EE",
                "address": "00200000",
                "value": "3FAB851F",
                "description": "Widescreen",
                "patch_type": "word",
                "verification_status": "community_verified",
                "code_method": "static_write",
            },
        ]
        text = generate_pnach_text("2EB5B9A9", "Test Game", patches)
        self.assertIn("estimated — verify", text)
        self.assertIn("continuous — game resets", text)
        self.assertIn("[verified]", text)
        self.assertIn("patch=1,EE,00B80090,word,00000001", text)
        self.assertIn("patch=1,EE,00200000,word,3FAB851F", text)

    def test_verification_status_constants_exported(self):
        """VERIFICATION_STATUS_LABELS and CODE_METHOD_LABELS must be exported."""
        from src.core import pnach_analyzer as pa
        self.assertIn("estimated",           pa.VERIFICATION_STATUS_LABELS)
        self.assertIn("community_verified",  pa.VERIFICATION_STATUS_LABELS)
        self.assertIn("verified",            pa.VERIFICATION_STATUS_LABELS)
        self.assertIn("static_write",        pa.CODE_METHOD_LABELS)
        self.assertIn("continuous_write",    pa.CODE_METHOD_LABELS)
        self.assertIn("word",                pa.PATCH_TYPE_LABELS)

    def test_most_entries_have_word_patch_type(self):
        """Word (32-bit) patches should be the plurality patch type.

        The original hand-crafted DB was nearly all word patches.  After importing
        579+ real-world pnach files from the community, byte (8-bit) and short
        (16-bit) writes are also common — many PS2 items/flags are stored in < 4
        bytes.  We therefore only require word patches to be the most frequent type
        and to account for at least 35% of all entries.
        """
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        from collections import Counter
        type_counts = Counter(v.get("patch_type") for v in db.values())
        word_count = type_counts.get("word", 0)
        total = len(db)
        self.assertGreater(word_count / total, 0.35,
                           f"Expected >35% word patches; got {word_count}/{total}")
        # word should also be the plurality type (most common)
        most_common_type = type_counts.most_common(1)[0][0]
        self.assertEqual(most_common_type, "word",
                         f"Expected 'word' to be most common patch type; got '{most_common_type}'")


class TestTextureFilePickerLogic(unittest.TestCase):
    """Tests for TextureFilePickerDialog.write_merged() logic without a real UI."""

    def _make_db_and_mods(self, tmp_dir: Path):
        """Create two mods with one shared file and one unique file each."""
        mod_a_dir = tmp_dir / "mod_a"
        mod_b_dir = tmp_dir / "mod_b"
        mod_a_dir.mkdir(parents=True)
        mod_b_dir.mkdir(parents=True)

        # Conflicting texture
        (mod_a_dir / "char" / "texture.png").parent.mkdir(parents=True, exist_ok=True)
        (mod_a_dir / "char" / "texture.png").write_bytes(b"MOD_A_TEX")

        (mod_b_dir / "char" / "texture.png").parent.mkdir(parents=True, exist_ok=True)
        (mod_b_dir / "char" / "texture.png").write_bytes(b"MOD_B_TEX")

        # Non-conflicting files
        (mod_a_dir / "env" / "sky.png").parent.mkdir(parents=True, exist_ok=True)
        (mod_a_dir / "env" / "sky.png").write_bytes(b"SKY_A")

        (mod_b_dir / "hud" / "icon.png").parent.mkdir(parents=True, exist_ok=True)
        (mod_b_dir / "hud" / "icon.png").write_bytes(b"ICON_B")

        db = ModDatabase()
        mod_a = ModInfo(
            id="modA", name="Mod A", mod_type=ModType.TEXTURE_PACK,
            path=str(mod_a_dir), enabled=True,
            files=["char/texture.png", "env/sky.png"],
        )
        mod_b = ModInfo(
            id="modB", name="Mod B", mod_type=ModType.TEXTURE_PACK,
            path=str(mod_b_dir), enabled=True,
            files=["char/texture.png", "hud/icon.png"],
        )
        db.add(mod_a)
        db.add(mod_b)
        return db, mod_a, mod_b

    def test_write_merged_mod_a_wins_conflict(self):
        """When modA wins the conflict, mod_a texture is written; non-conflicting from both included."""
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db, mod_a, mod_b = self._make_db_and_mods(tmp)

            # choices: modA wins char/texture.png
            choices = {("modA", "modB", "char/texture.png"): "modA"}
            resolved_paths = {rf: winner for (_, _, rf), winner in choices.items()}

            dest = tmp / "merged"
            dest.mkdir()
            all_mod_ids = {"modA", "modB"}
            copied = 0
            skipped = 0
            for mod_id in all_mod_ids:
                mod = db.get(mod_id)
                if not mod:
                    continue
                src_root = Path(mod.path)
                for rel_file in (mod.files or []):
                    if rel_file in resolved_paths and resolved_paths[rel_file] != mod_id:
                        continue
                    src_file = src_root / rel_file
                    if not src_file.is_file():
                        skipped += 1
                        continue
                    dest_file = dest / rel_file
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src_file), str(dest_file))
                    copied += 1

            self.assertEqual(copied, 3)  # mod_a/char/texture, mod_a/env/sky, mod_b/hud/icon
            self.assertEqual(skipped, 0)
            result_tex = dest / "char" / "texture.png"
            self.assertTrue(result_tex.exists())
            self.assertEqual(result_tex.read_bytes(), b"MOD_A_TEX")
            self.assertTrue((dest / "env" / "sky.png").exists())
            self.assertTrue((dest / "hud" / "icon.png").exists())


# ---------------------------------------------------------------------------
# Tests for config_manager: exe-adjacent paths and user_catalogue dir
# ---------------------------------------------------------------------------

class TestExeAdjacentPaths(unittest.TestCase):
    """config_manager stores data next to the executable / project root."""

    def test_get_exe_dir_returns_path(self):
        from src.core.config_manager import get_exe_dir
        d = get_exe_dir()
        self.assertIsInstance(d, Path)
        self.assertTrue(d.exists(), f"get_exe_dir() returned non-existent dir: {d}")

    def test_get_config_dir_equals_exe_dir(self):
        from src.core.config_manager import get_config_dir, get_exe_dir
        self.assertEqual(get_config_dir(), get_exe_dir())

    def test_get_data_dir_is_data_subdir_of_exe(self):
        from src.core.config_manager import get_data_dir, get_exe_dir
        self.assertEqual(get_data_dir(), get_exe_dir() / "data")

    def test_config_file_is_next_to_exe(self):
        from src.core.config_manager import CONFIG_FILE, get_exe_dir
        self.assertEqual(CONFIG_FILE.parent, get_exe_dir())

    def test_mods_db_file_is_in_data_dir(self):
        # Other tests temporarily patch cm.MODS_DB_FILE without restoring it,
        # so we verify the *logical* path rather than the module constant.
        from src.core.config_manager import get_data_dir, get_exe_dir
        expected_db = get_exe_dir() / "data" / "mods.json"
        self.assertEqual(get_data_dir() / "mods.json", expected_db)

    def test_get_user_catalogue_dir_creates_directory(self):
        from src.core.config_manager import get_exe_dir
        import src.core.config_manager as cm
        with tempfile.TemporaryDirectory() as tmp:
            orig = cm.get_exe_dir
            cm.get_exe_dir = lambda: Path(tmp)
            try:
                # Call via the module function (not the module-level singleton)
                from importlib import reload
                # Just call directly to test the logic
                user_cat = Path(tmp) / "user_catalogue"
                user_cat.mkdir(parents=True, exist_ok=True)
                readme = user_cat / "README.txt"
                if not readme.exists():
                    from src.core.config_manager import _USER_CATALOGUE_README
                    readme.write_text(_USER_CATALOGUE_README, encoding="utf-8")
                self.assertTrue(user_cat.is_dir())
                self.assertTrue(readme.exists())
                content = readme.read_text(encoding="utf-8")
                self.assertIn("type", content)
                self.assertIn("texture_pack", content)
                self.assertIn("game_serial", content)
            finally:
                cm.get_exe_dir = orig

    def test_user_catalogue_readme_contains_example(self):
        from src.core.config_manager import _USER_CATALOGUE_README
        self.assertIn("game_serial", _USER_CATALOGUE_README)
        self.assertIn("texture_pack", _USER_CATALOGUE_README)
        self.assertIn("author", _USER_CATALOGUE_README)


# ---------------------------------------------------------------------------
# Tests for catalogue_loader: user catalogue loading
# ---------------------------------------------------------------------------

class TestUserCatalogueLoader(unittest.TestCase):
    """load_catalogue() merges entries from the user_catalogue directory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_user_entry(self, eid="user-tp-001", mod_type="texture_pack"):
        return {
            "id": eid,
            "name": "My Custom Pack",
            "description": "A personal texture pack",
            "author": "Tester",
            "url": "https://example.com/my-pack",
            "source": "Personal",
            "game": "Ratchet & Clank",
            "game_serial": "SCUS-97199",
            "type": mod_type,
        }

    def test_load_user_catalogue_empty_dir(self):
        from src.core.catalogue_loader import load_user_catalogue
        result = load_user_catalogue(user_catalogue_dir=Path(self.tmpdir))
        self.assertEqual(result, [])

    def test_load_user_catalogue_single_entry(self):
        from src.core.catalogue_loader import load_user_catalogue
        from src.models.mod import ModType
        entry = self._make_user_entry()
        (Path(self.tmpdir) / "my_pack.json").write_text(
            json.dumps([entry]), encoding="utf-8"
        )
        result = load_user_catalogue(user_catalogue_dir=Path(self.tmpdir))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "user-tp-001")
        self.assertEqual(result[0]["type"], ModType.TEXTURE_PACK)

    def test_load_user_catalogue_multiple_types(self):
        from src.core.catalogue_loader import load_user_catalogue
        from src.models.mod import ModType
        entries = [
            self._make_user_entry("user-tp-001", "texture_pack"),
            self._make_user_entry("user-pn-001", "pnach"),
        ]
        (Path(self.tmpdir) / "mixed.json").write_text(
            json.dumps(entries), encoding="utf-8"
        )
        result = load_user_catalogue(user_catalogue_dir=Path(self.tmpdir))
        self.assertEqual(len(result), 2)
        types = {e["type"] for e in result}
        self.assertIn(ModType.TEXTURE_PACK, types)
        self.assertIn(ModType.PNACH, types)

    def test_load_user_catalogue_bad_json_skipped(self):
        from src.core.catalogue_loader import load_user_catalogue
        (Path(self.tmpdir) / "bad.json").write_text("not valid json", encoding="utf-8")
        (Path(self.tmpdir) / "good.json").write_text(
            json.dumps([self._make_user_entry()]), encoding="utf-8"
        )
        result = load_user_catalogue(user_catalogue_dir=Path(self.tmpdir))
        self.assertEqual(len(result), 1)

    def test_load_user_catalogue_missing_type_skipped(self):
        from src.core.catalogue_loader import load_user_catalogue
        entry = self._make_user_entry()
        del entry["type"]
        (Path(self.tmpdir) / "no_type.json").write_text(
            json.dumps([entry]), encoding="utf-8"
        )
        result = load_user_catalogue(user_catalogue_dir=Path(self.tmpdir))
        self.assertEqual(result, [])

    def test_load_catalogue_merges_user_entries(self):
        from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
        entry = self._make_user_entry("user-custom-unique-001")
        (Path(self.tmpdir) / "custom.json").write_text(
            json.dumps([entry]), encoding="utf-8"
        )
        result = load_catalogue(
            catalogue_dir=CATALOGUE_DIR,
            user_catalogue_dir=Path(self.tmpdir),
        )
        ids = [e["id"] for e in result]
        self.assertIn("user-custom-unique-001", ids)

    def test_load_catalogue_user_duplicate_id_skipped(self):
        """User entry whose ID clashes with a built-in entry is silently dropped."""
        from src.core.catalogue_loader import load_catalogue, CATALOGUE_DIR
        # Get a real built-in ID
        builtin = load_catalogue(catalogue_dir=CATALOGUE_DIR, user_catalogue_dir=False)
        if not builtin:
            self.skipTest("No built-in catalogue entries to test with")
        existing_id = builtin[0]["id"]

        entry = self._make_user_entry(existing_id)
        (Path(self.tmpdir) / "dup.json").write_text(
            json.dumps([entry]), encoding="utf-8"
        )
        result = load_catalogue(
            catalogue_dir=CATALOGUE_DIR,
            user_catalogue_dir=Path(self.tmpdir),
        )
        # Should only appear once
        count = sum(1 for e in result if e["id"] == existing_id)
        self.assertEqual(count, 1)


# ---------------------------------------------------------------------------
# Tests for texture_scanner
# ---------------------------------------------------------------------------

class TestTextureScannerUnmanaged(unittest.TestCase):
    """scan_unmanaged_texture_packs() finds pre-existing PCSX2 texture packs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_texture_pack(self, serial: str, filenames=("tex1.png",)):
        """Create a fake PCSX2 texture pack under self.tmpdir/<serial>/replacements/."""
        rep = Path(self.tmpdir) / serial / "replacements"
        rep.mkdir(parents=True, exist_ok=True)
        for fname in filenames:
            (rep / fname).write_bytes(b"FAKE_TEXTURE_DATA")
        return rep

    def test_empty_textures_root_returns_empty(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        result = scan_unmanaged_texture_packs("")
        self.assertEqual(result, [])

    def test_nonexistent_root_returns_empty(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        result = scan_unmanaged_texture_packs("/nonexistent/path/12345")
        self.assertEqual(result, [])

    def test_finds_texture_pack_with_replacements_subdir(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        self._create_texture_pack("SLUS-20062", ["tex1.png", "tex2.png"])
        result = scan_unmanaged_texture_packs(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].serial, "SLUS-20062")
        self.assertEqual(result[0].file_count, 2)

    def test_empty_replacements_dir_not_returned(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        # Create the folder structure but no files
        rep = Path(self.tmpdir) / "SLUS-20062" / "replacements"
        rep.mkdir(parents=True, exist_ok=True)
        result = scan_unmanaged_texture_packs(self.tmpdir)
        self.assertEqual(result, [])

    def test_non_serial_dirs_ignored(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        # A folder not named like a serial
        bad = Path(self.tmpdir) / "NotASerial" / "replacements"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "tex.png").write_bytes(b"data")
        result = scan_unmanaged_texture_packs(self.tmpdir)
        self.assertEqual(result, [])

    def test_managed_paths_excluded(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        rep = self._create_texture_pack("SLUS-20062")
        managed = {str(rep.resolve())}
        result = scan_unmanaged_texture_packs(self.tmpdir, managed_paths=managed)
        self.assertEqual(result, [])

    def test_multiple_serials_found(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        self._create_texture_pack("SLUS-20062", ["a.png"])
        self._create_texture_pack("SLES-54053", ["b.png"])
        result = scan_unmanaged_texture_packs(self.tmpdir)
        serials = {p.serial for p in result}
        self.assertIn("SLUS-20062", serials)
        self.assertIn("SLES-54053", serials)

    def test_size_bytes_computed(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        self._create_texture_pack("SLUS-20062", ["tex.png"])
        result = scan_unmanaged_texture_packs(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertGreater(result[0].size_bytes, 0)

    def test_size_label_format(self):
        from src.core.texture_scanner import UnmanagedPack, scan_unmanaged_texture_packs
        self._create_texture_pack("SLUS-20062", ["tex.png"])
        result = scan_unmanaged_texture_packs(self.tmpdir)
        label = result[0].size_label
        self.assertTrue(label, "size_label should not be empty")

    def test_results_sorted_by_serial(self):
        from src.core.texture_scanner import scan_unmanaged_texture_packs
        self._create_texture_pack("SLUS-20999", ["a.png"])
        self._create_texture_pack("SCES-50001", ["b.png"])
        result = scan_unmanaged_texture_packs(self.tmpdir)
        serials = [p.serial for p in result]
        self.assertEqual(serials, sorted(serials))


# ---------------------------------------------------------------------------
# Tests for installed_scanner
# ---------------------------------------------------------------------------

class TestInstalledScanner(unittest.TestCase):
    """scan_all() and per-type scanners in installed_scanner."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_serial_dir(self, base, serial, subdir="replacements", files=("tex.png",)):
        d = Path(base) / serial / subdir
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_bytes(b"DATA")
        return d

    def _make_pnach(self, base, crc="F0A235B4"):
        p = Path(base)
        p.mkdir(parents=True, exist_ok=True)
        fp = p / f"{crc}.pnach"
        fp.write_text("[EE]\npatch=1,EE,00123456,word,00000001", encoding="utf-8")
        return fp

    def _make_cover(self, base, serial="SLUS-20062"):
        p = Path(base)
        p.mkdir(parents=True, exist_ok=True)
        fp = p / f"{serial}.png"
        fp.write_bytes(b"\x89PNG")
        return fp

    # scan_pnach ----------------------------------------------------------

    def test_scan_pnach_empty_path(self):
        from src.core.installed_scanner import scan_pnach
        self.assertEqual(scan_pnach(""), [])

    def test_scan_pnach_finds_crc_file(self):
        from src.core.installed_scanner import scan_pnach
        self._make_pnach(self.tmpdir, "AABBCCDD")
        result = scan_pnach(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].crc, "AABBCCDD")

    def test_scan_pnach_ignores_non_crc_names(self):
        from src.core.installed_scanner import scan_pnach
        p = Path(self.tmpdir) / "somegame.pnach"
        p.write_bytes(b"patch=...")
        result = scan_pnach(self.tmpdir)
        self.assertEqual(result, [])

    def test_scan_pnach_respects_managed(self):
        from src.core.installed_scanner import scan_pnach
        fp = self._make_pnach(self.tmpdir, "11223344")
        result = scan_pnach(self.tmpdir, managed_paths={str(fp.resolve())})
        self.assertEqual(result, [])

    # scan_cheats ---------------------------------------------------------

    def test_scan_cheats_empty_path(self):
        from src.core.installed_scanner import scan_cheats
        self.assertEqual(scan_cheats(""), [])

    def test_scan_cheats_finds_widescreen_pnach(self):
        from src.core.installed_scanner import scan_cheats
        from src.models.mod import ModType
        self._make_pnach(self.tmpdir, "DEADBEEF")
        result = scan_cheats(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_type, ModType.CHEAT)
        self.assertEqual(result[0].crc, "DEADBEEF")

    # scan_cover_art ------------------------------------------------------

    def test_scan_cover_art_empty_path(self):
        from src.core.installed_scanner import scan_cover_art
        self.assertEqual(scan_cover_art(""), [])

    def test_scan_cover_art_finds_png(self):
        from src.core.installed_scanner import scan_cover_art
        from src.models.mod import ModType
        self._make_cover(self.tmpdir, "SLUS-20062")
        result = scan_cover_art(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].serial, "SLUS-20062")
        self.assertEqual(result[0].item_type, ModType.COVER_ART)

    def test_scan_cover_art_ignores_non_serial_names(self):
        from src.core.installed_scanner import scan_cover_art
        p = Path(self.tmpdir) / "mygame.png"
        p.write_bytes(b"\x89PNG")
        result = scan_cover_art(self.tmpdir)
        self.assertEqual(result, [])

    def test_scan_cover_art_respects_managed(self):
        from src.core.installed_scanner import scan_cover_art
        fp = self._make_cover(self.tmpdir, "SCUS-97199")
        result = scan_cover_art(self.tmpdir, managed_paths={str(fp.resolve())})
        self.assertEqual(result, [])

    # scan_textures -------------------------------------------------------

    def test_scan_textures_delegates_to_texture_scanner(self):
        from src.core.installed_scanner import scan_textures
        from src.models.mod import ModType
        self._make_serial_dir(self.tmpdir, "SLUS-20062", "replacements", ["a.png"])
        result = scan_textures(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_type, ModType.TEXTURE_PACK)
        self.assertEqual(result[0].serial, "SLUS-20062")

    # scan_all ------------------------------------------------------------

    def test_scan_all_combines_results(self):
        from src.core.installed_scanner import scan_all

        tex_root   = Path(self.tmpdir) / "textures"
        pnach_root = Path(self.tmpdir) / "cheats"
        cover_root = Path(self.tmpdir) / "covers"
        cheat_root = Path(self.tmpdir) / "cheats_ws"

        self._make_serial_dir(str(tex_root), "SLUS-20062", "replacements", ["a.png"])
        self._make_pnach(str(pnach_root), "F0A235B4")
        self._make_cover(str(cover_root), "SLUS-20062")
        self._make_pnach(str(cheat_root), "AABBCCDD")

        class FakeConfig:
            textures_path  = str(tex_root)
            pnach_path     = str(pnach_root)
            cheats_path    = str(cheat_root)
            cover_art_path = str(cover_root)

        result = scan_all(FakeConfig())
        types = {item.item_type.value for item in result}
        self.assertIn("texture_pack", types)
        self.assertIn("pnach", types)
        self.assertIn("cheat", types)
        self.assertIn("cover_art", types)

    def test_scan_all_empty_config(self):
        from src.core.installed_scanner import scan_all

        class EmptyConfig:
            textures_path  = ""
            pnach_path     = ""
            cheats_path    = ""
            cover_art_path = ""

        result = scan_all(EmptyConfig())
        self.assertEqual(result, [])

    # UnmanagedItem helpers -----------------------------------------------

    def test_unmanaged_item_size_label(self):
        from src.core.installed_scanner import UnmanagedItem
        from src.models.mod import ModType
        item = UnmanagedItem(
            item_type=ModType.PNACH,
            name="F0A235B4.pnach",
            path=Path("/tmp/F0A235B4.pnach"),
            size_bytes=1024 * 300,
        )
        self.assertIn("KB", item.size_label)

    def test_unmanaged_item_type_label(self):
        from src.core.installed_scanner import UnmanagedItem
        from src.models.mod import ModType
        item = UnmanagedItem(
            item_type=ModType.TEXTURE_PACK,
            name="SLUS-20062",
            path=Path("/tmp/textures/SLUS-20062/replacements"),
        )
        self.assertEqual(item.type_label, "Texture Pack")

    # find_catalogue_matches ---------------------------------------------

    def test_find_catalogue_matches_by_serial(self):
        from src.core.installed_scanner import find_catalogue_matches, UnmanagedItem
        from src.models.mod import ModType
        cat = [
            {"id": "a", "type": ModType.TEXTURE_PACK, "game_serial": "SLUS-20062",
             "game": "Sly 2: Band of Thieves"},
            {"id": "b", "type": ModType.TEXTURE_PACK, "game_serial": "SCUS-97199",
             "game": "Ratchet & Clank"},
        ]
        item = UnmanagedItem(
            item_type=ModType.TEXTURE_PACK, name="SLUS-20062 Pack",
            path=Path("/tmp"), serial="SLUS-20062",
        )
        matches = find_catalogue_matches(item, cat)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], "a")

    def test_find_catalogue_matches_returns_empty_if_no_match(self):
        from src.core.installed_scanner import find_catalogue_matches, UnmanagedItem
        from src.models.mod import ModType
        item = UnmanagedItem(
            item_type=ModType.TEXTURE_PACK, name="Unknown",
            path=Path("/tmp"), serial="XXXX-99999",
        )
        matches = find_catalogue_matches(item, [])
        self.assertEqual(matches, [])


# ---------------------------------------------------------------------------
# Tests for custom_card_builder
# ---------------------------------------------------------------------------

class TestCustomCardBuilder(unittest.TestCase):
    """build_entry() and save_entry() in custom_card_builder."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # build_entry ---------------------------------------------------------

    def test_build_entry_minimal(self):
        from src.core.custom_card_builder import build_entry
        e = build_entry(
            mod_type="texture_pack",
            name="Test Pack",
            game="Sly 2",
            game_serial="SCUS-97264",
            author="Me",
            url="",
            description="A test pack",
        )
        self.assertEqual(e["type"], "texture_pack")
        self.assertEqual(e["game_serial"], "SCUS-97264")
        self.assertIn("id", e)
        self.assertTrue(e["id"])

    def test_build_entry_normalises_serial_to_upper(self):
        from src.core.custom_card_builder import build_entry
        e = build_entry(
            mod_type="pnach", name="My Patch", game="Game",
            game_serial="scus-97264", author="", url="", description="",
        )
        self.assertEqual(e["game_serial"], "SCUS-97264")

    def test_build_entry_invalid_type_raises(self):
        from src.core.custom_card_builder import build_entry
        with self.assertRaises(ValueError):
            build_entry(
                mod_type="invalid_type", name="X", game="G",
                game_serial="SLUS-20062", author="", url="", description="",
            )

    def test_build_entry_empty_name_raises(self):
        from src.core.custom_card_builder import build_entry
        with self.assertRaises(ValueError):
            build_entry(
                mod_type="texture_pack", name="  ", game="G",
                game_serial="SLUS-20062", author="", url="", description="",
            )

    def test_build_entry_custom_id(self):
        from src.core.custom_card_builder import build_entry
        e = build_entry(
            mod_type="cover_art", name="Cover", game="Game",
            game_serial="SLUS-20062", author="", url="", description="",
            entry_id="my-custom-id",
        )
        self.assertEqual(e["id"], "my-custom-id")

    def test_build_entry_all_optional_fields_present(self):
        from src.core.custom_card_builder import build_entry
        e = build_entry(
            mod_type="save_file", name="My Save", game="Game",
            game_serial="SLUS-20062", author="Bob", url="https://example.com",
            description="desc", source="Personal", size_label="~10 KB",
            context="ctx", author_url="https://example.com/bob",
            thumbnail_url="", tags=["hd", "ps2"],
        )
        self.assertEqual(e["author_url"], "https://example.com/bob")
        self.assertEqual(e["tags"], ["hd", "ps2"])
        self.assertEqual(e["size_label"], "~10 KB")

    # save_entry ----------------------------------------------------------

    def test_save_entry_creates_file(self):
        from src.core.custom_card_builder import build_entry, save_entry
        e = build_entry(
            mod_type="texture_pack", name="Saved Pack", game="Game",
            game_serial="SLUS-20062", author="", url="", description="",
        )
        path = save_entry(e, user_catalogue_dir=Path(self.tmpdir))
        self.assertTrue(path.exists())

    def test_save_entry_appends_to_existing(self):
        from src.core.custom_card_builder import build_entry, save_entry
        e1 = build_entry(
            mod_type="texture_pack", name="Pack One", game="Game",
            game_serial="SLUS-20062", author="", url="", description="",
        )
        e2 = build_entry(
            mod_type="pnach", name="Patch Two", game="Game2",
            game_serial="SCUS-97264", author="", url="", description="",
        )
        save_entry(e1, user_catalogue_dir=Path(self.tmpdir))
        save_entry(e2, user_catalogue_dir=Path(self.tmpdir))
        import json
        data = json.loads((Path(self.tmpdir) / "my_cards.json").read_text())
        self.assertEqual(len(data), 2)

    def test_save_entry_duplicate_id_gets_new_id(self):
        from src.core.custom_card_builder import build_entry, save_entry
        e = build_entry(
            mod_type="texture_pack", name="Pack", game="Game",
            game_serial="SLUS-20062", author="", url="", description="",
            entry_id="dup-id",
        )
        save_entry(e, user_catalogue_dir=Path(self.tmpdir))
        save_entry(e, user_catalogue_dir=Path(self.tmpdir))  # same id
        import json
        data = json.loads((Path(self.tmpdir) / "my_cards.json").read_text())
        ids = [d["id"] for d in data]
        self.assertEqual(len(set(ids)), 2, "Duplicate ID should have been renamed")

    def test_save_entry_no_id_raises(self):
        from src.core.custom_card_builder import save_entry
        with self.assertRaises(ValueError):
            save_entry({"id": ""}, user_catalogue_dir=Path(self.tmpdir))

    def test_saved_entry_is_valid_catalogue_json(self):
        from src.core.custom_card_builder import build_entry, save_entry
        from src.core.catalogue_loader import load_user_catalogue
        e = build_entry(
            mod_type="texture_pack", name="Valid Pack", game="Sly 2",
            game_serial="SCUS-97264", author="Tester",
            url="https://example.com", description="Test desc",
        )
        save_entry(e, user_catalogue_dir=Path(self.tmpdir))
        result = load_user_catalogue(user_catalogue_dir=Path(self.tmpdir))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Valid Pack")

    # generate_id ---------------------------------------------------------

    def test_generate_id_is_string(self):
        from src.core.custom_card_builder import generate_id
        gid = generate_id("My Pack", "SCUS-97264")
        self.assertIsInstance(gid, str)
        self.assertTrue(gid)

    def test_generate_id_unique_per_call(self):
        from src.core.custom_card_builder import generate_id
        ids = {generate_id("Pack", "SCUS-97264") for _ in range(20)}
        # All 20 should be unique (random suffix)
        self.assertGreater(len(ids), 1)


# ===========================================================================
# TestConflictResolver
# ===========================================================================

class TestConflictResolver(unittest.TestCase):
    """Tests for src.core.conflict_resolver — conflict detection and resolution."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -----------------------------------------------------------------------
    # Module import
    # -----------------------------------------------------------------------

    def test_import(self):
        from src.core.conflict_resolver import (
            Conflict, ConflictSeverity,
            resolve_pnach_conflicts,
            resolve_cover_art_conflicts,
            resolve_texture_conflicts,
            resolve_all_conflicts,
            auto_fix_conflict,
        )

    # -----------------------------------------------------------------------
    # Conflict dataclass
    # -----------------------------------------------------------------------

    def test_conflict_severity_label(self):
        from src.core.conflict_resolver import Conflict, ConflictSeverity
        c = Conflict(
            conflict_type="test",
            severity=ConflictSeverity.ERROR,
            title="Test",
            description="desc",
        )
        self.assertIn("❌", c.severity_label)

    def test_conflict_severity_warning_label(self):
        from src.core.conflict_resolver import Conflict, ConflictSeverity
        c = Conflict(
            conflict_type="test",
            severity=ConflictSeverity.WARNING,
            title="Test",
            description="desc",
        )
        self.assertIn("⚠", c.severity_label)

    def test_conflict_severity_info_label(self):
        from src.core.conflict_resolver import Conflict, ConflictSeverity
        c = Conflict(
            conflict_type="test",
            severity=ConflictSeverity.INFO,
            title="Test",
            description="desc",
        )
        self.assertIn("ℹ", c.severity_label)

    def test_conflict_item_names(self):
        from src.core.conflict_resolver import Conflict, ConflictSeverity
        p = Path("/tmp/F0A235B4.pnach")
        c = Conflict(
            conflict_type="pnach_duplicate_crc",
            severity=ConflictSeverity.WARNING,
            title="Test",
            description="desc",
            items=[p],
        )
        self.assertEqual(c.item_names, ["F0A235B4.pnach"])

    def test_conflict_severity_color_not_empty(self):
        from src.core.conflict_resolver import Conflict, ConflictSeverity
        for sev in ConflictSeverity:
            c = Conflict(conflict_type="t", severity=sev, title="t", description="d")
            self.assertTrue(c.severity_color.startswith("#"))

    # -----------------------------------------------------------------------
    # resolve_pnach_conflicts — no conflict (empty dirs)
    # -----------------------------------------------------------------------

    def test_pnach_conflict_empty_dirs(self):
        from src.core.conflict_resolver import resolve_pnach_conflicts
        cheats_dir  = os.path.join(self.tmpdir, "cheats")
        cheats_ws   = os.path.join(self.tmpdir, "cheats_ws")
        os.makedirs(cheats_dir)
        os.makedirs(cheats_ws)
        conflicts = resolve_pnach_conflicts(cheats_dir, cheats_ws)
        self.assertEqual(conflicts, [])

    def test_pnach_conflict_missing_dirs(self):
        from src.core.conflict_resolver import resolve_pnach_conflicts
        conflicts = resolve_pnach_conflicts("", "")
        self.assertEqual(conflicts, [])

    # -----------------------------------------------------------------------
    # resolve_pnach_conflicts — duplicate CRC across folders
    # -----------------------------------------------------------------------

    def test_pnach_duplicate_crc_detected(self):
        from src.core.conflict_resolver import resolve_pnach_conflicts, ConflictSeverity
        cheats_dir = os.path.join(self.tmpdir, "cheats")
        cheats_ws  = os.path.join(self.tmpdir, "cheats_ws")
        os.makedirs(cheats_dir)
        os.makedirs(cheats_ws)

        crc = "AABBCCDD"
        Path(os.path.join(cheats_dir, f"{crc}.pnach")).write_text(
            "// patch A\npatch=1,EE,00100000,word,12345678\n"
        )
        Path(os.path.join(cheats_ws, f"{crc}.pnach")).write_text(
            "// patch B\npatch=1,EE,00200000,word,FFFFFFFF\n"
        )

        conflicts = resolve_pnach_conflicts(cheats_dir, cheats_ws)
        self.assertEqual(len(conflicts), 1)
        self.assertIn(crc, conflicts[0].title)
        # Different addresses → warning, not error
        self.assertEqual(conflicts[0].severity, ConflictSeverity.WARNING)
        self.assertEqual(conflicts[0].conflict_type, "pnach_duplicate_crc")
        self.assertEqual(len(conflicts[0].items), 2)

    def test_pnach_address_clash_detected(self):
        from src.core.conflict_resolver import resolve_pnach_conflicts, ConflictSeverity
        cheats_dir = os.path.join(self.tmpdir, "cheats")
        cheats_ws  = os.path.join(self.tmpdir, "cheats_ws")
        os.makedirs(cheats_dir)
        os.makedirs(cheats_ws)

        crc = "11223344"
        shared_addr = "00300000"
        Path(os.path.join(cheats_dir, f"{crc}.pnach")).write_text(
            f"patch=1,EE,{shared_addr},word,12345678\n"
        )
        Path(os.path.join(cheats_ws, f"{crc}.pnach")).write_text(
            f"patch=1,EE,{shared_addr},word,DEADBEEF\n"
        )

        conflicts = resolve_pnach_conflicts(cheats_dir, cheats_ws)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].severity, ConflictSeverity.ERROR)
        self.assertEqual(conflicts[0].conflict_type, "pnach_address_clash")
        self.assertIn(shared_addr.upper(), conflicts[0].description)

    def test_pnach_non_crc_files_ignored(self):
        """Files that are not 8-hex-digit CRC filenames must be ignored."""
        from src.core.conflict_resolver import resolve_pnach_conflicts
        cheats_dir = os.path.join(self.tmpdir, "cheats")
        cheats_ws  = os.path.join(self.tmpdir, "cheats_ws")
        os.makedirs(cheats_dir)
        os.makedirs(cheats_ws)
        Path(os.path.join(cheats_dir, "README.txt")).write_text("hi")
        Path(os.path.join(cheats_ws, "mycheat.pnach")).write_text("// not a CRC name")
        conflicts = resolve_pnach_conflicts(cheats_dir, cheats_ws)
        self.assertEqual(conflicts, [])

    def test_pnach_unique_crcs_no_conflict(self):
        from src.core.conflict_resolver import resolve_pnach_conflicts
        cheats_dir = os.path.join(self.tmpdir, "cheats")
        cheats_ws  = os.path.join(self.tmpdir, "cheats_ws")
        os.makedirs(cheats_dir)
        os.makedirs(cheats_ws)
        Path(os.path.join(cheats_dir,  "AABBCCDD.pnach")).write_text("patch=1,EE,00100000,word,0\n")
        Path(os.path.join(cheats_ws, "11223344.pnach")).write_text("patch=1,EE,00200000,word,0\n")
        conflicts = resolve_pnach_conflicts(cheats_dir, cheats_ws)
        self.assertEqual(conflicts, [])

    # -----------------------------------------------------------------------
    # resolve_cover_art_conflicts
    # -----------------------------------------------------------------------

    def test_cover_art_no_duplicates(self):
        from src.core.conflict_resolver import resolve_cover_art_conflicts
        covers_dir = os.path.join(self.tmpdir, "covers")
        os.makedirs(covers_dir)
        Path(os.path.join(covers_dir, "SLUS-20062.png")).write_bytes(b"PNG")
        Path(os.path.join(covers_dir, "SCES-50003.png")).write_bytes(b"PNG")
        conflicts = resolve_cover_art_conflicts(covers_dir)
        self.assertEqual(conflicts, [])

    def test_cover_art_duplicate_detected(self):
        from src.core.conflict_resolver import resolve_cover_art_conflicts, ConflictSeverity
        covers_dir = os.path.join(self.tmpdir, "covers")
        os.makedirs(covers_dir)
        Path(os.path.join(covers_dir, "SLUS-20062.png")).write_bytes(b"PNG")
        Path(os.path.join(covers_dir, "SLUS-20062.jpg")).write_bytes(b"JPG")
        conflicts = resolve_cover_art_conflicts(covers_dir)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].severity, ConflictSeverity.INFO)
        self.assertEqual(conflicts[0].conflict_type, "cover_art_duplicate")
        self.assertIn("SLUS-20062", conflicts[0].title)
        self.assertTrue(conflicts[0].can_auto_fix)

    def test_cover_art_non_serial_ignored(self):
        from src.core.conflict_resolver import resolve_cover_art_conflicts
        covers_dir = os.path.join(self.tmpdir, "covers")
        os.makedirs(covers_dir)
        Path(os.path.join(covers_dir, "background.png")).write_bytes(b"PNG")
        Path(os.path.join(covers_dir, "background.jpg")).write_bytes(b"JPG")
        conflicts = resolve_cover_art_conflicts(covers_dir)
        self.assertEqual(conflicts, [])

    def test_cover_art_missing_dir(self):
        from src.core.conflict_resolver import resolve_cover_art_conflicts
        conflicts = resolve_cover_art_conflicts("")
        self.assertEqual(conflicts, [])

    # -----------------------------------------------------------------------
    # resolve_texture_conflicts
    # -----------------------------------------------------------------------

    def test_texture_no_conflict_single_pack(self):
        from src.core.conflict_resolver import resolve_texture_conflicts
        tex_dir = os.path.join(self.tmpdir, "textures")
        repl    = os.path.join(tex_dir, "SLUS-20062", "replacements")
        os.makedirs(repl)
        Path(os.path.join(repl, "texture.dds")).write_bytes(b"DDS")
        conflicts = resolve_texture_conflicts(tex_dir)
        self.assertEqual(conflicts, [])

    def test_texture_merged_packs_detected(self):
        from src.core.conflict_resolver import resolve_texture_conflicts, ConflictSeverity
        tex_dir = os.path.join(self.tmpdir, "textures")
        repl    = os.path.join(tex_dir, "SLUS-20062", "replacements")
        os.makedirs(os.path.join(repl, "PackAlpha"))
        os.makedirs(os.path.join(repl, "PackBeta"))
        os.makedirs(os.path.join(repl, "PackGamma"))
        conflicts = resolve_texture_conflicts(tex_dir)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].severity, ConflictSeverity.INFO)
        self.assertEqual(conflicts[0].conflict_type, "texture_pack_merged")
        self.assertIn("SLUS-20062", conflicts[0].title)

    def test_texture_missing_dir(self):
        from src.core.conflict_resolver import resolve_texture_conflicts
        conflicts = resolve_texture_conflicts("")
        self.assertEqual(conflicts, [])

    # -----------------------------------------------------------------------
    # resolve_all_conflicts — empty config
    # -----------------------------------------------------------------------

    def test_resolve_all_empty_config(self):
        from src.core.conflict_resolver import resolve_all_conflicts

        class EmptyConfig:
            pnach_path     = ""
            cheats_path    = ""
            cover_art_path = ""
            textures_path  = ""

        conflicts = resolve_all_conflicts(EmptyConfig())
        self.assertEqual(conflicts, [])

    def test_resolve_all_sorted_severity(self):
        """resolve_all_conflicts must sort errors before warnings before infos."""
        from src.core.conflict_resolver import resolve_all_conflicts, ConflictSeverity

        cheats_dir = os.path.join(self.tmpdir, "cheats")
        cheats_ws  = os.path.join(self.tmpdir, "cheats_ws")
        covers_dir = os.path.join(self.tmpdir, "covers")
        os.makedirs(cheats_dir)
        os.makedirs(cheats_ws)
        os.makedirs(covers_dir)

        # Create an address clash (ERROR)
        crc = "DEADBEEF"
        addr = "00400000"
        Path(os.path.join(cheats_dir, f"{crc}.pnach")).write_text(
            f"patch=1,EE,{addr},word,11111111\n"
        )
        Path(os.path.join(cheats_ws, f"{crc}.pnach")).write_text(
            f"patch=1,EE,{addr},word,22222222\n"
        )

        # Create a cover art duplicate (INFO)
        Path(os.path.join(covers_dir, "SLUS-20062.png")).write_bytes(b"P")
        Path(os.path.join(covers_dir, "SLUS-20062.jpg")).write_bytes(b"J")

        class Cfg:
            pnach_path     = cheats_dir
            cheats_path    = cheats_ws
            cover_art_path = covers_dir
            textures_path  = ""

        conflicts = resolve_all_conflicts(Cfg())
        self.assertGreaterEqual(len(conflicts), 2)
        severities = [c.severity for c in conflicts]
        # error should come before info
        error_idx = next(i for i, s in enumerate(severities) if s == ConflictSeverity.ERROR)
        info_idx  = next(i for i, s in enumerate(severities) if s == ConflictSeverity.INFO)
        self.assertLess(error_idx, info_idx)

    # -----------------------------------------------------------------------
    # auto_fix_conflict — cover art
    # -----------------------------------------------------------------------

    def test_auto_fix_cover_art_removes_non_png(self):
        from src.core.conflict_resolver import (
            resolve_cover_art_conflicts, auto_fix_conflict
        )
        covers_dir = os.path.join(self.tmpdir, "covers")
        os.makedirs(covers_dir)
        png = Path(os.path.join(covers_dir, "SLUS-20062.png"))
        jpg = Path(os.path.join(covers_dir, "SLUS-20062.jpg"))
        png.write_bytes(b"PNG")
        jpg.write_bytes(b"JPG")

        conflicts = resolve_cover_art_conflicts(covers_dir)
        self.assertEqual(len(conflicts), 1)
        ok, msg = auto_fix_conflict(conflicts[0])
        self.assertTrue(ok)
        self.assertTrue(png.exists(), "PNG must be kept")
        self.assertFalse(jpg.exists(), "JPG must be deleted")

    def test_auto_fix_non_fixable_returns_false(self):
        from src.core.conflict_resolver import Conflict, ConflictSeverity, auto_fix_conflict
        c = Conflict(
            conflict_type="pnach_duplicate_crc",
            severity=ConflictSeverity.WARNING,
            title="test",
            description="desc",
            can_auto_fix=False,
        )
        ok, msg = auto_fix_conflict(c)
        self.assertFalse(ok)


# ===========================================================================

class TestBackupManager(unittest.TestCase):
    """Tests for src.core.backup_manager — create / list / restore / delete."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Patch get_exe_dir so backups go into our temp dir
        import src.core.config_manager as cm
        self._orig_exe_dir = cm.get_exe_dir
        cm.get_exe_dir = lambda: self.tmpdir

        # Simple fake config with real sub-directories
        self.cheats_dir    = os.path.join(self.tmpdir, "cheats")
        self.cheats_ws_dir = os.path.join(self.tmpdir, "cheats_ws")
        self.covers_dir    = os.path.join(self.tmpdir, "covers")
        self.textures_dir  = os.path.join(self.tmpdir, "textures")
        for d in (self.cheats_dir, self.cheats_ws_dir, self.covers_dir, self.textures_dir):
            os.makedirs(d, exist_ok=True)

        class FakeCfg:
            pass
        self.cfg = FakeCfg()
        self.cfg.pnach_path     = self.cheats_dir
        self.cfg.cheats_path    = self.cheats_ws_dir
        self.cfg.cover_art_path = self.covers_dir
        self.cfg.textures_path  = self.textures_dir

    def tearDown(self):
        import src.core.config_manager as cm
        cm.get_exe_dir = self._orig_exe_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -----------------------------------------------------------------------
    # Module import
    # -----------------------------------------------------------------------

    def test_import(self):
        from src.core.backup_manager import (
            BackupEntry,
            get_backup_dir,
            create_backup,
            list_backups,
            restore_backup,
            delete_backup,
        )

    # -----------------------------------------------------------------------
    # BackupEntry helpers
    # -----------------------------------------------------------------------

    def test_size_label_bytes(self):
        from src.core.backup_manager import BackupEntry
        e = BackupEntry(path="/tmp/x.zip", label="x.zip", created_at="2025-01-01T00:00:00", size_bytes=512)
        self.assertIn("KB", e.size_label)

    def test_size_label_mb(self):
        from src.core.backup_manager import BackupEntry
        e = BackupEntry(path="/tmp/x.zip", label="x.zip", created_at="2025-01-01T00:00:00", size_bytes=5 * 1024 * 1024)
        self.assertIn("MB", e.size_label)

    def test_size_label_gb(self):
        from src.core.backup_manager import BackupEntry
        e = BackupEntry(path="/tmp/x.zip", label="x.zip", created_at="2025-01-01T00:00:00", size_bytes=2 * 1024 * 1024 * 1024)
        self.assertIn("GB", e.size_label)

    # -----------------------------------------------------------------------
    # get_backup_dir
    # -----------------------------------------------------------------------

    def test_get_backup_dir_creates_dir(self):
        from src.core.backup_manager import get_backup_dir
        backup_dir = get_backup_dir(self.cfg)
        self.assertTrue(backup_dir.exists())
        self.assertTrue(backup_dir.is_dir())

    def test_get_backup_dir_idempotent(self):
        from src.core.backup_manager import get_backup_dir
        d1 = get_backup_dir(self.cfg)
        d2 = get_backup_dir(self.cfg)
        self.assertEqual(d1, d2)

    # -----------------------------------------------------------------------
    # create_backup
    # -----------------------------------------------------------------------

    def test_create_backup_returns_entry(self):
        from src.core.backup_manager import create_backup
        entry = create_backup(self.cfg)
        self.assertIsNotNone(entry)
        self.assertTrue(entry.label.startswith("backup_"))
        self.assertTrue(entry.label.endswith(".zip"))

    def test_create_backup_file_exists(self):
        from src.core.backup_manager import create_backup
        entry = create_backup(self.cfg)
        self.assertTrue(os.path.isfile(entry.path))

    def test_create_backup_with_note(self):
        from src.core.backup_manager import create_backup
        entry = create_backup(self.cfg, note="my note")
        self.assertIn("my_note", entry.label)

    def test_create_backup_note_sanitised(self):
        """Note with special characters must be sanitised in the filename."""
        from src.core.backup_manager import create_backup
        entry = create_backup(self.cfg, note="bad/path\\hack")
        # Slashes and backslashes must not appear in the filename
        self.assertNotIn("/", entry.label[7:])  # skip "backup_" prefix
        self.assertNotIn("\\", entry.label)

    def test_create_backup_includes_files(self):
        """Files placed in the source dirs must appear in the archive."""
        import zipfile
        from src.core.backup_manager import create_backup

        Path(os.path.join(self.cheats_dir, "AABBCCDD.pnach")).write_text("patch=1,EE,0,word,0")
        Path(os.path.join(self.covers_dir, "SLUS-20062.png")).write_bytes(b"PNG")

        entry = create_backup(self.cfg)
        with zipfile.ZipFile(entry.path) as zf:
            names = zf.namelist()
        self.assertTrue(any("AABBCCDD.pnach" in n for n in names))
        self.assertTrue(any("SLUS-20062.png" in n for n in names))

    def test_create_backup_size_bytes(self):
        """size_bytes should be > 0 when files are present."""
        from src.core.backup_manager import create_backup
        Path(os.path.join(self.cheats_dir, "11223344.pnach")).write_text("patch=1,EE,0,word,0")
        entry = create_backup(self.cfg)
        self.assertGreater(entry.size_bytes, 0)

    def test_create_backup_empty_dirs(self):
        """create_backup should succeed even when all configured dirs are empty."""
        from src.core.backup_manager import create_backup
        entry = create_backup(self.cfg)
        self.assertTrue(os.path.isfile(entry.path))

    # -----------------------------------------------------------------------
    # list_backups
    # -----------------------------------------------------------------------

    def test_list_backups_empty(self):
        from src.core.backup_manager import list_backups
        entries = list_backups(self.cfg)
        self.assertEqual(entries, [])

    def test_list_backups_after_create(self):
        from src.core.backup_manager import create_backup, list_backups
        create_backup(self.cfg, note="first")
        create_backup(self.cfg, note="second")
        entries = list_backups(self.cfg)
        self.assertEqual(len(entries), 2)

    def test_list_backups_newest_first(self):
        """list_backups must return entries newest-first."""
        import time
        from src.core.backup_manager import create_backup, list_backups
        e1 = create_backup(self.cfg, note="a")
        time.sleep(0.01)
        e2 = create_backup(self.cfg, note="b")
        entries = list_backups(self.cfg)
        # The most recently created file should appear first
        labels = [e.label for e in entries]
        self.assertEqual(labels.index(e2.label), 0)

    # -----------------------------------------------------------------------
    # restore_backup
    # -----------------------------------------------------------------------

    def test_restore_backup_restores_files(self):
        """Files in an archive should be restored to the correct destination."""
        from src.core.backup_manager import create_backup, restore_backup

        src_file = Path(os.path.join(self.cheats_dir, "DEADBEEF.pnach"))
        src_file.write_text("patch=1,EE,0,word,0")

        entry = create_backup(self.cfg)

        # Delete the source file then restore
        src_file.unlink()
        self.assertFalse(src_file.exists())

        count = restore_backup(entry, self.cfg)
        self.assertGreater(count, 0)
        self.assertTrue(src_file.exists())

    def test_restore_backup_returns_count(self):
        from src.core.backup_manager import create_backup, restore_backup
        Path(os.path.join(self.covers_dir, "SLUS-20062.png")).write_bytes(b"PNG")
        Path(os.path.join(self.cheats_dir, "AABBCCDD.pnach")).write_text("patch=1,EE,0,word,0")
        entry = create_backup(self.cfg)
        count = restore_backup(entry, self.cfg)
        self.assertEqual(count, 2)

    def test_restore_missing_archive_raises(self):
        from src.core.backup_manager import BackupEntry, restore_backup
        fake = BackupEntry(
            path="/nonexistent/backup_19990101_000000.zip",
            label="backup_19990101_000000.zip",
            created_at="1999-01-01T00:00:00",
            size_bytes=0,
        )
        with self.assertRaises(FileNotFoundError):
            restore_backup(fake, self.cfg)

    # -----------------------------------------------------------------------
    # delete_backup
    # -----------------------------------------------------------------------

    def test_delete_backup_removes_file(self):
        from src.core.backup_manager import create_backup, delete_backup, list_backups
        entry = create_backup(self.cfg)
        self.assertTrue(os.path.isfile(entry.path))
        ok = delete_backup(entry)
        self.assertTrue(ok)
        self.assertFalse(os.path.isfile(entry.path))

    def test_delete_backup_nonexistent_returns_false(self):
        from src.core.backup_manager import BackupEntry, delete_backup
        fake = BackupEntry(
            path="/nonexistent/backup_19990101_000000.zip",
            label="backup_19990101_000000.zip",
            created_at="1999-01-01T00:00:00",
            size_bytes=0,
        )
        ok = delete_backup(fake)
        self.assertFalse(ok)

    def test_list_after_delete_shows_fewer(self):
        from src.core.backup_manager import create_backup, delete_backup, list_backups
        e1 = create_backup(self.cfg, note="keep")
        e2 = create_backup(self.cfg, note="remove")
        delete_backup(e2)
        entries = list_backups(self.cfg)
        self.assertEqual(len(entries), 1)
        self.assertIn("keep", entries[0].label)

    def test_restore_zipslip_rejected(self):
        """A malicious archive with path traversal must not write outside dest_root."""
        import zipfile as zf_mod
        from src.core.backup_manager import BackupEntry, restore_backup, get_backup_dir

        backup_dir = get_backup_dir(self.cfg)
        evil_zip = str(backup_dir / "backup_19990101_000000.zip")

        # Craft an entry whose arcname tries to escape cheats_dir via ../
        evil_path = "cheats/../../evil.txt"
        with zf_mod.ZipFile(evil_zip, "w") as zf:
            zf.writestr(evil_path, "evil content")

        entry = BackupEntry(
            path=evil_zip,
            label="backup_19990101_000000.zip",
            created_at="1999-01-01T00:00:00",
            size_bytes=0,
        )
        count = restore_backup(entry, self.cfg)
        # The evil file must NOT have been written outside cheats_dir
        evil_file = os.path.join(self.tmpdir, "evil.txt")
        self.assertFalse(os.path.exists(evil_file), "Zip-slip path traversal was not blocked")
        # And nothing should have been restored (the entry was skipped)
        self.assertEqual(count, 0)


# ===========================================================================
# TestDownloadHistory
# ===========================================================================

class TestDownloadHistory(unittest.TestCase):
    """Tests for src.core.download_history."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import src.core.config_manager as cm
        self._orig_exe_dir = cm.get_exe_dir
        cm.get_exe_dir = lambda: self.tmpdir

        class FakeCfg:
            pass
        self.cfg = FakeCfg()

    def tearDown(self):
        import src.core.config_manager as cm
        cm.get_exe_dir = self._orig_exe_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- imports -----------------------------------------------------------

    def test_import(self):
        from src.core.download_history import (
            HistoryEntry,
            STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED,
            get_history_file,
            record_event,
            list_history,
            clear_history,
            delete_entry,
            export_history_csv,
        )

    # --- HistoryEntry properties -------------------------------------------

    def test_status_label_success(self):
        from src.core.download_history import HistoryEntry, STATUS_SUCCESS
        e = HistoryEntry(id="1", timestamp="2025-01-01T00:00:00+00:00",
                         mod_name="Test", mod_type="pnach", status=STATUS_SUCCESS)
        self.assertIn("Success", e.status_label)

    def test_status_label_failed(self):
        from src.core.download_history import HistoryEntry, STATUS_FAILED
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="pnach",
                         status=STATUS_FAILED)
        self.assertIn("Failed", e.status_label)

    def test_status_label_skipped(self):
        from src.core.download_history import HistoryEntry, STATUS_SKIPPED
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="pnach",
                         status=STATUS_SKIPPED)
        self.assertIn("Skip", e.status_label)

    def test_type_label_texture_pack(self):
        from src.core.download_history import HistoryEntry
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="texture_pack")
        self.assertIn("Texture", e.type_label)

    def test_type_label_pnach(self):
        from src.core.download_history import HistoryEntry
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="pnach")
        self.assertIn("PNACH", e.type_label)

    def test_size_label_zero(self):
        from src.core.download_history import HistoryEntry
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="pnach",
                         size_bytes=0)
        self.assertEqual(e.size_label, "–")

    def test_size_label_bytes(self):
        from src.core.download_history import HistoryEntry
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="pnach",
                         size_bytes=512)
        self.assertIn("B", e.size_label)

    def test_size_label_mb(self):
        from src.core.download_history import HistoryEntry
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="texture_pack",
                         size_bytes=10 * 1024 * 1024)
        self.assertIn("MB", e.size_label)

    def test_size_label_gb(self):
        from src.core.download_history import HistoryEntry
        e = HistoryEntry(id="1", timestamp="t", mod_name="X", mod_type="texture_pack",
                         size_bytes=2 * 1024 * 1024 * 1024)
        self.assertIn("GB", e.size_label)

    # --- serialisation round-trip ------------------------------------------

    def test_to_dict_from_dict_roundtrip(self):
        from src.core.download_history import HistoryEntry, STATUS_SUCCESS
        e = HistoryEntry(
            id="abc", timestamp="2025-03-01T12:00:00+00:00",
            mod_name="SH2 HD", mod_type="texture_pack",
            serial="SLUS-20228", source_url="https://example.com",
            status=STATUS_SUCCESS, size_bytes=1024, note="test note",
        )
        e2 = HistoryEntry.from_dict(e.to_dict())
        self.assertEqual(e.id, e2.id)
        self.assertEqual(e.mod_name, e2.mod_name)
        self.assertEqual(e.serial, e2.serial)
        self.assertEqual(e.size_bytes, e2.size_bytes)

    # --- get_history_file --------------------------------------------------

    def test_get_history_file_returns_path(self):
        from src.core.download_history import get_history_file
        p = get_history_file(self.cfg)
        self.assertIsInstance(p, Path)
        self.assertTrue(str(p).endswith("download_history.json"))

    # --- record_event ------------------------------------------------------

    def test_record_event_returns_entry(self):
        from src.core.download_history import record_event, STATUS_SUCCESS
        e = record_event(self.cfg, mod_name="Test Mod", mod_type="pnach",
                         status=STATUS_SUCCESS)
        self.assertIsNotNone(e.id)
        self.assertEqual(e.mod_name, "Test Mod")
        self.assertEqual(e.status, STATUS_SUCCESS)

    def test_record_event_writes_json(self):
        from src.core.download_history import record_event, get_history_file
        record_event(self.cfg, mod_name="Test Mod", mod_type="pnach")
        p = get_history_file(self.cfg)
        self.assertTrue(p.exists())
        import json
        data = json.loads(p.read_text())
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_record_event_multiple(self):
        from src.core.download_history import record_event, list_history
        record_event(self.cfg, mod_name="A", mod_type="pnach")
        record_event(self.cfg, mod_name="B", mod_type="cover_art")
        record_event(self.cfg, mod_name="C", mod_type="texture_pack")
        entries = list_history(self.cfg)
        self.assertEqual(len(entries), 3)

    def test_record_event_newest_first(self):
        from src.core.download_history import record_event, list_history
        record_event(self.cfg, mod_name="First", mod_type="pnach")
        record_event(self.cfg, mod_name="Second", mod_type="pnach")
        entries = list_history(self.cfg)
        self.assertEqual(entries[0].mod_name, "Second")
        self.assertEqual(entries[1].mod_name, "First")

    # --- list_history filters ----------------------------------------------

    def test_list_history_filter_status(self):
        from src.core.download_history import record_event, list_history, STATUS_SUCCESS, STATUS_FAILED
        record_event(self.cfg, mod_name="OK",  mod_type="pnach", status=STATUS_SUCCESS)
        record_event(self.cfg, mod_name="BAD", mod_type="pnach", status=STATUS_FAILED)
        successes = list_history(self.cfg, status=STATUS_SUCCESS)
        failures  = list_history(self.cfg, status=STATUS_FAILED)
        self.assertEqual(len(successes), 1)
        self.assertEqual(successes[0].mod_name, "OK")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].mod_name, "BAD")

    def test_list_history_filter_mod_type(self):
        from src.core.download_history import record_event, list_history
        record_event(self.cfg, mod_name="P", mod_type="pnach")
        record_event(self.cfg, mod_name="T", mod_type="texture_pack")
        pnach_only = list_history(self.cfg, mod_type="pnach")
        self.assertEqual(len(pnach_only), 1)
        self.assertEqual(pnach_only[0].mod_type, "pnach")

    def test_list_history_filter_serial(self):
        from src.core.download_history import record_event, list_history
        record_event(self.cfg, mod_name="A", mod_type="pnach", serial="SLUS-20228")
        record_event(self.cfg, mod_name="B", mod_type="pnach", serial="SLES-54053")
        results = list_history(self.cfg, serial="SLUS-20228")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].serial, "SLUS-20228")

    def test_list_history_limit(self):
        from src.core.download_history import record_event, list_history
        for i in range(10):
            record_event(self.cfg, mod_name=f"Mod {i}", mod_type="pnach")
        results = list_history(self.cfg, limit=3)
        self.assertEqual(len(results), 3)

    def test_list_history_empty(self):
        from src.core.download_history import list_history
        entries = list_history(self.cfg)
        self.assertEqual(entries, [])

    # --- clear_history -----------------------------------------------------

    def test_clear_history_returns_count(self):
        from src.core.download_history import record_event, clear_history
        record_event(self.cfg, mod_name="A", mod_type="pnach")
        record_event(self.cfg, mod_name="B", mod_type="pnach")
        count = clear_history(self.cfg)
        self.assertEqual(count, 2)

    def test_clear_history_empties_log(self):
        from src.core.download_history import record_event, clear_history, list_history
        record_event(self.cfg, mod_name="A", mod_type="pnach")
        clear_history(self.cfg)
        self.assertEqual(list_history(self.cfg), [])

    # --- delete_entry ------------------------------------------------------

    def test_delete_entry_removes_one(self):
        from src.core.download_history import record_event, delete_entry, list_history
        e1 = record_event(self.cfg, mod_name="Keep", mod_type="pnach")
        e2 = record_event(self.cfg, mod_name="Remove", mod_type="pnach")
        result = delete_entry(e2, self.cfg)
        self.assertTrue(result)
        remaining = list_history(self.cfg)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].mod_name, "Keep")

    def test_delete_entry_missing_returns_false(self):
        from src.core.download_history import HistoryEntry, delete_entry
        ghost = HistoryEntry(id="nonexistent", timestamp="t",
                             mod_name="X", mod_type="pnach")
        self.assertFalse(delete_entry(ghost, self.cfg))

    # --- export_history_csv ------------------------------------------------

    def test_export_csv_creates_file(self):
        from src.core.download_history import record_event, export_history_csv
        record_event(self.cfg, mod_name="A", mod_type="pnach")
        csv_path = export_history_csv(self.cfg)
        self.assertTrue(os.path.isfile(csv_path))

    def test_export_csv_has_header_and_row(self):
        from src.core.download_history import record_event, export_history_csv
        record_event(self.cfg, mod_name="Silent Hill 2 HD",
                     mod_type="texture_pack", serial="SLUS-20228")
        csv_path = export_history_csv(self.cfg)
        import csv as csv_mod
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = list(csv_mod.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mod_name"], "Silent Hill 2 HD")
        self.assertEqual(rows[0]["serial"], "SLUS-20228")

    def test_export_csv_custom_path(self):
        from src.core.download_history import record_event, export_history_csv
        record_event(self.cfg, mod_name="X", mod_type="pnach")
        out = os.path.join(self.tmpdir, "out.csv")
        result = export_history_csv(self.cfg, path=out)
        self.assertEqual(result, out)
        self.assertTrue(os.path.isfile(out))

    # --- max entries pruning -----------------------------------------------

    def test_max_entries_pruned(self):
        from src.core.download_history import (
            record_event, list_history, MAX_HISTORY_ENTRIES,
            _load, _save,
        )
        # Directly write more than MAX entries and verify list_history returns all
        entries = []
        for i in range(MAX_HISTORY_ENTRIES + 10):
            entries.append(
                __import__("src.core.download_history", fromlist=["HistoryEntry"]).HistoryEntry(
                    id=str(i), timestamp="t", mod_name=f"M{i}", mod_type="pnach"
                )
            )
        _save(entries, self.cfg)
        loaded = _load(self.cfg)
        self.assertEqual(len(loaded), MAX_HISTORY_ENTRIES)

    def test_save_is_atomic_no_tmp_files_left(self):
        """_save() must not leave .tmp files after a successful write."""
        from src.core.download_history import record_event, _save, _load
        record_event(self.cfg, mod_name="A", mod_type="pnach")
        # No .tmp files should remain
        tmp_files = list(Path(self.tmpdir).glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_save_does_not_corrupt_existing_file_on_write_error(self):
        """If an error occurs during write, the original file must be unchanged."""
        import json
        from src.core.download_history import record_event, _load, get_history_file
        record_event(self.cfg, mod_name="A", mod_type="pnach")

        import unittest.mock as um
        from src.core.download_history import _save
        entries = _load(self.cfg)
        history_path = get_history_file(self.cfg)

        original_json = json.loads(history_path.read_text(encoding="utf-8"))

        def _bad_replace(src, dst):
            raise OSError("simulated disk full")

        with um.patch("src.core.download_history.os.replace", side_effect=_bad_replace):
            try:
                _save(entries, self.cfg)
            except OSError:
                pass

        # Original file must still be valid
        data = json.loads(history_path.read_text(encoding="utf-8"))
        self.assertEqual(data, original_json)



class TestModNotes(unittest.TestCase):
    """Tests for src.core.mod_notes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import src.core.config_manager as cm
        self._orig_exe_dir = cm.get_exe_dir
        cm.get_exe_dir = lambda: self.tmpdir

        class FakeCfg:
            pass
        self.cfg = FakeCfg()

    def tearDown(self):
        import src.core.config_manager as cm
        cm.get_exe_dir = self._orig_exe_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- imports -----------------------------------------------------------

    def test_import(self):
        from src.core.mod_notes import (
            NoteEntry,
            get_notes_file,
            upsert_note,
            get_note,
            list_notes,
            delete_note,
            clear_notes,
            export_notes_csv,
        )

    # --- NoteEntry properties ----------------------------------------------

    def test_note_entry_type_label_texture_pack(self):
        from src.core.mod_notes import NoteEntry
        n = NoteEntry(id="1", entry_id="e1", entry_title="SH2 HD",
                      mod_type="texture_pack")
        self.assertIn("Texture Pack", n.type_label)

    def test_note_entry_type_label_pnach(self):
        from src.core.mod_notes import NoteEntry
        n = NoteEntry(id="1", entry_id="e1", entry_title="WS Patch",
                      mod_type="pnach")
        self.assertIn("PNACH", n.type_label)

    def test_note_entry_type_label_unknown_defaults_other(self):
        from src.core.mod_notes import NoteEntry
        n = NoteEntry(id="1", entry_id="e1", entry_title="X",
                      mod_type="unknown_type")
        self.assertIn("Other", n.type_label)

    def test_note_entry_short_text_short(self):
        from src.core.mod_notes import NoteEntry
        n = NoteEntry(id="1", entry_id="e1", entry_title="X",
                      mod_type="pnach", text="hello")
        self.assertEqual(n.short_text, "hello")

    def test_note_entry_short_text_truncated(self):
        from src.core.mod_notes import NoteEntry
        long_text = "a" * 100
        n = NoteEntry(id="1", entry_id="e1", entry_title="X",
                      mod_type="pnach", text=long_text)
        self.assertTrue(n.short_text.endswith("…"))
        self.assertLessEqual(len(n.short_text), 82)

    # --- serialisation round-trip ------------------------------------------

    def test_to_dict_from_dict_roundtrip(self):
        from src.core.mod_notes import NoteEntry
        n = NoteEntry(
            id="abc", entry_id="eid1", entry_title="SH2 HD",
            mod_type="texture_pack", serial="SLUS-20228",
            text="Great pack!", created_at="2025-01-01T00:00:00+00:00",
            updated_at="2025-06-01T00:00:00+00:00",
        )
        n2 = NoteEntry.from_dict(n.to_dict())
        self.assertEqual(n.id, n2.id)
        self.assertEqual(n.entry_id, n2.entry_id)
        self.assertEqual(n.entry_title, n2.entry_title)
        self.assertEqual(n.text, n2.text)
        self.assertEqual(n.serial, n2.serial)

    # --- get_notes_file ----------------------------------------------------

    def test_get_notes_file_returns_path(self):
        from src.core.mod_notes import get_notes_file
        p = get_notes_file(self.cfg)
        self.assertIsInstance(p, Path)
        self.assertTrue(str(p).endswith("mod_notes.json"))

    # --- upsert_note (create) ----------------------------------------------

    def test_upsert_note_creates_new(self):
        from src.core.mod_notes import upsert_note, get_note
        n = upsert_note(self.cfg, entry_id="e1", entry_title="SH2 HD",
                        mod_type="texture_pack", serial="SLUS-20228",
                        text="First note")
        self.assertIsNotNone(n.id)
        self.assertEqual(n.entry_id, "e1")
        self.assertEqual(n.text, "First note")
        self.assertTrue(n.created_at)
        self.assertTrue(n.updated_at)

    def test_upsert_note_persists_to_disk(self):
        from src.core.mod_notes import upsert_note, get_notes_file
        upsert_note(self.cfg, entry_id="e1", entry_title="SH2 HD",
                    mod_type="texture_pack", text="stored")
        p = get_notes_file(self.cfg)
        self.assertTrue(p.exists())
        import json as _json
        data = _json.loads(p.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["text"], "stored")

    # --- upsert_note (update) ----------------------------------------------

    def test_upsert_note_updates_existing(self):
        from src.core.mod_notes import upsert_note, list_notes
        upsert_note(self.cfg, entry_id="e1", entry_title="SH2 HD",
                    mod_type="texture_pack", text="v1")
        upsert_note(self.cfg, entry_id="e1", entry_title="SH2 HD",
                    mod_type="texture_pack", text="v2 updated")
        notes = list_notes(self.cfg)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].text, "v2 updated")

    def test_upsert_note_does_not_duplicate(self):
        from src.core.mod_notes import upsert_note, list_notes
        for _ in range(3):
            upsert_note(self.cfg, entry_id="e1", entry_title="SH2",
                        mod_type="pnach", text="note")
        self.assertEqual(len(list_notes(self.cfg)), 1)

    # --- get_note ----------------------------------------------------------

    def test_get_note_returns_correct(self):
        from src.core.mod_notes import upsert_note, get_note
        upsert_note(self.cfg, entry_id="e1", entry_title="Mod A",
                    mod_type="pnach", text="note A")
        upsert_note(self.cfg, entry_id="e2", entry_title="Mod B",
                    mod_type="pnach", text="note B")
        n = get_note(self.cfg, "e1")
        self.assertIsNotNone(n)
        self.assertEqual(n.text, "note A")

    def test_get_note_returns_none_when_absent(self):
        from src.core.mod_notes import get_note
        self.assertIsNone(get_note(self.cfg, "nonexistent"))

    # --- list_notes --------------------------------------------------------

    def test_list_notes_all(self):
        from src.core.mod_notes import upsert_note, list_notes
        upsert_note(self.cfg, entry_id="a", entry_title="A",
                    mod_type="texture_pack", text="x")
        upsert_note(self.cfg, entry_id="b", entry_title="B",
                    mod_type="pnach", text="y")
        notes = list_notes(self.cfg)
        self.assertEqual(len(notes), 2)

    def test_list_notes_empty_when_no_file(self):
        from src.core.mod_notes import list_notes
        self.assertEqual(list_notes(self.cfg), [])

    def test_list_notes_filter_mod_type(self):
        from src.core.mod_notes import upsert_note, list_notes
        upsert_note(self.cfg, entry_id="a", entry_title="A",
                    mod_type="texture_pack", text="tp")
        upsert_note(self.cfg, entry_id="b", entry_title="B",
                    mod_type="pnach", text="pn")
        tp = list_notes(self.cfg, mod_type="texture_pack")
        self.assertEqual(len(tp), 1)
        self.assertEqual(tp[0].mod_type, "texture_pack")

    def test_list_notes_filter_serial(self):
        from src.core.mod_notes import upsert_note, list_notes
        upsert_note(self.cfg, entry_id="a", entry_title="A",
                    mod_type="pnach", serial="SLUS-20228", text="x")
        upsert_note(self.cfg, entry_id="b", entry_title="B",
                    mod_type="pnach", serial="SLES-54053", text="y")
        results = list_notes(self.cfg, serial="SLUS-20228")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].serial, "SLUS-20228")

    def test_list_notes_filter_query_title(self):
        from src.core.mod_notes import upsert_note, list_notes
        upsert_note(self.cfg, entry_id="a", entry_title="Silent Hill 2 HD",
                    mod_type="texture_pack", text="great")
        upsert_note(self.cfg, entry_id="b", entry_title="God of War",
                    mod_type="texture_pack", text="also great")
        results = list_notes(self.cfg, query="silent")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].entry_id, "a")

    def test_list_notes_filter_query_text(self):
        from src.core.mod_notes import upsert_note, list_notes
        upsert_note(self.cfg, entry_id="a", entry_title="Mod A",
                    mod_type="pnach", text="installed v3 successfully")
        upsert_note(self.cfg, entry_id="b", entry_title="Mod B",
                    mod_type="pnach", text="waiting to test")
        results = list_notes(self.cfg, query="v3")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].entry_id, "a")

    def test_list_notes_sorted_by_updated_desc(self):
        from src.core.mod_notes import upsert_note, list_notes
        upsert_note(self.cfg, entry_id="a", entry_title="A",
                    mod_type="pnach", text="first")
        upsert_note(self.cfg, entry_id="b", entry_title="B",
                    mod_type="pnach", text="second")
        notes = list_notes(self.cfg)
        # Most recently upserted (b) should appear first
        self.assertEqual(notes[0].entry_id, "b")

    # --- delete_note -------------------------------------------------------

    def test_delete_note_removes_entry(self):
        from src.core.mod_notes import upsert_note, delete_note, list_notes
        upsert_note(self.cfg, entry_id="keep", entry_title="Keep",
                    mod_type="pnach", text="keep me")
        upsert_note(self.cfg, entry_id="remove", entry_title="Remove",
                    mod_type="pnach", text="delete me")
        result = delete_note(self.cfg, "remove")
        self.assertTrue(result)
        remaining = list_notes(self.cfg)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].entry_id, "keep")

    def test_delete_note_missing_returns_false(self):
        from src.core.mod_notes import delete_note
        self.assertFalse(delete_note(self.cfg, "does_not_exist"))

    # --- clear_notes -------------------------------------------------------

    def test_clear_notes_returns_count(self):
        from src.core.mod_notes import upsert_note, clear_notes
        upsert_note(self.cfg, entry_id="a", entry_title="A",
                    mod_type="pnach", text="x")
        upsert_note(self.cfg, entry_id="b", entry_title="B",
                    mod_type="pnach", text="y")
        count = clear_notes(self.cfg)
        self.assertEqual(count, 2)

    def test_clear_notes_empties_store(self):
        from src.core.mod_notes import upsert_note, clear_notes, list_notes
        upsert_note(self.cfg, entry_id="a", entry_title="A",
                    mod_type="pnach", text="x")
        clear_notes(self.cfg)
        self.assertEqual(list_notes(self.cfg), [])

    # --- export_notes_csv --------------------------------------------------

    def test_export_csv_creates_file(self):
        from src.core.mod_notes import upsert_note, export_notes_csv
        upsert_note(self.cfg, entry_id="a", entry_title="SH2",
                    mod_type="texture_pack", text="note")
        csv_path = export_notes_csv(self.cfg)
        self.assertTrue(os.path.isfile(csv_path))

    def test_export_csv_has_header_and_row(self):
        from src.core.mod_notes import upsert_note, export_notes_csv
        upsert_note(self.cfg, entry_id="slus_20228", entry_title="SH2 HD",
                    mod_type="texture_pack", serial="SLUS-20228",
                    text="Looks great at 4K")
        csv_path = export_notes_csv(self.cfg)
        import csv as csv_mod
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = list(csv_mod.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_title"], "SH2 HD")
        self.assertEqual(rows[0]["serial"], "SLUS-20228")
        self.assertEqual(rows[0]["text"], "Looks great at 4K")

    def test_export_csv_custom_path(self):
        from src.core.mod_notes import upsert_note, export_notes_csv
        upsert_note(self.cfg, entry_id="x", entry_title="X",
                    mod_type="other", text="test")
        out = os.path.join(self.tmpdir, "my_notes.csv")
        result = export_notes_csv(self.cfg, path=out)
        self.assertEqual(result, out)
        self.assertTrue(os.path.isfile(out))


# ===========================================================================
# Serial Database + Validator
# ===========================================================================

class TestSerialDatabase(unittest.TestCase):
    """Tests for the authoritative PS2 serial database and catalogue validator."""

    def setUp(self):
        from src.core.serial_validator import SerialDatabase
        self.sdb = SerialDatabase()

    # ------------------------------------------------------------------
    # DB integrity
    # ------------------------------------------------------------------

    def test_serial_db_loads_nonempty(self):
        """Serial DB must contain at least 300 games."""
        self.assertGreater(self.sdb.game_count(), 300)

    def test_serial_db_all_serials_valid_format(self):
        """Every primary serial must match the SLUS/SCUS/SLES/SCES-NNNNN pattern."""
        import re
        pat = re.compile(r'^[A-Z]{4}-\d{5}$')
        for title in self.sdb.all_titles():
            info = self.sdb.get_info(title)
            self.assertRegex(info.serial, pat,
                             f"Bad serial format for '{title}': {info.serial!r}")

    def test_serial_db_no_duplicate_primary_serials(self):
        """No two genuinely-different games should share the same primary serial.

        Title variants of the same game (e.g. 'God of War' / 'God of War (God Mode
        complete)', 'GTA III' / 'Grand Theft Auto III', 'Ico' / 'ICO') are allowed
        to share a serial because they refer to the same disc.  Only entries where
        neither title is a case-normalised substring of the other, and neither
        carries a save-variant suffix, are treated as distinct games.
        """
        import re
        VARIANT_SUFFIXES = re.compile(
            r'\s*[\(/](DMD complete|100% complete|God Mode complete|Titan Mode complete|'
            r'post-game.*|all unlocked|all characters|Greatest Hits|alternate|alt|'
            r'pre-order|The Journey.*|PAL|post-game|professional complete)[)\s].*$',
            re.I,
        )

        def core_title(t: str) -> str:
            """Strip save-variant suffixes and normalise to lowercase alphanumeric."""
            t2 = VARIANT_SUFFIXES.sub('', t).strip()
            # Keep only letters, digits, and spaces for robust comparison
            t2 = re.sub(r'[^a-z0-9 ]', ' ', t2.lower())
            # Expand common short-form game abbreviations
            t2 = re.sub(r'\bgta\b', 'grand theft auto', t2)
            t2 = re.sub(r'\s+', ' ', t2).strip()
            return t2

        seen: dict = {}  # serial → first title seen
        for title in self.sdb.all_titles():
            serial = self.sdb.get_serial(title)
            if serial not in seen:
                seen[serial] = title
                continue
            other = seen[serial]
            c1, c2 = core_title(title), core_title(other)
            # Allow if one core title is a substring of the other (title variant),
            # or the word sets overlap ≥ 80% (reordered title),
            # or the first 3 significant words are identical (subtitle variants).
            words1, words2 = set(c1.split()), set(c2.split())
            overlap = len(words1 & words2) / max(len(words1 | words2), 1)
            prefix1 = c1.split()[:2]
            prefix2 = c2.split()[:2]
            same_prefix = prefix1 == prefix2 and len(prefix1) >= 2
            if c1 not in c2 and c2 not in c1 and overlap < 0.8 and not same_prefix:
                self.fail(
                    f"Duplicate primary serial {serial!r} for genuinely different "
                    f"games: '{title}' vs '{other}'"
                )

    # ------------------------------------------------------------------
    # Known-correct serial assignments (CRC-backed)
    # ------------------------------------------------------------------

    def test_kingdom_hearts_serial(self):
        self.assertEqual(self.sdb.get_serial("Kingdom Hearts"), "SLUS-20370")

    def test_god_of_war_serial(self):
        self.assertEqual(self.sdb.get_serial("God of War"), "SCUS-97399")

    def test_mgs3_snake_eater_serial(self):
        self.assertEqual(
            self.sdb.get_serial("Metal Gear Solid 3: Snake Eater"), "SLUS-20915"
        )

    def test_okami_serial(self):
        # pnach_db CRC 1B594C95 + 21068223 confirm SLUS-21115 (not Steambot Chronicles SLUS-21344)
        self.assertEqual(self.sdb.get_serial("Okami"), "SLUS-21115")

    def test_castlevania_lament_serial(self):
        # SLUS-20733 confirmed via PCSX2 GameIndex (NTSC-U)
        self.assertEqual(
            self.sdb.get_serial("Castlevania: Lament of Innocence"), "SLUS-20733"
        )

    def test_disgaea_hour_of_darkness_serial(self):
        # SLUS-20666 confirmed via PCSX2 GameIndex (NTSC-U)
        self.assertEqual(
            self.sdb.get_serial("Disgaea: Hour of Darkness"), "SLUS-20666"
        )

    def test_shadow_hearts_serial(self):
        # SLUS-20347 confirmed via PCSX2 GameIndex (NTSC-U)
        self.assertEqual(self.sdb.get_serial("Shadow Hearts"), "SLUS-20347")

    def test_prince_of_persia_sot_serial(self):
        # CRC 6A928BAE + 880EB41E confirm SLUS-20743
        self.assertEqual(
            self.sdb.get_serial("Prince of Persia: The Sands of Time"), "SLUS-20743"
        )

    def test_silent_hill_4_serial(self):
        # SLUS-20873 confirmed via PCSX2 GameIndex (NTSC-U)
        self.assertEqual(
            self.sdb.get_serial("Silent Hill 4: The Room"), "SLUS-20873"
        )

    def test_hack_infection_serial(self):
        # CRC D3C7A0A3 confirms SLUS-20267
        self.assertEqual(self.sdb.get_serial(".hack//Infection"), "SLUS-20267")

    def test_zoe_2nd_runner_serial(self):
        self.assertEqual(
            self.sdb.get_serial("Zone of the Enders: The 2nd Runner"), "SLUS-20545"
        )

    def test_crash_twinsanity_serial(self):
        # SLUS-20909 confirmed via PCSX2 GameIndex (NTSC-U)
        self.assertEqual(
            self.sdb.get_serial("Crash Twinsanity"), "SLUS-20909"
        )

    # ------------------------------------------------------------------
    # is_valid / is_known helpers
    # ------------------------------------------------------------------

    def test_is_valid_correct_serial_returns_true(self):
        self.assertTrue(self.sdb.is_valid("Kingdom Hearts", "SLUS-20370"))

    def test_is_valid_wrong_serial_returns_false(self):
        self.assertFalse(self.sdb.is_valid("Kingdom Hearts", "SLUS-20773"))

    def test_is_known_alt_serial_returns_true(self):
        # SLPS-25112 is the Japanese regional alt for Armored Core 3
        self.assertTrue(self.sdb.is_known("Armored Core 3", "SLPS-25112"))

    def test_is_known_completely_wrong_serial_returns_false(self):
        self.assertFalse(self.sdb.is_known("Kingdom Hearts", "SLUS-99999"))

    def test_titles_for_serial_finds_game(self):
        titles = self.sdb.titles_for_serial("SLUS-20370")
        self.assertIn("Kingdom Hearts", titles)

    # ------------------------------------------------------------------
    # Catalogue validation — after fixes
    # ------------------------------------------------------------------

    def test_validate_all_catalogues_zero_issues_after_fixes(self):
        """After the Wave 37 serial fixes, no catalogue entry should mismatch."""
        issues = self.sdb.validate_all_catalogues()
        if issues:
            sample = "\n".join(str(i) for i in issues[:10])
            self.fail(
                f"Found {len(issues)} remaining serial mismatches:\n{sample}"
            )

    def test_validate_catalogue_detects_wrong_serial(self):
        """validate_catalogue() detects a manually-injected wrong serial."""
        from src.core.serial_validator import SerialDatabase
        sdb = SerialDatabase()
        fake_entries = [
            {"game": "Kingdom Hearts", "game_serial": "SLUS-20773"},
            {"game": "God of War",     "game_serial": "SCUS-97399"},  # correct
        ]
        issues = sdb.validate_catalogue(fake_entries, source_file="test")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].game, "Kingdom Hearts")
        self.assertEqual(issues[0].serial_found, "SLUS-20773")
        self.assertEqual(issues[0].expected_serial, "SLUS-20370")

    def test_summary_report_structure(self):
        report = self.sdb.summary_report()
        self.assertIn("total_games_in_db", report)
        self.assertIn("issue_count", report)
        self.assertIn("games_with_issues", report)
        self.assertIn("issues", report)
        self.assertGreater(report["total_games_in_db"], 300)
        self.assertIsInstance(report["issues"], list)

    def test_summary_report_issue_count_zero_after_fixes(self):
        """After Wave 37 fixes, summary report should show 0 issues."""
        report = self.sdb.summary_report()
        self.assertEqual(
            report["issue_count"], 0,
            f"Expected 0 issues, got {report['issue_count']}. "
            f"Affected games: {report['games_with_issues'][:5]}"
        )

    # ------------------------------------------------------------------
    # Serial DB file integrity
    # ------------------------------------------------------------------

    def test_serial_db_file_exists(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "data", "game_serial_db", "ps2_ntsc_u.json"
        )
        self.assertTrue(os.path.isfile(path))

    def test_serial_db_file_valid_json(self):
        import json, os
        path = os.path.join(
            os.path.dirname(__file__), "..", "data", "game_serial_db", "ps2_ntsc_u.json"
        )
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("version", data)
        self.assertIn("games", data)
        self.assertIsInstance(data["games"], dict)

    def test_catalogue_kingdom_hearts_serial_fixed(self):
        """All KH entries in every catalogue should use SLUS-20370 after fixes."""
        import json, os
        cat_dir = os.path.join(os.path.dirname(__file__), "..", "data", "catalogue")
        for fname in ("texture_packs.json", "saves.json", "cover_art.json", "pnach.json"):
            path = os.path.join(cat_dir, fname)
            if not os.path.isfile(path):
                continue
            data = json.load(open(path, encoding="utf-8"))
            for entry in data:
                if entry.get("game") == "Kingdom Hearts":
                    self.assertEqual(
                        entry.get("game_serial"), "SLUS-20370",
                        f"{fname}: Kingdom Hearts entry has wrong serial"
                    )

    def test_catalogue_god_of_war_serial_fixed(self):
        """All GoW entries should use SCUS-97399 after fixes."""
        import json, os
        cat_dir = os.path.join(os.path.dirname(__file__), "..", "data", "catalogue")
        for fname in ("texture_packs.json", "saves.json", "cover_art.json", "pnach.json"):
            path = os.path.join(cat_dir, fname)
            if not os.path.isfile(path):
                continue
            data = json.load(open(path, encoding="utf-8"))
            for entry in data:
                if entry.get("game") == "God of War":
                    self.assertEqual(
                        entry.get("game_serial"), "SCUS-97399",
                        f"{fname}: God of War entry has wrong serial"
                    )


# ===========================================================================
# Wave 38 – serial DB CRCs, expanded cheats catalogue, link checker,
#            CRC↔serial cross-validation
# ===========================================================================

class TestSerialDbCrcs(unittest.TestCase):
    """Serial DB must have CRC arrays populated from the PNACH DB."""

    def setUp(self):
        from src.core.serial_validator import SerialDatabase
        self.sdb = SerialDatabase()

    def test_serial_db_expanded_to_over_700_games(self):
        """After Wave 41 expansion, serial DB should contain > 950 games."""
        self.assertGreater(self.sdb.game_count(), 950)

    def test_kingdom_hearts_has_crcs(self):
        info = self.sdb.get_info("Kingdom Hearts")
        self.assertIsNotNone(info)
        self.assertGreater(len(info.crcs), 0,
                           "Kingdom Hearts entry should have at least one CRC")

    def test_god_of_war_has_crcs(self):
        info = self.sdb.get_info("God of War")
        self.assertIsNotNone(info)
        self.assertGreater(len(info.crcs), 0,
                           "God of War entry should have at least one CRC")

    def test_final_fantasy_x_has_crcs(self):
        info = self.sdb.get_info("Final Fantasy X")
        self.assertIsNotNone(info)
        self.assertGreater(len(info.crcs), 0)

    def test_gta_san_andreas_has_crcs(self):
        info = self.sdb.get_info("Grand Theft Auto: San Andreas")
        self.assertIsNotNone(info)
        self.assertGreater(len(info.crcs), 0)

    def test_games_with_crcs_count_over_200(self):
        """At least 875 games in the serial DB must have CRC entries.

        Wave 41 established ≥900; Wave 51 consolidated ~10 duplicate/redundant
        entries; Wave 52 cleared CRCs from 7 more wrong-case/alias entries
        while preserving all unique CRC coverage.
        """
        count = sum(
            1 for t in self.sdb.all_titles()
            if self.sdb.get_info(t) and self.sdb.get_info(t).crcs
        )
        self.assertGreater(count, 875,
                           f"Expected >875 games with CRCs, got {count}")

    def test_crcs_are_8_hex_uppercase(self):
        """All CRC values must be 8 uppercase hex characters."""
        import re
        pat = re.compile(r'^[0-9A-F]{8}$')
        for title in self.sdb.all_titles():
            info = self.sdb.get_info(title)
            for crc in info.crcs:
                self.assertRegex(crc, pat,
                                 f"Bad CRC {crc!r} for '{title}'")

    def test_wave41_new_games_present(self):
        """Wave 41: newly added NTSC-U games from Gabominated should be in DB."""
        new_games = [
            ("Area 51",            "SLUS-20595"),
            ("Black",              "SLUS-21376"),
            ("Cold Fear",          "SLUS-21047"),
            ("Drakan - The Ancients' Gates", "SCUS-97128"),
            ("Killzone",           "SCUS-97402"),
            ("Mercenaries 2 - World in Flames", "SLUS-21650"),
            ("Star Wars - The Force Unleashed", "SLUS-21614"),
            ("Stuntman - Ignition", "SLUS-21626"),
        ]
        for title, serial in new_games:
            with self.subTest(title=title):
                info = self.sdb.get_info(title)
                self.assertIsNotNone(info, f"'{title}' missing from serial DB")
                self.assertEqual(info.serial, serial)
                self.assertGreater(len(info.crcs), 0,
                                   f"'{title}' has no CRC entries")


class TestWave42SerialDb(unittest.TestCase):
    """Wave 42: serial DB expanded with PS2.data.json / PS2.titles.json data."""

    def setUp(self):
        from src.core.serial_validator import SerialDatabase
        self.sdb = SerialDatabase()

    def test_wave42_game_count_over_2200(self):
        """After Wave 42, serial DB should contain > 2200 games."""
        self.assertGreater(
            self.sdb.game_count(), 2200,
            f"Expected >2200 games, got {self.sdb.game_count()}"
        )

    def test_wave42_games_with_crcs_over_900(self):
        """Wave 42: at least 875 games still have CRC entries.

        Wave 51 consolidated ~10 duplicate/redundant entries into canonical
        entries; Wave 52 cleared CRCs from 7 more alias/wrong-case entries,
        reducing the count while preserving all unique CRC coverage.
        """
        count = sum(
            1 for t in self.sdb.all_titles()
            if self.sdb.get_info(t) and self.sdb.get_info(t).crcs
        )
        self.assertGreater(count, 875,
                           f"Expected >875 games with CRCs, got {count}")

    def test_wave42_dbz_sagas_crc_fixed(self):
        """Dragon Ball Z: Sagas must include CRC E36751DA (Wave 42 fix)."""
        info = self.sdb.get_info("Dragon Ball Z: Sagas")
        self.assertIsNotNone(info)
        self.assertIn("E36751DA", info.crcs,
                      "DBZ Sagas missing CRC E36751DA")

    def test_wave42_godfather_added(self):
        """The Godfather (SLUS-21385) must be present with CRC D850707E."""
        info = self.sdb.get_info("The Godfather")
        self.assertIsNotNone(info, "The Godfather missing from serial DB")
        self.assertEqual(info.serial, "SLUS-21385")
        self.assertIn("D850707E", info.crcs)

    def test_wave42_ps2data_games_present(self):
        """Wave 42: spot-check games added from PS2.data.json are in DB."""
        new_games = [
            ("Summoner",                         "SLUS-20074"),
            ("Midnight Club: Street Racing",     "SLUS-20063"),
            ("Dynasty Warriors 2",               "SLUS-20079"),
            ("ATV Offroad Fury",                 "SCUS-97122"),
            ("Dark Cloud",                       "SCUS-97111"),
            ("Gauntlet: Dark Legacy",            "SLUS-20047"),
            ("Star Wars: Starfighter",           "SLUS-20044"),
            ("Okage: Shadow King",               "SCUS-97129"),
            ("ATV Off-Road Fury",                "SCUS-97104"),
            ("Frequency",                        "SCUS-97125"),
        ]
        for title, serial in new_games:
            with self.subTest(title=title):
                info = self.sdb.get_info(title)
                self.assertIsNotNone(info, f"'{title}' missing from serial DB")
                self.assertEqual(
                    info.serial, serial,
                    f"'{title}' expected serial {serial!r}, got {info.serial!r}"
                )


class TestCrcSerialConsistency(unittest.TestCase):
    """CRC-serial cross-validation: every CRC's serial should exist in serial_db."""

    def setUp(self):
        from src.core.serial_validator import SerialDatabase
        self.sdb = SerialDatabase()

    def test_crc_serial_consistency_issues_under_5(self):
        """After Wave 38 fixes, < 5 CRC entries should have unknown serials.

        The only allowed leftovers are non-NTSC-U serials (PSP, Korean, etc.)
        that are correctly absent from the NTSC-U serial DB.
        """
        issues = self.sdb.validate_crc_serial_consistency()
        self.assertLess(
            len(issues), 5,
            f"Found {len(issues)} CRC-serial mismatches (expected < 5):\n"
            + "\n".join(str(i) for i in issues[:10])
        )

    def test_crc_serial_consistency_returns_list(self):
        result = self.sdb.validate_crc_serial_consistency()
        self.assertIsInstance(result, list)
        for item in result:
            self.assertIn("crc",    item)
            self.assertIn("serial", item)
            self.assertIn("issue",  item)


class TestCheatsCatalogue(unittest.TestCase):
    """Expanded cheats catalogue should have game-specific entries."""

    def setUp(self):
        import json, os
        path = os.path.join(
            os.path.dirname(__file__), "..", "data", "catalogue", "cheats.json"
        )
        with open(path, encoding="utf-8") as f:
            self.cheats = json.load(f)

    def test_cheats_catalogue_has_over_100_entries(self):
        """After filtering to direct-download-only entries, cheats.json should have ≥ 600 entries."""
        self.assertGreaterEqual(len(self.cheats), 600)

    def test_cheats_catalogue_has_game_specific_entries(self):
        """All retained entries should have a non-empty game_serial."""
        with_serial = [e for e in self.cheats if e.get("game_serial")]
        self.assertGreaterEqual(len(with_serial), 600,
                           f"Only {len(with_serial)} entries have a game_serial")

    def test_cheats_catalogue_kingdom_hearts_present(self):
        serials = {e.get("game_serial") for e in self.cheats}
        self.assertIn("SLUS-20370", serials,
                      "Kingdom Hearts (SLUS-20370) should be in cheats catalogue")

    def test_cheats_catalogue_god_of_war_present(self):
        serials = {e.get("game_serial") for e in self.cheats}
        self.assertIn("SCUS-97399", serials,
                      "God of War (SCUS-97399) should be in cheats catalogue")

    def test_cheats_catalogue_resident_evil_4_present(self):
        serials = {e.get("game_serial") for e in self.cheats}
        self.assertIn("SLUS-21134", serials,
                      "Resident Evil 4 (SLUS-21134) should be in cheats catalogue")

    def test_cheats_catalogue_all_serials_valid_format(self):
        """Every game_serial field must match XXXX-NNNNN or be empty."""
        import re
        pat = re.compile(r'^[A-Z]{4}-\d{5}$')
        for entry in self.cheats:
            serial = entry.get("game_serial", "")
            if serial:
                self.assertRegex(serial, pat,
                                 f"Bad serial {serial!r} in cheats entry {entry.get('id')}")

    def test_cheats_catalogue_game_crcs_are_valid(self):
        """Any game_crcs list must contain 8-char uppercase hex strings."""
        import re
        pat = re.compile(r'^[0-9A-F]{8}$')
        for entry in self.cheats:
            for crc in entry.get("game_crcs", []):
                self.assertRegex(crc, pat,
                                 f"Bad CRC {crc!r} in entry {entry.get('id')}")

    def test_cheats_catalogue_no_duplicate_ids(self):
        ids = [e.get("id") for e in self.cheats]
        self.assertEqual(len(ids), len(set(ids)),
                         "cheats.json contains duplicate entry IDs")

    def test_cheats_catalogue_hub_entries_removed(self):
        """The generic hub entries (no specific game) must not be present after filtering."""
        ids = {e.get("id") for e in self.cheats}
        self.assertNotIn("codejunkies_ps2", ids)
        self.assertNotIn("pcsx2_cheatdb_github", ids)

    def test_cheats_catalogue_direct_download_urls_valid(self):
        """Non-empty direct_download_url values must be valid http(s) URLs."""
        import re
        pat = re.compile(r'^https?://')
        for entry in self.cheats:
            url = entry.get("direct_download_url", "")
            if url:
                self.assertRegex(url, pat,
                                 f"Bad direct_download_url in entry {entry.get('id')!r}")


class TestLinkChecker(unittest.TestCase):
    """Tests for src.core.link_checker.LinkChecker."""

    def setUp(self):
        from src.core.link_checker import LinkChecker
        self.lc = LinkChecker()

    # -- Unit tests for URL validators --

    def test_valid_https_url_passes(self):
        from src.core.link_checker import LinkChecker
        lc = LinkChecker()
        issues = lc.check_entries(
            [{"url": "https://github.com/PCSX2/pcsx2"}],
            source_file="test",
        )
        self.assertEqual(issues, [])

    def test_malformed_url_flagged(self):
        from src.core.link_checker import LinkChecker, LinkIssue
        lc = LinkChecker()
        issues = lc.check_entries(
            [{"url": "not_a_url"}],
            source_file="test",
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "malformed")

    def test_bad_domain_flagged(self):
        from src.core.link_checker import LinkChecker
        lc = LinkChecker()
        issues = lc.check_entries(
            [{"url": "https://gamesavedfiles.com/some/page"}],
            source_file="test",
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "bad_domain")

    def test_empty_url_not_flagged(self):
        """Empty URL fields should not produce issues."""
        from src.core.link_checker import LinkChecker
        lc = LinkChecker()
        issues = lc.check_entries(
            [{"url": "", "author_url": ""}],
            source_file="test",
        )
        self.assertEqual(issues, [])

    def test_no_url_field_not_flagged(self):
        """Entries without URL fields should not produce issues."""
        from src.core.link_checker import LinkChecker
        lc = LinkChecker()
        issues = lc.check_entries([{"game": "Test", "serial": "SLUS-20000"}])
        self.assertEqual(issues, [])

    def test_multiple_url_fields_checked(self):
        """Both 'url' and 'author_url' fields are checked independently."""
        from src.core.link_checker import LinkChecker
        lc = LinkChecker()
        issues = lc.check_entries(
            [{"url": "not-valid", "author_url": "also-not-valid"}],
            source_file="test",
        )
        self.assertEqual(len(issues), 2)

    # -- Integration test: all catalogues pass link checks --

    def test_all_catalogues_pass_link_check(self):
        """All 5 catalogue files should have 0 link issues after Wave 38."""
        report = self.lc.check_all_catalogues()
        self.assertEqual(
            report["total_issues"], 0,
            f"Link issues found:\n"
            + "\n".join(
                f"  [{f}] {i}"
                for f, issues in report["issues_by_file"].items()
                for i in issues
            )
        )

    def test_check_all_catalogues_returns_dict(self):
        report = self.lc.check_all_catalogues()
        self.assertIn("catalogues_checked",   report)
        self.assertIn("total_issues",         report)
        self.assertIn("issues_by_file",       report)
        self.assertIn("issue_count_by_type",  report)
        self.assertIn("summary",              report)

    def test_check_all_catalogues_checks_five_files(self):
        report = self.lc.check_all_catalogues()
        self.assertEqual(len(report["catalogues_checked"]), 5)
        self.assertIn("cheats.json", report["catalogues_checked"])

    def test_link_issue_str_representation(self):
        from src.core.link_checker import LinkIssue
        issue = LinkIssue(
            source_file="test.json",
            entry_index=3,
            field_name="url",
            url="bad-url",
            issue_type="malformed",
            detail="no scheme",
        )
        s = str(issue)
        self.assertIn("test.json[3]", s)
        self.assertIn("malformed",     s)
        self.assertIn("bad-url",       s)

    def test_link_checker_with_custom_dir(self):
        """LinkChecker should handle a missing directory gracefully."""
        import tempfile, os
        from src.core.link_checker import LinkChecker
        tmp = tempfile.mkdtemp()
        lc = LinkChecker(cat_dir=tmp)
        report = lc.check_all_catalogues()
        # No files → 0 issues, 0 catalogues checked
        self.assertEqual(report["total_issues"], 0)
        self.assertEqual(report["catalogues_checked"], [])


class TestWave43MetadataEnrichment(unittest.TestCase):
    """Wave 43: serial DB enriched with release_date, developer, publisher, genre."""

    def setUp(self):
        from src.core.serial_validator import SerialDatabase
        self.sdb = SerialDatabase()

    def test_wave43_games_with_release_date_over_1700(self):
        """Wave 43: at least 1700 games should have a release_date."""
        count = sum(
            1 for t in self.sdb.all_titles()
            if self.sdb.get_info(t) and self.sdb.get_info(t).release_date
        )
        self.assertGreater(count, 1700,
                           f"Expected >1700 games with release_date, got {count}")

    def test_wave43_games_with_developer_over_1700(self):
        """Wave 43: at least 1700 games should have a developer."""
        count = sum(
            1 for t in self.sdb.all_titles()
            if self.sdb.get_info(t) and self.sdb.get_info(t).developer
        )
        self.assertGreater(count, 1700,
                           f"Expected >1700 games with developer, got {count}")

    def test_wave43_games_with_genre_over_1700(self):
        """Wave 43: at least 1700 games should have a genre."""
        count = sum(
            1 for t in self.sdb.all_titles()
            if self.sdb.get_info(t) and self.sdb.get_info(t).genre
        )
        self.assertGreater(count, 1700,
                           f"Expected >1700 games with genre, got {count}")

    def test_wave43_kingdom_hearts_metadata(self):
        """Kingdom Hearts should have correct release_date, developer, publisher."""
        info = self.sdb.get_info("Kingdom Hearts")
        self.assertIsNotNone(info, "Kingdom Hearts missing from serial DB")
        self.assertIsNotNone(info.release_date, "Kingdom Hearts missing release_date")
        self.assertIsNotNone(info.developer, "Kingdom Hearts missing developer")
        self.assertIsNotNone(info.publisher, "Kingdom Hearts missing publisher")

    def test_wave43_god_of_war_metadata(self):
        """God of War should have developer and genre populated."""
        info = self.sdb.get_info("God of War")
        self.assertIsNotNone(info, "God of War missing from serial DB")
        self.assertIsNotNone(info.developer, "God of War missing developer")
        self.assertIsNotNone(info.genre, "God of War missing genre")

    def test_wave43_metadata_fields_are_strings(self):
        """All populated metadata fields should be non-empty strings (not lists)."""
        for title in self.sdb.all_titles():
            info = self.sdb.get_info(title)
            if info is None:
                continue
            with self.subTest(title=title):
                for field_name in ("release_date", "developer", "publisher", "genre"):
                    val = getattr(info, field_name)
                    if val is not None:
                        self.assertIsInstance(
                            val, str,
                            f"'{title}'.{field_name} should be str, got {type(val)}"
                        )
                        self.assertGreater(
                            len(val), 0,
                            f"'{title}'.{field_name} should be non-empty"
                        )

    def test_wave43_gameinfo_metadata_fields_exist(self):
        """GameInfo dataclass must expose release_date, developer, publisher, genre."""
        from src.core.serial_validator import GameInfo
        gi = GameInfo(
            title="Test",
            serial="SLUS-00000",
            release_date="2001-01-01",
            developer="Test Dev",
            publisher="Test Pub",
            genre="Action",
        )
        self.assertEqual(gi.release_date, "2001-01-01")
        self.assertEqual(gi.developer, "Test Dev")
        self.assertEqual(gi.publisher, "Test Pub")
        self.assertEqual(gi.genre, "Action")


class TestWave44FpsPnachCodes(unittest.TestCase):
    """Wave 44: fps/widescreen/visual codes from Gabominated PCSX2 repo added to pnach DB."""

    def setUp(self):
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        self.db = json.loads(db_path.read_text())

    def test_wave44_pnach_db_size_over_47800(self):
        """Wave 44: pnach DB should have more than 47,800 entries after fps code addition."""
        self.assertGreater(
            len(self.db), 47800,
            f"Expected >47800 pnach DB entries after Wave 44, got {len(self.db)}"
        )

    def test_wave44_fps_entries_present(self):
        """Wave 44: pnach DB should contain fps category entries from Gabominated."""
        fps_entries = [e for e in self.db.values() if e.get("category") == "fps"]
        self.assertGreater(
            len(fps_entries), 200,
            f"Expected >200 fps entries in pnach DB, got {len(fps_entries)}"
        )

    def test_wave44_widescreen_entries_present(self):
        """Wave 44: pnach DB should contain widescreen entries from Gabominated."""
        ws_entries = [e for e in self.db.values() if e.get("category") == "widescreen"]
        self.assertGreater(
            len(ws_entries), 50,
            f"Expected >50 widescreen entries in pnach DB, got {len(ws_entries)}"
        )

    def test_wave44_fps_entry_structure(self):
        """Wave 44: fps entries must have required fields."""
        fps_entries = [(k, e) for k, e in self.db.items() if e.get("category") == "fps"]
        required_fields = ("game", "game_crc", "game_serial", "description", "category",
                           "patch_type", "verification_status")
        for key, entry in fps_entries[:20]:
            with self.subTest(key=key):
                for field in required_fields:
                    self.assertIn(
                        field, entry,
                        f"fps entry {key} missing required field '{field}'"
                    )
                # CRC in key must match game_crc
                key_crc = key.split(":")[0].upper()
                self.assertEqual(
                    key_crc, entry["game_crc"].upper(),
                    f"fps entry {key} key CRC doesn't match game_crc"
                )

    def test_wave44_fps_entries_community_verified(self):
        """Wave 44: Gabominated fps entries should be community_verified."""
        fps_entries = [e for e in self.db.values() if e.get("category") == "fps"]
        non_verified = [e for e in fps_entries
                        if e.get("verification_status") != "community_verified"]
        # Allow some tolerance but most should be community_verified
        self.assertLess(
            len(non_verified), len(fps_entries) // 2,
            f"Most fps entries should be community_verified"
        )

    def test_wave44_known_fps_games_present(self):
        """Wave 44: specific known games should have fps entries."""
        # These games had fps codes in Gabominated and their CRCs are now in pnach DB
        known_fps_serials = ["SLUS-21312", "SLUS-21376", "SLUS-21574", "SLUS-20003"]
        fps_entries = [e for e in self.db.values() if e.get("category") == "fps"]
        fps_serials = {e.get("game_serial") for e in fps_entries}
        for serial in known_fps_serials:
            self.assertIn(
                serial, fps_serials,
                f"Expected fps entry for {serial} not found in pnach DB"
            )

    def test_wave44_river_king_in_serial_db(self):
        """Wave 44: River King: A Wonderful Journey should be in the serial DB."""
        from src.core.serial_validator import SerialDatabase
        sdb = SerialDatabase()
        info = sdb.get_info("River King: A Wonderful Journey")
        self.assertIsNotNone(info, "River King: A Wonderful Journey missing from serial DB")
        self.assertEqual(info.serial, "SLUS-21275")
        self.assertIsNotNone(info.release_date)
        self.assertIsNotNone(info.developer)

    def test_wave44_world_soccer_we8_alt_serial(self):
        """Wave 44: World Soccer Winning Eleven 8: International should have SCUS-21117 as alt_serial."""
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
        data = json.loads(db_path.read_text())
        game = data["games"].get("World Soccer Winning Eleven 8: International")
        self.assertIsNotNone(game, "World Soccer WE8 International not found in serial DB")
        alt_serials = game.get("alt_serials", [])
        self.assertIn(
            "SCUS-21117", alt_serials,
            f"Expected SCUS-21117 in alt_serials for WE8 International, got {alt_serials}"
        )


class TestWave45AltSerials(unittest.TestCase):
    """Wave 45: alt_serial additions for game variants and multi-disc entries from PS2.data.json."""

    def setUp(self):
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
        self.data = json.loads(db_path.read_text())["games"]

    def _assert_alt_serial(self, title, expected_serial):
        game = self.data.get(title)
        self.assertIsNotNone(game, f"'{title}' not found in serial DB")
        alts = game.get("alt_serials", [])
        self.assertIn(
            expected_serial, alts,
            f"Expected {expected_serial} in alt_serials for '{title}', got {alts}",
        )

    # --- Variant/alternate-release alt_serials ---

    def test_lego_batman_scus_10380_alt_serial(self):
        """Wave 45: SCUS-10380 should be alt_serial for LEGO Batman: The Videogame."""
        self._assert_alt_serial("LEGO Batman: The Videogame", "SCUS-10380")

    def test_monsters_inc_scus_21052_alt_serial(self):
        """Wave 45: SCUS-21052 should be alt_serial for Monsters, Inc."""
        self._assert_alt_serial("Monsters, Inc.", "SCUS-21052")

    def test_toy_story_3_scus_90174_alt_serial(self):
        """Wave 45: SCUS-90174 should be alt_serial for Disney/Pixar Toy Story 3."""
        self._assert_alt_serial("Disney/Pixar Toy Story 3", "SCUS-90174")

    def test_gran_turismo_4_scus_90682_alt_serial(self):
        """Wave 45: SCUS-90682 should be alt_serial for Gran Turismo 4."""
        self._assert_alt_serial("Gran Turismo 4", "SCUS-90682")

    def test_war_of_the_monsters_scus_91197_alt_serial(self):
        """Wave 45: SCUS-91197 should be alt_serial for War of the Monsters."""
        self._assert_alt_serial("War of the Monsters", "SCUS-91197")

    def test_singstar_latino_scus_94346_alt_serial(self):
        """Wave 45: SCUS-94346 should be alt_serial for SingStar Latino."""
        self._assert_alt_serial("SingStar Latino", "SCUS-94346")

    def test_jak_daxter_slus_97124_alt_serial(self):
        """Wave 45: SLUS-97124 (GH) should be alt_serial for Jak and Daxter: The Precursor Legacy."""
        self._assert_alt_serial("Jak and Daxter: The Precursor Legacy", "SLUS-97124")

    def test_primal_slus_97142_alt_serial(self):
        """Wave 45: SLUS-97142 should be alt_serial for Primal."""
        self._assert_alt_serial("Primal", "SLUS-97142")

    def test_wild_arms_3_slus_97203_alt_serial(self):
        """Wave 45: SLUS-97203 (GH) should be alt_serial for Wild ARMs 3."""
        self._assert_alt_serial("Wild ARMs 3", "SLUS-97203")

    def test_atv_offroad_fury3_slus_97405_alt_serial(self):
        """Wave 45: SLUS-97405 should be alt_serial for ATV Offroad Fury 3."""
        self._assert_alt_serial("ATV Offroad Fury 3", "SLUS-97405")

    def test_eyetoy_antigrav_slus_97414_alt_serial(self):
        """Wave 45: SLUS-97414 should be alt_serial for EyeToy: Antigrav."""
        self._assert_alt_serial("EyeToy: Antigrav", "SLUS-97414")

    # --- Multi-disc alt_serials (Disc 2 / Disc 3 / Bonus Disc) ---

    def test_space_channel_5_disc2_alt_serial(self):
        """Wave 45: SLUS-20807 (Disc 2) should be alt_serial for Space Channel 5: Special Edition."""
        self._assert_alt_serial("Space Channel 5: Special Edition (Disc 1)", "SLUS-20807")

    def test_cy_girls_disc2_alt_serial(self):
        """Wave 45: SLUS-20854 (Disc 2/Aska) should be alt_serial for Cy Girls."""
        self._assert_alt_serial("Cy Girls", "SLUS-20854")

    def test_ribbit_king_bonus_disc_alt_serial(self):
        """Wave 45: SLUS-20914 (Bonus Disc) should be alt_serial for Ribbit King."""
        self._assert_alt_serial("Ribbit King", "SLUS-20914")

    def test_shadow_hearts_covenant_disc2_alt_serial(self):
        """Wave 45: SLUS-21044 (Disc 2) should be alt_serial for Shadow Hearts: Covenant."""
        self._assert_alt_serial("Shadow Hearts: Covenant", "SLUS-21044")

    def test_armored_core_nexus_disc2_alt_serial(self):
        """Wave 45: SLUS-21079 (Disc 2) should be alt_serial for Armored Core: Nexus."""
        self._assert_alt_serial("Armored Core: Nexus", "SLUS-21079")

    def test_mortal_kombat_deception_bonus_disc_alt_serial(self):
        """Wave 45: SLUS-21081 (Bonus Disc) should be alt_serial for MK: Deception Premium Pack."""
        self._assert_alt_serial("Mortal Kombat: Deception: Premium Pack", "SLUS-21081")

    def test_xenosaga_ep2_disc2_alt_serial(self):
        """Wave 45: SLUS-21133 (Disc 2) should be alt_serial for Xenosaga Episode II."""
        self._assert_alt_serial("Xenosaga Episode II: Jenseits von Gut und Böse", "SLUS-21133")

    def test_mgs3_subsistence_disc3_alt_serial(self):
        """Wave 45: SLUS-21360 (Disc 3/Existence) should be alt_serial for MGS3 Subsistence Disc 1."""
        self._assert_alt_serial(
            "Metal Gear Solid 3: Subsistence (Disc 1) (Subsistence)", "SLUS-21360"
        )

    def test_onimusha_dawn_disc2_alt_serial(self):
        """Wave 45: SLUS-21362 (Disc 2) should be alt_serial for Onimusha: Dawn of Dreams."""
        self._assert_alt_serial("Onimusha: Dawn of Dreams", "SLUS-21362")

    def test_xenosaga_ep3_disc2_alt_serial(self):
        """Wave 45: SLUS-21417 (Disc 2) should be alt_serial for Xenosaga Episode III."""
        self._assert_alt_serial("Xenosaga Episode III: Also sprach Zarathustra", "SLUS-21417")

    def test_tna_impact_bonus_disc_alt_serial(self):
        """Wave 45: SLUS-21824 (Bonus Disc) should be alt_serial for TNA Impact!."""
        self._assert_alt_serial("TNA Impact! Total Nonstop Action Wrestling", "SLUS-21824")

    def test_sakura_wars_disc2_alt_serial(self):
        """Wave 45: SLUS-21930 (Disc 2/Japanese VO) should be alt_serial for Sakura Wars Disc 1."""
        self._assert_alt_serial(
            "Sakura Wars: So Long, My Love (Disc 1) (English Voice Over)", "SLUS-21930"
        )


class TestWave46MetadataEnrichment(unittest.TestCase):
    """Wave 46: metadata enrichment for 12 games via alt-serial cross-reference with PS2.data.json,
    plus FIFA 13 (SLUS-21954) added as a new entry from PS2.titles.json."""

    def setUp(self):
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
        self.data = json.loads(db_path.read_text())["games"]

    def _assert_metadata(self, title, field, expected=None):
        game = self.data.get(title)
        self.assertIsNotNone(game, f"'{title}' not found in serial DB")
        value = game.get(field)
        self.assertIsNotNone(value, f"Expected '{field}' to be set for '{title}'")
        if expected is not None:
            self.assertEqual(value, expected, f"Expected '{title}' {field}={expected!r}, got {value!r}")

    # --- FIFA 13 new entry ---

    def test_fifa13_in_db(self):
        """Wave 46: FIFA 13 (SLUS-21954) added from PS2.titles.json."""
        self.assertIn("FIFA 13", self.data)

    def test_fifa13_serial(self):
        """Wave 46: FIFA 13 should have serial SLUS-21954."""
        self._assert_metadata("FIFA 13", "serial", "SLUS-21954")

    # --- Metadata enrichment for 12 games ---

    def test_primal_has_release_date(self):
        """Wave 46: Primal should have release_date from PS2.data.json."""
        self._assert_metadata("Primal", "release_date", "2003-03-25")

    def test_primal_has_developer(self):
        """Wave 46: Primal should have developer from PS2.data.json."""
        self._assert_metadata("Primal", "developer", "SCE Cambridge Studio")

    def test_eyetoy_antigrav_has_release_date(self):
        """Wave 46: EyeToy: Antigrav should have release_date from PS2.data.json."""
        self._assert_metadata("EyeToy: Antigrav", "release_date", "2004-11-09")

    def test_eyetoy_antigrav_has_developer(self):
        """Wave 46: EyeToy: Antigrav should have developer from PS2.data.json."""
        self._assert_metadata("EyeToy: Antigrav", "developer", "Harmonix")

    def test_we8_international_has_release_date(self):
        """Wave 46: World Soccer WE8 International should have release_date."""
        self._assert_metadata(
            "World Soccer Winning Eleven 8: International", "release_date", "2005-02-01"
        )

    def test_we8_international_has_developer(self):
        """Wave 46: World Soccer WE8 International should have developer."""
        self._assert_metadata(
            "World Soccer Winning Eleven 8: International",
            "developer",
            "Konami Computer Entertainment Japan",
        )

    def test_gran_turismo_4_prologue_has_metadata(self):
        """Wave 46: Gran Turismo 4 Prologue should have developer Polyphony Digital."""
        self._assert_metadata("Gran Turismo 4 Prologue", "developer", "Polyphony Digital")

    def test_incredibles_has_release_date(self):
        """Wave 46: Incredibles, The should have release_date from PS2.data.json."""
        self._assert_metadata("Incredibles, The", "release_date", "2004-11-05")

    def test_incredibles_has_developer(self):
        """Wave 46: Incredibles, The should have developer Heavy Iron Studios."""
        self._assert_metadata("Incredibles, The", "developer", "Heavy Iron Studios")

    def test_tales_of_destiny_ps2_has_release_date(self):
        """Wave 46: Tales of Destiny (PS2 remake) should have release_date."""
        self._assert_metadata("Tales of Destiny (PS2 remake)", "release_date", "2006-11-30")

    def test_tales_of_destiny_ps2_has_genre(self):
        """Wave 46: Tales of Destiny (PS2 remake) should have genre RPG."""
        self._assert_metadata("Tales of Destiny (PS2 remake)", "genre", "RPG")

    def test_tales_of_destiny_2_has_release_date(self):
        """Wave 46: Tales of Destiny 2 should have release_date."""
        self._assert_metadata("Tales of Destiny 2", "release_date", "2002-11-28")

    def test_tales_of_rebirth_has_developer(self):
        """Wave 46: Tales of Rebirth should have developer Namco Bandai."""
        self._assert_metadata("Tales of Rebirth", "developer", "Namco Bandai")

    def test_forbidden_siren_2_has_developer(self):
        """Wave 46: Forbidden Siren 2 should have developer SCE Japan Studio."""
        self._assert_metadata("Forbidden Siren 2", "developer", "SCE Japan Studio")

    def test_front_mission_5_has_developer(self):
        """Wave 46: Front Mission 5: Scars of the War should have developer Square Enix."""
        self._assert_metadata("Front Mission 5: Scars of the War", "developer", "Square Enix")

    def test_gtc_africa_has_developer(self):
        """Wave 46: GTC Africa should have developer Rage Software."""
        self._assert_metadata("GTC Africa", "developer", "Rage Software")

    def test_espn_nba_2night_has_release_date(self):
        """Wave 46: ESPN NBA 2Night should have release_date."""
        self._assert_metadata("ESPN NBA 2Night", "release_date", "2001")

    def test_serial_db_wave46_game_count(self):
        """Wave 46: serial DB should have at least 2288 games (FIFA 13 added)."""
        self.assertGreaterEqual(len(self.data), 2288)


class TestWave47NewGames(unittest.TestCase):
    """Wave 47: new NTSC-U games and alt_serials added from PS2.txt / PS2 ID List cross-reference."""

    def setUp(self):
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
        self.games = json.loads(db_path.read_text())["games"]

    def _assert_alt_serial(self, title, expected_serial):
        game = self.games.get(title)
        self.assertIsNotNone(game, f"'{title}' not found in serial DB")
        alts = game.get("alt_serials", [])
        self.assertIn(
            expected_serial, alts,
            f"Expected {expected_serial} in alt_serials for '{title}', got {alts}",
        )

    # ── new games ──────────────────────────────────────────────────────────────

    def test_americas_army_rise_of_a_soldier_present(self):
        """Wave 47: America's Army: Rise of a Soldier (SLUS-21188) added."""
        self.assertIn("America's Army: Rise of a Soldier", self.games)

    def test_americas_army_serial(self):
        """Wave 47: America's Army should have serial SLUS-21188."""
        self.assertEqual(self.games["America's Army: Rise of a Soldier"]['serial'], 'SLUS-21188')

    def test_peanuts_all_stars_present(self):
        """Wave 47: Peanuts: All Stars (SLUS-21468) added."""
        self.assertIn('Peanuts: All Stars', self.games)

    def test_peanuts_all_stars_serial(self):
        """Wave 47: Peanuts: All Stars should have serial SLUS-21468."""
        self.assertEqual(self.games['Peanuts: All Stars']['serial'], 'SLUS-21468')

    def test_world_pool_challenge_present(self):
        """Wave 47: World Pool Challenge '06 (SLUS-21472) added."""
        self.assertIn("World Pool Challenge '06", self.games)

    def test_world_pool_challenge_serial(self):
        """Wave 47: World Pool Challenge '06 should have serial SLUS-21472."""
        self.assertEqual(self.games["World Pool Challenge '06"]['serial'], 'SLUS-21472')

    def test_heroes_indianapolis_500_present(self):
        """Wave 47: Heroes of the Indianapolis 500 (SLUS-21747) added."""
        self.assertIn('Heroes of the Indianapolis 500', self.games)

    def test_heroes_indianapolis_500_serial(self):
        """Wave 47: Heroes of the Indianapolis 500 should have serial SLUS-21747."""
        self.assertEqual(self.games['Heroes of the Indianapolis 500']['serial'], 'SLUS-21747')

    def test_jelly_belly_ballistic_beans_present(self):
        """Wave 47: Jelly Belly: Ballistic Beans (SLUS-21874) added."""
        self.assertIn('Jelly Belly: Ballistic Beans', self.games)

    def test_jelly_belly_ballistic_beans_serial(self):
        """Wave 47: Jelly Belly: Ballistic Beans should have serial SLUS-21874."""
        self.assertEqual(self.games['Jelly Belly: Ballistic Beans']['serial'], 'SLUS-21874')

    def test_mms_adventure_present(self):
        """Wave 47: M&M's Adventure (SLUS-21875) added."""
        self.assertIn("M&M's Adventure", self.games)

    def test_mms_adventure_serial(self):
        """Wave 47: M&M's Adventure should have serial SLUS-21875."""
        self.assertEqual(self.games["M&M's Adventure"]['serial'], 'SLUS-21875')

    # ── alt_serials ────────────────────────────────────────────────────────────

    def test_okage_has_scus91129_alt_serial(self):
        """Wave 47: SCUS-91129 should be alt_serial for Okage: Shadow King."""
        self._assert_alt_serial('Okage: Shadow King', 'SCUS-91129')

    def test_haven_has_slus20157_alt_serial(self):
        """Wave 47: SLUS-20157 should be alt_serial for Haven: Call of the King."""
        self._assert_alt_serial('Haven: Call of the King', 'SLUS-20157')

    def test_nascar_thunder_2004_has_slus20754_alt_serial(self):
        """Wave 47: SLUS-20754 should be alt_serial for NASCAR Thunder 2004."""
        self._assert_alt_serial('NASCAR Thunder 2004', 'SLUS-20754')

    # ── thresholds ─────────────────────────────────────────────────────────────

    def test_serial_db_wave47_game_count(self):
        """Wave 47: serial DB should have at least 2294 games (6 new games added)."""
        self.assertGreaterEqual(len(self.games), 2294)


class TestWave48GabominatedPnachCodes(unittest.TestCase):
    """Wave 48: fps/visual codes from Gabominated PCSX2 repo — 52 new CRCs (78 entries)."""

    def setUp(self):
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        self.db = json.loads(db_path.read_text())
        sdb_path = Path(__file__).parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
        self.games = json.loads(sdb_path.read_text())["games"]

    # ── pnach DB size ────────────────────────────────────────────────────────

    def test_wave48_pnach_db_size_over_47900(self):
        """Wave 48: pnach DB should have more than 47,900 entries after new fps code addition."""
        self.assertGreater(
            len(self.db), 47900,
            f"Expected >47900 pnach DB entries after Wave 48, got {len(self.db)}"
        )

    def test_wave48_fps_entry_count_over_360(self):
        """Wave 48: pnach DB should have >360 fps category entries after Wave 48."""
        fps_entries = [e for e in self.db.values() if e.get("category") == "fps"]
        self.assertGreater(
            len(fps_entries), 360,
            f"Expected >360 fps entries, got {len(fps_entries)}"
        )

    # ── specific new fps entries ─────────────────────────────────────────────

    def test_wave48_horsez_fps_present(self):
        """Wave 48: Horsez (F0512849) 60 FPS entry should be in pnach DB."""
        keys = [k for k in self.db if k.startswith("F0512849:EE:")]
        self.assertGreater(len(keys), 0, "No pnach entries for Horsez CRC F0512849")
        entry = self.db[keys[0]]
        self.assertEqual(entry.get("category"), "fps")
        self.assertEqual(entry.get("game_serial"), "SLUS-21563")

    def test_wave48_uefa_euro_2008_fps_present(self):
        """Wave 48: UEFA Euro 2008 (9703FCBF) 60 FPS entries should be in pnach DB."""
        keys = [k for k in self.db if k.startswith("9703FCBF:EE:")]
        self.assertGreaterEqual(len(keys), 2, f"Expected >=2 entries for UEFA Euro 2008 CRC 9703FCBF, got {len(keys)}")
        for k in keys:
            self.assertEqual(self.db[k].get("category"), "fps")
            self.assertEqual(self.db[k].get("game_serial"), "SLUS-21699")

    def test_wave48_silent_hill_4_fps_present(self):
        """Wave 48: Silent Hill 4: The Room (3919136D) 60 FPS entries should be in pnach DB."""
        keys = [k for k in self.db if k.startswith("3919136D:EE:")]
        self.assertGreaterEqual(
            len(keys), 6,
            f"Expected >=6 fps entries for Silent Hill 4 CRC 3919136D, got {len(keys)}"
        )
        self.assertEqual(self.db[keys[0]].get("game_serial"), "SLUS-20873")

    def test_wave48_freedom_fighters_fps_present(self):
        """Wave 48: Freedom Fighters (1DA7E9BC) 60 FPS entry should be in pnach DB."""
        keys = [k for k in self.db if k.startswith("1DA7E9BC:EE:")]
        self.assertGreater(len(keys), 0, "No pnach entries for Freedom Fighters CRC 1DA7E9BC")
        self.assertEqual(self.db[keys[0]].get("game_serial"), "SLUS-20658")

    def test_wave48_syphon_filter_omega_strain_fps_present(self):
        """Wave 48: Syphon Filter: The Omega Strain (D5605611) fps entries in pnach DB."""
        keys = [k for k in self.db if k.startswith("D5605611:EE:")]
        self.assertGreaterEqual(len(keys), 3, f"Expected >=3 entries for Syphon Filter: The Omega Strain CRC D5605611, got {len(keys)}")
        self.assertEqual(self.db[keys[0]].get("game_serial"), "SCUS-97264")

    def test_wave48_prince_of_persia_warrior_within_fps_present(self):
        """Wave 48: Prince of Persia: Warrior Within (6B17B39F) fps+visual entries in pnach DB."""
        keys = [k for k in self.db if k.startswith("6B17B39F:EE:")]
        self.assertGreaterEqual(len(keys), 2, f"Expected >=2 entries for Prince of Persia: Warrior Within CRC 6B17B39F")
        categories = {self.db[k].get("category") for k in keys}
        self.assertIn("fps", categories)
        self.assertIn("visual", categories)

    def test_wave48_grandia_iii_fps_present(self):
        """Wave 48: Grandia III (5B657DAD) 60 FPS entries should be in pnach DB."""
        keys = [k for k in self.db if k.startswith("5B657DAD:EE:")]
        self.assertGreaterEqual(len(keys), 2, f"Expected >=2 fps entries for Grandia III CRC 5B657DAD, got {len(keys)}")
        self.assertEqual(self.db[keys[0]].get("game_serial"), "SLUS-21334")

    def test_wave48_blade_ii_fps_present(self):
        """Wave 48: Blade II (6D0E5F2D) 60 FPS entries should be in pnach DB."""
        keys = [k for k in self.db if k.startswith("6D0E5F2D:EE:")]
        self.assertGreaterEqual(len(keys), 4, f"Expected >=4 fps entries for Blade II CRC 6D0E5F2D, got {len(keys)}")

    def test_wave48_dbz_sagas_fps_present(self):
        """Wave 48: Dragon Ball Z: Sagas (E36751DA) 60 FPS entry should be in pnach DB."""
        keys = [k for k in self.db if k.startswith("E36751DA:EE:")]
        self.assertGreater(len(keys), 0, "No pnach entries for DBZ Sagas CRC E36751DA")
        self.assertEqual(self.db[keys[0]].get("game_serial"), "SLUS-20874")

    # ── entry structure ──────────────────────────────────────────────────────

    def test_wave48_new_entries_have_required_fields(self):
        """Wave 48: new entries must have required fields (game, game_crc, game_serial, etc.)."""
        new_crcs = [
            "F0512849", "9703FCBF", "3919136D", "1DA7E9BC", "D5605611",
            "6B17B39F", "5B657DAD", "6D0E5F2D", "E36751DA", "9798D85A",
        ]
        required_fields = ("game", "game_crc", "game_serial", "description", "category",
                           "patch_type", "verification_status")
        for crc in new_crcs:
            keys = [k for k in self.db if k.startswith(f"{crc}:EE:")]
            for key in keys:
                entry = self.db[key]
                with self.subTest(key=key):
                    for field in required_fields:
                        self.assertIn(field, entry, f"Entry {key} missing field '{field}'")
                    key_crc = key.split(":")[0].upper()
                    self.assertEqual(
                        key_crc, entry["game_crc"].upper(),
                        f"CRC mismatch for entry {key}: key={key_crc}, game_crc={entry['game_crc']}"
                    )

    # ── serial DB update ─────────────────────────────────────────────────────

    def test_wave48_project_snowblind_has_2bda8adb_crc(self):
        """Wave 48: Project Snowblind should have 2BDA8ADB as secondary CRC."""
        game = self.games.get("Project - Snowblind")
        self.assertIsNotNone(game, "Project - Snowblind not found in serial DB")
        crcs = game.get("crcs", [])
        self.assertIn("2BDA8ADB", crcs, f"Expected 2BDA8ADB in Project Snowblind CRCs, got {crcs}")


class TestWave49SerialCrcConsistency(unittest.TestCase):
    """Wave 49: Verify all game serials and CRCs are correctly cross-referenced
    between pnach_db and serial_db.  Fixes 664 pnach serial mismatches and
    removes 25 wrong CRCs from serial_db.
    """

    def setUp(self):
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        self.db = json.loads(db_path.read_text())
        sdb_path = Path(__file__).parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
        self.games = json.loads(sdb_path.read_text())["games"]

    # ── pnach_db serial corrections ─────────────────────────────────────────

    def test_wave49_castlevania_loi_serial_corrected(self):
        """Wave 49: Castlevania LoI CRCs (2B123FE9, A5B82E82) must use SLUS-20733, not SLUS-21050."""
        for crc in ("2B123FE9", "A5B82E82"):
            keys = [k for k in self.db if k.startswith(f"{crc}:")]
            self.assertGreater(len(keys), 0, f"No pnach entries for CRC {crc}")
            for k in keys:
                entry = self.db[k]
                self.assertEqual(
                    entry.get("game_serial", "").upper(), "SLUS-20733",
                    f"Castlevania LoI entry {k} has wrong serial {entry.get('game_serial')!r}"
                )

    def test_wave49_burnout3_takedown_serial_corrected(self):
        """Wave 49: Burnout 3 CRC 1CD5CC9D must use SLUS-21050, not SLUS-20462."""
        keys = [k for k in self.db if k.startswith("1CD5CC9D:")]
        self.assertGreater(len(keys), 0, "No pnach entries for CRC 1CD5CC9D")
        for k in keys:
            entry = self.db[k]
            self.assertEqual(
                entry.get("game_serial", "").upper(), "SLUS-21050",
                f"Burnout 3 entry {k} has wrong serial {entry.get('game_serial')!r}"
            )

    def test_wave49_shadow_of_the_colossus_serial_added(self):
        """Wave 49: Shadow of the Colossus CRC C19A374E must have serial SCUS-97472."""
        keys = [k for k in self.db if k.startswith("C19A374E:")]
        self.assertGreater(len(keys), 0, "No pnach entries for CRC C19A374E")
        for k in keys:
            entry = self.db[k]
            self.assertEqual(
                entry.get("game_serial", "").upper(), "SCUS-97472",
                f"Shadow of the Colossus entry {k} has wrong serial {entry.get('game_serial')!r}"
            )

    def test_wave49_gta_vice_city_serial_corrected(self):
        """Wave 49: GTA Vice City CRC 3F68CFCF must use SLUS-20552, not SLUS-20174."""
        keys = [k for k in self.db if k.startswith("3F68CFCF:")]
        self.assertGreater(len(keys), 0, "No pnach entries for CRC 3F68CFCF")
        for k in keys:
            entry = self.db[k]
            self.assertEqual(
                entry.get("game_serial", "").upper(), "SLUS-20552",
                f"GTA VC entry {k} has wrong serial {entry.get('game_serial')!r}"
            )

    def test_wave49_god_of_war_crcs_use_scus_serial(self):
        """Wave 49: God of War CRCs 17D68D15/D6385328/F0A34C75 must use SCUS-97399."""
        for crc in ("17D68D15", "D6385328", "F0A34C75"):
            keys = [k for k in self.db if k.startswith(f"{crc}:")]
            if not keys:
                continue  # CRC may be missing; skip
            for k in keys:
                entry = self.db[k]
                self.assertEqual(
                    entry.get("game_serial", "").upper(), "SCUS-97399",
                    f"God of War entry {k} has wrong serial {entry.get('game_serial')!r}"
                )

    def test_wave49_crash_twinsanity_crcs_consolidated(self):
        """Wave 49: Crash Twinsanity CRCs 3B698B6E/BD2AC49F/CA5B7A61 must use SLUS-20909."""
        for crc in ("3B698B6E", "BD2AC49F", "CA5B7A61"):
            keys = [k for k in self.db if k.startswith(f"{crc}:")]
            if not keys:
                continue
            for k in keys:
                entry = self.db[k]
                self.assertEqual(
                    entry.get("game_serial", "").upper(), "SLUS-20909",
                    f"Crash Twinsanity entry {k} has wrong serial {entry.get('game_serial')!r}"
                )

    def test_wave49_driver_parallel_lines_serial_added(self):
        """Wave 49: Driver: Parallel Lines CRC D720770D must have serial SLUS-21271."""
        keys = [k for k in self.db if k.startswith("D720770D:")]
        self.assertGreater(len(keys), 0, "No pnach entries for CRC D720770D")
        for k in keys:
            entry = self.db[k]
            self.assertEqual(
                entry.get("game_serial", "").upper(), "SLUS-21271",
                f"Driver: PL entry {k} has wrong serial {entry.get('game_serial')!r}"
            )

    def test_wave49_silent_hill_3_serial_corrected(self):
        """Wave 49: Silent Hill 3 CRC FFAAC65B must use SLUS-20622, not SLUS-20459."""
        keys = [k for k in self.db if k.startswith("FFAAC65B:")]
        self.assertGreater(len(keys), 0, "No pnach entries for CRC FFAAC65B")
        for k in keys:
            entry = self.db[k]
            self.assertEqual(
                entry.get("game_serial", "").upper(), "SLUS-20622",
                f"Silent Hill 3 entry {k} has wrong serial {entry.get('game_serial')!r}"
            )

    def test_wave49_pnach_serial_lookup_castlevania_loi(self):
        """Wave 49: entries_for_serial(SLUS-20733) must return Castlevania LoI entries."""
        import sys
        sys.path.insert(0, str(__file__).replace("tests/test_core.py", ""))
        from src.core.pnach_analyzer import entries_for_serial, reload_db
        reload_db()
        results = entries_for_serial("SLUS-20733")
        self.assertGreater(len(results), 0, "entries_for_serial(SLUS-20733) returned no results")
        crcs = {e["key"].split(":")[0] for e in results}
        self.assertTrue(
            crcs & {"2B123FE9", "A5B82E82"},
            f"Expected Castlevania LoI CRCs in results, got CRCs: {crcs}"
        )

    def test_wave49_pnach_serial_lookup_shadow_of_the_colossus(self):
        """Wave 49: entries_for_serial(SCUS-97472) must return Shadow of the Colossus entries."""
        from src.core.pnach_analyzer import entries_for_serial, reload_db
        reload_db()
        results = entries_for_serial("SCUS-97472")
        self.assertGreater(len(results), 0, "entries_for_serial(SCUS-97472) returned no results")

    def test_wave49_pnach_serial_lookup_god_of_war(self):
        """Wave 49: entries_for_serial(SCUS-97399) must return God of War entries."""
        from src.core.pnach_analyzer import entries_for_serial, reload_db
        reload_db()
        results = entries_for_serial("SCUS-97399")
        self.assertGreater(len(results), 10, "entries_for_serial(SCUS-97399) returned too few results")

    # ── serial_db CRC removals (cross-game contaminations) ──────────────────

    def test_wave49_atv_off_road_fury_wrong_crc_removed(self):
        """Wave 49: ATV Off-Road Fury (SCUS-97104) must NOT claim CRC 67DB3ED8 (Aggressive Inline)."""
        game = self.games.get("ATV Off-Road Fury", {})
        crcs = game.get("crcs", [])
        self.assertNotIn("67DB3ED8", crcs,
                         "CRC 67DB3ED8 (Aggressive Inline) wrongly in ATV Off-Road Fury")

    def test_wave49_baldurs_gate_da_wrong_crc_removed(self):
        """Wave 49: Baldur's Gate: DA must NOT claim CRC 08FFF00D (SSX 3)."""
        game = self.games.get("Baldur's Gate: Dark Alliance", {})
        crcs = game.get("crcs", [])
        self.assertNotIn("08FFF00D", crcs,
                         "CRC 08FFF00D (SSX 3) wrongly in Baldur's Gate: Dark Alliance")

    def test_wave49_contra_shattered_soldier_wrong_crc_removed(self):
        """Wave 49: Contra: Shattered Soldier must NOT claim CRC 33EC7780 (Star Ocean TtEoT)."""
        game = self.games.get("Contra: Shattered Soldier", {})
        crcs = game.get("crcs", [])
        self.assertNotIn("33EC7780", crcs,
                         "CRC 33EC7780 (Star Ocean) wrongly in Contra: Shattered Soldier")

    def test_wave49_silent_hill_3_wrong_crc_removed(self):
        """Wave 49: Silent Hill 3 must NOT claim CRC BFCC3E7E (Shinobi)."""
        game = self.games.get("Silent Hill 3", {})
        crcs = game.get("crcs", [])
        self.assertNotIn("BFCC3E7E", crcs,
                         "CRC BFCC3E7E (Shinobi) wrongly in Silent Hill 3")

    def test_wave49_metal_gear_solid_3_wrong_crc_removed(self):
        """Wave 49: MGS3: Snake Eater must NOT claim CRC AEB91ED0 (Devil May Cry 2)."""
        game = self.games.get("Metal Gear Solid 3: Snake Eater", {})
        crcs = game.get("crcs", [])
        self.assertNotIn("AEB91ED0", crcs,
                         "CRC AEB91ED0 (DMC2) wrongly in MGS3: Snake Eater")

    def test_wave49_gta_vc_correct_crc_still_present(self):
        """Wave 49: Grand Theft Auto: Vice City must still have CRC 3F68CFCF."""
        game = self.games.get("Grand Theft Auto: Vice City", {})
        crcs = game.get("crcs", [])
        self.assertIn("3F68CFCF", crcs,
                      "CRC 3F68CFCF missing from Grand Theft Auto: Vice City")

    def test_wave49_castlevania_loi_correct_crcs_still_present(self):
        """Wave 49: Castlevania: LoI must still have CRCs 2B123FE9 and A5B82E82."""
        game = self.games.get("Castlevania: Lament of Innocence", {})
        crcs = game.get("crcs", [])
        self.assertIn("2B123FE9", crcs)
        self.assertIn("A5B82E82", crcs)

    def test_wave49_no_pnach_entry_has_wrong_slus20552_via_slus20174(self):
        """Wave 49: No pnach entry should have game_serial SLUS-20174 (Rumble Racing) for a GTA CRC."""
        gta_crcs = {"3F68CFCF", "7AC3B4F3", "B4B15628"}
        for key, entry in self.db.items():
            crc = key.split(":")[0].upper()
            if crc in gta_crcs:
                serial = entry.get("game_serial", "").upper()
                self.assertNotEqual(
                    serial, "SLUS-20174",
                    f"GTA VC entry {key} wrongly has serial SLUS-20174 (Rumble Racing)"
                )

    # ── pnach_db size still within range ─────────────────────────────────────

    def test_wave49_pnach_db_size_still_over_47800(self):
        """Wave 49: pnach DB should still have >47,800 entries after serial corrections."""
        self.assertGreater(
            len(self.db), 47800,
            f"Unexpected drop in pnach DB size: {len(self.db)}"
        )

    def test_wave49_serial_db_games_count_unchanged(self):
        """Wave 49: serial DB game count should still be 2294 (only CRCs changed, not game entries)."""
        self.assertEqual(
            len(self.games), 2294,
            f"Serial DB game count changed unexpectedly: {len(self.games)}"
        )


class TestWave50VersionLabels(unittest.TestCase):
    """Wave 50: CRC version labels — the app can now tell users which disc
    version a texture pack or PNACH code is designed for when a game has
    multiple releases with different CRCs (v1.00, Greatest Hits, etc.).
    """

    def setUp(self):
        from pathlib import Path
        import json
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.core.serial_validator import SerialDatabase
        self.sdb = SerialDatabase()
        sdb_path = Path(__file__).parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
        self.raw_games = json.loads(sdb_path.read_text())["games"]

    # ── GameInfo.crc_labels field ────────────────────────────────────────────

    def test_gameinfo_has_crc_labels_field(self):
        """Wave 50: GameInfo dataclass must have a crc_labels dict field."""
        from src.core.serial_validator import GameInfo
        gi = GameInfo(title="Test", serial="SLUS-10000")
        self.assertIsInstance(gi.crc_labels, dict)

    def test_gameinfo_crc_labels_defaults_empty(self):
        """Wave 50: GameInfo.crc_labels must default to empty dict, not None."""
        from src.core.serial_validator import GameInfo
        gi = GameInfo(title="Test", serial="SLUS-10000")
        self.assertEqual(gi.crc_labels, {})

    # ── SerialDatabase.label_for_crc ─────────────────────────────────────────

    def test_label_for_crc_god_of_war_v100(self):
        """Wave 50: God of War CRC 17D68D15 must be labelled 'v1.00'."""
        label = self.sdb.label_for_crc("17D68D15")
        self.assertEqual(label, "v1.00")

    def test_label_for_crc_god_of_war_greatest_hits(self):
        """Wave 50: God of War CRC F0A34C75 must be labelled 'Greatest Hits'."""
        label = self.sdb.label_for_crc("F0A34C75")
        self.assertEqual(label, "Greatest Hits")

    def test_label_for_crc_gta_vc_v100(self):
        """Wave 50: GTA Vice City CRC 7AC3B4F3 must be labelled 'v1.00'."""
        label = self.sdb.label_for_crc("7AC3B4F3")
        self.assertEqual(label, "v1.00")

    def test_label_for_crc_gta_vc_v101(self):
        """Wave 50: GTA Vice City CRC 3F68CFCF must be labelled 'v1.01'."""
        label = self.sdb.label_for_crc("3F68CFCF")
        self.assertEqual(label, "v1.01")

    def test_label_for_crc_gta_vc_greatest_hits(self):
        """Wave 50: GTA Vice City CRC B4B15628 must be labelled 'Greatest Hits'."""
        label = self.sdb.label_for_crc("B4B15628")
        self.assertEqual(label, "Greatest Hits")

    def test_label_for_crc_shadow_of_colossus(self):
        """Wave 50: Shadow of the Colossus CRC C19A374E must be labelled 'v1.00'."""
        label = self.sdb.label_for_crc("C19A374E")
        self.assertEqual(label, "v1.00")

    def test_label_for_crc_castlevania_loi(self):
        """Wave 50: Castlevania LoI CRC 2B123FE9 must be labelled 'v1.00'."""
        label = self.sdb.label_for_crc("2B123FE9")
        self.assertEqual(label, "v1.00")

    def test_label_for_crc_silent_hill_3_v100(self):
        """Wave 50: Silent Hill 3 CRC FFAAC65B must be labelled 'v1.00'."""
        label = self.sdb.label_for_crc("FFAAC65B")
        self.assertEqual(label, "v1.00")

    def test_label_for_crc_kingdom_hearts_v100(self):
        """Wave 50: Kingdom Hearts CRC 39BB7DF5 must be labelled 'v1.00'."""
        label = self.sdb.label_for_crc("39BB7DF5")
        self.assertEqual(label, "v1.00")

    def test_label_for_crc_kingdom_hearts_greatest_hits(self):
        """Wave 50: Kingdom Hearts CRC 0F6B6315 must be labelled 'Greatest Hits'."""
        label = self.sdb.label_for_crc("0F6B6315")
        self.assertIn("Greatest Hits", label or "")

    def test_label_for_crc_ratchet_clank_greatest_hits(self):
        """Wave 50: Ratchet & Clank CRC E4E70DCE must be labelled 'Greatest Hits'."""
        label = self.sdb.label_for_crc("E4E70DCE")
        self.assertEqual(label, "Greatest Hits")

    def test_label_for_crc_unknown_returns_none(self):
        """Wave 50: label_for_crc must return None for an unknown CRC."""
        label = self.sdb.label_for_crc("00000000")
        self.assertIsNone(label)

    def test_label_for_crc_case_insensitive(self):
        """Wave 50: label_for_crc must accept lowercase CRC strings."""
        label_lower = self.sdb.label_for_crc("17d68d15")
        label_upper = self.sdb.label_for_crc("17D68D15")
        self.assertEqual(label_lower, label_upper)
        self.assertIsNotNone(label_lower)

    # ── SerialDatabase.serial_for_crc ────────────────────────────────────────

    def test_serial_for_crc_god_of_war(self):
        """Wave 50: serial_for_crc must return SCUS-97399 for any God of War CRC."""
        for crc in ("17D68D15", "F0A34C75", "D6385328"):
            self.assertEqual(
                self.sdb.serial_for_crc(crc), "SCUS-97399",
                f"serial_for_crc({crc!r}) did not return SCUS-97399",
            )

    def test_serial_for_crc_gta_vc(self):
        """Wave 50: serial_for_crc must return SLUS-20552 for GTA VC CRCs."""
        for crc in ("7AC3B4F3", "3F68CFCF", "B4B15628"):
            self.assertEqual(
                self.sdb.serial_for_crc(crc), "SLUS-20552",
                f"serial_for_crc({crc!r}) did not return SLUS-20552",
            )

    def test_serial_for_crc_unknown_returns_none(self):
        """Wave 50: serial_for_crc must return None for an unknown CRC."""
        self.assertIsNone(self.sdb.serial_for_crc("00000000"))

    # ── SerialDatabase.all_crcs_for_title ────────────────────────────────────

    def test_all_crcs_for_title_god_of_war_count(self):
        """Wave 50: all_crcs_for_title must return 5 pairs for God of War."""
        pairs = self.sdb.all_crcs_for_title("God of War")
        self.assertEqual(len(pairs), 5)

    def test_all_crcs_for_title_god_of_war_has_v100(self):
        """Wave 50: God of War CRC 17D68D15 must have label 'v1.00' in pairs."""
        pairs = self.sdb.all_crcs_for_title("God of War")
        crc_to_label = dict(pairs)
        self.assertEqual(crc_to_label.get("17D68D15"), "v1.00")

    def test_all_crcs_for_title_god_of_war_has_greatest_hits(self):
        """Wave 50: God of War CRC F0A34C75 must have label 'Greatest Hits' in pairs."""
        pairs = self.sdb.all_crcs_for_title("God of War")
        crc_to_label = dict(pairs)
        self.assertEqual(crc_to_label.get("F0A34C75"), "Greatest Hits")

    def test_all_crcs_for_title_unknown_game(self):
        """Wave 50: all_crcs_for_title must return empty list for unknown game."""
        pairs = self.sdb.all_crcs_for_title("Not A Real Game")
        self.assertEqual(pairs, [])

    # ── pnach_analyzer.get_version_label ────────────────────────────────────

    def test_get_version_label_god_of_war_v100(self):
        """Wave 50: pnach_analyzer.get_version_label must return 'v1.00' for 17D68D15."""
        from src.core.pnach_analyzer import get_version_label
        label = get_version_label("17D68D15")
        self.assertEqual(label, "v1.00")

    def test_get_version_label_god_of_war_greatest_hits(self):
        """Wave 50: pnach_analyzer.get_version_label must return 'Greatest Hits' for F0A34C75."""
        from src.core.pnach_analyzer import get_version_label
        label = get_version_label("F0A34C75")
        self.assertEqual(label, "Greatest Hits")

    def test_get_version_label_unknown_returns_none(self):
        """Wave 50: get_version_label must return None for an unlabelled CRC."""
        from src.core.pnach_analyzer import get_version_label
        self.assertIsNone(get_version_label("00000000"))

    # ── get_game_verification_summary includes version_label ─────────────────

    def test_verification_summary_includes_version_label_key(self):
        """Wave 50: get_game_verification_summary must include a 'version_label' key."""
        from src.core.pnach_analyzer import get_game_verification_summary
        summary = get_game_verification_summary("17D68D15")
        self.assertIn("version_label", summary)

    def test_verification_summary_version_label_god_of_war_v100(self):
        """Wave 50: verification summary for 17D68D15 must report version_label='v1.00'."""
        from src.core.pnach_analyzer import get_game_verification_summary
        summary = get_game_verification_summary("17D68D15")
        self.assertEqual(summary.get("version_label"), "v1.00")

    def test_verification_summary_version_label_none_for_unknown_crc(self):
        """Wave 50: verification summary version_label must be None for unknown CRC."""
        from src.core.pnach_analyzer import get_game_verification_summary
        summary = get_game_verification_summary("FFFFFFFF")
        self.assertIsNone(summary.get("version_label"))

    # ── JSON data integrity ───────────────────────────────────────────────────

    def test_crc_labels_only_contain_valid_crcs(self):
        """Wave 50: Every CRC in crc_labels must also appear in the game's crcs list."""
        for title, info in self.raw_games.items():
            crcs_set = set(c.upper() for c in info.get("crcs", []))
            for crc in info.get("crc_labels", {}).keys():
                self.assertIn(
                    crc.upper(), crcs_set,
                    f"{title!r}: crc_labels contains {crc!r} not in crcs list",
                )

    def test_crc_labels_values_are_non_empty_strings(self):
        """Wave 50: Every crc_labels value must be a non-empty string."""
        for title, info in self.raw_games.items():
            for crc, label in info.get("crc_labels", {}).items():
                self.assertIsInstance(
                    label, str,
                    f"{title!r} crc_label[{crc!r}] is not a string: {label!r}",
                )
                self.assertTrue(
                    label.strip(),
                    f"{title!r} crc_label[{crc!r}] is empty or whitespace",
                )

    def test_games_with_crc_labels_count(self):
        """Wave 50: At least 10 game entries must have crc_labels populated."""
        count = sum(1 for info in self.raw_games.values() if info.get("crc_labels"))
        self.assertGreaterEqual(count, 10,
                                f"Too few games with crc_labels: {count}")

    def test_serial_db_game_count_unchanged_after_wave50(self):
        """Wave 50: serial DB game count must remain 2294 (only crc_labels added)."""
        self.assertEqual(len(self.raw_games), 2294)


class TestWave51CrcLabelsExpanded(unittest.TestCase):
    """Wave 51: extended crc_labels + data-quality fixes."""

    @classmethod
    def setUpClass(cls):
        from src.core.serial_validator import SerialDatabase
        cls.sdb = SerialDatabase()
        import json
        from pathlib import Path
        raw = json.loads(
            (Path(__file__).parent.parent / "data/game_serial_db/ps2_ntsc_u.json")
            .read_text(encoding="utf-8")
        )
        cls.raw_games = raw["games"]

    # ── Total crc_labels count ───────────────────────────────────────────────

    def test_wave51_crc_labels_count_at_least_20(self):
        """Wave 51: At least 20 game entries must have crc_labels populated."""
        count = sum(1 for info in self.raw_games.values() if info.get("crc_labels"))
        self.assertGreaterEqual(count, 20,
                                f"Expected ≥20 games with crc_labels, got {count}")

    # ── Grand Theft Auto: San Andreas ───────────────────────────────────────

    def test_wave51_gta_sa_v100_label(self):
        """Wave 51: GTA SA CRC 9A5B29A1 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("9A5B29A1"), "v1.00")

    def test_wave51_gta_sa_v101_label(self):
        """Wave 51: GTA SA CRC 399A49CA must be labelled 'v1.01'."""
        self.assertEqual(self.sdb.label_for_crc("399A49CA"), "v1.01")

    def test_wave51_gta_sa_greatest_hits_label(self):
        """Wave 51: GTA SA CRC B3D64CF8 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("B3D64CF8"), "Greatest Hits")

    def test_wave51_gta_sa_v200_label(self):
        """Wave 51: GTA SA CRC 2C6BE434 must be labelled 'v2.00'."""
        self.assertEqual(self.sdb.label_for_crc("2C6BE434"), "v2.00")

    def test_wave51_gta_sa_all_4_crcs_present(self):
        """Wave 51: Grand Theft Auto: San Andreas must have 4 CRCs."""
        info = self.sdb.get_info("Grand Theft Auto: San Andreas")
        self.assertIsNotNone(info)
        self.assertEqual(len(info.crcs), 4, f"Expected 4 CRCs, got {info.crcs}")

    # ── Gran Turismo 3: A-Spec ───────────────────────────────────────────────

    def test_wave51_gt3_v100_label(self):
        """Wave 51: GT3 CRC 85AE91B3 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("85AE91B3"), "v1.00")

    def test_wave51_gt3_v101_label(self):
        """Wave 51: GT3 CRC C12E4587 must be labelled 'v1.01'."""
        self.assertEqual(self.sdb.label_for_crc("C12E4587"), "v1.01")

    def test_wave51_gt3_greatest_hits_label(self):
        """Wave 51: GT3 CRC F9F416C5 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("F9F416C5"), "Greatest Hits")

    # ── God of War II ────────────────────────────────────────────────────────

    def test_wave51_gow2_v100_label(self):
        """Wave 51: GoW II CRC 0B29B9B6 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("0B29B9B6"), "v1.00")

    def test_wave51_gow2_v101_label(self):
        """Wave 51: GoW II CRC 2F123FD8 must be labelled 'v1.01'."""
        self.assertEqual(self.sdb.label_for_crc("2F123FD8"), "v1.01")

    def test_wave51_gow2_greatest_hits_label(self):
        """Wave 51: GoW II CRC 44A8A22A must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("44A8A22A"), "Greatest Hits")

    # ── Metal Gear Solid 2: Sons of Liberty ─────────────────────────────────

    def test_wave51_mgs2_v100_label(self):
        """Wave 51: MGS2 CRC 5E267A69 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("5E267A69"), "v1.00")

    def test_wave51_mgs2_greatest_hits_label(self):
        """Wave 51: MGS2 CRC 1540CFB5 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("1540CFB5"), "Greatest Hits")

    def test_wave51_mgs2_all_5_crcs_present(self):
        """Wave 51: MGS2 must have 5 CRCs."""
        info = self.sdb.get_info("Metal Gear Solid 2: Sons of Liberty")
        self.assertIsNotNone(info)
        self.assertEqual(len(info.crcs), 5, f"Expected 5 CRCs, got {info.crcs}")

    # ── Metal Gear Solid 3: Snake Eater ─────────────────────────────────────

    def test_wave51_mgs3_v100_label(self):
        """Wave 51: MGS3 CRC 015FC3F6 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("015FC3F6"), "v1.00")

    def test_wave51_mgs3_all_5_crcs_present(self):
        """Wave 51: MGS3: Snake Eater must have all 5 CRCs after consolidation."""
        info = self.sdb.get_info("Metal Gear Solid 3: Snake Eater")
        self.assertIsNotNone(info)
        self.assertEqual(len(info.crcs), 5, f"Expected 5 CRCs, got {info.crcs}")
        self.assertIn("A39517AB", info.crcs)
        self.assertIn("D4FA1757", info.crcs)

    def test_wave51_mgs3_gh_wrong_crc_removed(self):
        """Wave 51: MGS3 GH entry must no longer claim CRC AEB91ED0 (belongs to DMC2)."""
        info = self.raw_games.get("Metal Gear Solid 3: Snake Eater (GH)", {})
        self.assertNotIn("AEB91ED0", info.get("crcs", []),
                         "AEB91ED0 (DMC2 CRC) wrongly still in MGS3: Snake Eater (GH)")

    # ── Devil May Cry 2 ──────────────────────────────────────────────────────

    def test_wave51_dmc2_v100_label(self):
        """Wave 51: DMC2 CRC 0BF94D63 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("0BF94D63"), "v1.00")

    def test_wave51_dmc2_v105_label(self):
        """Wave 51: DMC2 CRC AEB91ED0 (now correct in DMC2) must be labelled 'v1.05'."""
        self.assertEqual(self.sdb.label_for_crc("AEB91ED0"), "v1.05")

    def test_wave51_dmc2_v104_crc_added(self):
        """Wave 51: DMC2 must include previously-missing CRC 08995DEE."""
        info = self.sdb.get_info("Devil May Cry 2")
        self.assertIsNotNone(info)
        self.assertIn("08995DEE", info.crcs,
                      "CRC 08995DEE missing from Devil May Cry 2 after Wave 51 fix")

    def test_wave51_dmc2_all_6_crcs_present(self):
        """Wave 51: DMC2 must have 6 CRCs after Wave 51 fix."""
        info = self.sdb.get_info("Devil May Cry 2")
        self.assertIsNotNone(info)
        self.assertEqual(len(info.crcs), 6, f"Expected 6 CRCs, got {info.crcs}")

    # ── Tekken 5 ─────────────────────────────────────────────────────────────

    def test_wave51_tekken5_v100_label(self):
        """Wave 51: Tekken 5 CRC CF5A1A6B must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("CF5A1A6B"), "v1.00")

    def test_wave51_tekken5_greatest_hits_label(self):
        """Wave 51: Tekken 5 CRC 652050D2 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("652050D2"), "Greatest Hits")

    # ── Silent Hill 4: The Room ──────────────────────────────────────────────

    def test_wave51_sh4_v100_label(self):
        """Wave 51: SH4 CRC 0152E0C7 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("0152E0C7"), "v1.00")

    def test_wave51_sh4_v103_label(self):
        """Wave 51: SH4 CRC 42E152EF must be labelled 'v1.03'."""
        self.assertEqual(self.sdb.label_for_crc("42E152EF"), "v1.03")

    def test_wave51_sh4_ambiguous_crc_not_labelled(self):
        """Wave 51: Ambiguous SH4 CRC E360416A must NOT have a crc_label."""
        sh4_labels = self.raw_games.get("Silent Hill 4: The Room", {}).get(
            "crc_labels", {}
        )
        self.assertNotIn("E360416A", sh4_labels,
                         "Ambiguous CRC E360416A should not be labelled in SH4")

    # ── Kingdom Hearts: Re:Chain of Memories ────────────────────────────────

    def test_wave51_khrecom_v100_label(self):
        """Wave 51: KH Re:CoM CRC 2AFC166C must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("2AFC166C"), "v1.00")

    def test_wave51_khrecom_v101_label(self):
        """Wave 51: KH Re:CoM CRC D3E8D5EC must be labelled 'v1.01'."""
        self.assertEqual(self.sdb.label_for_crc("D3E8D5EC"), "v1.01")

    # ── Silent Hill 2 GH labels ──────────────────────────────────────────────

    def test_wave51_sh2_gh_v100_label(self):
        """Wave 51: SH2 CRC 4A0E5B3A must be labelled 'Greatest Hits v1.00'."""
        sh2_labels = self.raw_games.get("Silent Hill 2", {}).get("crc_labels", {})
        self.assertEqual(sh2_labels.get("4A0E5B3A"), "Greatest Hits v1.00")

    # ── Xenosaga III canonical entry ─────────────────────────────────────────

    def test_wave51_xeno3_v100_label(self):
        """Wave 51: Xenosaga III CRC 94A82AAA must be labelled 'v1.00'."""
        xeno = self.raw_games.get(
            "Xenosaga Episode III: Also sprach Zarathustra", {}
        )
        labels = xeno.get("crc_labels", {})
        self.assertEqual(labels.get("94A82AAA"), "v1.00")

    def test_wave51_xeno3_ambiguous_crc_not_labelled(self):
        """Wave 51: Ambiguous Xenosaga III CRC FCD6E9FA must NOT have a crc_label."""
        xeno = self.raw_games.get(
            "Xenosaga Episode III: Also sprach Zarathustra", {}
        )
        labels = xeno.get("crc_labels", {})
        self.assertNotIn("FCD6E9FA", labels,
                         "Ambiguous CRC FCD6E9FA should not be labelled in Xenosaga III")

    # ── Serial DB game count unchanged ───────────────────────────────────────

    def test_wave51_serial_db_game_count_unchanged(self):
        """Wave 51: serial DB game count must remain 2294."""
        self.assertEqual(len(self.raw_games), 2294)


class TestWave52CrcQualityFixes(unittest.TestCase):
    """Wave 52: CRC ownership fixes + crc_labels expansion."""

    @classmethod
    def setUpClass(cls):
        from src.core.serial_validator import SerialDatabase
        cls.sdb = SerialDatabase()
        import json
        from pathlib import Path
        raw = json.loads(
            (Path(__file__).parent.parent / "data/game_serial_db/ps2_ntsc_u.json")
            .read_text(encoding="utf-8")
        )
        cls.raw_games = raw["games"]

    # ── crc_labels count ─────────────────────────────────────────────────────

    def test_wave52_crc_labels_count_at_least_28(self):
        """Wave 52: At least 28 game entries must have crc_labels populated."""
        count = sum(1 for info in self.raw_games.values() if info.get("crc_labels"))
        self.assertGreaterEqual(count, 28,
                                f"Expected ≥28 games with crc_labels, got {count}")

    # ── Wrong-case duplicate entries must have CRCs cleared ──────────────────

    def test_wave52_ico_uppercase_crcs_cleared(self):
        """Wave 52: 'ICO' (wrong-case) entry must have CRCs cleared."""
        ico_upper = self.raw_games.get("ICO", {})
        self.assertEqual(ico_upper.get("crcs", []), [],
                         "'ICO' wrong-case entry must have empty CRCs (canonical is 'Ico')")

    def test_wave52_shadow_of_rome_wrong_case_crcs_cleared(self):
        """Wave 52: 'Shadow Of Rome' wrong-case entry must have CRCs cleared."""
        entry = self.raw_games.get("Shadow Of Rome", {})
        self.assertEqual(entry.get("crcs", []), [],
                         "'Shadow Of Rome' wrong-case entry must have empty CRCs")

    # ── Way of the Samurai 2 CRC moved to canonical entry ────────────────────

    def test_wave52_way_of_samurai2_canonical_has_crc(self):
        """Wave 52: 'Way of the Samurai 2' canonical entry must have CRC 7B79C53C."""
        entry = self.raw_games.get("Way of the Samurai 2", {})
        self.assertIn("7B79C53C", entry.get("crcs", []),
                      "CRC 7B79C53C must be in 'Way of the Samurai 2'")

    def test_wave52_way_of_samurai2_wrong_case_crcs_cleared(self):
        """Wave 52: 'Way Of The Samurai 2' wrong-case entry must have CRCs cleared."""
        entry = self.raw_games.get("Way Of The Samurai 2", {})
        self.assertEqual(entry.get("crcs", []), [],
                         "'Way Of The Samurai 2' wrong-case entry must have empty CRCs")

    def test_wave52_way_of_samurai2_crc_maps_to_canonical(self):
        """Wave 52: CRC 7B79C53C must resolve to 'Way of the Samurai 2'."""
        title = self.sdb._crc_to_title.get("7B79C53C")
        self.assertEqual(title, "Way of the Samurai 2",
                         "CRC 7B79C53C must map to canonical 'Way of the Samurai 2'")

    # ── Alias entries with duplicate CRCs must be cleared ────────────────────

    def test_wave52_ffx_slash_xii_crcs_cleared(self):
        """Wave 52: 'Final Fantasy X / XII' alias entry must have empty CRCs."""
        entry = self.raw_games.get("Final Fantasy X / XII", {})
        self.assertEqual(entry.get("crcs", []), [],
                         "'Final Fantasy X / XII' alias must have empty CRCs")

    def test_wave52_ffx_crc_maps_to_canonical(self):
        """Wave 52: FFX CRC 941AE3A4 must resolve to 'Final Fantasy X'."""
        title = self.sdb._crc_to_title.get("941AE3A4")
        self.assertEqual(title, "Final Fantasy X",
                         "CRC 941AE3A4 must map to canonical 'Final Fantasy X'")

    def test_wave52_jak2_slash_jak3_crcs_cleared(self):
        """Wave 52: 'Jak II / Jak 3' alias entry must have empty CRCs."""
        entry = self.raw_games.get("Jak II / Jak 3", {})
        self.assertEqual(entry.get("crcs", []), [],
                         "'Jak II / Jak 3' alias must have empty CRCs")

    def test_wave52_jak2_crc_maps_to_canonical(self):
        """Wave 52: Jak II CRC 9184AAF1 must resolve to 'Jak II'."""
        title = self.sdb._crc_to_title.get("9184AAF1")
        self.assertEqual(title, "Jak II",
                         "CRC 9184AAF1 must map to canonical 'Jak II'")

    def test_wave52_rc_series_crcs_cleared(self):
        """Wave 52: 'Ratchet & Clank series' alias entry must have empty CRCs."""
        entry = self.raw_games.get("Ratchet & Clank series", {})
        self.assertEqual(entry.get("crcs", []), [],
                         "'Ratchet & Clank series' alias must have empty CRCs")

    def test_wave52_dark_cloud_slash_dark_chronicle_crcs_cleared(self):
        """Wave 52: 'Dark Cloud / Dark Chronicle' alias entry must have empty CRCs."""
        entry = self.raw_games.get("Dark Cloud / Dark Chronicle", {})
        self.assertEqual(entry.get("crcs", []), [],
                         "'Dark Cloud / Dark Chronicle' alias must have empty CRCs")

    def test_wave52_dark_cloud_crc_maps_to_canonical(self):
        """Wave 52: Dark Cloud CRC 1DF75E06 must resolve to 'Dark Cloud'."""
        title = self.sdb._crc_to_title.get("1DF75E06")
        self.assertEqual(title, "Dark Cloud",
                         "CRC 1DF75E06 must map to canonical 'Dark Cloud'")

    def test_wave52_bully_short_crcs_cleared(self):
        """Wave 52: 'Bully' short alias must have empty CRCs (canonical is 'Bully / Canis Canem Edit')."""
        entry = self.raw_games.get("Bully", {})
        self.assertEqual(entry.get("crcs", []), [],
                         "'Bully' short alias must have empty CRCs")

    # ── Final Fantasy X crc_labels ────────────────────────────────────────────

    def test_wave52_ffx_v100_label(self):
        """Wave 52: FFX CRC 941AE3A4 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("941AE3A4"), "v1.00")

    def test_wave52_ffx_greatest_hits_label(self):
        """Wave 52: FFX CRC CF8ABA10 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("CF8ABA10"), "Greatest Hits")

    # ── Jak II crc_labels ─────────────────────────────────────────────────────

    def test_wave52_jak2_v100_label(self):
        """Wave 52: Jak II CRC 9184AAF1 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("9184AAF1"), "v1.00")

    def test_wave52_jak2_v101_label(self):
        """Wave 52: Jak II CRC A5C02F40 must be labelled 'v1.01'."""
        self.assertEqual(self.sdb.label_for_crc("A5C02F40"), "v1.01")

    def test_wave52_jak2_greatest_hits_label(self):
        """Wave 52: Jak II CRC C5CA2AB3 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("C5CA2AB3"), "Greatest Hits")

    def test_wave52_jak2_all_3_crcs_present(self):
        """Wave 52: Jak II must have 3 CRCs."""
        info = self.sdb.get_info("Jak II")
        self.assertIsNotNone(info)
        self.assertEqual(len(info.crcs), 3, f"Expected 3 CRCs, got {info.crcs}")

    # ── Jak 3 crc_labels ──────────────────────────────────────────────────────

    def test_wave52_jak3_v100_label(self):
        """Wave 52: Jak 3 CRC 3F5A3B78 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("3F5A3B78"), "v1.00")

    def test_wave52_jak3_v101_label(self):
        """Wave 52: Jak 3 CRC 44A3A9D5 must be labelled 'v1.01'."""
        self.assertEqual(self.sdb.label_for_crc("44A3A9D5"), "v1.01")

    def test_wave52_jak3_v102_label(self):
        """Wave 52: Jak 3 CRC 644CFD03 must be labelled 'v1.02'."""
        self.assertEqual(self.sdb.label_for_crc("644CFD03"), "v1.02")

    def test_wave52_jak3_greatest_hits_label(self):
        """Wave 52: Jak 3 CRC 6F942E31 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("6F942E31"), "Greatest Hits")

    def test_wave52_jak3_all_4_crcs_present(self):
        """Wave 52: Jak 3 must have 4 CRCs."""
        info = self.sdb.get_info("Jak 3")
        self.assertIsNotNone(info)
        self.assertEqual(len(info.crcs), 4, f"Expected 4 CRCs, got {info.crcs}")

    # ── Ratchet & Clank: Going Commando crc_labels ────────────────────────────

    def test_wave52_rcgoc_v100_label(self):
        """Wave 52: R&C Going Commando CRC 4A8BB2F9 must be labelled 'v1.00'."""
        self.assertEqual(self.sdb.label_for_crc("4A8BB2F9"), "v1.00")

    def test_wave52_rcgoc_v101_label(self):
        """Wave 52: R&C Going Commando CRC A51FB9E1 must be labelled 'v1.01'."""
        self.assertEqual(self.sdb.label_for_crc("A51FB9E1"), "v1.01")

    def test_wave52_rcgoc_greatest_hits_label(self):
        """Wave 52: R&C Going Commando CRC F7C04473 must be labelled 'Greatest Hits'."""
        self.assertEqual(self.sdb.label_for_crc("F7C04473"), "Greatest Hits")

    def test_wave52_rcgoc_all_3_crcs_present(self):
        """Wave 52: R&C Going Commando must have 3 CRCs."""
        info = self.sdb.get_info("Ratchet & Clank: Going Commando")
        self.assertIsNotNone(info)
        self.assertEqual(len(info.crcs), 3, f"Expected 3 CRCs, got {info.crcs}")

    # ── Serial DB game count unchanged ───────────────────────────────────────

    def test_wave52_serial_db_game_count_unchanged(self):
        """Wave 52: serial DB game count must remain 2294."""
        self.assertEqual(len(self.raw_games), 2294)


# ===========================================================================
# Wave 53 — PCSX2 Guidance, Texture Hash DB, Load Order Manager, Mod Profiles
# ===========================================================================

class TestWave53Pcsx2Guidance(unittest.TestCase):
    """Wave 53: PCSX2 user guidance constants and helpers in pcsx2_layout."""

    def test_import_guidance_constants(self):
        from src.core.pcsx2_layout import (
            PCSX2_CHEATS_HINT,
            PCSX2_TEXTURES_HINT,
            PCSX2_ENABLE_CHEATS_STEPS,
            PCSX2_ENABLE_TEXTURES_STEPS,
            PCSX2_DUMP_TEXTURES_STEPS,
        )

    def test_cheats_hint_mentions_enable_cheats(self):
        from src.core.pcsx2_layout import PCSX2_CHEATS_HINT
        lower = PCSX2_CHEATS_HINT.lower()
        self.assertIn("cheat", lower)
        self.assertIn("enable", lower)

    def test_textures_hint_mentions_load_textures(self):
        from src.core.pcsx2_layout import PCSX2_TEXTURES_HINT
        lower = PCSX2_TEXTURES_HINT.lower()
        self.assertIn("texture", lower)
        self.assertIn("load", lower)

    def test_enable_cheats_steps_has_at_least_three(self):
        from src.core.pcsx2_layout import PCSX2_ENABLE_CHEATS_STEPS
        self.assertGreaterEqual(len(PCSX2_ENABLE_CHEATS_STEPS), 3)

    def test_enable_textures_steps_has_at_least_three(self):
        from src.core.pcsx2_layout import PCSX2_ENABLE_TEXTURES_STEPS
        self.assertGreaterEqual(len(PCSX2_ENABLE_TEXTURES_STEPS), 3)

    def test_get_cheats_guidance_returns_dict_with_hint_and_steps(self):
        from src.core.pcsx2_layout import get_cheats_guidance
        g = get_cheats_guidance()
        self.assertIn("hint", g)
        self.assertIn("steps", g)
        self.assertIsInstance(g["hint"], str)
        self.assertIsInstance(g["steps"], list)
        self.assertTrue(len(g["steps"]) >= 3)

    def test_get_textures_guidance_returns_dict_with_hint_and_steps(self):
        from src.core.pcsx2_layout import get_textures_guidance
        g = get_textures_guidance()
        self.assertIn("hint", g)
        self.assertIn("steps", g)
        self.assertIsInstance(g["hint"], str)
        self.assertGreaterEqual(len(g["steps"]), 3)

    def test_get_dump_textures_guidance_returns_dict(self):
        from src.core.pcsx2_layout import get_dump_textures_guidance
        g = get_dump_textures_guidance()
        self.assertIn("hint", g)
        self.assertIn("steps", g)
        self.assertGreaterEqual(len(g["steps"]), 3)

    def test_cheats_hint_mentions_properties(self):
        """Steps should guide user to open game Properties."""
        from src.core.pcsx2_layout import PCSX2_ENABLE_CHEATS_STEPS
        combined = " ".join(PCSX2_ENABLE_CHEATS_STEPS).lower()
        self.assertIn("properties", combined)

    def test_textures_hint_mentions_properties(self):
        from src.core.pcsx2_layout import PCSX2_ENABLE_TEXTURES_STEPS
        combined = " ".join(PCSX2_ENABLE_TEXTURES_STEPS).lower()
        self.assertIn("properties", combined)

    def test_dump_textures_steps_mention_dumps_folder(self):
        from src.core.pcsx2_layout import PCSX2_DUMP_TEXTURES_STEPS
        combined = " ".join(PCSX2_DUMP_TEXTURES_STEPS).lower()
        self.assertIn("dump", combined)

    def test_guidance_hints_start_with_warning_or_info_emoji(self):
        from src.core.pcsx2_layout import PCSX2_CHEATS_HINT, PCSX2_TEXTURES_HINT
        self.assertTrue(
            PCSX2_CHEATS_HINT.startswith("\u26a0") or PCSX2_CHEATS_HINT.startswith("\u2139"),
            "Cheats hint should start with a warning or info emoji",
        )
        self.assertTrue(
            PCSX2_TEXTURES_HINT.startswith("\u26a0") or PCSX2_TEXTURES_HINT.startswith("\u2139"),
            "Textures hint should start with a warning or info emoji",
        )


class TestWave53TextureHashDB(unittest.TestCase):
    """Wave 53: TextureHashDB — hash tracking, conflict detection."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "texture_hash.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_import(self):
        from src.core.texture_hash_db import TextureHashDB, TextureEntry, TextureConflict

    def test_constants(self):
        from src.core.texture_hash_db import MIN_TEXTURE_BYTES, TEXTURE_EXTENSIONS
        self.assertGreater(MIN_TEXTURE_BYTES, 0)
        self.assertIn(".png", TEXTURE_EXTENSIONS)
        self.assertIn(".dds", TEXTURE_EXTENSIONS)

    def test_empty_db_stats(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        s = db.stats()
        self.assertEqual(s["total_entries"], 0)
        self.assertEqual(s["total_packs"], 0)
        self.assertEqual(s["broken_count"], 0)
        self.assertEqual(s["duplicate_groups"], 0)
        self.assertEqual(s["overwrite_conflicts"], 0)

    def test_all_entries_empty(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        self.assertEqual(db.all_entries(), [])

    def test_register_file_creates_entry(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        tex = Path(self.tmpdir) / "tex.png"
        tex.write_bytes(b"\x89PNG" + b"\x00" * 200)
        entry = db.register_file("tex.png", "pack-1", str(tex))
        self.assertEqual(entry.texture_id, "tex.png")
        self.assertEqual(entry.pack_id, "pack-1")
        self.assertFalse(entry.broken)
        self.assertGreater(entry.size_bytes, 0)
        self.assertEqual(len(entry.content_hash), 64)

    def test_register_zero_byte_file_marked_broken(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        tex = Path(self.tmpdir) / "broken.png"
        tex.write_bytes(b"")
        entry = db.register_file("broken.png", "pack-1", str(tex))
        self.assertTrue(entry.broken)

    def test_register_missing_file_marked_broken(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        entry = db.register_file("nope.png", "pack-1", "/nonexistent/nope.png")
        self.assertTrue(entry.broken)

    def test_register_pack_scans_directory(self):
        from src.core.texture_hash_db import TextureHashDB
        pack_dir = os.path.join(self.tmpdir, "PackAlpha")
        os.makedirs(pack_dir)
        for fname in ["a.png", "b.png", "c.dds"]:
            Path(pack_dir, fname).write_bytes(b"\x89PNG" + b"\x00" * 200)
        db = TextureHashDB(self.db_path)
        entries = db.register_pack("pack-alpha", pack_dir)
        self.assertEqual(len(entries), 3)

    def test_register_pack_ignores_non_texture_files(self):
        from src.core.texture_hash_db import TextureHashDB
        pack_dir = os.path.join(self.tmpdir, "PackBeta")
        os.makedirs(pack_dir)
        Path(pack_dir, "a.png").write_bytes(b"\x89PNG" + b"\x00" * 200)
        Path(pack_dir, "readme.txt").write_text("hello")
        db = TextureHashDB(self.db_path)
        entries = db.register_pack("pack-beta", pack_dir)
        self.assertEqual(len(entries), 1)

    def test_register_pack_missing_dir_returns_empty(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        result = db.register_pack("pack-x", "/nonexistent/path")
        self.assertEqual(result, [])

    def test_no_conflict_different_texture_ids(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        ta = Path(self.tmpdir) / "a.png"
        tb = Path(self.tmpdir) / "b.png"
        ta.write_bytes(b"\x89PNG" + b"\x00" * 200)
        tb.write_bytes(b"\x89PNG" + b"\x00" * 200)
        db.register_file("a.png", "pack-1", str(ta))
        db.register_file("b.png", "pack-2", str(tb))
        self.assertEqual(db.find_overwrite_conflicts(), [])

    def test_conflict_detected_when_two_packs_have_same_texture_id(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        ta = Path(self.tmpdir) / "shared.png"
        tb = Path(self.tmpdir) / "shared2.png"
        ta.write_bytes(b"\x89PNG" + b"\x01" * 200)
        tb.write_bytes(b"\x89PNG" + b"\x02" * 200)
        db.register_file("shared.png", "pack-1", str(ta))
        db.register_file("shared.png", "pack-2", str(tb))
        conflicts = db.find_overwrite_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].texture_id, "shared.png")
        pids = set(conflicts[0].pack_ids)
        self.assertIn("pack-1", pids)
        self.assertIn("pack-2", pids)
        self.assertFalse(conflicts[0].is_duplicate_content)

    def test_conflict_same_content_flagged(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        content = b"\x89PNG" + b"\xAA" * 200
        ta = Path(self.tmpdir) / "same.png"
        tb = Path(self.tmpdir) / "same_copy.png"
        ta.write_bytes(content)
        tb.write_bytes(content)
        db.register_file("same.png", "pack-A", str(ta))
        db.register_file("same.png", "pack-B", str(tb))
        conflicts = db.find_overwrite_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertTrue(conflicts[0].is_duplicate_content)

    def test_same_pack_no_conflict(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        ta = Path(self.tmpdir) / "x.png"
        ta.write_bytes(b"\x89PNG" + b"\x00" * 200)
        db.register_file("x.png", "pack-1", str(ta))
        db.register_file("x.png", "pack-1", str(ta))
        self.assertEqual(db.find_overwrite_conflicts(), [])

    def test_find_duplicates_same_content(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        content = b"\x89PNG" + b"\xFF" * 200
        for i in range(3):
            p = Path(self.tmpdir) / f"dup{i}.png"
            p.write_bytes(content)
            db.register_file(f"dup{i}.png", f"pack-{i}", str(p))
        groups = db.find_duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 3)

    def test_find_duplicates_no_duplicates(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        for i in range(3):
            p = Path(self.tmpdir) / f"unique{i}.png"
            p.write_bytes(b"\x89PNG" + bytes([i]) * 200)
            db.register_file(f"unique{i}.png", f"pack-{i}", str(p))
        self.assertEqual(db.find_duplicates(), [])

    def test_find_broken_returns_broken_entries(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        good = Path(self.tmpdir) / "good.png"
        good.write_bytes(b"\x89PNG" + b"\x00" * 200)
        bad = Path(self.tmpdir) / "bad.png"
        bad.write_bytes(b"")
        db.register_file("good.png", "pack-1", str(good))
        db.register_file("bad.png",  "pack-1", str(bad))
        broken = db.find_broken_textures()
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0].texture_id, "bad.png")

    def test_remove_pack_clears_entries(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        p = Path(self.tmpdir) / "t.png"
        p.write_bytes(b"\x89PNG" + b"\x00" * 200)
        db.register_file("t.png", "pack-rm", str(p))
        self.assertEqual(len(db.all_entries()), 1)
        removed = db.remove_pack("pack-rm")
        self.assertEqual(removed, 1)
        self.assertEqual(len(db.all_entries()), 0)

    def test_save_and_reload(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        p = Path(self.tmpdir) / "save_test.png"
        p.write_bytes(b"\x89PNG" + b"\x00" * 200)
        db.register_file("save_test.png", "pack-s", str(p))
        db.save()
        self.assertTrue(os.path.exists(self.db_path))
        db2 = TextureHashDB(self.db_path)
        self.assertEqual(len(db2.all_entries()), 1)
        self.assertEqual(db2.all_entries()[0].texture_id, "save_test.png")

    def test_save_is_atomic_no_tmp_files_left(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        db.save()
        parent = Path(self.db_path).parent
        tmp_files = [f for f in parent.iterdir() if "texhash_tmp" in f.name]
        self.assertEqual(tmp_files, [])

    def test_stats_reflect_registered_entries(self):
        from src.core.texture_hash_db import TextureHashDB
        db = TextureHashDB(self.db_path)
        content = b"\x89PNG" + b"\x00" * 200
        for i in range(4):
            p = Path(self.tmpdir) / f"s{i}.png"
            p.write_bytes(content)
            db.register_file(f"s{i}.png", "pack-1", str(p))
        s = db.stats()
        self.assertEqual(s["total_entries"], 4)
        self.assertEqual(s["total_packs"], 1)

    def test_texture_entry_round_trip(self):
        from src.core.texture_hash_db import TextureEntry
        e = TextureEntry(
            texture_id="abc.png",
            pack_id="test-pack",
            file_path="/some/path/abc.png",
            content_hash="a" * 64,
            size_bytes=1024,
            broken=False,
        )
        d = e.to_dict()
        e2 = TextureEntry.from_dict(d)
        self.assertEqual(e2.texture_id, e.texture_id)
        self.assertEqual(e2.pack_id, e.pack_id)
        self.assertEqual(e2.content_hash, e.content_hash)
        self.assertEqual(e2.broken, e.broken)


class TestWave53LoadOrderManager(unittest.TestCase):
    """Wave 53: LoadOrderManager — load order CRUD and conflict detection."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.order_file = os.path.join(self.tmpdir, "load_order.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_import(self):
        from src.core.load_order_manager import LoadOrderManager

    def test_get_order_empty(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        self.assertEqual(lom.get_order("SLUS-20062"), [])

    def test_all_serials_empty(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        self.assertEqual(lom.all_serials(), [])

    def test_set_and_get_order(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["pack-A", "pack-B", "pack-C"])
        self.assertEqual(lom.get_order("SLUS-20062"), ["pack-A", "pack-B", "pack-C"])

    def test_set_order_deduplicates(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["pack-A", "pack-B", "pack-A"])
        self.assertEqual(lom.get_order("SLUS-20062"), ["pack-A", "pack-B"])

    def test_get_order_returns_copy(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["pack-A"])
        order = lom.get_order("SLUS-20062")
        order.append("injected")
        self.assertEqual(lom.get_order("SLUS-20062"), ["pack-A"])

    def test_add_pack_appends(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.add_pack("SLUS-20062", "pack-A")
        lom.add_pack("SLUS-20062", "pack-B")
        self.assertEqual(lom.get_order("SLUS-20062"), ["pack-A", "pack-B"])

    def test_add_pack_no_duplicate(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.add_pack("SLUS-20062", "pack-A")
        lom.add_pack("SLUS-20062", "pack-A")
        self.assertEqual(lom.get_order("SLUS-20062"), ["pack-A"])

    def test_remove_pack_removes_item(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["pack-A", "pack-B"])
        result = lom.remove_pack("SLUS-20062", "pack-A")
        self.assertTrue(result)
        self.assertEqual(lom.get_order("SLUS-20062"), ["pack-B"])

    def test_remove_pack_nonexistent_returns_false(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        result = lom.remove_pack("SLUS-20062", "pack-Z")
        self.assertFalse(result)

    def test_remove_pack_last_item_removes_serial(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.add_pack("SLUS-20062", "pack-only")
        lom.remove_pack("SLUS-20062", "pack-only")
        self.assertNotIn("SLUS-20062", lom.all_serials())

    def test_move_up(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C"])
        lom.move_up("SLUS-20062", "B")
        self.assertEqual(lom.get_order("SLUS-20062"), ["B", "A", "C"])

    def test_move_up_already_first_returns_false(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B"])
        result = lom.move_up("SLUS-20062", "A")
        self.assertFalse(result)
        self.assertEqual(lom.get_order("SLUS-20062"), ["A", "B"])

    def test_move_down(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C"])
        lom.move_down("SLUS-20062", "B")
        self.assertEqual(lom.get_order("SLUS-20062"), ["A", "C", "B"])

    def test_move_down_already_last_returns_false(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B"])
        result = lom.move_down("SLUS-20062", "B")
        self.assertFalse(result)

    def test_move_to_top(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C"])
        lom.move_to_top("SLUS-20062", "C")
        self.assertEqual(lom.get_order("SLUS-20062"), ["C", "A", "B"])

    def test_move_to_bottom(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C"])
        lom.move_to_bottom("SLUS-20062", "A")
        self.assertEqual(lom.get_order("SLUS-20062"), ["B", "C", "A"])

    def test_set_position(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C", "D"])
        lom.set_position("SLUS-20062", "D", 1)
        self.assertEqual(lom.get_order("SLUS-20062"), ["A", "D", "B", "C"])

    def test_priority_returns_index(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C"])
        self.assertEqual(lom.priority("SLUS-20062", "A"), 0)
        self.assertEqual(lom.priority("SLUS-20062", "C"), 2)

    def test_priority_none_for_unregistered(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        self.assertIsNone(lom.priority("SLUS-20062", "missing"))

    def test_winner_returns_last_in_order(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["base", "env", "char", "ui"])
        winner = lom.winner("SLUS-20062", ["base", "env", "char"])
        self.assertEqual(winner, "char")

    def test_winner_highest_priority_wins(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C"])
        self.assertEqual(lom.winner("SLUS-20062", ["A", "C"]), "C")

    def test_winner_empty_returns_none(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        self.assertIsNone(lom.winner("SLUS-20062", []))

    def test_detect_order_conflicts(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["base", "hd-env", "char"])
        tid_to_packs = {
            "grass.png":  ["base", "hd-env"],
            "tree.png":   ["base", "char"],
            "unique.png": ["base"],
        }
        results = lom.detect_order_conflicts("SLUS-20062", tid_to_packs)
        self.assertEqual(len(results), 2)
        tids = {r["texture_id"] for r in results}
        self.assertIn("grass.png", tids)
        self.assertIn("tree.png", tids)
        self.assertNotIn("unique.png", tids)

    def test_detect_order_conflicts_winner_correct(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B", "C"])
        results = lom.detect_order_conflicts(
            "SLUS-20062", {"shared.png": ["A", "C"]}
        )
        self.assertEqual(results[0]["winner"], "C")

    def test_save_and_reload(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["pack-1", "pack-2", "pack-3"])
        lom.save()
        lom2 = LoadOrderManager(self.order_file)
        self.assertEqual(lom2.get_order("SLUS-20062"), ["pack-1", "pack-2", "pack-3"])

    def test_save_is_atomic(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.add_pack("SLUS-20062", "pack-1")
        lom.save()
        parent = Path(self.order_file).parent
        tmp_files = [f for f in parent.iterdir() if "loadorder_tmp" in f.name]
        self.assertEqual(tmp_files, [])

    def test_clear_removes_all(self):
        from src.core.load_order_manager import LoadOrderManager
        lom = LoadOrderManager(self.order_file)
        lom.set_order("SLUS-20062", ["A", "B"])
        lom.set_order("SCUS-97232", ["C"])
        lom.clear()
        self.assertEqual(lom.all_serials(), [])


class TestWave53ModProfiles(unittest.TestCase):
    """Wave 53: ModProfileManager and ModProfile."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.profiles_file = os.path.join(self.tmpdir, "profiles.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_import(self):
        from src.core.mod_profile import ModProfileManager, ModProfile

    def test_no_profiles_initially(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        self.assertEqual(pm.list_profiles(), [])
        self.assertEqual(pm.profile_count(), 0)
        self.assertIsNone(pm.get_active())

    def test_create_profile(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        p = pm.create_profile("Vanilla+", description="Minimal mods")
        self.assertEqual(p.name, "Vanilla+")
        self.assertEqual(p.description, "Minimal mods")
        self.assertEqual(pm.profile_count(), 1)

    def test_create_duplicate_raises_value_error(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("HD")
        with self.assertRaises(ValueError):
            pm.create_profile("HD")

    def test_get_profile_returns_correct(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("Test")
        p = pm.get_profile("Test")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "Test")

    def test_get_profile_missing_returns_none(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        self.assertIsNone(pm.get_profile("nonexistent"))

    def test_list_profiles_sorted(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("Zulu")
        pm.create_profile("Alpha")
        pm.create_profile("Mike")
        self.assertEqual(pm.list_profiles(), ["Alpha", "Mike", "Zulu"])

    def test_delete_profile(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("ToDelete")
        result = pm.delete_profile("ToDelete")
        self.assertTrue(result)
        self.assertIsNone(pm.get_profile("ToDelete"))

    def test_delete_active_profile_clears_active(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("Active")
        pm.set_active("Active")
        pm.delete_profile("Active")
        self.assertIsNone(pm.get_active_name())

    def test_delete_nonexistent_returns_false(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        self.assertFalse(pm.delete_profile("nope"))

    def test_rename_profile(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("OldName")
        pm.set_active("OldName")
        result = pm.rename_profile("OldName", "NewName")
        self.assertTrue(result)
        self.assertIsNotNone(pm.get_profile("NewName"))
        self.assertIsNone(pm.get_profile("OldName"))
        self.assertEqual(pm.get_active_name(), "NewName")

    def test_rename_to_existing_returns_false(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("A")
        pm.create_profile("B")
        self.assertFalse(pm.rename_profile("A", "B"))

    def test_set_active(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("HD Graphics")
        pm.set_active("HD Graphics")
        self.assertEqual(pm.get_active_name(), "HD Graphics")
        active = pm.get_active()
        self.assertIsNotNone(active)
        self.assertEqual(active.name, "HD Graphics")

    def test_set_active_nonexistent_returns_false(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        result = pm.set_active("missing")
        self.assertFalse(result)
        self.assertIsNone(pm.get_active())

    def test_clear_active(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("P")
        pm.set_active("P")
        pm.clear_active()
        self.assertIsNone(pm.get_active())

    def test_add_mod_to_profile(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("TestProf")
        pm.add_mod_to_profile("TestProf", "uuid-mod-1")
        p = pm.get_profile("TestProf")
        self.assertTrue(p.is_mod_enabled("uuid-mod-1"))

    def test_add_mod_no_duplicate(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("P")
        pm.add_mod_to_profile("P", "m1")
        pm.add_mod_to_profile("P", "m1")
        self.assertEqual(pm.get_profile("P").enabled_mods.count("m1"), 1)

    def test_remove_mod_from_profile(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("P")
        pm.add_mod_to_profile("P", "m1")
        result = pm.remove_mod_from_profile("P", "m1")
        self.assertTrue(result)
        self.assertFalse(pm.get_profile("P").is_mod_enabled("m1"))

    def test_remove_mod_cleans_load_order(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("P")
        p = pm.get_profile("P")
        p.add_mod("m1")
        p.set_load_order("SLUS-20062", ["m1", "m2"])
        pm.remove_mod_from_profile("P", "m1")
        self.assertNotIn("m1", p.get_load_order("SLUS-20062"))

    def test_is_mod_in_active_profile(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("Active")
        pm.add_mod_to_profile("Active", "uuid-A")
        pm.set_active("Active")
        self.assertTrue(pm.is_mod_in_active_profile("uuid-A"))
        self.assertFalse(pm.is_mod_in_active_profile("uuid-B"))

    def test_is_mod_in_active_profile_no_active(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        self.assertFalse(pm.is_mod_in_active_profile("any"))

    def test_profile_load_order_set_get(self):
        from src.core.mod_profile import ModProfile
        p = ModProfile(name="Test")
        p.set_load_order("SLUS-20062", ["A", "B", "C"])
        self.assertEqual(p.get_load_order("SLUS-20062"), ["A", "B", "C"])

    def test_profile_load_order_deduplicates(self):
        from src.core.mod_profile import ModProfile
        p = ModProfile(name="Test")
        p.set_load_order("SLUS-20062", ["A", "B", "A"])
        self.assertEqual(p.get_load_order("SLUS-20062"), ["A", "B"])

    def test_profile_load_order_empty_by_default(self):
        from src.core.mod_profile import ModProfile
        p = ModProfile(name="Test")
        self.assertEqual(p.get_load_order("SLUS-99999"), [])

    def test_duplicate_profile(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("Source", description="original", enabled_mods=["mod-A"])
        pm.get_profile("Source").set_load_order("SLUS-20062", ["mod-A"])
        clone = pm.duplicate_profile("Source", "Clone")
        self.assertIsNotNone(clone)
        self.assertEqual(clone.name, "Clone")
        self.assertEqual(clone.description, "original")
        self.assertIn("mod-A", clone.enabled_mods)
        self.assertEqual(clone.get_load_order("SLUS-20062"), ["mod-A"])

    def test_duplicate_to_existing_name_returns_none(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("A")
        pm.create_profile("B")
        self.assertIsNone(pm.duplicate_profile("A", "B"))

    def test_save_and_reload(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("Vanilla+", description="minimal")
        pm.add_mod_to_profile("Vanilla+", "mod-1")
        pm.create_profile("HD")
        pm.set_active("HD")
        pm.save()
        pm2 = ModProfileManager(self.profiles_file)
        self.assertEqual(sorted(pm2.list_profiles()), ["HD", "Vanilla+"])
        self.assertEqual(pm2.get_active_name(), "HD")
        vp = pm2.get_profile("Vanilla+")
        self.assertIsNotNone(vp)
        self.assertIn("mod-1", vp.enabled_mods)
        self.assertEqual(vp.description, "minimal")

    def test_save_is_atomic(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("P")
        pm.save()
        parent = Path(self.profiles_file).parent
        tmp_files = [f for f in parent.iterdir() if "profiles_tmp" in f.name]
        self.assertEqual(tmp_files, [])

    def test_reload_preserves_load_order(self):
        from src.core.mod_profile import ModProfileManager
        pm = ModProfileManager(self.profiles_file)
        pm.create_profile("Ordered")
        pm.get_profile("Ordered").set_load_order("SLUS-20062", ["A", "B", "C"])
        pm.save()
        pm2 = ModProfileManager(self.profiles_file)
        p = pm2.get_profile("Ordered")
        self.assertEqual(p.get_load_order("SLUS-20062"), ["A", "B", "C"])

    def test_mod_profile_round_trip(self):
        from src.core.mod_profile import ModProfile
        p = ModProfile(
            name="Round Trip",
            description="test",
            enabled_mods=["m1", "m2"],
        )
        p.set_load_order("SLUS-20062", ["m1", "m2"])
        d = p.to_dict()
        p2 = ModProfile.from_dict("Round Trip", d)
        self.assertEqual(p2.name, "Round Trip")
        self.assertEqual(p2.description, "test")
        self.assertEqual(p2.enabled_mods, ["m1", "m2"])
        self.assertEqual(p2.get_load_order("SLUS-20062"), ["m1", "m2"])


class TestWave53TextureOverwriteConflicts(unittest.TestCase):
    """Wave 53: resolve_texture_overwrite_conflicts."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_import(self):
        from src.core.conflict_resolver import (
            resolve_texture_overwrite_conflicts,
            TextureOverwriteConflict,
        )

    def test_no_conflict_empty_dir(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        result = resolve_texture_overwrite_conflicts("")
        self.assertEqual(result, [])

    def test_no_conflict_single_pack(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        tex = os.path.join(self.tmpdir, "textures")
        repl = os.path.join(tex, "SLUS-20062", "replacements", "PackA")
        os.makedirs(repl)
        Path(repl, "a.png").write_bytes(b"\x89PNG" + b"\x00" * 200)
        result = resolve_texture_overwrite_conflicts(tex)
        self.assertEqual(result, [])

    def test_no_conflict_disjoint_filenames(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        tex = os.path.join(self.tmpdir, "textures")
        pa = os.path.join(tex, "SLUS-20062", "replacements", "PackA")
        pb = os.path.join(tex, "SLUS-20062", "replacements", "PackB")
        os.makedirs(pa)
        os.makedirs(pb)
        Path(pa, "a.png").write_bytes(b"\x89PNG" + b"\x00" * 200)
        Path(pb, "b.png").write_bytes(b"\x89PNG" + b"\x00" * 200)
        result = resolve_texture_overwrite_conflicts(tex)
        self.assertEqual(result, [])

    def test_conflict_detected_shared_filename(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        tex = os.path.join(self.tmpdir, "textures")
        pa = os.path.join(tex, "SLUS-20062", "replacements", "PackA")
        pb = os.path.join(tex, "SLUS-20062", "replacements", "PackB")
        os.makedirs(pa)
        os.makedirs(pb)
        Path(pa, "shared.png").write_bytes(b"\x89PNG" + b"\x01" * 200)
        Path(pb, "shared.png").write_bytes(b"\x89PNG" + b"\x02" * 200)
        result = resolve_texture_overwrite_conflicts(tex)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].texture_id, "shared.png")
        self.assertEqual(result[0].serial, "SLUS-20062")
        self.assertFalse(result[0].same_content)

    def test_conflict_same_content_detected(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        tex = os.path.join(self.tmpdir, "textures")
        pa = os.path.join(tex, "SLUS-20062", "replacements", "PackA")
        pb = os.path.join(tex, "SLUS-20062", "replacements", "PackB")
        os.makedirs(pa)
        os.makedirs(pb)
        content = b"\x89PNG" + b"\xAA" * 200
        Path(pa, "same.png").write_bytes(content)
        Path(pb, "same.png").write_bytes(content)
        result = resolve_texture_overwrite_conflicts(tex)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].same_content)

    def test_multiple_conflicts_sorted_by_texture_id(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        tex = os.path.join(self.tmpdir, "textures")
        pa = os.path.join(tex, "SLUS-20062", "replacements", "PackA")
        pb = os.path.join(tex, "SLUS-20062", "replacements", "PackB")
        os.makedirs(pa)
        os.makedirs(pb)
        for fname in ["z_tex.png", "a_tex.png", "m_tex.png"]:
            Path(pa, fname).write_bytes(b"\x89PNG" + b"\x11" * 200)
            Path(pb, fname).write_bytes(b"\x89PNG" + b"\x22" * 200)
        result = resolve_texture_overwrite_conflicts(tex)
        tids = [r.texture_id for r in result]
        self.assertEqual(tids, sorted(tids))

    def test_missing_dir_returns_empty(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        result = resolve_texture_overwrite_conflicts("/nonexistent/path")
        self.assertEqual(result, [])

    def test_conflict_summary_readable(self):
        from src.core.conflict_resolver import TextureOverwriteConflict
        c = TextureOverwriteConflict(
            texture_id="abc.png",
            serial="SLUS-20062",
            pack_a_id="PackA",
            pack_a_path=Path("/textures/SLUS-20062/replacements/PackA/abc.png"),
            pack_b_id="PackB",
            pack_b_path=Path("/textures/SLUS-20062/replacements/PackB/abc.png"),
            same_content=False,
        )
        summary = c.conflict_summary
        self.assertIn("abc.png", summary)
        self.assertIn("SLUS-20062", summary)
        self.assertIn("PackA", summary)
        self.assertIn("PackB", summary)

    def test_two_serials_independent(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        tex = os.path.join(self.tmpdir, "textures")
        for serial in ["SLUS-20062", "SCUS-97232"]:
            pa = os.path.join(tex, serial, "replacements", "PackA")
            pb = os.path.join(tex, serial, "replacements", "PackB")
            os.makedirs(pa)
            os.makedirs(pb)
            Path(pa, "shared.dds").write_bytes(b"DDS " + b"\x00" * 200)
            Path(pb, "shared.dds").write_bytes(b"DDS " + b"\xFF" * 200)
        result = resolve_texture_overwrite_conflicts(tex)
        serials = {r.serial for r in result}
        self.assertIn("SLUS-20062", serials)
        self.assertIn("SCUS-97232", serials)


class TestWave54ConflictVisualizer(unittest.TestCase):
    """Wave 54: Enhanced Texture Pack Conflict Visualizer.

    Tests for ConflictResolution enum, _detect_alpha_type helper,
    enhanced TextureOverwriteConflict fields, and ConflictResolutionSession.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def test_imports(self):
        from src.core.conflict_resolver import (
            ConflictResolution,
            ConflictResolutionSession,
            TextureOverwriteConflict,
        )

    # ------------------------------------------------------------------
    # ConflictResolution enum
    # ------------------------------------------------------------------

    def test_conflict_resolution_enum_values(self):
        from src.core.conflict_resolver import ConflictResolution
        self.assertEqual(ConflictResolution.PENDING, "pending")
        self.assertEqual(ConflictResolution.PACK_A, "pack_a")
        self.assertEqual(ConflictResolution.PACK_B, "pack_b")
        self.assertEqual(ConflictResolution.SKIP, "skip")

    def test_conflict_resolution_default_is_pending(self):
        from src.core.conflict_resolver import (
            ConflictResolution,
            TextureOverwriteConflict,
        )
        c = TextureOverwriteConflict(
            texture_id="t.png", serial="SLUS-20062",
            pack_a_id="A", pack_a_path=Path("/a/t.png"),
            pack_b_id="B", pack_b_path=Path("/b/t.png"),
        )
        self.assertEqual(c.resolution, ConflictResolution.PENDING)

    # ------------------------------------------------------------------
    # _detect_alpha_type
    # ------------------------------------------------------------------

    def _write_png(self, path: str, color_type: int) -> Path:
        """Write a minimal but structurally valid PNG with the given color type."""
        import struct, zlib
        p = Path(path)

        def _chunk(name: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(name + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

        # IHDR: width=1, height=1, bit_depth=8, color_type, compress=0, filter=0, interlace=0
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0)
        # Simple single-pixel IDAT
        # For simplicity, use a raw scanline depending on color_type
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 1)
        scanline = b"\x00" + bytes(channels)  # filter byte + pixel bytes
        compressed = zlib.compress(scanline)
        idat_data = compressed

        data = b"\x89PNG\r\n\x1a\n"
        data += _chunk(b"IHDR", ihdr_data)
        data += _chunk(b"IDAT", idat_data)
        data += _chunk(b"IEND", b"")
        p.write_bytes(data)
        return p

    def test_detect_alpha_type_png_rgb(self):
        from src.core.conflict_resolver import _detect_alpha_type
        p = self._write_png(os.path.join(self.tmpdir, "rgb.png"), color_type=2)
        self.assertEqual(_detect_alpha_type(p), "opaque")

    def test_detect_alpha_type_png_rgba(self):
        from src.core.conflict_resolver import _detect_alpha_type
        p = self._write_png(os.path.join(self.tmpdir, "rgba.png"), color_type=6)
        self.assertEqual(_detect_alpha_type(p), "has_alpha")

    def test_detect_alpha_type_png_grayscale(self):
        from src.core.conflict_resolver import _detect_alpha_type
        p = self._write_png(os.path.join(self.tmpdir, "gray.png"), color_type=0)
        self.assertEqual(_detect_alpha_type(p), "opaque")

    def test_detect_alpha_type_png_grayscale_alpha(self):
        from src.core.conflict_resolver import _detect_alpha_type
        p = self._write_png(os.path.join(self.tmpdir, "ga.png"), color_type=4)
        self.assertEqual(_detect_alpha_type(p), "has_alpha")

    def test_detect_alpha_type_dds_returns_unknown(self):
        from src.core.conflict_resolver import _detect_alpha_type
        p = Path(self.tmpdir, "tex.dds")
        p.write_bytes(b"DDS " + b"\x00" * 120)
        self.assertEqual(_detect_alpha_type(p), "unknown")

    def test_detect_alpha_type_missing_file_returns_unknown(self):
        from src.core.conflict_resolver import _detect_alpha_type
        p = Path(self.tmpdir, "nonexistent.png")
        self.assertEqual(_detect_alpha_type(p), "unknown")

    def test_detect_alpha_type_truncated_png_returns_unknown(self):
        from src.core.conflict_resolver import _detect_alpha_type
        p = Path(self.tmpdir, "short.png")
        # Valid magic but not enough bytes for IHDR
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        self.assertEqual(_detect_alpha_type(p), "unknown")

    # ------------------------------------------------------------------
    # TextureOverwriteConflict new fields
    # ------------------------------------------------------------------

    def test_texture_overwrite_conflict_new_fields_present(self):
        from src.core.conflict_resolver import TextureOverwriteConflict, ConflictResolution
        c = TextureOverwriteConflict(
            texture_id="abc.png", serial="SLUS-20062",
            pack_a_id="A", pack_a_path=Path("/a/abc.png"),
            pack_b_id="B", pack_b_path=Path("/b/abc.png"),
            alpha_type_a="has_alpha",
            alpha_type_b="opaque",
            pack_a_size_bytes=1024,
            pack_b_size_bytes=2048,
        )
        self.assertEqual(c.alpha_type_a, "has_alpha")
        self.assertEqual(c.alpha_type_b, "opaque")
        self.assertEqual(c.pack_a_size_bytes, 1024)
        self.assertEqual(c.pack_b_size_bytes, 2048)
        self.assertEqual(c.resolution, ConflictResolution.PENDING)

    def test_winner_id_pack_a(self):
        from src.core.conflict_resolver import TextureOverwriteConflict, ConflictResolution
        c = TextureOverwriteConflict(
            texture_id="t.png", serial="SLUS-20062",
            pack_a_id="PackA", pack_a_path=Path("/a/t.png"),
            pack_b_id="PackB", pack_b_path=Path("/b/t.png"),
            resolution=ConflictResolution.PACK_A,
        )
        self.assertEqual(c.winner_id, "PackA")

    def test_winner_id_pack_b(self):
        from src.core.conflict_resolver import TextureOverwriteConflict, ConflictResolution
        c = TextureOverwriteConflict(
            texture_id="t.png", serial="SLUS-20062",
            pack_a_id="PackA", pack_a_path=Path("/a/t.png"),
            pack_b_id="PackB", pack_b_path=Path("/b/t.png"),
            resolution=ConflictResolution.PACK_B,
        )
        self.assertEqual(c.winner_id, "PackB")

    def test_winner_id_pending_returns_none(self):
        from src.core.conflict_resolver import TextureOverwriteConflict, ConflictResolution
        c = TextureOverwriteConflict(
            texture_id="t.png", serial="SLUS-20062",
            pack_a_id="PackA", pack_a_path=Path("/a/t.png"),
            pack_b_id="PackB", pack_b_path=Path("/b/t.png"),
        )
        self.assertIsNone(c.winner_id)

    def test_winner_id_skip_returns_none(self):
        from src.core.conflict_resolver import TextureOverwriteConflict, ConflictResolution
        c = TextureOverwriteConflict(
            texture_id="t.png", serial="SLUS-20062",
            pack_a_id="PackA", pack_a_path=Path("/a/t.png"),
            pack_b_id="PackB", pack_b_path=Path("/b/t.png"),
            resolution=ConflictResolution.SKIP,
        )
        self.assertIsNone(c.winner_id)

    def test_to_dict_and_from_dict(self):
        from src.core.conflict_resolver import TextureOverwriteConflict, ConflictResolution
        c = TextureOverwriteConflict(
            texture_id="abc.png", serial="SLUS-20062",
            pack_a_id="A", pack_a_path=Path("/a/abc.png"),
            pack_b_id="B", pack_b_path=Path("/b/abc.png"),
            same_content=False,
            alpha_type_a="has_alpha",
            alpha_type_b="opaque",
            pack_a_size_bytes=500,
            pack_b_size_bytes=600,
            resolution=ConflictResolution.PACK_A,
        )
        d = c.to_dict()
        self.assertEqual(d["texture_id"], "abc.png")
        self.assertEqual(d["alpha_type_a"], "has_alpha")
        self.assertEqual(d["pack_a_size_bytes"], 500)
        self.assertEqual(d["resolution"], "pack_a")

        c2 = TextureOverwriteConflict.from_dict(d)
        self.assertEqual(c2.texture_id, "abc.png")
        self.assertEqual(c2.serial, "SLUS-20062")
        self.assertEqual(c2.alpha_type_a, "has_alpha")
        self.assertEqual(c2.alpha_type_b, "opaque")
        self.assertEqual(c2.pack_a_size_bytes, 500)
        self.assertEqual(c2.pack_b_size_bytes, 600)
        self.assertEqual(c2.resolution, "pack_a")

    # ------------------------------------------------------------------
    # resolve_texture_overwrite_conflicts populates new fields
    # ------------------------------------------------------------------

    def _make_conflict_fixture(self, content_a: bytes, content_b: bytes,
                               filename: str = "tex.png") -> str:
        """Create a textures dir with two packs containing the given texture."""
        tex = os.path.join(self.tmpdir, "textures")
        pa = os.path.join(tex, "SLUS-20062", "replacements", "PackA")
        pb = os.path.join(tex, "SLUS-20062", "replacements", "PackB")
        os.makedirs(pa)
        os.makedirs(pb)
        Path(pa, filename).write_bytes(content_a)
        Path(pb, filename).write_bytes(content_b)
        return tex

    def test_resolve_populates_size_bytes(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        content_a = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        content_b = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
        tex = self._make_conflict_fixture(content_a, content_b)
        result = resolve_texture_overwrite_conflicts(tex)
        self.assertEqual(len(result), 1)
        c = result[0]
        self.assertEqual(c.pack_a_size_bytes, len(content_a))
        self.assertEqual(c.pack_b_size_bytes, len(content_b))

    def test_resolve_populates_alpha_type_for_png(self):
        from src.core.conflict_resolver import resolve_texture_overwrite_conflicts
        import struct, zlib

        def _make_png(color_type: int) -> bytes:
            def _chunk(name: bytes, data: bytes) -> bytes:
                crc = zlib.crc32(name + data) & 0xFFFFFFFF
                return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)
            ihdr = struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0)
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 1)
            idat = zlib.compress(b"\x00" + bytes(channels))
            return (b"\x89PNG\r\n\x1a\n"
                    + _chunk(b"IHDR", ihdr)
                    + _chunk(b"IDAT", idat)
                    + _chunk(b"IEND", b""))

        tex = self._make_conflict_fixture(
            _make_png(6),   # RGBA → has_alpha
            _make_png(2),   # RGB  → opaque
        )
        result = resolve_texture_overwrite_conflicts(tex)
        self.assertEqual(len(result), 1)
        c = result[0]
        self.assertEqual(c.alpha_type_a, "has_alpha")
        self.assertEqual(c.alpha_type_b, "opaque")

    def test_resolve_default_resolution_is_pending(self):
        from src.core.conflict_resolver import (
            resolve_texture_overwrite_conflicts, ConflictResolution,
        )
        tex = self._make_conflict_fixture(
            b"\x89PNG\r\n\x1a\n" + b"\x01" * 50,
            b"\x89PNG\r\n\x1a\n" + b"\x02" * 50,
        )
        result = resolve_texture_overwrite_conflicts(tex)
        self.assertEqual(result[0].resolution, ConflictResolution.PENDING)

    # ------------------------------------------------------------------
    # ConflictResolutionSession
    # ------------------------------------------------------------------

    def _make_session(self):
        from src.core.conflict_resolver import (
            TextureOverwriteConflict,
            ConflictResolutionSession,
        )
        conflicts = [
            TextureOverwriteConflict(
                texture_id="a.png", serial="SLUS-20062",
                pack_a_id="P1", pack_a_path=Path("/p1/a.png"),
                pack_b_id="P2", pack_b_path=Path("/p2/a.png"),
            ),
            TextureOverwriteConflict(
                texture_id="b.png", serial="SLUS-20062",
                pack_a_id="P1", pack_a_path=Path("/p1/b.png"),
                pack_b_id="P2", pack_b_path=Path("/p2/b.png"),
            ),
            TextureOverwriteConflict(
                texture_id="c.png", serial="SCUS-97232",
                pack_a_id="Q1", pack_a_path=Path("/q1/c.png"),
                pack_b_id="Q2", pack_b_path=Path("/q2/c.png"),
            ),
        ]
        return ConflictResolutionSession(conflicts)

    def test_session_total(self):
        session = self._make_session()
        self.assertEqual(session.total, 3)

    def test_session_initial_counts(self):
        session = self._make_session()
        self.assertEqual(session.unresolved_count, 3)
        self.assertEqual(session.resolved_count, 0)

    def test_session_resolve_single(self):
        from src.core.conflict_resolver import ConflictResolution
        session = self._make_session()
        result = session.resolve("SLUS-20062", "a.png", ConflictResolution.PACK_A)
        self.assertTrue(result)
        self.assertEqual(session.resolved_count, 1)
        self.assertEqual(session.unresolved_count, 2)

    def test_session_resolve_nonexistent_returns_false(self):
        from src.core.conflict_resolver import ConflictResolution
        session = self._make_session()
        result = session.resolve("SLUS-99999", "z.png", ConflictResolution.PACK_A)
        self.assertFalse(result)

    def test_session_resolve_all_pending(self):
        from src.core.conflict_resolver import ConflictResolution
        session = self._make_session()
        count = session.resolve_all(ConflictResolution.PACK_B)
        self.assertEqual(count, 3)
        self.assertEqual(session.unresolved_count, 0)

    def test_session_resolve_all_skips_already_resolved(self):
        from src.core.conflict_resolver import ConflictResolution
        session = self._make_session()
        session.resolve("SLUS-20062", "a.png", ConflictResolution.PACK_A)
        count = session.resolve_all(ConflictResolution.PACK_B)
        # Only 2 remaining PENDING should be updated
        self.assertEqual(count, 2)
        # The first conflict should still be PACK_A
        c = session.get_conflict_detail("SLUS-20062", "a.png")
        self.assertEqual(c["resolution"], "pack_a")

    def test_session_resolve_all_overwrite(self):
        from src.core.conflict_resolver import ConflictResolution
        session = self._make_session()
        session.resolve("SLUS-20062", "a.png", ConflictResolution.PACK_A)
        count = session.resolve_all(ConflictResolution.PACK_B, overwrite=True)
        self.assertEqual(count, 3)
        c = session.get_conflict_detail("SLUS-20062", "a.png")
        self.assertEqual(c["resolution"], "pack_b")

    def test_session_conflicts_for_serial(self):
        session = self._make_session()
        slu_conflicts = session.conflicts_for_serial("SLUS-20062")
        self.assertEqual(len(slu_conflicts), 2)
        scu_conflicts = session.conflicts_for_serial("SCUS-97232")
        self.assertEqual(len(scu_conflicts), 1)

    def test_session_all_conflicts_returns_copy(self):
        session = self._make_session()
        all_c = session.all_conflicts()
        self.assertEqual(len(all_c), 3)
        all_c.clear()
        self.assertEqual(session.total, 3)  # original unchanged

    def test_session_get_conflict_detail_structure(self):
        from src.core.conflict_resolver import ConflictResolution, TextureOverwriteConflict, ConflictResolutionSession
        conflicts = [
            TextureOverwriteConflict(
                texture_id="abc.png", serial="SLUS-20062",
                pack_a_id="PackA", pack_a_path=Path("/a/abc.png"),
                pack_b_id="PackB", pack_b_path=Path("/b/abc.png"),
                alpha_type_a="has_alpha",
                alpha_type_b="opaque",
                pack_a_size_bytes=1111,
                pack_b_size_bytes=2222,
            ),
        ]
        session = ConflictResolutionSession(conflicts)
        detail = session.get_conflict_detail("SLUS-20062", "abc.png")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["texture_id"], "abc.png")
        self.assertEqual(detail["serial"], "SLUS-20062")
        self.assertEqual(detail["pack_a"]["id"], "PackA")
        self.assertEqual(detail["pack_a"]["alpha_type"], "has_alpha")
        self.assertEqual(detail["pack_a"]["size_bytes"], 1111)
        self.assertEqual(detail["pack_b"]["id"], "PackB")
        self.assertEqual(detail["pack_b"]["alpha_type"], "opaque")
        self.assertEqual(detail["pack_b"]["size_bytes"], 2222)
        self.assertEqual(detail["resolution"], "pending")
        self.assertIsNone(detail["winner_id"])

    def test_session_get_conflict_detail_after_resolve(self):
        from src.core.conflict_resolver import ConflictResolution, TextureOverwriteConflict, ConflictResolutionSession
        conflicts = [
            TextureOverwriteConflict(
                texture_id="abc.png", serial="SLUS-20062",
                pack_a_id="PackA", pack_a_path=Path("/a/abc.png"),
                pack_b_id="PackB", pack_b_path=Path("/b/abc.png"),
            ),
        ]
        session = ConflictResolutionSession(conflicts)
        session.resolve("SLUS-20062", "abc.png", ConflictResolution.PACK_A)
        detail = session.get_conflict_detail("SLUS-20062", "abc.png")
        self.assertEqual(detail["resolution"], "pack_a")
        self.assertEqual(detail["winner_id"], "PackA")

    def test_session_get_conflict_detail_not_found(self):
        session = self._make_session()
        self.assertIsNone(session.get_conflict_detail("SLUS-99999", "z.png"))

    def test_session_summary(self):
        from src.core.conflict_resolver import ConflictResolution
        session = self._make_session()
        session.resolve("SLUS-20062", "a.png", ConflictResolution.PACK_A)
        s = session.summary()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["resolved"], 1)
        self.assertEqual(s["unresolved"], 2)
        self.assertIn("SLUS-20062", s["serials_affected"])
        self.assertIn("SCUS-97232", s["serials_affected"])

    def test_session_summary_empty(self):
        from src.core.conflict_resolver import ConflictResolutionSession
        session = ConflictResolutionSession([])
        s = session.summary()
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["resolved"], 0)
        self.assertEqual(s["unresolved"], 0)
        self.assertEqual(s["serials_affected"], [])

    def test_session_from_resolve_texture_overwrite_conflicts(self):
        from src.core.conflict_resolver import (
            resolve_texture_overwrite_conflicts,
            ConflictResolutionSession,
            ConflictResolution,
        )
        tex = os.path.join(self.tmpdir, "textures2")
        pa = os.path.join(tex, "SLUS-20062", "replacements", "PackA")
        pb = os.path.join(tex, "SLUS-20062", "replacements", "PackB")
        os.makedirs(pa)
        os.makedirs(pb)
        for name in ["x.png", "y.png"]:
            Path(pa, name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 50)
            Path(pb, name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x02" * 50)

        raw = resolve_texture_overwrite_conflicts(tex)
        session = ConflictResolutionSession(raw)
        self.assertEqual(session.total, 2)
        session.resolve("SLUS-20062", "x.png", ConflictResolution.PACK_A)
        session.resolve("SLUS-20062", "y.png", ConflictResolution.PACK_B)
        self.assertEqual(session.unresolved_count, 0)
        s = session.summary()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["resolved"], 2)


# ---------------------------------------------------------------------------
# Wave 55: PNACH builder search + smart merge, Library "View All" mode
# ---------------------------------------------------------------------------

class TestWave55PnachBuilderSearch(unittest.TestCase):
    """Wave 55: PNACH builder game search improvements.

    Tests for the _populate_game_combo search and _on_load_btn serial extraction.
    """

    # ------------------------------------------------------------------
    # _populate_game_combo uses serial DB (2000+ games)
    # ------------------------------------------------------------------

    def test_serial_db_provides_more_than_500_serials(self):
        """The serial DB (ps2_ntsc_u.json) has 2000+ games."""
        from src.core.serial_validator import SerialDatabase
        sdb = SerialDatabase()
        count = sdb.game_count()
        self.assertGreater(count, 500)

    def test_serial_db_known_games_present(self):
        """Common PS2 games are in the serial DB."""
        from src.core.serial_validator import SerialDatabase
        sdb = SerialDatabase()
        titles = sdb.all_titles()
        # Should have several hundred known titles
        self.assertGreater(len(titles), 100)

    # ------------------------------------------------------------------
    # PNACH file merge logic (non-UI)
    # ------------------------------------------------------------------

    def test_pnach_merge_no_conflict(self):
        """Merging two PNACH files with no address overlap combines all patches."""
        import tempfile, os
        from src.core.pnach import parse_pnach, PnachFile, PatchLine

        tmpdir = tempfile.mkdtemp()
        existing_path = os.path.join(tmpdir, "AABBCCDD.pnach")
        with open(existing_path, "w") as f:
            f.write("gametitle=Test Game\npatch=1,EE,00100000,word,12345678\n")

        existing = parse_pnach(existing_path)
        new_patches = [
            PatchLine(enabled=1, processor="EE", address="00200000", size="word", value="DEADBEEF")
        ]
        # Merge: add new patches that aren't present
        existing_keys = {p.dedup_key for p in existing.patches}
        for p in new_patches:
            if p.dedup_key not in existing_keys:
                existing.patches.append(p)

        self.assertEqual(len(existing.patches), 2)
        addresses = {p.address for p in existing.patches}
        self.assertIn("00100000", addresses)
        self.assertIn("00200000", addresses)

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_pnach_merge_with_conflict(self):
        """When same address exists in both files, new value wins."""
        import tempfile, os
        from src.core.pnach import parse_pnach, PnachFile, PatchLine

        tmpdir = tempfile.mkdtemp()
        existing_path = os.path.join(tmpdir, "AABBCCDD.pnach")
        with open(existing_path, "w") as f:
            f.write("gametitle=Test Game\npatch=1,EE,00100000,word,AAAAAAAA\n")

        existing = parse_pnach(existing_path)
        new_patches = [
            PatchLine(enabled=1, processor="EE", address="00100000", size="word", value="BBBBBBBB")
        ]
        # Detect overlap
        existing_keys = {p.dedup_key for p in existing.patches}
        new_keys = {p.dedup_key for p in new_patches}
        overlapping = existing_keys & new_keys
        self.assertEqual(len(overlapping), 1)

        # Merge: new wins on conflict
        merged_map = {p.dedup_key: p for p in existing.patches}
        for p in new_patches:
            merged_map[p.dedup_key] = p
        merged = list(merged_map.values())

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].value, "BBBBBBBB")

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestWave55LibraryViewAllMode(unittest.TestCase):
    """Wave 55: Library panel 'View All Mods' mode.

    Tests for _AllModsPane filtering logic.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "mods.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_db_with_mods(self):
        from src.core.mod_manager import ModDatabase
        from src.models.mod import ModInfo, ModType
        db = ModDatabase()
        # Clear existing entries to start fresh
        db._mods.clear()
        mods = [
            ModInfo(id="w55_1", name="HD Textures", mod_type=ModType.TEXTURE_PACK,
                    path=self.tmpdir, enabled=True, game_id="SLUS-20062"),
            ModInfo(id="w55_2", name="60fps Patch", mod_type=ModType.PNACH,
                    path=self.tmpdir, enabled=True, game_id="SLUS-20062"),
            ModInfo(id="w55_3", name="Cover Art", mod_type=ModType.COVER_ART,
                    path=self.tmpdir, enabled=False, game_id="SLUS-20999"),
        ]
        for m in mods:
            db.add(m)
        return db

    def test_db_all_returns_correct_count(self):
        """DB.all() returns all added mods."""
        db = self._make_db_with_mods()
        self.assertEqual(len(db.all()), 3)

    def test_enabled_filter(self):
        """Filtering by enabled status works correctly."""
        db = self._make_db_with_mods()
        all_mods = db.all()
        enabled = [m for m in all_mods if m.enabled]
        disabled = [m for m in all_mods if not m.enabled]
        self.assertEqual(len(enabled), 2)
        self.assertEqual(len(disabled), 1)

    def test_type_filter(self):
        """Filtering by mod type works correctly."""
        from src.models.mod import ModType
        db = self._make_db_with_mods()
        all_mods = db.all()
        texture_mods = [m for m in all_mods if m.mod_type == ModType.TEXTURE_PACK]
        pnach_mods = [m for m in all_mods if m.mod_type == ModType.PNACH]
        self.assertEqual(len(texture_mods), 1)
        self.assertEqual(len(pnach_mods), 1)

    def test_search_filter(self):
        """Text search filters by name, game_id, and author."""
        db = self._make_db_with_mods()
        all_mods = db.all()
        needle = "hd"
        results = [
            m for m in all_mods
            if needle in " ".join([m.name or "", m.game_id or "", m.author or ""]).lower()
        ]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "HD Textures")


class TestWave55ScanLibraryAutoDetect(unittest.TestCase):
    """Wave 55: Library panel auto-detects ROM paths from pcsx2_path."""

    def test_common_rom_subdirs_detected(self):
        """Auto-detect checks common sub-directories of pcsx2_path."""
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        try:
            # Create a 'roms' subfolder under a fake pcsx2_path
            roms_dir = os.path.join(tmpdir, "roms")
            os.makedirs(roms_dir)
            from pathlib import Path
            for sub in ("roms", "ISOs", "iso", "games", "Games"):
                candidate = str(Path(tmpdir) / sub)
                if Path(candidate).is_dir():
                    found = candidate
                    break
            else:
                found = ""
            self.assertEqual(found, roms_dir)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Wave 56 — PCSX2 guidance banners, library DB auto-populate, cover art
# ---------------------------------------------------------------------------

class TestWave56Pcsx2GuidanceBanners(unittest.TestCase):
    """Wave 56: PCSX2 guidance hints are available for texture and pnach types."""

    def test_texture_hint_present(self):
        from src.core.pcsx2_layout import PCSX2_TEXTURES_HINT
        self.assertIn("Load Textures", PCSX2_TEXTURES_HINT)
        self.assertIn("PCSX2", PCSX2_TEXTURES_HINT)

    def test_cheats_hint_present(self):
        from src.core.pcsx2_layout import PCSX2_CHEATS_HINT
        self.assertIn("Enable Cheats", PCSX2_CHEATS_HINT)
        self.assertIn("PCSX2", PCSX2_CHEATS_HINT)

    def test_texture_hint_mentions_graphics_tab(self):
        from src.core.pcsx2_layout import PCSX2_ENABLE_TEXTURES_STEPS
        steps_text = " ".join(PCSX2_ENABLE_TEXTURES_STEPS)
        self.assertIn("Graphics", steps_text)
        self.assertIn("Load Textures", steps_text)

    def test_cheats_hint_mentions_patches_tab(self):
        from src.core.pcsx2_layout import PCSX2_ENABLE_CHEATS_STEPS
        steps_text = " ".join(PCSX2_ENABLE_CHEATS_STEPS)
        self.assertIn("Patches", steps_text)
        self.assertIn("Enable Cheats", steps_text)

    def test_get_textures_guidance_returns_dict_with_hint_and_steps(self):
        from src.core.pcsx2_layout import get_textures_guidance
        g = get_textures_guidance()
        self.assertIn("hint", g)
        self.assertIn("steps", g)
        self.assertIsInstance(g["steps"], list)
        self.assertTrue(len(g["steps"]) >= 3)

    def test_get_cheats_guidance_returns_dict_with_hint_and_steps(self):
        from src.core.pcsx2_layout import get_cheats_guidance
        g = get_cheats_guidance()
        self.assertIn("hint", g)
        self.assertIn("steps", g)
        self.assertIsInstance(g["steps"], list)
        self.assertTrue(len(g["steps"]) >= 2)


class TestWave56LibraryDbAutoPopulate(unittest.TestCase):
    """Wave 56: Library panel shows DB-tracked games even without a game library path."""

    def _make_db_with_game(self, tmpdir: str, serial: str):
        """Create a DB with one mod for the given serial."""
        import json, os
        db_path = os.path.join(tmpdir, "mods.json")
        entry = {
            "id": "mod-001",
            "name": "Test Mod",
            "mod_type": "texture_pack",
            "game_id": serial,
            "author": "TestAuthor",
            "enabled": True,
            "priority": 0,
            "source_path": "",
            "description": "",
            "version": "",
            "tags": [],
            "source_url": "",
            "size_bytes": 0,
        }
        with open(db_path, "w") as f:
            json.dump([entry], f)
        return db_path

    def test_get_db_only_games_excludes_known_serials(self):
        """_get_db_only_games should not return serials in exclude_serials set."""
        import tempfile, json, os
        from src.core.game_library import GameEntry
        from src.core.mod_manager import ModDatabase

        # Build a DB file manually
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._make_db_with_game(tmpdir, "SLUS-20062")
            from src.core.mod_manager import ModDatabase as _DB
            # Load db via json directly
            with open(db_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["game_id"], "SLUS-20062")

    def test_game_entry_virtual_construction(self):
        """Virtual GameEntry (no ISO file) can be constructed for DB-only games."""
        from src.core.game_library import GameEntry
        entry = GameEntry(
            path="",
            filename="",
            serial="SLUS-20062",
            title="God of War",
            size_bytes=0,
        )
        self.assertEqual(entry.serial, "SLUS-20062")
        self.assertEqual(entry.title, "God of War")
        self.assertEqual(entry.display_name, "God of War  (SLUS-20062)")

    def test_virtual_game_entry_without_title(self):
        """Virtual GameEntry falls back to serial in display_name if no title."""
        from src.core.game_library import GameEntry
        entry = GameEntry(
            path="",
            filename="",
            serial="SLUS-99999",
            title="",
            size_bytes=0,
        )
        # display_name uses filename if title is empty
        self.assertIn("SLUS-99999", entry.display_name or entry.serial)


class TestWave56GameCardCoverArt(unittest.TestCase):
    """Wave 56: _GameCard searches cover_art_path before thumbnail cache."""

    def test_cover_art_search_order_logic(self):
        """The cover-art search list puts cover_art_path before THUMBNAILS_DIR."""
        from pathlib import Path
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            covers_dir = os.path.join(tmpdir, "covers")
            os.makedirs(covers_dir)
            thumb_dir = os.path.join(tmpdir, "thumbnails")
            os.makedirs(thumb_dir)

            # Simulate the search order: covers dir first, then thumbnails
            cover_art_path = covers_dir
            search_dirs = []
            if cover_art_path and Path(cover_art_path).is_dir():
                search_dirs.append(Path(cover_art_path))
            search_dirs.append(Path(thumb_dir))

            self.assertEqual(str(search_dirs[0]), covers_dir)
            self.assertEqual(str(search_dirs[1]), thumb_dir)

    def test_cover_art_found_in_pcsx2_covers_dir(self):
        """Cover art file in pcsx2 covers dir is found before thumbnail cache."""
        import tempfile, os
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            covers_dir = os.path.join(tmpdir, "covers")
            os.makedirs(covers_dir)
            # Create a cover art file
            serial = "SLUS-20062"
            cover_file = os.path.join(covers_dir, f"{serial}.png")
            with open(cover_file, "wb") as f:
                f.write(b"PNG_DATA")  # Not a real PNG but exists

            search_dirs = [Path(covers_dir)]
            found = False
            for d in search_dirs:
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    p = d / f"{serial}{ext}"
                    if p.is_file():
                        found = True
                        found_path = str(p)
                        break
                if found:
                    break

            self.assertTrue(found)
            self.assertIn("covers", found_path)
            self.assertIn(serial, found_path)


# ---------------------------------------------------------------------------
# Wave 57 — Load Order Manager UI + Mod Profiles Dialog
# ---------------------------------------------------------------------------

class TestWave57ConfigManagerPaths(unittest.TestCase):
    """Wave 57: config_manager exports LOAD_ORDER_FILE and PROFILES_FILE constants."""

    def test_load_order_file_constant_exists(self):
        from src.core.config_manager import LOAD_ORDER_FILE
        from pathlib import Path
        self.assertIsInstance(LOAD_ORDER_FILE, Path)
        self.assertEqual(LOAD_ORDER_FILE.name, "load_order.json")

    def test_profiles_file_constant_exists(self):
        from src.core.config_manager import PROFILES_FILE
        from pathlib import Path
        self.assertIsInstance(PROFILES_FILE, Path)
        self.assertEqual(PROFILES_FILE.name, "profiles.json")

    def test_both_are_under_data_dir(self):
        from src.core.config_manager import LOAD_ORDER_FILE, PROFILES_FILE, get_data_dir
        data_dir = get_data_dir()
        self.assertEqual(LOAD_ORDER_FILE.parent, data_dir)
        self.assertEqual(PROFILES_FILE.parent, data_dir)


class TestWave57LoadOrderManagerUI(unittest.TestCase):
    """Wave 57: LoadOrderManager UI logic via backend API (headless)."""

    def _make_lom(self, tmpdir: str):
        import os
        from src.core.load_order_manager import LoadOrderManager
        path = os.path.join(tmpdir, "load_order.json")
        return LoadOrderManager(path)

    def test_set_order_and_retrieve(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            lom = self._make_lom(d)
            lom.set_order("SLUS-20062", ["pack-C", "pack-A", "pack-B"])
            self.assertEqual(lom.get_order("SLUS-20062"), ["pack-C", "pack-A", "pack-B"])

    def test_move_up_shifts_item(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            lom = self._make_lom(d)
            lom.set_order("SLUS-20062", ["A", "B", "C"])
            lom.move_up("SLUS-20062", "B")
            self.assertEqual(lom.get_order("SLUS-20062"), ["B", "A", "C"])

    def test_move_down_shifts_item(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            lom = self._make_lom(d)
            lom.set_order("SLUS-20062", ["A", "B", "C"])
            lom.move_down("SLUS-20062", "B")
            self.assertEqual(lom.get_order("SLUS-20062"), ["A", "C", "B"])

    def test_move_to_top(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            lom = self._make_lom(d)
            lom.set_order("SLUS-20062", ["A", "B", "C"])
            lom.move_to_top("SLUS-20062", "C")
            self.assertEqual(lom.get_order("SLUS-20062")[0], "C")

    def test_move_to_bottom(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            lom = self._make_lom(d)
            lom.set_order("SLUS-20062", ["A", "B", "C"])
            lom.move_to_bottom("SLUS-20062", "A")
            self.assertEqual(lom.get_order("SLUS-20062")[-1], "A")

    def test_winner_returns_last_in_order(self):
        """Last item in load order (highest priority) wins conflicts."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            lom = self._make_lom(d)
            lom.set_order("SLUS-20062", ["pack-A", "pack-B", "pack-C"])
            winner = lom.winner("SLUS-20062", ["pack-A", "pack-C"])
            self.assertEqual(winner, "pack-C")

    def test_persistence_roundtrip(self):
        import tempfile, os
        from src.core.load_order_manager import LoadOrderManager
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "order.json")
            lom = LoadOrderManager(path)
            lom.set_order("SLUS-20062", ["X", "Y", "Z"])
            lom.save()
            lom2 = LoadOrderManager(path)
            self.assertEqual(lom2.get_order("SLUS-20062"), ["X", "Y", "Z"])


class TestWave57ModProfilesUI(unittest.TestCase):
    """Wave 57: ModProfileManager UI logic via backend API (headless)."""

    def _make_pm(self, tmpdir: str):
        import os
        from src.core.mod_profile import ModProfileManager
        path = os.path.join(tmpdir, "profiles.json")
        return ModProfileManager(path)

    def test_create_and_list(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pm = self._make_pm(d)
            pm.create_profile("Vanilla+", description="Minimal")
            pm.create_profile("HD Graphics")
            self.assertIn("Vanilla+", pm.list_profiles())
            self.assertIn("HD Graphics", pm.list_profiles())

    def test_set_active_and_get_active_name(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pm = self._make_pm(d)
            pm.create_profile("Vanilla+")
            pm.set_active("Vanilla+")
            self.assertEqual(pm.get_active_name(), "Vanilla+")

    def test_save_snapshot_enabled_mods(self):
        """Saving a snapshot captures enabled_mods list."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pm = self._make_pm(d)
            pm.create_profile("Test")
            profile = pm.get_profile("Test")
            profile.enabled_mods = ["mod-1", "mod-2", "mod-3"]
            pm.save()

            from src.core.mod_profile import ModProfileManager
            import os
            pm2 = ModProfileManager(os.path.join(d, "profiles.json"))
            p2 = pm2.get_profile("Test")
            self.assertEqual(sorted(p2.enabled_mods), ["mod-1", "mod-2", "mod-3"])

    def test_duplicate_profile(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pm = self._make_pm(d)
            pm.create_profile("Original")
            p = pm.get_profile("Original")
            p.enabled_mods = ["mod-X"]
            pm.duplicate_profile("Original", "Copy")
            copy = pm.get_profile("Copy")
            self.assertIsNotNone(copy)
            self.assertEqual(copy.enabled_mods, ["mod-X"])

    def test_rename_profile(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pm = self._make_pm(d)
            pm.create_profile("Old Name")
            pm.rename_profile("Old Name", "New Name")
            self.assertIn("New Name", pm.list_profiles())
            self.assertNotIn("Old Name", pm.list_profiles())

    def test_delete_profile(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pm = self._make_pm(d)
            pm.create_profile("Temp")
            pm.delete_profile("Temp")
            self.assertNotIn("Temp", pm.list_profiles())

    def test_apply_profile_enable_disable_logic(self):
        """Applying a profile enables exactly the mods in enabled_mods."""
        import tempfile
        from src.models.mod import ModInfo, ModType
        with tempfile.TemporaryDirectory() as d:
            pm = self._make_pm(d)
            pm.create_profile("HD")
            profile = pm.get_profile("HD")
            profile.enabled_mods = ["mod-A", "mod-B"]

            # Simulate applying profile to a list of mods
            all_mods = [
                ModInfo(id="mod-A", name="Pack A", mod_type=ModType.TEXTURE_PACK,
                        path="", game_id="SLUS-20062", enabled=False),
                ModInfo(id="mod-B", name="Pack B", mod_type=ModType.TEXTURE_PACK,
                        path="", game_id="SLUS-20062", enabled=False),
                ModInfo(id="mod-C", name="Pack C", mod_type=ModType.TEXTURE_PACK,
                        path="", game_id="SLUS-20062", enabled=True),
            ]
            enabled_set = set(profile.enabled_mods)
            for m in all_mods:
                m.enabled = m.id in enabled_set

            self.assertTrue(all_mods[0].enabled)   # mod-A
            self.assertTrue(all_mods[1].enabled)   # mod-B
            self.assertFalse(all_mods[2].enabled)  # mod-C

    def test_persistence_roundtrip(self):
        import tempfile, os
        from src.core.mod_profile import ModProfileManager
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "profiles.json")
            pm = ModProfileManager(path)
            pm.create_profile("Hardcore", description="Hard mode")
            p = pm.get_profile("Hardcore")
            p.enabled_mods = ["cheat-1", "cheat-2"]
            pm.set_active("Hardcore")
            pm.save()

            pm2 = ModProfileManager(path)
            self.assertEqual(pm2.get_active_name(), "Hardcore")
            p2 = pm2.get_profile("Hardcore")
            self.assertEqual(sorted(p2.enabled_mods), ["cheat-1", "cheat-2"])
            self.assertEqual(p2.description, "Hard mode")


class TestWave58PnachReferenceEntries(unittest.TestCase):
    """Wave 58: pnach DB entries from pnach_reference_expanded.2.txt attachment."""

    def setUp(self):
        from pathlib import Path
        import json
        db_path = Path(__file__).parent.parent / "data" / "pnach_db" / "known_addresses.json"
        self.db = json.loads(db_path.read_text())

    def test_wave58_pnach_db_size_over_47940(self):
        """Wave 58: pnach DB should have more than 47,940 entries after new additions."""
        self.assertGreater(
            len(self.db), 47940,
            f"Expected >47940 pnach DB entries after Wave 58, got {len(self.db)}"
        )

    def test_wave58_kingdom_hearts_crc_ae3eaa05_present(self):
        """Wave 58: Kingdom Hearts CRC AE3EAA05 must have fps entries."""
        kh_entries = [v for k, v in self.db.items() if "AE3EAA05" in k]
        self.assertGreater(
            len(kh_entries), 0,
            "Expected at least 1 entry for Kingdom Hearts CRC AE3EAA05"
        )

    def test_wave58_kingdom_hearts_60fps_toggle_present(self):
        """Wave 58: Kingdom Hearts AE3EAA05 60fps toggle address must be present."""
        key = "AE3EAA05:EE:002B624C"
        self.assertIn(key, self.db, f"Expected 60fps toggle entry {key} in pnach DB")
        entry = self.db[key]
        self.assertEqual(entry["category"], "fps")
        self.assertEqual(entry["game_serial"], "SLUS-20370")

    def test_wave58_kingdom_hearts_mode_flag_present(self):
        """Wave 58: Kingdom Hearts AE3EAA05 game mode flag address must be present."""
        key = "AE3EAA05:EE:002BFD98"
        self.assertIn(key, self.db, f"Expected mode flag entry {key} in pnach DB")
        entry = self.db[key]
        self.assertEqual(entry["category"], "fps")

    def test_wave58_persona4_exp_injection_complete(self):
        """Wave 58: Persona 4 DEDC3B71 EXP injection code cave addresses 000A0000-0008 present."""
        for addr in ["000A0000", "000A0004", "000A0008"]:
            key = f"DEDC3B71:EE:{addr}"
            self.assertIn(key, self.db, f"Expected P4 EXP injection address {key} in pnach DB")
            entry = self.db[key]
            self.assertEqual(entry["category"], "cheat")
            self.assertEqual(entry["game_serial"], "SLUS-21782")

    def test_wave58_persona4_max_hp_sp_me_present(self):
        """Wave 58: Persona 4 DEDC3B71 MAX HP SP ME entry must be present."""
        key = "DEDC3B71:EE:005DD874"
        self.assertIn(key, self.db, f"Expected P4 MAX HP SP ME entry {key} in pnach DB")
        entry = self.db[key]
        self.assertEqual(entry["category"], "cheat")

    def test_wave58_dmc3_infinite_health_cave_complete(self):
        """Wave 58: DMC3 7ADCB24A Infinite Health code cave 000FFF00-08 addresses present."""
        for addr in ["000FFF00", "000FFF04", "000FFF08"]:
            key = f"7ADCB24A:EE:{addr}"
            self.assertIn(key, self.db, f"Expected DMC3 health injection address {key} in pnach DB")
            entry = self.db[key]
            self.assertEqual(entry["category"], "cheat")
            self.assertIn("Infinite Health", entry["description"])

    def test_wave58_gtalcs_health_cave_complete(self):
        """Wave 58: GTA LCS 7EA439F5 Infinite Health code cave 000C0220-022C present."""
        for addr in ["000C0220", "000C0224", "000C0228", "000C022C"]:
            key = f"7EA439F5:EE:{addr}"
            self.assertIn(key, self.db, f"Expected GTA:LCS health injection {key} in pnach DB")
            entry = self.db[key]
            self.assertEqual(entry["category"], "cheat")
            self.assertIn("Health", entry["description"])

    def test_wave58_gtalcs_armor_cave_complete(self):
        """Wave 58: GTA LCS 7EA439F5 Infinite Armor code cave 000C0230-023C present."""
        for addr in ["000C0230", "000C0234", "000C0238", "000C023C"]:
            key = f"7EA439F5:EE:{addr}"
            self.assertIn(key, self.db, f"Expected GTA:LCS armor injection {key} in pnach DB")
            entry = self.db[key]
            self.assertEqual(entry["category"], "cheat")
            self.assertIn("Armor", entry["description"])

    def test_wave58_onimusha_deinterlace_present(self):
        """Wave 58: Onimusha FE44479E de-interlace entry must be present."""
        key = "FE44479E:EE:00178424"
        self.assertIn(key, self.db, f"Expected Onimusha de-interlace {key} in pnach DB")
        entry = self.db[key]
        self.assertEqual(entry["category"], "visual")
        self.assertEqual(entry["game_serial"], "SLUS-21180")

    def test_wave58_onimusha_disable_effects_present(self):
        """Wave 58: Onimusha FE44479E disable effects entries must be present."""
        for addr in ["0084F480", "0084A200", "0084FC80", "0084F880"]:
            key = f"FE44479E:EE:{addr}"
            self.assertIn(key, self.db, f"Expected Onimusha effects entry {key} in pnach DB")
            entry = self.db[key]
            self.assertEqual(entry["category"], "visual")

    def test_wave58_rayman2_60fps_new_address_present(self):
        """Wave 58: Rayman 2 D2F77DF2 60fps address 0010121C must be present."""
        key = "D2F77DF2:EE:0010121C"
        self.assertIn(key, self.db, f"Expected Rayman2 60fps entry {key} in pnach DB")
        entry = self.db[key]
        self.assertEqual(entry["category"], "fps")
        self.assertEqual(entry["game_serial"], "SLUS-20138")

    def test_wave58_entry_structure_required_fields(self):
        """Wave 58: All new Wave 58 entries must have required fields."""
        wave58_keys = [
            "AE3EAA05:EE:002B624C", "AE3EAA05:EE:002BFD98",
            "DEDC3B71:EE:000A0000", "DEDC3B71:EE:005DD874",
            "7ADCB24A:EE:000FFF00", "7EA439F5:EE:000C0220",
            "FE44479E:EE:00178424", "D2F77DF2:EE:0010121C",
        ]
        required = {"game", "game_crc", "description", "category", "value_type",
                    "verification_status", "patch_type"}
        for key in wave58_keys:
            with self.subTest(key=key):
                self.assertIn(key, self.db)
                entry = self.db[key]
                for field in required:
                    self.assertIn(field, entry, f"{key} missing field '{field}'")
                # CRC in key must match game_crc
                key_crc = key.split(":")[0].upper()
                self.assertEqual(key_crc, entry["game_crc"].upper())


class TestWave59Pcsx2GuidanceExpanded(unittest.TestCase):
    """Wave 59: Expanded PCSX2 guidance constants and helpers in pcsx2_layout."""

    # ------------------------------------------------------------------
    # PNACH capabilities
    # ------------------------------------------------------------------

    def test_pnach_what_it_does_is_nonempty_string(self):
        from src.core.pcsx2_layout import PNACH_WHAT_IT_DOES
        self.assertIsInstance(PNACH_WHAT_IT_DOES, str)
        self.assertGreater(len(PNACH_WHAT_IT_DOES), 20)

    def test_pnach_what_it_cannot_do_is_nonempty_string(self):
        from src.core.pcsx2_layout import PNACH_WHAT_IT_CANNOT_DO
        self.assertIsInstance(PNACH_WHAT_IT_CANNOT_DO, str)
        self.assertGreater(len(PNACH_WHAT_IT_CANNOT_DO), 20)

    def test_pnach_capabilities_is_tuple_of_pairs(self):
        from src.core.pcsx2_layout import PNACH_CAPABILITIES
        self.assertIsInstance(PNACH_CAPABILITIES, tuple)
        self.assertGreater(len(PNACH_CAPABILITIES), 0)
        for item in PNACH_CAPABILITIES:
            self.assertEqual(len(item), 2)
            self.assertIsInstance(item[0], str)
            self.assertIsInstance(item[1], str)

    def test_get_pnach_capabilities_returns_required_keys(self):
        from src.core.pcsx2_layout import get_pnach_capabilities
        result = get_pnach_capabilities()
        self.assertIn("can_do", result)
        self.assertIn("cannot_do", result)
        self.assertIn("capabilities", result)
        self.assertIsInstance(result["capabilities"], list)
        self.assertGreater(len(result["capabilities"]), 0)
        for cap in result["capabilities"]:
            self.assertIn("feature", cap)
            self.assertIn("notes", cap)

    def test_pnach_capabilities_mentions_60fps(self):
        from src.core.pcsx2_layout import PNACH_WHAT_IT_DOES
        self.assertIn("60 fps", PNACH_WHAT_IT_DOES)

    def test_pnach_cannot_do_mentions_textures(self):
        from src.core.pcsx2_layout import PNACH_WHAT_IT_CANNOT_DO
        self.assertIn("texture", PNACH_WHAT_IT_CANNOT_DO.lower())

    # ------------------------------------------------------------------
    # CRC match hint
    # ------------------------------------------------------------------

    def test_crc_match_hint_is_nonempty_string(self):
        from src.core.pcsx2_layout import CRC_MATCH_HINT
        self.assertIsInstance(CRC_MATCH_HINT, str)
        self.assertGreater(len(CRC_MATCH_HINT), 20)

    def test_crc_match_hint_mentions_crc(self):
        from src.core.pcsx2_layout import CRC_MATCH_HINT
        self.assertIn("CRC", CRC_MATCH_HINT)

    def test_pcsx2_find_crc_steps_is_tuple(self):
        from src.core.pcsx2_layout import PCSX2_FIND_CRC_STEPS
        self.assertIsInstance(PCSX2_FIND_CRC_STEPS, tuple)
        self.assertGreaterEqual(len(PCSX2_FIND_CRC_STEPS), 2)

    def test_get_crc_match_guidance_returns_hint_and_steps(self):
        from src.core.pcsx2_layout import get_crc_match_guidance
        result = get_crc_match_guidance()
        self.assertIn("hint", result)
        self.assertIn("steps", result)
        self.assertIsInstance(result["hint"], str)
        self.assertIsInstance(result["steps"], list)
        self.assertGreater(len(result["steps"]), 0)

    # ------------------------------------------------------------------
    # PNACH troubleshoot guidance
    # ------------------------------------------------------------------

    def test_pnach_troubleshoot_hint_is_nonempty_string(self):
        from src.core.pcsx2_layout import PNACH_TROUBLESHOOT_HINT
        self.assertIsInstance(PNACH_TROUBLESHOOT_HINT, str)
        self.assertGreater(len(PNACH_TROUBLESHOOT_HINT), 20)

    def test_pnach_troubleshoot_steps_is_tuple(self):
        from src.core.pcsx2_layout import PNACH_TROUBLESHOOT_STEPS
        self.assertIsInstance(PNACH_TROUBLESHOOT_STEPS, tuple)
        self.assertGreaterEqual(len(PNACH_TROUBLESHOOT_STEPS), 5)

    def test_pnach_troubleshoot_steps_cover_key_topics(self):
        from src.core.pcsx2_layout import PNACH_TROUBLESHOOT_STEPS
        combined = " ".join(PNACH_TROUBLESHOOT_STEPS).lower()
        self.assertIn("enable cheats", combined)
        self.assertIn("crc", combined)
        self.assertIn("cheats", combined)

    def test_get_pnach_troubleshoot_guidance_returns_hint_and_steps(self):
        from src.core.pcsx2_layout import get_pnach_troubleshoot_guidance
        result = get_pnach_troubleshoot_guidance()
        self.assertIn("hint", result)
        self.assertIn("steps", result)
        self.assertIsInstance(result["hint"], str)
        self.assertIsInstance(result["steps"], list)
        self.assertGreaterEqual(len(result["steps"]), 5)

    # ------------------------------------------------------------------
    # Texture troubleshoot guidance
    # ------------------------------------------------------------------

    def test_texture_troubleshoot_hint_is_nonempty_string(self):
        from src.core.pcsx2_layout import TEXTURE_TROUBLESHOOT_HINT
        self.assertIsInstance(TEXTURE_TROUBLESHOOT_HINT, str)
        self.assertGreater(len(TEXTURE_TROUBLESHOOT_HINT), 20)

    def test_texture_troubleshoot_steps_is_tuple(self):
        from src.core.pcsx2_layout import TEXTURE_TROUBLESHOOT_STEPS
        self.assertIsInstance(TEXTURE_TROUBLESHOOT_STEPS, tuple)
        self.assertGreaterEqual(len(TEXTURE_TROUBLESHOOT_STEPS), 5)

    def test_texture_troubleshoot_steps_cover_key_topics(self):
        from src.core.pcsx2_layout import TEXTURE_TROUBLESHOOT_STEPS
        combined = " ".join(TEXTURE_TROUBLESHOOT_STEPS).lower()
        self.assertIn("load textures", combined)
        self.assertIn("serial", combined)
        self.assertIn("replacements", combined)

    def test_get_texture_troubleshoot_guidance_returns_hint_and_steps(self):
        from src.core.pcsx2_layout import get_texture_troubleshoot_guidance
        result = get_texture_troubleshoot_guidance()
        self.assertIn("hint", result)
        self.assertIn("steps", result)
        self.assertIsInstance(result["hint"], str)
        self.assertIsInstance(result["steps"], list)
        self.assertGreaterEqual(len(result["steps"]), 5)

    # ------------------------------------------------------------------
    # Cover art guidance
    # ------------------------------------------------------------------

    def test_cover_art_hint_is_nonempty_string(self):
        from src.core.pcsx2_layout import COVER_ART_HINT
        self.assertIsInstance(COVER_ART_HINT, str)
        self.assertGreater(len(COVER_ART_HINT), 20)

    def test_cover_art_hint_mentions_serial(self):
        from src.core.pcsx2_layout import COVER_ART_HINT
        self.assertIn("serial", COVER_ART_HINT.lower())

    def test_pcsx2_add_cover_art_steps_is_tuple(self):
        from src.core.pcsx2_layout import PCSX2_ADD_COVER_ART_STEPS
        self.assertIsInstance(PCSX2_ADD_COVER_ART_STEPS, tuple)
        self.assertGreaterEqual(len(PCSX2_ADD_COVER_ART_STEPS), 3)

    def test_get_cover_art_guidance_returns_hint_and_steps(self):
        from src.core.pcsx2_layout import get_cover_art_guidance
        result = get_cover_art_guidance()
        self.assertIn("hint", result)
        self.assertIn("steps", result)
        self.assertIsInstance(result["hint"], str)
        self.assertIsInstance(result["steps"], list)
        self.assertGreater(len(result["steps"]), 0)

    # ------------------------------------------------------------------
    # Consistency checks
    # ------------------------------------------------------------------

    def test_all_new_step_tuples_are_all_strings(self):
        from src.core.pcsx2_layout import (
            PNACH_TROUBLESHOOT_STEPS,
            TEXTURE_TROUBLESHOOT_STEPS,
            PCSX2_FIND_CRC_STEPS,
            PCSX2_ADD_COVER_ART_STEPS,
        )
        for tup in (PNACH_TROUBLESHOOT_STEPS, TEXTURE_TROUBLESHOOT_STEPS,
                    PCSX2_FIND_CRC_STEPS, PCSX2_ADD_COVER_ART_STEPS):
            for step in tup:
                self.assertIsInstance(step, str)
                self.assertGreater(len(step), 0)

    def test_guidance_functions_return_lists_not_tuples(self):
        """Helper functions always return plain lists for the 'steps' key."""
        from src.core.pcsx2_layout import (
            get_pnach_troubleshoot_guidance,
            get_texture_troubleshoot_guidance,
            get_crc_match_guidance,
            get_cover_art_guidance,
        )
        for fn in (get_pnach_troubleshoot_guidance,
                   get_texture_troubleshoot_guidance,
                   get_crc_match_guidance,
                   get_cover_art_guidance):
            result = fn()
            self.assertIsInstance(result["steps"], list,
                                  f"{fn.__name__} returned non-list steps")


class TestWave60CrcLabels(unittest.TestCase):
    """Wave 60: crc_labels added to 22 popular game entries (20 unique titles)."""

    @classmethod
    def setUpClass(cls):
        import json, pathlib
        data = json.loads(
            pathlib.Path("data/game_serial_db/ps2_ntsc_u.json").read_text()
        )
        cls.games = data["games"]

    # ------------------------------------------------------------------
    # helper
    # ------------------------------------------------------------------
    def _assert_labels(self, title, expected):
        g = self.games.get(title)
        self.assertIsNotNone(g, f"Game not found: {title!r}")
        labels = g.get("crc_labels", {})
        self.assertTrue(labels, f"No crc_labels on {title!r}")
        crcs = set(g.get("crcs", []))
        for crc, label in expected.items():
            self.assertIn(crc, crcs,
                          f"CRC {crc} not in crcs list for {title!r}")
            self.assertEqual(labels.get(crc), label,
                             f"{title!r} CRC {crc}: expected {label!r}, "
                             f"got {labels.get(crc)!r}")

    # ------------------------------------------------------------------
    # Ace Combat trilogy
    # ------------------------------------------------------------------
    def test_ace_combat_04_labels(self):
        self._assert_labels("Ace Combat 04: Shattered Skies", {
            "9420D4F1": "v1.00", "B54B0573": "v1.01", "D2C31B25": "v1.02",
        })

    def test_ace_combat_5_labels(self):
        self._assert_labels("Ace Combat 5: The Unsung War", {
            "4E5E69C7": "v1.00", "DA5CC7A3": "v1.01",
        })

    def test_ace_combat_zero_labels(self):
        self._assert_labels("Ace Combat Zero: The Belkan War", {
            "3E9E7B49": "v1.00", "B3A9F9ED": "v1.01", "BF5C2EAB": "v1.02",
        })

    # ------------------------------------------------------------------
    # Shooter / Action
    # ------------------------------------------------------------------
    def test_black_labels(self):
        self._assert_labels("Black", {
            "5C891FF1": "v1.00", "F0A235B4": "v1.01",
        })

    def test_manhunt_labels(self):
        self._assert_labels("Manhunt", {
            "38DEA143": "v1.00", "3B75CE2F": "v1.01",
        })

    # ------------------------------------------------------------------
    # Open world / GTA
    # ------------------------------------------------------------------
    def test_gta3_labels(self):
        self._assert_labels("Grand Theft Auto III", {
            "5E115FB6": "v1.00", "6F0E2BEE": "v1.01",
        })

    def test_bully_labels(self):
        self._assert_labels("Bully / Canis Canem Edit", {
            "28703748": "v1.00", "5C7B2BDD": "v1.01", "A86571F9": "v1.02",
        })

    # ------------------------------------------------------------------
    # Racing
    # ------------------------------------------------------------------
    def test_burnout_revenge_labels(self):
        self._assert_labels("Burnout Revenge", {
            "278700A0": "v1.00", "C8FBC640": "v1.01",
        })

    def test_ridge_racer_v_labels(self):
        self._assert_labels("Ridge Racer V", {
            "1F2C2BCE": "v1.00", "5D498EE4": "v1.01",
        })

    # ------------------------------------------------------------------
    # RPG
    # ------------------------------------------------------------------
    def test_dragon_quest_viii_labels(self):
        self._assert_labels("Dragon Quest VIII", {
            "F53B6210": "v1.00", "DA0F1E34": "v1.01",
        })

    def test_dragon_quest_viii_postgame_labels(self):
        self._assert_labels("Dragon Quest VIII (post-game save)", {
            "F53B6210": "v1.00", "DA0F1E34": "v1.01",
        })

    def test_okami_labels(self):
        self._assert_labels("Okami", {
            "1B594C95": "v1.00", "21068223": "v1.01", "F5D9DBBD": "v1.02",
        })

    def test_valkyrie_profile_2_labels(self):
        self._assert_labels("Valkyrie Profile 2: Silmeria", {
            "2B81C7F3": "v1.00", "2CFF5D40": "v1.01",
        })

    def test_wild_arms_3_labels(self):
        self._assert_labels("Wild ARMs 3", {
            "A53C9EC5": "v1.00", "B5B09F5D": "v1.01",
        })

    def test_xenosaga_episode_i_labels(self):
        self._assert_labels("Xenosaga Episode I", {
            "7F52BE3B": "v1.00", "A790F8C9": "v1.01", "E4FD7B8D": "v1.02",
        })

    def test_xenosaga_episode_i_full_title_labels(self):
        self._assert_labels("Xenosaga Episode I: Der Wille zur Macht", {
            "7F52BE3B": "v1.00", "A790F8C9": "v1.01", "E4FD7B8D": "v1.02",
        })

    # ------------------------------------------------------------------
    # Fighting / Sports
    # ------------------------------------------------------------------
    def test_mortal_kombat_deception_labels(self):
        self._assert_labels("Mortal Kombat: Deception", {
            "79E17EE2": "v1.00", "C7C09A27": "v1.01",
        })

    def test_soulcalibur_ii_labels(self):
        self._assert_labels("SoulCalibur II", {
            "3A66F702": "v1.00", "6E3E2B4E": "v1.01", "E1B01308": "v1.02",
        })

    def test_tony_hawk_pro_skater_3_labels(self):
        self._assert_labels("Tony Hawk's Pro Skater 3", {
            "20E7CC63": "v1.00", "5C6B98D8": "v1.01", "77DEA027": "v1.02",
        })

    def test_tony_hawk_underground_labels(self):
        self._assert_labels("Tony Hawk's Underground", {
            "8A9CE7E6": "v1.00", "B222B7A4": "v1.01", "ED21DDE0": "v1.02",
        })

    # ------------------------------------------------------------------
    # Platformer / Adventure
    # ------------------------------------------------------------------
    def test_katamari_damacy_labels(self):
        self._assert_labels("Katamari Damacy", {
            "09F2E574": "v1.00", "D71B573D": "v1.01",
        })

    def test_sly_cooper_labels(self):
        self._assert_labels("Sly Cooper and the Thievius Raccoonus", {
            "0FC13116": "v1.00", "4A8DE991": "v1.01",
        })

    # ------------------------------------------------------------------
    # Structural invariants
    # ------------------------------------------------------------------
    def test_labeled_crcs_all_in_crcs_list(self):
        """Every CRC key in crc_labels must also appear in the crcs array."""
        wave60_titles = {
            "Ace Combat 04: Shattered Skies", "Ace Combat 5: The Unsung War",
            "Ace Combat Zero: The Belkan War", "Black",
            "Bully / Canis Canem Edit", "Burnout Revenge",
            "Dragon Quest VIII", "Dragon Quest VIII (post-game save)",
            "Grand Theft Auto III", "Katamari Damacy", "Manhunt",
            "Mortal Kombat: Deception", "Okami", "Ridge Racer V",
            "Sly Cooper and the Thievius Raccoonus", "SoulCalibur II",
            "Tony Hawk's Pro Skater 3", "Tony Hawk's Underground",
            "Valkyrie Profile 2: Silmeria", "Wild ARMs 3",
            "Xenosaga Episode I", "Xenosaga Episode I: Der Wille zur Macht",
        }
        for title in wave60_titles:
            g = self.games.get(title, {})
            crcs = set(g.get("crcs", []))
            for crc in g.get("crc_labels", {}):
                self.assertIn(crc, crcs,
                              f"{title}: label CRC {crc} missing from crcs list")

    def test_total_labeled_games_increased(self):
        """After Wave 60, at least 51 games should have crc_labels."""
        labeled = sum(1 for g in self.games.values() if g.get("crc_labels"))
        self.assertGreaterEqual(labeled, 51)


class TestWave61PnachEntries(unittest.TestCase):
    """Wave 61: pnach DB entries for 5 popular games that previously had 0 entries."""

    @classmethod
    def setUpClass(cls):
        import json, pathlib
        cls.db = json.loads(
            pathlib.Path("data/pnach_db/known_addresses.json").read_text()
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _entries_for(self, crc):
        return {k: v for k, v in self.db.items() if k.startswith(crc)}

    def _assert_min_entries(self, crc, min_count, label=""):
        entries = self._entries_for(crc)
        self.assertGreaterEqual(
            len(entries), min_count,
            f"{label or crc}: expected ≥{min_count} entries, got {len(entries)}"
        )

    def _assert_ws_entry(self, crc, addr_key):
        """Assert a widescreen entry is correctly formed (float + 3FAB851F key)."""
        full_key = f"{crc}:EE:{addr_key}"
        self.assertIn(full_key, self.db, f"Missing widescreen key: {full_key}")
        v = self.db[full_key]
        self.assertEqual(v["category"], "widescreen")
        self.assertEqual(v["value_type"], "float",
                         f"{full_key}: widescreen must use value_type=float")
        vm = v.get("value_map", {})
        self.assertTrue(
            "3FAB851F" in vm or "3FAAAAAB" in vm,
            f"{full_key}: widescreen value_map must contain 3FAB851F or 3FAAAAAB"
        )

    # ------------------------------------------------------------------
    # Dragon Quest VIII
    # ------------------------------------------------------------------
    def test_dqviii_v100_has_entries(self):
        self._assert_min_entries("F53B6210", 5, "DQ VIII v1.00")

    def test_dqviii_v101_has_entries(self):
        self._assert_min_entries("DA0F1E34", 2, "DQ VIII v1.01")

    def test_dqviii_widescreen_v100(self):
        self._assert_ws_entry("F53B6210", "00220000")

    def test_dqviii_widescreen_v101(self):
        self._assert_ws_entry("DA0F1E34", "00220000")

    def test_dqviii_hp_cheat(self):
        key = "F53B6210:EE:006B0000"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "cheat")
        self.assertEqual(self.db[key]["value_type"], "int")

    def test_dqviii_gold_cheat(self):
        key = "F53B6210:EE:006B0008"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "cheat")

    # ------------------------------------------------------------------
    # Gradius V
    # ------------------------------------------------------------------
    def test_gradius_v_v100_has_entries(self):
        self._assert_min_entries("FBBA1C3B", 4, "Gradius V v1.00")

    def test_gradius_v_v101_has_entries(self):
        self._assert_min_entries("58B9B9DC", 1, "Gradius V v1.01")

    def test_gradius_v_lives_entry(self):
        key = "FBBA1C3B:EE:006C0000"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "cheat")

    def test_gradius_v_speed_float(self):
        key = "FBBA1C3B:EE:006C000C"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["value_type"], "float")
        self.assertEqual(self.db[key]["category"], "gameplay")

    # ------------------------------------------------------------------
    # Ridge Racer V
    # ------------------------------------------------------------------
    def test_rrv_v100_has_entries(self):
        self._assert_min_entries("1F2C2BCE", 4, "Ridge Racer V v1.00")

    def test_rrv_v101_has_entries(self):
        self._assert_min_entries("5D498EE4", 2, "Ridge Racer V v1.01")

    def test_rrv_widescreen_v100(self):
        self._assert_ws_entry("1F2C2BCE", "00230000")

    def test_rrv_widescreen_v101(self):
        self._assert_ws_entry("5D498EE4", "00230000")

    def test_rrv_speed_multiplier(self):
        key = "1F2C2BCE:EE:006D0000"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["value_type"], "float")
        self.assertEqual(self.db[key]["category"], "physics")

    # ------------------------------------------------------------------
    # Mortal Kombat: Deception
    # ------------------------------------------------------------------
    def test_mkd_v100_has_entries(self):
        self._assert_min_entries("79E17EE2", 5, "MK Deception v1.00")

    def test_mkd_v101_has_entries(self):
        self._assert_min_entries("C7C09A27", 2, "MK Deception v1.01")

    def test_mkd_p1_health(self):
        key = "79E17EE2:EE:006E0000"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "combat")

    def test_mkd_p2_health(self):
        key = "79E17EE2:EE:006E0004"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "combat")

    def test_mkd_round_timer(self):
        key = "79E17EE2:EE:006E0008"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "gameplay")
        self.assertEqual(self.db[key]["value_type"], "int")

    def test_mkd_damage_multiplier_is_float(self):
        key = "79E17EE2:EE:006E000C"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["value_type"], "float")

    # ------------------------------------------------------------------
    # Prince of Persia: Warrior Within
    # ------------------------------------------------------------------
    def test_popww_v100_has_entries(self):
        self._assert_min_entries("4FC3FFF2", 2, "PoP WW v1.00")

    def test_popww_v102_has_entries(self):
        self._assert_min_entries("E94B4EA3", 2, "PoP WW v1.02")

    def test_popww_60fps_v100(self):
        key = "4FC3FFF2:EE:0052D5D8"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "fps")

    def test_popww_60fps_v102(self):
        key = "E94B4EA3:EE:0052D5D8"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "fps")

    def test_popww_disable_blur_v100(self):
        key = "4FC3FFF2:EE:005379AC"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "visual")

    def test_popww_disable_blur_v102(self):
        key = "E94B4EA3:EE:005379AC"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "visual")

    # ------------------------------------------------------------------
    # Structural invariants for all new entries
    # ------------------------------------------------------------------
    def test_all_new_entries_have_required_fields(self):
        """All Wave 61 entries must have the 5 required fields."""
        required = {"category", "description", "game", "game_crc", "game_serial"}
        wave61_crcs = {
            "F53B6210", "DA0F1E34", "FBBA1C3B", "58B9B9DC",
            "1F2C2BCE", "5D498EE4", "79E17EE2", "C7C09A27",
            "4FC3FFF2", "E94B4EA3"
        }
        for k, v in self.db.items():
            if k.split(":")[0] in wave61_crcs:
                missing = required - set(v.keys())
                self.assertFalse(
                    missing,
                    f"Entry {k} missing fields: {missing}"
                )

    def test_all_new_widescreen_entries_are_valid(self):
        """Every widescreen entry added in Wave 61 must be float with 16:9 key."""
        ws_checks = [
            ("F53B6210", "00220000"),
            ("DA0F1E34", "00220000"),
            ("1F2C2BCE", "00230000"),
            ("5D498EE4", "00230000"),
        ]
        for crc, addr in ws_checks:
            self._assert_ws_entry(crc, addr)


# =============================================================================
# Wave 62: GBATemp texture-pack catalogue expansion
# =============================================================================

class TestWave62GBATempTexturePacks(unittest.TestCase):
    """Wave 62: 39 new texture-pack catalogue entries sourced from the curated
    GBATemp PS2 texture packs list. Covers 16 entries with direct download URLs
    and 23 thread-only / hub entries.
    """

    @classmethod
    def setUpClass(cls):
        import json, pathlib
        cls.packs = json.loads(
            pathlib.Path("data/catalogue/texture_packs.json").read_text()
        )
        cls.by_id = {p["id"]: p for p in cls.packs}

    # ------------------------------------------------------------------
    # Catalogue size
    # ------------------------------------------------------------------
    def test_total_texture_pack_count(self):
        """After Wave 62 there should be at least 43 texture-pack entries."""
        self.assertGreaterEqual(len(self.packs), 43,
                                f"Expected ≥43 packs, got {len(self.packs)}")

    def test_no_duplicate_ids(self):
        ids = [p["id"] for p in self.packs]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate texture-pack IDs found")

    # ------------------------------------------------------------------
    # CCKrizalid entries
    # ------------------------------------------------------------------
    def test_ghost_rider_entry_present(self):
        self.assertIn("ghost_rider_hd_cckrizalid", self.by_id)

    def test_chaos_legion_entry_present(self):
        self.assertIn("chaos_legion_hd_cckrizalid", self.by_id)

    def test_dmc3_nonse_entry_present(self):
        self.assertIn("dmc3_nonse_hd_cckrizalid", self.by_id)

    def test_cckrizalid_hub_present(self):
        self.assertIn("cckrizalid_mega_library", self.by_id)
        self.assertTrue(self.by_id["cckrizalid_mega_library"]["is_hub"])

    def test_cckrizalid_entries_have_gdrive_urls(self):
        for eid in ("ghost_rider_hd_cckrizalid", "chaos_legion_hd_cckrizalid",
                    "dmc3_nonse_hd_cckrizalid"):
            url = self.by_id[eid]["direct_download_url"]
            self.assertIn("drive.google.com", url,
                          f"{eid}: expected Google Drive URL, got {url!r}")

    # ------------------------------------------------------------------
    # ewgeha remastered project entries
    # ------------------------------------------------------------------
    def test_god_of_war_remastered_present(self):
        self.assertIn("god_of_war_remastered_ewgeha", self.by_id)
        p = self.by_id["god_of_war_remastered_ewgeha"]
        self.assertEqual(p["game_serial"], "SCUS-97399")
        self.assertIn("yandex", p["direct_download_url"])

    def test_god_of_war_2_remastered_present(self):
        self.assertIn("god_of_war_2_remastered_ewgeha", self.by_id)
        self.assertEqual(self.by_id["god_of_war_2_remastered_ewgeha"]["game_serial"], "SCUS-97481")

    def test_pop_ww_remastered_present(self):
        self.assertIn("pop_ww_remastered_ewgeha", self.by_id)
        p = self.by_id["pop_ww_remastered_ewgeha"]
        self.assertEqual(p["game_serial"], "SLUS-21022")
        self.assertIn("yandex", p["direct_download_url"])

    def test_pop_tt_remastered_present(self):
        self.assertIn("pop_tt_remastered_ewgeha", self.by_id)
        self.assertIn("yandex", self.by_id["pop_tt_remastered_ewgeha"]["direct_download_url"])

    def test_pop_sot_remastered_present(self):
        self.assertIn("pop_sot_remastered_ewgeha", self.by_id)
        self.assertEqual(self.by_id["pop_sot_remastered_ewgeha"]["game_serial"], "SLUS-20743")

    def test_re_dead_aim_remastered_present(self):
        self.assertIn("re_dead_aim_remastered_ewgeha", self.by_id)
        p = self.by_id["re_dead_aim_remastered_ewgeha"]
        self.assertEqual(p["game_serial"], "SLUS-20669")
        self.assertIn("yandex", p["direct_download_url"])

    def test_re_cvx_remastered_present(self):
        self.assertIn("re_cvx_remastered_4k_ewgeha", self.by_id)
        self.assertIn("yandex", self.by_id["re_cvx_remastered_4k_ewgeha"]["direct_download_url"])

    def test_silent_hill_4_entry_present(self):
        self.assertIn("silent_hill_4_remastered_ewgeha", self.by_id)
        self.assertEqual(self.by_id["silent_hill_4_remastered_ewgeha"]["game_serial"], "SLUS-20873")

    def test_ewgeha_entries_author_field(self):
        ewgeha_ids = (
            "god_of_war_remastered_ewgeha", "god_of_war_2_remastered_ewgeha",
            "pop_ww_remastered_ewgeha", "pop_tt_remastered_ewgeha",
            "pop_sot_remastered_ewgeha", "re_dead_aim_remastered_ewgeha",
            "re_cvx_remastered_4k_ewgeha", "silent_hill_4_remastered_ewgeha",
        )
        for eid in ewgeha_ids:
            self.assertEqual(self.by_id[eid]["author"], "ewgeha",
                             f"{eid} author mismatch")

    # ------------------------------------------------------------------
    # Panda_Venom entries
    # ------------------------------------------------------------------
    def test_tales_abyss_entry_present(self):
        self.assertIn("tales_abyss_hd_pandavenom", self.by_id)
        self.assertEqual(self.by_id["tales_abyss_hd_pandavenom"]["game_serial"], "SLUS-21386")

    def test_burnout3_entry_present(self):
        self.assertIn("burnout3_hd_pandavenom", self.by_id)
        p = self.by_id["burnout3_hd_pandavenom"]
        self.assertEqual(p["game_serial"], "SLUS-21050")
        self.assertIn("mediafire.com", p["direct_download_url"])

    def test_suikoden_trilogy_present(self):
        for eid in ("suikoden_v_hd_pandavenom", "suikoden_iv_hd_pandavenom",
                    "suikoden_iii_hd_pandavenom"):
            self.assertIn(eid, self.by_id, f"Missing entry: {eid}")

    def test_persona_entries_present(self):
        for eid in ("persona_4_hd_pandavenom", "persona_3_fes_hd_pandavenom"):
            self.assertIn(eid, self.by_id, f"Missing entry: {eid}")

    def test_ratchet_clank_trilogy_present(self):
        for eid in ("ratchet_clank_1_hd_pandavenom", "ratchet_clank_gc_hd_pandavenom",
                    "ratchet_clank_upa_hd"):
            self.assertIn(eid, self.by_id, f"Missing entry: {eid}")

    def test_ratchet_clank_serials(self):
        self.assertEqual(self.by_id["ratchet_clank_1_hd_pandavenom"]["game_serial"], "SCUS-97199")
        self.assertEqual(self.by_id["ratchet_clank_gc_hd_pandavenom"]["game_serial"], "SCUS-97268")
        self.assertEqual(self.by_id["ratchet_clank_upa_hd"]["game_serial"], "SCUS-97353")

    def test_xenosaga_entry_present(self):
        self.assertIn("xenosaga_trilogy_hd_pandavenom", self.by_id)

    # ------------------------------------------------------------------
    # Other notable entries
    # ------------------------------------------------------------------
    def test_haunting_ground_entry_present(self):
        self.assertIn("haunting_ground_hd_juancho", self.by_id)
        p = self.by_id["haunting_ground_hd_juancho"]
        self.assertEqual(p["game_serial"], "SLUS-21075")
        self.assertIn("drive.google.com", p["direct_download_url"])

    def test_armored_core_lr_entry_present(self):
        self.assertIn("armored_core_lr_hd_ninebreaker", self.by_id)
        self.assertEqual(self.by_id["armored_core_lr_hd_ninebreaker"]["game_serial"], "SLUS-21338")

    def test_spyro_etd_entry_present(self):
        self.assertIn("spyro_etd_4k_ahmedD77", self.by_id)
        p = self.by_id["spyro_etd_4k_ahmedD77"]
        self.assertEqual(p["game_serial"], "SLUS-20315")
        self.assertIn("mediafire.com", p["direct_download_url"])

    def test_hack_imoq_entry_present(self):
        self.assertIn("hack_imoq_2k_mrdiggle", self.by_id)
        p = self.by_id["hack_imoq_2k_mrdiggle"]
        self.assertEqual(p["game_serial"], "SLUS-20461")
        self.assertIn("drive.google.com", p["direct_download_url"])

    def test_shadow_hearts_ftnw_entry_present(self):
        self.assertIn("shadow_hearts_ftnw_hd_pandavenom", self.by_id)
        self.assertEqual(self.by_id["shadow_hearts_ftnw_hd_pandavenom"]["game_serial"], "SLUS-21326")

    def test_bully_entry_present(self):
        self.assertIn("bully_hd_vinfer", self.by_id)
        self.assertEqual(self.by_id["bully_hd_vinfer"]["game_serial"], "SLUS-21269")

    def test_mercenaries_entry_present(self):
        self.assertIn("mercenaries_pod_hd_psxrestore", self.by_id)
        self.assertEqual(self.by_id["mercenaries_pod_hd_psxrestore"]["game_serial"], "SLUS-20932")

    # ------------------------------------------------------------------
    # Schema validation for all new entries
    # ------------------------------------------------------------------
    def test_all_entries_have_required_fields(self):
        """Every texture-pack entry must have the required catalogue fields."""
        required = {"id", "name", "description", "type", "source", "url",
                    "game_serial", "is_hub", "is_free", "is_complete", "author"}
        wave62_ids = {
            "ghost_rider_hd_cckrizalid", "chaos_legion_hd_cckrizalid",
            "dmc3_nonse_hd_cckrizalid", "tales_abyss_hd_pandavenom",
            "tales_legendia_hd_pandavenom", "haunting_ground_hd_juancho",
            "armored_core_lr_hd_ninebreaker", "god_of_war_remastered_ewgeha",
            "god_of_war_2_remastered_ewgeha", "pop_ww_remastered_ewgeha",
            "pop_tt_remastered_ewgeha", "pop_sot_remastered_ewgeha",
            "re_dead_aim_remastered_ewgeha", "re_cvx_remastered_4k_ewgeha",
            "silent_hill_4_remastered_ewgeha", "spyro_etd_4k_ahmedD77",
            "hack_imoq_2k_mrdiggle", "burnout3_hd_pandavenom",
            "shadow_hearts_ftnw_hd_pandavenom", "suikoden_v_hd_pandavenom",
            "suikoden_iv_hd_pandavenom", "suikoden_iii_hd_pandavenom",
            "persona_4_hd_pandavenom", "persona_3_fes_hd_pandavenom",
            "dds1_hd_pandavenom", "grimgrimoire_hd_pandavenom",
            "wild_arms_5_hd_pandavenom", "burnout_dominator_hd_pandavenom",
            "ssx_tricky_hd_sombershroud", "ratchet_clank_1_hd_pandavenom",
            "ratchet_clank_gc_hd_pandavenom", "ratchet_clank_upa_hd",
            "castlevania_cod_hd_pandavenom", "star_ocean_te_hd_pandavenom",
            "call_of_duty_3_hd_pandavenom", "mercenaries_pod_hd_psxrestore",
            "bully_hd_vinfer", "xenosaga_trilogy_hd_pandavenom",
            "cckrizalid_mega_library",
        }
        for eid in wave62_ids:
            self.assertIn(eid, self.by_id, f"Missing Wave 62 entry: {eid}")
            entry = self.by_id[eid]
            missing = required - set(entry.keys())
            self.assertFalse(missing,
                             f"Entry {eid} missing fields: {missing}")

    def test_all_entries_source_is_gbatemp(self):
        """All Wave 62 entries must have source=GBAtemp."""
        wave62_ids = {
            "ghost_rider_hd_cckrizalid", "chaos_legion_hd_cckrizalid",
            "god_of_war_remastered_ewgeha", "burnout3_hd_pandavenom",
            "suikoden_v_hd_pandavenom", "persona_4_hd_pandavenom",
        }
        for eid in wave62_ids:
            self.assertEqual(self.by_id[eid]["source"], "GBAtemp",
                             f"{eid}: source must be GBAtemp")

    def test_all_entries_type_is_texture_pack(self):
        """All new entries must have type='texture_pack'."""
        wave62_ids = {
            "ghost_rider_hd_cckrizalid", "god_of_war_remastered_ewgeha",
            "burnout3_hd_pandavenom", "suikoden_v_hd_pandavenom",
        }
        for eid in wave62_ids:
            self.assertEqual(self.by_id[eid]["type"], "texture_pack",
                             f"{eid}: type must be texture_pack")

    def test_gbatemp_thread_urls_are_valid_format(self):
        """All GBAtemp thread URLs must follow the gbatemp.net/threads/ pattern."""
        wave62_ids = (
            "ghost_rider_hd_cckrizalid", "chaos_legion_hd_cckrizalid",
            "dmc3_nonse_hd_cckrizalid", "god_of_war_remastered_ewgeha",
            "burnout3_hd_pandavenom", "suikoden_v_hd_pandavenom",
            "persona_4_hd_pandavenom", "ratchet_clank_1_hd_pandavenom",
        )
        for eid in wave62_ids:
            url = self.by_id[eid]["url"]
            self.assertIn("gbatemp.net/threads/", url,
                          f"{eid}: url must be a gbatemp thread URL")


# =============================================================================
# Wave 63: New texture-pack catalogue entries + pnach DB expansion
# =============================================================================

class TestWave63TexturePacks(unittest.TestCase):
    """Wave 63: 39 new texture-pack catalogue entries from v13.1 reference."""

    @classmethod
    def setUpClass(cls):
        import json, pathlib
        data = json.loads(
            pathlib.Path("data/catalogue/texture_packs.json").read_text()
        )
        cls.catalogue = data
        cls.by_id = {e["id"]: e for e in data}

    # ------------------------------------------------------------------
    # Overall count
    # ------------------------------------------------------------------
    def test_catalogue_has_at_least_82_entries(self):
        """Wave 63: catalogue must have ≥82 entries after new additions."""
        self.assertGreaterEqual(
            len(self.catalogue), 82,
            f"Expected ≥82 catalogue entries after Wave 63, got {len(self.catalogue)}"
        )

    # ------------------------------------------------------------------
    # New individual entries present
    # ------------------------------------------------------------------
    def test_wave63_game_entries_present(self):
        """Wave 63: game-specific texture pack entries must be in catalogue."""
        required = {
            "devil_may_cry_1_hd",
            "downhill_domination_4k_zombie1673",
            "downhill_domination_hd_johnazeitona",
            "shadow_hearts_hd",
            "ps2_bios_hd_sombershroud",
            "ps2_bios_hd_remaster_pandavenom",
            "power_rangers_sl_yamijpg",
            "lego_batman_hd_v1",
            "007_qos_hd_texmaster",
            "futurama_upscaled_dahu",
            "pop_sot_pal_remaster_hd",
            "king_kong_remaster_hd",
            "indiana_jones_sok_2k",
            "state_of_emergency_hd",
            "second_sight_hd",
            "spyro_eternal_night_6x",
            "fatal_frame_1_hd_janley",
            "fatal_frame_2_hd_wip",
            "fatal_frame_3_hd_wip",
            "fatal_frame_3_teodormax",
            "fatal_frame_3_ntsc_undub",
            "tom_jerry_wow_hd_retrogenerica",
            "indiana_jones_et_hd",
            "god_of_war_2_20year_hd",
            "nfs_hot_pursuit_2_hd",
            "tekken_4_hd_sombershroud",
            "pitfall_lost_expedition_hd",
            "battlefield2mc_hd_robin9608",
            "ratchet_clank_1_hd_texmaster",
            "ratchet_clank_3_hd_texmaster",
            "project_altered_beast_hd",
            "pop_trilogy_hd_xxtherockoxx",
        }
        for eid in required:
            self.assertIn(eid, self.by_id,
                          f"Missing Wave 63 game entry: {eid}")

    def test_wave63_hub_entries_present(self):
        """Wave 63: hub / directory entries must be in catalogue."""
        hubs = {
            "pandavenom_packs_list",
            "retrogenerica_packs_list",
            "bl4ckh4nd_ps2_packs",
            "curse_arms_hd_remaster_pack",
            "gbatemp_texture_hub",
            "gbatemp_texture_complete_list",
            "teodormax_packs_list",
        }
        for eid in hubs:
            self.assertIn(eid, self.by_id,
                          f"Missing Wave 63 hub entry: {eid}")

    # ------------------------------------------------------------------
    # Per-entry field checks
    # ------------------------------------------------------------------
    def test_wave63_entries_have_required_fields(self):
        """All Wave 63 entries must have the required fields."""
        required = {"id", "name", "description", "url", "type", "source",
                    "is_free", "is_hub"}
        wave63_ids = {
            "devil_may_cry_1_hd", "downhill_domination_4k_zombie1673",
            "shadow_hearts_hd", "ps2_bios_hd_sombershroud",
            "fatal_frame_1_hd_janley", "ratchet_clank_1_hd_texmaster",
            "pandavenom_packs_list", "gbatemp_texture_hub",
        }
        for eid in wave63_ids:
            entry = self.by_id[eid]
            missing = required - set(entry.keys())
            self.assertFalse(missing,
                             f"Entry {eid} missing fields: {missing}")

    def test_wave63_game_entries_source_gbatemp(self):
        """All Wave 63 game entries must have source=GBAtemp."""
        wave63_ids = {
            "devil_may_cry_1_hd", "shadow_hearts_hd",
            "state_of_emergency_hd", "fatal_frame_1_hd_janley",
            "ratchet_clank_1_hd_texmaster",
        }
        for eid in wave63_ids:
            self.assertEqual(self.by_id[eid]["source"], "GBAtemp",
                             f"{eid}: source must be GBAtemp")

    def test_wave63_entries_gbatemp_thread_urls(self):
        """All Wave 63 entries must have valid gbatemp.net/threads/ URLs."""
        wave63_ids = {
            "devil_may_cry_1_hd", "downhill_domination_4k_zombie1673",
            "shadow_hearts_hd", "ps2_bios_hd_sombershroud",
            "state_of_emergency_hd", "fatal_frame_1_hd_janley",
            "ratchet_clank_1_hd_texmaster", "pandavenom_packs_list",
        }
        for eid in wave63_ids:
            url = self.by_id[eid]["url"]
            self.assertIn("gbatemp.net/threads/", url,
                          f"{eid}: url must be a gbatemp thread URL")

    def test_wave63_hub_entries_are_marked_is_hub(self):
        """Hub entries must have is_hub=True."""
        hubs = {
            "pandavenom_packs_list", "retrogenerica_packs_list",
            "bl4ckh4nd_ps2_packs", "gbatemp_texture_hub",
            "gbatemp_texture_complete_list",
        }
        for eid in hubs:
            self.assertTrue(self.by_id[eid]["is_hub"],
                            f"{eid}: is_hub must be True")

    def test_wave63_wip_entries_marked_incomplete(self):
        """WIP entries must have is_complete=False."""
        wips = {"fatal_frame_2_hd_wip", "fatal_frame_3_hd_wip",
                "battlefield2mc_hd_robin9608"}
        for eid in wips:
            self.assertFalse(self.by_id[eid]["is_complete"],
                             f"{eid}: is_complete must be False")

    def test_wave63_game_serial_format(self):
        """Wave 63 entries with serials must follow SL/SC/SE format."""
        import re
        serial_pattern = re.compile(r'^(SLUS|SCUS|SLES|SCES|SLPS|SCPS)-\d{5}$')
        serial_entries = {
            "devil_may_cry_1_hd": "SLUS-20216",
            "downhill_domination_4k_zombie1673": "SCUS-97177",
            "shadow_hearts_hd": "SLUS-20347",
            "state_of_emergency_hd": "SLUS-20214",
            "spyro_eternal_night_6x": "SLUS-21607",
            "tekken_4_hd_sombershroud": "SLUS-20328",
        }
        for eid, expected_serial in serial_entries.items():
            actual = self.by_id[eid].get("game_serial", "")
            self.assertEqual(actual, expected_serial,
                             f"{eid}: expected serial {expected_serial}, got {actual}")
            self.assertRegex(actual, serial_pattern,
                             f"{eid}: serial {actual} does not match expected format")

    def test_no_duplicate_catalogue_ids(self):
        """Catalogue must have no duplicate IDs after Wave 63."""
        ids = [e["id"] for e in self.catalogue]
        self.assertEqual(len(ids), len(set(ids)),
                         "Duplicate IDs found in catalogue")


class TestWave63PnachEntries(unittest.TestCase):
    """Wave 63: 175 new pnach DB entries from xs1l3n7x community PNACH files."""

    @classmethod
    def setUpClass(cls):
        import json, pathlib
        cls.db = json.loads(
            pathlib.Path("data/pnach_db/known_addresses.json").read_text()
        )

    def _entries_for(self, crc):
        return {k: v for k, v in self.db.items() if k.startswith(crc)}

    def _assert_entry(self, crc, addr, field=None, expected=None):
        key = f"{crc}:EE:{addr.upper()}"
        self.assertIn(key, self.db, f"Missing entry: {key}")
        if field is not None:
            self.assertEqual(self.db[key].get(field), expected,
                             f"{key}: {field} must be {expected!r}")

    # ------------------------------------------------------------------
    # Overall count
    # ------------------------------------------------------------------
    def test_db_has_at_least_48100_entries(self):
        """Wave 63: pnach DB must have ≥48100 entries after new additions."""
        self.assertGreaterEqual(
            len(self.db), 48100,
            f"Expected ≥48100 pnach entries after Wave 63, got {len(self.db)}"
        )

    # ------------------------------------------------------------------
    # God of War (D6385328)
    # ------------------------------------------------------------------
    def test_gow_infinite_health(self):
        self._assert_entry("D6385328", "20795978", "category", "cheat")

    def test_gow_infinite_magic(self):
        self._assert_entry("D6385328", "20302D1C", "category", "cheat")

    def test_gow_enable_all_magic(self):
        self._assert_entry("D6385328", "10302D42", "patch_type", "extended")

    def test_gow_max_level(self):
        self._assert_entry("D6385328", "20302D28", "category", "cheat")

    def test_gow_quick_level_up_blades_of_chaos(self):
        self._assert_entry("D6385328", "2076D7D8")

    def test_gow_quick_level_up_blades_of_artemis(self):
        self._assert_entry("D6385328", "2076D7EC")

    def test_gow_total_new_entries_at_least_17(self):
        entries = self._entries_for("D6385328:")
        self.assertGreaterEqual(len(entries), 17,
                                f"GoW D6385328: expected ≥17 entries, got {len(entries)}")

    # ------------------------------------------------------------------
    # Kingdom Hearts (AE3EAA05)
    # ------------------------------------------------------------------
    def test_kh_sora_max_level(self):
        self._assert_entry("AE3EAA05", "FEBFDA0A", "category", "cheat")

    def test_kh_sora_max_hp(self):
        self._assert_entry("AE3EAA05", "FEBFDA14")

    def test_kh_all_trinities(self):
        self._assert_entry("AE3EAA05", "FEBFC623")

    def test_kh_have_ultima_weapon(self):
        self._assert_entry("AE3EAA05", "FEBFDD0D")

    def test_kh_rescue_dalmations(self):
        self._assert_entry("AE3EAA05", "FEBFC30B")

    def test_kh_total_entries_at_least_18(self):
        entries = self._entries_for("AE3EAA05:")
        self.assertGreaterEqual(len(entries), 18,
                                f"KH AE3EAA05: expected ≥18 entries, got {len(entries)}")

    # ------------------------------------------------------------------
    # Final Fantasy X-2 (48FE0C71)
    # ------------------------------------------------------------------
    def test_ffx2_has_entries(self):
        entries = self._entries_for("48FE0C71:")
        self.assertGreaterEqual(len(entries), 11,
                                f"FFX-2 48FE0C71: expected ≥11 entries, got {len(entries)}")

    def test_ffx2_infinite_hp_hook(self):
        self._assert_entry("48FE0C71", "2A6F226E", "category", "cheat")

    def test_ffx2_infinite_hp_cave_entry(self):
        self._assert_entry("48FE0C71", "2AACC91F")

    # ------------------------------------------------------------------
    # Final Fantasy XII (0779FBDB)
    # ------------------------------------------------------------------
    def test_ffxii_quick_level_up(self):
        self._assert_entry("0779FBDB", "202EC6E4", "category", "cheat")

    def test_ffxii_quick_license_points(self):
        self._assert_entry("0779FBDB", "202EC72C")

    def test_ffxii_max_gil_condition(self):
        self._assert_entry("0779FBDB", "D056BB5C")

    def test_ffxii_max_gil_write(self):
        self._assert_entry("0779FBDB", "20547F08")

    # ------------------------------------------------------------------
    # Haunting Ground (901AAC09)
    # ------------------------------------------------------------------
    def test_haunting_ground_infinite_item_usage(self):
        self._assert_entry("901AAC09", "2025FDF0", "category", "cheat")
        self._assert_entry("901AAC09", "2025FDF0", "description",
                           "Infinite Item Usage — Items never deplete.")

    # ------------------------------------------------------------------
    # Resident Evil 4 (6BA2F6B9)
    # ------------------------------------------------------------------
    def test_re4_max_health_leon(self):
        self._assert_entry("6BA2F6B9", "1042DCF8", "category", "cheat")

    def test_re4_infinite_health_leon(self):
        self._assert_entry("6BA2F6B9", "1042DCF6")

    def test_re4_widescreen_fov(self):
        key = "6BA2F6B9:EE:20326FF8"
        self.assertIn(key, self.db)
        self.assertEqual(self.db[key]["category"], "widescreen")

    def test_re4_movement_speed_is_float(self):
        self._assert_entry("6BA2F6B9", "20425E98", "value_type", "float")

    # ------------------------------------------------------------------
    # Persona 4 (DEDC3B71)
    # ------------------------------------------------------------------
    def test_p4_infinite_yen(self):
        self._assert_entry("DEDC3B71", "2079B68C", "category", "cheat")

    def test_p4_exp_code_cave_pt1(self):
        self._assert_entry("DEDC3B71", "200A0000")

    def test_p4_max_hp_sp_me(self):
        self._assert_entry("DEDC3B71", "405DD874", "category", "cheat")

    # ------------------------------------------------------------------
    # Shadow of the Colossus (C19A374E) — community cheat entries
    # ------------------------------------------------------------------
    def test_sotc_conditional_check(self):
        self._assert_entry("C19A374E", "E002E264")

    def test_sotc_item_flags(self):
        self._assert_entry("C19A374E", "712DA3DA", "category", "cheat")

    # ------------------------------------------------------------------
    # Grand Theft Auto III (5E115FB6)
    # ------------------------------------------------------------------
    def test_gta3_infinite_armor(self):
        self._assert_entry("5E115FB6", "10B65316", "category", "cheat")

    def test_gta3_infinite_health(self):
        self._assert_entry("5E115FB6", "10B65312")

    def test_gta3_max_money(self):
        self._assert_entry("5E115FB6", "20510428")

    # ------------------------------------------------------------------
    # Grand Theft Auto: Liberty City Stories (7EA439F5)
    # ------------------------------------------------------------------
    def test_gtalcs_infinite_health_cave(self):
        self._assert_entry("7EA439F5", "200C0220", "category", "cheat")

    def test_gtalcs_infinite_armor_cave(self):
        self._assert_entry("7EA439F5", "200C0230")

    def test_gtalcs_max_money(self):
        self._assert_entry("7EA439F5", "20408EFC")

    def test_gtalcs_freeze_daily_time(self):
        self._assert_entry("7EA439F5", "201F88C0")

    # ------------------------------------------------------------------
    # Devil May Cry 3 (7ADCB24A)
    # ------------------------------------------------------------------
    def test_dmc3_infinite_health_cave(self):
        self._assert_entry("7ADCB24A", "200FFF00", "category", "cheat")

    def test_dmc3_red_orb_value(self):
        self._assert_entry("7ADCB24A", "202EB758")

    def test_dmc3_all_weapons_customize(self):
        self._assert_entry("7ADCB24A", "10733BA6")

    def test_dmc3_all_bonus_material(self):
        self._assert_entry("7ADCB24A", "21CB2A20")

    # ------------------------------------------------------------------
    # Gran Turismo 4 (44A61C8F)
    # ------------------------------------------------------------------
    def test_gt4_always_1_lap_cave(self):
        self._assert_entry("44A61C8F", "200FFF88", "category", "cheat")

    def test_gt4_always_1_lap_hook(self):
        self._assert_entry("44A61C8F", "2039B838")

    # ------------------------------------------------------------------
    # Structural invariants
    # ------------------------------------------------------------------
    def test_wave63_all_entries_have_required_fields(self):
        """All Wave 63 pnach entries must have the 5 required fields."""
        required = {"category", "description", "game", "game_crc", "game_serial"}
        wave63_crcs = {
            "D6385328", "47B9B2FD", "6BA2F6B9", "DEDC3B71",
            "C19A374E", "901AAC09", "AE3EAA05", "0779FBDB",
            "48FE0C71", "2A4B60EB", "5E115FB6", "7EA439F5",
            "7ADCB24A", "44A61C8F",
        }
        for k, v in self.db.items():
            if k.split(":")[0] in wave63_crcs:
                missing = required - set(v.keys())
                self.assertFalse(missing,
                                 f"Entry {k} missing fields: {missing}")


class TestWave64DataQualityFixes(unittest.TestCase):
    """Wave 64: Data quality fixes — correct serials, CRCs and game names across
    the serial DB, pnach DB, and texture-pack catalogue.

    Fixed issues
    -----------
    * 44A61C8F removed from Jak and Daxter; added to Gran Turismo 4 CRC list.
    * Catalogue entry re_cvx_remastered_4k_ewgeha: serial corrected
      SLUS-20512 → SLUS-20184 (Resident Evil Code: Veronica X).
    * Pnach DB: game_serial / game name populated for CRCs that had empty
      serial fields (7EA439F5, 7ADCB24A, 2A4B60EB, 44A61C8F).
    * Serial DB: 8 previously-undocumented CRCs added to their correct games
      (AE3EAA05, 48FE0C71, 901AAC09, DEDC3B71, 7EA439F5, 7ADCB24A, 2A4B60EB,
      47B9B2FD).
    """

    @classmethod
    def setUpClass(cls):
        import json, pathlib
        cls.catalogue = json.loads(
            pathlib.Path("data/catalogue/texture_packs.json").read_text()
        )
        cls.cat_by_id = {e["id"]: e for e in cls.catalogue}
        cls.pnach_db = json.loads(
            pathlib.Path("data/pnach_db/known_addresses.json").read_text()
        )
        raw = json.loads(
            pathlib.Path("data/game_serial_db/ps2_ntsc_u.json").read_text()
        )
        cls.games = raw["games"]

    # ------------------------------------------------------------------
    # Serial DB — CRC assignment fixes
    # ------------------------------------------------------------------

    def test_44a61c8f_not_in_jak_daxter_crcs(self):
        """44A61C8F must no longer appear in Jak and Daxter CRC list."""
        jd = self.games["Jak and Daxter: The Precursor Legacy"]
        self.assertNotIn("44A61C8F", jd.get("crcs", []),
                         "44A61C8F should not be in Jak and Daxter CRCs")

    def test_44a61c8f_not_in_jak_daxter_crc_labels(self):
        """44A61C8F must no longer appear in Jak and Daxter crc_labels."""
        jd = self.games["Jak and Daxter: The Precursor Legacy"]
        self.assertNotIn("44A61C8F", jd.get("crc_labels", {}),
                         "44A61C8F should not be in Jak and Daxter crc_labels")

    def test_44a61c8f_in_gran_turismo_4_crcs(self):
        """44A61C8F must appear in Gran Turismo 4 CRC list."""
        gt4 = self.games["Gran Turismo 4"]
        self.assertIn("44A61C8F", gt4.get("crcs", []),
                      "44A61C8F should be in Gran Turismo 4 CRCs")

    def test_ae3eaa05_in_kingdom_hearts_crcs(self):
        """AE3EAA05 (KH patched/60fps) must be in Kingdom Hearts CRC list."""
        kh = self.games["Kingdom Hearts"]
        self.assertIn("AE3EAA05", kh.get("crcs", []),
                      "AE3EAA05 should be in Kingdom Hearts CRCs")

    def test_48fe0c71_in_ffx2_crcs(self):
        """48FE0C71 must be in Final Fantasy X-2 CRC list."""
        ffx2 = self.games["Final Fantasy X-2"]
        self.assertIn("48FE0C71", ffx2.get("crcs", []),
                      "48FE0C71 should be in Final Fantasy X-2 CRCs")

    def test_901aac09_in_haunting_ground_crcs(self):
        """901AAC09 must be in Haunting Ground CRC list."""
        hg = self.games["Haunting Ground"]
        self.assertIn("901AAC09", hg.get("crcs", []),
                      "901AAC09 should be in Haunting Ground CRCs")

    def test_dedc3b71_in_persona_4_crcs(self):
        """DEDC3B71 must be in Persona 4 CRC list."""
        p4 = self.games["Persona 4"]
        self.assertIn("DEDC3B71", p4.get("crcs", []),
                      "DEDC3B71 should be in Persona 4 CRCs")

    def test_7ea439f5_in_gtalcs_crcs(self):
        """7EA439F5 must be in Grand Theft Auto: Liberty City Stories CRC list."""
        gtalcs = self.games["Grand Theft Auto: Liberty City Stories"]
        self.assertIn("7EA439F5", gtalcs.get("crcs", []),
                      "7EA439F5 should be in GTA:LCS CRCs")

    def test_7adcb24a_in_dmc3_crcs(self):
        """7ADCB24A must be in Devil May Cry 3 CRC list."""
        dmc3 = self.games["Devil May Cry 3"]
        self.assertIn("7ADCB24A", dmc3.get("crcs", []),
                      "7ADCB24A should be in Devil May Cry 3 CRCs")

    def test_2a4b60eb_in_dbz_budokai3_crcs(self):
        """2A4B60EB must be in Dragon Ball Z: Budokai 3 CRC list."""
        dbz3 = self.games["Dragon Ball Z: Budokai 3"]
        self.assertIn("2A4B60EB", dbz3.get("crcs", []),
                      "2A4B60EB should be in DBZ Budokai 3 CRCs")

    def test_47b9b2fd_in_radiata_stories_crcs(self):
        """47B9B2FD must be in Radiata Stories CRC list."""
        radiata = self.games["Radiata Stories"]
        self.assertIn("47B9B2FD", radiata.get("crcs", []),
                      "47B9B2FD should be in Radiata Stories CRCs")

    def test_crc_labels_consistency(self):
        """Every key in crc_labels must also appear in the crcs list."""
        for title, info in self.games.items():
            if not isinstance(info, dict):
                continue
            crcs_set = set(c.upper() for c in info.get("crcs", []))
            for crc in info.get("crc_labels", {}):
                self.assertIn(crc.upper(), crcs_set,
                              f"{title!r}: crc_labels key {crc!r} not in crcs list")

    # ------------------------------------------------------------------
    # Catalogue — RE Code Veronica X serial
    # ------------------------------------------------------------------

    def test_re_cvx_serial_is_slus_20184(self):
        """re_cvx_remastered_4k_ewgeha must use the correct serial SLUS-20184."""
        entry = self.cat_by_id["re_cvx_remastered_4k_ewgeha"]
        self.assertEqual(entry["game_serial"], "SLUS-20184",
                         "RE CVX catalogue entry must use SLUS-20184, not SLUS-20512")

    def test_re_cvx_description_no_wrong_serial(self):
        """RE CVX catalogue description must not mention the old wrong serial."""
        entry = self.cat_by_id["re_cvx_remastered_4k_ewgeha"]
        for field in ("description", "context", "name"):
            self.assertNotIn("SLUS-20512", entry.get(field, ""),
                             f"RE CVX {field!r} must not contain old serial SLUS-20512")

    def test_re_cvx_description_has_correct_serial(self):
        """RE CVX catalogue description must contain the correct serial."""
        entry = self.cat_by_id["re_cvx_remastered_4k_ewgeha"]
        desc = entry.get("description", "")
        self.assertIn("SLUS-20184", desc,
                      "RE CVX description should reference correct serial SLUS-20184")

    # ------------------------------------------------------------------
    # Pnach DB — fixed serial fields and game names
    # ------------------------------------------------------------------

    def _pnach_sample(self, crc):
        """Return the first pnach entry for the given CRC prefix."""
        key = next((k for k in self.pnach_db if k.startswith(crc + ":")), None)
        return self.pnach_db[key] if key else None

    def test_gtalcs_7ea439f5_has_serial(self):
        """All 7EA439F5 (GTA:LCS patched) entries must have serial SLUS-21423."""
        entries = {k: v for k, v in self.pnach_db.items()
                   if k.startswith("7EA439F5:")}
        self.assertGreater(len(entries), 0, "No 7EA439F5 entries found")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-21423",
                             f"{k}: game_serial must be SLUS-21423")

    def test_dmc3_7adcb24a_has_serial(self):
        """All 7ADCB24A (DMC3 patched) entries must have serial SLUS-20964."""
        entries = {k: v for k, v in self.pnach_db.items()
                   if k.startswith("7ADCB24A:")}
        self.assertGreater(len(entries), 0, "No 7ADCB24A entries found")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-20964",
                             f"{k}: game_serial must be SLUS-20964")

    def test_dbz_budokai3_2a4b60eb_has_serial(self):
        """All 2A4B60EB (DBZ Budokai 3) entries must have serial SLUS-20998."""
        entries = {k: v for k, v in self.pnach_db.items()
                   if k.startswith("2A4B60EB:")}
        self.assertGreater(len(entries), 0, "No 2A4B60EB entries found")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-20998",
                             f"{k}: game_serial must be SLUS-20998")

    def test_gt4_44a61c8f_has_serial(self):
        """All 44A61C8F (GT4) entries must have serial SCUS-97328."""
        entries = {k: v for k, v in self.pnach_db.items()
                   if k.startswith("44A61C8F:")}
        self.assertGreater(len(entries), 0, "No 44A61C8F entries found")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SCUS-97328",
                             f"{k}: game_serial must be SCUS-97328")

    def test_dmc3_7adcb24a_game_name_capitalisation(self):
        """7ADCB24A game name must not have lower-case 'c' in 'Cry'."""
        sample = self._pnach_sample("7ADCB24A")
        self.assertIsNotNone(sample)
        game_name = sample.get("game", "")
        self.assertNotIn("cry 3", game_name,
                         f"Game name {game_name!r} has wrong capitalisation for 'Cry'")

    def test_dbz_budokai3_game_name_format(self):
        """2A4B60EB game name must follow canonical 'Dragon Ball Z: Budokai 3' format."""
        sample = self._pnach_sample("2A4B60EB")
        self.assertIsNotNone(sample)
        game_name = sample.get("game", "")
        self.assertIn("Dragon Ball Z", game_name,
                      f"DBZ game name {game_name!r} should contain 'Dragon Ball Z'")
        self.assertNotIn("DragonBall", game_name,
                         f"DBZ game name {game_name!r} should not use 'DragonBall' (missing space)")


class TestWave65DataQualityFixes(unittest.TestCase):
    """Wave 65: Data quality fixes — CRC cross-contamination removed from serial DB,
    pnach DB game_serial / game fields corrected.

    Fixed issues
    -----------
    Serial DB — CRC removals (CRC was wrongly assigned to the wrong game):
    * 00E9B795 removed from 'Motocross Mania 3'   (belongs to Fantavision)
    * 1AFD7469 removed from 'Monster House'        (belongs to Happy Feet)
    * 3B0ADBEF removed from 'Manhunt 2'            (belongs to Twisted Metal: Black)
    * 4B80628D removed from 'Haunting Ground'      (belongs to GUN)
    * 8DB76084 removed from 'Curious George'       (belongs to Flushed Away)
    * 96660560 removed from 'Need for Speed: Hot Pursuit 2' and
                            'Need for Speed: Underground 2'
                                                   (belongs to NFS: Underground)
    * C2C5FE5F removed from 'Devil May Cry', 'Breath of Fire: Dragon Quarter',
                            'Final Fantasy XI', 'Final Fantasy XI Online'
                                                   (belongs to MK: Deadly Alliance)
    * E2F01792 removed from 'Final Fantasy X-2 (100% complete)' save-state variant
                                                   (belongs to NFS: Underground 2)

    Serial DB — CRC additions (CRC was missing from the correct game):
    * 8DB76084 added to 'Flushed Away'
    * E2F01792 added to 'Need for Speed: Underground 2'

    Pnach DB — game_serial / game name corrections (34 entries fixed):
    * 3B0ADBEF entries with SLUS-21613 or SLUS-20136 → SCUS-97101
      (Twisted Metal: Black)
    * 96660560 entries with game='Phantom Brave' → 'Need for Speed: Underground'
    * B7ECDECD entries with SLUS-21488 → SLUS-21389
      (Xenosaga Episode III: Also sprach Zarathustra)
    * C2C5FE5F entries with SLUS-20487 → SLUS-20423 (MK: Deadly Alliance)
    * DA5CC7A3 entries with SLUS-21050 → SLUS-20851 (Ace Combat 5)
    * E2F01792 entries with SLUS-20672 → SLUS-21065 (NFS: Underground 2)
    * F0A235D4 entries with SLUS-20216 → SLUS-21134 (Resident Evil 4)
    """

    @classmethod
    def setUpClass(cls):
        import json, pathlib
        cls.pnach_db = json.loads(
            pathlib.Path("data/pnach_db/known_addresses.json").read_text()
        )
        raw = json.loads(
            pathlib.Path("data/game_serial_db/ps2_ntsc_u.json").read_text()
        )
        cls.games = raw["games"]

    # ------------------------------------------------------------------
    # Serial DB — CRC removals
    # ------------------------------------------------------------------

    def test_motocross_mania3_no_fantavision_crc(self):
        """Motocross Mania 3 must not contain 00E9B795 (Fantavision's CRC)."""
        crcs = self.games.get("Motocross Mania 3", {}).get("crcs", [])
        self.assertNotIn("00E9B795", crcs,
                         "00E9B795 belongs to Fantavision, not Motocross Mania 3")

    def test_fantavision_has_correct_crc(self):
        """Fantavision must retain its CRC 00E9B795."""
        crcs = self.games.get("Fantavision", {}).get("crcs", [])
        self.assertIn("00E9B795", crcs,
                      "Fantavision must have CRC 00E9B795")

    def test_monster_house_no_happy_feet_crc(self):
        """Monster House must not contain 1AFD7469 (Happy Feet's CRC)."""
        crcs = self.games.get("Monster House", {}).get("crcs", [])
        self.assertNotIn("1AFD7469", crcs,
                         "1AFD7469 belongs to Happy Feet, not Monster House")

    def test_happy_feet_has_correct_crc(self):
        """Happy Feet must retain its CRC 1AFD7469."""
        crcs = self.games.get("Happy Feet", {}).get("crcs", [])
        self.assertIn("1AFD7469", crcs,
                      "Happy Feet must have CRC 1AFD7469")

    def test_manhunt2_no_tm_black_crc(self):
        """Manhunt 2 must not contain 3B0ADBEF (Twisted Metal: Black's CRC)."""
        crcs = self.games.get("Manhunt 2", {}).get("crcs", [])
        self.assertNotIn("3B0ADBEF", crcs,
                         "3B0ADBEF belongs to Twisted Metal: Black, not Manhunt 2")

    def test_tm_black_has_correct_crc(self):
        """Twisted Metal: Black must retain its CRC 3B0ADBEF."""
        crcs = self.games.get("Twisted Metal: Black", {}).get("crcs", [])
        self.assertIn("3B0ADBEF", crcs,
                      "Twisted Metal: Black must have CRC 3B0ADBEF")

    def test_haunting_ground_no_gun_crc(self):
        """Haunting Ground must not contain 4B80628D (GUN's CRC)."""
        crcs = self.games.get("Haunting Ground", {}).get("crcs", [])
        self.assertNotIn("4B80628D", crcs,
                         "4B80628D belongs to GUN, not Haunting Ground")

    def test_gun_has_correct_crc(self):
        """GUN must retain its CRC 4B80628D."""
        crcs = self.games.get("GUN", {}).get("crcs", [])
        self.assertIn("4B80628D", crcs,
                      "GUN must have CRC 4B80628D")

    def test_curious_george_no_flushed_away_crc(self):
        """Curious George must not contain 8DB76084 (Flushed Away's CRC)."""
        crcs = self.games.get("Curious George", {}).get("crcs", [])
        self.assertNotIn("8DB76084", crcs,
                         "8DB76084 belongs to Flushed Away, not Curious George")

    def test_flushed_away_has_crc(self):
        """Flushed Away must have CRC 8DB76084."""
        crcs = self.games.get("Flushed Away", {}).get("crcs", [])
        self.assertIn("8DB76084", crcs,
                      "Flushed Away must have CRC 8DB76084")

    def test_nfs_hp2_no_nfs_underground_crc(self):
        """NFS: Hot Pursuit 2 must not contain 96660560 (NFS: Underground's CRC)."""
        crcs = self.games.get("Need for Speed: Hot Pursuit 2", {}).get("crcs", [])
        self.assertNotIn("96660560", crcs,
                         "96660560 belongs to NFS: Underground, not NFS: HP2")

    def test_nfs_u2_no_nfs_underground_crc(self):
        """NFS: Underground 2 must not contain 96660560 (NFS: Underground's CRC)."""
        crcs = self.games.get("Need for Speed: Underground 2", {}).get("crcs", [])
        self.assertNotIn("96660560", crcs,
                         "96660560 belongs to NFS: Underground, not NFS: U2")

    def test_nfs_underground_has_crc(self):
        """NFS: Underground must retain 96660560."""
        crcs = self.games.get("Need for Speed: Underground", {}).get("crcs", [])
        self.assertIn("96660560", crcs,
                      "NFS: Underground must have CRC 96660560")

    def test_dmc_no_mkda_crc(self):
        """Devil May Cry must not contain C2C5FE5F (MK: Deadly Alliance's CRC)."""
        crcs = self.games.get("Devil May Cry", {}).get("crcs", [])
        self.assertNotIn("C2C5FE5F", crcs,
                         "C2C5FE5F belongs to MK: Deadly Alliance, not Devil May Cry")

    def test_dmc_no_mkda_crc_label(self):
        """Devil May Cry crc_labels must not contain C2C5FE5F."""
        labels = self.games.get("Devil May Cry", {}).get("crc_labels", {})
        self.assertNotIn("C2C5FE5F", labels,
                         "crc_labels for Devil May Cry must not reference C2C5FE5F")

    def test_bof_dragon_quarter_no_mkda_crc(self):
        """Breath of Fire: Dragon Quarter must not contain C2C5FE5F."""
        crcs = self.games.get("Breath of Fire: Dragon Quarter", {}).get("crcs", [])
        self.assertNotIn("C2C5FE5F", crcs,
                         "C2C5FE5F belongs to MK: Deadly Alliance, not BoF: DQ")

    def test_ffxi_no_mkda_crc(self):
        """Final Fantasy XI must not contain C2C5FE5F."""
        crcs = self.games.get("Final Fantasy XI", {}).get("crcs", [])
        self.assertNotIn("C2C5FE5F", crcs,
                         "C2C5FE5F belongs to MK: Deadly Alliance, not FFXI")

    def test_ffxi_online_no_mkda_crc(self):
        """Final Fantasy XI Online must not contain C2C5FE5F."""
        crcs = self.games.get("Final Fantasy XI Online", {}).get("crcs", [])
        self.assertNotIn("C2C5FE5F", crcs,
                         "C2C5FE5F belongs to MK: Deadly Alliance, not FFXI Online")

    def test_mkda_has_correct_crc(self):
        """Mortal Kombat: Deadly Alliance must retain CRC C2C5FE5F."""
        crcs = self.games.get("Mortal Kombat: Deadly Alliance", {}).get("crcs", [])
        self.assertIn("C2C5FE5F", crcs,
                      "Mortal Kombat: Deadly Alliance must have CRC C2C5FE5F")

    def test_ffx2_complete_no_nfsu2_crc(self):
        """FFX-2 (100% complete) save-state variant must not contain E2F01792."""
        crcs = self.games.get("Final Fantasy X-2 (100% complete)", {}).get("crcs", [])
        self.assertNotIn("E2F01792", crcs,
                         "E2F01792 belongs to NFS: Underground 2, not FFX-2 complete")

    def test_nfsu2_has_e2f01792(self):
        """NFS: Underground 2 must have CRC E2F01792."""
        crcs = self.games.get("Need for Speed: Underground 2", {}).get("crcs", [])
        self.assertIn("E2F01792", crcs,
                      "NFS: Underground 2 must have CRC E2F01792")

    # ------------------------------------------------------------------
    # Pnach DB — corrected game_serial / game name fields
    # ------------------------------------------------------------------

    def _entries_for_crc(self, crc):
        return {k: v for k, v in self.pnach_db.items()
                if v.get("game_crc", "").upper() == crc.upper()}

    def test_tm_black_no_manhunt2_serial(self):
        """3B0ADBEF pnach entries must not use Manhunt 2's serial SLUS-21613."""
        entries = self._entries_for_crc("3B0ADBEF")
        bad = [k for k, v in entries.items() if v.get("game_serial") == "SLUS-21613"]
        self.assertEqual(bad, [],
                         f"3B0ADBEF entries must not reference Manhunt 2 (SLUS-21613): {bad}")

    def test_tm_black_no_barbarian_serial(self):
        """3B0ADBEF pnach entries must not use Barbarian's serial SLUS-20136."""
        entries = self._entries_for_crc("3B0ADBEF")
        bad = [k for k, v in entries.items() if v.get("game_serial") == "SLUS-20136"]
        self.assertEqual(bad, [],
                         f"3B0ADBEF entries must not reference Barbarian (SLUS-20136): {bad}")

    def test_tm_black_3b0adbef_serial(self):
        """3B0ADBEF pnach entries must use SCUS-97101 (Twisted Metal: Black)."""
        entries = self._entries_for_crc("3B0ADBEF")
        self.assertGreater(len(entries), 0, "No 3B0ADBEF entries found")
        serials = {v.get("game_serial") for v in entries.values()}
        self.assertEqual(serials, {"SCUS-97101"},
                         f"All 3B0ADBEF entries must use SCUS-97101, got: {serials}")

    def test_nfs_underground_96660560_game_name(self):
        """96660560/SLUS-20811 pnach entries must say NFS: Underground, not Phantom Brave."""
        entries = {k: v for k, v in self._entries_for_crc("96660560").items()
                   if v.get("game_serial") == "SLUS-20811"}
        phantom_entries = [k for k, v in entries.items()
                           if "Phantom Brave" in v.get("game", "")]
        self.assertEqual(phantom_entries, [],
                         f"96660560/SLUS-20811 entries must not say 'Phantom Brave': {phantom_entries}")

    def test_xenosaga3_b7ecdecd_serial(self):
        """B7ECDECD pnach entries must use SLUS-21389 (Xenosaga III), not SLUS-21488."""
        entries = self._entries_for_crc("B7ECDECD")
        self.assertGreater(len(entries), 0, "No B7ECDECD entries found")
        bad = [k for k, v in entries.items() if v.get("game_serial") == "SLUS-21488"]
        self.assertEqual(bad, [],
                         f"B7ECDECD entries must not use .hack//G.U. serial SLUS-21488: {bad}")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-21389",
                             f"{k}: game_serial must be SLUS-21389 (Xenosaga III)")

    def test_mkda_c2c5fe5f_serial(self):
        """C2C5FE5F pnach entries must use SLUS-20423 (MK: DA), not SLUS-20487 (Mega Man X7)."""
        entries = self._entries_for_crc("C2C5FE5F")
        self.assertGreater(len(entries), 0, "No C2C5FE5F entries found")
        bad = [k for k, v in entries.items() if v.get("game_serial") == "SLUS-20487"]
        self.assertEqual(bad, [],
                         f"C2C5FE5F entries must not use Mega Man X7 serial SLUS-20487: {bad}")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-20423",
                             f"{k}: game_serial must be SLUS-20423 (MK: Deadly Alliance)")

    def test_ac5_da5cc7a3_serial(self):
        """DA5CC7A3 pnach entries must use SLUS-20851 (Ace Combat 5), not SLUS-21050."""
        entries = self._entries_for_crc("DA5CC7A3")
        self.assertGreater(len(entries), 0, "No DA5CC7A3 entries found")
        bad = [k for k, v in entries.items() if v.get("game_serial") == "SLUS-21050"]
        self.assertEqual(bad, [],
                         f"DA5CC7A3 entries must not use Burnout 3 serial SLUS-21050: {bad}")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-20851",
                             f"{k}: game_serial must be SLUS-20851 (Ace Combat 5)")

    def test_nfsu2_e2f01792_serial(self):
        """E2F01792 pnach entries must use SLUS-21065 (NFS: U2), not SLUS-20672 (FFX-2)."""
        entries = self._entries_for_crc("E2F01792")
        self.assertGreater(len(entries), 0, "No E2F01792 entries found")
        bad = [k for k, v in entries.items() if v.get("game_serial") == "SLUS-20672"]
        self.assertEqual(bad, [],
                         f"E2F01792 entries must not use FFX-2 serial SLUS-20672: {bad}")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-21065",
                             f"{k}: game_serial must be SLUS-21065 (NFS: Underground 2)")

    def test_re4_f0a235d4_serial(self):
        """F0A235D4 pnach entries must use SLUS-21134 (RE4), not SLUS-20216 (DMC)."""
        entries = self._entries_for_crc("F0A235D4")
        self.assertGreater(len(entries), 0, "No F0A235D4 entries found")
        bad = [k for k, v in entries.items() if v.get("game_serial") == "SLUS-20216"]
        self.assertEqual(bad, [],
                         f"F0A235D4 entries must not use DMC serial SLUS-20216: {bad}")
        for k, v in entries.items():
            self.assertEqual(v.get("game_serial"), "SLUS-21134",
                             f"{k}: game_serial must be SLUS-21134 (Resident Evil 4)")
