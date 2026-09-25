#!/usr/bin/env python3
"""v6.2 tests: the exe-ready packaging kit.

Covers:
- nova_localmodels.app_local_dir() frozen anchoring (the user's own
  change: local/ must sit NEXT TO THE EXE, never inside _MEIPASS)
- web_server._resolve_web_dir() bundled-first / exe-side fallback
- exe_entry.py no-arg double-click -> serve dispatch
- NovaAssistant.spec sanity (datas, per-exe console flags, icon)
- build_assets/NovaAssistant.ico structure (ICO header + PNG payload)
- build_exe.bat CRLF + ASCII convention
- make_icon.py grid discipline (16x16)
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))


class TestOwnModelsRootFrozen(unittest.TestCase):
    """The user's change: frozen exe -> local/ next to sys.executable."""

    def test_unfrozen_anchors_next_to_file(self):
        import nova_localmodels
        root = nova_localmodels.app_local_dir()
        self.assertEqual(root.parent, APP)
        self.assertEqual(root.name, "local")

    def test_frozen_anchors_next_to_exe(self):
        import nova_localmodels
        with tempfile.TemporaryDirectory() as td:
            fake_exe = Path(td) / "dist" / "NovaAssistant" / "NovaAssistant.exe"
            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", str(fake_exe)):
                root = nova_localmodels.app_local_dir()
        self.assertEqual(root, fake_exe.parent / "local")

    def test_frozen_not_next_to_source(self):
        # the whole point: in a bundled exe local/ must NOT land in _MEIPASS
        import nova_localmodels
        with tempfile.TemporaryDirectory() as td:
            fake_exe = Path(td) / "NovaAssistant.exe"
            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", str(fake_exe)):
                root = nova_localmodels.app_local_dir()
        self.assertNotEqual(root.parent, APP)


class TestResolveWebDir(unittest.TestCase):
    """Bundled web/ wins; exe-side web/ is the frozen fallback."""

    def test_normal_case_bundled(self):
        import web_server
        self.assertEqual(web_server._resolve_web_dir(APP), APP / "web")
        self.assertTrue((web_server.WEB_DIR / "index.html").is_file())

    def test_unfrozen_missing_web_returns_bundled_path_anyway(self):
        import web_server
        with tempfile.TemporaryDirectory() as td:
            d = web_server._resolve_web_dir(Path(td))
            self.assertEqual(d, Path(td) / "web")  # honest: still the default

    def test_frozen_fallback_to_exe_side(self):
        import web_server
        # app_dir points at a bare (bundled-but-data-less) dir; the real
        # web/ folder sits next to the fake executable -> must win
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "_MEIPASS"
            empty.mkdir()
            exe_dir = Path(td) / "dist"
            (exe_dir / "web").mkdir(parents=True)
            (exe_dir / "web" / "index.html").write_text("<html></html>",
                                                        encoding="utf-8")
            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable",
                                   str(exe_dir / "NovaAssistant.exe")):
                d = web_server._resolve_web_dir(empty)
            self.assertEqual(d, exe_dir / "web")

    def test_frozen_no_fallback_available_keeps_bundled_path(self):
        import web_server
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "_MEIPASS"
            empty.mkdir()
            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable",
                                   str(Path(td) / "NovaAssistant.exe")):
                d = web_server._resolve_web_dir(empty)
            self.assertEqual(d, empty / "web")  # honest default, no crash


class TestExeEntry(unittest.TestCase):
    """Double-click (no args) must turn into `serve`."""

    def test_no_args_becomes_serve(self):
        import exe_entry
        import nova_assistant
        captured = {}

        def fake_main():
            captured["argv"] = list(sys.argv)

        with mock.patch.object(sys, "argv", ["NovaAssistant.exe"]), \
             mock.patch.object(nova_assistant, "main", fake_main):
            exe_entry.main()
        self.assertEqual(captured["argv"], ["NovaAssistant.exe", "serve"])

    def test_args_pass_through_untouched(self):
        import exe_entry
        import nova_assistant
        captured = {}

        def fake_main():
            captured["argv"] = list(sys.argv)

        with mock.patch.object(sys, "argv",
                               ["NovaAssistant.exe", "models"]), \
             mock.patch.object(nova_assistant, "main", fake_main):
            exe_entry.main()
        self.assertEqual(captured["argv"], ["NovaAssistant.exe", "models"])


class TestSpecAndAssets(unittest.TestCase):
    """The build kit files exist and say what they must say."""

    def setUp(self):
        self.spec = (APP / "NovaAssistant.spec").read_text(encoding="utf-8")

    def test_spec_bundles_web_data(self):
        self.assertIn("datas=", self.spec)
        self.assertIn('"web"', self.spec.split("datas=")[1].split("]")[0])

    def test_spec_console_flags(self):
        # windowed dashboard + console terminal agent, in ONE dist
        self.assertIn("console=False", self.spec)
        self.assertIn("console=True", self.spec)
        self.assertLess(self.spec.index("NovaAssistant"),
                        self.spec.index("console=False"))
        # v6.7: the console exe builds from novacode_entry.py (routes
        # 'serve'/module words correctly; nova.py alone has no subcommands)
        self.assertLess(self.spec.index('"novacode_entry.py"'),
                        self.spec.index("console=True"))

    def test_spec_icon_optional(self):
        self.assertIn("ICON.is_file()", self.spec)

    def test_spec_excludes_tests_from_bundle(self):
        self.assertIn("excludes=", self.spec)

    def test_ico_structure(self):
        ico = APP / "build_assets" / "NovaAssistant.ico"
        self.assertTrue(ico.is_file(), "run scripts/make_icon.py first")
        data = ico.read_bytes()
        res, typ, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((res, typ, count), (0, 1, 1))
        w, h, ncol, rsv, planes, bpp, size, off = struct.unpack(
            "<BBBBHHII", data[6:22])
        self.assertEqual((w or 256, h or 256), (256, 256))
        self.assertEqual(bpp, 32)
        self.assertEqual(off, 22)
        self.assertEqual(len(data), off + size)
        self.assertEqual(data[off:off + 8], b"\x89PNG\r\n\x1a\n")

    def test_bat_is_crlf_ascii(self):
        bat = APP / "build_exe.bat"
        self.assertTrue(bat.is_file())
        data = bat.read_bytes()
        data.decode("ascii")  # raises on non-ascii
        self.assertNotIn(b"\r\r\n", data)
        self.assertIn(b"\r\n", data)  # CRLF present

    def test_make_icon_grid_is_16x16(self):
        sys.path.insert(0, str(APP / "scripts"))
        try:
            import make_icon
            rows = make_icon.PIXELS.strip("\n").split("\n")
            self.assertEqual(len(rows), 16)
            for r in rows:
                self.assertEqual(len(r), 16)
            self.assertEqual(set("".join(rows)) - set("TVLGW"), set())
        finally:
            sys.path.pop(0)

    def test_exe_entry_compiles(self):
        import py_compile
        py_compile.compile(str(APP / "exe_entry.py"), doraise=True)
        py_compile.compile(str(APP / "scripts" / "make_icon.py"), doraise=True)


class TestVersionBump(unittest.TestCase):
    def test_version_is_6_2_1(self):
        import nova
        # 6.2.1 = the bug-fix & hardening pass over 6.2
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
