#!/usr/bin/env python3
"""Stage-2 feature tests: snapshots/unlimited undo, manual checkpoints,
hunk diff review engine, style repo-map. Temp dirs, no network."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_snapshots as snaps
import nova_diffview as dv
import nova_repomap as rm
from nova_policy import NovaIgnore


def mkfile(ws, rel, content):
    p = Path(ws) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TempWS(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_t2_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)


# ------------------------------------------------- snapshots
class TestAutoUnits(TempWS):
    def test_push_undo_modified(self):
        f = mkfile(self.ws, "a.txt", "original")
        bk = self.ws / ".nova_backups" / "b1__a.txt"
        bk.parent.mkdir(parents=True, exist_ok=True)
        bk.write_text("original", encoding="utf-8")
        f.write_text("changed", encoding="utf-8")
        uid, err = snaps.push_auto_unit(self.ws, [(f, bk)], note="test")
        self.assertEqual(err, "")
        self.assertEqual(f.read_text(encoding="utf-8"), "changed")
        res = snaps.undo_units(self.ws, 1)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["restored"], [("restored", "a.txt")])
        self.assertEqual(f.read_text(encoding="utf-8"), "original")

    def test_push_undo_new_file_gets_deleted(self):
        f = mkfile(self.ws, "sub/new.py", "print(1)")
        uid, err = snaps.push_auto_unit(self.ws, [(f, None)], note="new")
        self.assertEqual(err, "")
        res = snaps.undo_units(self.ws, 1)
        self.assertEqual(res["restored"], [("deleted", "sub/new.py")])
        self.assertFalse(f.exists())

    def test_unlimited_multi_level_undo(self):
        f = mkfile(self.ws, "log.txt", "v0")
        for i in range(1, 8):   # 7 consecutive edits
            old = f.read_text(encoding="utf-8")
            bk = self.ws / ".nova_backups" / f"b{i}.txt"
            bk.parent.mkdir(parents=True, exist_ok=True)
            bk.write_text(old, encoding="utf-8")
            f.write_text(f"v{i}", encoding="utf-8")
            snaps.push_auto_unit(self.ws, [(f, bk)])
        res = snaps.undo_units(self.ws, 3)
        self.assertEqual(f.read_text(encoding="utf-8"), "v4")
        snaps.undo_units(self.ws, 4)
        self.assertEqual(f.read_text(encoding="utf-8"), "v0")
        self.assertEqual(snaps.list_units(self.ws, "auto"), [])

    def test_mixed_batch_order(self):
        a = mkfile(self.ws, "a.txt", "A0")
        b = mkfile(self.ws, "b.txt", "B0")
        new = mkfile(self.ws, "c.txt", "C-new")
        bka = mkfile(self.ws, ".nova_backups/ba", "A0")
        bkb = mkfile(self.ws, ".nova_backups/bb", "B0")
        a.write_text("A1"); b.write_text("B1")
        snaps.push_auto_unit(self.ws, [(a, bka), (b, bkb), (new, None)])
        snaps.undo_units(self.ws, 1)
        self.assertEqual(a.read_text(encoding="utf-8"), "A0")
        self.assertEqual(b.read_text(encoding="utf-8"), "B0")
        self.assertFalse(new.exists())

    def test_escapes_blocked(self):
        evil = self.ws / ".." / "outside.txt"
        evil.write_text("x", encoding="utf-8")
        uid, err = snaps.push_auto_unit(self.ws, [(evil, None)])
        # relative_to raises -> nothing snapshotable -> empty unit refused
        self.assertNotEqual(err, "")

    def test_retention_prune(self):
        f = mkfile(self.ws, "r.txt", "v0")
        for i in range(snaps.MAX_AUTO_UNITS + 5):
            old = f.read_text(encoding="utf-8")
            bk = self.ws / ".nova_backups" / f"p{i}"
            bk.parent.mkdir(parents=True, exist_ok=True)
            bk.write_text(old, encoding="utf-8")
            f.write_text(f"v{i}")
            snaps.push_auto_unit(self.ws, [(f, bk)])
        self.assertLessEqual(len(snaps.list_units(self.ws, "auto")),
                             snaps.MAX_AUTO_UNITS)
        # newest preserved: undo restores the state BEFORE the last edit,
        # i.e. the content the newest unit snapshotted
        snaps.undo_units(self.ws, 1)
        self.assertEqual(f.read_text(encoding="utf-8"), f"v{snaps.MAX_AUTO_UNITS + 3}")

    def test_corrupt_unit_skipped(self):
        d = snaps.root(self.ws, "auto") / "garbage"
        d.mkdir(parents=True)
        (d / "meta.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(snaps.list_units(self.ws, "auto"), [])


class TestManualCheckpoints(TempWS):
    def test_checkpoint_restore_roundtrip(self):
        mkfile(self.ws, "a.py", "print('v1')")
        mkfile(self.ws, "sub/b.js", "let x = 1;")
        uid, err, skipped = snaps.make_manual(self.ws, label="before-refactor")
        self.assertEqual(err, "")
        # mutate: edit one, delete one, create one
        (self.ws / "a.py").write_text("print('v2')")
        (self.ws / "sub/b.js").unlink()
        mkfile(self.ws, "later.txt", "created after")
        meta = snaps.find_manual(self.ws, "before-refactor")
        self.assertIsNotNone(meta)
        res = snaps.restore_manual(self.ws, meta)
        self.assertEqual(res["errors"], [])
        self.assertEqual((self.ws / "a.py").read_text(encoding="utf-8"), "print('v1')")
        self.assertTrue((self.ws / "sub/b.js").is_file())
        self.assertFalse((self.ws / "later.txt").exists())

    def test_ignores_nova_and_secrets(self):
        mkfile(self.ws, ".nova/x.json", "{}")
        mkfile(self.ws, "server.pem", "PRIVATE")
        mkfile(self.ws, "ok.py", "x=1")
        state, skipped = snaps.build_checkpoint(self.ws)
        self.assertIn("ok.py", state)
        self.assertNotIn(".nova/x.json", state)
        # secrets are TRACKED as skipped (state None) so restore never
        # deletes them, but their content is never stored
        self.assertIsNone(state.get("server.pem"))
        uid, err, _ = snaps.make_manual(self.ws)
        self.assertEqual(err, "")
        meta = snaps.find_manual(self.ws, uid)
        stored = [f for f in meta["files"] if f["rel"] == "server.pem"]
        self.assertTrue(stored[0]["skip"])

    def test_novaignore_respected(self):
        mkfile(self.ws, "big/dataset.csv", "a,b")
        mkfile(self.ws, "keep.py", "x=1")
        (self.ws / ".novaignore").write_text("big/\n", encoding="utf-8")
        state, _ = snaps.build_checkpoint(self.ws, NovaIgnore.load(self.ws))
        self.assertNotIn("big/dataset.csv", state)
        self.assertIn("keep.py", state)

    def test_restore_by_unique_label(self):
        mkfile(self.ws, "m.txt", "1")
        snaps.make_manual(self.ws, label="snap1")
        snaps.make_manual(self.ws, label="snap2")
        meta = snaps.find_manual(self.ws, "snap2")
        self.assertEqual(meta["label"], "snap2")
        self.assertIsNone(snaps.find_manual(self.ws, "nope"))

    def test_retention_manual(self):
        for i in range(snaps.MAX_MANUAL_UNITS + 3):
            snaps.make_manual(self.ws, label=f"s{i}")
        self.assertLessEqual(len(snaps.list_units(self.ws, "manual")),
                             snaps.MAX_MANUAL_UNITS)

    def test_too_big_file_marked_skip(self):
        mkfile(self.ws, "huge.bin", "x" * (snaps.MAX_FILE_BYTES + 10))
        uid, err, skipped = snaps.make_manual(self.ws)
        self.assertEqual(err, "")
        meta = snaps.find_manual(self.ws, uid)
        flagged = [f for f in meta["files"] if f["rel"] == "huge.bin"]
        self.assertTrue(flagged and flagged[0]["skip"])


# ------------------------------------------------- diffview
class TestDiffEngine(unittest.TestCase):
    ORIGINAL = "line1\nline2\nline3\nline4\nline5"

    def test_apply_hunks_sequential(self):
        h = [("line2", "TWO"), ("line4", "FOUR")]
        text, applied, problems = dv.apply_hunks(self.ORIGINAL, h)
        self.assertEqual(problems, [])
        self.assertEqual(text, "line1\nTWO\nline3\nFOUR\nline5")

    def test_apply_hunks_later_hunk_invalidated(self):
        h = [("line2\nline3", "replaced"), ("line3", "orphan")]
        text, applied, problems = dv.apply_hunks(self.ORIGINAL, h)
        self.assertEqual(len(applied), 1)
        self.assertEqual(problems[0][0], 2)   # hunk 2 no longer matches

    def test_ambiguous_hunk_rejected(self):
        text, applied, problems = dv.apply_hunks("x\nx\n", [("x", "y")])
        self.assertEqual(applied, [])
        self.assertIn("2 times", problems[0][1])

    def test_unified_diff_shape(self):
        lines = dv.unified_diff("f.py", self.ORIGINAL, self.ORIGINAL.replace("line3", "LINE3"))
        self.assertTrue(any(l.startswith("-") for l in lines))
        self.assertTrue(any(l.startswith("+") for l in lines))
        self.assertTrue(any(l.startswith("@@") for l in lines))

    def test_diff_line_cap(self):
        big = "\n".join(f"l{i}" for i in range(500))
        lines = dv.unified_diff("b.txt", big, big + "\nextra")
        self.assertLessEqual(len(lines), dv.MAX_DIFF_LINES + 1)

    def test_hunk_preview_found_and_not_found(self):
        lines, ok = dv.hunk_preview(self.ORIGINAL, "line3", "THREE")
        self.assertTrue(ok)
        self.assertIn("- line3", lines)
        self.assertIn("+ THREE", lines)
        lines, ok = dv.hunk_preview(self.ORIGINAL, "nope", "x")
        self.assertFalse(ok)

    def test_review_flow_accept_reject(self):
        answers = iter(["n", "y"])
        printed = []
        accepted, notes, text = dv.review_hunks(
            self.ORIGINAL,
            [("line2", "TWO"), ("line4", "FOUR")],
            ask_fn=lambda p: next(answers),
            print_fn=printed.append,
            color_fn=None)
        self.assertEqual(accepted, [("line4", "FOUR")])
        self.assertEqual(text, "line1\nline2\nline3\nFOUR\nline5")
        self.assertTrue(any("rejected" in n for n in notes))

    def test_review_quit_stops(self):
        answers = iter(["q"])
        accepted, notes, text = dv.review_hunks(
            self.ORIGINAL, [("line2", "TWO"), ("line4", "FOUR")],
            ask_fn=lambda p: next(answers), print_fn=lambda s: None)
        self.assertEqual(accepted, [])
        self.assertEqual(text, self.ORIGINAL)

    def test_review_all_shortcut(self):
        answers = iter(["a"])
        accepted, notes, text = dv.review_hunks(
            self.ORIGINAL, [("line2", "TWO"), ("line4", "FOUR")],
            ask_fn=lambda p: next(answers), print_fn=lambda s: None)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(text, "line1\nTWO\nline3\nFOUR\nline5")

    def test_paint_colors(self):
        out = dv.paint(["+added", "-removed", "@@ h @@"], color_fn=lambda code, t: code + t + "\033[0m")
        self.assertIn("\033[92m+added", out)
        self.assertIn("\033[91m-removed", out)
        self.assertIn("\033[96m@@ h @@", out)

    def test_summarize(self):
        s = dv.summarize_changes(["a.py", "b.py", "c.py", "d.py"], ["e.py"])
        self.assertIn("new: a.py, b.py, c.py...", s)
        self.assertIn("edited: e.py", s)


# ------------------------------------------------- repomap
class TestRepoMap(TempWS):
    def test_python_signatures(self):
        code = ('import os\n\n\nclass Engine:\n'
                '    def inner(self):\n        pass\n\n\n'
                'def top_level(a, b):\n    pass\n\n\n'
                'async def a_factory():\n    pass\n')
        sigs = rm.file_signatures("x.py", code)
        self.assertEqual(len(sigs), 3)
        self.assertTrue(sigs[0].startswith("class Engine"))
        self.assertTrue(sigs[1].startswith("def top_level"))
        self.assertTrue(sigs[2].startswith("async def a_factory"))

    def test_python_indented_defs_excluded(self):
        code = "def outer():\n    def helper():\n        pass\n"
        sigs = rm.file_signatures("x.py", code)
        self.assertEqual(len(sigs), 1)
        self.assertIn("outer", sigs[0])

    def test_js_signatures(self):
        code = ("export function renderMd(src) {}\n"
                "class Table {}\n"
                "const handler = async (req) => {}\n"
                "let plain = 5;\n")
        sigs = rm.file_signatures("a.js", code)
        self.assertEqual(len(sigs), 3)

    def test_css_json_html_sh(self):
        self.assertTrue(any("@media" in s for s in
                        rm.file_signatures("s.css", "@media (max-width:600px){\n}\n.card {\n}\n")))
        self.assertEqual(rm.file_signatures("d.json", '{"name": 1, "items": []}'),
                         ["key: name", "key: items"])
        html = "<title>My App</title><script src='app.js'></script>"
        sigs = rm.file_signatures("i.html", html)
        self.assertTrue(any("title: My App" in s for s in sigs))
        self.assertTrue(any("app.js" in s for s in sigs))
        self.assertEqual(rm.sh_signatures("function run(){\n}\npack () {\n}\n"),
                         ["function run()", "function pack()"])

    def test_broken_python_never_raises(self):
        # malformed content must never raise - it may still yield a
        # harmless signature, that is fine
        for junk in ("def broken(:\n  pass", "\x00\x01\x02", "class :", "def"):
            sigs = rm.file_signatures("x.py", junk)
            self.assertIsInstance(sigs, list)

    def test_map_respects_budget_and_content(self):
        mkfile(self.ws, "main.py", "def run():\n    pass\n")
        mkfile(self.ws, "util.py", "class U:\n    pass\n")
        mkfile(self.ws, "data.bin", "x" * 50)
        mp = rm.build_style_map(self.ws)
        self.assertIn("main.py (3 lines): def run()", mp)
        self.assertIn("class U", mp)
        self.assertIn("data.bin", mp)

    def test_map_respects_novaignore(self):
        mkfile(self.ws, "vendor/lib.py", "def v():\n    pass\n")
        mkfile(self.ws, "app.py", "def a():\n    pass\n")
        (self.ws / ".novaignore").write_text("vendor/\n", encoding="utf-8")
        mp = rm.build_style_map(self.ws, ignore=NovaIgnore.load(self.ws))
        self.assertNotIn("vendor", mp)
        self.assertIn("app.py", mp)

    def test_map_budget_cap(self):
        for i in range(80):
            mkfile(self.ws, f"f{i:02d}.py", f"def f{i}():\n    pass\n" * 4)
        mp = rm.build_style_map(self.ws, max_chars=800)
        self.assertLessEqual(len(mp), 900)
        self.assertIn("more files", mp)

    def test_empty_ws(self):
        self.assertEqual(rm.build_style_map(self.ws), "(the workspace is empty)")


if __name__ == "__main__":
    unittest.main()
