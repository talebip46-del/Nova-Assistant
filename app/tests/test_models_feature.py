#!/usr/bin/env python3
"""v5.1 tests: local model discovery + selection.
Covers the pure nova_models module (parse/pick/resolve/display), the
--list-models CLI flag, resolve_session_model ordering rules, the web
/api/info "models" field and the /api/settings model switch - all
offline (the Ollama layer is faked at http_get_json)."""
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova
import nova_models as nm
import web_server


TAGS_OK = {"models": [
    {"name": "qwen2.5-coder:3b", "model": "qwen2.5-coder:3b",
     "size": 1_900_000_000, "modified_at": "2026-01-02T10:00:00Z",
     "details": {"family": "qwen2", "parameter_size": "3.2B",
                 "quantization_level": "Q4_K_M"}},
    {"name": "llama3:8b", "size": 4_700_000_000,
     "details": {"family": "llama", "parameter_size": "8B"}},
    {"name": "nomic-embed-text", "size": 274_000_000,
     "details": {"family": "nomic-bert", "parameter_size": "137M"}},
]}


def tags_for(names):
    """Build a valid /api/tags payload from plain names."""
    return {"models": [{"name": n, "size": 1_000_000,
                        "details": {"family": "f", "parameter_size": "1B"}}
                       for n in names]}


def fake_get_json(payload, fail=False):
    """Patch nova.http_get_json with a canned payload (or a raiser)."""
    def fake(path, timeout=10):
        if fail:
            raise OSError("connection refused")
        return payload
    return fake


# --------------------------------------------------------------- parse_tags
class TestParseTags(unittest.TestCase):
    def test_valid_payload_full_fields(self):
        out = nm.parse_tags(TAGS_OK)
        self.assertEqual([m["name"] for m in out],
                         ["qwen2.5-coder:3b", "llama3:8b", "nomic-embed-text"])
        self.assertEqual(out[0]["size"], 1_900_000_000)
        self.assertEqual(out[0]["family"], "qwen2")
        self.assertEqual(out[0]["params"], "3.2B")
        self.assertEqual(out[0]["quant"], "Q4_K_M")
        self.assertEqual(out[0]["modified"], "2026-01-02T10:00:00Z")

    def test_non_dict_payloads(self):
        for bad in (None, [], "x", 42, {"models": None}, {},
                    {"models": "nope"}, {"models": {"a": 1}}):
            self.assertEqual(nm.parse_tags(bad), [], repr(bad))

    def test_junk_entries_skipped(self):
        payload = {"models": [
            "string entry",                       # not a dict
            {"size": 100},                        # no name
            {"name": ""},                         # empty
            {"name": "  "},                       # whitespace
            {"name": 42},                         # wrong type
            {"name": "bad\nname"},                # newline -> rejected
            {"name": "ok:1b", "size": "big"},     # junk size -> None
            {"name": "ok2", "size": 0},           # zero size -> None
            {"name": "ok2"},                      # duplicate -> dropped
        ]}
        out = nm.parse_tags(payload)
        names = [m["name"] for m in out]
        self.assertEqual(names, ["ok:1b", "ok2"])
        self.assertEqual(out[0]["size"], None)
        self.assertEqual(out[1]["size"], None)

    def test_name_falls_back_to_model_field(self):
        out = nm.parse_tags({"models": [{"model": "alias-name", "size": 5}]})
        self.assertEqual(out[0]["name"], "alias-name")

    def test_details_not_dict_is_ignored(self):
        out = nm.parse_tags({"models": [{"name": "x", "details": "junk"}]})
        self.assertEqual((out[0]["family"], out[0]["params"], out[0]["quant"]),
                         ("", "", ""))

    def test_oversize_name_rejected(self):
        out = nm.parse_tags({"models": [{"name": "x" * 500}]})
        self.assertEqual(out, [])

    def test_server_order_preserved(self):
        names = ["zeta", "alpha", "mid:7b"]
        out = nm.parse_tags(tags_for(names))
        self.assertEqual([m["name"] for m in out], names)  # no silent sorting


# --------------------------------------------------------------- pick_default
class TestPickDefault(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(nm.pick_default([]), "")
        self.assertEqual(nm.pick_default(["", None]), "")  # type: ignore

    def test_prefers_coder_over_larger_generic(self):
        self.assertEqual(
            nm.pick_default(["llama3:70b", "qwen2.5-coder:3b"]),
            "qwen2.5-coder:3b")

    def test_prefers_smallest_tag_within_family(self):
        self.assertEqual(
            nm.pick_default(["qwen2.5-coder:7b", "qwen2.5-coder:1.5b"]),
            "qwen2.5-coder:1.5b")

    def test_never_picks_embedding_when_chat_exists(self):
        self.assertEqual(
            nm.pick_default(["nomic-embed-text", "llama3:8b"]), "llama3:8b")

    def test_embedding_as_last_resort(self):
        self.assertEqual(nm.pick_default(["nomic-embed-text"]),
                         "nomic-embed-text")

    def test_env_override_wins_even_if_unknown(self):
        self.assertEqual(nm.pick_default(["llama3:8b"], env_model="mistral"),
                         "mistral")

    def test_deterministic(self):
        names = ["gemma2", "deepseek-coder", "llama3", "qwen2.5-coder:3b"]
        self.assertEqual(nm.pick_default(names), nm.pick_default(names))
        self.assertEqual(nm.pick_default(names), "deepseek-coder")


# --------------------------------------------------------------- resolve_choice
class TestResolveChoice(unittest.TestCase):
    NAMES = ["qwen2.5-coder:1.5b", "qwen2.5-coder:3b", "llama3:8b", "5"]

    def test_exact_name_wins(self):
        self.assertEqual(nm.resolve_choice("llama3:8b", self.NAMES), "llama3:8b")

    def test_exact_name_beats_index(self):
        # '5' is a REAL model name here - it must not resolve to row 5
        self.assertEqual(nm.resolve_choice("5", self.NAMES), "5")

    def test_base_match(self):
        self.assertEqual(nm.resolve_choice("qwen2.5-coder", self.NAMES),
                         "qwen2.5-coder:1.5b")  # first hit in server order
        self.assertEqual(nm.resolve_choice("llama3", self.NAMES), "llama3:8b")

    def test_index_selection(self):
        self.assertEqual(nm.resolve_choice("3", self.NAMES), "llama3:8b")

    def test_index_bounds(self):
        self.assertIsNone(nm.resolve_choice("0", self.NAMES))
        self.assertIsNone(nm.resolve_choice("9", self.NAMES))

    def test_unknown(self):
        self.assertIsNone(nm.resolve_choice("gpt-4o", self.NAMES))
        self.assertIsNone(nm.resolve_choice("", self.NAMES))
        self.assertIsNone(nm.resolve_choice("  ", self.NAMES))
        self.assertIsNone(nm.resolve_choice("x", []))

    def test_case_insensitive_base(self):
        self.assertEqual(nm.resolve_choice("LLAMA3", self.NAMES), "llama3:8b")


# --------------------------------------------------------------- display
class TestDisplay(unittest.TestCase):
    def test_fmt_size(self):
        self.assertEqual(nm.fmt_size(None), "")
        self.assertEqual(nm.fmt_size(0), "")
        self.assertEqual(nm.fmt_size(True), "")      # bool guard
        self.assertEqual(nm.fmt_size(500), "500 B")
        self.assertEqual(nm.fmt_size(1_900_000_000), "1.8 GB")

    def test_table_rows_cap(self):
        models = nm.parse_tags(tags_for([f"m{i}" for i in range(60)]))
        rows = nm.table_rows(models, max_rows=40)
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0][1], "m0")
        note = nm.table_overflow_note(models, max_rows=40)
        self.assertIn("20 more", note)
        self.assertEqual(nm.table_overflow_note(models[:10], max_rows=40), "")

    def test_web_list_cap_and_shape(self):
        models = nm.parse_tags(TAGS_OK)
        out = nm.web_list(models)
        self.assertEqual(out[0]["name"], "qwen2.5-coder:3b")
        self.assertEqual(out[0]["size"], "1.8 GB")
        self.assertEqual(out[0]["params"], "3.2B")
        self.assertNotIn("details", out[0])


# --------------------------------------------------------------- nova wiring
class TestNovaWiring(unittest.TestCase):
    def setUp(self):
        self.sess = nova.Session(Path(tempfile.mkdtemp(prefix="nova_m_")))

    def test_list_installed_models_fakes(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(TAGS_OK)
            self.assertEqual(nova.list_installed_models(),
                             ["qwen2.5-coder:3b", "llama3:8b", "nomic-embed-text"])
            detailed = nova.list_models_detailed()
            self.assertEqual(detailed[0]["family"], "qwen2")
        finally:
            nova.http_get_json = orig

    def test_list_models_fail_soft(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(None, fail=True)
            self.assertEqual(nova.list_installed_models(), [])
            self.assertEqual(nova.list_models_detailed(), [])
        finally:
            nova.http_get_json = orig

    def test_resolve_session_model_prefers_default_base(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(
                tags_for(["llama3:8b", "qwen2.5-coder:3b"]))
            self.sess.model = ""                 # nothing chosen yet
            got = nova.resolve_session_model(self.sess, quiet=True)
            self.assertEqual(got, "qwen2.5-coder:3b")
        finally:
            nova.http_get_json = orig

    def test_resolve_session_model_honours_profile_model(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(tags_for(["llama3:8b"]))
            self.sess.model = "llama3:8b"
            self.assertEqual(nova.resolve_session_model(self.sess, quiet=True),
                             "llama3:8b")
        finally:
            nova.http_get_json = orig

    def test_resolve_session_model_falls_back_when_missing(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(tags_for(["llama3:8b"]))
            self.sess.model = "gpt-4o-mini"      # not an ollama model here
            out = io.StringIO()
            with redirect_stdout(out):
                got = nova.resolve_session_model(self.sess)
            self.assertEqual(got, "llama3:8b")
            self.assertIn("not installed", out.getvalue())
        finally:
            nova.http_get_json = orig

    def test_resolve_session_model_no_models(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json({"models": []})
            self.sess.model = ""
            out = io.StringIO()
            with redirect_stdout(out):
                got = nova.resolve_session_model(self.sess)
            self.assertEqual(got, "")            # nothing to pick - honest ''
            self.assertIn("no models available yet", out.getvalue())
            self.assertIn("ollama pull", out.getvalue())
        finally:
            nova.http_get_json = orig

    def test_resolve_session_model_ollama_down(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(None, fail=True)
            self.sess.model = "whatever"
            self.assertEqual(nova.resolve_session_model(self.sess, quiet=True),
                             "whatever")         # fail-soft: keep the choice
        finally:
            nova.http_get_json = orig

    def test_resolve_session_model_env_override(self):
        orig = nova.http_get_json
        old_env = nova.os.environ.get("NOVA_MODEL")
        try:
            nova.os.environ["NOVA_MODEL"] = "llama3:8b"
            nova.http_get_json = fake_get_json(tags_for(["llama3:8b"]))
            self.sess.model = ""                 # no profile model
            self.assertEqual(nova.resolve_session_model(self.sess, quiet=True),
                             "llama3:8b")
        finally:
            nova.http_get_json = orig
            if old_env is None:
                nova.os.environ.pop("NOVA_MODEL", None)
            else:
                nova.os.environ["NOVA_MODEL"] = old_env

    def test_cmd_model_switch_by_number_and_name(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(TAGS_OK)
            nova.cmd_model(self.sess, "")        # table must not crash
            nova.cmd_model(self.sess, "2")
            self.assertEqual(self.sess.model, "llama3:8b")
            nova.cmd_model(self.sess, "qwen2.5-coder")
            self.assertEqual(self.sess.model, "qwen2.5-coder:3b")
            nova.cmd_model(self.sess, "nope")    # unknown - unchanged
            self.assertEqual(self.sess.model, "qwen2.5-coder:3b")
            nova.cmd_model(self.sess, "nomic-embed-text")  # explicit is allowed
            self.assertEqual(self.sess.model, "nomic-embed-text")
        finally:
            nova.http_get_json = orig

    def test_models_alias_is_registered(self):
        tool = nova.find_tool("/models")
        self.assertIsNotNone(tool)
        self.assertEqual(tool["fn"], nova.cmd_model)


# --------------------------------------------------------------- CLI flag
class TestParseArgsListModels(unittest.TestCase):
    def test_flag_parsed(self):
        opts = nova.parse_args(["--list-models"])
        self.assertTrue(opts["list_models"])
        opts = nova.parse_args(["--list-models", "--web", "ws"])
        self.assertTrue(opts["list_models"])
        self.assertTrue(opts["web"])

    def test_other_flags_untouched(self):
        opts = nova.parse_args(["--web"])
        self.assertFalse(opts["list_models"])

    def test_flag_takes_no_value(self):
        with self.assertRaises(ValueError):
            nova.parse_args(["--list-models=foo"])


# --------------------------------------------------------------- web face
class TestWebModelEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web_server.nova = nova
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_mweb_"))
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        cls.httpd = web_server._make_server(args)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def post(self, path, obj):
        data = json.dumps(obj).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_info_includes_models(self):
        orig = nova.http_get_json
        old_active = nova.providers._ACTIVE["name"]
        try:
            nova.providers._ACTIVE["name"] = None   # ollama default
            nova.http_get_json = fake_get_json(TAGS_OK)
            code, info = self.get("/api/info")
            self.assertEqual(code, 200)
            self.assertEqual(info["ollama_ok"], True)
            names = [m["name"] for m in info["models"]]
            self.assertIn("qwen2.5-coder:3b", names)
        finally:
            nova.http_get_json = orig
            nova.providers._ACTIVE["name"] = old_active

    def test_info_ollama_down_models_empty(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(None, fail=True)
            code, info = self.get("/api/info")
            self.assertEqual(code, 200)
            self.assertEqual(info["ollama_ok"], False)
            self.assertEqual(info["models"], [])
        finally:
            nova.http_get_json = orig

    def test_settings_model_switch_valid(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(TAGS_OK)
            code, res = self.post("/api/settings", {"model": "llama3:8b"})
            self.assertEqual(code, 200)
            self.assertEqual(res["model"], "llama3:8b")
            self.assertEqual(web_server.STATE.sess.model, "llama3:8b")
            # base-name resolution also works (first tag variant wins)
            code, res = self.post("/api/settings", {"model": "qwen2.5-coder"})
            self.assertEqual(res["model"], "qwen2.5-coder:3b")
        finally:
            nova.http_get_json = orig

    def test_settings_model_switch_unknown_rejected(self):
        orig = nova.http_get_json
        before = web_server.STATE.sess.model
        try:
            nova.http_get_json = fake_get_json(TAGS_OK)
            code, res = self.post("/api/settings", {"model": "gpt-4o"})
            self.assertEqual(code, 409)
            self.assertIn("not installed", res["error"])
            self.assertEqual(web_server.STATE.sess.model, before)
        finally:
            nova.http_get_json = orig

    def test_settings_model_invalid_payload(self):
        for bad in ("", "   ", 42, None, "x" * 200):
            code, res = self.post("/api/settings", {"model": bad})
            self.assertEqual(code, 400, repr(bad))


if __name__ == "__main__":
    unittest.main()
