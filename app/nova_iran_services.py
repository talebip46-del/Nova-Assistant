#!/usr/bin/env python3
# =====================================================================
#  Nova - Iranian service providers with API keys (v7.11.0)
#  The user's ask: "for EVERY kind of task I want to grab API keys from
#  several trusted Iranian sites - Kavenegar for SMS, payment, maps,
#  crypto, bots, video... don't limit it to the names I say."
#
#  WHAT THIS IS (and is not):
#    - nova_providers.py = the BRAIN providers (LLM clouds). This module
#      = Iranian WEB SERVICES the agent can actually DO things with:
#      send SMS, create payment links, route on the map, read crypto
#      prices, drive Iranian messenger bots, search Aparat.
#    - ONE catalog (IRAN_SERVICES) with request TEMPLATES per action.
#      build_request() is PURE (offline-testable); run_action() only
#      adds the network call + usage metering.
#    - KEYS live in the workspace vault  <ws>/.nova/iran_services.json
#      (chmod 600 on POSIX, atomic writes, cross-process file_lock -
#      the exact same discipline as the provider vault). A full key
#      NEVER reaches logs, the web UI or error messages (redacted).
#    - USAGE METERING per service: requests / ok / fail / last status /
#      last error / latency - visible in the web panel, so the user can
#      see exactly what was consumed (the v7.9 law: nothing hides).
#    - SAFE TESTS: every service may define ONE "safe" action (getMe,
#      account info, public market data, sandbox payment). The test
#      button runs exactly that - never something that costs money.
#
#  Zero dependencies. Missing file = Nova boots exactly as before.
#  This module never prints: ServiceError carries a short user-readable
#  message; nova.py decides how to show it (terminal / web).
# =====================================================================
import json
import os
import re
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import nova_atomic as natom
except Exception:
    natom = None

VERSION = "1.0"
MAX_KEY_LEN = 400
MAX_BODY = 2 * 1024 * 1024          # 2 MB response cap
CONFIG_FILE = "iran_services.json"
MAX_CONFIG_BYTES = 256 * 1024
UA = "Nova-Assistant/7.11 (+iran-services)"

TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(\??)\}")


class ServiceError(Exception):
    """A clean, user-readable service problem (unknown service/action,
    missing key, missing/unknown parameter, HTTP failure). Never a raw
    traceback - and never a leaked key."""


# --------------------------------------------------------------- categories
CATEGORIES = [
    ("sms", "پیامک و پیام‌رسانی"),
    ("pay", "پرداخت و درگاه"),
    ("map", "نقشه و مسیریابی"),
    ("crypto", "رمزارز و قیمت لحظه‌ای"),
    ("bot", "ربات پیام‌رسان‌های ایرانی"),
    ("video", "ویدیو"),
]
CATEGORY_LABELS = dict(CATEGORIES)


# --------------------------------------------------------------- the catalog
# Every entry: label/en (names), category, site/panel/docs (where the user
# grabs the key), key_env (optional env override), key_names/key_hint (what
# the user is looking for), actions {action_id -> request template}.
#
# Template tokens:  {key} = the stored key (never printed),  {ts} = unix ts,
# {name} = a user parameter,  {name?} = optional (entry DROPPED when empty).
# "form" = x-www-form-urlencoded body; "body" = JSON body; "query" = GET qs.
# "json_params": values the user may pass as a raw JSON string which must
#                become a real JSON object/list in the body (arrays, ints).
# "path_encode": URL-path parameters that must be percent-encoded.
# "safe": True  -> free, no side effect - the TEST button runs this one.
# "no_key": True -> public endpoint, works with no key at all.
# "ok_check": data-driven success rule ("dig_in": value at path in values,
#             "field": field equals value); default = HTTP 2xx.
# "extract" + "link_tpl"/"link_field": surface the useful bits (authority,
#             trackId, trans_id, payment link...) instead of raw JSON.
IRAN_SERVICES = {
    # ================= پیامک =================
    "kavenegar": {
        "label": "کاوه نگار", "en": "Kavenegar", "category": "sms",
        "site": "https://kavenegar.com",
        "panel": "https://panel.kavenegar.com/Client/Setting/Api",
        "docs": "https://kavenegar.com/rest-api.html",
        "key_env": "KAVENEGAR_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل کاوه‌نگار ← تنظیمات ← API Key",
        "actions": {
            "send_sms": {
                "desc": "ارسال پیامک (چند شماره را با کاما جدا کنید)",
                "method": "GET",
                "url": "https://api.kavenegar.com/v1/{key}/sms/send.json",
                "query": {"receptor": "{receptor}", "message": "{message}",
                          "sender": "{sender?}"},
                "required": ["receptor", "message"],
                "optional": ["sender"],
                "ok_check": {"kind": "dig_in", "path": "return.status",
                             "values": [200]},
            },
            "account_info": {
                "desc": "اطلاعات حساب - تست رایگان کلید",
                "method": "GET",
                "url": "https://api.kavenegar.com/v1/{key}/account/info.json",
                "required": [],
                "safe": True,
                "ok_check": {"kind": "dig_in", "path": "return.status",
                             "values": [200]},
            },
        },
    },
    "melipayamak": {
        "label": "ملی پیامک", "en": "MeliPayamak", "category": "sms",
        "site": "https://www.melipayamak.com",
        "panel": "https://console.melipayamak.com",
        "docs": "https://github.com/melipayamak",
        "key_env": "MELIPAYAMAK_API_KEY",
        "key_names": ["کلید وب‌سرویس کنسول"],
        "key_hint": "کنسول ملی‌پیامک ← توسعه‌دهندگان ← کلید وب‌سرویس",
        "actions": {
            "send_sms": {
                "desc": "ارسال پیامک (کنسول جدید)",
                "method": "POST",
                "url": "https://console.melipayamak.com/api/send/simple/{key}",
                "body": {"from": "{from}", "to": "{to}", "text": "{text}"},
                "required": ["from", "to", "text"],
            },
        },
    },
    "ghasedak": {
        "label": "قاصدک", "en": "Ghasedak", "category": "sms",
        "site": "https://ghasedak.me", "panel": "https://ghasedak.me",
        "docs": "https://ghasedak.me/dev",
        "key_env": "GHASEDAK_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل قاصدک ← حساب کاربری ← کلید API",
        "actions": {
            "send_sms": {
                "desc": "ارسال پیامک ساده از یک خط",
                "method": "POST",
                "url": "https://api.ghasedak.me/v2/sms/send/simple",
                "headers": {"apikey": "{key}"},
                "form": {"message": "{message}", "receptor": "{receptor}",
                         "linenumber": "{linenumber}"},
                "required": ["message", "receptor", "linenumber"],
            },
        },
    },
    "smsir": {
        "label": "SMS.ir", "en": "SMS.ir", "category": "sms",
        "site": "https://sms.ir", "panel": "https://sms.ir/panel",
        "docs": "https://app.sms.ir/developer-guide",
        "key_env": "SMSIR_API_KEY",
        "key_names": ["X-API-KEY"],
        "key_hint": "پنل SMS.ir ← توسعه‌دهندگان ← کلید API",
        "actions": {
            "send_verify": {
                "desc": "کد تایید با قالب (parameters مثال: "
                        "[{\"name\":\"CODE\",\"value\":\"123\"}])",
                "method": "POST",
                "url": "https://api.sms.ir/v1/send/verify",
                "headers": {"X-API-KEY": "{key}"},
                "body": {"mobile": "{mobile}", "templateId": "{template_id}",
                         "parameters": "{parameters?}"},
                "required": ["mobile", "template_id"],
                "optional": ["parameters"],
                "json_params": ["parameters", "template_id"],
            },
            "send_bulk": {
                "desc": "ارسال انبوه (phones مثال: [\"0912...\"])",
                "method": "POST",
                "url": "https://api.sms.ir/v1/send/bulk",
                "headers": {"X-API-KEY": "{key}"},
                "body": {"phone": "{phones}", "message": "{message}",
                         "lineNumber": "{line_number?}"},
                "required": ["phones", "message"],
                "optional": ["line_number"],
                "json_params": ["phones"],
            },
        },
    },
    "farazsms": {
        "label": "فراز اس‌ام‌اس", "en": "FarazSMS", "category": "sms",
        "site": "https://farazsms.com", "panel": "http://panel.farazsms.com",
        "docs": "https://farazsms.com/webservice-v2/",
        "key_env": "FARAZ_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل فراز ← راهنمای وب‌سرویس (REST v2)",
        "actions": {
            "send_sms": {
                "desc": "ارسال پیامک (REST v2)",
                "method": "POST",
                "url": "https://api2.farazsms.com/api/v2/{key}/send/simple/",
                "body": {"origin": "{from}", "destination": "{to}",
                         "message": "{message}"},
                "required": ["from", "to", "message"],
            },
        },
    },

    # ================= پرداخت =================
    "zarinpal": {
        "label": "زرین‌پال", "en": "Zarinpal", "category": "pay",
        "site": "https://www.zarinpal.com",
        "panel": "https://www.zarinpal.com/console",
        "docs": "https://docs.zarinpal.com",
        "key_env": "ZARINPAL_MERCHANT_ID",
        "key_names": ["Merchant ID (مرچنت)"],
        "key_hint": "کنسول زرین‌پال ← درگاه‌ها ← شناسه مرچنت",
        "actions": {
            "create_payment": {
                "desc": "ساخت درخواست پرداخت و لینک درگاه (مبلغ به تومان؛ "
                        "ساخت لینک هزینه‌ای ندارد)",
                "method": "POST",
                "url": "https://api.zarinpal.com/pg/v4/payment/request.json",
                "body": {"merchant_id": "{key}", "amount": "{amount}",
                         "callback_url": "{callback}",
                         "description": "{description?}"},
                "required": ["amount", "callback"],
                "optional": ["description"],
                "json_params": ["amount"],
                "extract": [{"field": "authority", "path": "data.authority"}],
                "link_tpl": "https://www.zarinpal.com/pg/StartPay/{authority}",
                "ok_check": {"kind": "dig_in", "path": "data.code",
                             "values": [100, 101]},
            },
        },
    },
    "idpay": {
        "label": "آیدی‌پی", "en": "IDPay", "category": "pay",
        "site": "https://idpay.ir", "panel": "https://panel.idpay.ir",
        "docs": "https://idpay.ir/web-service",
        "key_env": "IDPAY_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل آیدی‌پی ← فروشندگان ← کلید API",
        "actions": {
            "create_payment": {
                "desc": "ساخت پرداخت (order_id دلخواه، amount به تومان؛ "
                        "sandbox=1 برای تست)",
                "method": "POST",
                "url": "https://api.idpay.ir/v1.1/payment",
                "headers": {"X-API-KEY": "{key}", "X-SANDBOX": "{sandbox?}"},
                "body": {"order_id": "{order_id}", "amount": "{amount}",
                         "callback": "{callback?}"},
                "required": ["order_id", "amount"],
                "optional": ["sandbox", "callback"],
                "json_params": ["amount"],
                "extract": [{"field": "id", "path": "id"},
                            {"field": "link", "path": "link"}],
                "link_field": "link",
            },
            "sandbox_test": {
                "desc": "تست رایگان کلید در حالت سندباکس (بدون هزینه)",
                "method": "POST",
                "url": "https://api.idpay.ir/v1.1/payment",
                "headers": {"X-API-KEY": "{key}", "X-SANDBOX": "1"},
                "body": {"order_id": "nova-{ts}", "amount": 15000,
                         "callback": "https://example.com/callback"},
                "required": [],
                "safe": True,
                "extract": [{"field": "id", "path": "id"},
                            {"field": "link", "path": "link"}],
            },
        },
    },
    "zibal": {
        "label": "زیبال", "en": "Zibal", "category": "pay",
        "site": "https://zibal.ir", "panel": "https://zibal.ir/panel",
        "docs": "https://docs.zibal.ir",
        "key_env": "ZIBAL_MERCHANT",
        "key_names": ["Merchant (مرچنت)"],
        "key_hint": "پنل زیبال ← درگاه‌ها ← مرچنت",
        "actions": {
            "create_payment": {
                "desc": "ساخت درخواست پرداخت (amount به تومان)",
                "method": "POST",
                "url": "https://gateway.zibal.ir/v1/request",
                "body": {"merchant": "{key}", "amount": "{amount}",
                         "callbackUrl": "{callback?}",
                         "description": "{description?}"},
                "required": ["amount"],
                "optional": ["callback", "description"],
                "json_params": ["amount"],
                "extract": [{"field": "trackId", "path": "trackId"}],
                "link_tpl": "https://gateway.zibal.ir/start/{trackId}",
                "ok_check": {"kind": "dig_in", "path": "result",
                             "values": [100]},
            },
            "sandbox_test": {
                "desc": "تست رایگان با مرچنت آزمایشی zibal (بدون کلید هم کار می‌کند)",
                "method": "POST",
                "url": "https://gateway.zibal.ir/v1/request",
                "body": {"merchant": "zibal", "amount": 1000,
                         "callbackUrl": "https://example.com/callback",
                         "description": "Nova sandbox test"},
                "required": [],
                "no_key": True,
                "safe": True,
                "extract": [{"field": "trackId", "path": "trackId"}],
                "ok_check": {"kind": "dig_in", "path": "result",
                             "values": [100]},
            },
        },
    },
    "nextpay": {
        "label": "نکست‌پی", "en": "NextPay", "category": "pay",
        "site": "https://nextpay.org", "panel": "https://nextpay.org/panel",
        "docs": "https://nextpay.org/dev",
        "key_env": "NEXTPAY_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل نکست‌پی ← درگاه‌ها ← API Key",
        "actions": {
            "create_payment": {
                "desc": "ساخت درخواست پرداخت (amount به تومان)",
                "method": "POST",
                "url": "https://nextpay.org/nx/gateway/token",
                "body": {"api_key": "{key}", "amount": "{amount}",
                         "order_id": "{order_id?}",
                         "callback_uri": "{callback}"},
                "required": ["amount", "callback"],
                "optional": ["order_id"],
                "json_params": ["amount"],
                "extract": [{"field": "trans_id", "path": "trans_id"}],
                "link_tpl": "https://nextpay.org/nx/gateway/payment/{trans_id}",
                "ok_check": {"kind": "dig_in", "path": "code",
                             "values": [-1]},
            },
        },
    },
    "payping": {
        "label": "پی‌پینگ", "en": "PayPing", "category": "pay",
        "site": "https://www.payping.ir", "panel": "https://www.payping.ir/panel",
        "docs": "https://www.payping.ir/apidoc",
        "key_env": "PAYPING_API_KEY",
        "key_names": ["Bearer Token"],
        "key_hint": "پنل پی‌پینگ ← تنظیمات ← توکن API",
        "actions": {
            "create_payment": {
                "desc": "ساخت درخواست پرداخت (amount به تومان)",
                "method": "POST",
                "url": "https://api.payping.ir/v2/pay",
                "headers": {"Authorization": "Bearer {key}"},
                "body": {"amount": "{amount}", "returnUrl": "{callback}",
                         "description": "{description?}"},
                "required": ["amount", "callback"],
                "optional": ["description"],
                "json_params": ["amount"],
                "extract": [{"field": "code", "path": "code"}],
                "link_tpl": "https://api.payping.ir/v2/pay/gotoipg/{code}",
            },
        },
    },

    # ================= نقشه و مسیریابی =================
    "neshan": {
        "label": "نشان", "en": "Neshan", "category": "map",
        "site": "https://neshan.org", "panel": "https://platform.neshan.org",
        "docs": "https://docs.neshan.org",
        "key_env": "NESHAN_API_KEY",
        "key_names": ["Api-Key"],
        "key_hint": "پلتفرم نشان ← سرویس‌ها ← کلید API",
        "actions": {
            "search": {
                "desc": "جست‌وجوی مکان (عبارت + مرکز نقشه lat,lng)",
                "method": "GET",
                "url": "https://api.neshan.org/v1/search",
                "headers": {"Api-Key": "{key}"},
                "query": {"term": "{term}", "lat": "{lat}", "lng": "{lng}"},
                "required": ["term", "lat", "lng"],
                "defaults": {"term": "تهران", "lat": "35.6892",
                             "lng": "51.389"},
                "safe": True,
            },
            "directions": {
                "desc": "مسیریابی (origin/destination به شکل lat,lng)",
                "method": "GET",
                "url": "https://api.neshan.org/v4/directions",
                "headers": {"Api-Key": "{key}"},
                "query": {"origin": "{origin}", "destination": "{destination}",
                          "avoidTrafficZone": "{avoid_traffic?}"},
                "required": ["origin", "destination"],
                "optional": ["avoid_traffic"],
            },
            "reverse": {
                "desc": "تبدیل مختصات به آدرس (reverse geocode)",
                "method": "GET",
                "url": "https://api.neshan.org/v2/reverse",
                "headers": {"Api-Key": "{key}"},
                "query": {"lat": "{lat}", "lng": "{lng}"},
                "required": ["lat", "lng"],
            },
        },
    },
    "mapir": {
        "label": "مپ‌ای‌آر (نقشه ایران)", "en": "Map.ir", "category": "map",
        "site": "https://map.ir", "panel": "https://map.ir",
        "docs": "https://map.ir/services/rest/",
        "key_env": "MAPIR_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل map.ir ← کلید API (هدر MAP-IR-API-KEY)",
        "actions": {
            "search": {
                "desc": "جست‌وجوی خودکار مکان",
                "method": "GET",
                "url": "https://map.ir/search/v2/auto-complete",
                "headers": {"MAP-IR-API-KEY": "{key}"},
                "query": {"text": "{text}"},
                "required": ["text"],
            },
            "route": {
                "desc": "مسیریابی OSRM (مختصات به شکل lng,lat)",
                "method": "GET",
                "url": "https://map.ir/routes/route/v1/driving/"
                       "{lng1},{lat1};{lng2},{lat2}",
                "headers": {"MAP-IR-API-KEY": "{key}"},
                "required": ["lng1", "lat1", "lng2", "lat2"],
                # v8.0: path params are percent-encoded - raw substitution
                # let a value containing ?/#/.. silently rewrite the
                # request path (the same guard aparat already had).
                "path_encode": ["lng1", "lat1", "lng2", "lat2"],
            },
        },
    },

    # ================= رمزارز =================
    "nobitex": {
        "label": "نوبیتکس", "en": "Nobitex", "category": "crypto",
        "site": "https://nobitex.ir", "panel": "https://nobitex.ir/panel",
        "docs": "https://api.nobitex.ir",
        "key_env": "NOBITEX_API_KEY",
        "key_names": ["API Token"],
        "key_hint": "پنل نوبیتکس ← تنظیمات ← توکن API",
        "actions": {
            "market_stats": {
                "desc": "قیمت لحظه‌ای بازار (بدون کلید) - مثال: "
                        "src=btc,eth dst=rls",
                "method": "POST",
                "url": "https://api.nobitex.ir/market/stats",
                "body": {"srcCurrency": "{src}", "dstCurrency": "{dst}"},
                "required": [],
                "defaults": {"src": "btc,usdt,eth", "dst": "rls"},
                "no_key": True,
                "safe": True,
            },
            "wallets": {
                "desc": "کیف پول‌ها و موجودی (نیاز به کلید)",
                "method": "POST",
                "url": "https://api.nobitex.ir/wallets/list",
                "headers": {"Authorization": "Token {key}"},
                "required": [],
            },
        },
    },
    "wallex": {
        "label": "والکس", "en": "Wallex", "category": "crypto",
        "site": "https://wallex.ir", "panel": "https://wallex.ir",
        "docs": "https://api.wallex.ir",
        "key_env": "WALLEX_API_KEY",
        "key_names": ["X-API-KEY"],
        "key_hint": "پنل والکس ← امنیت ← کلید API",
        "actions": {
            "markets": {
                "desc": "بازارها و قیمت‌ها (بدون کلید)",
                "method": "GET",
                "url": "https://api.wallex.ir/v1/markets",
                "required": [],
                "no_key": True,
                "safe": True,
            },
            "balances": {
                "desc": "موجودی حساب (نیاز به کلید)",
                "method": "GET",
                "url": "https://api.wallex.ir/v1/account/balances",
                "headers": {"X-API-KEY": "{key}"},
                "required": [],
            },
        },
    },
    "bitpin": {
        "label": "بیت‌پین", "en": "Bitpin", "category": "crypto",
        "site": "https://bitpin.ir", "panel": "https://bitpin.ir",
        "docs": "https://api.bitpin.ir",
        "key_env": "BITPIN_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل بیت‌پین ← تنظیمات ← کلید API",
        "actions": {
            "markets": {
                "desc": "بازارها و قیمت‌ها (بدون کلید)",
                "method": "GET",
                "url": "https://api.bitpin.ir/v1/mkt/markets",
                "required": [],
                "no_key": True,
                "safe": True,
            },
        },
    },
    "ramzinex": {
        "label": "رمزینکس", "en": "Ramzinex", "category": "crypto",
        "site": "https://ramzinex.ir", "panel": "https://ramzinex.ir",
        "docs": "https://publicapi.ramzinex.com",
        "key_env": "RAMZINEX_API_KEY",
        "key_names": ["API Key"],
        "key_hint": "پنل رمزینکس ← حساب ← کلید API",
        "actions": {
            "pairs": {
                "desc": "جفت‌ارزها و قیمت‌ها (بدون کلید)",
                "method": "GET",
                "url": "https://publicapi.ramzinex.com/exchange/api/v1.0/"
                       "exchange/pairs",
                "required": [],
                "no_key": True,
                "safe": True,
            },
        },
    },

    # ================= ربات پیام‌رسان‌های ایرانی =================
    "bale": {
        "label": "بله (ربات)", "en": "Bale Bot", "category": "bot",
        "site": "https://bale.ai", "panel": "https://bale.ai",
        "docs": "https://docs.bale.ai",
        "key_env": "BALE_BOT_TOKEN",
        "key_names": ["Bot Token"],
        "key_hint": "بله ← BotFather ← توکن ربات",
        "actions": {
            "get_me": {
                "desc": "اطلاعات ربات - تست رایگان کلید",
                "method": "GET",
                "url": "https://tapi.bale.ai/bot{key}/getMe",
                "required": [],
                "safe": True,
                "ok_check": {"kind": "field", "name": "ok", "value": True},
            },
            "send_message": {
                "desc": "ارسال پیام به یک گفت‌وگو (chat_id + text)",
                "method": "POST",
                "url": "https://tapi.bale.ai/bot{key}/sendMessage",
                "body": {"chat_id": "{chat_id}", "text": "{text}"},
                "required": ["chat_id", "text"],
                "ok_check": {"kind": "field", "name": "ok", "value": True},
            },
        },
    },
    "eitaa": {
        "label": "ایتا (ایتایار)", "en": "Eitaa", "category": "bot",
        "site": "https://eitaa.com", "panel": "https://eitaayar.ir",
        "docs": "https://docs.eitaayar.ir",
        "key_env": "EITAA_TOKEN",
        "key_names": ["Token"],
        "key_hint": "ایتایار ← توکن ارسال پیام",
        "actions": {
            "send_message": {
                "desc": "ارسال پیام به کانال/گفت‌وگو",
                "method": "POST",
                "url": "https://eitaayar.ir/api/{key}/sendMessage",
                "form": {"chat_id": "{chat_id}", "text": "{text}"},
                "required": ["chat_id", "text"],
            },
        },
    },
    "rubika": {
        "label": "روبیکا (ربات)", "en": "Rubika Bot", "category": "bot",
        "site": "https://rubika.ir", "panel": "https://rubika.ir",
        "docs": "https://rubika.ir",
        "key_env": "RUBIKA_BOT_TOKEN",
        "key_names": ["Bot Token"],
        "key_hint": "روبیکا ← BotFather روبیکا ← توکن ربات (v3)",
        "actions": {
            "get_me": {
                "desc": "اطلاعات ربات - تست رایگان کلید",
                "method": "POST",
                "url": "https://botapi.rubika.ir/v3/{key}/getMe",
                "required": [],
                "safe": True,
            },
            "send_message": {
                "desc": "ارسال پیام به یک گفت‌وگو",
                "method": "POST",
                "url": "https://botapi.rubika.ir/v3/{key}/sendMessage",
                "body": {"chat_id": "{chat_id}", "text": "{text}"},
                "required": ["chat_id", "text"],
            },
        },
    },

    # ================= ویدیو =================
    "aparat": {
        "label": "آپارات", "en": "Aparat", "category": "video",
        "site": "https://www.aparat.com", "panel": "https://www.aparat.com",
        "docs": "https://www.aparat.com/etc/api",
        "key_env": None,
        "key_names": [],
        "key_hint": "آپارات به کلید نیاز ندارد (API عمومی)",
        "needs_key": False,
        "actions": {
            "most_viewed": {
                "desc": "پربازدیدترین ویدیوهای آپارات (بدون کلید؛ "
                        "جست‌وجوی عمومی آپارات فعلاً بسته است)",
                "method": "GET",
                "url": "https://www.aparat.com/etc/api/mostViewedVideos",
                "required": [],
                "no_key": True,
                "safe": True,
            },
            "user_videos": {
                "desc": "ویدیوهای یک کانال (نام کاربری)",
                "method": "GET",
                "url": "https://www.aparat.com/etc/api/videoByUser/{user}",
                "path_encode": ["user"],
                "required": ["user"],
                "no_key": True,
            },
        },
    },
}

# Persian labels for every parameter the UI renders - one dict, all
# services share it (a param name means the same thing everywhere).
PARAM_FA = {
    "receptor": "شماره گیرنده", "message": "متن پیام", "sender": "خط ارسال",
    "from": "خط فرستنده", "to": "شماره گیرنده", "text": "متن",
    "linenumber": "شماره خط", "mobile": "شماره موبایل",
    "template_id": "شناسه قالب", "parameters": "پارامترهای قالب (JSON)",
    "phones": "لیست شماره‌ها (JSON)", "line_number": "شماره خط",
    "amount": "مبلغ (تومان)", "callback": "آدرس بازگشت",
    "description": "توضیحات", "order_id": "شناسه سفارش",
    "sandbox": "سندباکس (1 یا 0)", "term": "عبارت جست‌وجو",
    "lat": "عرض جغرافیایی", "lng": "طول جغرافیایی",
    "origin": "مبدأ (lat,lng)", "destination": "مقصد (lat,lng)",
    "avoid_traffic": "پرهیز از طرح ترافیک (true/false)",
    "lng1": "طول مبدأ", "lat1": "عرض مبدأ",
    "lng2": "طول مقصد", "lat2": "عرض مقصد",
    "src": "ارز مبدأ (مثال btc,eth)", "dst": "ارز مقصد (مثال rls)",
    "chat_id": "شناسه چت", "user": "نام کاربری کانال",
    "query": "عبارت جست‌وجو",
}


# --------------------------------------------------------------- registry
def names():
    """Every service id (catalog order)."""
    return list(IRAN_SERVICES.keys())


def entry(sid):
    """One service entry (a NEW dict) or None."""
    sid = (sid or "").strip().lower()
    e = IRAN_SERVICES.get(sid)
    return dict(e) if e else None


def actions_of(sid):
    """{action_id: action} for one service, or {}."""
    e = IRAN_SERVICES.get((sid or "").strip().lower())
    return dict(e.get("actions", {})) if e else {}


def safe_action(sid):
    """The ONE free/no-side-effect action id for the test button, or ''."""
    for aid, act in actions_of(sid).items():
        if act.get("safe"):
            return aid
    return ""


def _action_tokens(act):
    """Every parameter name the template references - the ALLOWED set.
    Unknown user params are rejected (typo protection)."""
    out = set()
    for v in [act.get("url", "")]:
        out |= {m.group(1) for m in TOKEN_RE.finditer(v)}
    for block in ("headers", "query", "body", "form"):
        for v in (act.get(block) or {}).values():
            if isinstance(v, str):
                out |= {m.group(1) for m in TOKEN_RE.finditer(v)}
    out |= set(act.get("defaults") or {})
    out.discard("key")
    return out


def _keep(template_value, params):
    """False when the whole value is ONE optional token {name?} and the
    param is empty/missing - that whole header/query/body entry drops."""
    m = TOKEN_RE.fullmatch(str(template_value))
    return not (m and m.group(2)) or bool(str(params.get(m.group(1), "")).strip())


def _sub_str(template, params):
    """Inline substitution: {key}/{ts}/{name}; {name?} collapses to ''."""
    def rep(m):
        name = m.group(1)
        return str(params.get(name, ""))
    return TOKEN_RE.sub(rep, str(template))


def _deep_sub(obj, params, json_params):
    """Walk the JSON body template. A string leaf that is EXACTLY one
    token AND that param is declared in json_params AND the user's raw
    value parses as JSON -> insert the parsed object (arrays/ints for
    sms.ir phones/templates, zarinpal amounts...). Everything else is a
    plain string substitution."""
    if isinstance(obj, dict):
        return {k: _deep_sub(v, params, json_params)
                for k, v in obj.items() if _keep(v, params)}
    if isinstance(obj, list):
        return [_deep_sub(v, params, json_params) for v in obj]
    if isinstance(obj, str):
        m = TOKEN_RE.fullmatch(obj)
        if m and m.group(1) in json_params:
            raw = params.get(m.group(1), "")
            try:
                return json.loads(raw)
            except Exception:
                return _sub_str(obj, params)
        return _sub_str(obj, params)
    return obj


def build_request(sid, action, params=None, key="", ts=None):
    """PURE template -> request dict {method,url,headers,data}. No
    network, no state - fully offline-testable. Raises ServiceError on
    unknown service/action, unknown or missing parameters."""
    svc = IRAN_SERVICES.get((sid or "").strip().lower())
    if not svc:
        raise ServiceError(f"unknown service '{sid}'")
    act = (svc.get("actions") or {}).get((action or "").strip().lower())
    if not act:
        raise ServiceError(
            f"unknown action '{action}' for '{sid}' "
            f"(available: {', '.join(svc.get('actions') or {})})")
    p = dict(params or {})
    # defaults fill missing/empty params BEFORE validation
    for k, v in (act.get("defaults") or {}).items():
        if not str(p.get(k, "")).strip():
            p[k] = v
    # typo guard: a param the template never references is an error
    allowed = _action_tokens(act)
    unknown = sorted(set(p) - allowed)
    if unknown:
        raise ServiceError(
            f"unknown parameter(s): {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(allowed)) or 'none'})")
    missing = [r for r in (act.get("required") or [])
               if not str(p.get(r, "")).strip()]
    if missing:
        raise ServiceError(
            "missing parameter(s): " + ", ".join(missing))
    p["key"] = key or ""
    p["ts"] = str(ts if ts is not None else int(time.time()))

    method = (act.get("method") or "GET").upper()
    path_enc = set(act.get("path_encode") or [])

    def sub_token(m):
        name = m.group(1)
        if name == "key":
            return p["key"]
        v = str(p.get(name, ""))
        return urllib.parse.quote(v, safe="") if name in path_enc else v
    url = TOKEN_RE.sub(sub_token, act["url"])
    if not url.startswith(("http://", "https://")):
        raise ServiceError(f"bad url for {sid}.{action}")

    headers = {"User-Agent": UA}
    for k, v in (act.get("headers") or {}).items():
        if _keep(v, p):
            headers[k] = _sub_str(v, p)

    query = {k: _sub_str(v, p) for k, v in (act.get("query") or {}).items()
             if _keep(v, p)}
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)

    data = None
    if act.get("form") is not None:
        pairs = {k: _sub_str(v, p) for k, v in act["form"].items()
                 if _keep(v, p)}
        data = urllib.parse.urlencode(pairs).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif act.get("body") is not None:
        jp = set(act.get("json_params") or [])
        body = _deep_sub(act["body"], p, jp)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    return {"method": method, "url": url, "headers": headers, "data": data,
            "action": act}


def _dig(obj, path):
    """data.authority / return.status walk - None when absent."""
    cur = obj
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _check_ok(act, status, data):
    """Data-driven success rule (per action) or plain HTTP 2xx."""
    c = act.get("ok_check")
    if not c:
        return 200 <= status < 300
    if c.get("kind") == "dig_in":
        return _dig(data, c.get("path", "")) in c.get("values", [])
    if c.get("kind") == "field":
        return _dig(data, c.get("name", "")) == c.get("value")
    return 200 <= status < 300


def _http(req, timeout):
    """The ONE network seam. Returns (status, text, transport_error).
    An HTTP 4xx/5xx is a RESPONSE (its JSON body often carries the real
    API error) - only DNS/socket/timeout failures land in error. The
    response is capped at MAX_BODY bytes."""
    try:
        r = urllib.request.Request(req["url"], data=req["data"],
                                   headers=req["headers"],
                                   method=req["method"])
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                return resp.status, "", "response too large (2 MB cap)"
            return resp.status, raw.decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read(102400).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body, None
    except Exception as e:
        return 0, "", str(e)[:300]


def _maybe_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def _redact(text, key):
    """The full key must NEVER survive into an error string / result."""
    t = str(text or "")
    if key:
        t = t.replace(key, "..." + key[-4:])
    return t[:400]


# --------------------------------------------------------------- key vault
# <ws>/.nova/iran_services.json  {"keys": {sid: key}, "usage": {...}}
_CFG = {"ws": None, "keys": {}, "usage": {}}
_CFG_LOCK = threading.RLock()


def config_path(ws):
    import pathlib
    return pathlib.Path(ws) / ".nova" / CONFIG_FILE


def _parse_cfg(raw):
    cfg = {"keys": {}, "usage": {}}
    if isinstance(raw, dict):
        for k in ("keys", "usage"):
            v = raw.get(k)
            if isinstance(v, dict):
                cfg[k] = {str(kk): vv for kk, vv in v.items()}
        # hostile tolerance: values must be sane shapes
        cfg["keys"] = {k: v for k, v in cfg["keys"].items()
                       if isinstance(k, str) and isinstance(v, str)}
        cfg["usage"] = {k: v for k, v in cfg["usage"].items()
                        if isinstance(k, str) and isinstance(v, dict)}
    return cfg


def load_state(ws):
    """(Re)load the vault. Fail-soft: a missing/broken file = empty."""
    with _CFG_LOCK:
        _CFG["keys"], _CFG["usage"] = {}, {}
        _CFG["ws"] = str(ws) if ws else None
        if not ws:
            return _CFG
        try:
            p = config_path(ws)
            if p.is_file() and p.stat().st_size <= MAX_CONFIG_BYTES:
                _CFG.update(_parse_cfg(json.loads(
                    p.read_text(encoding="utf-8", errors="replace"))))
                _CFG["ws"] = str(ws)
        except Exception:
            pass
    return _CFG


def _ensure(ws):
    """Lazy bind: functions receive ws per call; reload when it changed."""
    if _CFG.get("ws") != (str(ws) if ws else None):
        load_state(ws)


def _save_locked():
    ws = _CFG.get("ws")
    if not ws:
        return "no workspace"
    try:
        import pathlib
        p = pathlib.Path(ws) / ".nova" / CONFIG_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {"keys": _CFG.get("keys", {}), "usage": _CFG.get("usage", {})}
        err = (natom.write_text_atomic(p, json.dumps(
            body, indent=1, ensure_ascii=False)) if natom is not None
            else _fallback_write(p, json.dumps(
                body, indent=1, ensure_ascii=False)))
        if err:
            return err
        try:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)   # POSIX: keep secrets
        except OSError:
            pass
        return ""
    except OSError as e:
        return str(e)


def _fallback_write(p, text):
    try:
        tmp = p.with_name("%s.tmp%d" % (p.name, (os.getpid() * 7919
                                        + threading.get_ident() % 100000
                                        + int(time.time() * 1000))
                                       % 1000000))  # v7.14.1: unique across threads
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)


def _with_state(ws, fn):
    """fn(_CFG) under the in-process lock + cross-process file_lock,
    starting from a fresh disk read (the nova_providers discipline -
    REPL and web share one vault file)."""
    with _CFG_LOCK:
        _ensure(ws)
        lock_path = None
        if ws and natom is not None:
            try:
                lock_path = config_path(ws).parent / "iran_services.lock"
            except Exception:
                lock_path = None
        if lock_path is None:
            changed = fn(_CFG)
            return _save_locked() if changed else ""
        try:
            with natom.file_lock(lock_path, timeout=8.0):
                load_state(ws)
                changed = fn(_CFG)
                return _save_locked() if changed else ""
        except Exception:
            changed = fn(_CFG)          # documented fail-open (in-process)
            return _save_locked() if changed else ""


def key_source(ws, sid):
    """'' | 'file' | 'env' - where this service's key comes from."""
    _ensure(ws)
    k = _CFG["keys"].get(sid, "")
    if k:
        return "file"
    e = IRAN_SERVICES.get(sid) or {}
    if e.get("key_env") and os.environ.get(e["key_env"], "").strip():
        return "env"
    return ""


def key_of(ws, sid):
    """The actual key string ('' when unset). Env fallback after file."""
    _ensure(ws)
    k = _CFG["keys"].get(sid, "")
    if k:
        return k
    e = IRAN_SERVICES.get(sid) or {}
    if e.get("key_env"):
        return os.environ.get(e["key_env"], "").strip()
    return ""


def key_status(ws, sid):
    """(is_set, masked) - the full key NEVER leaves the module."""
    k = key_of(ws, sid)
    if not k:
        return (False, "")
    return (True, "..." + k[-4:] if len(k) > 4 else "...")


def set_key(ws, sid, value):
    """Store one service key in the workspace vault. Error string or ''."""
    if (sid or "").strip().lower() not in IRAN_SERVICES:
        return f"unknown service '{sid}'"
    v = (value or "").strip()[:MAX_KEY_LEN]
    if not v:
        return "empty key"

    def op(cfg):
        cfg["keys"][sid.strip().lower()] = v
        return True
    return _with_state(ws, op)


def del_key(ws, sid):
    """Remove a stored key (an env var, if any, takes over again)."""
    sid = (sid or "").strip().lower()
    if sid not in IRAN_SERVICES:
        return f"unknown service '{sid}'"

    def op(cfg):
        if sid in cfg["keys"]:
            cfg["keys"].pop(sid, None)
            return True
        return False
    return _with_state(ws, op)


# --------------------------------------------------------------- execution
def _bump_usage(ws, sid, action, ok, status, err, ms):
    """One metering tick per attempt - the panel shows what was spent.
    v8.0: defensive int coercion - a hand-edited vault with a non-numeric
    usage field ("requests": "12+") used to raise int() out of here and
    break run_action's never-raises contract."""
    def _num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    def op(cfg):
        u = cfg.setdefault("usage", {}).setdefault(sid, {})
        u["requests"] = _num(u.get("requests", 0)) + 1
        u["ok"] = _num(u.get("ok", 0)) + (1 if ok else 0)
        u["fail"] = _num(u.get("fail", 0)) + (0 if ok else 1)
        u["last_ts"] = int(time.time())
        u["last_action"] = action
        u["last_status"] = status
        u["last_ms"] = ms
        u["last_error"] = "" if ok else (err or "")[:300]
        return True
    return _with_state(ws, op)


def usage_of(ws, sid=None):
    """Metering snapshot (a copy - safe to ship to the browser)."""
    _ensure(ws)
    with _CFG_LOCK:
        u = _CFG.get("usage", {})
        if sid:
            return dict(u.get(sid, {}))
        return {k: dict(v) for k, v in u.items()}


def run_action(ws, sid, action, params=None, timeout=20):
    """Build + execute one service action, meter it, return a dict that
    is safe to print/ship: the key is redacted everywhere, data preview
    is capped. Never raises - failures come back as {"ok": False}."""
    sid = (sid or "").strip().lower()
    try:
        req = build_request(sid, action, params, key="", ts=int(time.time()))
        act = req.pop("action")
    except ServiceError as e:
        return {"ok": False, "service": sid, "action": action,
                "error": str(e)}
    # key check AFTER build validation (better errors first)
    needs_key = not act.get("no_key")
    key = key_of(ws, sid) if needs_key else ""
    if needs_key and not key:
        e = IRAN_SERVICES.get(sid) or {}
        return {"ok": False, "service": sid, "action": action,
                "error": f"کلید '{e.get('label', sid)}' تنظیم نشده است"
                         + (f" ({e.get('key_hint', '')})" if e.get("key_hint")
                            else "")}
    try:
        req = build_request(sid, action, params, key=key,
                            ts=int(time.time()))
        act = req.pop("action")
    except ServiceError as e:
        return {"ok": False, "service": sid, "action": action,
                "error": _redact(str(e), key)}

    t0 = time.time()
    # v8.10.1 fix: int(timeout or 20) raised ValueError on a non-numeric
    # timeout - the docstring promises run_action NEVER raises. Coerce
    # like the fail-soft laws everywhere else.
    try:
        _to = int(timeout or 20)
    except (TypeError, ValueError):
        _to = 20
    status, text, terr = _http(req, timeout=max(2, min(_to, 60)))
    ms = int((time.time() - t0) * 1000)
    data = _maybe_json(text)
    ok = _check_ok(act, status, data) if terr is None else False
    err = terr or "" if ok else (terr or _api_error(act, status, data, text))
    fields = {e["field"]: _dig(data, e["path"])
              for e in (act.get("extract") or [])}
    link = ""
    if ok:
        if act.get("link_field"):
            link = str(fields.get(act["link_field"]) or "")
        elif act.get("link_tpl"):
            link = act["link_tpl"]
            for f, v in fields.items():
                if v:
                    link = link.replace("{" + f + "}", str(v))
    # v8.0 (server-side twin of the UI guard): only real http(s) links
    # leave this module - a hostile upstream returning a javascript: or
    # data: "link" must never reach a clickable anchor anywhere.
    if link and not link.startswith(("http://", "https://")):
        link = ""
    _bump_usage(ws, sid, action, ok, status, _redact(err, key), ms)
    out = {"ok": ok, "service": sid, "action": action, "status": status,
           "ms": ms, "fields": fields, "link": link,
           "error": _redact(err, key) if err else ""}
    # capped preview of the raw answer (never the request!)
    if data is not None:
        try:
            js = json.dumps(data, ensure_ascii=False)
            out["data"] = data if len(js) <= 4000 else None
            out["data_preview"] = js[:4000]
        except Exception:
            pass
    return out


def _api_error(act, status, data, text):
    """Best-effort human message from the API's own error shapes."""
    if data is not None:
        for path in ("return.message", "data.message", "error", "message",
                     "error_message", "errors", "status", "result"):
            v = _dig(data, path)
            if v and not isinstance(v, (dict, list)):
                return f"HTTP {status}: {v}"
        if data.get("ok") is False:
            return f"HTTP {status}: error description not provided"
    if text and len(text) < 300:
        return f"HTTP {status}: {text.strip()}"
    return f"HTTP {status}"


def test_key(ws, sid, timeout=15):
    """The SAFE test: runs the service's one safe action (getMe /
    account info / public market data / sandbox payment). Never costs
    money. Returns run_action's dict (or an honest no-free-test note)."""
    sid = (sid or "").strip().lower()
    aid = safe_action(sid)
    if not aid:
        svc = IRAN_SERVICES.get(sid) or {}
        first = next(iter((svc.get("actions") or {})), "")
        return {"ok": False, "service": sid, "action": "",
                "error": f"این سرویس عملیات تست رایگان ندارد - "
                         f"از اکشن اصلی '{first}' استفاده کنید"
                if first else "unknown service"}
    return run_action(ws, sid, aid, params={}, timeout=timeout)


# --------------------------------------------------------------- web face
def web_state(ws):
    """Everything the web panel needs in ONE payload. Masked keys only,
    parameter metadata for the dynamic forms, per-service usage."""
    _ensure(ws)
    cats = [{"id": cid, "label": lab} for cid, lab in CATEGORIES]
    services = []
    for sid in names():
        e = IRAN_SERVICES[sid]
        is_set, masked = key_status(ws, sid)
        acts = []
        for aid, act in e.get("actions", {}).items():
            plist = []
            for pname in list(act.get("required") or []):
                plist.append({"name": pname, "req": True,
                              "desc": PARAM_FA.get(pname, pname)})
            for pname in list(act.get("optional") or []):
                plist.append({"name": pname, "req": False,
                              "desc": PARAM_FA.get(pname, pname)})
            acts.append({
                "id": aid, "desc": act.get("desc", ""),
                "method": act.get("method", "GET"),
                "params": plist, "defaults": act.get("defaults") or {},
                "safe": bool(act.get("safe")),
                "no_key": bool(act.get("no_key")),
            })
        services.append({
            "id": sid, "label": e.get("label", sid),
            "en": e.get("en", ""), "category": e.get("category", ""),
            "site": e.get("site", ""), "panel": e.get("panel", ""),
            "docs": e.get("docs", ""), "key_names": e.get("key_names") or [],
            "key_hint": e.get("key_hint", ""),
            "key_env": e.get("key_env") or "",
            "needs_key": e.get("needs_key", True),
            "key_set": is_set, "key_masked": masked,
            "key_source": key_source(ws, sid),
            "actions": acts,
        })
    return {"categories": cats, "services": services,
            "usage": usage_of(ws), "version": VERSION,
            "count": len(services)}


def web_action(ws, data):
    """One mutation from the web panel: set_key / del_key / test / call.
    Returns (ok, payload, http_status). NEVER echoes a full key."""
    action = str(data.get("action", "")).strip()
    sid = str(data.get("service", "")).strip().lower()
    if action in ("set_key", "del_key", "test", "call") \
            and sid not in IRAN_SERVICES:
        return (False, {"error": f"unknown service '{sid}'"}, 404)
    if action == "set_key":
        key = str(data.get("key", "")).strip()
        if not key or len(key) > MAX_KEY_LEN:
            return (False, {"error": f"key must be 1-{MAX_KEY_LEN} "
                                     "characters"}, 400)
        err = set_key(ws, sid, key)
        if err:
            return (False, {"error": err}, 400)
        return (True, {"ok": True, "key_masked": key_status(ws, sid)[1]}, 200)
    if action == "del_key":
        del_key(ws, sid)
        return (True, {"ok": True}, 200)
    if action == "test":
        try:
            res = test_key(ws, sid)
        except Exception as e:
            return (False, {"error": str(e)[:300]}, 500)
        return (True, res, 200)
    if action == "call":
        aid = str(data.get("ir_action", data.get("action_id", ""))).strip()
        params = data.get("params")
        if not isinstance(params, dict):
            params = {}
        params = {str(k): str(v) for k, v in params.items()
                  if str(v).strip()}
        try:
            res = run_action(ws, sid, aid, params=params)
        except Exception as e:
            return (False, {"error": str(e)[:300]}, 500)
        return (True, res, 200)
    return (False, {"error": "unknown action"}, 400)
