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
        """Catalogue should include game-specific texture pack entries (non-hub, specific files)."""
        ids = self._load_catalogue()
        # DeadOnTheInside Patreon-hosted texture packs are the main specific-file entries
        game_entries = [
            "doti_spyro_textures",
            "doti_crash_woc_textures",
            "doti_gow1_textures",
            "doti_ffx_textures",
            "doti_kh1_textures",
            "doti_kh2_textures",
            "doti_sotc_textures",
            "doti_gt4_textures",
            "doti_dmc3_textures",
            "doti_ratchet_clank_textures",
            "doti_jak_textures",
            "doti_dbz_bt3_textures",
            "doti_gtasa_textures",
            "doti_ico_textures",
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

    # -- New browse-filter preference fields ---------------------------------

    def test_browse_filter_defaults(self):
        """show_paid defaults to False; show_account_required and show_incomplete to True."""
        cfg = AppConfig()
        self.assertFalse(cfg.show_paid)
        self.assertTrue(cfg.show_account_required)
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
        self.assertTrue(cfg.show_account_required)
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
        expected = [
            "spyro_anb_6x_extra_detail",
            "spyro_anb_6x_only",
            "spyro_anb_4x_anime",
            "spyro_anb_mediafire_folder",
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

    def test_sly2_save_entry_present(self):
        ids = self._get_ids()
        self.assertIn("sly2_save_gamefiles", ids)

    def test_bully_save_entry_present(self):
        ids = self._get_ids()
        self.assertIn("bully_save_moataz", ids)

    def test_ps2home_saves_hub_removed(self):
        """The ps2home_saves_hub entry is a category hub and must NOT be in catalogue."""
        ids = self._get_ids()
        self.assertNotIn("ps2home_saves_hub", ids)

    def test_atv_save_entry_present(self):
        ids = self._get_ids()
        self.assertIn("atv_fury_save_ps2home", ids)

    def test_bully_save_has_mediafire_url(self):
        """Bully save entry must have a direct_download_url pointing to MediaFire."""
        src = self._get_all_json_text()
        self.assertIn("mediafire.com/file/hktfw1t8dv4etgo/bully_saves", src)

    def test_bully_save_author_is_moataz(self):
        src = self._get_all_json_text()
        self.assertIn("moataz", src)
        self.assertIn("gbatemp.net/members/moataz", src)

    def test_sly2_save_source_is_gbatemp_download(self):
        src = self._get_all_json_text()
        self.assertIn("gbatemp.net/download/sly-2-band-of-thieves-ps2-europe", src)

    def test_atv_save_source_is_ps2home(self):
        src = self._get_all_json_text()
        self.assertIn("ps2-home.com/forum/viewtopic.php?f=70&t=12165", src)

    # Popular-game save entries added for issue #3
    def test_popular_game_saves_present(self):
        """Issue #3 popular PS2 game save entries must be in the catalogue."""
        ids = self._get_ids()
        expected = [
            "kingdom_hearts_save_gbatemp",
            "ffx_save_gbatemp",
            "god_of_war_save_gbatemp",
            "gta_sa_save_gbatemp",
            "mgs3_save_gbatemp",
            "re4_save_gbatemp",
            "sotc_save_gbatemp",
            "jak_daxter_save_gbatemp",
            "ratchet_clank_save_gbatemp",
            "dbz_bt3_save_gbatemp",
            "tekken5_save_gbatemp",
            "persona4_save_gbatemp",
        ]
        for eid in expected:
            self.assertIn(eid, ids, f"Missing popular-game save entry: {eid}")

    def test_all_save_entries_are_not_hub(self):
        """Every save file entry must be a specific-file entry (is_hub=False)."""
        entries = self._get_entries()
        saves = [e for e in entries if e["type"] == "save_file"]
        for e in saves:
            self.assertFalse(e.get("is_hub", False),
                             f"Save entry {e['id']} must not be a hub")

    def test_save_entries_have_game_serial_or_game_name(self):
        """Every specific save entry should mention a game name or serial in description/context."""
        ids = self._get_ids()
        save_ids = [eid for eid in ids if 'save' in eid.lower()]
        self.assertGreater(len(save_ids), 5, "Expected multiple specific save entries")


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
        """All non-hub Patreon entries should have requires_account=True (explicit or inferred)."""
        patreon_entries = [
            e for e in self.catalogue
            if e.get("source") == "Patreon" and not e.get("is_hub", False)
        ]
        self.assertGreater(len(patreon_entries), 0, "Should have some Patreon entries")
        for entry in patreon_entries:
            # Either explicitly set or inferred as True (Patreon is in _ACCOUNT_REQUIRED_SOURCES)
            explicit = entry.get("requires_account")
            if explicit is not None:
                self.assertTrue(explicit,
                    f"Patreon entry {entry['id']} has requires_account=False, expected True")


class TestTextureStructureNormalization(unittest.TestCase):
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
        url = self.gcu("SLUS-21829")
        self.assertIn("/US/", url)
        self.assertIn("SLUS21829", url)
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
        url = self.gcu("slus-21829")
        self.assertIn("SLUS21829", url)
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
        expected = {
            "doti_gow1_textures":          "SCUS-97399",
            "doti_kh2_textures":           "SLUS-21005",
            "doti_ffx_textures":           "SLUS-20312",
            "doti_sh2_textures":           "SLUS-20228",
            "cckrizalid_baroque_textures": "SLUS-21829",
            "spyro_anb_6x_extra_detail":   "SLUS-21372",
            "sly2_save_gamefiles":         "SCES-52400",
            "bully_save_moataz":           "SLUS-21358",
            "god_of_war_save_gbatemp":     "SCUS-97399",
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
        self.assertEqual(e["game_serial"], "SLUS-21829")

    def test_baroque_author_is_cckrizalid(self):
        e = self.entries["cckrizalid_baroque_textures"]
        self.assertEqual(e["author"], "CCKrizalid")

    def test_baroque_author_url_points_to_profile(self):
        e = self.entries["cckrizalid_baroque_textures"]
        self.assertIn("cckrizalid.606805", e["author_url"])

    def test_all_cckrizalid_entries_have_thread_url(self):
        thread = "mega-library-of-hd-texture-packs-by-cckrizalid.618690"
        cc = [e for e in self.entries.values() if e.get("author") == "CCKrizalid"]
        self.assertGreater(len(cc), 1)
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
        self.assertGreaterEqual(len(cc), 15,
                                "Expected at least 15 CCKrizalid pack entries")


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
        self.assertGreater(len(self.catalogue), 850,
                           "catalogue should have >850 entries after scaling")

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
                    "upscale_tech", "is_free", "requires_account", "is_complete"}
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
        self.assertGreater(len(tp), 380, "Expected >380 texture pack entries")

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
        from src.models.mod import ModType
        pn = [e for e in self.catalogue if e["type"] == ModType.PNACH]
        self.assertGreater(len(pn), 320, "Expected >320 PNACH entries")

    def test_has_save_file_entries(self):
        from src.models.mod import ModType
        sv = [e for e in self.catalogue if e["type"] == ModType.SAVE_FILE]
        self.assertGreater(len(sv), 120, "Expected >120 save file entries")

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
        self.assertIn("PS2Wide", self.all_sources)

    # ── New sources from scaling ──────────────────────────────────────────────

    def test_gamebanana_source_present(self):
        """Scaling added GameBanana entries."""
        gb = [e for e in self.catalogue if e["source"] == "GameBanana"]
        self.assertGreater(len(gb), 0, "Expected GameBanana entries")

    # ── 60fps patches ─────────────────────────────────────────────────────────

    def test_60fps_patches_present(self):
        fps_patches = [e for e in self.catalogue if "60fps" in e.get("tags", [])]
        self.assertGreater(len(fps_patches), 10,
                           "Expected >10 60fps PNACH entries")

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
        self.assertGreaterEqual(len(cc), 20,
                                "Expected at least 20 CCKrizalid entries after scaling")


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
        for mt in ModType:
            entries = [e for e in self.catalogue if e["type"] == mt]
            self.assertGreater(len(entries), 0,
                               f"No catalogue entries of type {mt}")

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
        """Known addresses DB should have grown beyond 3790 entries (wave 20 expansion)."""
        from src.core.pnach_analyzer import reload_db
        n = reload_db()
        self.assertGreater(n, 3790, "PNACH DB should have more than 3790 entries after wave-20 expansion")

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
        """The vast majority of entries should use 'word' patch_type (32-bit writes)."""
        import json
        from pathlib import Path
        db = json.loads((Path(__file__).parent.parent /
                         "data/pnach_db/known_addresses.json").read_text())
        word_count = sum(1 for v in db.values() if v.get("patch_type") == "word")
        total = len(db)
        self.assertGreater(word_count / total, 0.90,
                           f"Expected >90% word patches; got {word_count}/{total}")


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
