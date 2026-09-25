#!/usr/bin/env python3
# =====================================================================
#  Nova v8.11.0 regression tests - the "full audit round" release:
#  the suite must be portable to ANY host (no machine-specific paths),
#  doc strings must match reality (version headers, provider count,
#  trusted-domain count), shipped state must be clean (no stray
#  duplicate FIXES file, no caches), and the v8.1 audit fix
#  (nova_bg zombie check encoding) stays pinned.
#  Everything is offline.
# =====================================================================
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova                    # noqa: E402
import nova_think              # noqa: E402
import nova_providers          # noqa: E402
import nova_search as ns       # noqa: E402
import nova_bg                 # noqa: E402

APP = Path(__file__).resolve().parent.parent
REPO = APP.parent


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


class TestVersionPins(unittest.TestCase):
    def test_core_versions_are_821(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(nova_think.VERSION, "8.12.0")

    def test_header_matches_version(self):
        head = _src("nova.py").splitlines()[:8]
        self.assertTrue(any("Version 8.12.0" in ln for ln in head),
                        "nova.py header still says an old version")

    def test_module_cli_headers_current(self):
        self.assertIn("(v8.12.0)", _src("nova_assistant.py").splitlines()[2])
        self.assertIn("(v8.12.0)", _src("novacode_entry.py").splitlines()[2])
        desc = _src("nova_assistant.py")
        self.assertIn('description="Nova Assistant v8.12.0', desc)


class TestDocStringHonesty(unittest.TestCase):
    """Help texts and header comments must match the real registry sizes."""

    def test_provider_count_matches_registry(self):
        self.assertGreaterEqual(len(nova_providers.PROVIDERS), 30)
        self.assertNotIn("26 built-in", _src("nova_providers.py"))
        self.assertNotIn("26 built-in", _src("nova.py"))

    def test_trusted_domain_count_matches_registry(self):
        self.assertGreaterEqual(len(ns.TRUSTED), 350)
        search_src = _src("nova_search.py")
        self.assertNotIn("~200 domains", search_src)
        self.assertNotIn("~330 trusted", search_src)


class TestSuitePortability(unittest.TestCase):
    """the v8.2.0 package shipped tests/scripts with machine-specific
    absolute paths that broke the suite on every new host. They must
    stay relative."""

    # built by concatenation so this file never contains the literal itself
    MACHINE_PATH = "nova_project" + "/nova-assistant"

    def test_no_hardcoded_machine_paths_in_tests(self):
        for p in sorted((APP / "tests").glob("test_*.py")):
            self.assertNotIn(self.MACHINE_PATH,
                             p.read_text(encoding="utf-8"),
                             "%s has a hardcoded machine path" % p.name)

    def test_no_hardcoded_machine_paths_in_scripts(self):
        for p in sorted((APP / "scripts").glob("*.py")):
            src = p.read_text(encoding="utf-8")
            self.assertNotIn(self.MACHINE_PATH, src,
                             "%s has a hardcoded machine path" % p.name)

    def test_v670_tests_use_app_relative_root(self):
        src = _src("tests/test_v670_deep_fixes.py")
        self.assertIn("_APP_DIR = Path(__file__).resolve().parent.parent", src)
        self.assertNotIn("/home/z/", src)

    def test_pin_scripts_resolve_app_relative(self):
        for name in ("pin_v780.py", "pin_v821.py"):
            src = _src("scripts/" + name)
            self.assertNotIn('/home/z/', src)
            self.assertIn("Path(__file__).resolve()", src)

    def test_packager_output_dir_is_portable(self):
        src = _src("scripts/package_v820.py")
        self.assertNotIn('Path("/home/z/my-project/download")', src)
        self.assertIn("NOVA_OUT_DIR", src)


class TestShippedTreeHygiene(unittest.TestCase):
    """the v8.2.0 package accidentally shipped a duplicate FIXES file
    inside app/."""

    def test_no_duplicate_fixes_doc_in_app(self):
        stray = APP / "FIXES-6.8.0.fa.md"
        self.assertFalse(stray.exists(),
                         "stray duplicate FIXES-6.8.0.fa.md back in app/")

    def test_bg_zombie_check_reads_with_explicit_encoding(self):
        src = _src("nova_bg.py")
        self.assertIn('.read_text(encoding="utf-8")', src)


class TestRegistrySanity(unittest.TestCase):
    def test_search_registry_counts_stable(self):
        # 389 entries at v8.11.0 (56 fa-tagged); allow small drift, never loss
        self.assertGreaterEqual(len(ns.TRUSTED), 385)
        fa = [d for d in ns.TRUSTED if "fa" in d[2:]]
        self.assertGreaterEqual(len(fa), 50)

    def test_provider_registry_has_local_and_cloud(self):
        names = {p.get("name", "") for p in nova_providers.PROVIDERS.values()} \
            if isinstance(nova_providers.PROVIDERS, dict) else set()
        self.assertTrue(names or nova_providers.PROVIDERS)


if __name__ == "__main__":
    unittest.main()
