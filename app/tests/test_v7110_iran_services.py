#!/usr/bin/env python3
"""v7.11.0 tests: IRANIAN SERVICES with API keys.

The user's ask (message 28): "کلا از این سایتای معتبر ایرانی که api key
دارن هم اضافه کن، انتظار دارم بر هر کاری بتونم از چند تا سایت ایرانی api
key بگیرم، مثلا همو از کاوه نگار api key برای پیامک و اینکه فقط به
اسمایی که من میگم فکر نکن یک عالمه از این نوع سایت ها برای همه کار بزار"

Pinned here:
  1. CATALOG: 20 trusted Iranian services across 6 categories - every
     service the user named (kavenegar/zarinpal/bale/aparat) plus a
     broad set per category (SMS 5, payment 5, maps 2, crypto 4,
     messenger bots 3, video 1). Every action is a well-formed request
     template (method/https/params/ok_check) and every service that
     CAN have a free test has one (11 safe tests).
  2. build_request() - the PURE engine: path-key (kavenegar), header
     auth (ghasedak apikey / payping bearer / neshan Api-Key), JSON
     bodies (zarinpal int amount via json_params), form bodies
     (ghasedak/eitaa), optional {p?} dropping (idpay X-SANDBOX absent),
     defaults (nobitex market stats), JSON-escape params (sms.ir
     phones/parameters/templateId), path percent-encoding (aparat
     Persian query), raw colon in bot tokens (bale) - and the typo
     guard (unknown param) + missing-required errors.
  3. ok-checks per real API dialect: kavenegar return.status==200,
     zarinpal data.code in 100/101, zibal result==100, nextpay code==-1,
     bale ok==True, idpay link presence.
  4. VAULT: keys in <ws>/.nova/iran_services.json (chmod 600 POSIX),
     env fallback, masked display, unknown-service errors, 400-char
     cap, cross-process file_lock discipline (same as the provider
     vault). A full key NEVER leaks into a result/error.
  5. EXECUTION + METERING: run_action through a stubbed network seam -
     success (fields/extract/link), API-error bodies, transport
     failures, missing key (Persian hint) - and the per-service usage
     counters (requests/ok/fail/last_*) persisting into the vault.
  6. WEB + CLI surfaces: /api/iran state shape (masked keys only),
     web_action set_key/del_key/test/call, /services in TOOLS
     (model-briefed), cmd_services list/key/test smoke.

All tests are NETWORK-FREE (the network seam is stubbed; no socket).
"""
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova  # noqa: E402
import nova_iran_services as iran  # noqa: E402


class _WSTestCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(prefix="nova_v711_")
        self.ws = Path(d)
        iran.load_state(self.ws)
        self.addCleanup(iran.load_state, None)


# --------------------------------------------------------------- catalog
class TestCatalog(unittest.TestCase):
    def test_twenty_services_six_categories(self):
        self.assertEqual(len(iran.names()), 20)
        self.assertEqual(len(set(iran.names())), 20)
        self.assertEqual(len(iran.CATEGORIES), 6)
        cat_ids = {c for c, _ in iran.CATEGORIES}
        for sid in iran.names():
            e = iran.entry(sid)
            self.assertIsNotNone(e, sid)
            self.assertIn(e.get("category"), cat_ids, sid)
            self.assertTrue(e.get("label"), sid)
            self.assertTrue(e.get("site", "").startswith("https://"), sid)
            self.assertTrue(e.get("actions"), sid)

    def test_every_named_service_present(self):
        # the user named these explicitly + the ones from message 26
        for sid in ("kavenegar", "zarinpal", "bale", "aparat",
                    "melipayamak", "neshan", "nobitex", "eitaa",
                    "rubika", "idpay", "zibal"):
            self.assertIn(sid, iran.names())

    def test_categories_coverage(self):
        for cid, _ in iran.CATEGORIES:
            sids = [s for s in iran.names()
                    if (iran.entry(s) or {}).get("category") == cid]
            self.assertTrue(sids, cid)

    def test_actions_well_formed(self):
        total = 0
        for sid in iran.names():
            for aid, act in iran.actions_of(sid).items():
                total += 1
                self.assertIn(act.get("method"), ("GET", "POST", "PUT"),
                              f"{sid}.{aid}")
                self.assertTrue(act["url"].startswith("https://"),
                                f"{sid}.{aid}")
                if not act.get("no_key"):
                    blob = (act["url"]
                            + json.dumps(act.get("headers") or {})
                            + json.dumps(act.get("body") or {})
                            + json.dumps(act.get("form") or {}))
                    self.assertIn("{key}", blob,
                                  f"{sid}.{aid}: key must go somewhere")
                toks = iran._action_tokens(act)
                for r in act.get("required", []):
                    self.assertIn(r, toks, f"{sid}.{aid} required {r}")
                for o in act.get("optional", []):
                    self.assertIn(o, toks, f"{sid}.{aid} optional {o}")
                oc = act.get("ok_check")
                if oc:
                    self.assertIn(oc.get("kind"), ("dig_in", "field"),
                                  f"{sid}.{aid}")
                for ex in act.get("extract", []):
                    self.assertIn("field", ex, f"{sid}.{aid}")
                    self.assertIn("path", ex, f"{sid}.{aid}")

    def test_safe_tests_present(self):
        # every service that can be safely probed has one safe action
        expected = {"kavenegar", "idpay", "zibal", "neshan", "nobitex",
                    "wallex", "bitpin", "ramzinex", "bale", "rubika",
                    "aparat"}
        got = {s for s in iran.names() if iran.safe_action(s)}
        self.assertEqual(got, expected)
        self.assertEqual(len(got), 11)

    def test_aparat_is_keyless(self):
        e = iran.entry("aparat")
        self.assertFalse(e.get("needs_key", True))
        self.assertEqual(e.get("key_names"), [])
        self.assertIsNone(e.get("key_env"))
        for act in e["actions"].values():
            self.assertTrue(act.get("no_key"))


# --------------------------------------------------------------- engine
class TestBuildRequest(unittest.TestCase):
    def test_kavenegar_path_key_and_query(self):
        r = iran.build_request(
            "kavenegar", "send_sms",
            {"receptor": "09123456789", "message": "سلام Nova"},
            key="ABC-KEY-42", ts=1700000000)
        self.assertEqual(r["method"], "GET")
        self.assertIn("https://api.kavenegar.com/v1/ABC-KEY-42/sms/send.json",
                      r["url"])
        self.assertIn("receptor=09123456789", r["url"])
        self.assertIn("%D8%B3%D9%84%D8%A7%D9%85", r["url"])  # سلام encoded

    def test_kavenegar_optional_sender_dropped(self):
        r = iran.build_request("kavenegar", "send_sms",
                               {"receptor": "0912", "message": "hi"})
        self.assertNotIn("sender=", r["url"])
        r2 = iran.build_request("kavenegar", "send_sms",
                                {"receptor": "0912", "message": "hi",
                                 "sender": "10008663"})
        self.assertIn("sender=10008663", r2["url"])

    def test_ghasedak_header_and_form(self):
        r = iran.build_request(
            "ghasedak", "send_sms",
            {"message": "salam", "receptor": "0912", "linenumber": "5000"},
            key="G-KEY")
        self.assertEqual(r["headers"]["apikey"], "G-KEY")
        self.assertEqual(r["headers"]["Content-Type"],
                         "application/x-www-form-urlencoded")
        self.assertIn(b"message=salam", r["data"])
        self.assertIn(b"linenumber=5000", r["data"])

    def test_payping_bearer_header(self):
        r = iran.build_request("payping", "create_payment",
                               {"amount": "10000",
                                "callback": "https://a.b/c"}, key="TOK")
        self.assertEqual(r["headers"]["Authorization"], "Bearer TOK")
        body = json.loads(r["data"])
        self.assertEqual(body["amount"], 10000)          # json_params int
        self.assertEqual(body["returnUrl"], "https://a.b/c")

    def test_zarinpal_body_merchant_int_amount(self):
        r = iran.build_request("zarinpal", "create_payment",
                               {"amount": "250000",
                                "callback": "https://x/cb",
                                "description": "تست"},
                               key="MERCH-1", ts=1700000000)
        body = json.loads(r["data"])
        self.assertEqual(body, {"merchant_id": "MERCH-1", "amount": 250000,
                                "callback_url": "https://x/cb",
                                "description": "تست"})

    def test_idpay_sandbox_optional_header(self):
        r = iran.build_request("idpay", "create_payment",
                               {"order_id": "o1", "amount": "15000"},
                               key="K")
        self.assertNotIn("X-SANDBOX", r["headers"])
        r2 = iran.build_request("idpay", "create_payment",
                                {"order_id": "o1", "amount": "15000",
                                 "sandbox": "1"}, key="K")
        self.assertEqual(r2["headers"]["X-SANDBOX"], "1")

    def test_idpay_sandbox_test_static(self):
        r = iran.build_request("idpay", "sandbox_test", {}, key="K",
                               ts=1700000000)
        self.assertEqual(r["headers"]["X-SANDBOX"], "1")
        body = json.loads(r["data"])
        self.assertEqual(body["order_id"], "nova-1700000000")
        self.assertEqual(body["amount"], 15000)

    def test_zibal_sandbox_test_merchant(self):
        r = iran.build_request("zibal", "sandbox_test", {})
        self.assertEqual(json.loads(r["data"])["merchant"], "zibal")

    def test_nobitex_defaults(self):
        r = iran.build_request("nobitex", "market_stats", {})
        body = json.loads(r["data"])
        self.assertEqual(body, {"srcCurrency": "btc,usdt,eth",
                                "dstCurrency": "rls"})

    def test_nobitex_wallets_token_header(self):
        r = iran.build_request("nobitex", "wallets", {}, key="NK")
        self.assertEqual(r["headers"]["Authorization"], "Token NK")

    def test_smsir_json_escape_params(self):
        r = iran.build_request(
            "smsir", "send_verify",
            {"mobile": "09123456789", "template_id": "100000",
             "parameters": '[{"name":"CODE","value":"123"}]'}, key="SK")
        body = json.loads(r["data"])
        self.assertEqual(body["templateId"], 100000)     # int via json
        self.assertEqual(body["parameters"],
                         [{"name": "CODE", "value": "123"}])
        self.assertEqual(body["mobile"], "09123456789")  # NOT json'd

    def test_smsir_bulk_phone_list(self):
        r = iran.build_request("smsir", "send_bulk",
                               {"phones": '["0912","0913"]',
                                "message": "salam"}, key="SK")
        self.assertEqual(json.loads(r["data"])["phone"], ["0912", "0913"])

    def test_aparat_path_encoding_no_key(self):
        r = iran.build_request("aparat", "user_videos", {"user": "aparat"})
        self.assertEqual(r["url"],
                         "https://www.aparat.com/etc/api/videoByUser/aparat")
        r2 = iran.build_request("aparat", "user_videos", {"user": "a b"})
        self.assertIn("videoByUser/a%20b", r2["url"])
        self.assertEqual(r2["headers"].get("Authorization", ""),
                         "")  # no auth needed at all

    def test_bale_token_colon_stays_raw(self):
        r = iran.build_request("bale", "get_me", {},
                               key="123456:AAHx-9")
        self.assertEqual(r["url"], "https://tapi.bale.ai/bot123456:AAHx-9/getMe")
        r2 = iran.build_request("bale", "send_message",
                                {"chat_id": "777", "text": "سلام"},
                                key="T:K")
        self.assertIn("/botT:K/sendMessage", r2["url"])
        self.assertEqual(json.loads(r2["data"]),
                         {"chat_id": "777", "text": "سلام"})

    def test_eitaa_form_body(self):
        r = iran.build_request("eitaa", "send_message",
                               {"chat_id": "@ch", "text": "سلام"}, key="E1")
        self.assertEqual(r["url"],
                         "https://eitaayar.ir/api/E1/sendMessage")
        self.assertIn(b"chat_id=%40ch", r["data"])

    def test_neshan_search_headers(self):
        r = iran.build_request("neshan", "search", {}, key="NSH")
        self.assertEqual(r["headers"]["Api-Key"], "NSH")
        # defaults fill term/lat/lng
        self.assertIn("term=", r["url"])

    def test_mapir_route_path_params(self):
        r = iran.build_request("mapir", "route",
                               {"lng1": "51.3", "lat1": "35.6",
                                "lng2": "51.4", "lat2": "35.7"}, key="M")
        self.assertEqual(r["url"],
                         "https://map.ir/routes/route/v1/driving/"
                         "51.3,35.6;51.4,35.7")
        self.assertEqual(r["headers"]["MAP-IR-API-KEY"], "M")

    def test_errors_unknown_and_missing(self):
        with self.assertRaises(iran.ServiceError):
            iran.build_request("nosuch", "x")
        with self.assertRaises(iran.ServiceError):
            iran.build_request("kavenegar", "nosuch")
        with self.assertRaises(iran.ServiceError) as cm:
            iran.build_request("kavenegar", "send_sms",
                               {"receptor": "0912", "message": "h",
                                "wrong": "1"})
        self.assertIn("unknown parameter", str(cm.exception))
        self.assertIn("wrong", str(cm.exception))
        with self.assertRaises(iran.ServiceError) as cm2:
            iran.build_request("kavenegar", "send_sms",
                               {"receptor": "0912"})
        self.assertIn("message", str(cm2.exception))

    def test_error_never_contains_key(self):
        key = "SUPERSECRET-KEY-12345"
        try:
            iran.build_request("kavenegar", "send_sms", {"message": "x"},
                               key=key)
            self.fail("expected ServiceError")
        except iran.ServiceError as e:
            self.assertNotIn(key, str(e))


# --------------------------------------------------------------- ok rules
class TestOkChecks(unittest.TestCase):
    def test_kavenegar(self):
        act = iran.actions_of("kavenegar")["send_sms"]
        self.assertTrue(iran._check_ok(act, 200,
                                       {"return": {"status": 200}}))
        self.assertFalse(iran._check_ok(act, 200,
                                        {"return": {"status": 412}}))

    def test_zarinpal(self):
        act = iran.actions_of("zarinpal")["create_payment"]
        self.assertTrue(iran._check_ok(act, 200,
                                       {"data": {"code": 100}}))
        self.assertTrue(iran._check_ok(act, 200,
                                       {"data": {"code": 101}}))
        self.assertFalse(iran._check_ok(act, 200,
                                        {"data": {"code": -71}}))

    def test_zibal_nextpay_bale(self):
        self.assertTrue(iran._check_ok(iran.actions_of("zibal")["create_payment"],
                                       200, {"result": 100}))
        self.assertFalse(iran._check_ok(iran.actions_of("zibal")["create_payment"],
                                        200, {"result": 102}))
        self.assertTrue(iran._check_ok(iran.actions_of("nextpay")["create_payment"],
                                       200, {"code": -1}))
        self.assertTrue(iran._check_ok(iran.actions_of("bale")["get_me"],
                                       200, {"ok": True}))
        self.assertFalse(iran._check_ok(iran.actions_of("bale")["get_me"],
                                        200, {"ok": False}))

    def test_dig_walk(self):
        self.assertEqual(iran._dig({"a": {"b": 7}}, "a.b"), 7)
        self.assertIsNone(iran._dig({"a": 1}, "a.b.c"))
        self.assertIsNone(iran._dig("junk", "a.b"))


# --------------------------------------------------------------- vault
class TestVault(_WSTestCase):
    def test_set_del_roundtrip_and_chmod(self):
        self.assertEqual(iran.set_key(self.ws, "kavenegar",
                                      "KEY-ABCD"), "")
        self.assertEqual(iran.key_source(self.ws, "kavenegar"), "file")
        is_set, masked = iran.key_status(self.ws, "kavenegar")
        self.assertTrue(is_set)
        self.assertEqual(masked, "...ABCD")
        p = self.ws / ".nova" / "iran_services.json"
        self.assertTrue(p.is_file())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(p.stat().st_mode) & 0o777, 0o600)
        raw = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(raw["keys"]["kavenegar"], "KEY-ABCD")
        self.assertEqual(iran.del_key(self.ws, "kavenegar"), "")
        self.assertFalse(iran.key_status(self.ws, "kavenegar")[0])

    def test_unknown_service(self):
        self.assertIn("unknown", iran.set_key(self.ws, "nope", "x"))
        self.assertIn("unknown", iran.del_key(self.ws, "nope", ))

    def test_empty_and_long_keys(self):
        self.assertEqual(iran.set_key(self.ws, "kavenegar", "  "), "empty key")
        self.assertEqual(iran.set_key(self.ws, "kavenegar", "x" * 401), "")
        # 401 -> capped to 400 silently (same law as the provider vault)
        self.assertEqual(len(iran.key_of(self.ws, "kavenegar")), 400)

    def test_env_fallback(self):
        e = iran.entry("zarinpal")
        with mock.patch.dict(os.environ, {e["key_env"]: "ENV-MERCH"}):
            self.assertEqual(iran.key_source(self.ws, "zarinpal"), "env")
            self.assertEqual(iran.key_of(self.ws, "zarinpal"), "ENV-MERCH")
            self.assertEqual(iran.key_status(self.ws, "zarinpal")[1],
                             "...ERCH")
        # env gone -> unset again
        self.assertEqual(iran.key_source(self.ws, "zarinpal"), "")

    def test_workspace_switch_reloads(self):
        iran.set_key(self.ws, "bale", "B-TOKEN")
        d2 = Path(tempfile.mkdtemp(prefix="nova_v711b_"))
        self.assertEqual(iran.key_of(d2, "bale"), "")
        self.assertEqual(iran.key_of(self.ws, "bale"), "B-TOKEN")


# --------------------------------------------------------------- execution
class _StubHTTP(unittest.TestCase):
    """Stubs iran._http - the ONE network seam - and gives a temp ws."""

    def setUp(self):
        d = tempfile.mkdtemp(prefix="nova_v711c_")
        self.ws = Path(d)
        iran.load_state(self.ws)
        self.addCleanup(iran.load_state, None)
        iran.set_key(self.ws, "kavenegar", "KEY-ABCD1234")

    def stub(self, status=200, text="{}", err=None):
        return mock.patch.object(iran, "_http",
                                 return_value=(status, text, err))


class TestRunAction(_StubHTTP):
    def test_success_metering_and_fields(self):
        with self.stub(200, json.dumps({"return": {"status": 200,
                                                   "message": "تسویه شد"}})):
            res = iran.run_action(self.ws, "kavenegar", "account_info", {})
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], 200)
        u = iran.usage_of(self.ws, "kavenegar")
        self.assertEqual(u["requests"], 1)
        self.assertEqual(u["ok"], 1)
        self.assertEqual(u["fail"], 0)
        self.assertEqual(u["last_action"], "account_info")
        self.assertEqual(u["last_status"], 200)
        self.assertNotIn("KEY-ABCD1234", json.dumps(res))  # no key leak

    def test_usage_persisted_to_vault(self):
        with self.stub(200, json.dumps({"result": 100, "trackId": "99"})):
            iran.run_action(self.ws, "zibal", "sandbox_test", {})
        raw = json.loads((self.ws / ".nova" / "iran_services.json")
                         .read_text(encoding="utf-8"))
        self.assertEqual(raw["usage"]["zibal"]["requests"], 1)
        self.assertEqual(raw["usage"]["zibal"]["ok"], 1)

    def test_api_error_body_metered_as_fail(self):
        with self.stub(412, json.dumps({"return": {"status": 412,
                                                   "message": "کلید نامعتبر"}})):
            res = iran.run_action(self.ws, "kavenegar", "account_info", {})
        self.assertFalse(res["ok"])
        self.assertIn("412", res["error"])
        u = iran.usage_of(self.ws, "kavenegar")
        self.assertEqual(u["fail"], 1)
        self.assertIn("412", u["last_error"])

    def test_transport_error_metered(self):
        with self.stub(0, "", "connection refused"):
            res = iran.run_action(self.ws, "kavenegar", "account_info", {})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "connection refused")

    def test_missing_key_persian_hint(self):
        iran.del_key(self.ws, "kavenegar")
        with self.stub(200, "{}"):
            res = iran.run_action(self.ws, "kavenegar", "account_info", {})
        self.assertFalse(res["ok"])
        self.assertIn("تنظیم نشده", res["error"])
        # NOT metered as a request - nothing left the machine
        self.assertEqual(iran.usage_of(self.ws, "kavenegar").get("requests", 0), 0)

    def test_no_key_action_runs_keyless(self):
        with self.stub(200, json.dumps({"mostviewedvideos": []})):
            res = iran.run_action(self.ws, "aparat", "most_viewed", {})
        self.assertTrue(res["ok"])

    def test_unknown_action_no_network(self):
        res = iran.run_action(self.ws, "kavenegar", "nosuch", {})
        self.assertFalse(res["ok"])
        self.assertIn("unknown action", res["error"])

    def test_zarinpal_link_extraction(self):
        iran.set_key(self.ws, "zarinpal", "MERCH-X")
        with self.stub(200, json.dumps(
                {"data": {"code": 100, "authority": "A00012345"}})):
            res = iran.run_action(self.ws, "zarinpal", "create_payment",
                                  {"amount": "500000",
                                   "callback": "https://x/cb"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["fields"]["authority"], "A00012345")
        self.assertEqual(res["link"],
                         "https://www.zarinpal.com/pg/StartPay/A00012345")


class TestTestKey(_StubHTTP):
    def test_safe_test_runs_safe_action(self):
        iran.set_key(self.ws, "bale", "B-TOKEN")
        with self.stub(200, json.dumps({"ok": True,
                                        "result": {"id": 42}})) as mh:
            res = iran.test_key(self.ws, "bale")
        self.assertTrue(res["ok"])
        url = mh.call_args[0][0]["url"]
        self.assertIn("/getMe", url)

    def test_no_free_test_is_honest(self):
        res = iran.test_key(self.ws, "melipayamak")
        self.assertFalse(res["ok"])
        self.assertIn("تست رایگان ندارد", res["error"])
        self.assertEqual(iran.usage_of(self.ws, "melipayamak"), {})


# --------------------------------------------------------------- web + CLI
class TestWebSurface(_WSTestCase):
    def test_web_state_shape_masked(self):
        iran.set_key(self.ws, "kavenegar", "SECRET-9999")
        st = iran.web_state(self.ws)
        self.assertEqual(st["count"], 20)
        self.assertEqual(len(st["categories"]), 6)
        k = next(s for s in st["services"] if s["id"] == "kavenegar")
        self.assertTrue(k["key_set"])
        self.assertEqual(k["key_masked"], "...9999")
        self.assertEqual(k["category"], "sms")
        self.assertTrue(k["actions"])
        a = k["actions"][0]
        self.assertIn("params", a)
        raw = json.dumps(st)
        self.assertNotIn("SECRET-9999", raw)   # the full key NEVER ships

    def test_web_state_error_never_leaks(self):
        st = nova.web_iran_state(SimpleNamespace(ws=str(self.ws)))
        self.assertIn("services", st)

    def test_web_action_set_del(self):
        ok, p, s = iran.web_action(
            self.ws, {"action": "set_key", "service": "kavenegar",
                      "key": "KEY-9999"})
        self.assertTrue(ok)
        self.assertEqual(p["key_masked"], "...9999")
        ok, _, _ = iran.web_action(self.ws,
                                   {"action": "del_key",
                                    "service": "kavenegar"})
        self.assertTrue(ok)
        self.assertFalse(iran.key_status(self.ws, "kavenegar")[0])

    def test_web_action_unknown_service_404(self):
        ok, p, s = iran.web_action(self.ws,
                                   {"action": "test", "service": "nope"})
        self.assertFalse(ok)
        self.assertEqual(s, 404)

    def test_web_action_bad_action_400(self):
        ok, _, s = iran.web_action(self.ws,
                                   {"action": "frobnicate",
                                    "service": "bale"})
        self.assertFalse(ok)
        self.assertEqual(s, 400)

    def test_web_action_test_and_call(self):
        iran.set_key(self.ws, "bale", "B-TOKEN")
        with mock.patch.object(iran, "_http",
                               return_value=(200,
                                             json.dumps({"ok": True}), None)):
            ok, res, s = iran.web_action(self.ws,
                                         {"action": "test",
                                          "service": "bale"})
            self.assertTrue(ok)
            self.assertTrue(res["ok"])
            ok, res, s = iran.web_action(
                self.ws, {"action": "call", "service": "bale",
                          "ir_action": "send_message",
                          "params": {"chat_id": "5", "text": "سلام"}})
            self.assertTrue(ok)
            self.assertTrue(res["ok"])

    def test_web_action_call_strips_empty_params(self):
        iran.set_key(self.ws, "kavenegar", "KK-12345")
        with mock.patch.object(iran, "_http",
                               return_value=(200, json.dumps(
                                   {"return": {"status": 200}}), None)) as mh:
            ok, res, s = iran.web_action(
                self.ws, {"action": "call", "service": "kavenegar",
                          "ir_action": "send_sms",
                          "params": {"receptor": "0912", "message": "hi",
                                     "sender": "  "}})
            self.assertTrue(ok)
            body = mh.call_args[0][0]
            self.assertIn("receptor=0912", body["url"])
            self.assertNotIn("sender=", body["url"])

    def test_nova_web_iran_action_missing_module_degrades(self):
        with mock.patch.object(nova, "iran", None):
            st = nova.web_iran_state(SimpleNamespace(ws=str(self.ws)))
            self.assertIn("error", st)
            ok, p, s = nova.web_iran_action(
                SimpleNamespace(ws=str(self.ws)), {"action": "test",
                                                   "service": "bale"})
            self.assertFalse(ok)
            self.assertEqual(s, 501)


class TestCli(_WSTestCase):
    def test_services_registered_model_briefed(self):
        t = next(t for t in nova.TOOLS if t.get("cmd") == "/services")
        self.assertTrue(t.get("model"))
        self.assertTrue(t.get("mhelp"))
        self.assertIn("test", t["mhelp"])

    def test_cmd_services_list_and_key(self):
        sess = SimpleNamespace(ws=str(self.ws))
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_services(sess, "")
        out = buf.getvalue()
        self.assertIn("کاوه نگار", out)
        self.assertIn("kavenegar", out)
        self.assertIn("زرین‌پال", out)
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_services(sess, "key kavenegar CLI-KEY-77")
        out = buf.getvalue()
        self.assertIn("ذخیره شد", out)
        self.assertEqual(iran.key_of(self.ws, "kavenegar"), "CLI-KEY-77")

    def test_cmd_services_test_call(self):
        sess = SimpleNamespace(ws=str(self.ws))
        iran.set_key(self.ws, "bale", "B-TOK")
        with mock.patch.object(iran, "_http",
                               return_value=(200, json.dumps(
                                   {"ok": True}), None)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                nova.cmd_services(sess, "test bale")
            self.assertIn("OK", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                nova.cmd_services(
                    sess, 'call bale send_message chat_id=1 text="سلام Nova"')
            self.assertIn("OK", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_services(sess, "test melipayamak")
        self.assertIn("تست رایگان ندارد", buf.getvalue())

    def test_cmd_services_bad_service(self):
        sess = SimpleNamespace(ws=str(self.ws))
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_services(sess, "test nope")
        self.assertIn("unknown", buf.getvalue())


# --------------------------------------------------------------- versions
class TestVersions(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(iran.VERSION, "1.0")

    def test_headline_named_in_header(self):
        src = (APP / "nova.py").read_text(encoding="utf-8")
        self.assertIn("v7.11: IRANIAN SERVICES", src)
        self.assertIn("nova_iran_services.py", src)


if __name__ == "__main__":
    unittest.main()
