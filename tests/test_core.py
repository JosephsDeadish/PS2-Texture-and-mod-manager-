"""Tests for PS2 Mod Manager core logic."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure src is importable
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.models.mod import AppConfig, ConflictInfo, ModInfo, ModStatus, ModType
from src.core.config_manager import detect_pcsx2_paths, load_config, save_config


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

    def test_detect_no_conflicts(self):
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


if __name__ == "__main__":
    unittest.main()
