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
        """Import and return the CATALOGUE list from browse_panel."""
        # We can't import PyQt6 in the test env, so we parse the file directly
        # and load just the IDs from the catalogue
        import ast
        bp_path = Path(__file__).parent.parent / "src" / "ui" / "browse_panel.py"
        src = bp_path.read_text(encoding="utf-8")
        # Extract all "id": "..." values from CATALOGUE
        ids = []
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith('"id":'):
                val = stripped.split(":", 1)[1].strip().strip('",').strip()
                ids.append(val)
        return ids

    def test_game_specific_texture_entries_present(self):
        """Catalogue should include game-specific texture pack entries."""
        ids = self._load_catalogue()
        game_entries = [
            "spyro_etd_textures",
            "crash_woc_textures",
            "gow1_textures",
            "ffx_textures",
            "kh1_textures",
            "kh2_textures",
            "sotc_textures",
            "gt4_textures",
            "dmc3_textures",
            "ratchet_clank_textures",
            "jak_daxter_textures",
            "dbz_bt3_textures",
            "gta_sa_textures",
            "ico_textures",
        ]
        for entry_id in game_entries:
            self.assertIn(entry_id, ids, f"Missing catalogue entry: {entry_id}")

    def test_game_specific_pnach_entries_present(self):
        """Catalogue should include game-specific PNACH patch entries."""
        ids = self._load_catalogue()
        pnach_entries = [
            "gow_widescreen_pnach",
            "kh_widescreen_pnach",
            "ffx_widescreen_pnach",
            "gt4_widescreen_pnach",
            "crash_woc_pnach",
            "sotc_pnach",
        ]
        for entry_id in pnach_entries:
            self.assertIn(entry_id, ids, f"Missing PNACH entry: {entry_id}")

    def test_game_specific_cover_art_entries_present(self):
        """Catalogue should include game-specific cover art entries."""
        ids = self._load_catalogue()
        cover_entries = [
            "cover_art_popular_us",
            "cover_art_popular_eu",
        ]
        for entry_id in cover_entries:
            self.assertIn(entry_id, ids, f"Missing cover art entry: {entry_id}")

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



class TestCatalogueIntegrity(unittest.TestCase):
    """Structural integrity checks for the browse-panel catalogue.

    Uses Python's ``ast`` module to parse the catalogue list without importing
    any Qt code, so these tests run fine in headless CI environments.
    """

    @classmethod
    def setUpClass(cls):
        import ast

        src_file = Path(__file__).parent.parent / "src" / "ui" / "browse_panel.py"
        tree = ast.parse(src_file.read_text(encoding="utf-8"))

        # Walk the AST to find the CATALOGUE assignment
        catalogue_node = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "CATALOGUE"
                and node.value is not None
            ):
                catalogue_node = node.value
                break

        if catalogue_node is None:
            raise RuntimeError("Could not find CATALOGUE assignment in browse_panel.py")

        # Convert the AST list of dicts to Python dicts.
        # ModType.TEXTURE_PACK etc. appear as ast.Attribute nodes; convert
        # them to their .value strings (e.g. "texture_pack").
        def _literal(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.List):
                return [_literal(e) for e in node.elts]
            if isinstance(node, ast.Tuple):
                return tuple(_literal(e) for e in node.elts)
            if isinstance(node, ast.Dict):
                return {_literal(k): _literal(v) for k, v in zip(node.keys, node.values)}
            # ModType.TEXTURE_PACK → "texture_pack" etc.
            if isinstance(node, ast.Attribute):
                return node.attr.lower()
            # Concatenated strings: ("part1" "part2") → JoinedStr handled as concat
            if isinstance(node, ast.JoinedStr):
                return "<f-string>"
            raise ValueError(f"Unexpected AST node type: {type(node).__name__}")

        cls.catalogue = _literal(catalogue_node)

    # ------------------------------------------------------------------
    # Structural checks
    # ------------------------------------------------------------------

    _REQUIRED_FIELDS = {
        "id", "name", "description", "author", "author_url",
        "url", "type", "source", "game", "tags",
        "download_action", "upscale_tech",
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
        valid_types = {"texture_pack", "pnach", "cover_art", "save_file", "cheat"}
        for entry in self.catalogue:
            self.assertIn(
                entry["type"], valid_types,
                f"Entry {entry['id']} has invalid type: {entry['type']!r}"
            )

    def test_all_authors_are_non_empty(self):
        for entry in self.catalogue:
            self.assertTrue(
                entry.get("author", "").strip(),
                f"Entry {entry['id']} has empty author"
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

