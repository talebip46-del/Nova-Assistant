#!/usr/bin/env python3
# =====================================================================
#  Nova Code - model provider layer (v6.6)
#  ONE streaming interface, MANY brains. The agent no longer cares
#  where its model lives.
#
#  v6.6 "a lot of providers" upgrade:
#    - 30 built-in providers (local + cloud + CN clouds + aggregators)
#    - CUSTOM providers: any number of user-defined OpenAI-compatible
#      (or Anthropic/Gemini-wire) endpoints, stored per workspace
#    - KEY VAULT: API keys stored in <ws>/.nova/providers.json (or the
#      classic env vars - the file wins when both exist). Keys never
#      appear in logs, terminal output or web responses (masked).
#    - AUTO MODEL DISCOVERY: as soon as a key exists, GET <base>/models
#      lists what the key can actually use (1 request, cached 24h -
#      discovery itself obeys the "fewer requests" law).
#    - PER-SECTION ROUTING: coding / talk / utility / council can each
#      run on their OWN provider+model (e.g. a big brain for coding,
#      a fast cheap one for talk and utility calls).
#    - ECONOMY hooks: per-section max-token caps + Anthropic prompt
#      caching + budget checks (the heavy lifting lives in
#      nova_economy.py; this module only carries the config).
#
#  v7.9 "b.ai is real" fix + the usage panel:
#    - B.AI (the REAL b.ai - chat.b.ai / api.b.ai, docs.b.ai) joins the
#      registry as its OWN provider: one OpenAI-compatible key that
#      reaches GPT / Claude / Gemini / DeepSeek / GLM / Qwen / Kimi.
#      The v7.8 guess ("b.ai" = Blackbox AI) was WRONG - blackbox keeps
#      its own entry now, and 'b.ai' aliases to the new 'bai' provider.
#      B.AI bills in Credits with the documented law  1 USD = 1,000,000
#      Credits  and  X Credits/Token == X USD / 1M tokens  - so Nova's
#      USD price table converts to credits 1:1 (nova_cost.CREDITS_PER_USD).
#    - USAGE PANEL: /cost and the web economy card now SHOW what the
#      clouds actually consumed - requests, prompt/completion tokens,
#      USD + credit estimate per provider, and the CONTEXT the last
#      request used vs the model's context window (nova_cost.usage_summary).
#
#  v7.8 "cloud first" upgrade (the user's ask: cloud models with API
#  keys, more providers, least credit/request/token burn):
#    - Blackbox AI joins the registry; friendly ALIASES so
#      '/provider hf' and routing aliases work everywhere.
#    - REAL USAGE capture from the cloud SSE stream: the final chunks of
#      OpenAI-compatible / Anthropic / Gemini streams carry the actual
#      prompt/completion token counts - they used to be thrown away, so
#      every cloud turn was priced with a character GUESS. Now the cost
#      ledger, the daily budgets and /cost all run on real numbers.
#    - stream_options.include_usage for OpenAI (the one provider that
#      needs an explicit ask to report usage on a stream).
#    - cache_talk economy flag: identical resent talk turns are served
#      from the local response cache too (zero tokens / credits).
#
#  Wire kinds ("kind"):
#    openai     OpenAI-compatible /chat/completions + SSE (most providers)
#    anthropic  Claude /v1/messages + SSE
#    gemini     Google streamGenerateContent + SSE
#    ollama     local Ollama NDJSON (streamed by nova.py itself)
#
#  Switching:
#    export NOVA_PROVIDER=openai        # pick at startup
#    /provider openai                   # switch live, inside the agent
#    /provider                          # see every provider + key status
#
#  Keys (only the providers you actually use need one):
#    file:  <ws>/.nova/providers.json  "keys": {"openai": "sk-..."}
#    env:   OPENAI_API_KEY / BAI_API_KEY / OPENROUTER_API_KEY / GROQ_API_KEY /
#           DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY /
#           MISTRAL_API_KEY / TOGETHER_API_KEY / FIREWORKS_API_KEY /
#           CEREBRAS_API_KEY / SAMBANOVA_API_KEY / XAI_API_KEY /
#           COHERE_API_KEY / PERPLEXITY_API_KEY / NVIDIA_API_KEY /
#           HF_TOKEN / GITHUB_TOKEN / DEEPINFRA_API_KEY / ZAI_API_KEY /
#           ZHIPU_API_KEY / DASHSCOPE_API_KEY / MOONSHOT_API_KEY /
#           NOVA_API_KEY (for custom)
#
#  Pure Python standard library. Zero dependencies. Streaming via NDJSON
#  (Ollama) or SSE (everyone else) with the same weak-hardware policy as
#  the rest of Nova: the timeout caps the SILENCE between two chunks -
#  a slow provider is never cut off while tokens keep arriving.
#
#  This module never prints: stream_chunks() raises ProviderError with a
#  short English message and nova.py decides how to show it (terminal /
#  web). All parsing helpers are split out pure so the offline QA suite
#  can test every protocol without any network. Secrets never print.
# =====================================================================
import http.client
import json
import os
import re
import socket
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


class ProviderError(Exception):
    """A clean, user-readable provider problem (bad key, unknown name,
    HTTP error, empty base URL...). Never a raw traceback."""


# --------------------------------------------------------------- registry
# Every provider Nova can talk to out of the box. "kind" selects the wire
# protocol. needs_key=False = local server, runs with no key at all.
# models_path = where GET lists the models ("" = not supported).
# mt_field    = the payload field for output caps (OpenAI renamed it,
#               everyone else still speaks classic max_tokens).
PROVIDERS = {
    # ---- local (no key, no internet) ---------------------------------
    # ollama has NO hardcoded model (v5.1): nova.py resolves the actual
    # model against the installed library. '' = 'not resolved yet'.
    "ollama": {
        "kind": "ollama", "base": "http://localhost:11434",
        "model": "", "key_env": None, "needs_key": False,
        "models_path": "/api/tags",
        "label": "Ollama (local)", "hint": "any model you pulled - /model lists them",
    },
    "lmstudio": {
        "kind": "openai", "base": "http://localhost:1234/v1",
        "model": "", "key_env": None, "needs_key": False,
        "label": "LM Studio (local)", "hint": "start the LM Studio server first",
    },
    "llamacpp": {
        "kind": "openai", "base": "http://localhost:8080/v1",
        "model": "", "key_env": None, "needs_key": False,
        "label": "llama.cpp (local)", "hint": "llama-server --port 8080",
    },
    "vllm": {
        "kind": "openai", "base": "http://localhost:8000/v1",
        "model": "", "key_env": None, "needs_key": False,
        "label": "vLLM (local)", "hint": "vllm serve <model>",
    },
    # ---- big clouds ---------------------------------------------------
    "openai": {
        "kind": "openai", "base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini", "key_env": "OPENAI_API_KEY",
        "mt_field": "max_completion_tokens",
        "label": "OpenAI", "hint": "platform.openai.com",
    },
    "anthropic": {
        "kind": "anthropic", "base": "https://api.anthropic.com",
        "model": "claude-3-5-haiku-latest", "key_env": "ANTHROPIC_API_KEY",
        "label": "Anthropic Claude", "hint": "console.anthropic.com",
    },
    "gemini": {
        "kind": "gemini", "base": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.0-flash", "key_env": "GEMINI_API_KEY",
        "label": "Google Gemini", "hint": "aistudio.google.com/apikey",
    },
    "xai": {
        "kind": "openai", "base": "https://api.x.ai/v1",
        "model": "grok-4-fast", "key_env": "XAI_API_KEY",
        "label": "xAI Grok", "hint": "console.x.ai",
    },
    "mistral": {
        "kind": "openai", "base": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest", "key_env": "MISTRAL_API_KEY",
        "label": "Mistral AI", "hint": "console.mistral.ai",
    },
    "cohere": {
        "kind": "openai", "base": "https://api.cohere.ai/compatibility/v1",
        "model": "command-r7b-12-2024", "key_env": "COHERE_API_KEY",
        "label": "Cohere", "hint": "dashboard.cohere.com (OpenAI-compatible endpoint)",
    },
    "github": {
        "kind": "openai", "base": "https://models.github.ai/inference",
        "model": "openai/gpt-4o-mini", "key_env": "GITHUB_TOKEN",
        "label": "GitHub Models", "hint": "a GitHub token is enough - github.com/settings/tokens",
    },
    # ---- cheap / fast --------------------------------------------------
    "groq": {
        "kind": "openai", "base": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile", "key_env": "GROQ_API_KEY",
        "label": "Groq", "hint": "console.groq.com - extremely fast, generous free tier",
    },
    "cerebras": {
        "kind": "openai", "base": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b", "key_env": "CEREBRAS_API_KEY",
        "label": "Cerebras", "hint": "cloud.cerebras.ai - fastest inference, free tier",
    },
    "sambanova": {
        "kind": "openai", "base": "https://api.sambanova.ai/v1",
        "model": "Meta-Llama-3.3-70B-Instruct", "key_env": "SAMBANOVA_API_KEY",
        "label": "SambaNova", "hint": "cloud.sambanova.ai - very fast",
    },
    "deepseek": {
        "kind": "openai", "base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat", "key_env": "DEEPSEEK_API_KEY",
        "label": "DeepSeek", "hint": "platform.deepseek.com - very cheap",
    },
    # ---- model aggregators / GPU clouds --------------------------------
    "openrouter": {
        "kind": "openai", "base": "https://openrouter.ai/api/v1",
        "model": "qwen/qwen-2.5-coder-32b-instruct", "key_env": "OPENROUTER_API_KEY",
        "label": "OpenRouter", "hint": "openrouter.ai - hundreds of models, one key",
    },
    "together": {
        "kind": "openai", "base": "https://api.together.xyz/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "key_env": "TOGETHER_API_KEY",
        "label": "Together AI", "hint": "api.together.xyz",
    },
    "fireworks": {
        "kind": "openai", "base": "https://api.fireworks.ai/inference/v1",
        "model": "accounts/fireworks/models/deepseek-v3", "key_env": "FIREWORKS_API_KEY",
        "label": "Fireworks AI", "hint": "fireworks.ai",
    },
    "deepinfra": {
        "kind": "openai", "base": "https://api.deepinfra.com/v1/openai",
        "model": "meta-llama/Llama-3.3-70B-Instruct", "key_env": "DEEPINFRA_API_KEY",
        "label": "DeepInfra", "hint": "deepinfra.com - cheap pay-per-token",
    },
    "hyperbolic": {
        "kind": "openai", "base": "https://api.hyperbolic.xyz/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct", "key_env": "HYPERBOLIC_API_KEY",
        "label": "Hyperbolic", "hint": "app.hyperbolic.xyz",
    },
    "nvidia": {
        "kind": "openai", "base": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct", "key_env": "NVIDIA_API_KEY",
        "label": "NVIDIA NIM", "hint": "build.nvidia.com - free credits",
    },
    "huggingface": {
        "kind": "openai", "base": "https://router.huggingface.co/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct", "key_env": "HF_TOKEN",
        "label": "Hugging Face", "hint": "hf.co/settings/tokens (Inference Providers)",
    },
    "perplexity": {
        "kind": "openai", "base": "https://api.perplexity.ai",
        "model": "sonar", "key_env": "PERPLEXITY_API_KEY",
        "label": "Perplexity", "hint": "sonar models have live web search",
    },
    "blackbox": {
        # v7.9: blackbox is its own provider again - the v7.8 guess that
        # "b.ai" meant Blackbox was wrong. OpenAI-compatible chat
        # completions under /api/... (base already carries it), so the
        # default /models path resolves to /api/models.
        "kind": "openai", "base": "https://api.blackbox.ai/api",
        "model": "blackboxai", "key_env": "BLACKBOX_API_KEY",
        "label": "Blackbox AI",
        "hint": "blackbox.ai - coding-first models, one key",
    },
    "bai": {
        # v7.9: the REAL b.ai - B.AI (chat.b.ai / api.b.ai, docs.b.ai).
        # A unified LLM gateway: one key, 20+ models (GPT / Claude /
        # Gemini / DeepSeek / GLM / Qwen / Kimi / MiniMax...), and the
        # endpoint speaks plain OpenAI chat/completions + GET /models.
        # Docs: Authorization: Bearer <BAI_API_KEY> (x-api-key also ok).
        # Billing is credit-based with 1 USD = 1,000,000 Credits and
        # X Credits/Token == X USD/1M tokens - Nova's USD pricing table
        # doubles as the credit rate (see nova_cost.CREDITS_PER_USD).
        "kind": "openai", "base": "https://api.b.ai/v1",
        "model": "auto", "key_env": "BAI_API_KEY",
        "label": "B.AI (b.ai)",
        "hint": "b.ai - one key for GPT/Claude/Gemini/DeepSeek/GLM; "
                "'auto' lets B.AI pick per request (chat.b.ai)",
    },
    # ---- CN clouds (very cheap GLM / Qwen / Kimi) ----------------------
    "zai": {
        "kind": "openai", "base": "https://api.z.ai/api/paas/v4",
        "model": "glm-4.6", "key_env": "ZAI_API_KEY",
        "label": "Z.AI (GLM)", "hint": "z.ai - GLM models, OpenAI-compatible",
    },
    "zhipu": {
        "kind": "openai", "base": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash", "key_env": "ZHIPU_API_KEY",
        "label": "Zhipu (GLM CN)", "hint": "open.bigmodel.cn - glm-4-flash is FREE",
    },
    "dashscope": {
        "kind": "openai", "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus", "key_env": "DASHSCOPE_API_KEY",
        "label": "Alibaba Qwen", "hint": "dashscope.aliyuncs.com compatible-mode",
    },
    "moonshot": {
        "kind": "openai", "base": "https://api.moonshot.cn/v1",
        "model": "kimi-k2-0905-preview", "key_env": "MOONSHOT_API_KEY",
        "label": "Moonshot Kimi", "hint": "platform.moonshot.cn",
    },
    # ---- the classic escape hatch --------------------------------------
    "custom": {
        "kind": "openai", "base": "", "model": "",
        "key_env": "NOVA_API_KEY",
        "label": "Custom OpenAI-compatible", "hint": "LM Studio / vLLM / llama.cpp / proxy",
    },
}

# providers that run fine without any key (local servers + the raw custom slot)
_KEYLESS = {"ollama", "lmstudio", "llamacpp", "vllm", "custom"}

# v7.8: friendly aliases -> canonical registry names. The user types
# 'b.ai' or 'hf' in /provider, /key, /brain or the web panel; Nova
# resolves them to the real entry. Aliases never appear in names() -
# only the canonical id does.
PROVIDER_ALIASES = {
    # v7.9: 'b.ai' belongs to the REAL B.AI platform now (api.b.ai);
    # blackbox keeps only its own names.
    "b.ai": "bai", "b-ai": "bai", "b ai": "bai", "bai": "bai",
    "bankofai": "bai", "bank of ai": "bai",
    "blackboxai": "blackbox", "black box": "blackbox",
    "hf": "huggingface", "hugging face": "huggingface",
    "hugging-face": "huggingface",
}


def _canon(name):
    """'b.ai' -> 'bai', ' HF ' -> 'huggingface' - everything else
    passes through stripped/lowered. Pure, never raises."""
    n = str(name or "").strip().lower()
    return PROVIDER_ALIASES.get(n, n)

# module-level override (set by set_provider) - survives for the whole
# process so /provider switching works live; NOVA_PROVIDER seeds it once.
_ACTIVE = {"name": None}

# per-provider model overrides made with /provider <name> <model>
_MODEL_OVERRIDES = {}

# --------------------------------------------------------------- workspace config
# One JSON file per workspace carries EVERYTHING the provider layer needs:
#   {"keys": {"openai": "sk-..."},
#    "custom": [{"name": "myrelay", "kind": "openai",
#                "base": "https://relay.example/v1", "model": "..."}],
#    "routing": {"talk": "groq/llama-3.3-70b-versatile", ...},
#    "economy": {"cache": true, "daily_budget_usd": 2.0},
#    "discovered": {"groq": {"ts": 1712345678, "models": ["..."]}}}
# Keys/customs/routing/economy/discovery-cache all live together. The file
# is chmod 600 on POSIX. Env keys still work; the FILE wins when both exist
# (what the UI shows is what gets used - no surprises).
CONFIG_FILE = "providers.json"
MAX_CONFIG_BYTES = 200_000
MAX_KEYS = 40
MAX_CUSTOM = 24
MAX_KEY_LEN = 400
MAX_MODELS_CACHED = 800
DISCOVERY_TTL = 24 * 3600        # one /models request per provider per day
CUSTOM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._~/@:+\- ]{1,200}$")

CFG_FILE_KWS = ("keys", "custom", "routing", "economy", "discovered")

_CFG = {"ws": None, "keys": {}, "custom": [], "routing": {},
        "economy": {}, "discovered": {}}
# v6.6.0 fix: MUST be reentrant - set_route()'s validation re-enters
# entry() (which locks) while _with_state() already holds the lock. A
# plain Lock deadlocked the whole agent on the first /brain call.
_CFG_LOCK = threading.RLock()

# economy defaults (nova_economy.py may override behaviour, this is config)
ECONOMY_DEFAULTS = {
    "cache": True,                 # utility-section response cache
    "cache_talk": True,            # v7.8: also cache identical resent talk turns
    "cache_ttl": 7 * 86400,        # seconds a cached answer stays valid
    "cache_max": 64,               # entries kept per workspace
    "anthropic_cache": True,       # system-prompt cache_control (0.1x reads)
    "max_tokens": {"talk": 1024, "utility": 512, "coding": 0},  # 0 = uncapped
    "daily_budget_usd": 0.0,       # 0 = off; blocks a provider when exceeded
    "daily_token_budget": 0,       # 0 = off; prompt+completion tokens/day
}

SECTIONS = ("coding", "talk", "utility", "council")
SECTION_LABELS = {
    "coding": "Coding agent (terminal + web coding tab)",
    "talk": "Simple talk (web گفت و گو tab)",
    "utility": "Utility calls (commit/PR text, compact, verify judge)",
    "council": "Council partner (second brain)",
}


def _clean_key_map(obj):
    out = {}
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:MAX_KEYS * 2]:
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            # v7.8: a key saved under an alias ('b.ai') lands on the
            # canonical name ('bai' since v7.9, 'blackbox' before) - one
            # vault row per provider.
            name = _canon(k)
            val = v.strip()[:MAX_KEY_LEN]
            if name and val and (CUSTOM_NAME_RE.match(name)
                                 or name in PROVIDERS):
                out[name] = val
    return out


def _clean_custom_list(obj):
    out = []
    if not isinstance(obj, list):
        return out
    for c in obj[:MAX_CUSTOM]:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip().lower()
        base = str(c.get("base", "")).strip().rstrip("/")
        if not CUSTOM_NAME_RE.match(name) or name in PROVIDERS:
            continue
        if not base.lower().startswith(("http://", "https://")) or len(base) > 300:
            continue
        kind = str(c.get("kind", "openai")).strip().lower()
        if kind not in ("openai", "anthropic", "gemini"):
            kind = "openai"
        model = str(c.get("model", "")).strip()[:120]
        # v6.7 fix: an invalid model name used to drop the WHOLE provider
        # entry here - a provider saved with a model the regex dislikes
        # (e.g. 'llama 3.1 (latest)') worked until the next restart and
        # then silently vanished. Keep the provider, strip just the model.
        if model and not MODEL_NAME_RE.match(model):
            model = ""
        label = str(c.get("label", "")).strip()[:60] or name
        entry = {"name": name, "kind": kind, "base": base, "model": model,
                 "label": label}
        out.append(entry)
    return out


def _clean_routing(obj):
    out = {}
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:len(SECTIONS) * 2]:
            if k not in SECTIONS or not isinstance(v, str):
                continue
            t = v.strip()[:200]
            if not t:
                continue
            prov = t.split("/", 1)[0].strip().lower()
            if MODEL_NAME_RE.match(t) and prov:
                out[k] = t
    return out


def _clean_economy(obj):
    out = {}
    if not isinstance(obj, dict):
        return out
    for k in ("cache", "anthropic_cache", "cache_talk"):
        if isinstance(obj.get(k), bool):
            out[k] = obj[k]
    for k in ("cache_ttl", "cache_max", "daily_token_budget"):
        v = obj.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10 ** 9:
            out[k] = v
    v = obj.get("daily_budget_usd")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 10 ** 6:
        out["daily_budget_usd"] = float(v)
    mt = obj.get("max_tokens")
    if isinstance(mt, dict):
        clean = {}
        for s in SECTIONS:
            v = mt.get(s)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 200_000:
                clean[s] = v
        if clean:
            out["max_tokens"] = clean
    return out


def _clean_discovered(obj):
    out = {}
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:MAX_KEYS * 2]:
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            name = k.strip().lower()[:60]
            ts = v.get("ts")
            models = v.get("models")
            if not isinstance(ts, (int, float)) or ts <= 0:
                continue
            if not isinstance(models, list):
                continue
            clean, seen = [], set()
            for m in models[:MAX_MODELS_CACHED * 2]:
                if not isinstance(m, str):
                    continue
                n = m.strip()
                if not n or n in seen or not MODEL_NAME_RE.match(n) \
                        or len(n) > 200:
                    continue
                seen.add(n)
                clean.append(n)
                if len(clean) >= MAX_MODELS_CACHED:
                    break
            if clean:
                out[name] = {"ts": int(ts), "models": clean}
    return out


def parse_config(obj):
    """Raw JSON dict -> validated config dict. Pure; never raises."""
    if not isinstance(obj, dict):
        return {"keys": {}, "custom": [], "routing": {},
                "economy": {}, "discovered": {}}
    return {
        "keys": _clean_key_map(obj.get("keys")),
        "custom": _clean_custom_list(obj.get("custom")),
        "routing": _clean_routing(obj.get("routing")),
        "economy": _clean_economy(obj.get("economy")),
        "discovered": _clean_discovered(obj.get("discovered")),
    }


def config_path(ws):
    import pathlib
    return pathlib.Path(ws) / ".nova" / CONFIG_FILE


def load_config(ws):
    """(Re)load the workspace provider config into module state. Fail-soft:
    a missing/broken/hostile file just means an empty config (env keys
    keep working). Called at session start and on /workspace changes."""
    with _CFG_LOCK:
        _CFG["ws"] = None
        _CFG["keys"], _CFG["custom"] = {}, []
        _CFG["routing"], _CFG["economy"], _CFG["discovered"] = {}, {}, {}
        if ws is None:
            return _CFG
        try:
            p = config_path(ws)
            if p.is_file() and p.stat().st_size <= MAX_CONFIG_BYTES:
                parsed = parse_config(json.loads(
                    p.read_text(encoding="utf-8", errors="replace")))
                _CFG.update(parsed)
            _CFG["ws"] = str(ws)
        except Exception:
            _CFG["ws"] = str(ws) if ws else None
    return _CFG


def _save_locked():
    """Write the current module state to the workspace file (atomic).
    Caller must hold _CFG_LOCK (and ideally the cross-process file_lock
    from _with_state). Returns error string or ''."""
    ws = _CFG.get("ws")
    if not ws:
        return "no workspace"
    try:
        p = config_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {k: _CFG.get(k, {}) for k in CFG_FILE_KWS}
        # v6.7: unique scratch name - a fixed ".tmp" collided across
        # processes (REPL + web share the workspace vault) and could
        # publish a torn, truncated secrets file.
        # v7.14.1 fix: natom may legitimately be None here (the import
        # guard exists at the top); calling None raised AttributeError
        # past the "error string or ''" contract - fall back to a manual
        # unique-tmp write instead.
        payload = json.dumps(body, indent=1, ensure_ascii=False)
        if natom is not None:
            err = natom.write_text_atomic(p, payload)
            if err:
                return err
        else:
            tmp = p.with_name("%s.tmp%d" % (p.name,
                              (os.getpid() * 7919
                               + threading.get_ident() % 100000
                               + int(time.time() * 1000)) % 1000000))
            try:
                tmp.write_text(payload, encoding="utf-8")
                tmp.replace(p)
            except OSError as e:
                return str(e)
        try:                                # POSIX: keep secrets private
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return ""
    except OSError as e:
        return str(e)


def _reload_locked():
    """v7.1.0: merge the on-disk vault into _CFG (file wins). Two processes
    share one workspace (REPL + web): without this, a web-saved API key
    was silently ERASED the next time the REPL saved anything, because
    _save_locked rewrites the whole file from this process's stale memory.
    Caller must hold _CFG_LOCK."""
    ws = _CFG.get("ws")
    if not ws:
        return
    try:
        p = config_path(ws)
        if p.is_file() and p.stat().st_size <= MAX_CONFIG_BYTES:
            parsed = parse_config(json.loads(
                p.read_text(encoding="utf-8", errors="replace")))
            _CFG.update(parsed)
    except Exception:
        pass                      # unreadable file: keep the memory state


def _with_state(fn):
    """Run fn(_CFG) under the lock, persisting afterwards when it changed
    anything (fn returns True).
    v7.1.0: cross-process lost-update fix - the read-modify-write cycle
    now happens under nova_atomic.file_lock AND starts from a fresh read
    of the file, so the other process's last save is never clobbered
    (same pattern nova_cost already uses for its ledger)."""
    with _CFG_LOCK:
        lock_path = None
        ws = _CFG.get("ws")
        if ws and natom is not None:
            try:
                lock_path = config_path(ws).parent / "providers.lock"
            except Exception:
                lock_path = None
        if lock_path is None:
            changed = fn(_CFG)
            return _save_locked() if changed else ""
        try:
            with natom.file_lock(lock_path, timeout=8.0):
                _reload_locked()
                changed = fn(_CFG)
                return _save_locked() if changed else ""
        except Exception:
            # degraded path: in-process lock only (documented fail-open,
            # same as everywhere file_lock degrades)
            changed = fn(_CFG)
            return _save_locked() if changed else ""


# --------------------------------------------------------------- registry
def customs():
    """The user-defined custom providers (validated list)."""
    with _CFG_LOCK:
        return [dict(c) for c in _CFG["custom"]]


def entry(name):
    """Registry entry for a name (built-in, custom or ALIAS like 'b.ai')
    - a NEW dict, or None. Never resolves keys; for display and
    existence checks."""
    name = _canon(name)
    if name in PROVIDERS:
        e = dict(PROVIDERS[name])
    else:
        with _CFG_LOCK:
            for c in _CFG["custom"]:
                if c["name"] == name:
                    e = dict(c)
                    break
            else:
                return None
    e["name"] = name
    # v6.6: a named custom provider points where the USER says - LM Studio,
    # vLLM, an authenticated relay - so its key is OPTIONAL (a 401 from a
    # key-hungry endpoint is a clean, visible error at call time).
    if name in PROVIDERS:
        e.setdefault("needs_key", name not in _KEYLESS)
    else:
        e["needs_key"] = False
    e.setdefault("models_path", "/models")
    e.setdefault("mt_field", "max_tokens")
    return e


def names():
    """All provider keys in display order (ollama first, customs last)."""
    with _CFG_LOCK:
        custom_names = [c["name"] for c in _CFG["custom"]]
    return (["ollama"] + [n for n in PROVIDERS if n != "ollama"]
            + [n for n in custom_names if n not in PROVIDERS])


def registry_names():
    """Valid provider names for validation (same as names())."""
    return names()


def _file_key(name):
    with _CFG_LOCK:
        return _CFG["keys"].get(name, "")


def resolve(name=None):
    """Fully-resolved config for one provider name (default: NOVA_PROVIDER
    env, else ollama). Returns a NEW dict (key + env overrides applied) or
    raises ProviderError with a helpful message. Never touches global
    state. Key source: workspace file FIRST, then the environment."""
    name = (name or os.environ.get("NOVA_PROVIDER", "") or "ollama").strip().lower()
    name = _canon(name)
    e = entry(name)
    if e is None:
        raise ProviderError(
            f"unknown provider '{name}'. Available: " + ", ".join(names()))
    cfg = dict(e)
    cfg.pop("needs_key", None)
    cfg["key_optional"] = not e.get("needs_key", True)
    # env overrides: NOVA_BASE_URL / NOVA_MODEL win over the built-in
    # defaults. NOVA_BASE_URL applies ONLY to the raw 'custom' provider
    # (named custom providers carry their own base): on a fixed provider
    # it would silently redirect that provider's traffic - INCLUDING its
    # Authorization key - to an arbitrary base URL.
    env_base = os.environ.get("NOVA_BASE_URL", "").strip()
    env_model = os.environ.get("NOVA_MODEL", "").strip()
    if env_base and name == "custom" and not cfg["base"]:
        cfg["base"] = env_base
    if env_model and not cfg["model"]:
        # v8.7: the env override FILLS an empty model (custom / lmstudio
        # / llamacpp rely on it, same spirit as the base gate above) -
        # it used to stomp EVERY provider's built-in default, so a stale
        # NOVA_MODEL renamed groq's model into a nonexistent local name
        # (HTTP 400 'model not found' with no visible hint why).
        cfg["model"] = env_model
    if name == "custom":
        if not cfg["base"]:
            raise ProviderError(
                "the 'custom' provider needs an OpenAI-compatible base URL, "
                "e.g.  NOVA_BASE_URL=http://localhost:1234/v1  "
                "(LM Studio / vLLM / llama.cpp / any /chat/completions server)")
        if not cfg["model"]:
            raise ProviderError(
                "the 'custom' provider needs a model name, e.g.  NOVA_MODEL=qwen2.5-coder-7b-instruct")
    if cfg["kind"] != "ollama":
        # v6.6.0 fix: custom entries carry no key_env - .get() (a KeyError
        # here killed every resolve of a named custom provider)
        key = _file_key(name) or os.environ.get(cfg.get("key_env") or "", "").strip()
        cfg["key"] = key
        # custom targets usually need NO key at all (LM Studio, vLLM...)
        if not key and not cfg["key_optional"]:
            raise ProviderError(
                f"provider '{name}' needs an API key ({cfg.get('hint', '')}). "
                f"Set it with:  /key {name} <the-key>   or:  "
                f"export {cfg['key_env']}=...")
    else:
        cfg["key"] = ""
    return cfg


def current():
    """Resolved config of the ACTIVE provider (set_provider override or
    NOVA_PROVIDER env or ollama)."""
    return resolve(_ACTIVE["name"])


def current_name():
    return _ACTIVE["name"] or (os.environ.get("NOVA_PROVIDER", "") or "ollama").strip().lower()


def set_provider(name, model=None):
    """Switch the active provider for this process (used by /provider).
    Returns the resolved config; raises ProviderError on a bad name or a
    missing key, so the previous provider stays active on failure."""
    cfg = resolve(name)               # validates first - no partial switches
    if model:
        cfg = dict(cfg)
        cfg["model"] = model.strip()
        _set_model_override(cfg["name"], cfg["model"])
    _ACTIVE["name"] = cfg["name"]
    return cfg


def _set_model_override(name, model):
    if model:
        _MODEL_OVERRIDES[name] = model
    else:
        _MODEL_OVERRIDES.pop(name, None)


def default_model(cfg):
    """Model for a provider config: /provider override > NOVA_MODEL env >
    registry default (nova.py keeps its own notion in sess.model; for
    ollama the registry default is '' - resolved from the installed
    library at startup)."""
    over = _MODEL_OVERRIDES.get(cfg.get("name", ""))
    if over:
        return over
    return cfg.get("model") or ""


# --------------------------------------------------------------- key vault
def mask_key(key):
    """A key that may be SHOWN: 'sk-abcd1234...' -> '...1234' style.
    Never returns more than the last 4 characters."""
    k = str(key or "").strip()
    if not k:
        return ""
    return "..." + k[-4:] if len(k) > 4 else "..."


def key_source(name):
    """'' | 'file' | 'env' - where the key for this provider comes from."""
    name = _canon(name)
    if _file_key(name):
        return "file"
    e = entry(name) or {}
    env = os.environ.get(e.get("key_env") or "", "").strip()
    return "env" if env else ""


def key_status(name):
    """(is_set, masked) for UI display - the full key NEVER leaves here."""
    name = _canon(name)
    src = key_source(name)
    if not src:
        return (False, "")
    if src == "file":
        return (True, mask_key(_file_key(name)))
    e = entry(name) or {}
    return (True, mask_key(os.environ.get(e.get("key_env") or "", "")))


def set_key(ws, name, value):
    """Store one API key in the workspace vault. Aliases ('b.ai') are
    stored under the canonical name. Returns error string or ''. The
    value is validated for sane length only - keys have many shapes and
    we must not second-guess the provider."""
    name = _canon(name)
    if entry(name) is None:
        return f"unknown provider '{name}'"
    v = (value or "").strip()[:MAX_KEY_LEN]
    if not v:
        return "empty key"

    def op(cfg):
        cfg["keys"][name] = v
        return True
    return _with_state(op)


def del_key(ws, name):
    """Remove a stored key (the env var, if any, takes over again).
    v7.1.0: name normalized exactly like set_key - an un-normalized name
    was a silent no-op (the key stayed in the vault)."""
    name = _canon(name)

    def op(cfg):
        if name in cfg["keys"]:
            cfg["keys"].pop(name, None)
            return True
        return False
    return _with_state(op)


def add_custom(ws, name, base, model="", kind="openai", label=""):
    """Add a user-defined provider. Returns error string or ''."""
    name = (name or "").strip().lower()
    if not CUSTOM_NAME_RE.match(name):
        return ("bad provider name: 2-32 chars, lowercase letters, digits, "
                "- and _ (e.g. 'myrelay')")
    if entry(name) is not None:
        return f"provider name '{name}' is already taken"
    base = (base or "").strip().rstrip("/")
    if not base.lower().startswith(("http://", "https://")) or len(base) > 300:
        return "the base URL must start with http:// or https://"
    kind = (kind or "openai").strip().lower()
    if kind not in ("openai", "anthropic", "gemini"):
        return "kind must be openai, anthropic or gemini"
    model = (model or "").strip()[:120]
    # v6.7 fix: an invalid model name was stored verbatim, then the
    # loader silently dropped the whole provider on the next start. The
    # user now hears about it at save time instead.
    if model and not MODEL_NAME_RE.match(model):
        return ("bad model name: use letters, digits, . _ ~ / @ : + - and "
                "spaces (e.g. 'qwen2.5-coder:7b')")
    label = (label or "").strip()[:60] or name

    def op(cfg):
        if len(cfg["custom"]) >= MAX_CUSTOM:
            # v7.9: the FIFO eviction used to orphan the evicted provider's
            # API key (plaintext in the vault forever) + its routing row +
            # its discovery cache - del_custom cleaned up, this path did not.
            old = cfg["custom"].pop(0)
            oname = str(old.get("name", ""))
            cfg["keys"].pop(oname, None)
            cfg["discovered"].pop(oname, None)
            for s in SECTIONS:
                if str(cfg["routing"].get(s, "")).split("/", 1)[0] == oname:
                    cfg["routing"].pop(s, None)
        cfg["custom"].append({"name": name, "kind": kind, "base": base,
                              "model": model, "label": label})
        return True
    return _with_state(op)


def del_custom(ws, name):
    """Remove a custom provider (and its key + routing). Returns error
    string or ''."""

    def op(cfg):
        n = (name or "").strip().lower()
        before = len(cfg["custom"])
        cfg["custom"] = [c for c in cfg["custom"] if c["name"] != n]
        if len(cfg["custom"]) == before:
            return False
        cfg["keys"].pop(n, None)
        for s in SECTIONS:
            if str(cfg["routing"].get(s, "")).split("/", 1)[0] == n:
                cfg["routing"].pop(s, None)
        cfg["discovered"].pop(n, None)
        return True
    return _with_state(op)


# --------------------------------------------------------------- routing
def route_target(section):
    """The stored routing target for one section ('' = active brain)."""
    with _CFG_LOCK:
        return _CFG["routing"].get(section, "")


def routing():
    """A copy of the whole routing map (for display)."""
    with _CFG_LOCK:
        return dict(_CFG["routing"])


def parse_target(target):
    """'provider/model/with/slashes' -> (provider, model-with-slashes).
    A bare provider name is also accepted ('' model = the provider's
    default). Raises ProviderError on garbage."""
    t = (target or "").strip()
    if not t or not MODEL_NAME_RE.match(t):
        raise ProviderError(
            "a brain target looks like  provider/model  e.g.  groq/llama-3.3-70b-versatile")
    if "/" in t:
        prov, model = t.split("/", 1)
        prov = _canon(prov)
        model = model.strip()
    else:
        prov, model = _canon(t), ""
    if not prov:
        raise ProviderError("the target needs a provider before the '/'")
    if entry(prov) is None:
        raise ProviderError(
            f"unknown provider '{prov}'. Available: " + ", ".join(names()))
    return (prov, model)


def set_route(ws, section, target):
    """Point one section at 'provider/model' (or '' / 'off' to clear).
    Returns error string or ''."""
    if section not in SECTIONS:
        return f"unknown section '{section}' ({', '.join(SECTIONS)})"
    t = (target or "").strip()
    if not t or t.lower() in ("off", "none", "clear", "default"):
        t = ""

    def op(cfg):
        if t:
            try:
                prov, model = parse_target(t)
            except ProviderError as e:
                # validation errors must not persist anything
                raise _RouteReject(str(e)) from None
            # v7.9 audit fix: persist the CANONICAL 'provider/model'. The
            # raw target ('b.ai/gpt-4o') was stored verbatim - the web
            # panel's route select only knows canonical ids, showed
            # "(مغز فعال هدر)", and one plain save click silently wiped
            # the route.
            cfg["routing"][section] = prov + ("/" + model if model else "")
        else:
            cfg["routing"].pop(section, None)
        return True
    try:
        return _with_state(op)
    except _RouteReject as e:
        return str(e)


class _RouteReject(Exception):
    pass


def resolve_route(section):
    """Routing for one section -> (cfg, model). (None, '') means 'no
    route stored - use the active brain'. Raises ProviderError when the
    routed provider is misconfigured (missing key...), so the caller can
    fall back with a visible note."""
    target = route_target(section)
    if not target:
        return (None, "")
    prov, model = parse_target(target)
    cfg = resolve(prov)
    return (cfg, model or default_model(cfg))


# --------------------------------------------------------------- economy config
def economy():
    """Validated economy config (defaults merged under user overrides)."""
    with _CFG_LOCK:
        user = dict(_CFG["economy"])
    out = dict(ECONOMY_DEFAULTS)
    out.update(user)
    mt = dict(ECONOMY_DEFAULTS["max_tokens"])
    mt.update(user.get("max_tokens") or {})
    out["max_tokens"] = mt
    return out


def set_economy(ws, updates):
    """Persist a few economy fields. Unknown fields are ignored.
    Returns error string or ''."""
    clean = _clean_economy(updates or {})
    if not clean:
        return "nothing to change"

    def op(cfg):
        cfg["economy"].update(clean)
        return True
    return _with_state(op)


def max_tokens_for(section):
    """Output cap for a section (0 = uncapped)."""
    eco = economy()
    try:
        return max(0, int(eco["max_tokens"].get(section or "coding", 0)))
    except Exception:
        return 0


def cache_enabled():
    return bool(economy().get("cache", True))


def anthropic_cache_enabled():
    return bool(economy().get("anthropic_cache", True))


# --------------------------------------------------------------- model discovery
def _models_endpoint(cfg):
    """(url, headers) for the model list of one resolved config.
    One GET - never more (the result is cached for a day).
    v6.7: Gemini and Anthropic paginate their model lists by default
    (Gemini pageSize=50, Anthropic limit=20) - the detected list was
    silently truncated and fresh models were missing. One bigger page
    keeps the one-request-per-day law."""
    kind = cfg.get("kind", "openai")
    base = (cfg.get("base") or "").rstrip("/")
    if kind == "ollama":
        return base + "/api/tags", {}
    if kind == "anthropic":
        return base + "/v1/models?limit=1000", {
            "x-api-key": cfg.get("key", ""),
            "anthropic-version": "2023-06-01"}
    if kind == "gemini":
        return base + "/models?pageSize=1000", {
            "x-goog-api-key": cfg.get("key", "")}
    # openai-compatible
    path = cfg.get("models_path") or "/models"
    headers = {}
    if cfg.get("key"):
        headers["Authorization"] = "Bearer " + cfg["key"]
    return base + path, headers


def _clean_model_list(raw_names):
    """Dedupe + validate + cap. Server order is kept (the UI numbers them)."""
    out, seen = [], set()
    for m in raw_names:
        if not isinstance(m, str):
            continue
        n = m.strip()
        if not n or len(n) > 200 or not MODEL_NAME_RE.match(n) or n in seen:
            continue
        seen.add(n)
        out.append(n)
        if len(out) >= MAX_MODELS_CACHED:
            break
    return out


def _models_parse_openai(payload):
    """GET /models body of ANY OpenAI-compatible server -> [names].
    Handles {'data':[{'id':..}]}, bare lists, {'models':[...]} and junk."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("data")
        if not isinstance(items, list):
            items = payload.get("models")
        if not isinstance(items, list):
            return []
    else:
        return []
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict):
            v = it.get("id", it.get("name", ""))
            if isinstance(v, str):
                out.append(v)
    return _clean_model_list(out)


def _models_parse_gemini(payload):
    """Gemini GET /models body -> [names] (the 'models/' prefix is
    stripped; embedding models are dropped - they cannot chat)."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("models")
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        if not isinstance(name, str):
            continue
        if name.startswith("models/"):
            name = name[len("models/"):]
        low = name.lower()
        if "embed" in low or "aqa" in low:
            continue
        out.append(name)
    return _clean_model_list(out)


def _models_parse_ollama(payload):
    """Ollama /api/tags body -> [names] (same shape nova_models parses)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return []
    out = []
    for m in payload["models"]:
        if isinstance(m, dict):
            v = m.get("name", m.get("model", ""))
            if isinstance(v, str):
                out.append(v)
    return _clean_model_list(out)


def _models_parse(kind, payload):
    if kind == "gemini":
        return _models_parse_gemini(payload)
    if kind == "ollama":
        return _models_parse_ollama(payload)
    return _models_parse_openai(payload)          # openai + anthropic shapes


def _get_json(url, headers, timeout):
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # v6.7: project convention caps every read (4MB like the council);
        # an unbounded read let a hostile/broken endpoint exhaust RAM.
        return json.loads(resp.read(4_000_000).decode("utf-8", "replace"))


def cached_models(name):
    """The discovered model list from the cache - NO network. [] when
    nothing was discovered yet (this is what /api/info serves)."""
    with _CFG_LOCK:
        c = _CFG["discovered"].get(_canon(name))
        return list(c["models"]) if c else []


_DISCOVER_INFLIGHT = set()      # names currently being fetched (v6.7)


def discover(name, force=False, timeout=8):
    """The model list of one provider. Cached for DISCOVERY_TTL (one HTTP
    request per provider per day - discovery obeys the request diet).
    force=True re-fetches (used right after a key is saved). A failed
    refresh degrades to the stale cache when one exists."""
    name = _canon(name)
    e = entry(name)
    if e is None:
        raise ProviderError(f"unknown provider '{name}'")
    now = time.time()
    with _CFG_LOCK:
        c = _CFG["discovered"].get(name)
        if c and not force and now - c.get("ts", 0) < DISCOVERY_TTL:
            return list(c["models"])
        # v6.7: a second thread hitting discover() while the first is on
        # the wire used to fetch again - two requests for one day, breaking
        # the request diet. Wait for the in-flight fetch instead.
        if name in _DISCOVER_INFLIGHT:
            stale_wait = list(c["models"]) if c else []
            waiter = threading.Condition(_CFG_LOCK)
            deadline = time.time() + max(2, int(timeout or 8))
            while name in _DISCOVER_INFLIGHT and time.time() < deadline:
                waiter.wait(min(0.1, max(0.01, deadline - time.time())))
            c2 = _CFG["discovered"].get(name)
            if c2:
                return list(c2["models"])
            return stale_wait
        _DISCOVER_INFLIGHT.add(name)
        stale = list(c["models"]) if c else []
    try:
        return _discover_fetch(name, now, stale, timeout)
    finally:
        with _CFG_LOCK:
            _DISCOVER_INFLIGHT.discard(name)


def _discover_fetch(name, now, stale, timeout):
    cfg = resolve(name)          # raises a clean error on a missing key
    if cfg.get("kind") != "ollama" and not cfg.get("key") \
            and not cfg.get("key_optional"):
        raise ProviderError(
            f"provider '{name}' needs an API key before its models can be detected")
    url, headers = _models_endpoint(cfg)
    try:
        payload = _get_json(url, headers, timeout)
        models = _models_parse(cfg.get("kind", "openai"), payload)
    except urllib.error.HTTPError as ex:
        if stale:
            return stale
        raise ProviderError(_http_message(ex)) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as ex:
        if stale:
            return stale
        raise ProviderError(_network_error(ex)) from None
    except ValueError as ex:
        if stale:
            return stale
        raise ProviderError("the model list endpoint returned invalid JSON") from None

    def op(cfgr):
        # v6.7 fix: a 200-with-empty-list (LM Studio restarted with
        # nothing loaded, proxies answering {}) used to poison the 24h
        # cache AND destroy a good stale list - /catalog then showed zero
        # models for a day with no self-heal. Keep the stale cache when
        # the fresh fetch is empty.
        if models or not stale:
            cfgr["discovered"][name] = {"ts": int(now), "models": models}
        return bool(models or not stale)
    _with_state(op)
    return list(models) if models else (stale or [])


# --------------------------------------------------------------- SSE utils
def _sse_data_lines(resp):
    """Yield the payload of every `data:` line from an SSE byte stream.
    Comments (':' prefix), blank lines and stray non-SSE lines are skipped -
    OpenRouter sends ': OPENROUTER PROCESSING' keep-alives, some proxies
    send whitespace. Robust against all of them."""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            yield line[5:].strip()


def _request(url, payload, headers):
    """POST helper -> urllib request object (json body)."""
    all_headers = {"Content-Type": "application/json"}
    all_headers.update(headers or {})
    return urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=all_headers)


def _network_error(e):
    """Any raw network failure -> short clean message (no key, no URL)."""
    reason = getattr(e, "reason", None)
    return "cannot reach the provider endpoint (" + str(reason or e) + ")"


def _http_message(e):
    """urllib.error.HTTPError -> short clean English message with a hint.
    v8.0: the error body read is CAPPED at 256 KB and the error object is
    closed - a broken/hostile endpoint answering 500 with a multi-GB body
    used to be read into RAM unbounded."""
    detail = ""
    try:
        detail = e.read(262_144).decode("utf-8", "replace")
    except TypeError:
        # duck-typed error objects whose read() takes no size argument
        try:
            detail = e.read().decode("utf-8", "replace")[:262_144]
        except Exception:
            pass
    except Exception:
        pass
    finally:
        try:
            e.close()
        except Exception:
            pass
    hint = ""
    if e.code in (401, 403):
        hint = " - the API key is missing or wrong"
    elif e.code == 404:
        hint = " - model name or base URL is probably wrong"
    elif e.code == 429:
        hint = " - rate limited / out of quota, retry later"
    msg = f"HTTP {e.code}{hint}"
    if detail:
        try:
            j = json.loads(detail)
            err = j.get("error", j.get("message", detail))
            msg += ": " + str(err)[:300]
        except Exception:
            msg += ": " + detail[:300]
    return msg


def _int_cap(v):
    """A max_tokens cap -> positive int, or 0 (no cap). Never raises."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    return v if v > 0 else 0


# --------------------------------------------------------------- protocol adapters
# Wire format per provider kind. Each generator yields text pieces and is
# written so the actual PARSING is a pure function a test suite can feed.
# Robustness rule: a misbehaving/broken provider must surface as a clean
# ProviderError - never a raw AttributeError/TypeError from bad JSON.

# --------------------------------------------------------------- usage capture
def _absorb_usage(usage, prompt_tokens, completion_tokens):
    """Fold one real usage report into the caller's usage dict. Any
    positive count wins; the dict flips to actual=True so the cost
    ledger prices the turn with REAL tokens instead of a character
    guess. Never raises.
    v7.9: json.loads turns 1e999 into float('inf') and int(inf) raised a
    raw OverflowError that killed the whole stream - OverflowError joins
    the except, and absurd counts (a 400-digit int passes int()) are
    refused outright (a real turn is <10^7 tokens)."""
    if usage is None or not isinstance(usage, dict):
        return
    try:
        p = int(prompt_tokens or 0)
    except (TypeError, ValueError, OverflowError):
        p = 0          # v7.9 audit fix: per-field tolerance - one junk
    try:               # field no longer discards its valid sibling
        c = int(completion_tokens or 0)
    except (TypeError, ValueError, OverflowError):
        c = 0
    if p > 10 ** 12 or c > 10 ** 12:
        return
    if p > 0:
        usage["prompt_tokens"] = p
    if c > 0:
        usage["completion_tokens"] = c
    if p > 0 or c > 0:
        usage["actual"] = True


# v8.2: WHY did the last stream end? "length" = the provider cut the
# answer at its output cap (finish_reason length / stop_reason max_tokens
# / finishReason MAX_TOKENS) - nova.py's stream_chat turns that into
# complete=False so the auto-continue rescue can finish the answer.
# Reset by stream_chunks() at entry, so it always describes the most
# recent call of THIS process (parallel /explore streams may race; the
# consequence is only an extra or missing continuation round, never a
# crash - and explore answers are complete texts by construction).
LAST_FINISH_REASON = ""


def _openai_parse(data, usage=None):
    """One SSE payload of an OpenAI-compatible stream -> list of pieces.
    ('[DONE]' or a JSON without choices -> [].) Raises ProviderError when
    the payload carries an API error object.
    v7.8: a payload with a `usage` object (OpenAI's final include_usage
    chunk, DeepSeek/Groq/OpenRouter/... final chunks) reports REAL token
    counts into `usage` instead of being dropped on the floor."""
    if data == "[DONE]":
        return []
    try:
        obj = json.loads(data)
    except ValueError:
        return []                       # tolerate junk lines from proxies
    if not isinstance(obj, dict):
        return []                       # some proxies emit a bare JSON array
    if obj.get("error"):
        err = obj["error"]
        text = err.get("message", "") if isinstance(err, dict) else str(err)
        raise ProviderError("API error: " + str(text)[:300])
    u = obj.get("usage")
    if isinstance(u, dict):
        _absorb_usage(usage, u.get("prompt_tokens"),
                      u.get("completion_tokens"))
    choices = obj.get("choices") or []
    if not choices or not isinstance(choices, list) or not isinstance(choices[0], dict):
        return []
    # v8.2: finish_reason length = the output cap cut the answer mid-stream
    fr = str(choices[0].get("finish_reason") or "").lower()
    if fr:
        global LAST_FINISH_REASON
        LAST_FINISH_REASON = "length" if fr == "length" else fr
    delta = choices[0].get("delta") or {}
    if not isinstance(delta, dict):
        return []
    # v7.9: a broken proxy sent content as a LIST - it used to be yielded
    # verbatim and killed the turn with a TypeError in stdout.write.
    piece = delta.get("content")
    return [piece] if isinstance(piece, str) and piece else []


def _openai_stream(cfg, model, messages, temperature, timeout, max_tokens=0,
                   usage=None):
    """OpenAI-compatible SSE chat stream (OpenAI / OpenRouter / Groq /
    DeepSeek / Blackbox / LM Studio / vLLM / llama.cpp / custom / ...)."""
    url = cfg["base"].rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "stream": True,
               "temperature": temperature}
    if cfg.get("name") == "llamacpp":
        # v6.8: context caching between turns - llama.cpp's server reuses
        # the KV cache when the prompt PREFIX is unchanged, and honors an
        # explicit cache_prompt hint. The stable system prompt + growing
        # history order Nova produces makes the reuse actually hit.
        payload["cache_prompt"] = True
    if cfg.get("name") == "openai":
        # v7.8 economy: OpenAI only reports usage on a stream when asked.
        # One tiny request field = real token accounting for every turn
        # (every other compatible provider sends usage by itself).
        payload["stream_options"] = {"include_usage": True}
    cap = _int_cap(max_tokens)
    if cap:
        # v6.6: per-section output caps. OpenAI renamed the field; every
        # other OpenAI-compatible server still speaks max_tokens.
        payload[cfg.get("mt_field") or "max_tokens"] = cap
    headers = {}
    if cfg.get("key"):
        headers["Authorization"] = "Bearer " + cfg["key"]
    try:
        with urllib.request.urlopen(
                _request(url, payload, headers), timeout=timeout) as resp:
            for data in _sse_data_lines(resp):
                for piece in _openai_parse(data, usage):
                    yield piece
    except urllib.error.HTTPError as e:
        raise ProviderError(_http_message(e)) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError,
            http.client.HTTPException) as e:
        # v7.9: IncompleteRead (an http.client.HTTPException, NOT an
        # OSError) is the literal 'connection dropped before the first
        # token' case - it used to escape as a raw error and the caller's
        # one-calm-retry never fired. Now it is a clean ProviderError.
        raise ProviderError(_network_error(e)) from None


def _anthropic_split(messages):
    """Claude wants the system text as a top-level 'system' field, not a
    message. Returns (system_text, messages_without_system, split_at)
    where split_at is the char count of the STABLE prefix (the core
    rules, marked by nova.py via 'cache_split_at') for prompt caching.
    v6.2.1 fix: a system message without 'content' raised a raw KeyError -
    every other parse helper degrades malformed input, so does this one."""
    sys_parts = []
    rest = []
    split_at = 0
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system":
            sys_parts.append(str(m.get("content", "")))
            v = m.get("cache_split_at")
            if isinstance(v, int) and 0 < v <= len(str(m.get("content", ""))) \
                    and split_at == 0:
                split_at = v
        else:
            rest.append(m)
    return "\n\n".join(sys_parts), rest, split_at


def _anthropic_parse(data, usage=None):
    """One SSE payload of an Anthropic messages stream -> list of pieces.
    v7.8: message_start carries the input-token count and message_delta
    the output count - folded into `usage` for real cost accounting."""
    try:
        obj = json.loads(data)
    except ValueError:
        return []
    if not isinstance(obj, dict):
        return []
    etype = obj.get("type", "")
    if etype == "error":
        err = obj.get("error")
        # Anthropic documents errors as objects, but some proxies send a
        # plain string - both must end up as a clean message, not a crash
        text = err.get("message", "") if isinstance(err, dict) else str(err)
        raise ProviderError("API error: " + str(text or err)[:300])
    if etype == "message_start":
        msg = obj.get("message")
        mu = msg.get("usage") if isinstance(msg, dict) else None
        if isinstance(mu, dict):
            # v7.9 audit fix: cache tokens are BILLED tokens. The prompt
            # breakpoint this very adapter sets means nearly every real
            # turn carries cache_creation (1.25x) / cache_read (0.1x)
            # counts - dropping them undercounted real spend ~5.8x on
            # measured traffic. The ledger stores one prompt-token
            # number, so fold both into their input equivalents.
            try:
                inp = int(mu.get("input_tokens") or 0)
                cw = int(mu.get("cache_creation_input_tokens") or 0)
                cr = int(mu.get("cache_read_input_tokens") or 0)
            except (TypeError, ValueError, OverflowError):
                inp, cw, cr = 0, 0, 0
            if cw > 10 ** 12 or cr > 10 ** 12:
                cw = cr = 0
            equiv = inp + int(round(cw * 1.25)) + int(round(cr * 0.1))
            _absorb_usage(usage, equiv, 0)
    elif etype == "message_delta":
        mu = obj.get("usage")
        if isinstance(mu, dict):
            _absorb_usage(usage, 0, mu.get("output_tokens"))
        # v8.2: stop_reason max_tokens = the answer was cut at the cap
        dl = obj.get("delta")
        sr = str((dl or {}).get("stop_reason") or "").lower() \
            if isinstance(dl, dict) else ""
        if sr:
            global LAST_FINISH_REASON
            LAST_FINISH_REASON = "length" if sr == "max_tokens" else sr
    if etype == "content_block_delta":
        delta = obj.get("delta") or {}
        if isinstance(delta, dict) and delta.get("type") == "text_delta" and delta.get("text"):
            return [delta["text"]]
    return []


def _anthropic_stream(cfg, model, messages, temperature, timeout, max_tokens=0,
                      usage=None):
    system, msgs, split_at = _anthropic_split(messages)
    url = cfg["base"].rstrip("/") + "/v1/messages"
    try:
        env_cap = max(256, int(os.environ.get("NOVA_MAX_TOKENS", "8192")))
    except ValueError:
        env_cap = 8192
    cap = _int_cap(max_tokens)
    max_tokens_out = max(256, min(env_cap, cap) if cap else env_cap)
    payload = {"model": model, "max_tokens": max_tokens_out, "messages": msgs,
               "stream": True, "temperature": temperature}
    if system:
        # v6.6 economy: one cache breakpoint on the STABLE system text (the
        # core rules + tool briefing). Repeat turns re-read it at 0.1x the
        # input price - on a long coding session that is most of the bill.
        # v6.7 fix: the single breakpoint used to sit on the WHOLE system
        # text - which includes the file map / knowledge / project notes.
        # Every file change then invalidated the cached prefix and each
        # turn PAID the 1.25x cache-write price with zero read hits. The
        # dynamic remainder now rides in a second, uncached block.
        if anthropic_cache_enabled():
            stable, dynamic = system, ""
            if 0 < split_at < len(system):
                stable, dynamic = system[:split_at], system[split_at:]
            blocks = [{"type": "text", "text": stable,
                       "cache_control": {"type": "ephemeral"}}]
            if dynamic:
                blocks.append({"type": "text", "text": dynamic})
            payload["system"] = blocks
        else:
            payload["system"] = system
    headers = {"x-api-key": cfg.get("key", ""),
               "anthropic-version": "2023-06-01"}
    try:
        with urllib.request.urlopen(
                _request(url, payload, headers), timeout=timeout) as resp:
            for data in _sse_data_lines(resp):
                for piece in _anthropic_parse(data, usage):
                    yield piece
    except urllib.error.HTTPError as e:
        raise ProviderError(_http_message(e)) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError,
            http.client.HTTPException) as e:
        raise ProviderError(_network_error(e)) from None


def _gemini_build(messages, temperature, max_tokens=0):
    """Gemini payload: roles are 'user'/'model', system text becomes
    systemInstruction. Returns the request body dict.
    v8.1: a message may carry 'images': [base64-jpeg] - each becomes an
    inline_data part (the AI image-verify layer sends photos this way)."""
    contents, sys_parts = [], []
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        if role == "system":
            if text:
                sys_parts.append(text)
            continue
        if not text and not m.get("images"):
            continue
        parts = [{"text": text}] if text else []
        for b in (m.get("images") or []):
            if isinstance(b, str) and b:
                parts.append({"inline_data": {"mime_type": "image/jpeg",
                                              "data": b}})
        if role == "assistant":
            contents.append({"role": "model", "parts": parts})
        else:
            contents.append({"role": "user", "parts": parts})
    gen = {"temperature": temperature}
    cap = _int_cap(max_tokens)
    if cap:
        gen["maxOutputTokens"] = cap
    payload = {"contents": contents, "generationConfig": gen}
    if sys_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(sys_parts)}]}
    return payload


def _gemini_parse(data, usage=None):
    """One SSE payload of a Gemini streamGenerateContent stream -> pieces.
    v7.8: usageMetadata (present on every chunk) feeds real accounting."""
    try:
        obj = json.loads(data)
    except ValueError:
        return []
    if not isinstance(obj, dict):
        return []
    if obj.get("error"):
        err = obj["error"]
        text = err.get("message", "") if isinstance(err, dict) else str(err)
        raise ProviderError("API error: " + str(text)[:300])
    um = obj.get("usageMetadata")
    if isinstance(um, dict):
        _absorb_usage(usage, um.get("promptTokenCount"),
                      um.get("candidatesTokenCount"))
    out = []
    for cand in obj.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        # v8.2: finishReason MAX_TOKENS = the answer was cut at the cap
        frg = str(cand.get("finishReason") or "")
        if frg:
            global LAST_FINISH_REASON
            LAST_FINISH_REASON = ("length" if frg.upper() == "MAX_TOKENS"
                                  else frg)
        parts = ((cand.get("content") or {}).get("parts")) or []
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if text:
                out.append(text)
    return out


def _gemini_stream(cfg, model, messages, temperature, timeout, max_tokens=0,
                   usage=None):
    base = cfg["base"].rstrip("/")
    # the key goes in a HEADER (it used to ride in the URL query, where it
    # could land in proxy logs); the model name is URL-encoded
    url = f"{base}/models/{urllib.parse.quote(str(model), safe='')}:streamGenerateContent?alt=sse"
    headers = {"x-goog-api-key": cfg.get("key", "")}
    payload = _gemini_build(messages, temperature, max_tokens=max_tokens)
    try:
        with urllib.request.urlopen(
                _request(url, payload, headers), timeout=timeout) as resp:
            for data in _sse_data_lines(resp):
                for piece in _gemini_parse(data, usage):
                    yield piece
    except urllib.error.HTTPError as e:
        raise ProviderError(_http_message(e)) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError,
            http.client.HTTPException) as e:
        raise ProviderError(_network_error(e)) from None


_STREAMS = {
    "openai": _openai_stream,
    "anthropic": _anthropic_stream,
    "gemini": _gemini_stream,
}


def stream_chunks(cfg, model, messages, temperature, timeout=1800, max_tokens=0,
                  usage=None):
    """Dispatch one streaming chat call for ANY non-Ollama provider.
    Yields text pieces; raises ProviderError with a short English message
    on any problem (bad key, HTTP error, dead network...). The caller owns
    the heartbeat / interruption / rendering policy. `max_tokens` = an
    optional output cap (0 = uncapped) - the economy layer sets it per
    section so a chatty model cannot burn credits.
    v7.8 `usage`: an optional dict - when given, the REAL prompt/completion
    token counts reported by the provider's stream are folded into it
    (usage['actual'] flips True), so the cost ledger stops guessing."""
    if cfg.get("kind") == "ollama":
        raise ProviderError("internal: ollama streaming is handled by nova.py")
    # v8.2: the finish-reason flag describes THIS call only - reset at the
    # very top so even a failed dispatch never reports a stale reason
    global LAST_FINISH_REASON
    LAST_FINISH_REASON = ""
    fn = _STREAMS.get(cfg.get("kind"))
    if fn is None:
        raise ProviderError(f"no stream adapter for provider kind '{cfg.get('kind')}'")
    return fn(cfg, model, messages, temperature, timeout, max_tokens=max_tokens,
              usage=usage)


def once(cfg, model, messages, timeout=30, max_tokens=0):
    """v8.1: one COLLECTED chat round-trip for MACHINE callers (the AI
    image-verify / query-expansion layers in nova.py): the stream is
    drained into a single string, nothing is printed, nothing is cached
    and no ledger entry is written (tiny utility calls - the caller may
    account for them itself). Raises ProviderError on any problem."""
    buf = []
    for piece in stream_chunks(cfg, model, messages, 0.1,
                               timeout=timeout, max_tokens=max_tokens,
                               usage=None):
        buf.append(piece)
    return "".join(buf)
