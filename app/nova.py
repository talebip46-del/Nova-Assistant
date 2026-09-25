#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - local AI assistant (the Nova Code coding module)
#  for Ollama, llama.cpp GGUF files and cloud providers
#  Version 8.12.0 - pure Python standard library, zero dependencies.
#  Built for real projects: websites, tools, games, scripts.
#  (release codename: "master switch" - the zero-to-one-hundred
#   assurance audit proved the master switches were not absolute:
#   a guardian the user turned OFF still blocked the web Approve
#   button and still voted in the speculative draft gate, a probe
#   with 'deep on / wiring off' silently skipped the pre-apply gate,
#   and 'python gen.py out.html' was hijacked as a preview and never
#   ran. Plus input hardening: truthy garbage no longer fires the
#   destructive settings resets, non-bool toggles are rejected
#   honestly, nan/inf env timeouts fall back to the default, and the
#   workspace walk prunes .git/node_modules DURING the walk.
#   Every fix ships with the test that proves it; nothing else changed)
#
#  SLOW-HARDWARE BUILD: Ollama answers can take a very long time on weak
#  machines. Nothing here cuts a generation short - timeouts are generous
#  silence-guards only, and a live [waiting] timer shows progress.
#
#  v5.0: AGENT SUPERSTRUCTURE - 20 features, one coherent layer:
#        VERSIONING   every apply batch becomes a persistent snapshot
#                     unit (.nova/snapshots) -> /undo [n] walks back
#                     UNLIMITED steps; /snapshot <label> + /restore keep
#                     manual checkpoints before big moves; when the
#                     workspace is a git repo every apply is ALSO
#                     auto-committed with a generated message (nova:).
#        REVIEW       'd(iff)' in the apply prompt shows a colored
#                     unified diff and approves/rejects EACH hunk of an
#                     === EDIT: === block independently.
#        CONTEXT      the project map is now a STYLE map: top-level
#                     classes/functions per file instead of bare line
#                     counts; .novaignore excludes paths from the
#                     agent's view (map, [READ:], /read, /load).
#        AUTOMATION   after every apply: silent syntax check of the
#                     touched files + optional linters + a detected test
#                     command (pytest/npm/unittest/make) with a compact
#                     report; failures feed straight into the auto/
#                     verify loops. /autotest toggles it.
#        PLANNING     the model keeps a live === PLAN === checklist
#                     across turns (terminal rendering + web todo panel
#                     + /todo management); the auto loop injects the
#                     current plan status into every follow-up.
#        KNOWLEDGE    /skill saves named approaches; repeating the same
#                     successful task kind 3x auto-forges a skill; top
#                     skills are injected into every system prompt.
#        SAFETY       /policy: per-command allowlist/denylist (deny
#                     always wins, even for manual /run);
#                     /explain: analysis mode that refuses every write.
#        MULTI-BRAIN  /council <q>: the SAME question to the active
#                     provider AND a partner brain, both answers shown,
#                     optional judge round merges the best of both.
#        BACKGROUND   /bg <cmd> runs long jobs behind the prompt with a
#                     completion notice on the next prompt (and a PWA
#                     notification in the web face).
#        ACCOUNTING   /cost: per-model token + USD ledger (real counts
#                     where the provider reports them); /estimate prices
#                     a request BEFORE sending it, including a duration
#                     guess learned from this machine's measured speed.
#        MEMORY       the conversation survives terminal restarts
#                     (.nova/memory.json, /memory to manage).
#        PROFILES     per-workspace defaults (.nova/profile.json):
#                     provider, model, mode, timeout persist per project.
#        WEB v2       full PWA (manifest + service worker + icons,
#                     installable on the phone, LAN token auth kept),
#                     self-written syntax highlighting (no CDN),
#                     per-hunk approve/reject UI, todo panel, cost
#                     badge, council panel, background notifications.
#  v4.1: SECURITY & ROBUSTNESS HARDENING (full audit pass) -
#        web face: same-origin (CSRF) + Host checks + JSON content-type
#        enforcement on every POST, DNS-rebinding guard, bytes-safe token
#        compare, Connection: close on error replies (no keep-alive body
#        desync), tab-closed no longer kills a streaming turn, --host ""
#        rejected (it bound 0.0.0.0 with auth off).
#        agent core: /fix and /verify no longer attach pending files twice,
#        'Run:' hint is taken from the LAST line outside file blocks (a
#        Makefile 'run:' inside a FILE block can never hijack execution),
#        tool tokens ([READ:]/[SEARCH:]) must be alone on their own line and
#        the first-in-text one wins, Ctrl+C during /run kills the child tree,
#        NUL/control chars sanitized out of file names, symlink-escape proof
#        safe_join, credential files (.env, .ssh, id_rsa, *.pem...) can
#        never reach the model context, ONE attachment cap helper for every
#        path (/load, /search, /learn, /docs, /review), the current user
#        message itself is now trimmed to fit a small context window,
#        /serve serves in-process with a dotfile/symlink guard, honest
#        wording: shell commands run with FULL user rights (cwd-only
#        confinement - not a security sandbox).
#        providers: non-dict JSON / string errors no longer crash the
#        parsers (clean ProviderError), network failures converted too,
#        Gemini key moved out of the URL into a header + URL-encoded model,
#        NOVA_BASE_URL now only overrides the 'custom' provider.
#        search: truncated-gzip fallback actually runs (EOFError caught),
#        DDG snippets can no longer land on the wrong result, JS-only
#        placeholder pages are not cached for 7 days, private networks
#        (localhost/LAN/link-local + redirects) blocked for page fetches.
#        installers: install.bat quoting + errorlevel checks + CRLF,
#        install.sh safe under curl|bash, python3 version-checked launcher.
#  v5.2: NOVA ASSISTANT + MODEL FILES - the program is now "Nova
#        Assistant" and the coding module inside is "Nova Code".
#        A SECOND way to run a local brain: drop .gguf model files you
#        downloaded into a models folder (NOVA_MODELS_DIR, or
#        ~/.nova/models, or <workspace>/.nova/models) - they are
#        discovered automatically, shown in /model and in the web
#        dropdown, and run via a one-time `ollama create` import (or
#        llama.cpp's llama-server when Ollama is unavailable), cached
#        in .nova/local_models.json. *.safetensors files are listed
#        honestly as 'convert to GGUF first'.
#  v5.1: MODEL FREEDOM - the bundled custom-AI builder is GONE (no more
#        nova-ai/ folder, no Modelfile, no prebuilt nova-code brain).
#        Nova now runs on ANY model in the local Ollama library:
#        every start auto-discovers the installed models and picks a
#        sane coding default, /model shows a rich table (size, family,
#        params, quant) and switches by NAME or by NUMBER, --list-models
#        prints the catalogue from the shell, and the web face gets a
#        model dropdown fed by /api/info. NOVA_MODEL still overrides.
#        /kb load now loads ANY user-chosen file into the knowledge base.
#  v4.0: UNIFIED EDITION - ONE program, TWO faces + multi-provider
#        brains.  python3 nova.py          = terminal face (as before).
#        python3 nova.py --web   = the SAME agent (files, tools, streaming,
#        auto-apply with backups) served as a local web app - the only
#        difference is one option.  /provider switches the brain:
#        ollama (default) | openai | openrouter | groq | deepseek |
#        anthropic | gemini | custom (LM Studio / vLLM / llama.cpp).
#  v3.3: SEARCH DATA EXPANSION - nova_search.py grew to ~330 trusted
#        domains / 42 languages (Android, Kotlin/ktor, Flutter api docs,
#        wasm, x86 assembly, queues/search/API specs, cloud docs, ...),
#        duplicate-domain fail-fast, marker-preserving KB cut, atomic
#        cache writes, precompiled hot regexes, empty-keyword guard.
#  v3.2: DISK MODE - run a model BIGGER than your RAM. Ollama memory-maps
#        model files, so a model larger than RAM still runs: the OS pages
#        the weights in from disk on demand. /disk measures real RAM vs
#        every installed model's size on disk, prints an honest per-disk-
#        type speed estimate (the part that does not fit is re-read from
#        disk for EVERY generated token) and copy-paste swap/pagefile
#        recipes (Linux / Windows / macOS). Fail-soft everywhere: works
#        even when Ollama is down or RAM cannot be detected.
#  v3.1: AGENT LOOPS + SURGICAL EDITS -
#        MULTI-ROUND TOOL LOOP: the model can chain [READ:]/[SEARCH:] over
#        several rounds per answer (NOVA_TOOL_ROUNDS, default 3) with repeat,
#        failure and budget guards - a dead tool can never wedge the turn.
#        /verify <cmd>: AUTOMATIC verify loop - run -> if it fails Nova fixes
#        (files applied without asking, backups kept) -> re-run, up to
#        NOVA_VERIFY_STEPS rounds, and it stops by itself when the SAME error
#        comes back twice (no wasted generations).
#        === EDIT: === PARTIAL-EDIT protocol: SEARCH/REPLACE hunks change a
#        few lines of an existing file instead of rewriting the whole thing -
#        exact-match validation (must match once), backups, /undo support,
#        and far fewer tokens than a full file (safe on the 4096 window).
#  v3.0: CLAUDE-CLASS AGENT ON WEAK HARDWARE -
#        /auto              autonomous build-fix loop (apply -> run -> fix,
#                           up to NOVA_AUTO_STEPS rounds, confirmations on
#                           shell commands unless /auto yolo)
#        NOVA.md            per-project memory (like CLAUDE.md): /init
#                           creates it, it is auto-injected as project law
#        /compact           summarize the conversation to free context
#        /retry             regenerate the last answer
#        /review <file>     strict senior-engineer code review
#        /changes           files created/modified this session
#        search v3.0        more official sources + regex language + KB and
#                           cache robustness fixes (see nova_search.py)
#  v2.6: TOOL-WARE MODEL - one dynamic TOOL REGISTRY is the single source of
#        truth for every slash-command: /help, dispatch, /status AND the
#        model's own system-prompt briefing are all GENERATED from it. Adding,
#        removing or upgrading a tool is a one-entry edit - the model always
#        sees the current tool set, nothing to sync by hand. New model token
#        [READ: file] (inspect a file before editing) beside [SEARCH: query].
#  v2.5: STRONGER BRAIN - rewritten system prompt (exact file protocol with a
#        worked example + language rules for python/js/html+css/sql), a context
#        budget manager (the system prompt can never be silently cut off on a
#        small window), num_predict -1 (no silent answer truncation), smart
#        "continue" recovery after partial answers, chat-mode system prompt.
#  v2.4: SMARTER KNOWLEDGE - trusted-source data tripled (207 domains, all
#        languages: sql, javascript, python, rust, go, c/cpp, csharp, java,
#        php, ...) + language-aware ranking boosts matching official docs.
#  v2.3: HARDENED BUILD - stable /run (capped output capture + full process-
#        tree kill, no hangs, no RAM blowups), localhost-only preview server,
#        LF-safe file writing, Windows reserved-name defense, web-UI fixes.
#  v2.2: WEB RESEARCH & LEARNING - the agent can update its own knowledge
#    /search <query>   web search (trusted sources first)
#    /docs <url>       read one documentation page into context
#    /learn <topic>    deep research, saved into a persistent knowledge base
#    /kb               manage saved knowledge
#    auto [SEARCH: q]  the model itself can request fresh facts mid-answer
#  Powered by nova_search.py (keyless: DuckDuckGo, Wikipedia, Stack Exchange).
#
#  Usage:
#      python3 nova.py [workspace]            terminal face (default)
#      python3 nova.py --web [--port 8765]    web face - the same agent
#      /provider <name>                       switch the brain (ollama |
#                                             openai | openrouter | groq |
#                                             deepseek | anthropic |
#                                             gemini | custom)
#
#  All terminal output is English. Talk to the model in any language.
# =====================================================================
import atexit
import ast
import base64
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

AGENT_NAME = "Nova Assistant"     # the program   (Nova Code = coding module)
CODING_BRAND = "Nova Code"
#  v7.12: WEB SEARCH IN THE SIMPLE CHAT (the user's ask: "توی چت معمولی
#         هم باید سرچ وب داشته باشیم"):
#        - the گفت و گو tab used to answer from the model's weights only -
#          every "latest / price / news / weather" question got a stale
#          guess. Now a compact [WEB RESULTS] block rides with the turn:
#          ranked trusted-first by nova_search (v7.10 already biases
#          Persian queries toward 56 credible Iranian domains).
#        - three modes persisted per workspace (.nova/talk_web.json):
#          off | auto (default - the turn is searched when its wording
#          implies fresh facts) | always. The browser shows a segmented
#          control and renders the sources under the answer.
#        - the search runs fail-soft: no network = the answer continues
#          without the block and a note explains it. Sources stream as a
#          structured {t:"web"} event; the block itself never enters the
#          talk history, so context stays clean.
#        - talk-side commands: /web [off|auto|always] and /search <query>
#          (manual search right inside the chat bubble, no model call).
#  v7.11: IRANIAN SERVICES with API keys (the user's ask: "از هر کاری
#         بتونم از چند تا سایت ایرانی api key بگیرم - مثلا کاوه نگار برای
#         پیامک - و فقط به اسمایی که می‌گم فکر نکن"):
#        - nova_iran_services.py: 20 trusted Iranian services across 6
#          categories - SMS (Kavenegar/MeliPayamak/Ghasedak/SMS.ir/
#          FarazSMS), payment (Zarinpal/IDPay/Zibal/NextPay/Payping),
#          maps (Neshan/Map.ir), crypto (Nobitex/Wallex/Bitpin/Ramzinex),
#          messenger bots (Bale/Eitaa/Rubika) and video (Aparat).
#        - /services command + the web "سرویس‌های ایرانی" panel: save the
#          key in the workspace vault (.nova/iran_services.json, chmod
#          600), run the SAFE free test (getMe / account info / public
#          market data / sandbox payment), then call real actions
#          (send_sms, create_payment, directions, market stats...).
#        - EVERY call is metered per service (requests/ok/fail/last
#          status/error/latency) and shown in the panel - nothing hides.
#        - the agent can call it too (/services is model-briefed).
#  v7.9: THE REAL b.ai + the usage panel (the user's ask: "منظورم واقعا
#        سایت b.ai بود" + "بتونم ببینم چقدر توکن-درخواست-کردیت مصرف کردم
#        و چقدر context"):
#        - b.ai is the B.AI platform (chat.b.ai / api.b.ai, docs.b.ai) -
#          a unified LLM gateway with its own OpenAI-compatible endpoint.
#          The v7.8 guess ('b.ai' = Blackbox) was wrong; 'bai' is now its
#          own provider (BAI_API_KEY) and blackbox keeps its own entry.
#        - USAGE PANEL: /cost and the web economy card show what the
#          clouds actually consumed - requests, prompt/completion tokens,
#          USD + credit estimate (b.ai law: 1 USD = 1,000,000 credits),
#          and how much CONTEXT the last request filled of its window.
#        - web action cost_reset clears the ledger from the panel.
#  v7.8: CLOUD FIRST + request economy round 2 (the user's ask: cloud
#        models with API keys, 'b.ai' in the provider list, best output
#        with the least credit/request/token burn):
#        - REAL usage capture from cloud SSE streams (OpenAI/Anthropic/
#          Gemini and every OpenAI-compatible final chunk) - the cost
#          ledger, daily budgets and /cost run on real tokens, no guesses.
#        - one automatic retry on transient cloud failures (HTTP 429/5xx,
#          network blips) BEFORE the first token - a rate-limited turn
#          survives instead of dying (and the user re-sending costs more
#          than the one calm retry).
#        - cache_talk: identical resent talk turns are answered from the
#          local response cache - zero tokens, zero credits, zero requests.
#        - v7.13 NOVA INTEL: real Project Intelligence (one integrated
#          scan), a REAL task graph with dependencies, SEMANTIC memory
#          (scored recall, not raw history), a Context Engine, the
#          instrumented agent loop (observe->decide->execute->test->
#          fix->verify), honest completion detection (a success claim
#          without evidence is rejected), smart recovery, impact
#          analysis, regression detection, automatic test skeletons,
#          the staged critic, smart rollback, multi-project workspaces
#          and project/user profiles - all local, all fail-soft.
# v7.14: THE THINK PROTOCOL - visible reasoning for every brain: forced
#        === THINK === / === END === blocks for models without native
#        reasoning, native <think> capture for reasoners, clean separation
#        (thinking never becomes files, tool tokens or history bloat).
# v8.0 "clear" - THE STABILITY RELEASE:
#        word-by-word audit of every file (55+ verified bugs fixed);
#        the stability four: nova_flightlog (the agent's black box of
#        decisions, /blackbox), hardened atomic writes (durable rename,
#        0600 secrets, quarantine + last-good restore), the FileSandbox
#        (agent file access confined to the workspace; .nova and
#        sensitive system paths refused, /sandbox files), and the plugin
#        system (user side-tools OUTSIDE the core, .nova/plugins/*.json,
#        SSRF-guarded, quarantined on corruption, /plugin). Honesty
#        hardening: string evidence is no longer "verification", early
#        loop exits are no longer fake "done", "no tests ran" is no
#        longer a pass.
# v8.3 "context engine" - THE USER OWNS THE WINDOW:
#        nova_ctxengine.py - per-backend context windows, settable from
#        the web (Models tab) and /ctxset: LOCAL (Ollama / llama.cpp /
#        LM Studio / vLLM) and CLOUD windows are separate by design;
#        Nova's number OVERRIDES the runtime default (num_ctx on every
#        Ollama call, -c when spawning llama-server) - whatever Ollama
#        picked for the model stops mattering. When a conversation
#        outgrows the window, the old block is folded into a SMART
#        DIGEST (goals / file paths / commands / decisions kept,
#        chatter dropped, newest messages verbatim) - deterministic and
#        offline: no model call, no credits, weak-hardware safe. The
#        model-summarized /compact stays as the manual deep option.
# v8.4 "code guardian" - NOTHING BROKEN REACHES THE DISK:
#        nova_guardian.py - ONE supervisor agent + a fleet of language
#        sub-sub-agents (~30 profiles) watching EVERY file the model
#        produces: a REAL parser where Python ships one (ast/json/yaml/
#        toml), parse-only tools when installed (node --check, bash -n,
#        php -l, ruby -c, gofmt, luac, gcc -fsyntax-only), a string-
#        aware bracket scanner (comments/strings/heredocs per family)
#        for everything else, plus high-signal bug patterns. The pre-
#        apply gate REJECTS a syntax-broken batch atomically (nothing
#        is written) and hands the model an exact per-line repair
#        prompt. After the apply, the sub-sub-agents review the touched
#        files IN PARALLEL on the local brain (nova_subagent) - their
#        findings feed the next fix round. The fleet has its OWN
#        websearch channel ("guardian:" cache namespace, hard 8 s
#        budget) for fresh references, but correctness NEVER depends
#        on the internet: a built-in offline knowledge base answers
#        when the network is gone.
# v8.5 "bug hunter" - SYNTAX WAS ONLY HALF THE PROBLEM:
#        nova_probe.py - FOUR behavior probes hunting the bug classes
#        a syntax gate cannot see (the user: "the code parses fine -
#        but a part of the work is missing, or a button does nothing"):
#        WIRING (deterministic, offline): the element graph across the
#        batch + workspace - every getElementById/querySelector lookup,
#        inline onclick handler, <script src>/<link href> file and
#        every relative import must land on something real, or the
#        batch is REFUSED before one byte is written (the exact
#        dead-reference list rides to the next turn as repair context).
#        SMOKE: freshly written entry scripts are EXECUTED (tight
#        timeout, stdin closed, the run-sandbox honored when on) and
#        the crash is parsed into a finding - server starts and
#        interactive input are recognized, never false bugs.
#        BROWSER: when Playwright/Chromium exist, the applied page
#        loads headless (file:// - fully offline): console errors,
#        page errors, failed resources, then up to 8 visible buttons
#        are CLICKED - a crash on click is a dead feature, caught.
#        COMPLETENESS: the LOCAL brain compares the user's request
#        with the wiring skeletons (ids/buttons/functions) of the
#        delivered files - "a part of the work fell off" becomes a
#        finding. Advisory only, never a cloud key.
#        Settings .nova/probe.json (on/wiring/smoke/browser/review/
#        reject_wiring), /probe command, web panel in the Models tab.
#        Correctness NEVER depends on the internet or a browser.
VERSION = "8.12.0"
CODENAME = "master switch"
OLLAMA_URL = os.environ.get("NOVA_OLLAMA_URL", "http://localhost:11434")
# Preferred base model name (no tag). Startup resolves it against the
# ACTUAL installed models: exact -> tag variant -> best auto-pick, so a
# machine without this exact name still boots on a good local brain.
DEFAULT_MODEL = "qwen2.5-coder"

HISTORY_LIMIT = 12        # messages kept in context (small-model friendly)
MAX_TRANSCRIPT_RAM = 400  # v6.3: /export transcript entries kept in RAM (bounded)
MAX_LOAD_CHARS = 8000     # max chars injected per attached file
MAX_FIX_CHARS = 6000      # max chars per file auto-attached for debugging
MAX_ERROR_CHARS = 3500    # max chars of command output sent to the model
MAX_READ_CHARS = 4000     # max chars printed by /read
MAP_MAX_FILES = 50        # max entries in the project file map
MAX_FIX_FILES = 3         # max files auto-attached by the debug loop
MAX_ATTACHMENTS = 8       # max pending /load attachments (protects small ctx)
RUN_OUTPUT_CAP = 400_000  # max chars captured per stream of /run (RAM safety)
MAX_EDIT_FILE_CHARS = 400_000  # === EDIT: === refuses files bigger than this
NOVA_MD_FILE = "NOVA.md"      # per-project memory (auto-injected, project law)
MAX_NOVA_MD_CHARS = 2500     # injection cap for NOVA.md (context safety)
AUTO_YOLO = os.environ.get("NOVA_AUTO_YOLO", "0") == "1"  # skip run confirms

# ---- patience settings (very weak hardware friendly) -----------------------
# On a slow machine, loading the model + evaluating the prompt can take
# several minutes before the FIRST token appears. SOCK_TIMEOUT is NOT a
# total-answer limit: it only caps the silence between two chunks. While
# tokens keep arriving, a generation is never cut off.
def _envint(name, default):
    """int from an env var - a typo like NOVA_NUM_CTX=abc must never crash
    the agent at import time (falls back to the default instead)."""
    raw = str(os.environ.get(name, "")).strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


SOCK_TIMEOUT = _envint("NOVA_TIMEOUT", 1800)   # max silence (s)
KEEP_ALIVE = os.environ.get("NOVA_KEEP_ALIVE", "60m")        # keep model in RAM
NUM_CTX = max(512, _envint("NOVA_NUM_CTX", 4096))            # context window (512 floor - v8.7: a 0/negative env value used to flow into the payload)
DEFAULT_RUN_TIMEOUT = _envint("NOVA_RUN_TIMEOUT", 120)
RUN_TIMEOUT_CAP = 3600                                       # /timeout upper bound
CTX_RESERVE = _envint("NOVA_CTX_RESERVE", 1400)  # tokens kept free for the ANSWER
CTX_CHARS_PER_TOKEN = 2.7    # conservative chars-per-token estimate (mixed
                             # English/code/Persian - deliberately pessimistic)
AUTO_MAX_STEPS = max(1, min(12, _envint("NOVA_AUTO_STEPS", 5)))  # /auto rounds
# NOTE: these MUST stay below _envint's definition (v3.0 caught that bug the
# hard way - a NameError at import is the worst possible first impression).
MAX_TOOL_ROUNDS = max(1, min(6, _envint("NOVA_TOOL_ROUNDS", 3)))  # model tool
                          # rounds per user message ([READ:]/[SEARCH:] chains)
VERIFY_MAX_STEPS = max(1, min(8, _envint("NOVA_VERIFY_STEPS", 3)))  # /verify
                          # run -> auto-fix -> re-run rounds
# v8.6: the ACTIVE workspace/model for the sess-less image hooks (the
# vision gate + verifier resolve settings and the brain through this).
_VISION_ACTIVE = {"ws": None, "model": None}

MODES = {"code": 0.4, "balanced": 0.6, "creative": 0.8}
MODE_HINTS = {
    "code": "CURRENT MODE: code - prioritize correctness, precision and efficiency. "
            "Handle this request as serious engineering work.",
    "balanced": "CURRENT MODE: balanced - correct code with tasteful polish.",
    "creative": "CURRENT MODE: creative - add visual flair, smooth animations and "
                "delightful details, but keep the code correct and lightweight.",
}
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".nova_backups", "venv",
                ".venv", ".idea", ".vscode", ".nova"}

# file names must stay on ONE line: under re.DOTALL a bare (.+?) could
# otherwise match across newlines and fabricate a multi-line file name
FILE_RE = re.compile(r"===\s*FILE:\s*([^\n]+?)\s*===\s*\n(.*?)(?:\n|^)\s*===\s*END(?:\s+FILE)?\s*===", re.DOTALL | re.MULTILINE)
FENCED_RE = re.compile(r"```[A-Za-z0-9_+#.-]*[^\n]*\n(.*?)```", re.DOTALL)
NAME_COMMENT_RE = re.compile(
    r"^\s*(?:#|//|<!--|/\*)\s*file\s*:\s*([^\s*>]+?)\s*(?:-->)?\s*(?:\*/)?\s*$", re.IGNORECASE
)
PY_TRACEBACK_RE = re.compile(r'File "([^"\n]+)", line')
GENERIC_FILE_RE = re.compile(r'([\w./\\-]+\.(?:py|js|html|css|json))\s*[(:]')
SEARCH_TOKEN_RE = re.compile(r"\[SEARCH:\s*([^\]\n]{3,120}?)\s*\]", re.IGNORECASE)
READ_TOKEN_RE = re.compile(r"\[READ:\s*([^\]\n]{1,200}?)\s*\]", re.IGNORECASE)
IMG_TOKEN_RE = re.compile(r"\[IMG:\s*([^\]\n]{3,120}?)\s*\]", re.IGNORECASE)
# === EDIT: === partial-edit protocol (v3.1): the whole block, then the
# SEARCH/REPLACE hunks inside it. The markers mirror git-conflict style so
# small models copy them reliably; the block closes with === END ===.
EDIT_RE = re.compile(r"===\s*EDIT:\s*([^\n]+?)\s*===\s*\n(.*?)\n?\s*===\s*END(?:\s+EDIT)?\s*===",
                     re.DOTALL)
# The <{7} SEARCH marker is LINE-ANCHORED via (?:^|\n): without the anchor an
# eight-arrow '<<<<<<<< SEARCH' would still match by shifting the regex one
# arrow to the right (the (?:^|\n) then no longer fits before arrow #2).
EDIT_HUNK_RE = re.compile(
    r"(?:^|\n)<{7}[ \t]*SEARCH[ \t]*\n(.*?)\n={7}[ \t]*\n(.*?)\n?>{7}[ \t]*REPLACE",
    re.DOTALL)
EDIT_HUNK_CLOSE_RE = re.compile(r"(?:^|\n)>{7}[ \t]*REPLACE")
# NOTE: exactly one arrow before {7} - ">>{7}" would mean EIGHT arrows and
# silently refuse every well-formed hunk (caught by v3.1 QA bisecting).
EDIT_HUNK_OPEN_RE = re.compile(r"(?:^|\n)<{7}[ \t]*SEARCH")
# v7.7: the HEADER of an === EDIT: === block - used by parse_edits to find
# blocks whose === END === never came (same recovery idea as _FILE_OPEN_RE).
# Line-anchored, but tolerates a leading ``` fence: weak models wrap the
# whole protocol block in fences and the old anywhere-match accepted that.
_EDIT_OPEN_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:```[ \t]*)?===[ \t]*EDIT:[ \t]*([^\n]+?)[ \t]*===",
    re.MULTILINE)
# v7.7: the salvage STOP for an unclosed EDIT body when no hunk close
# exists. NOT _BLOCK_STOP_RE: a hunk's own '=======' separator line starts
# with '===' and would cut the body before the >>>>>>> REPLACE side - only
# the next block HEADER or the model's Run/Preview hint line ends it.
_EDIT_SALVAGE_STOP_RE = re.compile(
    r"^[ \t]*(?:```[ \t]*)?===[ \t]*(?:FILE|EDIT)[ \t]*:.*$|"
    r"^[ \t]*(?:run|preview)[ \t]*:.*$",
    re.MULTILINE | re.IGNORECASE)
# the next block HEADER alone - the hard limit a salvaged body can never
# cross (a 'run:' line INSIDE hunk content must not bound it)
_EDIT_NEXT_HDR_RE = re.compile(
    r"^[ \t]*(?:```[ \t]*)?===[ \t]*(?:FILE|EDIT)[ \t]*:.*$",
    re.MULTILINE | re.IGNORECASE)


def _hdr_start(text, m):
    """The position of the opening '===' of an _EDIT_OPEN_RE match. The
    regex's (?:^|\n) anchor CONSUMES the newline, so m.start() sits one
    char before the closed-block EDIT_RE span starts - the containment
    checks need the real '===' position, not the anchor."""
    return m.start() + m.group(0).index("===")


def _salvage_bound(text, body_start, limit_pos):
    """Where a salvaged (unclosed) EDIT body ends. When a complete hunk
    close (>>>>>>> REPLACE) exists, the body extends PAST any 'run:' line
    inside the hunk content (a Makefile target is hunk content, not a Run
    hint) up to the end of that close; without a close, the model's
    Run/Preview hint line or the next header bounds the body."""
    seg = text[body_start:limit_pos]
    closes = list(EDIT_HUNK_CLOSE_RE.finditer(seg))
    if closes:
        return body_start + closes[-1].end()
    stop = _EDIT_SALVAGE_STOP_RE.search(seg)
    return body_start + (stop.start() if stop else len(seg))
# commands that never exit on their own (servers) - /verify refuses them:
# a verify loop against a server would only time out and "fix" healthy code
SERVER_HINTS = ("/serve", "http.server", "uvicorn", "gunicorn", "flask run",
                "npm run dev", "next dev", "vite", "jupyter", "webpack serve",
                "npx serve")
# the "Run: ..." / "Preview: ..." line the model ends coding answers with
RUN_HINT_RE = re.compile(r"^\s*(?:run|preview)\s*:\s*(.+?)\s*$",
                         re.MULTILINE | re.IGNORECASE)
KB_FILE = ".nova_knowledge.md"          # per-workspace learned knowledge

# Credential-ish files must never flow into the model's context: with a
# cloud provider active they would leave the machine (.env, SSH/AWS keys,
# git credentials, certificates...). The file map already hides dotfiles;
# this pattern guards the [READ:] tool and every attachment path.
SECRET_FILE_RE = re.compile(
    r"(?:^|/)(?:"
    r"\.env(?:\.[^/]*)?|\.netrc|\.npmrc|\.pgpass|\.git-credentials|"
    r"id_rsa[^/]*|id_ed25519[^/]*|id_ecdsa[^/]*|id_dsa[^/]*|"
    r"\.git/config|\.docker/config\.json|\.kube/config|"
    r"\.ssh/[^/]+|\.aws/[^/]+|"
    r"[^/]+\.(?:pem|key|p12|pfx|keystore)"
    r")$", re.IGNORECASE)


def is_secret_path(rel):
    """True for credential files that must never reach the model context."""
    r = str(rel).strip().replace("\\", "/").lstrip("/")
    return bool(SECRET_FILE_RE.search(r))

# Windows reserved device names - a file with one of these names would
# write to the console/printer instead of the disk, so they get a "_" suffix.
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    "COM" + str(i) for i in range(1, 10)} | {"LPT" + str(i) for i in range(1, 10)}

# Web research module (same folder). Missing file = search features off,
# everything else keeps working fully offline.
try:
    import nova_search as ns
except Exception:
    ns = None

# v7.11: Iranian service providers (SMS / payment / maps / crypto / bots
# / video) with per-workspace API keys and usage metering. Missing file
# = everything else works, /services and the web panel answer cleanly.
try:
    import nova_iran_services as iran
except Exception:
    iran = None

# Model provider layer (same folder): lets the SAME agent run on top of
# any local Ollama model (default - auto-discovered at startup) or on any
# cloud / self-hosted API. Missing file = only Ollama is available and
# everything else keeps working.
try:
    import nova_providers as providers
except Exception:
    providers = None

# Web-mode hooks (set by web_server.py before any turn):
#   TOKEN_SINK      fn(piece) - answer tokens stream to the browser
#                   instead of being written to stdout
#   EVENT_SINK      fn(dict) - structured UI events (todo updates,
#                   background notices) for the web face; terminal keeps
#                   it None and renders everything itself
#   NONINTERACTIVE  every interactive prompt auto-answers with the safe
#                   default ('') - the web has no keyboard to ask
TOKEN_SINK = None
EVENT_SINK = None
NONINTERACTIVE = False
# v6.9: >0 while /agent runs parallel sub-agents - their per-call
# heartbeat lines would otherwise overwrite each other's streamed
# output on one terminal (the lock serializes bytes, not lines).
_PARALLEL_DEPTH = 0
# v6.9: a --provider CLI flag outranks the workspace profile for THIS run
_CLI_PROVIDER = None


def emit_event(obj):
    """Push one structured UI event to the web face (when it is
    listening). Terminal mode: silently ignored. A broken sink must
    never break an agent turn."""
    if EVENT_SINK is not None:
        try:
            EVENT_SINK(obj)
        except Exception:
            pass


# --------------------------------------------------------------- feature modules
# The v5.0 superstructure. They ship together with nova.py; a missing
# module degrades exactly one feature instead of the whole agent.
try:
    import nova_policy as npol
except Exception:
    npol = None
try:
    import nova_project as nproj
except Exception:
    nproj = None
try:
    import nova_memory as nmem
except Exception:
    nmem = None
try:
    import nova_cost
except Exception:
    nova_cost = None
try:
    import nova_snapshots as snaps
except Exception:
    snaps = None
try:
    import nova_diffview as diffview
except Exception:
    diffview = None
try:
    import nova_repomap as repomap
except Exception:
    repomap = None
try:
    import nova_feedback as feedback
except Exception:
    feedback = None
try:
    import nova_todo
except Exception:
    nova_todo = None
try:
    import nova_skills as skills
except Exception:
    skills = None
try:
    import nova_bg
except Exception:
    nova_bg = None
try:
    import nova_council as council
except Exception:
    council = None
try:
    import nova_commitmsg as commitmsg
except Exception:
    commitmsg = None
try:
    import nova_models as nmodels
except Exception:
    nmodels = None
try:
    import nova_localmodels as lmodels
except Exception:
    lmodels = None
# v7.13: PROJECT INTELLIGENCE CORE - the unified brain for the task
# graph, semantic memory, context engine, the honest agent loop,
# impact analysis, regression detection, test skeletons, the staged
# critic and smart rollback. Missing file = every feature above keeps
# working exactly as before, just without the intelligence layer.
try:
    import nova_intel as intel
except Exception:
    intel = None
# v7.14: the THINK protocol layer - missing file = no forced reasoning,
# native <think> hygiene off; everything else keeps working as before.
try:
    import nova_think as think
except Exception:
    think = None
# v6.3: security + logging layer (ships with nova.py; degrade to None so
# a partial copy keeps the agent booting, exactly like the modules above)
try:
    import nova_security as nsec
except Exception:
    nsec = None
try:
    import nova_log
except Exception:
    nova_log = None
# v8.0 "clear": the stability four - flight recorder (the agent's black
# box of decisions), file sandbox (agent file-access isolation). Both
# optional like every sibling: a partial copy still boots.
try:
    import nova_flightlog as flightlog
except Exception:
    flightlog = None
try:
    import nova_sandbox as sandbox
except Exception:
    sandbox = None
try:
    import nova_plugins as plugins
except Exception:
    plugins = None
# v6.6: request economy layer (response cache, budgets, saved-counters).
# Missing file = the agent works exactly as before, just without the diet.
try:
    import nova_economy as econ
except Exception:
    econ = None
# v6.8: edit-harness / autonomy / hardware / security upgrades. Every
# import stays optional - a partial copy of the app must still boot.
try:
    import nova_hardware as hardware
except Exception:
    hardware = None
try:
    import nova_secretbox as secretbox
except Exception:
    secretbox = None
try:
    import nova_rlimits as rlimits
except Exception:
    rlimits = None
# (nova_sandbox is imported once above, next to nova_flightlog - v8.0)
try:
    import nova_astmap as astmap
except Exception:
    astmap = None
try:
    import nova_depgraph as depgraph
except Exception:
    depgraph = None
try:
    import nova_subagent as subagent
except Exception:
    subagent = None
try:
    import nova_bench as bench
except Exception:
    bench = None
try:
    import nova_quality as quality
except Exception:
    quality = None
# v7.0: the DESIGN ENGINE - weak models still ship beautiful websites.
# Deterministic beauty floor + web-intent design contract; missing file =
# the agent works exactly as before, just without the polish.
try:
    import nova_design as design
except Exception:
    design = None
# v7.2: Nova IMAGES - the agent finds and downloads real photos from the
# internet for the sites it builds (SSRF-safe, deadline-bounded, offline
# falls back to generated local art). Missing file = no photo features,
# everything else keeps working.
try:
    import nova_images as imgsys
except Exception:
    imgsys = None
# v7.3: Nova FONTS - a local, offline font library (Persian + English,
# SIL OFL) and a context-aware pairing engine: the agent picks the right
# fonts per project, the model can override per page via
# <meta name="nova-fonts" content="...">. Missing file = system fonts,
# everything else keeps working.
try:
    import nova_fonts as fontsys
except Exception:
    fontsys = None
# v7.5: the BACKEND-AWARE layer + the new power features. Missing file =
# the corresponding feature is simply absent, everything else keeps working
# (the same fail-soft contract as every module above).
try:
    import nova_backend as backend_policy
except Exception:
    backend_policy = None
try:
    import nova_idioms as idioms
except Exception:
    idioms = None
try:
    import nova_router as router
except Exception:
    router = None
try:
    import nova_rag as rag
except Exception:
    rag = None
try:
    import nova_style as style
except Exception:
    style = None
try:
    import nova_explore as explore
except Exception:
    explore = None
# v8.3 "context engine": per-backend context windows (local vs cloud,
# user-settable from the web/terminal) + the smart history digest.
# Missing file = pre-8.3 behavior exactly (env/global windows only).
try:
    import nova_ctxengine as ctxengine
except Exception:
    ctxengine = None
# v8.4 "code guardian": the supervisor agent + the language sub-sub-
# agent fleet (deterministic multi-language gate + parallel model
# reviews + the dedicated, offline-safe websearch). Missing file =
# pre-8.4 behavior exactly (the classic lint gate alone).
try:
    import nova_guardian as guardian
except Exception:
    guardian = None
# v8.5 "bug hunter": the four behavior probes (wiring / smoke /
# browser / completeness) - they catch what syntax gates cannot: the
# dead button, the missing file, the crashed entry script, the
# fallen-off requirement. Missing file = pre-8.5 behavior exactly.
try:
    import nova_probe as probe
except Exception:
    probe = None
# v8.6 "vision": the local-model VISION layer - 100% automatic
# detection of whether the active local brain can see images (ollama
# /api/show capabilities / families / gguf keys / name fallback) plus
# the approval policy for internet photos (the local AI must approve
# every selection and download). Missing file = pre-8.6 behavior.
try:
    import nova_vision as vision
except Exception:
    vision = None

# --------------------------------------------------------------- colors
class C:
    B = "\033[1m"; P = "\033[95m"; CY = "\033[96m"; G = "\033[92m"
    Y = "\033[93m"; R = "\033[91m"; D = "\033[2m"; E = "\033[0m"

USE_COLOR = sys.stdout.isatty() and os.environ.get("NOVA_NOCOLOR") != "1"

def c(color, text):
    return (color + text + C.E) if USE_COLOR else text

def ask(prompt):
    """input() wrapper honoring colors. In web mode (NONINTERACTIVE) it
    auto-answers with the safe default ('') and logs the decision so the
    user sees what was chosen on their behalf."""
    if NONINTERACTIVE:
        print(c(C.D, str(prompt).strip() + " -> (auto)"))
        return ""
    if USE_COLOR and "readline" in sys.modules:
        # v6.5: same readline width fix as the main REPL prompt
        return input("\001" + C.CY + "\002" + str(prompt) + "\001" + C.E + "\002")
    return input(c(C.CY, prompt) if USE_COLOR else prompt)


def ui_input(prompt=""):
    """input() for OPTIONAL interactive extras (pick-from-list, save-as).
    In web mode it returns '' so the extra is simply skipped."""
    if NONINTERACTIVE:
        return ""
    return input(prompt)

def setup_terminal():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if os.name == "nt":
        os.system("")  # enable ANSI escape sequences on Windows 10+
    try:
        import readline  # noqa: F401  (arrow keys / input history on POSIX)
    except ImportError:
        pass

# --------------------------------------------------------------- helpers
def http_get_json(path, timeout=10):
    """Small local calls only (/api/tags, /api/show). 10 s: even a busy,
    slow machine answers these quickly enough - no need to be stingy."""
    req = urllib.request.Request(OLLAMA_URL + path)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def model_details(model):
    """Short model description via /api/show, e.g. 'qwen2 - 3.2B'. '' on failure."""
    try:
        req = urllib.request.Request(
            OLLAMA_URL + "/api/show",
            data=json.dumps({"model": model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        det = d.get("details", {})
        fam, size = det.get("family", "") or "", det.get("parameter_size", "") or ""
        return (fam + (" - " + size if size else "")).strip()
    except Exception:
        return ""

def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0

def _model_fmt_size(n):
    """v6.5: size formatting for /model and --list-models with a fallback
    for a partial install (nova_models.py missing): a .gguf on disk used
    to crash the table with AttributeError on the None module."""
    if nmodels is not None:
        return nmodels.fmt_size(n)
    return human_size(n) if isinstance(n, (int, float)) and n is not None else ""

def py_run_name():
    """Interpreter name to suggest for 'Run:' hints (python3 / python / py).
    v6.4 fix: a frozen (PyInstaller) exe must never suggest ITSELF -
    sys.executable there is the packaged NovaAssistant.exe, so the old
    suggestion was literally 'NovaAssistant.exe main.py' (running it just
    spawned a second Nova). On a frozen build fall back to whatever real
    python exists on PATH."""
    if getattr(sys, "frozen", False):
        return _pick_python_name()
    # non-frozen: basename(sys.executable) is usually right, but on Windows
    # it can be pythonw.exe (silent, no console) or carry an ugly ".exe"
    # suffix - let _pick_python_name pick a sane console interpreter
    # (it returns this very interpreter when it is a good choice).
    return _pick_python_name()

def _pick_python_name():
    """A python interpreter name that actually exists on THIS machine.
    Windows: PATH lookup first, order python/py/python3 (the python3.exe
    there is often only the Microsoft Store stub). Nova's own interpreter
    name is only a fallback - it may be pythonw.exe (no console output)
    or a Store stub, and a frozen exe is NovaAssistant.exe, never a real
    python. POSIX: Nova's own interpreter first (a venv's python3.12 is
    more precise than bare python3), then PATH."""
    own = ""
    if not getattr(sys, "frozen", False):
        base = os.path.basename(sys.executable or "").lower()
        if base.startswith("python") and not base.startswith("pythonw"):
            own = os.path.basename(sys.executable or "")
    if os.name == "nt":
        for cand in ("python", "py", "python3"):
            if shutil.which(cand):
                return cand
        if own:
            return own
        return "py"
    if own:
        return own
    for cand in ("python3", "python"):
        if shutil.which(cand):
            return cand
    return "python3"

def _normalize_run_hint(cmd):
    """Make the model's 'Run:' hint actually executable on THIS machine
    (v6.4). Small models copy the system prompt's 'python3' even on
    Windows, where python3.exe does not exist - the suggested command then
    fails with 'python was not found' and the user's Run click does
    nothing. Rewrite ONLY the interpreter token to one that exists here;
    everything else stays exactly as the model wrote it."""
    cmd = str(cmd or "").strip().strip("`\"'").strip()
    if not cmd:
        return cmd
    parts = cmd.split()
    tok = parts[0].lower()
    if tok == "python" or tok == "python3" or tok == "py" \
            or tok == "py3" or tok.startswith("python3."):
        parts[0] = _pick_python_name()
        return " ".join(parts)
    return cmd

# ---- v7.7: 'Run:' hints that are really PREVIEWS -------------------------
# Weak models end a WEBSITE answer with 'Preview: index.html' or
# 'Run: start index.html'. Handing that to a shell exits 127 / 'not
# recognized' even though the site is perfectly healthy - the click then
# looks "failed", the auto-fix round fed a NON-EXISTENT error back to the
# model, and the model rewrote HEALTHY files (the user-reported
# "run worked, I asked for an edit, then everything broke" loop).
# A preview-hint is intercepted before the shell and opens the file instead.
_PREVIEW_PREFIX_RE = re.compile(
    r"^(?:cmd(?:\.exe)?\s*/c\s+|start\s+(?:\"\"\s+)?|open\s+|xdg-open\s+|"
    r"explorer(?:\.exe)?\s+)", re.IGNORECASE)
# a document path can never contain shell metacharacters - this class
# (letters/digits incl. Persian via \w, dot, slash, space, dash, parens,
# plus, ZWNJ/ZWJ/marks - ubiquitous inside Persian words like
# تازه‌سازی, and NBSP) refuses ; | & $ ` > < quotes and newlines outright
_PREVIEW_PATH_RE = re.compile(
    r"^[\w./\\() +\-\u200c\u200d\u200e\u200f\u00a0]+\.(?:html?|htm)$")


def preview_target(ws, cmd):
    """A Run/Preview hint that really means 'open this document in a
    browser' (a bare .html/.htm path, optionally behind start/open/
    xdg-open/explorer/cmd /c). Returns the Path when it is a preview
    hint (existing or not - the caller distinguishes), else None.
    Workspace-relative first; an EXISTING absolute file path is accepted
    too (the click is an explicit user action and no shell is involved).
    Anything with shell metacharacters is refused by the path regex and
    falls through to the normal screened shell path."""
    cmd = str(cmd or "").strip().strip("`\"'").strip()
    if not cmd:
        return None
    # peel ONE OR MORE open-prefixes: 'cmd /c start index.html' is a
    # cmd/c wrapping a start wrapping the document
    while True:
        m = _PREVIEW_PREFIX_RE.match(cmd)
        if not m:
            break
        cmd = cmd[m.end():].strip().strip("\"'").strip()
    # peel FLAG tokens ('start /min index.html', 'xdg-open --arg x.html'):
    # a flag has no dot, so a real path (which needs its extension) survives
    while True:
        head, sep, rest = cmd.partition(" ")
        if sep and head[:1] in ("/", "-") and "." not in head \
                and "\\" not in head and len(head) < 32:
            cmd = rest.strip().strip("\"'").strip()
            continue
        break
    # v8.12: an INTERPRETER-LED command that happens to end in .html is a
    # RUN hint, not a preview - 'python gen.py out.html' GENERATES the
    # page; intercepting it as a document path made the shell never run,
    # the file was never written and every loop saw a phantom stop. Only
    # the FIRST token decides (a document may legitimately be called
    # 'node.js.html' - that stays a preview). The token is normalized
    # like _prerun_named_files does: paths ('./venv/bin/python') collapse
    # to their basename and Windows shells strip .exe/.cmd/.bat.
    head = cmd.partition(" ")[0].lower().strip("\"'")
    head = head.replace("\\", "/").rpartition("/")[2] or head
    for _sh_ext in (".exe", ".cmd", ".bat"):
        if head.endswith(_sh_ext):
            head = head[:-len(_sh_ext)]
            break
    if head in (_PRERUN_EXECUTORS | {"pip", "pip3", "npm", "npx", "yarn",
                                     "pnpm", "go", "cargo", "dotnet",
                                     "java", "ruby", "php", "perl"}) \
            or re.match(r"^python(?:3(?:\.\d+)?)?$", head) \
            or head.endswith((".py", ".pyw", ".js", ".mjs", ".cjs")):
        return None
    if not _PREVIEW_PATH_RE.match(cmd):
        return None
    rel = cmd.replace("\\", "/")
    # ABSOLUTE paths are handled directly: safe_join would strip the root
    # and treat them as workspace-relative (pointing at a wrong file).
    # They are accepted as-is (open-or-note, never a shell) - the suffix
    # regex above already limits them to .html/.htm documents.
    try:
        ap = Path(rel)
    except (OSError, ValueError):
        return None
    if ap.is_absolute():
        return ap
    try:
        return safe_join(ws, rel)
    except (ValueError, TypeError):
        return None

# ---- v7.7: 'the OS itself refused the command' failures ------------------
# Exit 126/127 (and the Windows 9009 / 'not recognized' forms) mean the
# COMMAND never ran - there is no code error for the model to fix. Feeding
# those to the auto-fix round only produced phantom 'fixes' that rewrote
# healthy files (see preview_target above).
_UNRUNNABLE_RE = re.compile(
    r"is not recognized as an internal or external command|"
    r"is not an internal or external command|"
    r"Access is denied|"
    r": not found\r?$|command not found|"
    r"cannot execute binary file|exec format error",
    re.IGNORECASE | re.MULTILINE)
# v8.11: a line that is clearly a PROGRAM's own crash report - a python
# traceback / a [Errno ..] OSError message - is evidence the command DID
# run. The old whole-output regex matched 'Access is denied' inside
# 'PermissionError: [Errno 13] Access is denied: ...' and the fix round
# was skipped for a real code error.
_TRACEBACK_LINE_RE = re.compile(
    r"\[errno \d+\]|\[winerror \d+\]|^traceback\b|^during handling"
    r"|^the above exception|^\s+file \"",
    re.IGNORECASE)


def error_signature(f):
    """v8.8: a NORMALIZED failure fingerprint for the loop guards. The
    exact output tail used to be compared byte-for-byte - a traceback whose
    line number shifted by one (or a timestamp inside the output) defeated
    the 'same error twice' stop, so the fix loops kept burning rounds on a
    fix that was not landing. Normalization: casefold, whitespace
    collapsed, and (v8.11, SELECTIVE) only the shifting LOCATION markers
    blanked - 'line 7' -> 'line N', file:line:col frames -> :N, hex
    addresses -> 0xN. Real numbers in messages stay (two DIFFERENT errors
    that differ only in their numbers are no longer merged). Compared
    ALONGSIDE the exact signature: either one repeating in the last few
    rounds stops the loop."""
    code = f.get("code")
    tail = str(f.get("output") or "")[-2000:].lower()
    # v8.11: SELECTIVE normalization. Blanking every digit merged two
    # REAL different errors ('expect 2 args, got 3' vs 'expect 3 args,
    # got 2') into one signature, so a healthy loop was declared 'the
    # SAME error came back'. Only the shifting LOCATION markers (line
    # numbers, file:col frames, hex addresses) collapse now - that was
    # the actual drift the v8.8 guard was built for.
    t = re.sub(r"(line|row|col|column|pos(?:ition)?)\s*\d+", r"\1 N", tail)
    t = re.sub(r":[ \t]*\d+(?::\d+)?", ":N", t)
    t = re.sub(r"\b0x[0-9a-f]+\b", "0xN", t)
    t = re.sub(r"\s+", " ", t).strip()
    return (code, t)


def is_unrunnable_failure(code, output):
    """True when the failure says 'the OS could not run this thing at all'
    (command not found / not executable / not a command) rather than 'the
    program ran and reported a problem'. Only real program failures go to
    the auto-fix loop."""
    if code in (126, 127, 9009):
        return True
    if code is None:
        return False
    # v8.11: line-scanned - only SHELL/OS-shaped lines count
    for line in str(output or "")[-800:].splitlines():
        if not line.strip() or _TRACEBACK_LINE_RE.search(line):
            continue
        if _UNRUNNABLE_RE.search(line):
            return True
    return False

def sanitize_parts(rel):
    rel = rel.strip().replace("\\", "/")
    rel = re.sub(r"^[A-Za-z]:", "", rel).lstrip("/")
    parts = []
    for p in rel.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise ValueError("path escapes the workspace: " + rel)
        p = re.sub(r"[<>:\"|?*]", "_", p).rstrip(" .")
        # control characters (NUL, newlines, escapes) in a file name are
        # never legitimate - a NUL would make open() raise mid-apply and
        # leave a half-applied batch behind
        p = re.sub(r"[\x00-\x1f\x7f]", "_", p)
        if p.split(".")[0].upper() in WIN_RESERVED:
            # v6.9 fix: the suffix landed AFTER the extension ('con.txt_'),
            # which is still the CON device - the reserved name is the
            # STEM, so the de-fanging underscore must go in front.
            p = "_" + p
        if p:
            parts.append(p)
    if not parts:
        raise ValueError("empty file path")
    return parts

def safe_join(ws, rel):
    """Join `rel` onto the workspace with traversal AND symlink-escape
    protection. The parts-based checks stop '../' and absolute paths; the
    resolve() containment check stops a pre-existing symlink INSIDE the
    workspace from redirecting a write/read outside it. Fail-closed: if the
    path cannot be resolved safely, it is refused."""
    p = ws.joinpath(*sanitize_parts(rel))
    try:
        resolved, ws_root = p.resolve(), Path(ws).resolve()
    except Exception as e:
        raise ValueError("cannot resolve the path safely: " + str(e))
    if resolved != ws_root and ws_root not in resolved.parents:
        raise ValueError("path escapes the workspace (symlink): " + rel)
    return p

def truncate(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.7), int(limit * 0.25)
    return text[:head] + "\n... [truncated] ...\n" + text[-tail:]

def _looks_like_server(cmd):
    """True for commands that run for ever (servers) - /verify and the auto
    loop must never chase them with fix rounds.
    v6.7: word-boundary matching. The old substring test flagged any
    command merely CONTAINING a hint ('vite' inside 'invite', a path
    with 'serve' in it) and abandoned healthy runs."""
    low = (cmd or "").lower()
    for h in SERVER_HINTS:
        rx = re.search(r"(?<![\w\-/])" + re.escape(h) + r"(?![\w\-])", low)
        if not rx:
            continue
        # v8.11: 'vite build' / 'vite bundle' / 'vite compile' exit on
        # their own - a one-shot verb right after the hint means a BUILD,
        # not a dev server (the bare 'vite' hint abandoned healthy builds
        # mid-task; /loop said 'server detected' and gave up)
        rest = low[rx.end():].lstrip()
        first = (rest.split(" ", 1)[0] if rest else "").rstrip(";|&")
        if first.startswith(("build", "bundle", "compile", "optim")):
            continue
        return True
    return False

def open_browser(url):
    try:
        if os.name == "nt":
            os.startfile(url)  # noqa: type checker
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# --------------------------------------------------------------- system prompt
BASE_SYSTEM = """You are Nova Code, the coding engine of Nova Assistant - an autonomous coding agent running locally on a modest machine. You build real, complete projects from scratch - websites, tools, games, scripts. You write every file yourself, run commands through the user, and debug errors until everything works. The user trusts this code in real projects: correctness always beats cleverness.

## How to output files (MOST IMPORTANT RULE)
Whenever you create or change code, output each file in EXACTLY this format:

=== FILE: relative/path.ext ===
<complete file content>
=== END ===

Example - the user asks: "a python script that prints hello"

=== FILE: hello.py ===
def main():
    print("hello")

if __name__ == "__main__":
    main()
=== END ===

Run: python3 hello.py

File rules:
- NEW files or FULL rewrites: output the COMPLETE file content - full imports, full logic, full closing tags. Never diffs, never "...", never "rest unchanged".
- For a SMALL change to an existing file, use the === EDIT: === format below instead - it is shorter and safer.
- One block per file. A multi-file project means SEVERAL blocks back to back (index.html AND css/style.css AND js/main.js - each with its own === FILE: ... === END ===). Output every file the task needs - one missing file breaks the whole project. Output ALL files in THIS one answer - never "I will add the rest in the next message". Never wrap the file content in markdown ``` fences - the block headers replace them.
- Paths are RELATIVE to the workspace root (index.html, css/style.css, js/main.js). Never invent files the task does not need; if a project file map is provided, reuse those files instead of creating duplicates.
- End every coding answer with the exact command to run or preview the result (Run: ... / Preview: ...).

## Editing existing files (small changes)
To change a few lines of an EXISTING file, do NOT rewrite the whole file - output:

=== EDIT: relative/path.ext ===
<<<<<<< SEARCH
<exact lines from the current file, copied character-for-character>
=======
<replacement lines>
>>>>>>> REPLACE
=== END ===

- SEARCH must match the current file content EXACTLY ONCE (same indentation). Repeat SEARCH/REPLACE pairs inside one block for several changes.
- Unsure of the exact current text? See the file first ([READ: path], or ask the user to /read it), then edit.

## Workflow
- New project or feature: state a short plan (2-5 sentences), then output the files.
- Big projects: build a small WORKING core first, say what is ready, offer the next step - never write so much that files get cut off.
- Small change: update only the files that change - prefer === EDIT: === blocks for them.
- On "continue": resume EXACTLY where your previous message stopped; never repeat files you already output completely.

## Quality bar
- Think before writing: trace the main flows AND the failure paths in your head first.
- Handle edge cases: empty input, missing files, failed loads, zero divisions. Programs fail with a clear message, never a raw crash.
- Fully offline by default: no CDN links for CSS/JS/fonts, no API keys, no invented URLs. Real PHOTOS on web pages are the one exception: write <img src="IMG:english description" alt="..."> and Nova finds and downloads them (see the design contract on web tasks). Never embed base64/data: URIs as photos; JS-built cards keep img:"IMG:..." in their data and render a real <img>.
- Websites: index.html at the root; css/style.css + js/main.js as the project grows; meta viewport; relative paths; semantic HTML; no lorem ipsum - real content and real UI text.

## Language rules
- Python: standard library first. Logic in functions, entry point under if __name__ == "__main__". Wrap file/network access in try/except with clear error messages. No hardcoded absolute paths.
- JavaScript: must never crash on user actions. Guard null/undefined before use, addEventListener for events, script at end of body or defer, never put raw user input into innerHTML.
- HTML + CSS: one css/style.css; responsive with flex/grid and viewport meta; readable contrast; light, smooth animations.
- SQL: put EVERY user value in a ? or %s parameter placeholder - never build queries by string concatenation. Name columns explicitly in INSERT; give tables PRIMARY KEY and correct types; close connections or use context managers.
- General: clear names, small functions, comment only the "why".

## Debugging
When given a command output or error traceback:
1. Name the root cause in one short sentence.
2. Output the fix: small changes as === EDIT: === blocks, bigger rewrites as complete === FILE: === blocks.
3. Give the exact command to re-run.
Fix the root cause, not the symptom. If information is missing, pick the most reasonable assumption, state it in one line, and continue.

## Style
- Compact answers, simple English, short sentences - even when code is long.
- If the user writes Persian (Farsi), reply in simple Farsi, but ALL code, file paths, identifiers and comments stay English."""

# v6.8: compact few-shot for LOCAL models - exact file-protocol examples.
# Small brains imitate examples far better than they follow prose; keeping
# it byte-stable across turns also keeps the KV/prompt cache warm.
LOCAL_FEWSHOT = """

## Worked examples (copy this output shape exactly)
Task: "create hello.py that prints hi"
Correct answer:
I'll create the file.
=== FILE: hello.py ===
print("hi")
=== END ===
Run: python hello.py

Task: "change the print to Hello in hello.py"
Correct answer (small change - EDIT, no rewrite):
=== EDIT: hello.py ===
<<<<<<< SEARCH
print("hi")
=======
print("Hello")
>>>>>>> REPLACE
=== END ===
Run: python hello.py

Task: "make a page with a stylesheet" (TWO files - each gets its OWN block)
Correct answer:
I'll create both files.
=== FILE: index.html ===
<!doctype html>
<html><head><link rel="stylesheet" href="css/style.css"></head>
<body><h1>Hi</h1></body></html>
=== END ===
=== FILE: css/style.css ===
body { font-family: sans-serif; }
=== END ===
Preview: index.html"""

# --------------------------------------------------------------- model tools
# Model-initiated tool calls. The model outputs ONE token line, the agent runs
# the tool and sends the result back as the next message. This registry is
# EXTENSIBLE: to give the model a new ability, add one entry here (regex with
# one capture group + run(sess, arg) -> follow-up text) - model_tool_section()
# automatically teaches the new token to the model. No prompt editing.
#   needs_ns True -> the token is hidden/ignored when nova_search.py is gone.
# All handlers MUST be fail-soft: on any problem return a short English error
# note the model can read and continue from, or None (agent reports failure).

def _action_search(sess, query):
    """[SEARCH: q] - quick trusted web research, digest sent back to the model."""
    if ns is None:
        return None
    print(c(C.Y, "[search] Nova asked for fresh information: " + query))
    try:
        digest, sources = ns.quick_research(query)
    except Exception as e:
        print(c(C.R, "[search] failed: " + str(e)))
        print(c(C.D, "  (no internet? ask Nova to answer from its own knowledge)"))
        return None
    if not (digest and sources):
        return None
    print(c(C.G, f"[search] read {len(sources)} trusted source(s) - sending them back..."))
    return (
        "Web research was done for you. Here are the results:\n\n"
        f"--- web research: \"{query}\" ---\n{digest}\n--- end of research ---\n\n"
        "Now answer the user's original request completely, using these results. "
        "If files are needed, output them with the === FILE: === format."
    )


def _action_read(sess, arg):
    """[READ: file] - show one workspace file to the model (read-only,
    escape-proof, size-capped, credential-guarded)."""
    arg = arg.strip().strip("'\"")
    if not arg:
        return None
    if is_secret_path(arg):
        return (f"Tool result for [READ: {arg}]: REFUSED - this file can hold "
                "credentials/secrets, so it is blocked from the context. Ask "
                "the user to paste the relevant lines instead, then continue.")
    if sess.ignore is not None and sess.ignore.matches(arg):
        return (f"Tool result for [READ: {arg}]: REFUSED - this path is in the "
                "project's .novaignore list, so it stays out of the agent's "
                "view. Continue your answer without it.")
    try:
        p = safe_join(sess.ws, arg)
    except ValueError as e:
        return (f"Tool result for [READ: {arg}]: REFUSED - {e}. "
                "Continue your answer without this file.")
    # v8.0: the FILE sandbox also gates READS - Nova's own .nova state
    # and host-side credential folders stay out of the model's context.
    if sandbox is not None:
        ok_s, why_s = sandbox.check_path(sess.ws, p, write=False)
        if not ok_s:
            return (f"Tool result for [READ: {arg}]: REFUSED - {why_s}. "
                    "Continue your answer without this file.")
    if not p.is_file():
        return (f"Tool result for [READ: {arg}]: the file does not exist in the "
                "workspace. Check the 'Current project files' list; if the file "
                "should exist, create it yourself with the === FILE: === format; "
                "then continue your answer.")
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return (f"Tool result for [READ: {arg}]: cannot read the file ({e}). "
                "Continue your answer without it.")
    content = truncate(raw, MAX_LOAD_CHARS)
    # note must depend on the RAW size: truncate() output is never longer
    # than the limit, so checking it instead would never show the warning
    note = ("" if len(raw) <= MAX_LOAD_CHARS else
            " (shortened to fit the context - for other parts ask the user to /load it)")
    return (f"Tool result for [READ: {arg}]{note}:\n"
            f"--- file: {arg} ---\n{content}\n--- end of file ---\n\n"
            "Use this exact current content for your answer, then continue.")


def _action_img(sess, arg):
    """[IMG: description] - Nova finds a real photo on the internet,
    downloads it into the workspace and hands the local path back so the
    model can reference it in the HTML it is about to write."""
    if imgsys is None or not imgsys.available():
        # v7.2 audit fix: the NOVA_NO_IMAGES=1 kill switch (and a missing
        # network layer) used to be ignored on this path - the model could
        # still fetch photos while images were switched off.
        return None
    arg = arg.strip().strip("'\"")
    if not arg:
        return None
    print(c(C.Y, "[img] Nova asked for a real photo: " + arg))
    try:
        rel, source, meta = imgsys.pick_and_save(arg, sess.ws)
    except Exception as e:
        print(c(C.R, "[img] failed: " + str(e)))
        return None
    if not rel:
        return (f"Tool result for [IMG: {arg}]: no real photo could be fetched "
                "(offline or no good match). Continue WITHOUT a photo: skip that "
                "image or use a styled gradient div instead. Do NOT invent URLs.")
    dims = ""
    if meta.get("w") and meta.get("h"):
        dims = f", {meta['w']}x{meta['h']}"
    print(c(C.G, f"[img] saved {rel} ({source})"))
    emit_event({"t": "note", "text": f"[img] '{arg[:60]}' <- {rel} ({source})"})
    return (f"Tool result for [IMG: {arg}]: a real photo was saved to {rel}"
            f" (source: {source}{dims}). Reference EXACTLY this relative path in "
            f'your HTML: <img src="{rel}" alt="...">. If you need more photos, '
            "use one [IMG: ...] token per subject. Now continue your answer with "
            "the files.")


MODEL_ACTIONS = [
    {
        "name": "SEARCH",
        "regex": SEARCH_TOKEN_RE,
        "arg_hint": "short english query",
        "mhelp": "fresh facts from trusted sites; never invent versions/URLs/APIs",
        "needs_ns": True,
        "run": _action_search,
    },
    {
        "name": "READ",
        "regex": READ_TOKEN_RE,
        "arg_hint": "relative/path.ext",
        "mhelp": "see a workspace file's current content before changing it",
        "needs_ns": False,
        "run": _action_read,
    },
    {
        "name": "IMG",
        "regex": IMG_TOKEN_RE,
        "arg_hint": "short english photo description",
        "mhelp": "find and download a real photo; the saved workspace path comes back - use it in <img src>",
        "needs_ns": True,
        "run": _action_img,
    },
]


def extract_run_hint(answer):
    """The 'Run: ...' / 'Preview: ...' hint the model ENDS a coding answer
    with. The LAST match outside === FILE: === / === EDIT: === bodies wins:
    a Makefile recipe like 'run: main.py' or a README line inside a file
    block must never hijack the command that actually gets executed.
    v7.7: SALVAGED (unclosed) edit bodies are excluded too - a 'run:' rule
    inside a truncated Makefile edit is not the turn's Run command."""
    if not answer:
        return None
    spans = [m.span() for m in FILE_RE.finditer(answer)]
    spans += [m.span() for m in EDIT_RE.finditer(answer)]
    spans += _edit_salvage_spans(answer)
    best = None
    for m in RUN_HINT_RE.finditer(answer):
        if any(s <= m.start() < e for s, e in spans):
            continue                      # inside a file/edit block
        best = m
    return best.group(1).strip() if best else None


def _edit_salvage_spans(text):
    """v7.7: char spans of the SALVAGED (unclosed) === EDIT: === bodies -
    the regions parse_edits recovers that the closed-block EDIT_RE never
    covers. extract_run_hint / find_model_action exclude these too, so a
    'run:' line or a tool token INSIDE a recovered body never hijacks the
    turn's real Run command / tool round."""
    if not text:
        return []
    spans = []
    file_spans = [m.span() for m in FILE_RE.finditer(text)]
    closed = [m.span() for m in EDIT_RE.finditer(text)]
    for m in _EDIT_OPEN_RE.finditer(text):
        hstart = _hdr_start(text, m)
        if any(s <= hstart < e for s, e in closed + file_spans):
            continue
        nxt_hdr = _EDIT_NEXT_HDR_RE.search(text, m.end())
        limit = nxt_hdr.start() if nxt_hdr else len(text)
        spans.append((hstart, _salvage_bound(text, m.end(), limit)))
    return spans


def find_model_action(answer):
    """The model's tool token ([SEARCH: q] / [READ: f] / [IMG: d]) ->
    (action, arg), or None. The system prompt teaches ONE token ALONE on
    its own line (last line), so only standalone lines count - a token
    merely mentioned in prose or example code must never trigger a real
    tool round. v7.2 audit fix: tokens INSIDE a === FILE:/EDIT: === body
    never fire either (a commented '[IMG: hero photo]' inside generated
    HTML used to burn a real tool round + download a stray photo). When
    more than one valid token exists, the FIRST in the text wins (registry
    order no longer beats text order). Tokens whose feature is unavailable
    (needs_ns without nova_search.py) are invisible - the registry decides."""
    if not answer or "[" not in answer:
        return None
    spans = [m.span() for m in FILE_RE.finditer(answer)]
    spans += [m.span() for m in EDIT_RE.finditer(answer)]
    spans += _edit_salvage_spans(answer)
    best = None                           # (position, action, arg)
    for act in MODEL_ACTIONS:
        if not tool_available(act):
            continue
        for m in act["regex"].finditer(answer):
            if any(s <= m.start() < e for s, e in spans):
                continue                  # inside a file/edit block
            line_start = answer.rfind("\n", 0, m.start()) + 1
            line_end = answer.find("\n", m.end())
            if line_end == -1:
                line_end = len(answer)
            line = answer[line_start:line_end].strip()
            if line != m.group(0).strip():
                # tolerate trailing punctuation only ('[READ: x].'), never
                # a token embedded in a sentence. v7.1.0: leading bullets
                # ('- [READ: x]' / '* [READ: x]') are tolerated too - small
                # models bullet their tool tokens despite the instruction.
                rest = line.replace(m.group(0).strip(), "", 1) \
                    .strip(" \t.,;:!").lstrip("-*• ").strip()
                if rest:
                    continue
            if best is None or m.start() < best[0]:
                best = (m.start(), act, (m.group(1) or "").strip())
    return (best[1], best[2]) if best else None


def _exec_model_action(sess, act, arg):
    """Run one model-initiated tool with user-visible status. A broken tool
    must never break the turn: exceptions become a None follow-up."""
    print(c(C.Y, f"\n[tool] Nova requested {act['name']}: {arg}"))
    try:
        return act["run"](sess, arg)
    except Exception as e:  # a broken tool must never break the turn
        print(c(C.R, "[tool] " + act["name"] + " failed: " + str(e)))
        return None


def model_tool_section():
    """AUTO-GENERATED tool briefing, injected into every system prompt.
    Generated from TOOLS + MODEL_ACTIONS at runtime, so it can never drift
    from the real tool set: add / remove / upgrade a tool and the model's
    view of its own abilities updates on the very next start."""
    lines = ["## Tools you can use (the agent runs them)",
             "When one helps, tell the user exactly what to type:"]
    for t in TOOLS:
        if t.get("model") and tool_available(t):
            lines.append("- " + t["usage"] + " - " + t["mhelp"])
    acts = [a for a in MODEL_ACTIONS if tool_available(a)]
    if acts:
        lines.append("Your tool tokens - output ONE token alone as the last line, "
                     "then stop; the agent runs it and sends the result back, then you "
                     "continue. You may chain a few rounds (one token per answer); "
                     "on error, just continue without it.")
        for a in acts:
            lines.append("- [" + a["name"] + ": " + a["arg_hint"] + "] - " + a["mhelp"])
    lines.append("For MULTI-STEP work: start the answer with a plan checklist -\n"
                 "=== PLAN ===\n1. [x] first step (already done)\n2. next step\n"
                 "3. [ ] another step\n=== END ===\n"
                 "Keep it short (max 6 items). When you continue work later, re-output "
                 "the whole block with updated [x] marks first - the user watches your "
                 "progress through it.")
    lines.append("Trust '--- web research:' and 'Learned knowledge' text over "
                 "your guesses.")
    return "\n".join(lines)

# --------------------------------------------------------------- file parsing
# v6.4 small-model hardening for the file protocol. Three real-world
# failure modes (all reported as "the file was created but the code was
# wrong / it could not run"):
#   1. the model wraps the block BODY in a markdown fence - the ``` lines
#      used to be written INTO the file, which then cannot run;
#   2. the model forgets the === END === marker (or the answer is cut) -
#      the whole block used to be silently dropped, NO file was written,
#      yet the 'Run:' suggestion still appeared and failed on a file that
#      does not exist;
#   3. the model puts its 'Run: ...' line INSIDE the body (belongs after
#      === END ===) - it used to end up in the file as bogus code.
_FENCE_LINE_RE = re.compile(r"^```[A-Za-z0-9_+#.\-]*[ \t]*$")
_FILE_OPEN_RE = re.compile(r"^[ \t]*===[ \t]*FILE:[ \t]*([^\n]+?)[ \t]*===[ \t]*\n?",
                            re.MULTILINE)
# a salvage block ends at the next ===...=== marker line or at the
# model's Run/Preview hint line - never swallow those into the file
_BLOCK_STOP_RE = re.compile(r"^[ \t]*===.*$|^[ \t]*(?:run|preview)[ \t]*:.*$",
                            re.MULTILINE | re.IGNORECASE)
# the run-hint line that slips INTO a file body: match the protocol
# casing (Run/Preview) ONLY, so a lowercase Makefile target like
# 'run: main.py' as the last line of a Makefile is never stripped
_BODY_RUN_LINE_RE = re.compile(r"^[ \t]*(?:Run|Preview)[ \t]*:[ \t]*(.+?)[ \t]*$")


def _strip_outer_fences(body):
    """Drop ONE markdown fence accidentally wrapped around a block body.
    Conservative on purpose: strip only when the first non-empty line is a
    fence opener AND the last non-empty line is a closing fence AND those
    are the only fence lines in the body (a README that legitimately starts
    and ends with its own fenced examples has 4+ fences and is untouched).
    A single opening fence with no closing one (truncated answer) is also
    dropped - a lone ``` line can never be valid file content."""
    lines = body.split("\n")
    idx = [i for i, ln in enumerate(lines) if _FENCE_LINE_RE.match(ln.strip())]
    if not idx:
        return body
    first_nz = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    last_nz = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()),
                   None)
    if first_nz is None or first_nz not in idx or first_nz == last_nz:
        return body
    if len(idx) == 1:
        # only an opening fence - the answer was cut mid-file
        return "\n".join(lines[first_nz + 1:]).rstrip("\n")
    if len(idx) != 2 or last_nz not in idx:
        return body                  # 3+ fences = real content, not a wrapper
    return "\n".join(lines[first_nz + 1:last_nz])


def _split_trailing_run_hint(body):
    """(body_without_it, hint) when the file body ends with a 'Run:' /
    'Preview:' line that slipped inside the block (protocol casing only).
    The hint belongs AFTER === END ===; in the body it is bogus code."""
    lines = body.rstrip("\n").split("\n")
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()),
                None)
    if last is not None and len(lines) > 1:
        m = _BODY_RUN_LINE_RE.match(lines[last])
        if m:
            body = "\n".join(lines[:last]).rstrip("\n")
            return body, m.group(1).strip()
    return body, None


def _salvage_unclosed_files(text, taken, files, run_hints):
    """Recover === FILE: === blocks whose === END === never came: body runs
    to the next === marker / Run-hint line / end of the answer. Appends to
    `files` (and run_hints); always loud on the console so the recovery is
    visible, never silent."""
    for m in _FILE_OPEN_RE.finditer(text):
        # v8.10.1 fix: the containment check needs the REAL '===' position.
        # _FILE_OPEN_RE's ^[ \t]* anchor starts at the LINE start, while the
        # FILE_RE spans in `taken` begin at '===' itself - an INDENTED
        # complete block used to fall outside every span, the salvage path
        # re-parsed it (duplicate file entry + a false '[fix] missing END'
        # warning). The EDIT path solved this exact problem with
        # _hdr_start(); the FILE salvage path now gets the same treatment.
        hdr = m.start() + m.group(0).index("===")
        if any(s <= hdr < e for s, e in taken):
            continue                      # a complete FILE_RE block
        stop = _BLOCK_STOP_RE.search(text, m.end())
        body = text[m.end():stop.start() if stop else len(text)]
        if not body.strip():
            continue                      # nothing to write
        body = _strip_outer_fences(body).rstrip("\n")
        if not body.strip():
            continue
        body, hint = _split_trailing_run_hint(body)
        if hint and run_hints is not None:
            run_hints.append(hint)
        files.append((m.group(1).strip(), body))
        # v7.1.0: mark the salvaged region as taken so the outside-fenced
        # scan in parse_files cannot re-report its content as unnamed blocks
        taken.append((m.start(), stop.start() if stop else len(text)))
        print(c(C.Y, "[fix] a === FILE: block was missing its === END === "
                     "marker - its content was recovered so the file is "
                     "written anyway"))


def _fenced_blocks(text):
    """Scan plain ``` fenced code blocks: a #// name comment in the first
    two lines names the file, anything else is an unnamed block (v6.4
    logic, extracted in v7.1.0 so the named-files path can reuse it)."""
    files, unnamed = [], []
    for m in FENCED_RE.finditer(text):
        body = m.group(1)
        lines = body.split("\n")
        name, name_idx = None, -1
        for i, ln in enumerate(lines[:2]):
            nm = NAME_COMMENT_RE.match(ln.strip())
            if nm:
                name, name_idx = nm.group(1), i
                break
        if name:
            rest = "\n".join(lines[name_idx + 1:])
            files.append((name.strip(), rest))
        elif body.strip():
            # v8.7: whitespace-only bodies are fence leftovers from fenced
            # === FILE: === blocks (the fence lines sit OUTSIDE the parsed
            # span). They used to survive as phantom "unnamed blocks" and
            # burn a whole repair round - or a bogus Save-as prompt.
            unnamed.append(body)
    return files, unnamed


def _outside_spans(text, taken):
    """The text NOT covered by any (start, end) span - the gaps between
    the parsed protocol blocks."""
    parts, pos = [], 0
    for start, end in sorted(taken):
        if start > pos:
            parts.append(text[pos:start])
        pos = max(pos, end)
    if pos < len(text):
        parts.append(text[pos:])
    return "\n".join(parts)


def parse_files(text, run_hints=None, _depth=0):
    """Return (files, unnamed_blocks). files = list of (relpath, content).
    v6.4: `run_hints` (optional list) collects 'Run:'/'Preview:' lines that
    slipped INSIDE file bodies, and unclosed blocks / wrapped fences are
    repaired instead of producing broken or missing files (see the
    v6.4 note above parse_files).
    v6.9: when one block forgot its === END === and the lazy body swallowed
    the NEXT complete block, the split is done here loudly (the first file
    gets its head, the swallowed block is re-parsed) - the old code wrote
    both contents into ONE file and silently dropped the second.
    v8.0: CRLF is normalized ONCE here exactly like parse_edits already
    did (v7.7.1) - a CRLF-emitting model used to write files with
    embedded \r\n and then broke every follow-up EDIT (its SEARCH, LF,
    no longer matched the file on disk)."""
    if "\r\n" in text:
        text = text.replace("\r\n", "\n")
    files, unnamed = [], []
    taken = []
    for m in FILE_RE.finditer(text):
        name, body = m.group(1).strip(), m.group(2)
        body = body[1:] if body.startswith("\n") else body
        inner = _FILE_OPEN_RE.search(body)
        if inner and _depth < 3:
            head = _strip_outer_fences(body[:inner.start()])
            head, hint = _split_trailing_run_hint(head)
            if hint and run_hints is not None:
                run_hints.append(hint)
            print(c(C.Y, "[fix] a === FILE: block was missing its === END === "
                         "marker before '%s' - the two blocks were split apart"
                         % (inner.group(1).strip() or "?")))
            if head.strip():
                files.append((name, head.rstrip("\n")))
            sub_files, sub_unnamed = parse_files(
                body[inner.start():], run_hints, _depth=_depth + 1)
            files.extend(sub_files)
            unnamed.extend(sub_unnamed)
            taken.append(m.span())
            continue
        body = _strip_outer_fences(body)
        body, hint = _split_trailing_run_hint(body)
        if hint and run_hints is not None:
            run_hints.append(hint)
        files.append((name, body))
        taken.append(m.span())
    _salvage_unclosed_files(text, taken, files, run_hints)
    if files:
        # v7.1.0: named blocks must not SILENTLY DROP plain fenced code
        # blocks in the same answer (small models name the first file and
        # fence the second - the second file then vanished without any
        # note and without the repair round). Scan only the regions
        # OUTSIDE the parsed spans: fences inside file bodies (README
        # examples, docs of the protocol itself) stay excluded.
        outside = _outside_spans(text, taken)
        if outside.strip():
            extra_files, extra_unnamed = _fenced_blocks(outside)
            files.extend(extra_files)
            unnamed.extend(extra_unnamed)
        return files, unnamed
    return _fenced_blocks(text)


def parse_edits(text):
    """Extract === EDIT: === partial-edit blocks.
    Returns [(relpath, [(search, replace), ...])]. Malformed hunks are NOT
    silently dropped: prepare_edits() reports them to the model/user.
    v7.7 REWRITE (left-to-right scan instead of one lazy EDIT_RE sweep):
      - an === EDIT: === block whose === END === never came (truncated
        answer / weak model) used to vanish SILENTLY - the raw SEARCH/
        REPLACE markers then sat in the chat as broken output while the
        edit the user asked for never happened. The unclosed block is now
        recovered like unclosed FILE blocks: its body ends at the next
        block header / Run-hint line / end of the answer.
      - WORSE, the lazy DOTALL body of an unclosed block swallowed the
        NEXT block's header AND its === END === (the same v6.9 FILE-protocol
        bug), so the following edit's hunks landed in the FIRST file -
        a guaranteed wrong-file corruption. The scan now never lets one
        block's body cross the next header line.
    The marker-count rule still refuses half-formed hunks either way."""
    # v7.7.1 (audit): normalize CRLF ONCE up front - an '=== END ===\r\n'
    # line made the end-regex miss, the closed block was misclassified as
    # unclosed and its salvage body swallowed the NEXT block (phantom
    # hunks -> the user's real edit refused by all-or-nothing)
    text = text.replace("\r\n", "\n")
    edits = []
    file_spans = [m.span() for m in FILE_RE.finditer(text)]
    end_re = re.compile(
        r"^[ \t]*(?:```[ \t]*)?===[ \t]*END(?:[ \t]+EDIT)?[ \t]*===[ \t]*(?:```[ \t]*)?$",
        re.MULTILINE)
    pos = 0
    while True:
        m = _EDIT_OPEN_RE.search(text, pos)
        if not m:
            break
        pos = m.end()
        hstart = _hdr_start(text, m)
        if any(s <= hstart < e for s, e in file_spans):
            # an EDIT block inside a FILE body is ambiguous model output:
            # not applied (its target text was never parsed as a file), but
            # never SILENT either (v7.7.1 audit) - the FILE body carries the
            # raw markers as content, so say so loudly
            print(c(C.Y, "[edit skipped] an === EDIT: block sits inside a "
                         "=== FILE: body - it was left as that file's content, "
                         "not applied as an edit"))
            continue
        name = m.group(1).strip()
        endm = end_re.search(text, m.end())
        nxt_hdr = _EDIT_NEXT_HDR_RE.search(text, m.end())
        limit = nxt_hdr.start() if nxt_hdr else len(text)
        if endm and endm.start() < limit:
            body = text[m.end():endm.start()]
            pos = endm.end()
            salvaged = False
        else:
            body_end = _salvage_bound(text, m.end(), limit)
            body = text[m.end():body_end]
            pos = body_end
            salvaged = True
        body = body[1:] if body.startswith("\n") else body
        body = body.replace("\r\n", "\n")   # LF everywhere, like file writes
        hunks = [(s, r) for s, r in EDIT_HUNK_RE.findall(body)]
        # both marker kinds must appear EXACTLY once per hunk: the lazy
        # regex could otherwise 'swallow' an eight-arrow >>>>>>> REPLACE by
        # shifting its arrows into the replacement text (v4.1 audit)
        n_open = len(EDIT_HUNK_OPEN_RE.findall(body))
        n_close = len(EDIT_HUNK_CLOSE_RE.findall(body))
        if n_open != len(hunks) or n_close != len(hunks):
            # a malformed or missing ======= / >>>>>>> REPLACE side - refuse
            # the whole block loudly instead of applying a half-understood edit
            hunks = []
        edits.append((name, hunks))
        if salvaged and hunks:
            print(c(C.Y, "[fix] an === EDIT: block was missing its === END === "
                         "marker - its hunks were recovered and will be applied"))
    return edits


def prepare_edits(sess, edits):
    """Validate edit blocks against the CURRENT workspace files.
    Returns (plans, problems):
      plans    = [(path, target, hunk_count, updated_text)] - ready to write
      problems = [(path, reason)] - the WHOLE block for that path is refused
    Rules that keep this safe:
    - all-or-nothing per file: one bad hunk leaves the file untouched;
    - SEARCH must match the current content EXACTLY ONCE (no ambiguity,
      no partial matches, no drift since the model last saw the file);
    - several EDIT blocks for the same file are merged (hunks apply in
      order, each seeing the result of the previous one);
    - files are capped in size to bound RAM on a 4 GB machine.
    v6.9: blocks are merged keyed by the RESOLVED path - two spellings of
    one file ('app.py' + './app.py') used to produce two plans for the
    same target, the second overwriting the first from the ORIGINAL disk
    content (the first edit silently reverted)."""
    merged = {}   # resolved target -> [hunks] (insertion order kept)
    order = []    # resolved targets
    display = {}  # resolved target -> first path string seen
    problems = []
    for path, hunks in edits:
        try:
            key = str(safe_join(sess.ws, path).resolve())
        except ValueError as e:
            problems.append((path, str(e)))
            continue
        if key not in merged:
            merged[key] = []
            order.append(key)
            display[key] = path
        merged[key].extend(hunks)
    plans = []
    for key in order:
        path = display[key]
        hunks = merged[key]
        if not hunks:
            problems.append((path, "no valid SEARCH/REPLACE hunks found - the exact format is: "
                                   "<<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE, "
                                   "closed by === END ==="))
            continue
        try:
            target = safe_join(sess.ws, path)
        except ValueError as e:
            problems.append((path, str(e)))
            continue
        # v8.0: the FILE sandbox gates the EDIT path too - an === EDIT:
        # .nova/profile.json === used to pass safe_join (the file exists
        # inside the workspace) and silently re-configure the agent.
        if sandbox is not None:
            ok_s, why_s = sandbox.check_path(sess.ws, target, write=True)
            if not ok_s:
                problems.append((path, why_s))
                continue
        if not target.is_file():
            problems.append((path, "file does not exist - create new files with === FILE: ==="))
            continue
        try:
            if target.stat().st_size > MAX_EDIT_FILE_CHARS:
                problems.append((path, "file is too large for the edit protocol "
                                       f"(cap {MAX_EDIT_FILE_CHARS} chars)"))
                continue
            original = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            problems.append((path, "cannot read the file: " + str(e)))
            continue
        cur, ok = original, True
        for i, (search, replace) in enumerate(hunks, 1):
            if not search:
                problems.append((path, f"hunk {i}: SEARCH is empty - copy the exact lines to replace"))
                ok = False
                break
            n = cur.count(search)
            if n == 0:
                # v6.8.3: ONE rstrip-tolerant retry - small models routinely
                # drift on trailing spaces / indentation; an ambiguous or
                # truly-absent SEARCH still refuses the hunk.
                span = diffview.flex_match(cur, search) if diffview is not None \
                    else None
                if span is not None:
                    cur = cur[:span[0]] + replace + cur[span[1]:]
                    continue
                problems.append((path, f"hunk {i}: SEARCH text not found in the current file - "
                                       f"copy it character-for-character (check with /read {path} "
                                       f"or [READ: {path}])"))
                ok = False
                break
            if n > 1:
                problems.append((path, f"hunk {i}: SEARCH text appears {n} times - add more "
                                       "surrounding lines so it matches exactly once"))
                ok = False
                break
            cur = cur.replace(search, replace, 1)
        if ok:
            plans.append((path, target, len(hunks), cur))
    return plans, problems

# --------------------------------------------------------------- project map
def build_map(ws):
    # v6.2.1 fix: the walk used to break as soon as MAP_MAX_FILES entries
    # were collected, so `total` could never exceed len(entries) and the
    # "... and N more files" hint was unreachable - the model saw a full
    # map with no indication that files were missing. Now the walk keeps
    # COUNTING after the cap (cheap: stat only, no reads) so the map ends
    # with an honest "... and N more files" line.
    entries, total = [], 0
    read_budget = 1_000_000   # bound the line-count reads on huge workspaces
    for root, dirs, names in os.walk(ws):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not d.startswith("."))
        for n in sorted(names):
            if n.startswith("."):
                continue
            p = Path(root) / n
            rel = p.relative_to(ws).as_posix()
            try:
                size = p.stat().st_size
            except OSError:
                continue
            total += 1
            if len(entries) >= MAP_MAX_FILES:
                continue   # keep counting, stop adding
            if size < 100_000 and read_budget > 0:
                try:
                    body = p.read_text(encoding="utf-8", errors="replace")
                    read_budget -= len(body)
                    entries.append(f"- {rel} ({body.count(chr(10)) + 1} lines)")
                except OSError:
                    entries.append(f"- {rel}")
            else:
                entries.append(f"- {rel} ({human_size(size)})")
    if not entries:
        return "(the workspace is empty)"
    extra = total - len(entries)
    text = "\n".join(entries)
    if extra > 0:
        text += f"\n- ... and {extra} more files (ask for a specific path before reusing it)"
    return text

# --------------------------------------------------------------- context budget
def _est_tokens(text):
    """Rough token estimate for a text - deliberately conservative
    (over-estimates a little so we always stay inside the real window)."""
    return int(len(text) / CTX_CHARS_PER_TOKEN) + 1


def _shrink_lines(text, max_lines, note):
    """Keep the first max_lines lines of a section, then a note line."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + "\n" + note


# --------------------------------------------------------------- session
class Session:
    def __init__(self, workspace):
        self.ws = workspace
        self.kb_path = workspace / KB_FILE   # learned knowledge base
        self.model = DEFAULT_MODEL
        self.mode = "code"
        self.run_timeout = DEFAULT_RUN_TIMEOUT
        self.history = []          # [{role, content}] sent to the API
        self.transcript = []       # [(role, text)] for /export
        self.loads = []            # [(name, content)] attached to next message
        self.last_cmd = None
        self.last_run_cmd = ""     # v7.7: last model/derived Run hint - keeps
                                   # the web Run chip alive across edit turns
        self.last_failed = None    # {"cmd","code","output"}
        self.last_batch = []       # [(target, backup)] from the last apply - for /undo
        self.serve_proc = None     # background preview server
        self.serve_port = None
        self.auto = False          # /auto - autonomous build-fix loop
        self.auto_yolo = AUTO_YOLO # skip per-command confirmations in auto mode
        self.touched = {}          # rel path -> "new" | "modified" (this session)
        self.last_composed = None  # last composed user text (for /retry)
        self.nova_md_text = ""     # project memory (NOVA.md) injection text
        self.map_text = ""
        # ---- v5.0 superstructure state ----
        self.ignore = npol.NovaIgnore.load(workspace) if npol else None
        self.policy = npol.load_policy(workspace) if npol else {}
        self.explain = False       # /explain - analyze but never write
        self.autotest = True       # run detected tests after each apply
        self.confirm_changes = False  # web: per-hunk approve before writing
        self.autofix = True           # v6.8.3: web failed Run -> one auto fix round
        self.fix_rounds = 0        # v8.8: consecutive auto-fix rounds fired
                                   # without a green run - the loop brake
        self.todo = []             # live plan checklist [{done, text}]
        self.last_request = ""     # last user request (commit messages, skills)
        self.last_feedback = None  # result of the post-apply quality gate
        self.bg_notified = int(time.time())  # bg completion notices cursor
        self.memory_on = True
        # v6.8: security extras - at-rest passphrase (None = plaintext),
        # per-command CPU/RAM caps, sandbox config (loaded per workspace)
        self.lock_pass = None
        self.limits = rlimits.env_limits() if rlimits else {"cpu_s": 0, "ram_mb": 0}
        # arm at-rest encryption process-wide when a passphrase is set
        # (env or later /lock) - BOTH faces (repl + web) honor it
        if secretbox is not None and nmem is not None:
            _pp = os.environ.get("NOVA_PASSPHRASE", "")
            if _pp and nmem.set_cipher(_pp):
                self.lock_pass = _pp
        # v6.6: the workspace carries the provider config (API keys, custom
        # providers, per-section routing, economy settings). Load it before
        # the profile applies, so a profiled provider can resolve its key.
        if providers is not None:
            try:
                providers.load_config(self.ws)
            except Exception:
                pass
        # v6.7 fix: configure() was never called in production - the
        # persistent log sink (<ws>/.nova/logs/nova.log) was dead code and
        # every fail-soft swallow left no post-restart trail.
        if nova_log is not None:
            try:
                nova_log.configure(self.ws)
            except Exception:
                pass
        # v8.0: the agent's black box - point the flight recorder at
        # this workspace and log the session boot decision.
        if flightlog is not None:
            try:
                flightlog.configure(self.ws)
                flightlog.log("session.boot", "agent session started",
                              version=VERSION, mode=self.mode,
                              model=self.model)
            except Exception:
                pass
        # v8.3: the context engine settings (.nova/context.json) - the
        # user's per-backend windows + auto-compression. Loaded before
        # anything that budgets tokens (fail-soft: {} = env defaults).
        self.ctx_settings = (ctxengine.load_settings(self.ws)
                             if ctxengine is not None else {})
        # v8.4: the code guardian settings (.nova/guardian.json) + the
        # one-shot repair context (set when the pre-apply gate rejects a
        # batch - the NEXT user message rides with the exact fix list).
        self.guardian_settings = (guardian.load_settings(self.ws)
                                  if guardian is not None else {})
        self.guardian_repair = None
        # v8.5: the bug hunter settings (.nova/probe.json) + the one-
        # shot wiring-repair context (the pre-apply gate refused a
        # batch - the NEXT user message rides with the exact fix list).
        self.probe_settings = (probe.load_settings(self.ws)
                               if probe is not None else {})
        self.probe_repair = None
        # v8.6: the vision settings (.nova/vision.json) - the approval
        # policy for internet photos (the local AI must approve).
        self.vision_settings = (vision.load_settings(self.ws)
                                if vision is not None else {})
        # the sess-less image hooks resolve the ACTIVE workspace/model
        # through this tracker (one workspace per process - the web
        # server and the CLI both boot exactly one Session).
        _VISION_ACTIVE["ws"] = self.ws
        _VISION_ACTIVE["model"] = self.model
        self._apply_profile()
        _VISION_ACTIVE["model"] = self.model
        self.rescan(silent=True)
        self._load_memory()

    # ---------- per-project profile (v5.0) ----------
    def _apply_profile(self):
        """Restore this workspace's saved defaults BEFORE anything else
        runs. Fail-soft: a broken profile just means stock defaults.
        v8.0: `mode` and `run_timeout` from an old/hand-edited profile
        are now VALIDATED exactly like _load_memory and /profile set do
        - an invalid value used to poison every later turn
        (MODE_HINTS[self.mode] KeyError in system_parts, TypeError in
        proc.wait(timeout=...))."""
        prof = nproj.load_profile(self.ws) if nproj else {}
        if not prof:
            return
        rt = prof.get("run_timeout", None)
        if rt is not None:
            try:
                v = int(rt)
                if 5 <= v <= 3600:
                    self.run_timeout = v
            except (TypeError, ValueError):
                pass
        if prof.get("mode") in MODES:
            self.mode = prof["mode"]
        if isinstance(prof.get("autotest"), bool):
            self.autotest = prof["autotest"]
        prov_name = prof.get("provider")
        if prov_name and providers is not None and _CLI_PROVIDER is None:
            try:
                cfg = providers.set_provider(prov_name, model=prof.get("model"))
                self.model = cfg["model"]
            except Exception as e:
                if nova_log is not None:
                    nova_log.soft("nova.profile.provider", e, msg=str(prov_name))
        elif prof.get("model"):
            self.model = prof["model"]

    def save_profile_field(self, field, value):
        """Persist one setting into the per-project profile (best effort).
        v8.6: every model switch lands here - keep the vision tracker
        honest so the approval layer asks the CURRENT brain.
        v8.7: a different brain also re-arms the local vision verdict
        (the cached text-only verdict belonged to the OLD model)."""
        if field == "model":
            _VISION_ACTIVE["model"] = value
            if _IMG_AI_STATE.get("local") is False:
                _IMG_AI_STATE["local"] = None
        if not nproj:
            return
        err = nproj.save_profile(self.ws, {field: value})
        if err:
            print(c(C.Y, "[!] could not save the project profile: " + err))

    # ---------- cross-run memory (v5.0) ----------
    def _load_memory(self):
        """Restore the previous terminal run's conversation, if any."""
        if not nmem or not self.memory_on:
            return
        try:
            history, transcript, meta = nmem.load_memory(self.ws)
        except ValueError as e:
            # v6.8: a sealed memory.json.enc with the wrong passphrase must
            # not crash boot - tell the user, start fresh, keep the file
            print(c(C.Y, "[lock] could not decrypt the saved conversation "
                         f"({e}) - set the same passphrase via /lock, or "
                         "/memory clear to drop it."))
            return
        if meta.get("locked"):
            print(c(C.Y, "[lock] the saved conversation is ENCRYPTED and no "
                         "passphrase is armed - set it with /lock <passphrase> "
                         "(or /memory clear to drop the sealed file)."))
        if not history and not transcript:
            return
        self.history = history
        self.transcript = transcript
        if meta.get("model") and self.model == DEFAULT_MODEL:
            self.model = meta["model"]
            # v8.7: a memory-restored model switch must keep the vision
            # tracker honest (the sess-less image hooks read it).
            _VISION_ACTIVE["model"] = self.model
        if meta.get("mode") in MODES:
            self.mode = meta["mode"]
        when = datetime.fromtimestamp(meta["ts"]).strftime("%Y-%m-%d %H:%M") \
            if meta.get("ts") else "earlier"
        print(c(C.G, f"[memory] restored the conversation from {when} "
                     f"({len(history)} messages) - /memory clear to forget"))

    def save_memory(self):
        if not nmem or not self.memory_on:
            return
        nmem.save_memory(self.ws, self.history, self.transcript,
                         extra={"model": self.model, "mode": self.mode})

    # ---------- workspace ----------
    def set_workspace(self, path):
        p = Path(path).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        # v6.5 fix: everything below belongs to the OLD workspace. Keeping
        # it made a legacy /undo after '/workspace B' restore workspace A's
        # file (and then crash halfway: relative_to raised an uncaught
        # ValueError), re-apply stale loads, /retry compose against stale
        # context and leak the preview server of the old project.
        self.last_batch = []
        self.touched = {}
        self.last_failed = None
        self.fix_rounds = 0       # v8.8: the new project starts with a full budget
        self.last_cmd = None
        self.last_run_cmd = ""    # v7.7: the old project's hint must not
                                   # open the NEW project's files
        self.loads = []
        self.last_feedback = None
        self.last_composed = None
        # v8.10.1 fix: the one-shot repair contexts are one-shot PER
        # PROJECT. A batch refused in project A used to arm these, and
        # the first message in project B silently carried A's per-file
        # fix list (paths that do not exist in B) - the same leak class
        # the v6.9 fix removed for history/feedback.
        self.guardian_repair = None
        self.probe_repair = None
        # v6.9 fix: the OLD project's conversation used to ride along - the
        # next turn sent it to the model against the NEW workspace (and
        # remember() then PERSISTED it into the new project's memory file).
        self.history = []
        self.transcript = []
        self.bg_notified = int(time.time())
        # v6.7 fix: the old project's live plan used to leak into the new
        # project's /status and auto-loop prompts.
        self.todo = []
        if self.serve_proc and self.serve_proc.poll() is None:
            try:
                stop_serve(self)
            except Exception:
                pass
        else:
            self.serve_proc = None
            self.serve_port = None
        self.ws = p
        self.kb_path = p / KB_FILE
        if npol is not None:
            self.policy = npol.load_policy(p)   # the NEW workspace's rules
        # v6.2.1 fix: apply the NEW workspace's saved profile (provider /
        # model / mode / run_timeout). Before, only __init__ applied it, so
        # switching projects silently kept the old project's brain and
        # settings until restart.
        if providers is not None:
            try:
                providers.load_config(p)   # v6.6: the NEW workspace's vault
            except Exception:
                pass
        if nova_log is not None:            # v6.7: re-point the file sink
            try:
                nova_log.configure(p)
            except Exception:
                pass
        self._apply_profile()
        # v6.7 fix: when the NEW workspace's profile does not pin a
        # provider, the old cloud brain used to stay active against the
        # NEW vault - if its key lived only in the old vault, requests
        # failed confusingly (or silently degraded to Ollama with a cloud
        # model name). Re-base on the local-first default in that case.
        _prof = nproj.load_profile(self.ws) if nproj else {}
        # v7.1.0: the v6.9 re-base now honors --provider like _apply_profile
        # does - without this guard, '/workspace otherdir' on a run started
        # with --provider groq silently reset the brain to Ollama while the
        # model name stayed groq (the next turn then 404'd).
        if providers is not None and _CLI_PROVIDER is None \
                and not (_prof or {}).get("provider"):
            try:
                providers.set_provider("ollama")
            except Exception:
                pass
        # v8.7: the per-workspace layers load at __init__ time - the
        # context engine, guardian, probe and vision settings belong to
        # the OLD project. /workspace B used to keep running against
        # project A's saved windows and gate switches until restart,
        # and the sess-less image hooks kept resolving project A (and
        # its model) through the _VISION_ACTIVE tracker.
        self.ctx_settings = (ctxengine.load_settings(self.ws)
                             if ctxengine is not None else {})
        self.guardian_settings = (guardian.load_settings(self.ws)
                                  if guardian is not None else {})
        self.probe_settings = (probe.load_settings(self.ws)
                               if probe is not None else {})
        self.vision_settings = (vision.load_settings(self.ws)
                                if vision is not None else {})
        _VISION_ACTIVE["ws"] = self.ws
        _VISION_ACTIVE["model"] = getattr(self, "model", None)
        print(c(C.G, "Workspace set: ") + str(p))
        self.rescan(silent=True)

    def rescan(self, silent=False):
        self.ignore = npol.NovaIgnore.load(self.ws) if npol else self.ignore
        if repomap is not None:
            self.map_text = repomap.build_style_map(
                self.ws, ignore=self.ignore, max_chars=repomap.MAX_MAP_CHARS)
        else:
            self.map_text = build_map(self.ws)
        self._load_nova_md()
        # v7.13: keep the project-intelligence scan honest - if the tree
        # changed under us, the next intel query rescans automatically.
        if intel is not None:
            try:
                intel.ProjectIntelligence(self.ws).refresh_if_stale()
            except Exception:
                pass
        if not silent:
            print(c(C.D, self.map_text))

    def _load_nova_md(self):
        """Read NOVA.md (project memory). Missing file = empty injection.
        A broken file must never break the session."""
        try:
            p = self.ws / NOVA_MD_FILE
            if p.is_file():
                self.nova_md_text = truncate(
                    p.read_text(encoding="utf-8", errors="replace"),
                    MAX_NOVA_MD_CHARS)
            else:
                self.nova_md_text = ""
        except OSError:
            self.nova_md_text = ""

    # ---------- prompts ----------
    def kb_text(self):
        """Saved web knowledge for this workspace (truncated for the prompt)."""
        if ns is None:
            return ""
        try:
            return ns.kb_text(self.kb_path)
        except Exception as e:
            if nova_log is not None:
                nova_log.soft("nova.kb_text", e)     # v6.3: visible in /log
            return ""

    def system_parts(self):
        """The system prompt in trimmable sections:
        (core rules + auto tool briefing [+auto hint] + mode hint,
        NOVA.md project-law section, file-map section, learned-knowledge
        section). The tool briefing is GENERATED from the tool registry, so
        the model always knows the current tools.
        v7.5 PROMPT PROFILES: the brain that will actually serve this turn
        decides the profile - local_small gets the condensed, example-heavy
        prompt with firm idiom patterns; cloud_frontier gets the rich full
        prompt with idioms demoted to OPTIONAL hints (never imposed on a
        strong model, never limiting its own style)."""
        ws_name = self.ws.name or str(self.ws)
        auto_hint = ("\n\nAUTO MODE IS ON: files you output are applied automatically "
                     "and your Run: command is executed. Always end a work answer with "
                     "exactly one 'Run: <command>' line."
                     if self.auto else "")
        explain_hint = ("\n\nEXPLAIN MODE IS ON: this is an ANALYSIS-ONLY turn. Do NOT "
                        "output === FILE: === or === EDIT: === blocks and do not propose "
                        "write commands - explain, review and advise only."
                        if self.explain else "")
        core = (BASE_SYSTEM + "\n\n" + model_tool_section() + auto_hint + explain_hint
                + "\n\n" + MODE_HINTS[self.mode])
        # v7.5: prompt profile + the idiom library in its backend-fitting voice
        profile = self.prompt_profile()
        if idioms is not None and not self.explain:
            idiom_block = idioms.suggest_text(
                getattr(self, "_turn_query", ""), profile=profile)
            if idiom_block:
                core += "\n\n" + idiom_block
        # v7.0: the design contract rides ONLY on web/UI turns (detected
        # from the user's own words in chat_turn) - ~200 tokens there,
        # zero for every other task. Inserted BEFORE the few-shot so the
        # example block stays the last thing the model reads.
        # v7.1.0: NOVA_NO_DESIGN=1 kills the contract too (the kill switch
        # used to silence only the post-apply polish).
        if getattr(self, "web_turn", False) and design is not None \
                and design.enabled():
            core += "\n\n" + design.DESIGN_CONTRACT
        # v6.8: compact worked example for LOCAL models - small brains
        # follow a 12-line example far better than prose rules. ~110
        # tokens, stable (same every turn -> KV/prompt cache stays warm).
        # v7.5: a cloud_frontier brain NEVER sees it - a frontier model
        # needs no protocol training wheels, and the extra examples can
        # rigidify a creative model.
        if profile == "local_small":
            core += LOCAL_FEWSHOT
        nova_sec = ""
        if self.nova_md_text:
            nova_sec = ("\n\n## Project notes (NOVA.md - the law of this project)\n"
                        "Follow these conventions, commands and structure even when "
                        "they differ from your defaults:\n" + self.nova_md_text)
        map_sec = ("\n\n## Current project files (workspace: " + ws_name + ")\n"
                   + self.map_text)
        kb = self.kb_text()
        kb_sec = ""
        if kb:
            kb_sec = ("\n\n## Learned knowledge (web research saved in this workspace)\n"
                      "This was collected from trusted sites with /learn. Use it when "
                      "relevant - it outranks your guesses:\n" + kb)
        skill_sec = skills.inject_text(self.ws) if skills else ""
        # v7.5: the user's coding style (all backends - personalization,
        # not weakness compensation) + semantic codebase hits for THIS query
        extra = skill_sec
        if style is not None and not self.explain:
            try:
                st = style.inject_text(self.ws)
                if st:
                    extra += "\n\n" + st
            except Exception:
                pass
        if rag is not None and not self.explain:
            try:
                q = getattr(self, "_turn_query", "")
                if q:
                    rc = rag.relevant_code_text(self.ws, q)
                    if rc:
                        extra += "\n\n" + rc
            except Exception:
                pass
        # v7.14: the THINK protocol - a brain without native reasoning is
        # asked to reason in the open (=== THINK === ... === END ===).
        # auto: only non-reasoners; on: everyone; off: nobody. The model
        # that will actually SERVE decides (turn-model override / route),
        # not just the session default.
        try:
            if think is not None and think.enabled():
                serve = getattr(self, "_think_model", "") or self.model
                if think.should_force(self.ws, serve):
                    core += "\n\n" + think.force_prompt("coding")
        except Exception:
            pass
        # v8.7 CRITICAL fix: kb_sec (the /learn learned knowledge) was
        # BUILT here but never returned - v7.5 replaced it with `extra`
        # in the tuple when style/skills/rag landed, so the learned
        # knowledge never reached the model again (silently) and the
        # build_messages trim ladder trimmed the wrong section.
        return core, nova_sec, map_sec, kb_sec, extra

    def system_prompt(self):
        core, nova_sec, map_sec, kb_sec, extra = self.system_parts()
        return core + nova_sec + map_sec + kb_sec + extra

    def _local_brain(self):
        """True when the brain that will actually serve the coding turn
        (the /brain coding route counts) is a LOCAL server."""
        cfg = _provider_cfg()
        try:
            if providers is not None:
                rcfg, _rm = providers.resolve_route("coding")
                if rcfg is not None:
                    cfg = rcfg
        except Exception:
            pass
        kind = str(cfg.get("kind", "ollama")).lower()
        return kind in ("ollama", "?", "lmstudio", "llamacpp", "vllm") \
            or _is_free_local(cfg)

    def prompt_profile(self):
        """v7.5: 'local_small' | 'cloud_frontier' - WHO serves this turn
        decides HOW the prompt looks. Weakness-compensation layers
        (few-shot examples, firm idioms) attach ONLY to local_small; a
        cloud frontier brain gets the full rich prompt, untouched."""
        try:
            if backend_policy is not None:
                return backend_policy.prompt_profile(
                    "local" if self._local_brain() else "cloud")
        except Exception:
            pass
        return "local_small" if self._local_brain() else "cloud_frontier"

    def compose(self, user_text):
        """Return the user text with pending attachments appended (does not clear)."""
        if not self.loads:
            return user_text
        attach = "\n".join(
            f"\n--- attached file: {name} ---\n{content}\n--- end of file ---"
            for name, content in self.loads
        )
        return user_text + "\n" + attach

    def remember(self, composed_user, answer, display_user=None):
        self.history.append({"role": "user", "content": composed_user})
        self.history.append({"role": "assistant", "content": answer})
        while len(self.history) > HISTORY_LIMIT:
            self.history.pop(0)
        if self.history and self.history[0]["role"] == "assistant":
            self.history.pop(0)
        self.transcript.append(("user", display_user if display_user is not None else composed_user))
        self.transcript.append(("nova", answer))
        # v6.3 RAM guard: the transcript used to grow unbounded during one
        # long session (the FILE copy is capped by nova_memory.MAX_TRANSCRIPT,
        # but the in-RAM list kept every turn). Keep the newest 400 entries.
        if len(self.transcript) > MAX_TRANSCRIPT_RAM:
            del self.transcript[:-MAX_TRANSCRIPT_RAM]
        self.save_memory()   # v5.0: the conversation survives restarts

    # ---------- v8.3 context engine ----------
    def _ctx_wins(self):
        """(local, cloud) effective windows for THIS session in tokens.
        User-saved settings (.nova/context.json, custom=True) are the
        law; otherwise the env-backed globals stay in charge."""
        cs = getattr(self, "ctx_settings", None) or {}
        local = NUM_CTX
        cloud = max(2048, _envint("NOVA_CLOUD_CTX", 16384))
        if ctxengine is not None and cs.get("custom"):
            if isinstance(cs.get("local_ctx"), int):
                local = cs["local_ctx"]
            if isinstance(cs.get("cloud_ctx"), int):
                cloud = cs["cloud_ctx"]
        return local, cloud

    def _effective_num_ctx(self):
        """The num_ctx actually sent to Ollama / llama-server for this
        session's LOCAL brain (Ollama would otherwise silently keep the
        model's own default - Nova's window setting must win)."""
        return self._ctx_wins()[0]

    def _ctx_used_tokens(self):
        """Estimated tokens the CURRENT history would occupy."""
        return sum(_est_tokens(m.get("content", "")) for m in self.history)

    def _maybe_ctx_compact(self):
        """v8.3: after a turn, fold the old block into a digest when the
        conversation grows past the compression threshold - BEFORE the
        next turn overflows the window and the brutal ladder has to cut
        blindly. Deterministic and offline: no model call, no credits,
        safe on weak hardware (the model-summarized /compact stays the
        manual deep option)."""
        if ctxengine is None or not self.history:
            return
        cs = getattr(self, "ctx_settings", None) or {}
        if not cs.get("auto_compact", True):
            return
        local, _cloud = self._ctx_wins()
        thr = cs.get("compact_threshold", 0.85)
        used = self._ctx_used_tokens()
        if used <= int(local * thr):
            return
        # target: land back under the threshold with headroom for one
        # more exchange (~CTX_RESERVE) - otherwise every turn re-folds.
        target = max(256, int(local * thr) - CTX_RESERVE)
        newh, stats = ctxengine.compress_history(
            self.history, target,
            keep_recent=cs.get("keep_recent", 4), cpt=CTX_CHARS_PER_TOKEN)
        if not stats.get("changed"):
            return
        self.history = newh
        while len(self.history) > HISTORY_LIMIT:
            self.history.pop(0)
        self.save_memory()
        msg = ("[context] engine: %d old messages folded (%s) - "
               "~%d -> ~%d tokens, newest %d kept verbatim"
               % (stats.get("old", 0), stats.get("mode", "?"),
                  stats.get("tokens_before", 0), stats.get("tokens_after", 0),
                  cs.get("keep_recent", 4)))
        print(c(C.Y, msg))

    def _prompt_ctx(self):
        """v6.6 economy: the prompt budget (tokens) for the ACTIVE brain.
        Local Ollama keeps NOVA_NUM_CTX (weak-hardware friendly). Cloud
        providers get a tighter default (NOVA_CLOUD_CTX, 16384) - shipping
        the whole file map + history to a pricey model burns credits for
        nothing, and most cloud windows are large enough that we would
        never fill them anyway. The trimmer then works exactly as before,
        just against the cheaper budget.

        v6.7: a /brain coding route changes WHO actually serves the
        coding turn - the prompt must fit THAT brain's budget, not the
        active one's (otherwise the routed brain can receive an
        over-window prompt).

        v8.3: both windows are now user-settable per workspace
        (.nova/context.json via /ctxset or the web Models tab) - the
        custom numbers override the env defaults and are kept SEPARATE
        for local and cloud brains on purpose: a 7B on a weak box and a
        frontier cloud model live in different window sizes."""
        cfg = _provider_cfg()
        if providers is not None:
            try:
                rcfg, _rm = providers.resolve_route("coding")
                if rcfg is not None:
                    cfg = rcfg
            except Exception:
                pass
        if cfg.get("kind") in ("ollama", "?", "lmstudio", "llamacpp",
                               "vllm") or _is_free_local(cfg):
            # v6.8.1 fix: LM Studio / llama.cpp / vLLM are LOCAL servers
            # with their own (often small) context windows - they must get
            # the local budget, not NOVA_CLOUD_CTX, or the trimmer never
            # fires and the server silently drops the oldest tokens.
            return self._ctx_wins()[0]
        return self._ctx_wins()[1]

    def build_messages(self, composed_user):
        """Messages for /api/chat, fitted into the context window.

        Why this matters: llama.cpp silently drops the OLDEST tokens when a
        prompt is bigger than num_ctx - on a 4096 window the system prompt
        (the file protocol itself!) would get cut off and answers fall
        apart. We trim ourselves instead, in a controlled order: oldest
        history, then the learned knowledge, then the file map, then the
        NOVA.md project notes. The core rules and the current user message
        are never touched.
        """
        win = self._prompt_ctx()
        budget = max(512, win - CTX_RESERVE)  # tokens available for the prompt

        core, nova_sec, map_sec, kb_sec, extra = self.system_parts()
        orig_map, orig_kb, orig_nova = map_sec, kb_sec, nova_sec
        orig_extra = extra
        history = list(self.history)

        # 0) v8.3 context engine: BEFORE the brutal trim ladder, fold the
        #    old block into a smart digest that keeps goals / file paths /
        #    commands / decisions and drops the chatter. The ladder below
        #    then only fires when even the digest cannot fit.
        if ctxengine is not None and history:
            cs = getattr(self, "ctx_settings", None) or {}
            if cs.get("auto_compact", True):
                hist_budget = max(256, budget - _est_tokens(
                    core + map_sec + kb_sec + extra + nova_sec
                    + composed_user))
                history, cstats = ctxengine.compress_history(
                    history, hist_budget,
                    keep_recent=cs.get("keep_recent", 4),
                    cpt=CTX_CHARS_PER_TOKEN)
                if cstats.get("changed"):
                    print(c(C.Y,
                            "[context] engine: %d old messages folded (%s) "
                            "to fit the %d-token window - newest %d verbatim"
                            % (cstats.get("old", 0), cstats.get("mode", "?"),
                               win, cs.get("keep_recent", 4))))

        def over(h):
            n = _est_tokens(core + map_sec + kb_sec + extra + nova_sec
                            + composed_user)
            return n + sum(_est_tokens(m.get("content", "")) for m in h) > budget

        # 1) drop the oldest history pairs (keep at least the last 2)
        while len(history) > 4 and over(history):
            history = history[2:]
        # 2) shorten the learned knowledge (v8.7: this used to trim
        #    `extra` - skills/style/rag - because of the kb_sec drop)
        if len(kb_sec) > 1200 and over(history):
            kb_sec = kb_sec[:1200] + "\n(knowledge shortened to fit the context window)"
        # 2b) v8.7: the injected extras (skills + style + rag) get the
        #     same shorten-then-drop treatment now that they are a
        #     separate section (they rode in the kb slot before).
        if len(extra) > 1200 and over(history):
            extra = extra[:1200] + "\n(context sections shortened to fit the window)"
        # 3) shorten the file map
        if over(history):
            map_sec = _shrink_lines(map_sec, 24,
                                    "(file map shortened to fit the context window)")
        # 4) last resort: keep only the most recent history pair
        while len(history) > 2 and over(history):
            history = history[2:]
        # 5) then drop the knowledge entirely
        if over(history):
            kb_sec = ""
        # 5b) v8.7: and only then the extras
        if over(history):
            extra = ""
        # 6) and reduce the map to its bare minimum
        if over(history):
            map_sec = _shrink_lines(map_sec, 10, "(file map shortened)")
        # 7) shrink NOVA.md project notes (never dropped: user-written law)
        if len(nova_sec) > 900 and over(history):
            nova_sec = nova_sec[:900] + "\n(project notes shortened to fit the context window)"
        if len(nova_sec) > 400 and over(history):
            nova_sec = nova_sec[:400] + "\n(project notes shortened)"
        # 7b) v6.8.1 fix: the final 2-message history floor could keep a
        # GIANT pair (a /load attachment or a pasted log is remembered in
        # full) - everything below then overflows the window and llama.cpp
        # silently drops the OLDEST tokens (the file protocol!). If the
        # remaining history itself cannot fit, it goes - the core rules
        # and the current message must survive.
        while history and over(history):
            history = history[:0] if len(history) <= 2 else history[2:]
        if not history and self.history:
            print(c(C.Y, "[context] the window is too small for ANY history - "
                         "sending the core rules + your message only"))
        # 8) final fallback: the CURRENT user message itself (a huge /load
        # batch or a pasted log) must also fit - llama.cpp would silently
        # drop the OLDEST tokens (the file protocol itself!) instead. Cut
        # it, keeping head and tail, so the window never overflows.
        # v6.2.1 fix: the old guard `200 < room` made this branch DEAD
        # exactly when the prompt was most over budget (small num_ctx or a
        # giant pasted log): room <= 200 meant "send it anyway" and the
        # window overflowed. Now we always trim when over budget, clamping
        # the target so the message degrades instead of overflowing.
        if over(history):
            used = sum(_est_tokens(m.get("content", "")) for m in history) \
                + _est_tokens(core + map_sec + kb_sec + extra + nova_sec)
            room = int((budget - used) * CTX_CHARS_PER_TOKEN)
            if room < len(composed_user):
                target = max(room, 400)   # keep a sane minimum slice
                print(c(C.Y, "[context] the message itself was too big - "
                             "trimmed to fit the window"))
                composed_user = truncate(composed_user, target)

        if (len(history) < len(self.history)
                or len(map_sec) < len(orig_map) or len(kb_sec) < len(orig_kb)
                or len(nova_sec) < len(orig_nova)
                or len(extra) < len(orig_extra)):
            print(c(C.Y, "[context] trimmed old history / knowledge / file map "
                         f"to fit the {win}-token window"))

        # v6.7: 'cache_split_at' marks the end of the STABLE system prefix
        # (core rules) for the Anthropic prompt cache - the dynamic file
        # map / knowledge / notes ride in a second, uncached block so they
        # cannot invalidate the cached prefix on every file change.
        msgs = [{"role": "system",
                 "content": core + nova_sec + map_sec + kb_sec + extra,
                 "cache_split_at": len(core)}]
        msgs += history
        msgs.append({"role": "user", "content": composed_user})
        return msgs

# --------------------------------------------------------------- chat
# (terminal + web + every provider meet here)
# v6.8.1: process-wide serialization for ALL model-stream writes - one
# terminal, one web stream, and /agent's parallel sub-agents all funnel
# through this lock (emit + heartbeat).
_STREAM_LOCK = threading.RLock()


def _is_free_local(cfg):
    """True when the endpoint is a LOCAL model server (free, never
    budget-gated): a known local kind, or any base URL on the loopback
    host. v6.7: the old `not key_optional` check both budget-gated the
    free local llama.cpp server (its cfg carries no key_optional) AND let
    PAID relays through unchecked (custom providers are key_optional by
    design) - exactly the runaway-loop case the gate exists for."""
    kind = str(cfg.get("kind", "")).lower()
    if kind in ("ollama", "?", "lmstudio", "llamacpp", "vllm"):
        return True
    try:
        host = (urllib.parse.urlparse(str(cfg.get("base") or ""))
                .hostname or "").lower()
    except Exception:
        host = ""
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


# v7.8: a cloud stream that died with one of these BEFORE the first token
# gets ONE calm retry - a rate limit (429) or a datacenter blip (5xx /
# dropped connection) usually clears in seconds, and the alternative is
# the user re-sending the whole turn (a FULL second request).
_TRANSIENT_RE = re.compile(r"^HTTP (429|500|501|502|503|504|529)\b")


def _transient_provider_error(msg):
    """True for retry-worthy provider failures (HTTP 429/5xx, dead
    connection; v7.9 adds 501 so the whole 5xx family matches the
    documented promise). Auth/model errors (401/403/404...) are
    permanent - retrying those would only waste time, never fix anything."""
    m = str(msg or "").strip()
    return bool(_TRANSIENT_RE.match(m)) \
        or m.startswith("cannot reach the provider endpoint")


def _cacheable_section(section, eco):
    """v7.8: which sections may be served from the response cache.
    utility was always cached (pure functions of their prompt); talk
    joins when cache_talk is on - the cache key contains the FULL
    history, so only an exact resend of the same conversation state
    hits it (the accidental double-tap / resend-after-error case),
    never a 'give me another answer' repeat with different context."""
    if section == "utility":
        return True
    if section == "talk":
        try:
            return bool((eco or {}).get("cache_talk", True))
        except Exception:
            return True
    return False


def _provider_cfg():
    """Active provider config, fail-soft: a missing module or a missing
    API key must never crash a display path (/status, /disk) or the web."""
    if providers is None:
        return {"name": "ollama", "kind": "ollama", "label": "Ollama (local)",
                "model": DEFAULT_MODEL}
    try:
        return providers.current()
    except Exception:
        try:
            name = providers.current_name()
        except Exception:
            name = "ollama"
        return {"name": name, "kind": "?",
                "label": "unresolved - see /provider", "model": DEFAULT_MODEL}


def _eff_ctx(sess):
    """The session's effective LOCAL context window (v8.11 helper). The
    sess-less model calls (speculative draft, explore candidates,
    guardian/probe reviewers) used to fall back to the NUM_CTX env
    default and silently ignore the user's /ctxset window."""
    try:
        return sess._effective_num_ctx()
    except Exception:
        return NUM_CTX


def stream_chat(model, messages, temperature, sess=None, section=None,
                quiet=False, num_ctx=None):
    """Stream an answer from the ACTIVE provider. Returns (text, complete).

    Slow-hardware policy: the socket timeout (SOCK_TIMEOUT, default 1800 s)
    only caps the SILENCE between two chunks - never the total answer time.
    A heartbeat line shows elapsed seconds while the model thinks.
    The brain is any local Ollama model (auto-discovered at startup)
    or any API provider from nova_providers.py (/provider to switch).
    With `sess` the turn is also recorded into the token/cost ledger
    (real usage counts where the provider reports them, a conservative
    character estimate everywhere else).

    v6.6 `section`: coding | talk | utility | council. A section with a
    routing entry (.nova/providers.json, /brain) runs on ITS OWN
    provider+model; the economy layer adds a response cache (utility),
    a pre-request budget check and a per-section output cap - the
    "way fewer tokens, credits and requests" diet.

    v7.5 `quiet`: TRUE for the machine-only callers (speculative draft,
    /explore parallel candidates): nothing is written to the terminal or
    the web stream - the text is collected and returned only. Errors are
    silent too (the empty answer tells the caller enough)."""
    cfg = _provider_cfg()
    # v8.2: reset the hard-error flag for THIS call - chat_turn reads it
    # right after the return to decide whether an auto-continue is worth
    # anything (an Ollama 'model requires more memory' is not).
    global _LAST_STREAM_HARD, _LAST_STREAM_INTERRUPT
    _LAST_STREAM_HARD = False
    _LAST_STREAM_INTERRUPT = False
    ollama_mode = cfg.get("kind", "ollama") in ("ollama", "?")
    brain_model = model
    routed = False
    # ---- v6.6: per-section brain routing (coding / talk / utility / council)
    # v6.7: "coding" is routed too now - the route was stored, displayed
    # (/brain, web panel) and advertised in the help, but the guard below
    # excluded it, so a saved coding route silently never executed.
    if providers is not None and section:
        try:
            rcfg, rmodel = providers.resolve_route(section)
        except Exception as e:
            rcfg, rmodel = None, ""
            if isinstance(e, providers.ProviderError):
                print(c(C.Y, f"\n[brain:{section}] route not usable ({e}) - "
                             "using the active brain"))
        if rcfg is not None:
            cfg = rcfg
            brain_model = rmodel or providers.default_model(cfg) or brain_model
            ollama_mode = cfg.get("kind") == "ollama"
            routed = True
    # ---- v5.2: a 'file:<name>' model is a local .gguf FILE. Make it
    # runnable right here (before the heartbeat starts, so the one-time
    # import / llama-server spawn prints readable progress), then route
    # the chat through Ollama - or through the llama.cpp OpenAI API.
    # (A routed section brain never triggers the file import path - the
    # session's own model choice must not hijack another section.)
    if not routed and lmodels is not None and isinstance(model, str) \
            and model.startswith(lmodels.LOCAL_PREFIX):
        lmode, lval = ensure_local_model(sess)
        if lmode is None:
            msg = "[local model] " + str(lval)
            print(c(C.R, "\n" + msg))
            if TOKEN_SINK is not None:
                TOKEN_SINK(msg + "\n")     # the web face must see it too
            return "", False
        if lmode == "ollama":
            brain_model = lval            # the imported library name
        else:
            ollama_mode = False
            cfg = lval                    # llama.cpp (OpenAI-compatible)
    # ---- v6.6 economy: response cache + budget, BEFORE any request ----
    mt_cap = 0
    if providers is not None:
        try:
            mt_cap = providers.max_tokens_for(section or "coding")
        except Exception:
            mt_cap = 0
    cache_key = None
    if econ is not None and providers is not None and providers.cache_enabled() \
            and _cacheable_section(section, providers.economy()):
        try:
            cache_key = econ.cache_key(cfg.get("name", ""), brain_model,
                                       messages, temperature)
        except Exception:
            cache_key = None
        if cache_key and sess is not None:
            try:
                hit = econ.cache_get(sess.ws, cache_key,
                                     ttl=providers.economy().get("cache_ttl",
                                                                 econ.DEFAULT_TTL))
            except Exception:
                hit = None
            if hit is not None:
                # THE cheapest request: zero tokens, zero credits, zero
                # round-trips. Show it exactly like a streamed answer.
                if TOKEN_SINK is not None:
                    TOKEN_SINK(hit)
                else:
                    sys.stdout.write(hit)
                    sys.stdout.flush()
                try:
                    est = sum(int(len(str(m.get("content", ""))) / 3.2) + 1
                              for m in messages if isinstance(m, dict)) \
                        + int(len(hit) / 3.2) + 1
                    econ.bump(sess.ws, "cache_hits")
                    econ.bump(sess.ws, "requests_saved")
                    econ.bump_tokens_saved(sess.ws, max(0, int(est)))
                except Exception:
                    pass
                return hit, True
    if (not ollama_mode) and econ is not None and sess is not None \
            and cfg.get("name") and not _is_free_local(cfg):
        # billable endpoints only - local servers (LM Studio / llama.cpp /
        # vLLM / Ollama, including local custom providers) are free and
        # never hit a budget gate; everything else does (v6.7)
        try:
            reason = econ.budget_block(sess.ws, cfg.get("name", ""))
        except Exception:
            reason = None
        if reason:
            try:
                econ.bump(sess.ws, "blocked")
            except Exception:
                pass
            if not quiet:
                print(c(C.R, "\n[budget] " + reason))
                if TOKEN_SINK is not None:
                    TOKEN_SINK("\n[budget] " + reason + "\n")
            return "", False
    req = None
    if ollama_mode:
        payload = {
            "model": brain_model, "messages": messages, "stream": True,
            "keep_alive": KEEP_ALIVE,  # stay in RAM: no slow reload after a pause
            "options": {"temperature": temperature, "top_p": 0.9, "top_k": 40,
                        "repeat_penalty": 1.05,
                        # v8.3: the session's LOCAL window setting - Nova's
                        # law overrides whatever default Ollama picked for
                        # the model (bigger or smaller). No session (bench,
                        # probes) keeps the global default. v8.11: a caller
                        # may pass the session's window explicitly
                        # (num_ctx=...) while still keeping streaming quiet.
                        "num_ctx": (num_ctx or _eff_ctx(sess)),
                        # v6.6: the economy cap applies to talk/utility only;
                        # coding stays uncapped (num_predict -1) by default
                        "num_predict": mt_cap if mt_cap else -1},
        }
        req = urllib.request.Request(
            OLLAMA_URL + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    chunks = []
    complete = False
    # v8.2: a HARD stream error (Ollama reported an error mid-stream) must
    # not be followed by an auto-continue round - the model itself said it
    # cannot continue (OOM, missing model...); retrying would just burn
    # minutes on slow hardware. The signal rides in _LAST_STREAM_HARD.
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}

    # ---- heartbeat: proves the agent is alive during long waits ------------
    stop_evt = threading.Event()
    got_first = threading.Event()
    # v6.8.1: ONE process-wide stream lock - parallel sub-agents (/agent)
    # each run stream_chat; without a shared lock their heartbeat lines and
    # token writes interleave on the same terminal/stream.
    wait_lock = _STREAM_LOCK
    t0 = time.time()
    WAIT_W = 96  # fixed-width line so \r erases it cleanly

    def heartbeat():
        if quiet or not sys.stdout.isatty():
            return  # piped/quiet output: never pollute it with timer lines
        if _PARALLEL_DEPTH:
            return  # v6.9: parallel /agent streams share this terminal
        while not stop_evt.wait(15):
            el = int(time.time() - t0)
            line = ("\r[waiting] {:5d}s elapsed - first tokens can take minutes "
                    "on weak hardware (Ctrl+C = stop)").format(el)
            with wait_lock:
                if got_first.is_set():
                    continue
                sys.stdout.write(line[:WAIT_W].ljust(WAIT_W))
                sys.stdout.flush()

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()

    def note(kind, msg):
        """User-visible problem line - suppressed in quiet mode."""
        if not quiet:
            print(c(kind, msg))

    def clear_wait():
        if not sys.stdout.isatty():
            return
        with wait_lock:
            sys.stdout.write("\r" + " " * WAIT_W + "\r")
            sys.stdout.flush()

    def emit(piece):
        """One funnel for EVERY protocol: collects the text and routes it
        to the terminal - or to the web TOKEN_SINK when web mode is live.
        v6.8.1: the write is serialized process-wide (parallel /agent
        sub-agents share one stdout / one web stream).
        v7.5: quiet mode collects ONLY (drafts / explore candidates must
        never leak into the visible stream)."""
        if not got_first.is_set():
            got_first.set()
            if not quiet:
                clear_wait()
        chunks.append(piece)
        if quiet:
            return
        with _STREAM_LOCK:
            if TOKEN_SINK is not None:
                TOKEN_SINK(piece)
            else:
                sys.stdout.write(piece)
                sys.stdout.flush()

    try:
        if ollama_mode:
            with urllib.request.urlopen(req, timeout=SOCK_TIMEOUT) as resp:
                for raw in resp:
                    try:
                        data = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if "error" in data:
                        note(C.R, "\n[ollama error] " + str(data["error"]))
                        _LAST_STREAM_HARD = True
                        break
                    piece = (data.get("message") or {}).get("content", "")
                    if piece:
                        emit(piece)
                    if data.get("done"):
                        # v8.2: Ollama reports WHY the generation stopped.
                        # done_reason "length" = the context window or the
                        # output cap cut the answer MID-STREAM. The old code
                        # marked any done as complete, so a truncated
                        # mid-file answer looked finished: no warning, no
                        # continuation, half a site on disk. "length" is
                        # honest: the answer is NOT complete.
                        _dr = str(data.get("done_reason") or "stop").lower()
                        if _dr == "length":
                            complete = False
                            note(C.Y,
                                 "\n[!] the model stopped at its context/output "
                                 "limit (done_reason=length) - the answer was "
                                 "cut and Nova will continue it automatically.")
                        else:
                            complete = True
                        # real usage counts - free, straight from Ollama
                        usage = {"prompt_tokens": int(data.get("prompt_eval_count") or 0),
                                 "completion_tokens": int(data.get("eval_count") or 0),
                                 "actual": True}
                        # v6.8: context-caching observability - when the
                        # KV cache was warm, Ollama only re-evaluates the
                        # NEW tail of the prompt (prompt_eval_count << the
                        # tokens we actually sent). Log the reuse rate.
                        try:
                            est = sum(_est_tokens(m.get("content", ""))
                                      for m in messages)
                            pev = usage["prompt_tokens"]
                            # v6.8.1: 0.4 (was 0.6) - _est_tokens is
                            # deliberately pessimistic (2.7 chars/token);
                            # dense code can exceed 4.5 real chars/token,
                            # which made a COLD cache log as "warm".
                            if est > 256 and 0 < pev < est * 0.4 \
                                    and nova_log is not None:
                                nova_log.info(
                                    "nova.kv_cache_warm",
                                    msg=f"prompt re-eval {pev}/{est} tokens "
                                        f"({int(100 - 100 * pev / est)}% cached)")
                        except Exception:
                            pass
                        break
        else:
            # v7.8: ONE calm retry for transient cloud failures (429/5xx/
            # dropped connection) - but ONLY when nothing was streamed yet
            # (a mid-answer death is retried by the user typing continue,
            # a blind retry would duplicate the partial text).
            _attempt = 0
            while True:
                try:
                    for piece in providers.stream_chunks(
                            cfg, brain_model, messages, temperature,
                            timeout=SOCK_TIMEOUT, max_tokens=mt_cap,
                            usage=usage):
                        emit(piece)
                    complete = True
                    # v8.2: a cloud provider that hit its output cap reports
                    # finish_reason length / max_tokens / MAX_TOKENS on the
                    # final chunk - the same honest 'the answer was cut'
                    # signal the Ollama path now reads. stream_chunks reset
                    # the flag at entry, so it describes THIS call only.
                    if str(getattr(providers, "LAST_FINISH_REASON", "")
                           or "") == "length":
                        complete = False
                        note(C.Y, "\n[!] the provider cut the answer at its "
                                  "output limit - Nova will continue it "
                                  "automatically.")
                    break
                except Exception as e:
                    if providers is not None \
                            and isinstance(e, providers.ProviderError) \
                            and _attempt < 1 and not chunks \
                            and _transient_provider_error(str(e)):
                        _attempt += 1
                        # v7.9: note() prints - a broken/closed stdout must
                        # not escape HERE, or the retry dies AND the cost
                        # ledger + cache_put tail after the try block is
                        # skipped (the turn then vanished from the books).
                        try:
                            note(C.Y, "\n[retry] " + str(e)[:140]
                                          + " - one more try in 3s")
                        except Exception:
                            pass
                        time.sleep(3.0)
                        continue
                    raise
    except KeyboardInterrupt:
        _LAST_STREAM_INTERRUPT = True
        note(C.Y, "\n[interrupted] partial answer kept - type:  continue  to go on")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        msg = f"HTTP {e.code}"
        try:
            j = json.loads(detail)
            msg += ": " + str(j.get("error", detail))[:300]
        except Exception:
            if detail:
                msg += ": " + detail[:300]
        note(C.R, "\n[" + ("ollama" if ollama_mode else "provider") + "] " + msg)
        if ollama_mode:
            note(C.D, "  (not installed? see what you have:  /model   |   pull one:  ollama pull " + brain_model + ")")
        else:
            note(C.D, "  (check the key / model name - see:  /provider)")
    except socket.timeout:
        note(C.R, f"\n[slow] no data for {SOCK_TIMEOUT}s - gave up (raise it: NOVA_TIMEOUT=<sec>).")
        note(C.D, "  The partial answer is kept - type:  continue  to ask for the rest.")
    except urllib.error.URLError as e:
        note(C.R, "\n[connection lost] " + str(e))
        if ollama_mode:
            note(C.D, "  Is Ollama running? Start it with:  ollama serve")
        else:
            note(C.D, "  Cannot reach the API endpoint - check internet and /provider settings.")
    except OSError as e:
        note(C.R, "\n[connection lost] " + str(e))
    except Exception as e:
        if providers is not None and isinstance(e, providers.ProviderError):
            note(C.R, "\n[provider] " + str(e))
            note(C.D, "  Fix the key / model name - or go back to the local brain:  /provider ollama")
        else:
            note(C.R, "\n[error] " + type(e).__name__ + ": " + str(e))
    finally:
        stop_evt.set()
        hb.join(timeout=1)
        if not got_first.is_set() and not quiet:
            clear_wait()
    # ---- cost ledger (v5.0): every turn is accounted for ---------------
    if sess is not None and nova_cost is not None:
        try:
            dur = time.time() - t0
            cfg_name = cfg.get("name", "ollama")
            if not usage["actual"]:
                # estimate: prompt = everything we sent, answer = what came back
                usage = {"prompt_tokens": sum(_est_tokens(m.get("content", ""))
                                              for m in messages),
                         "completion_tokens": _est_tokens("".join(chunks)),
                         "actual": False}
            nova_cost.record(sess.ws, cfg_name, brain_model,
                             usage["prompt_tokens"], usage["completion_tokens"],
                             actual=usage["actual"], dur_s=dur,
                             ok=bool("".join(chunks).strip()))
        except Exception:
            pass
    # ---- v6.6 economy: keep the utility answer for identical requests --
    if cache_key is not None and complete and chunks and sess is not None \
            and econ is not None:
        try:
            if providers is not None:
                eco = providers.economy()
            else:
                eco = {}
            econ.cache_put(sess.ws, cache_key, "".join(chunks),
                           ttl=eco.get("cache_ttl", econ.DEFAULT_TTL),
                           max_entries=eco.get("cache_max",
                                               econ.DEFAULT_MAX_ENTRIES))
        except Exception:
            pass
    return "".join(chunks), complete

CONTINUE_WORDS = {"continue", "cont", "c", "go on"}


# v8.2: the cut-answer rescue needs to know whether the LAST stream_chat
# died with a HARD error (Ollama reported 'model requires more memory',
# an auth failure...) - continuing such a stream is pointless. Reset at
# every stream_chat entry; the synchronous caller reads it right after.
_LAST_STREAM_HARD = False
# v8.7: the user pressed Ctrl+C mid-stream - an explicit STOP. The
# auto-continue rescue must not override it (it used to re-issue the
# request, so the printed "type: continue to go on" was a lie).
_LAST_STREAM_INTERRUPT = False


RESUME_TAIL_CHARS = _envint("NOVA_RESUME_TAIL", 1400)


def _resume_tail(raw, cap=None):
    """The last `cap` chars of a cut answer - enough for the model to see
    EXACTLY where its own text stopped (usually mid-file), never enough
    to overflow a small context window on top of the standing prompt."""
    cap = cap or RESUME_TAIL_CHARS
    t = str(raw or "").rstrip()
    if len(t) <= cap:
        return t
    return t[-cap:]


def _resume_message(raw, request=""):
    """The user-side message of an auto-continue round: a compact anchor
    (the original request, capped) + the precise resume instruction +
    the raw tail LAST. The order matters: build_messages' context budget
    may trim this message on a small window (truncate keeps head+tail),
    and the tail - the exact point where the model stopped - is the one
    part that must always survive the cut."""
    req = str(request or "").strip()
    if len(req) > 300:
        req = req[:300] + "..."
    head = ("You were asked: " + req + "\n\n") if req else ""
    return (
        head
        + "Your previous answer was cut off mid-generation (the model stream "
          "stopped before you finished). Continue EXACTLY where it stopped - "
          "do NOT repeat anything you already wrote, do not start over, do "
          "not re-explain. If you were inside a === FILE: block, continue "
          "that file's content from the exact cut point, then close it with "
          "=== END ===. Then output every remaining file the task still "
          "needs (each with its own === FILE: path === / === END === block) "
          "and finish with the Run or Preview line.\n"
        + "Its final lines were (everything from here on is where your own "
          "text stopped):\n-----\n" + _resume_tail(raw))


def _is_continue_word(text):
    """True for bare 'continue' style replies after a cut-off answer."""
    return text.strip().lower().rstrip(".! ") in CONTINUE_WORDS


def _coding_brain_is_local():
    """True when the brain that serves coding turns is local - the
    auto-retry must NEVER silently spend cloud credits."""
    try:
        cfg = _provider_cfg()
        if providers is not None:
            rcfg, _rm = providers.resolve_route("coding")
            if rcfg is not None:
                cfg = rcfg
        kind = str(cfg.get("kind", "ollama")).lower()
        return kind in ("ollama", "?", "lmstudio", "llamacpp", "vllm")
    except Exception:
        return False


def _fallback_local_model(sess, exclude):
    """The NEXT best installed local model for the weak-answer auto-retry
    (v6.8). Benchmark ranking (.nova/bench.json, /bench) wins when it has
    data; otherwise server order. None = nothing else to try."""
    if nmodels is None:
        return None
    try:
        names = [n for n in list_installed_models() if n != exclude]
    except Exception:
        return None
    if not names:
        return None
    if bench is not None:
        try:
            data = bench.load(sess.ws)
            ranked = sorted(((n, (r or [{}])[-1])
                             for n, r in (data.get("models") or {}).items()),
                            key=lambda kv: -bench.score_row(kv[1]))
            for n, _row in ranked:
                if n in names:
                    return n
        except Exception:
            pass
    return names[0]


PROTOCOL_HINT_RE = re.compile(r"===\s*(?:FILE|EDIT)\s*:", re.IGNORECASE)


def _is_protocol_block(body, edits_found=False):
    """True when an "unnamed" fenced block is really a === FILE:/EDIT: ===
    protocol block the main regexes ALREADY parsed (the model wrapped it
    in markdown fences). A SEARCH/REPLACE hunk body counts as protocol
    ONLY when an === EDIT: === header exists somewhere in the raw answer
    (a fence line swallowed it) - a headerless hunk block was never
    parsed, so it must SURVIVE the filter and get the repair round.
    Real unnamed code always survives."""
    if PROTOCOL_HINT_RE.search(body):
        return True
    if "<<<<<<< SEARCH" in body and ">>>>>>> REPLACE" in body:
        return edits_found
    return False


def _unnamed_repair_message(unnamed, have_work=False):
    """v6.8.3 - the ONE corrective re-ask when the model produced code
    block(s) without the === FILE: name === header (the #2 reason a
    'create these files' request ends with nothing on disk: the model
    wraps everything in plain ``` fences and the blocks go unnamed).
    The bodies are echoed back truncated - the model does NOT see its own
    previous answer mid-loop, so this is its only chance to re-emit them
    with proper headers.
    v6.9 `have_work`: the SAME answer also carried named FILE/EDIT work.
    The re-ask then asks ONLY for the unnamed blocks; the named work is
    ALSO carried in chat_turn (keyed by resolved path), so even a partial
    or missing re-emission cannot lose what round 1 already delivered."""
    parts = []
    for i, body in enumerate(unnamed[:4], 1):
        first = body.strip().split("\n")[0][:60] if body.strip() else "(empty)"
        parts.append(f"--- block #{i} ({len(body.splitlines())} lines, starts with: {first}) ---\n"
                     + truncate(body, 2000))
    return (
        "Your answer contained code block(s) but NO === FILE: name === header, "
        "so NOTHING was saved to disk. The file protocol is mandatory and "
        "looks EXACTLY like this:\n\n"
        "=== FILE: relative/path.ext ===\n<complete file content>\n=== END ===\n\n"
        "Re-output EVERY file you intended - each NEW file with its own "
        "=== FILE: path === header and === END === closer, each SMALL "
        "change to an existing file as === EDIT: path === with "
        "<<<<<<< SEARCH / ======= / >>>>>>> REPLACE - ALL of them in THIS "
        "one answer - never promise a later message. No markdown fences "
        "around the block.\n"
        + ("Your earlier named === FILE: === / === EDIT: === blocks were "
           "already received - do NOT repeat them. Output ONLY the "
           "block(s) below, each now named with its === FILE: path === "
           "header and === END === closer, in THIS answer.\n\n"
           if have_work else "")
        + "For reference, the unnamed block(s) you produced were:\n\n"
        + "\n\n".join(parts)
    )


def _draft_valid(text, sess=None):
    """v7.5 SPECULATIVE gate: is a draft answer good enough to skip the
    main brain? Deterministic checks only (zero model calls): complete
    protocol work, every body passes the lint gate, a Run/Preview line,
    no unnamed leftovers. A draft that fails ANY check simply loses and
    the main brain answers normally - the user never sees it.
    v8.12: the guardian's master switch is honored (sess passed in from
    the production caller) - a fleet the user turned OFF no longer
    secretly votes a draft down."""
    try:
        if not text or not text.strip():
            return False
        if "Run:" not in text and "Preview:" not in text:
            return False
        files, unnamed = parse_files(text)
        edits = parse_edits(text)
        if not (files or edits):
            return False
        if unnamed:
            return False
        if quality is not None:
            for name, body in files:
                ok, _problem = quality.preapply_check(name, body)
                if not ok:
                    return False
        # v8.4: the guardian fleet gets a vote too - a draft that
        # breaks ANY of the ~30 languages is not good enough to save
        # the big model a run (deterministic, zero model calls).
        # v8.12: only while the fleet's master switch is ON (the env
        # kill-switch wins even without a session) - a disabled gate
        # must not vote anywhere.
        if guardian is not None and _guardian_master_on(sess):
            try:
                grep = guardian.review_batch(files, chat_fn=None,
                                             cfg={"model": False,
                                                  "web": False})
                if grep.get("rejects"):
                    return False
            except Exception:
                pass
        return True
    except Exception:
        return False


def _guardian_master_on(sess=None):
    """v8.4: the guardian's master switch - settings file on top, the
    NOVA_GUARDIAN=0 env kill-switch always wins (air-gapped CI, tests,
    'the fleet annoys me' days). Fail-soft to ON (its default)."""
    if os.environ.get("NOVA_GUARDIAN", "") == "0":
        return False
    if guardian is None:
        return False
    return guardian.enabled(getattr(sess, "guardian_settings", None)
                            or {}, "on")


def enabled_guardian(sess):
    return _guardian_master_on(sess)


def _guardian_chat_fn(sess):
    """The chat callback the guardian's sub-sub-agents review with: the
    SAME local brain, one tight prompt per file, quiet, no history.
    Returns None on a cloud brain (a fleet review must never silently
    spend the user's credits - the explore layer made the same call)."""
    if not _coding_brain_is_local():
        return None

    def ask(prompt):
        try:
            ans, _ok = stream_chat(sess.model,
                                   [{"role": "user", "content": prompt}],
                                   MODES.get("code", 0.4), sess=None,
                                   num_ctx=_eff_ctx(sess),
                                   section=None, quiet=True)
            return ans or ""
        except Exception:
            return ""
    return ask


def _probe_master_on(sess=None):
    """v8.5: the bug hunter's master switch - settings file on top, the
    NOVA_PROBE=0 env kill-switch always wins (tests, air-gapped CI,
    'the hunter annoys me' days). Fail-soft to ON (its default)."""
    if probe is None:
        return False
    return probe.master_on(getattr(sess, "probe_settings", None))


def _probe_chat_fn(sess):
    """The chat callback the completeness probe reviews with: the SAME
    local brain, one tight prompt, quiet, no history. Returns None on a
    cloud brain (a completeness review must never silently spend the
    user's credits - the guardian made the same call)."""
    if not _coding_brain_is_local():
        return None

    def ask(prompt):
        try:
            ans, _ok = stream_chat(sess.model,
                                   [{"role": "user", "content": prompt}],
                                   MODES.get("code", 0.4), sess=None,
                                   num_ctx=_eff_ctx(sess),
                                   section=None, quiet=True)
            return ans or ""
        except Exception:
            return ""
    return ask


def _learn_allowed():
    """v7.5: the background learner (style + RAG) must NEVER race a test
    suite's temp-dir cleanup: pytest tears workspaces down while a daemon
    thread may still be writing into .nova. Under pytest (or with
    NOVA_NO_LEARN=1) the learning pass simply does not start - the
    synchronous style/RAG APIs stay fully available to the tests."""
    if os.environ.get("NOVA_NO_LEARN", "") == "1":
        return False
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return True


def _post_apply_learn(sess):
    """v7.5: background learning after every apply - the user's coding
    style profile is refreshed and the semantic RAG index is rebuilt
    (daemon thread, fail-soft). Nothing here may slow down or break the
    apply path."""
    try:
        if not _learn_allowed():
            return

        def run():
            try:
                if style is not None \
                        and os.environ.get("NOVA_NO_STYLE", "") != "1":
                    style.refresh(sess.ws, sess.ignore)
            except Exception:
                pass
            try:
                if rag is not None \
                        and os.environ.get("NOVA_NO_RAG", "") != "1":
                    rag.build_async(sess.ws, sess.ignore)
            except Exception:
                pass
        t = threading.Thread(target=run, daemon=True, name="nova-learn")
        t.start()
    except Exception:
        pass


def chat_turn(sess, user_text, auto=False):
    """One full model turn with a MULTI-ROUND TOOL LOOP.

    The model may fire its tool tokens ([SEARCH: q] / [READ: f]) several
    times in a row: each result is fed back and the model continues - until
    it produces files/edits, gives a final answer, or the round budget
    (MAX_TOOL_ROUNDS) runs out. Guards keep the loop healthy even on slow
    hardware where every round costs minutes:
      - repeat guard: the same token+arg never executes twice in one turn;
      - failure guard: a tool that fails gets ONE corrective nudge so the
        turn still ends with a real answer, not a dangling token;
      - work wins: as soon as the model outputs files/edits, tokens are
        skipped and the work is applied.

    Returns a result dict:
        {"answer": str, "files": [names], "edits": [names],
         "applied": [names], "run_cmd": str|None,
         "suggested_run": str|""}   # derived fallback (web button only)
    auto=True -> files/edits are applied WITHOUT prompts (used by the /auto
    and /verify loops; they handle command execution themselves)."""
    print(c(C.D, "\n--- Nova Code is thinking ---"))
    sess.last_request = user_text[:400]   # commit messages + skill capture
    composed = sess.compose(user_text)
    # v7.0: web/UI intent flag - drives the design contract for THIS turn
    # (detected from the user's original words; repair rounds keep it).
    try:
        sess.web_turn = bool(design and design.is_web_task(user_text))
    except Exception:
        sess.web_turn = False
    if sess.explain:
        composed = ("EXPLAIN MODE: analyze and explain ONLY - no file output, "
                    "no edit blocks, no write commands.\n\n" + composed)
    if (_is_continue_word(user_text) and sess.history
            and sess.history[-1]["role"] == "assistant"):
        # A bare "continue" is too vague for a small model - it would often
        # start over from scratch. Give it a precise resume instruction.
        composed = ("Your previous answer was cut off or paused. Continue EXACTLY where it "
                    "stopped - do not repeat files or explanations you already output. If "
                    "files are still missing, output each remaining COMPLETE file with the "
                    "=== FILE: === format, then the run command.")
    sess.last_composed = composed  # /retry always replays the USER's message
    # v8.4: one-shot guardian repair context - the previous batch was
    # refused by the fleet gate; THIS message rides with the exact
    # per-file fix list so a plain "اوکی درستش کن" is already precise.
    _grep_ctx = getattr(sess, "guardian_repair", None)
    if _grep_ctx:
        sess.guardian_repair = None
        composed = composed + "\n\n" + _grep_ctx
    # v8.5: one-shot bug-hunter repair context - the previous batch was
    # refused by the wiring gate; THIS message rides with the exact
    # dead-reference list so a plain "fix it" is already precise.
    _prep_ctx = getattr(sess, "probe_repair", None)
    if _prep_ctx:
        sess.probe_repair = None
        composed = composed + "\n\n" + _prep_ctx
    # v7.5: the query rides on the session so system_parts() can inject the
    # fitting idioms + the semantic codebase hits for THIS request.
    sess._turn_query = user_text
    result = {"answer": "", "files": [], "edits": [], "applied": [],
              "run_cmd": None, "think": None}
    rounds_left = MAX_TOOL_ROUNDS
    seen_tokens = set()   # (token, arg) pairs already executed in this turn
    display = user_text   # transcript label of the current user message
    force_final = False   # set once the repeat guard has fired
    files, edits, unnamed = [], [], []
    repaired_unnamed = False   # v6.8.3: the ONE protocol-repair round
    carried_files, carried_edits = [], []   # v6.9: work kept across it
    # ---- v7.5: the BACKEND-AWARE orchestration ----------------------------
    # ONE place decides WHO serves this turn and HOW MANY answers we ask for:
    #   backend (local/cloud) -> difficulty (router) -> turn-model override,
    #   a speculative draft (easy + local) and best-of-N exploration
    #   (medium/hard + local). A cloud brain gets exactly ONE answer, the
    #   full prompt, zero interference - model switching there happens only
    #   through the user's EXPLICIT cloud route map (/route). Every step is
    #   fail-soft to "exactly as before".
    backend = "local" if sess._local_brain() else "cloud"
    turn_model = None       # model override for THIS turn (router / spec)
    first_answer = None     # pre-computed winner (speculative draft / explore)
    result["explore"] = None
    difficulty = "medium"
    has_coding_route = False
    try:
        if providers is not None:
            _rcfg, _rm = providers.resolve_route("coding")
            has_coding_route = _rcfg is not None
    except Exception:
        pass
    if router is not None:
        try:
            installed = list_installed_models()
            _m, difficulty, _why = router.decide(
                sess.ws, user_text, backend, installed, sess.model,
                has_coding_route=has_coding_route)
            if _m and _m != sess.model:
                turn_model = _m
                print(c(C.D, "[router] " + _why))
            # v8.0: the black box records the routing decision
            if flightlog is not None:
                try:
                    flightlog.log("brain.pick", _why or "route decided",
                                  backend=backend, model=turn_model
                                  or sess.model, difficulty=difficulty)
                except Exception:
                    pass
        except Exception:
            pass
    # v7.14: the model that will actually serve THIS turn (the router's
    # turn-model override or the coding route wins over the session
    # default) - the THINK protocol needs it to decide forced vs native.
    try:
        _svc = turn_model
        if _svc is None and providers is not None:
            _rc, _rm = providers.resolve_route("coding")
            if _rc is not None and _rm:
                _svc = _rm
        sess._think_model = _svc or sess.model
    except Exception:
        sess._think_model = getattr(sess, "_think_model", sess.model)
    # speculative draft: LOCAL + easy + a smaller model available -> run the
    # cheap draft first; keep it only when it fully validates, otherwise
    # escalate silently to the main brain (the classic draft-then-verify).
    if turn_model and backend == "local" and difficulty == "easy" \
            and backend_policy is not None \
            and backend_policy.feature_enabled("speculative", "local"):
        try:
            draft_answer, _dc = stream_chat(
                turn_model, sess.build_messages(composed), MODES[sess.mode],
                sess=None, section=None, quiet=True,
                num_ctx=_eff_ctx(sess))   # v8.11: honor /ctxset here too
            if _draft_valid(draft_answer, sess):
                print(c(C.D, "[speculative] draft accepted - the big model "
                             "stayed cold this turn"))
                first_answer = draft_answer
            else:
                print(c(C.D, "[speculative] draft not clean - escalating to "
                             "the main brain"))
            turn_model = None      # an easy-task pick never serves by itself
        except Exception:
            turn_model = None
    # multi-sample + best-of selection: LOCAL ONLY (samples are free - just
    # time; a cloud API would bill 3-4x, and a frontier model is already
    # better on its first answer). AUTO on HARD tasks only - a medium task
    # usually does not justify the extra latency; ask for it explicitly
    # with /explore (or NOVA_EXPLORE_MEDIUM=1 to widen the auto gate).
    _force_k = 0
    try:
        _force_k = int(getattr(sess, "_force_explore", 0) or 0)
    except Exception:
        _force_k = 0
    _explore_on = backend == "local" and first_answer is None \
        and backend_policy is not None \
        and backend_policy.feature_enabled("explore", "local") \
        and explore is not None \
        and (_force_k >= 2
             or difficulty == "hard"
             or (difficulty == "medium"
                 and os.environ.get("NOVA_EXPLORE_MEDIUM", "") == "1"))
    if _explore_on:
        try:
            _k = max(2, min(_force_k or backend_policy.best_of_count("local"), 4))
            print(c(C.D, f"[explore] generating {_k} candidate answers "
                         "in parallel..."))
            _msgs = sess.build_messages(composed)
            _model = turn_model or sess.model
            exp = explore.explore(
                lambda _t: stream_chat(_model, _msgs, _t, sess=None,
                                       section=None, quiet=True,
                                       num_ctx=_eff_ctx(sess)),
                MODES[sess.mode], k=_k)
            _best = exp["best"]
            first_answer = exp["ranked"][_best]["text"]
            result["explore"] = {"k": _k, "model": _model,
                                 "scores": [r["score"] for r in exp["ranked"]],
                                 "chosen": _best}
            print(c(C.D, "[explore] scores: "
                         + ", ".join(f"#{i + 1}={r['score']}"
                                     for i, r in enumerate(exp["ranked"]))
                         + f" -> using #{_best + 1}"))
        except Exception:
            first_answer = None
    while True:
        # v7.5: the turn may already HAVE its answer (speculative draft or
        # the explore winner) - round 1 then needs no request at all.
        # Otherwise: the router's turn-model override (when set) streams
        # directly (section=None - a stored route would only fight it), and
        # the normal path goes through the routing layer as before (v6.7).
        if first_answer is not None:
            answer, complete = first_answer, True
            first_answer = None
        elif turn_model is not None:
            answer, complete = stream_chat(turn_model,
                                           sess.build_messages(composed),
                                           MODES[sess.mode], sess=sess,
                                           section=None)
        else:
            answer, complete = stream_chat(sess.model,
                                           sess.build_messages(composed),
                                           MODES[sess.mode], sess=sess,
                                           section="coding")
        # v6.8: WEAK-ANSWER AUTO-RETRY - an EMPTY answer on a local brain
        # gets exactly ONE silent retry on the next installed model
        # (bench-ranked when /bench has data). Cloud brains are never
        # retried here (no silent credit spend).
        # v6.8.1 fix: section="coding" re-routed the retry to the SAME
        # failing /brain model; section=None streams the fallback model
        # directly, and the EXCLUDED model is the one that actually served.
        if not answer.strip() and _coding_brain_is_local():
            # v8.7: the excluded model is whoever ACTUALLY served the
            # empty answer - the router's turn-model pick when it fired
            # (it used to be excluded from the search, so the "another
            # model" retry could re-pick the very model that failed),
            # else sess.model possibly re-routed by section="coding".
            served = turn_model if turn_model is not None else sess.model
            if turn_model is None:
                try:
                    if providers is not None:
                        _rcfg, _rmodel = providers.resolve_route("coding")
                        if _rcfg is not None and _rmodel:
                            served = _rmodel
                except Exception:
                    pass
            fb = _fallback_local_model(sess, served)
            if fb:
                print(c(C.Y, "\n[!] empty answer - auto-retry with another "
                             f"local model: {fb}"))
                try:
                    answer, complete = stream_chat(
                        fb, sess.build_messages(composed), MODES[sess.mode],
                        sess=sess, section=None)
                except Exception as e:
                    print(c(C.Y, f"[!] fallback retry failed: {e}"))
                    answer = ""
        # v7.14: THINK EXTRACTION - the reasoning block (forced for
        # non-reasoners, native <think> for reasoners) is separated BEFORE
        # any parsing, remembering or tool handling: thinking can never
        # become a file, fire a token, or bloat the conversation history.
        # The raw text already streamed live to the terminal/web - the
        # web face re-renders it as a collapsible think box.
        #
        # v8.2 CUT-ANSWER RESCUE, in three layers:
        #   1. SALVAGE - think.extract() no longer discards an unclosed
        #      reasoning block that contains real work (files / fences /
        #      tool tokens): the work becomes the answer (salvaged=True).
        #   2. HONEST TRUNCATION - stream_chat now reports done_reason=
        #      length (Ollama) and finish_reason length/max_tokens (cloud)
        #      as complete=False instead of pretending the answer ended.
        #   3. AUTO-CONTINUE - when the answer was cut (not complete) or
        #      an open reasoning block left NOTHING usable, Nova silently
        #      asks the model to continue EXACTLY where it stopped (the
        #      raw tail rides along so it can resume mid-file), appends
        #      the continuation to the RAW text and re-extracts once.
        # The user-visible effect: a 4B model that hit its window mid-file
        # no longer dies with 'empty answer' - the file gets finished.
        raw_answer = answer
        _td = None
        if think is not None:
            try:
                _td = think.extract(answer)
            except Exception:
                _td = None
            if _td is not None:
                answer = _td["answer"]
        _cont_left = max(0, min(3, _envint("NOVA_AUTO_CONTINUE", 2)))
        while raw_answer.strip() and _cont_left > 0 \
                and not _LAST_STREAM_HARD \
                and not _LAST_STREAM_INTERRUPT \
                and ((not complete) or (not answer.strip())):
            # continue only on a REAL cut: the stream died / hit the
            # output cap, or an open reasoning block left nothing usable
            if complete and answer.strip():
                break
            _cont_left -= 1
            print(c(C.Y, "\n[continue] the answer was cut off before it "
                         "finished - Nova continues it automatically..."))
            try:
                _cmsgs = sess.build_messages(
                    _resume_message(raw_answer, user_text))
                if turn_model is not None:
                    answer, complete = stream_chat(
                        turn_model, _cmsgs, MODES[sess.mode], sess=sess,
                        section=None)
                else:
                    answer, complete = stream_chat(
                        sess.model, _cmsgs, MODES[sess.mode], sess=sess,
                        section="coding")
            except Exception as _ce:
                print(c(C.Y, "[continue] failed: " + str(_ce)[:160]))
                break
            # v8.11: join at the REAL cut point. The resume prompt says
            # "continue EXACTLY where it stopped", so a stream cut
            # mid-token ('def fo' + 'o(bar):') stitched with a blank
            # line wrote CORRUPTED files to disk ('def fo\n\no(bar):')
            # even though the continuation was perfect. A cut inside a
            # word (raw ends in a word char, continuation starts in
            # one) is unambiguous -> direct concatenation; a clean
            # line-boundary cut keeps the blank-line join.
            if answer.strip():
                # \Z (not $): a trailing newline must NOT count as a
                # mid-token cut - $ also matches just before it
                if re.search(r"\w\Z", raw_answer or "") \
                        and re.match(r"\w", answer):
                    raw_answer = (raw_answer or "") + answer
                else:
                    raw_answer = (raw_answer or "").rstrip() \
                        + "\n\n" + answer.rstrip()
            # else: nothing usable came back - keep the raw text as is
            if think is not None:
                try:
                    _td = think.extract(raw_answer)
                except Exception:
                    _td = None
            # v8.10.1 fix: the merged RAW text is the truth. Without a
            # think module (a supported configuration) - or when extract()
            # raises - `answer` used to stay the continuation TAIL only:
            # the first chunk's files silently vanished from the applied
            # batch AND from history (the resume prompt says 'do not
            # repeat', so the tail alone never carried them).
            answer = _td["answer"] if _td is not None else raw_answer
        if think is not None and _td and _td.get("think"):
            result["think"] = _td["think"]
            emit_event({"t": "think", "text": _td["think"],
                        "native": bool(_td.get("native"))})
        print("\n" + c(C.D, "-" * 46))
        result["answer"] = answer
        if not answer.strip():
            print(c(C.Y, "[!] empty answer - the model produced no usable output "
                         "(its reasoning block may never have closed, or the "
                         "connection failed). Try again, type:  continue  - or /clear."))
            result["complete"] = complete
            return result
        sess.remember(composed, answer, display_user=display)
        sess.loads = []  # attachments were delivered successfully
        # v8.3 context engine: fold the old block when the conversation
        # outgrew the window's threshold during that turn (deterministic,
        # offline - so the NEXT turn starts light).
        try:
            sess._maybe_ctx_compact()
        except Exception:
            pass
        # ---- live plan (v5.0): the LAST plan block is the truth ------
        if nova_todo is not None:
            new_plan = nova_todo.parse_plan(answer)
            if new_plan or sess.todo:
                sess.todo = nova_todo.merge_plan(sess.todo, new_plan)
                emit_event({"t": "todo", "items": sess.todo,
                            "progress": nova_todo.progress(sess.todo)})
        if not complete:
            print(c(C.Y, "[!] the answer may be incomplete (interrupted or timed out)."
                       " Type:  continue  - Nova will finish where it stopped."))

        # ---- model-initiated tools + output protocols -----------------------
        # The active tokens live in MODEL_ACTIONS (registry-driven: adding a
        # new token there automatically works here too). Output always wins:
        # if the model produced files/edits, apply them and skip tool tokens.
        run_hints_in_files = []      # v6.4: 'Run:' lines that slipped into bodies
        files, unnamed = parse_files(answer, run_hints=run_hints_in_files)
        edits = parse_edits(answer)
        # v6.9: a fenced === EDIT:/FILE: === block surfaces here as an
        # "unnamed" code block - it is protocol text already parsed above,
        # never ask where to "save" it. REAL unnamed code survives the
        # filter (the old `unnamed = []` silently dropped a genuinely new
        # file whenever an EDIT block rode along in the same answer ->
        # "cannot create multiple files and edit them").
        unnamed = [u for u in unnamed
                   if not _is_protocol_block(u, edits_found=bool(edits))]
        # v6.9: named work carried from a previous repair round - the
        # model may re-emit only PART of it when asked to name the rest.
        if carried_files:
            files = carried_files + files   # offer_apply keeps the LAST block per path
        if carried_edits:
            # keyed by RESOLVED path: './app.py' in round 2 must count as
            # 'app.py' from round 1 (string compare used to let both through
            # and the second plan silently reverted the first).
            new_paths = set()
            for p, h in edits:
                if not h:
                    continue   # a malformed re-emission must not drop the carried hunks
                try:
                    new_paths.add(str(safe_join(sess.ws, p).resolve()))
                except ValueError:
                    new_paths.add(str(p))
            for p, h in carried_edits:
                try:
                    kp = str(safe_join(sess.ws, p).resolve())
                except ValueError:
                    kp = str(p)
                if kp not in new_paths:
                    edits.append((p, h))
        result["files"] = [f[0] for f in files]
        result["edits"] = [e[0] for e in edits]
        if (files or edits) and unnamed and not repaired_unnamed \
                and not force_final and rounds_left > 0:
            # v6.9: named work + STILL-unnamed block(s): one repair round
            # for the unnamed part only; the named work rides along in
            # carried_* so the re-emission cannot lose it.
            repaired_unnamed = True
            rounds_left -= 1
            carried_files, carried_edits = files, edits
            display = "(protocol repair - asked to name the remaining files)"
            composed = _unnamed_repair_message(unnamed, have_work=True)
            continue
        if files or edits:
            break
        if unnamed and not repaired_unnamed and not force_final \
                and rounds_left > 0:
            # v6.8.3 PROTOCOL REPAIR: named files beat "Save as?" prompts
            # (REPL) and beat silent skipping (web). One re-ask, then give
            # up gracefully into the old paths.
            repaired_unnamed = True
            rounds_left -= 1
            carried_files, carried_edits = [], []
            display = "(protocol repair - asked to name the files)"
            composed = _unnamed_repair_message(unnamed)
            continue

        found = find_model_action(answer)
        if found is None or force_final:
            break
        act, arg = found
        key = (act["name"], arg.strip().lower())
        if key in seen_tokens:
            # repeat guard: same token + same arg twice = a small model going
            # in circles. One corrective nudge, then the loop hard-stops.
            force_final = True
            rounds_left = 0
            display = f"(repeated tool token {act['name']} - asked to finish)"
            composed = (f"You already used [{act['name']}: {arg}] and its result is already "
                        "in this conversation. Do NOT repeat the token. Continue and finish "
                        "your answer now using the information you already have.")
            continue
        if rounds_left <= 0:
            break
        seen_tokens.add(key)
        rounds_left -= 1
        display = f"(tool round - [{act['name']}: {arg}])"
        follow = _exec_model_action(sess, act, arg)
        if follow:
            composed = follow
            continue
        # failure guard: the tool failed or had nothing - one nudge so the
        # turn still ends with a real answer instead of a dangling token
        composed = (f"Your [{act['name']}: {arg}] tool call returned nothing useful "
                    "(failed or offline). Do NOT repeat it. Continue and finish your "
                    "answer now using what you know.")

    if files or edits or unnamed:
        if sess.explain:
            print(c(C.Y, "[explain] file output ignored - explain mode only "
                         "analyzes (turn it off: /explain off)"))
        else:
            result["applied"] = offer_apply(sess, files, unnamed, edits=edits, auto=auto) or []

    m = extract_run_hint(answer)
    if m:
        result["run_cmd"] = _normalize_run_hint(m)
    elif run_hints_in_files:
        # the model put its Run: line inside a file body - it was stripped
        # from the file, so still offer the button with it
        result["run_cmd"] = _normalize_run_hint(run_hints_in_files[-1])
    # v7.7: keep the Run chip alive across edit turns - a weak model often
    # forgets the Run/Preview line on follow-up edits, the chip vanished
    # and the stale button (or nothing) was left behind. When THIS turn
    # touched files (or staged a batch) and carries no fresh hint, re-offer
    # the project's last known hint. A fresh RUNNABLE hint always wins;
    # a pure-prose hint (no latin/digit at all) is still shown to the user
    # but never becomes the project's remembered command; /clear and
    # workspace switches reset it.
    if result.get("run_cmd") and re.search(r"[A-Za-z0-9]", result["run_cmd"]):
        sess.last_run_cmd = result["run_cmd"]
    elif not result.get("run_cmd") \
            and result.get("applied") \
            and getattr(sess, "last_run_cmd", ""):
        # v8.11: only when files were REALLY applied this turn - the old
        # pending_apply branch re-offered the project's stale Run hint
        # while a batch was merely STAGED (nothing on disk yet): the UI
        # then said 'nothing written yet' AND offered to run code that
        # does not exist, and a failed click sent the auto-fix machine
        # after the wrong files
        result["run_cmd"] = sess.last_run_cmd
    if not result["run_cmd"] and result["applied"]:
        # v6.9: files landed but the model never said how to run them -
        # DERIVED suggestion for the web Run button. Kept in its own key:
        # /verify and /auto may only follow a command the MODEL wrote
        # (a derived "python helper.py" on a support module would exit 0
        # and fake a green verify without ever running the entry point).
        result["suggested_run"] = _default_run_cmd(result["applied"])
    # v8.2: an honest completion flag for the web done event - a turn
    # still cut after every auto-continue round must not look green.
    result["complete"] = bool(complete)
    return result

# --------------------------------------------------------------- backups
def backup_file(sess, target):
    bk_dir = sess.ws / ".nova_backups"
    bk_dir.mkdir(exist_ok=True)
    rel = target.relative_to(sess.ws).as_posix().replace("/", "__")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bk = bk_dir / (ts + "__" + rel)
    shutil.copy2(target, bk)
    return bk

def stop_serve(sess):
    proc = sess.serve_proc
    if not proc:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        print(c(C.Y, f"Preview server on port {sess.serve_port} stopped."))
    else:
        print(c(C.D, f"(preview server on port {sess.serve_port} had already exited)"))
    sess.serve_proc = None
    sess.serve_port = None

# --------------------------------------------------------------- apply files
def offer_apply(sess, files, unnamed, edits=None, auto=False):
    """Write the model's output into the workspace (with backups + /undo):
    === FILE: === blocks are written whole, === EDIT: === blocks are applied
    as validated SEARCH/REPLACE hunks (all-or-nothing per file).
    auto=True: apply everything WITHOUT any prompt - used by the /auto and
    /verify loops (backups still happen, so /undo still restores everything).
    Returns the list of applied file names."""
    # v8.12: the loop-guard flag starts FRESH on every call - a stale
    # True from an earlier turn must never make /auto believe THIS
    # batch was gate-refused (only a refusal below sets it again).
    sess.batch_refused = False
    edits = edits or []
    plans = []  # (name, body, target)
    for name, body in files:
        try:
            target = safe_join(sess.ws, name)
        except ValueError as e:
            print(c(C.R, "[skip] " + str(e)))
            continue
        # v8.0: the FILE sandbox - agent file writes stay inside the
        # workspace and away from Nova's own .nova state / sensitive
        # folders (a model-issued === FILE: .nova/profile.json === used
        # to be a valid write that silently re-configured the agent).
        ok_s, why_s = sandbox.check_path(sess.ws, target, write=True) \
            if sandbox is not None else (True, "")
        if not ok_s:
            print(c(C.R, "[sandbox refused] " + name + ": " + why_s))
            emit_event({"t": "note", "text": "[i] " + name +
                        " was NOT written: " + why_s})
            try:
                if flightlog is not None:
                    flightlog.warn("sandbox.write", "file write refused",
                                   path=name, reason=why_s)
            except Exception:
                pass
            continue
        plans.append((name, body, target))

    # v6.2.1 fix: small models sometimes repeat === FILE: === blocks for the
    # same path in ONE answer. Without dedupe the second block backed up the
    # FIRST block's just-written content, so /undo restored an intermediate
    # state instead of the pre-apply content (silent undo corruption). Keep
    # the LAST block per target (final content wins); each target is then
    # backed up exactly once with its true pre-apply content.
    if plans:
        _dedup = {}
        for name, body, target in plans:
            _dedup[target.resolve()] = (name, body, target)
        if len(_dedup) < len(plans):
            print(c(C.Y, f"[i] {len(plans) - len(_dedup)} duplicate FILE block(s) "
                         "merged - the last one wins"))
            plans = list(_dedup.values())

    # v7.1.0: an EMPTY === FILE: === block for an EXISTING non-empty file is
    # degenerate model output - applying it would blank real content with a
    # zero-byte write (the lint gate passes empty content by design, so this
    # is the one place it can be caught). New empty files (__init__.py,
    # .gitkeep) stay allowed; only blanking an EXISTING file is refused.
    _real_plans = []
    for name, body, target in plans:
        if not body.strip() and target.exists() \
                and target.stat().st_size > 0:
            print(c(C.R, "[refused] " + name + ": EMPTY file block would blank "
                         "an existing file - use === EDIT: === to change it"))
            emit_event({"t": "note", "text":
                        "[i] " + name + " was NOT written: the file block was "
                        "empty and the file already has content."})
            continue
        _real_plans.append((name, body, target))
    plans = _real_plans

    # validate edit blocks against the CURRENT files on disk
    eplans, epb = prepare_edits(sess, edits) if edits else ([], [])
    for path, reason in epb:
        print(c(C.R, f"[edit refused] {path}: {reason}"))
    # a file that is both fully rewritten and edited in the same answer is a
    # model contradiction: the edit was validated against the OLD content, so
    # applying it would silently throw the rewrite away - refuse the edit
    rewritten = {p[2].resolve() for p in plans}
    kept_eplans = []
    for e in eplans:
        if e[1].resolve() in rewritten:
            print(c(C.R, f"[edit refused] {e[0]}: this file is also fully rewritten "
                          "with === FILE: === in the same answer - pick one"))
        else:
            kept_eplans.append(e)
    eplans = kept_eplans

    if not plans and not eplans and not unnamed:
        return []
    if not plans and not eplans and unnamed:
        if auto:
            print(c(C.Y, "[auto] skipped unnamed code block(s) - name files with "
                         "=== FILE: path === so they can be written."))
            return []
        for i, body in enumerate(unnamed[:3], 1):
            preview = body.strip().split("\n")[0][:60]
            print(c(C.Y, f"[?] Nova produced code block #{i} without a file name ({preview}...)"))
            ans = ui_input("    Save as (relative path, Enter=skip): ").strip()
            if ans:
                try:
                    plans.append((ans, body, safe_join(sess.ws, ans)))
                except ValueError as e:
                    print(c(C.R, "[skip] " + str(e)))
        if not plans:
            return []
    # v6.9: unnamed blocks left over NEXT TO named work are no longer
    # silently dropped - the REPL still gets its "Save as?" prompt and
    # auto/web get a loud note instead of silent data loss.
    if unnamed and (plans or eplans):
        if auto or NONINTERACTIVE:
            note = ("[i] " + str(len(unnamed)) + " unnamed code block(s) "
                    "were NOT saved - name files with === FILE: path === "
                    "so they can be written.")
            # terminal prints it; the web face gets the structured event.
            # (printing AND emitting doubled the line in the browser - the
            # console tee already bridges every print into the notes box.)
            if EVENT_SINK is None:
                print(c(C.Y, "[auto] " + note))
            emit_event({"t": "note", "text": note})
        else:
            for i, body in enumerate(unnamed[:3], 1):
                preview = body.strip().split("\n")[0][:60]
                print(c(C.Y, f"[?] Nova produced code block #{i} without a file name ({preview}...)"))
                ans = ui_input("    Save as (relative path, Enter=skip): ").strip()
                if ans:
                    try:
                        plans.append((ans, body, safe_join(sess.ws, ans)))
                    except ValueError as e:
                        print(c(C.R, "[skip] " + str(e)))
    # ---- web confirm-changes mode: stage instead of writing --------------
    # v6.9 fix: the guard used to require auto=True, so web turns that run
    # with auto=False (/fix, /retry, /review typed into the web box) hit
    # the interactive apply prompt instead - ask() returns "" under
    # NONINTERACTIVE, and the default answer APPLIED everything with zero
    # approval. Every non-interactive confirm_changes turn now stages.
    if NONINTERACTIVE and getattr(sess, "confirm_changes", False):
        return stage_pending_changes(sess, plans, eplans, edits)

    if not auto:
        edit_base = len(plans) + 1   # eplans numbering starts right after plans -
                                      # captured BEFORE plans is filtered below, so
                                      # the numbers picked in "select" mode still
                                      # match what was printed here
        print(c(C.B, "\n=== file changes ==="))
        for i, (name, body, target) in enumerate(plans, 1):
            lines = body.count("\n") + 1
            status = "overwrite" if target.exists() else "new"
            print(f"  [{i}] {name}  ({status}, {lines} lines)")
        for j, (name, target, nh, _new) in enumerate(eplans, edit_base):
            print(f"  [{j}] {name}  (edit, {nh} hunk{'s' if nh != 1 else ''})")

        ans = ask("Apply changes? [Y/n/s(elect)/d(iff)]: ").strip().lower()
        if ans in ("n", "no"):
            print(c(C.D, "(skipped - files stay unchanged)"))
            return []
        if ans in ("s", "select"):
            pick = ui_input("Change numbers to apply (comma, e.g. 1,3): ").strip()
            total = len(plans) + len(eplans)
            want = {int(x) for x in re.findall(r"\d+", pick) if 0 < int(x) <= total}
            # NOTE: both filters must use the SAME pre-filter offset (edit_base)
            # that was printed above - recomputing it from the now-shrunk
            # `plans` list here was the v4.0 bug: it silently applied/skipped
            # the wrong edit whenever both files and edits were selectable.
            plans = [p for i, p in enumerate(plans, 1) if i in want]
            eplans = [e for j, e in enumerate(eplans, edit_base) if j in want]
            if not plans and not eplans:
                print(c(C.D, "(nothing selected)"))
                return []
        if ans in ("d", "diff"):
            plans, eplans = _diff_review(sess, plans, eplans, edits)
            if not plans and not eplans:
                print(c(C.D, "(nothing approved)"))
                return []

    snap_batch = []       # persistent undo (v5.0): [(target, backup|None)]
    applied, has_py, has_js, has_html = [], False, False, False
    # NOTE (v6.8.1): sess.last_batch is NOT reset here anymore - the lint
    # gate below can reject the batch BEFORE anything is written, and a
    # rejected batch must not wipe the previous apply's in-memory /undo.

    # ---- v6.8: INTERNAL LINTER BEFORE APPLY -------------------------------
    # A file that cannot even parse must never reach the disk (the old
    # gate only ran AFTER writing). Atomic rule: ANY rejected file aborts
    # the whole batch BEFORE a single byte is written.
    if quality is not None:
        lint_rejects = []
        for name, body, target in plans:
            ok, problem = quality.preapply_check(name, body)
            if not ok:
                lint_rejects.append((name, problem))
        for name, target, nh, updated in eplans:
            ok, problem = quality.preapply_check(name, updated)
            if not ok:
                lint_rejects.append((name, problem))
        if lint_rejects:
            for name, problem in lint_rejects:
                print(c(C.R, f"[lint] {name}: {problem}"))
            print(c(C.Y, "[lint] " + str(len(lint_rejects)) +
                         " file(s) failed the pre-apply check - NOTHING was "
                         "written (fix the content and ask again)"))
            emit_event({"t": "lint_reject", "files": [
                {"name": n, "problem": p} for n, p in lint_rejects]})
            sess.last_feedback = {"syntax": [(n, p) for n, p in lint_rejects],
                                  "lint": [], "tests": None}
            sess.batch_refused = True     # v8.11: fresh flag for the loop guard
            return []

    # lint gate passed - from here on the batch is really happening
    # ---- v8.4: THE CODE GUARDIAN - supervisor's deterministic gate -----
    # nova_quality only deeply knows py/js/json/html/css; the guardian
    # fleet covers ~30 languages (parsers, parse-only tools, a string-
    # aware bracket scanner, bug patterns). Same atomic contract as the
    # lint gate: ANY deterministic error aborts the batch BEFORE one
    # byte is written, and the exact repair list is kept for the next
    # turn. Fail-soft: a broken guardian can never stop an apply.
    if guardian is not None and enabled_guardian(sess):
        try:
            gset = getattr(sess, "guardian_settings", None) or {}
            grep = guardian.review_batch(
                [(n, b) for n, b, _t in plans],
                chat_fn=None,                       # pre-apply: deterministic
                cfg={"model": False,                # layer only (latency)
                     "web": False,                  # the web enriches the
                     "reject_syntax": guardian.enabled(   # MODEL layer only
                         gset, "reject_syntax")},
                edit_bodies=[(n, u) for n, _t, _nh, u in eplans])
            if grep["rejects"]:
                for d in grep["rejects"]:
                    for line, problem in d["errors"][:3]:
                        print(c(C.R, "[guardian] %s: line %s: %s"
                                     % (d["file"], line or "?", problem)))
                n_err = sum(len(d["errors"]) for d in grep["rejects"])
                print(c(C.Y, "[guardian] " + str(len(grep["rejects"])) +
                             " file(s) failed the " +
                             str(guardian.lang_count()) + "-language fleet "
                             "gate (" + str(n_err) + " problem(s)) - NOTHING "
                             "was written"))
                emit_event({"t": "guardian_reject",
                            "files": [{"name": d["file"],
                                       "lang": d["lang"],
                                       "errors": d["errors"],
                                       "warns": d["warns"]}
                                      for d in grep["rejects"]],
                            "repair": guardian.repair_prompt(grep)})
                sess.last_feedback = {"syntax": [
                    (d["file"], d["errors"][0][1] if d["errors"] else "?")
                    for d in grep["rejects"]],
                    "lint": [], "tests": None,
                    "guardian": guardian.findings_summary(grep)}
                sess.batch_refused = True   # v8.11: fresh loop-guard flag
                sess.guardian_repair = guardian.repair_prompt(grep)
                if flightlog is not None:
                    try:
                        flightlog.warn("guardian.reject",
                                       "pre-apply fleet gate refused the "
                                       "batch", files=", ".join(
                                           d["file"] for d in
                                           grep["rejects"][:6]))
                    except Exception:
                        pass
                return []
            for d in grep["warns"]:
                for line, problem in d["warns"][:2]:
                    print(c(C.Y, "[guardian] %s: line %s: %s (applied anyway)"
                                 % (d["file"], line or "?", problem)))
        except Exception:
            pass                       # the guardian never breaks an apply

    # ---- v8.5: THE BUG HUNTER - the wiring gate -------------------------
    # Syntax can be perfect and a button still DEAD: a lookup of an id
    # that exists nowhere, an onclick naming a function nobody defined,
    # a <script src> pointing at a file that was never written. The
    # wiring gate builds the element graph across the batch + workspace
    # and REFUSES the batch before one byte is written when a reference
    # is dead (the same atomic contract as the lint/guardian gates).
    if probe is not None and _probe_master_on(sess):
        try:
            pset = getattr(sess, "probe_settings", None) or {}
            # v8.12: the deep sweep joins the gate trigger - a user who
            # turned wiring off but deep on still gets the pre-apply
            # gate (deep alone used to be silently post-apply-only).
            if probe.enabled(pset, "wiring") or probe.enabled(pset, "deep"):
                prep = probe.pre_apply_gate(
                    [(n, b) for n, b, _t in plans] +
                    [(n, u) for n, _t, _nh, u in eplans],
                    ws=sess.ws, cfg=pset)
                if prep["reject"]:
                    for _rel, _line, msg in prep["errors"][:4]:
                        print(c(C.R, "[hunter] %s" % msg))
                    print(c(C.Y, "[hunter] " + str(len(prep["errors"])) +
                                 " dead reference(s) - NOTHING was written "
                                 "(every id/handler/file must exist)"))
                    emit_event({"t": "probe_reject",
                                "errors": prep["errors"][:12],
                                "warns": prep["warns"][:8],
                                "repair": prep["repair"]})
                    sess.last_feedback = {
                        "syntax": [], "lint": [], "tests": None,
                        "probe": [(rel, line, msg) for rel, line, msg
                                  in prep["errors"][:12]]}
                    sess.batch_refused = True   # v8.11: fresh loop-guard flag
                    sess.probe_repair = prep["repair"]
                    if flightlog is not None:
                        try:
                            flightlog.warn("probe.reject",
                                           "pre-apply wiring gate refused "
                                           "the batch",
                                           files=", ".join(
                                               r for r, _l, _m in
                                               prep["errors"][:6]))
                        except Exception:
                            pass
                    return []
                for rel, line, msg in prep["warns"][:3]:
                    print(c(C.Y, "[hunter] %s: line %s: %s (applied anyway)"
                                 % (rel, line or "?", msg)))
        except Exception:
            pass                       # the hunter never breaks an apply

    sess.last_batch = []  # one undo unit per apply

    # ---- v6.8: ATOMIC MULTI-FILE TRANSACTION ------------------------------
    # The old loop SKIPPED a file whose write failed and happily applied
    # the rest - a half-applied batch is worse than none (imports break,
    # /undo restores files one by one). Now: first failure ROLLS BACK
    # every file already written in this batch (backups restored, new
    # files deleted) and the batch reports as one failed transaction.
    tx_journal = []   # [(target, existed, backup_path_or_None)]
    tx_failed = None
    # v7.1.0 fix: build the rollback baseline from the FULL batch plan. The
    # old dict was built from `applied` while it was still EMPTY (always {}),
    # so a rolled-back file erased an earlier apply's new/modified record -
    # exactly the bug the v6.9 note claimed to fix.
    touched_before = {n2: sess.touched.get(n2)
                      for n2 in [p[0] for p in plans] + [e[0] for e in eplans]}

    def _rollback():
        for target, existed, bk in reversed(tx_journal):
            try:
                if existed and bk is not None and bk.exists():
                    shutil.copy2(bk, target)
                elif not existed and target.exists():
                    target.unlink()
            except OSError as e:
                print(c(C.R, f"  [rollback] {target.name}: {e}"))

    for name, body, target in plans:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            status = "overwritten (backup saved)" if existed else "written"
            bk = backup_file(sess, target) if existed else None
            # v6.8.1 fix: journal BEFORE opening - open(target, "w") already
            # TRUNCATES the file, so a write that dies mid-way (ENOSPC, I/O
            # error, lone surrogate = ValueError) must still be rolled back
            # to its backup / removed as a partial stray file.
            tx_journal.append((target, existed, bk))
            # newline="\n": keep exact LF line endings on Windows too (CRLF would
            # break bash/node scripts and git diffs); encoding stays UTF-8.
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
        except (OSError, ValueError) as e:
            tx_failed = (name, e)
            break
        if bk:
            sess.last_batch.append((target, bk))
        snap_batch.append((target, bk))    # None = new file -> undo deletes
        applied.append(name)
        sess.touched[name] = "modified" if existed else "new"
        lname = name.lower()
        has_py = has_py or lname.endswith(".py")
        has_js = has_js or lname.endswith(".js")
        has_html = has_html or lname.endswith(".html")
        print(c(C.G, f"  + {name} [{status}]"))
    if tx_failed is None:
        for name, target, nh, updated in eplans:
            # edit = modify an existing file: always a backup first, so /undo
            # restores the pre-edit content exactly like a full rewrite does
            try:
                bk = backup_file(sess, target)
                tx_journal.append((target, True, bk))
                with open(target, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(updated)
            except (OSError, ValueError) as e:
                tx_failed = (name, e)
                break
            sess.last_batch.append((target, bk))
            snap_batch.append((target, bk))
            applied.append(name)
            sess.touched[name] = "modified"
            lname = name.lower()
            has_py = has_py or lname.endswith(".py")
            has_js = has_js or lname.endswith(".js")
            has_html = has_html or lname.endswith(".html")
            print(c(C.G, f"  ~ {name} [edited: {nh} hunk{'s' if nh != 1 else ''}, backup saved]"))
    if tx_failed is not None:
        name, err = tx_failed
        print(c(C.R, f"  [!] {name}: cannot write ({err}) - ROLLING BACK the "
                     "whole batch (atomic transaction)"))
        _rollback()
        # journal + undo bookkeeping must forget the rolled-back files
        rolled = {t.resolve() for t, _e, _b in tx_journal}
        sess.last_batch = [(t, b) for t, b in sess.last_batch
                           if t.resolve() not in rolled]
        snap_batch = [b for b in snap_batch if b[0].resolve() not in rolled]
        for n2 in list(applied):
            old_val = touched_before.get(n2)
            if old_val is None:
                sess.touched.pop(n2, None)
            else:
                sess.touched[n2] = old_val
        print(c(C.Y, "[tx] batch aborted - every file is back to its "
                     "pre-apply state"))
        emit_event({"t": "tx_aborted", "file": name, "error": str(err)})
        return []
    # ---- v7.0 DESIGN ENGINE: the beauty floor -----------------------------
    # Deterministic post-apply polish (charset/viewport/title, missing or
    # absent stylesheets filled with the Nova design system). Runs BEFORE
    # the snapshot unit so /undo removes the floor files too.
    _design_polish_hook(sess, applied, snap_batch)
    # ---- v7.2 IMAGES: real internet photos into the applied pages --------
    # Same contract as the design hook: rewrites in place + asset extras
    # join the SAME undo unit / snapshot before the push.
    _image_fill_hook(sess, applied, snap_batch)
    # ---- v7.3 FONTS: local font library + context-aware pairing ---------
    # Same contract: woff2 binaries + nova-fonts.css join the SAME undo
    # unit; pages are re-linked in place (link/rtl) AFTER the images pass.
    _font_install_hook(sess, applied, snap_batch)

    sess.rescan(silent=True)
    print(c(C.G, f"Applied {len(applied)} file(s)." +
               ("  (/undo [n] restores them)" if sess.last_batch else "")))

    # ---- persistent snapshot unit (unlimited /undo) -----------------------
    if snaps is not None and snap_batch:
        note = diffview.summarize_changes(
            [n for n in applied if sess.touched.get(n) == "new"],
            [n for n in applied if sess.touched.get(n) == "modified"]) \
            if diffview is not None else ""
        uid, err = snaps.push_auto_unit(sess.ws, snap_batch, note=note)
        if err and not uid:
            print(c(C.Y, "[!] snapshot unit failed: " + err))
        elif err:
            # v8.0: skip-notes (e.g. a too-large file) come back with a
            # VALID uid - that is a warning, not a failure
            print(c(C.D, "[i] snapshot note: " + err))

    # ---- v7.5 GIT-NATIVE COMMIT-PER-EDIT (every workspace, every edit) ---
    # The user's own repo wins when one exists; otherwise the Nova-managed
    # history repo (.nova/history.git) takes the commits - one commit per
    # file, descriptive messages, zero config needed. NOVA_NO_GIT=1 opts
    # out entirely. Best effort: a git hiccup must never fail the apply.
    if commitmsg is not None and applied \
            and os.environ.get("NOVA_NO_GIT", "") != "1":
        try:
            mode = commitmsg.history_mode(sess.ws)
            if mode == "repo":
                _git_autocommit(sess, applied)      # v6.8: one commit per file
            else:
                _nova_history_commit(sess, applied)
        except Exception as e:
            print(c(C.Y, "[git] auto-commit skipped: " + str(e)))

    # ---- automatic quality gate: syntax + optional lint + tests ----------
    _feedback_gate(sess, applied, auto=auto)

    # ---- v7.5: background learning (style profile + semantic RAG) --------
    _post_apply_learn(sess)

    if auto:
        return applied  # the /auto loop decides what to run next

    # next-step hints
    suggestion, offer = None, None
    if has_py:
        suggestion = py_run_name() + " " + _entry_py(applied)
        offer = "run"
    elif has_js and shutil.which("node"):
        suggestion = "node " + _entry_js(applied)
        offer = "run"
    elif has_html:
        print(c(C.D, "Preview your site:  /serve   then open http://localhost:8000"))
        run_now = ask("Start the preview server now? [y/N]: ").strip().lower()
        if run_now in ("y", "yes"):
            cmd_serve(sess, "")
        return applied
    if suggestion:
        print(c(C.D, "Run suggestion: " + suggestion))
        if offer == "run":
            run_now = ask("Run it now? [y/N]: ").strip().lower()
            if run_now in ("y", "yes"):
                run_command(sess, suggestion)
    return applied

# --------------------------------------------------------------- web approval flow
MAX_PENDING_AGE = 600   # seconds a staged "changes" batch stays valid


def stage_pending_changes(sess, plans, eplans, edits):
    """Confirm-changes mode (web face): DO NOT write anything. Stage the
    whole batch, push it to the browser as a structured 'changes' event
    (diffs + per-hunk previews) and wait for POST /api/apply. Returns []
    (nothing applied yet - the caller sees an empty result)."""
    if diffview is None:
        return []
    bid = "p" + str(int(time.time() * 1000))
    files_payload = []
    for name, body, target in plans:
        kind = "overwrite" if target.exists() else "new"
        diff_lines = []
        if kind == "overwrite":
            try:
                old = target.read_text(encoding="utf-8", errors="replace")
                diff_lines = diffview.unified_diff(name, old, body, max_lines=70)
            except OSError:
                diff_lines = ["(cannot read the current file for a diff)"]
        else:
            diff_lines = diffview.new_file_preview(name, body, max_lines=14)
        files_payload.append({"name": name, "kind": kind,
                              "lines": body.count("\n") + 1,
                              "diff": diff_lines[:90]})
    merged = {}
    for path, hunks in (edits or []):
        merged.setdefault(path, []).extend(hunks)
    edits_payload, staged = [], {}
    for path, hunks in merged.items():
        if not hunks:
            continue
        try:
            target = safe_join(sess.ws, path)
            original = target.read_text(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue
        entries = []
        for i, (s, r) in enumerate(hunks, 1):
            lines, ok = diffview.hunk_preview(original, s, r)
            entries.append({"i": i, "valid": ok, "preview": lines[:16]})
        staged[path] = hunks
        edits_payload.append({"name": path, "hunks": entries})
    sess.pending_apply = {"id": bid, "plans": list(plans), "hunks": staged,
                          "ts": time.time()}
    emit_event({"t": "changes", "id": bid, "files": files_payload,
                "edits": edits_payload})
    print(c(C.Y, "[changes] waiting for your approval in the panel "
                 "(nothing is written yet)"))
    return []


def apply_approved(sess, batch_id, keep_files, hunks_map):
    """Apply exactly what the user approved from a staged batch:
    keep_files = [name] of the === FILE: === blocks to write,
    hunks_map  = {path: [hunk numbers]} of the === EDIT: === hunks.
    Hunks are RE-VALIDATED against the file content at this moment (the
    file may have changed since staging) - invalid hunks are reported,
    not applied. After writing: snapshot unit, git auto-commit and the
    quality gate run exactly like a normal apply. Returns (ok, result)."""
    pend = getattr(sess, "pending_apply", None)
    if not pend or pend.get("id") != str(batch_id):
        return (False, {"error": "no matching pending batch (already applied or expired)"})
    if time.time() - pend.get("ts", 0) > MAX_PENDING_AGE:
        sess.pending_apply = None
        return (False, {"error": "the staged batch expired - ask Nova again"})
    keep = {str(x) for x in (keep_files or [])}
    plans = [p for p in pend.get("plans", []) if p[0] in keep]
    # v6.8.1 fix: the web approval path bypassed offer_apply's pre-apply
    # lint gate - a syntax-broken file the user approved from the browser
    # reached the disk. Same atomic rule here: one bad file aborts ALL.
    # v8.7: re-validate the EDIT hunks ONCE and keep the merged bodies -
    # every pre-apply gate (lint / guardian / probe) needs them.
    merged_map = {}
    for path, idxs in (hunks_map or {}).items():
        staged = pend.get("hunks", {}).get(path) or []
        want = [staged[i - 1] for i in (idxs or [])
                if isinstance(i, int) and 0 < i <= len(staged)]
        if not want:
            continue
        try:
            cur = safe_join(sess.ws, path).read_text(encoding="utf-8",
                                                     errors="replace")
            merged, _ap, _pr = diffview.apply_hunks(cur, want)
            merged_map[path] = merged
        except (ValueError, OSError):
            continue
    if quality is not None:
        lint_rejects = []
        for name, body, target in plans:
            ok, problem = quality.preapply_check(name, body)
            if not ok:
                lint_rejects.append(f"{name}: {problem}")
        for path, merged in merged_map.items():
            ok, problem = quality.preapply_check(path, merged)
            if not ok:
                lint_rejects.append(f"{path}: {problem}")
        if lint_rejects:
            return (False, {"error": "pre-apply check failed - nothing written",
                            "details": lint_rejects})
    # v8.7: the same web-shaped hole existed for the v8.4 guardian fleet
    # and the v8.5 wiring probe - a batch the user approved in the
    # browser never met their gates (the terminal path runs both in
    # offer_apply). Reject = zero bytes, the same atomic law.
    # v8.12: the master switch is checked too - a guardian the user
    # turned OFF (env kill-switch or panel toggle) must not block the
    # web Approve button when the same batch applies fine in the
    # terminal (the probe gate below already did this).
    if guardian is not None and _guardian_master_on(sess) \
            and (plans or merged_map):
        try:
            gset = getattr(sess, "guardian_settings", None) or {}
            grep = guardian.review_batch(
                [(n, b) for n, b, _t in plans],
                chat_fn=None,                       # pre-apply: deterministic
                cfg={"model": False, "web": False,
                     "reject_syntax": guardian.enabled(gset, "reject_syntax")},
                edit_bodies=list(merged_map.items()))
            if grep.get("rejects"):
                return (False, {
                    "error": "the code-guardian gate refused the batch "
                             "- nothing written",
                    "details": ["%s: %s" % (
                        d.get("file", "?"),
                        (d.get("errors") or [(0, "?")])[0][1])
                        for d in grep["rejects"]]})
        except Exception:
            pass                       # the guardian never breaks an apply
    if probe is not None and _probe_master_on(sess):
        try:
            pset = getattr(sess, "probe_settings", None) or {}
            # v8.12: the deep sweep joins the gate trigger - a user who
            # turned wiring off but deep on still gets the pre-apply
            # gate (deep alone used to be silently post-apply-only).
            if probe.enabled(pset, "wiring") or probe.enabled(pset, "deep"):
                prep = probe.pre_apply_gate(
                    [(n, b) for n, b, _t in plans] +
                    list(merged_map.items()),
                    ws=sess.ws, cfg=pset)
                if prep.get("reject"):
                    return (False, {
                        "error": "the bug-hunter gate refused the "
                                 "batch - nothing written",
                        "details": ["%s:%s: %s" % (rel, line or "?", msg)
                                    for rel, line, msg
                                    in prep.get("errors", [])[:12]]})
        except Exception:
            pass                       # the hunter never breaks an apply
    sess.last_batch = []
    snap_batch = []
    applied = []
    results = {"applied": [], "errors": [], "skipped": []}
    # v6.9: the web approval path now runs the SAME atomic transaction as
    # offer_apply - a mid-batch write failure used to leave file 1 written
    # and the rest missing (the half-applied batch the v6.8 note calls
    # worse than none). Journal BEFORE open (a truncated write must roll
    # back too), restore on the first failure.
    tx_journal = []
    touched_before = {name: sess.touched.get(name) for name, _b, _t in plans}
    for path in (hunks_map or {}):
        touched_before.setdefault(path, sess.touched.get(path))

    def _rollback():
        for rtarget, rexisted, rbk in reversed(tx_journal):
            try:
                if rexisted and rbk is not None and rbk.exists():
                    shutil.copy2(rbk, rtarget)
                elif not rexisted and rtarget.exists():
                    rtarget.unlink()
            except OSError as e:
                print(c(C.R, f"  [rollback] {rtarget.name}: {e}"))

    for name, body, target in plans:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            bk = backup_file(sess, target) if existed else None
            tx_journal.append((target, existed, bk))
            if bk:
                sess.last_batch.append((target, bk))
            snap_batch.append((target, bk))
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
        except (OSError, ValueError) as e:
            results["errors"].append(f"{name}: {e}")
            snap_batch = [b for b in snap_batch if b[0] != target]
            sess.last_batch = [(t, b) for t, b in sess.last_batch
                               if t != target]
            print(c(C.R, f"  [!] {name}: cannot write ({e}) - ROLLING BACK "
                         "the approved batch (atomic transaction)"))
            _rollback()
            # v7.1.0: restore the PRE-batch touched records (a plain pop()
            # erased an earlier apply's new/modified classification)
            for n2 in applied:
                old = touched_before.get(n2)
                if old is None:
                    sess.touched.pop(n2, None)
                else:
                    sess.touched[n2] = old
            emit_event({"t": "tx_aborted", "file": name, "error": str(e)})
            results["errors"].append("batch rolled back - nothing applied")
            sess.pending_apply = None
            # ok=True so the browser panel still receives the FULL result
            # (applied=[] + the errors) instead of a bare error string
            return (True, results)
        applied.append(name)
        sess.touched[name] = "modified" if existed else "new"
    for path, idxs in (hunks_map or {}).items():
        staged = pend.get("hunks", {}).get(path)
        if not staged:
            results["errors"].append(f"{path}: no staged edit")
            continue
        want = [staged[i - 1] for i in (idxs or [])
                if isinstance(i, int) and 0 < i <= len(staged)]
        if not want:
            results["skipped"].append(path)
            continue
        try:
            target = safe_join(sess.ws, path)
            # v8.0: sandbox twin-check at apply time (defense in depth -
            # the plan may have been staged before a config change)
            if sandbox is not None:
                ok_s, why_s = sandbox.check_path(sess.ws, target,
                                                 write=True)
                if not ok_s:
                    results["errors"].append(f"{path}: {why_s}")
                    results["skipped"].append(path)
                    continue
            original = target.read_text(encoding="utf-8",
                                         errors="replace")
        except (ValueError, OSError) as e:
            results["errors"].append(f"{path}: {e}")
            continue
        text, applied_h, problems = (diffview.apply_hunks(original, want)
                                     if diffview else (original, [], []))
        for j, reason in problems:
            results["errors"].append(f"{path} hunk {j}: {reason}")
        if not applied_h:
            continue
        try:
            bk = backup_file(sess, target)
            tx_journal.append((target, True, bk))
            sess.last_batch.append((target, bk))
            snap_batch.append((target, bk))
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except (OSError, ValueError) as e:
            # v7.1.0 fix: the EDIT write path now runs the SAME atomic
            # rollback as the FILE path - a failed write here used to leave
            # a TRUNCATED file on disk (open() already cut it) and the rest
            # of the batch (snapshot + git) then committed that state.
            results["errors"].append(f"{path}: {e}")
            snap_batch = [b for b in snap_batch if b[0] != target]
            sess.last_batch = [(t, b) for t, b in sess.last_batch
                               if t != target]
            print(c(C.R, f"  [!] {path}: cannot write the edit ({e}) - "
                         "ROLLING BACK the approved batch (atomic transaction)"))
            _rollback()
            for n2 in applied:
                old = touched_before.get(n2)
                if old is None:
                    sess.touched.pop(n2, None)
                else:
                    sess.touched[n2] = old
            emit_event({"t": "tx_aborted", "file": path, "error": str(e)})
            results["errors"].append("batch rolled back - nothing applied")
            sess.pending_apply = None
            return (True, results)
        applied.append(path)
        sess.touched[path] = "modified"
    if applied:
        # v7.0: same beauty floor as offer_apply, BEFORE the snapshot push
        _design_polish_hook(sess, applied, snap_batch)
        # v7.2: same real-photo pass (extras join the same snapshot unit)
        _image_fill_hook(sess, applied, snap_batch)
        # v7.3: same font-library pass (extras join the same snapshot unit)
        _font_install_hook(sess, applied, snap_batch)
        sess.rescan(silent=True)
        if snaps is not None and snap_batch:
            snaps.push_auto_unit(sess.ws, snap_batch, note="web-approved batch")
        if commitmsg is not None and commitmsg.is_repo(sess.ws):
            _git_autocommit(sess, applied)
        _feedback_gate(sess, applied, auto=True)
    sess.pending_apply = None
    results["applied"] = applied
    return (True, results)


def _design_polish_hook(sess, applied, snap_batch):
    """v7.0 DESIGN ENGINE hook, shared by offer_apply + apply_approved.
    Runs nova_design.design_polish AFTER the atomic transaction: polishes
    the just-written HTML files in place and writes the floor stylesheets.
    Extras join the SAME undo unit / snapshot / touched map as the batch,
    so /undo and the web 'changed files' chips stay exactly right.
    v7.2: the floor is palette-stamped with a hash of the user's own
    request (sess.last_request) - every project gets its own look.
    Fail-soft everywhere: a polish problem can never fail an apply."""
    if design is None or not applied:
        return
    try:
        extras, notes = design.design_polish(
            sess.ws, applied, seed=getattr(sess, "last_request", None) or None)
    except Exception as e:
        print(c(C.Y, "[design] polish skipped: " + str(e)[:120]))
        return
    for note in notes:
        print(c(C.G, "[design] " + note))
    for rel, content in extras:
        try:
            target = safe_join(sess.ws, rel)
        except ValueError as e:
            print(c(C.Y, "[design] skip " + rel + ": " + str(e)[:100]))
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            bk = backup_file(sess, target) if existed else None
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            if bk:
                sess.last_batch.append((target, bk))
            snap_batch.append((target, bk))
            applied.append(rel)
            sess.touched[rel] = "modified" if existed else "new"
            print(c(C.G, "  + " + rel + " [Nova design floor]"))
        except OSError as e:
            print(c(C.Y, "[design] cannot write " + rel + ": " + str(e)[:100]))


def _image_fill_hook(sess, applied, snap_batch):
    """v7.2 IMAGES hook, shared by offer_apply + apply_approved.
    Runs nova_images.fill_html_images AFTER the atomic transaction: every
    <img> in the just-applied pages gets a real, downloaded photo (or, if
    the internet cannot provide one, a generated local art placeholder) -
    a built site never shows a broken image. Downloaded assets join the
    SAME undo unit / snapshot / touched map as the batch, exactly like
    the design-floor extras. Fail-soft everywhere."""
    if imgsys is None or not applied:
        return
    try:
        extras, notes = imgsys.fill_html_images(sess.ws, applied)
    except Exception as e:
        print(c(C.Y, "[img] fill skipped: " + str(e)[:120]))
        return
    for note in notes:
        print(c(C.G, note))
    for rel, data in extras:
        try:
            target = safe_join(sess.ws, rel)
        except ValueError as e:
            print(c(C.Y, "[img] skip " + rel + ": " + str(e)[:100]))
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # fill_html_images creates these files DURING the pass itself,
            # so an extra is ALWAYS a new asset: backing it up here would
            # snapshot the just-fetched bytes and /undo would then RESTORE
            # the photo instead of deleting it (the orphan-forever bug).
            with open(target, "wb") as fh:
                fh.write(data)
            snap_batch.append((target, None))
            applied.append(rel)
            sess.touched[rel] = "new"
            print(c(C.G, "  + " + rel + " [Nova images]"))
        except OSError as e:
            print(c(C.Y, "[img] cannot write " + rel + ": " + str(e)[:100]))


def _font_install_hook(sess, applied, snap_batch):
    """v7.3 FONTS hook, shared by offer_apply + apply_approved.
    Runs nova_fonts.install_pass AFTER the images pass: copies the needed
    local woff2 fonts into <ws>/fonts/, writes/links nova-fonts.css and
    adds dir="rtl" to Persian pages. Extras join the SAME undo unit /
    snapshot / touched map as the batch:
      - bytes extras (woff2) are ALWAYS-new assets -> image-hook rules
        (no backup - backing them up would snapshot the just-copied bytes
        and /undo would RESTORE the file instead of deleting it)
      - text extras (nova-fonts.css) may OVERWRITE an earlier Nova sheet
        -> design-hook rules (backup first, so /undo restores the old one)
    v7.4 audit fix: a file the MODEL's own batch just wrote is never
    touched (the double undo-entry used to resurrect it on /undo), and
    install_pass never overwrites a foreign file at a library path.
    Fail-soft everywhere: a font problem can never fail an apply."""
    if fontsys is None or not applied:
        return
    batch_rels = set(applied)          # the model's own files this apply
    try:
        extras, notes = fontsys.install_pass(
            sess.ws, applied,
            request_text=getattr(sess, "last_request", None) or None)
    except Exception as e:
        print(c(C.Y, "[fonts] pass skipped: " + str(e)[:120]))
        return
    for note in notes:
        print(c(C.G, "[fonts] " + note))
    for rel, data in extras:
        if rel in batch_rels:
            continue                   # the model owns this file - hands off
        try:
            target = safe_join(sess.ws, rel)
        except ValueError as e:
            print(c(C.Y, "[fonts] skip " + rel + ": " + str(e)[:100]))
            continue
        try:
            is_bytes = isinstance(data, (bytes, bytearray))
            existed = target.exists()
            if is_bytes:
                if existed:
                    # a foreign file at a library path - install_pass now
                    # filters it, this is belt-and-suspenders: never turn
                    # the user's file into a Nova "new" asset
                    continue
                # always-new asset: /undo deletes it via bk=None
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "wb") as fh:
                    fh.write(data)
                snap_batch.append((target, None))
                sess.touched[rel] = "new"
                applied.append(rel)
                print(c(C.G, "  + " + rel + " [Nova fonts]"))
            else:
                bk = backup_file(sess, target) if existed else None
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(data)
                if bk:
                    sess.last_batch.append((target, bk))
                snap_batch.append((target, bk))
                sess.touched[rel] = "modified" if existed else "new"
                applied.append(rel)
                print(c(C.G, "  + " + rel + " [Nova fonts]"))
        except OSError as e:
            print(c(C.Y, "[fonts] cannot write " + rel + ": " + str(e)[:100]))


def _diff_review(sess, plans, eplans, edits):
    """The 'd(iff)' apply path: colored unified diff per FILE block and an
    approve/reject decision per HUNK for every === EDIT: === block.
    Returns the filtered (plans, eplans) - each entry carries its final
    approved content, re-validated against the current file state."""
    if diffview is None:
        print(c(C.Y, "[!] diff review unavailable (nova_diffview.py missing)"))
        return (plans, eplans)
    color_fn = (lambda code, text: c(code, text)) if USE_COLOR else None
    print(c(C.B, "\n=== diff review (approve what you want) ==="))
    keep_plans = []
    for name, body, target in plans:
        print("")
        if target.exists():
            try:
                old = target.read_text(encoding="utf-8", errors="replace")
                print(diffview.paint(diffview.unified_diff(name, old, body), color_fn))
            except OSError:
                print(diffview.new_file_preview(name, body))
        else:
            print(diffview.paint(diffview.new_file_preview(name, body), color_fn))
        if (ask(f"Include {name}? [Y/n]: ").strip().lower()) not in ("n", "no"):
            keep_plans.append((name, body, target))
    keep_eplans = []
    # merge the raw hunks per RESOLVED path (the SAME rule prepare_edits
    # uses) so the review works on the ORIGINAL text with per-hunk
    # granularity. v7.14.1 fix: merging by RAW path meant two spellings
    # of one file ("app.py" + "./app.py") produced one eplan (all hunks)
    # but only the first spelling's hunks were reviewed - the approved
    # apply then wrote the reviewed subset and the second spelling's
    # edits vanished without any message.
    merged, display = {}, {}
    for path, hunks in (edits or []):
        try:
            key = str(safe_join(sess.ws, path).resolve())
        except ValueError:
            key = str(path)
        merged.setdefault(key, [])
        merged[key].extend(hunks)
        display.setdefault(key, path)
    eplan_keys = set()
    for e in eplans:
        try:
            eplan_keys.add(str(Path(e[1]).resolve()))
        except Exception:
            eplan_keys.add(str(e[0]))
    for key, hunks in merged.items():
        if key not in eplan_keys or not hunks:
            continue
        name = display.get(key, key)
        target = Path(key)
        try:
            original = target.read_text(encoding="utf-8", errors="replace")
        except (ValueError, OSError) as e:
            print(c(C.R, f"[!] {name}: {e}"))
            continue
        print(c(C.B, f"\n--- {name}: {len(hunks)} hunk(s) ---"))
        accepted, notes, final_text = diffview.review_hunks(
            original, hunks, ask_fn=ask, print_fn=lambda s: print(s),
            color_fn=color_fn)
        for note in notes:
            print(c(C.Y, "  (" + note + ")"))
        if accepted:
            keep_eplans.append((name, target, len(accepted), final_text))
    return (keep_plans, keep_eplans)


def _git_autocommit(sess, applied):
    """GIT-NATIVE COMMIT-PER-EDIT (v6.8): every applied file becomes its
    OWN commit with a descriptive message - the model's multi-file batch
    lands as N reviewable commits, not one opaque blob. Messages combine
    the heuristic summary with the AST symbol diff for .py edits
    (zero model calls). Never pushes; best effort."""
    try:
        err = commitmsg.ensure_excludes(sess.ws)
        if err:
            print(c(C.Y, "[git] exclude setup failed: " + err))
        committed = 0
        for name in applied:
            new_files = [n for n in applied
                         if n == name and sess.touched.get(n) == "new"]
            ed_files = [n for n in applied
                        if n == name and sess.touched.get(n) == "modified"]
            msg = commitmsg.heuristic_message("", sess.last_request,
                                              new_files, ed_files)
            # AST-aware suffix: "edited run_command, parse_files" beats a
            # generic "modified file.py" in the log
            if astmap is not None and name.lower().endswith(".py"):
                try:
                    target = safe_join(sess.ws, name)
                    old = ""
                    for t, bk in sess.last_batch:
                        if t.resolve() == target.resolve() and bk and bk.exists():
                            old = bk.read_text(encoding="utf-8",
                                               errors="replace")
                            break
                    cur = target.read_text(encoding="utf-8", errors="replace")
                    detail = astmap.change_summary(old, cur)
                    if detail:
                        msg = f"{msg} ({detail})"
                except Exception:
                    pass
            ok, detail = commitmsg.auto_commit(sess.ws, msg,
                                               [str(sess.ws / name)])
            if ok:
                committed += 1
            elif detail and detail not in ("nothing to commit",):
                print(c(C.Y, f"[git] {name}: auto-commit skipped: " + detail))
        if committed:
            print(c(C.D, f"  (git: {committed} commit(s), one per file - "
                         "git log to review)"))
    except Exception as e:
        print(c(C.Y, "[git] auto-commit failed: " + str(e)))


def _nova_history_commit(sess, applied):
    """v7.5 COMMIT-PER-EDIT for workspaces that are NOT git repos: the
    Nova-managed history repo (.nova/history.git) takes one commit per
    applied file with the same descriptive messages as _git_autocommit.
    Zero user config (the repo has its own identity), zero project
    pollution (git-dir lives under .nova). Best effort, fail-soft."""
    try:
        committed = 0
        for name in applied:
            new_files = [n for n in applied
                         if n == name and sess.touched.get(n) == "new"]
            ed_files = [n for n in applied
                        if n == name and sess.touched.get(n) == "modified"]
            msg = commitmsg.heuristic_message("", sess.last_request,
                                              new_files, ed_files)
            ok, detail = commitmsg.nova_auto_commit(
                sess.ws, msg, [str(sess.ws / name)])
            if ok:
                committed += 1
            elif detail and detail not in ("nothing to commit",):
                print(c(C.Y, f"[git] {name}: history commit skipped: " + detail))
        if committed:
            print(c(C.D, f"  (history: {committed} commit(s) saved in "
                         ".nova/history.git - /gitlog to review)"))
    except Exception as e:
        print(c(C.Y, "[git] history commit failed: " + str(e)))


def _feedback_gate(sess, applied, auto=False):
    """Run the post-apply quality gate: syntax checks on the touched
    files, optional installed linters, and (when /autotest is on) one
    detected test command. Terminal: compact report. auto loops: the
    problems land in sess.last_feedback for the next fix round."""
    sess.last_feedback = None
    if not applied or feedback is None:
        return
    syntax = feedback.check_files(sess.ws, applied)
    lint = []
    try:
        lint = feedback.optional_lint(sess.ws, applied)
    except Exception:
        lint = []
    test_res = None
    if sess.autotest:
        try:
            test_res = feedback.run_tests(sess.ws)
        except Exception as e:
            test_res = {"ok": True, "cmd": None, "report": f"(test runner failed: {e})"}
    sess.last_feedback = {"syntax": syntax, "lint": lint, "tests": test_res}
    # ---- v8.4: THE CODE GUARDIAN - the fleet's post-apply review -------
    # The deterministic gate already refused the unparseable. Here the
    # SUPERVISOR dispatches the language sub-sub-agents (parallel, LOCAL
    # brain only, budgeted) over the touched files; semantic findings
    # (undefined names, wrong API use, logic slips) land in
    # last_feedback["guardian"] so the NEXT fix round sees them. Fail-
    # soft end to end: a missing brain/credit-less cloud/any error =
    # no review, the pipeline stays exactly as before.
    if guardian is not None and _guardian_master_on(sess):
        try:
            gset = getattr(sess, "guardian_settings", None) or {}
            if syntax:
                pass          # syntax problems already feed the next round
            else:
                grev = guardian.review_batch(
                    [(n, _read_ws_file(sess, n)) for n in applied[:4]],
                    chat_fn=_guardian_chat_fn(sess) if guardian.enabled(
                        gset, "model") else None,
                    cfg=gset,
                    web_on=guardian.enabled(gset, "web"))
                g_find = grev.get("agents") or []
                g_flat = [(a["file"], ln, msg)
                          for a in g_find for ln, msg in
                          (a.get("findings") or [])]
                if g_flat:
                    sess.last_feedback["guardian"] = g_flat
                    for fname, ln, msg in g_flat[:6]:
                        print(c(C.Y, "[guardian] %s: %s" %
                                     (fname, ("line %s: " % ln) if ln else "")
                                     + msg))
                    print(c(C.D, "  (fleet review - the next fix round "
                                 "gets these)"))
                emit_event({"t": "guardian",
                            "findings": g_flat[:12],
                            "online": bool(grev.get("online")),
                            "model": bool(grev.get("model_used")),
                            "verdict": grev.get("verdict")})
                if flightlog is not None:
                    try:
                        flightlog.log("guardian.review",
                                      "fleet post-apply review",
                                      files=", ".join(applied[:6]),
                                      findings=len(g_flat),
                                      model=str(bool(grev.get(
                                          "model_used"))))
                    except Exception:
                        pass
        except Exception:
            pass                       # the guardian never breaks the gate
    # ---- v8.5: THE BUG HUNTER - the behavior sweep ----------------------
    # Syntax is green; now the BEHAVIOR probes: the wiring sweep over
    # the real workspace, smoke runs of the fresh entry scripts (tight
    # timeout, sandbox honored), the headless browser console truth when
    # Playwright exists, and the completeness review against the user's
    # request (local brain only). Findings land in
    # last_feedback["probe"] so the NEXT fix round sees them. Fail-soft
    # end to end - the hunter can never break the gate.
    if probe is not None and _probe_master_on(sess):
        try:
            pset = getattr(sess, "probe_settings", None) or {}
            prep = probe.run_post_apply(
                sess.ws, applied,
                request=getattr(sess, "last_request", "") or "",
                chat_fn=_probe_chat_fn(sess)
                if probe.enabled(pset, "review") else None,
                cfg=pset)
            flat = [(f, l, m) for f, l, m, _lv in prep.get("findings", [])]
            if flat:
                sess.last_feedback["probe"] = flat
            for lv, text in probe.report_lines(prep, max_lines=6):
                print(c(C.Y if lv == "warn" else C.R, "[hunter] " + text))
            if flat:
                print(c(C.D, "  (behavior sweep verdict: %s - the next "
                             "fix round gets these)" % prep["verdict"]))
            elif prep.get("verdict") == "pass":
                print(c(C.D, "[hunter] behavior sweep clean (wiring + "
                             "smoke%s)" % (" + browser" if (prep.get(
                                 "browser") or {}).get("ran") else "")))
            emit_event({"t": "probe", "verdict": prep.get("verdict"),
                        "findings": flat[:12],
                        "clicks": (prep.get("browser") or {}).get(
                            "clicks", 0) or 0,
                        "smoke_runs": (prep.get("smoke") or {}).get(
                            "ran", 0) or 0})
            if flightlog is not None:
                try:
                    flightlog.log("probe.sweep", "behavior sweep after "
                                  "apply", files=", ".join(applied[:6]),
                                  verdict=str(prep.get("verdict")),
                                  findings=len(flat))
                except Exception:
                    pass
        except Exception:
            pass                       # the hunter never breaks the gate
    # ---- report ---------------------------------------------------------
    if syntax:
        for rel, problem in syntax:
            print(c(C.R, f"[check] {rel}: {problem}"))
    else:
        print(c(C.D, f"[check] syntax OK ({len(applied)} file(s))"))
    for tag, problem in lint:
        print(c(C.Y, f"[{tag}] {problem}"))
    if test_res and test_res.get("cmd"):
        rep = test_res["report"]
        print(c(C.G if test_res.get("ok") else C.R, "[tests] " + rep))
        if not test_res.get("ok") and test_res.get("tail"):
            print(c(C.D, "  " + (test_res["tail"].replace("\n", "\n  "))[:800]))
        elif not test_res.get("ok"):
            print(c(C.D, "  (fix: /fix after a /run, or read the tail above)"))
    elif test_res is not None and not test_res.get("cmd"):
        pass  # no test setup - stay quiet
    emit_event({"t": "feedback", "syntax": syntax, "lint": lint,
                "tests": {k: test_res.get(k) for k in ("ok", "cmd", "report")}
                if test_res else None})
    # v8.0: the black box records the apply decision
    if flightlog is not None:
        try:
            flightlog.log("apply.batch", "%d file(s) applied" % len(applied),
                          files=", ".join(applied[:6]),
                          syntax=len(syntax), lint=len(lint),
                          tests=(test_res or {}).get("cmd") or "")
        except Exception:
            pass
    _intel_gate(sess, applied)


def _intel_gate(sess, applied):
    """v7.13: the intelligence layer observes every apply batch -
    refresh the project scan, warn about the impact radius, score the
    batch with the staged critic, keep the regression baseline honest,
    remember the event in the semantic memory and mirror the live
    agent status. EVERY step is fail-soft: the intel layer must never
    break the apply pipeline (this hook runs inside the user's real
    coding loop)."""
    if intel is None or not applied:
        return
    try:
        ws = Path(sess.ws)
        # 1) impact analysis (cheap fingerprint refresh happens inside)
        imp = {}
        try:
            imp = intel.ImpactAnalyzer(ws).analyze(applied)
        except Exception:
            imp = {}
        if imp.get("affected"):
            print(c(C.Y, "[impact] %d file(s) import what just changed: %s"
                        % (len(imp["affected"]),
                           ", ".join(imp["affected"][:5]))))
            print(c(C.D, "         (/impact %s shows the full radius)"
                        % applied[0]))
        # 2) the staged critic on this batch
        fbk = getattr(sess, "last_feedback", None) or {}
        crep = None
        try:
            crep = intel.Critic.review({
                "files": applied, "syntax": fbk.get("syntax") or [],
                "lint": fbk.get("lint") or [], "impact": imp,
                "tests": fbk.get("tests")})
            if crep["verdict"] == "rollback":
                print(c(C.R, intel.Critic.text_report({
                    "files": applied, "syntax": fbk.get("syntax") or [],
                    "lint": fbk.get("lint") or [], "impact": imp,
                    "tests": fbk.get("tests")}).split("\n", 1)[-1]))
                print(c(C.Y, "[critic] syntax AND tests broken - /undo "
                             "restores the last snapshot"))
            else:
                print(c(C.G if crep["verdict"] == "ship" else C.Y,
                        "[critic] score %d/100 -> %s"
                        % (crep["score"], crep["verdict"])))
        except Exception:
            crep = None
        # 3) regression bookkeeping - REUSE the gate's own test result
        #    (never run the suite twice), first green run = the baseline
        reg = None
        try:
            rd = intel.RegressionDetector(
                ws, runner=lambda: fbk.get("tests") or {})
            if not intel.load_json(rd.path, {}):
                rd.baseline()
            elif fbk.get("tests"):
                reg = rd.check()
                if reg.get("verdict") == "new-fail":
                    print(c(C.R, "[regress] REGRESSION: the suite was "
                                 "green and now fails"))
                elif reg.get("verdict") == "fixed":
                    print(c(C.G, "[regress] suite green again - "
                                 "baseline updated"))
        except Exception:
            reg = None
        # 4) remember the batch in the semantic memory
        try:
            mem = intel.SemanticMemory(ws / ".nova" / "memory_vec.json")
            mem.remember("applied batch: %s (critic: %s)"
                         % (", ".join(applied[:8]),
                            crep["verdict"] if crep else "?"),
                         kind="event", tags=["apply"])
            if reg and reg.get("verdict") == "new-fail":
                mem.remember("regression appeared after applying %s"
                             % ", ".join(applied[:5]),
                             kind="decision", tags=["regression"])
        except Exception:
            pass
        # 5) live agent status for the dashboard
        try:
            intel.AgentStatus(ws).set(
                phase="verify",
                tested=intel.CompletionDetector.summarize({
                    "lint_ok": not (fbk.get("syntax") or []),
                    "tests_ok": (fbk.get("tests") or {}).get("ok")}),
                event="applied: %s%s" % (
                    ", ".join(applied[:5]) or "(none)",
                    " -> critic %s" % crep["verdict"] if crep else ""))
        except Exception:
            pass
        emit_event({"t": "intel", "critic": crep, "impact": imp,
                    "regression": (reg or {}).get("verdict")})
    except Exception:
        pass  # the intelligence layer must never kill a real turn


def _default_run_cmd(applied):
    """v6.9: a sensible verify command when the model forgot its 'Run:'
    line (small models do) - mirrors offer_apply's REPL suggestion so
    the web Run button still appears and the auto loops still have a
    command to verify with. "" = nothing safe to guess (e.g. html-only
    projects are previewed with /serve, never "run")."""
    has_py = any(a.lower().endswith(".py") for a in applied)
    has_js = any(a.lower().endswith(".js") for a in applied)
    if has_py:
        return py_run_name() + " " + _entry_py(applied)
    if has_js and shutil.which("node"):
        return "node " + _entry_js(applied)
    return ""


def _entry_py(applied):
    for cand in ("main.py", "app.py", "run.py"):
        if cand in applied:
            return cand
    return next(a for a in applied if a.lower().endswith(".py"))

def _entry_js(applied):
    for cand in ("main.js", "index.js", "app.js"):
        if cand in applied:
            return cand
    return next(a for a in applied if a.lower().endswith(".js"))

# --------------------------------------------------------------- run & debug
def _kill_tree(proc):
    """Kill a process AND everything it spawned (shell children keep pipes
    open - killing only the shell can leave orphans running for ever)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _drain(pipe, cap, buf):
    """Reader thread: capture up to `cap` chars, keep READING to EOF but
    discard the excess. This bounds RAM on a 4 GB machine even when a
    runaway program prints gigabytes, without changing program behavior."""
    total = 0
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            if total < cap:
                room = cap - total
                keep = chunk if len(chunk) <= room else chunk[:room]
                buf.append(keep)
                total += len(keep)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


# ---------------------------------------------------- v8.8: PRE-RUN GATE
# The user's report: "I press Run and only THEN a syntax error appears".
# The apply-time gates (lint / guardian / probe) protect files as they are
# WRITTEN - but a Run command may target files that were never gated (an
# older session, a manual edit, an untouched support module). From 8.8 the
# entry files a command names (+ their local import closure) are syntax
# checked BEFORE the shell ever sees the command; a file that cannot parse
# is never executed - the exact errors go to the fix machinery instead.
PRERUN_EXIT = -2                 # "the pre-run gate refused this command"
PRERUN_FILE_CAP = 12             # max files scanned in one gate pass
PRERUN_FILE_BYTES = 1_000_000    # per-file read cap (beyond = skipped, fail-open)
# Only syntaxes whose breakage CRASHES a run: executable code. HTML/CSS/
# JSON are deliberately out - they are rendered/data files; a broken tag
# never raises SyntaxError in a shell run, and gating them would refuse
# legitimate commands (a build script fed a template, an output path that
# will be overwritten anyway). The apply-time gates already guard those
# types when the model writes them.
_PRERUN_CODE_RE = re.compile(
    r"[\w./\\-]+\.(?:py|js|mjs|cjs)\b", re.IGNORECASE)
# A segment is gated only when an INTERPRETER leads it - 'python main.py'
# gates, 'git diff main.py' / 'cat app.js' / 'rm bad.py' must never gate.
_PRERUN_EXECUTORS = {
    "python", "python3", "py", "pypy", "pypy3",
    "node", "nodejs", "deno", "bun", "ts-node", "tsx", "pytest",
}


def _prerun_named_files(cmd):
    """Code files a command will actually EXECUTE (not merely mention).
    Compound commands are split on the shell separators; each segment is
    judged by its FIRST token (an interpreter - or a directly executed
    code file). Redirection targets are stripped first: 'python build.py
    > manifest.json' WRITES the file, it does not execute it. Fail-open
    by design: anything ambiguous is simply not gated."""
    out = []
    for seg in re.split(r"&&|\|\||;|\|", cmd or ""):
        seg = seg.strip()
        if not seg:
            continue
        head = seg.split(None, 1)[0].strip("\"'").lower()
        head = re.sub(r"\.(?:exe|cmd|bat)$", "", head)
        led = (head in _PRERUN_EXECUTORS or head.startswith("python3.")
               or bool(_PRERUN_CODE_RE.fullmatch(head.lstrip("./"))))
        if not led:
            continue
        # redirection targets are data sinks/sources, not executed syntax
        seg = re.sub(r"(?:\d?>>?|<)\s*[\w./\\-]+\.(?:py|js|mjs|cjs)\b",
                     " ", seg, flags=re.IGNORECASE)
        # v8.11: only the FIRST code file after the interpreter is
        # gated - 'python gen.py skeleton.py' executes gen.py while
        # skeleton.py is DATA on argv. (Deliberately fail-open: a
        # 'python -m pkg.mod' entry was never gated and still is not.)
        # pytest is the exception: it imports EVERY named test file.
        cap = None if head == "pytest" else 1
        seen_here = 0
        for m in _PRERUN_CODE_RE.finditer(seg):
            raw = m.group(0).strip(".").replace("\\", "/").lstrip("/")
            if raw and raw not in out:
                out.append(raw)
                seen_here += 1
                if cap is not None and seen_here >= cap:
                    break
    return out


def _prerun_candidate_files(sess, cmd):
    """Files the pre-run gate must look at, in a deterministic order:
    (1) code files the command will actually execute (interpreter-led
    segments only - see _prerun_named_files), then (2) the LOCAL import
    closure of the first named .py entry - because 'python main.py'
    crashes exactly as hard when utils.py (imported, never named) cannot
    parse. A module is followed ONLY when it resolves to a real file next
    to the importer or at the workspace root, so the stdlib and installed
    packages are never chased (no blocklist needed: the existence test is
    the filter). Bounded (PRERUN_FILE_CAP files, depth 3) and fail-soft:
    anything unresolvable is simply not followed."""
    picked = []
    seen = set()

    def add(rel):
        # normalize + workspace-contained + existing + size-capped
        rel = str(rel).replace("\\", "/").strip(".").lstrip("/")
        if not rel or rel in seen or len(picked) >= PRERUN_FILE_CAP:
            return False
        try:
            p = safe_join(sess.ws, rel)
        except ValueError:
            return False
        try:
            if not p.is_file() or p.stat().st_size > PRERUN_FILE_BYTES:
                return False
        except OSError:
            return False
        seen.add(rel)
        picked.append(rel)
        return True

    named = _prerun_named_files(cmd)
    for rel in named:
        add(rel)

    # ---- local import closure of the first named Python entry ----------
    entry_rel = next((r for r in named if r.lower().endswith(".py")), None)
    if entry_rel is None:
        return picked
    try:
        ws_root = Path(sess.ws).resolve()
        entry_p = safe_join(sess.ws, entry_rel).resolve()
    except (ValueError, OSError):
        return picked
    if ws_root not in entry_p.parents and entry_p != ws_root:
        return picked
    pending = [(entry_p, 0)]
    visited = set()

    def resolve_mod(root, dotted):
        """Existing local files for a dotted module name resolved from
        `root`: every ancestor package's __init__.py on the way (they all
        execute before the module does), then mod.py and mod/__init__.py.
        Only files that REALLY exist are returned - that existence test is
        what keeps the stdlib and installed packages out."""
        out = []
        parts = [p for p in str(dotted).replace("\\", "/").replace(".", "/")
                 .split("/") if p and p != "."]
        if not parts:
            return out
        cur_dir = Path(root)
        for part in parts[:-1]:
            cur_dir = cur_dir / part
            init = cur_dir / "__init__.py"
            try:
                if init.is_file():
                    out.append(init.resolve())
            except OSError:
                continue
        leaf = cur_dir / parts[-1]
        for cand in (leaf.with_name(leaf.name + ".py"),
                     leaf / "__init__.py"):
            try:
                if cand.is_file():
                    out.append(cand.resolve())
            except OSError:
                continue
        return out

    def add_resolved(root, dotted, depth):
        for cp in resolve_mod(root, dotted):
            if cp in visited:
                continue
            try:
                rel = cp.relative_to(ws_root).as_posix()
            except ValueError:
                continue          # resolved outside the workspace
            if add(rel):
                pending.append((cp, depth + 1))

    while pending and len(picked) < PRERUN_FILE_CAP:
        cur, depth = pending.pop(0)
        if cur in visited or depth > 3:
            continue
        visited.add(cur)
        try:
            tree = ast.parse(cur.read_text(encoding="utf-8",
                                           errors="replace")
                             [:PRERUN_FILE_BYTES])
        except Exception:
            continue          # unparseable -> preapply_check reports it
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    # absolute: try the importer's folder, then ws root
                    for base in (cur.parent, ws_root):
                        add_resolved(base, a.name, depth)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = cur.parent
                    try:
                        for _ in range(node.level - 1):
                            base = base.parent
                    except Exception:
                        continue
                    if node.module:
                        add_resolved(base, node.module, depth)
                        # 'from .pkg import mod' also executes pkg/mod.py
                        if len(picked) < PRERUN_FILE_CAP:
                            for a in node.names:
                                add_resolved(base, node.module + "/" + a.name,
                                             depth)
                    else:
                        # 'from . import utils' - the names ARE the modules
                        for a in node.names:
                            add_resolved(base, a.name, depth)
                elif node.module:
                    for base in (cur.parent, ws_root):
                        add_resolved(base, node.module, depth)
                    if depth == 0:
                        # 'from pkg import x' executes pkg/__init__ and
                        # possibly pkg/x.py - only worth following on
                        # the entry itself (bounded fan-out)
                        for a in node.names:
                            for base in (cur.parent, ws_root):
                                add_resolved(base, node.module + "/" + a.name,
                                             depth)
    return picked


def _prerun_gate(sess, cmd):
    """v8.8: the pre-run syntax gate. Deterministic, offline, fail-open.
    Returns [(rel, problem)] for every file the command would exercise
    that cannot parse - empty list = nothing to refuse. Uses the SAME
    checker the apply gate uses (quality.preapply_check), so a file that
    passes here behaves exactly like one the apply gate would have
    accepted; anything the checker is unsure about passes (the real run,
    not the gate, is the final judge)."""
    problems = []
    if quality is None:
        return problems
    try:
        files = _prerun_candidate_files(sess, cmd)
    except Exception:
        return problems
    for rel in files:
        try:
            p = safe_join(sess.ws, rel)
            body = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue            # unreadable -> let the real run report it
        try:
            ok, problem = quality.preapply_check(rel, body)
        except Exception:
            continue            # the checker itself must never block a run
        if not ok and problem:
            problems.append((rel, str(problem)))
    return problems


def run_command(sess, cmd, auto=False, origin="repl"):
    """Run a shell command inside the workspace (capped output, process-tree
    kill, generous timeout). Returns the exit code (int), None if the command
    could not start, -1 on timeout, or PRERUN_EXIT when the v8.8 pre-run
    syntax gate refused it (nothing was executed; sess.last_failed carries
    the exact per-file errors for the fix machinery). auto=True: never asks
    anything - the /auto loop handles what happens after a failure.
    origin="repl" (human typed it) or "web" (the agent's web turn proposed
    it - v6.3: screened + audited, never silently executed).
    NOTE: the workspace is only the working directory - the command runs
    with the FULL permissions of this user. It is a convenience boundary,
    not a security sandbox; review commands before running them."""
    cmd = cmd.strip()
    if not cmd:
        if sess.last_cmd:
            cmd = sess.last_cmd
            print(c(C.D, "(repeat) " + cmd))
        else:
            print(c(C.Y, "[!] no previous command. Use:  /run " + py_run_name() + " main.py"))
            return None
    if sess.explain:
        print(c(C.Y, "[explain] shell commands are blocked in explain mode "
                     "(nothing may change) - /explain off to leave"))
        return None
    # ---- v7.7: preview hints open the file, they never reach the shell ----
    # ('Preview: index.html' / 'Run: start index.html' - see preview_target)
    ptarget = preview_target(sess.ws, cmd)
    if ptarget is not None:
        if nsec is not None:
            # v7.7.1 (audit): the preview branch bypasses the security gate
            # (no shell runs) - still leave the same audit trail every
            # other execution path leaves
            try:
                nsec.audit(sess.ws, "preview", cmd, origin=origin,
                           verdict="allow", reason="document preview open")
            except Exception:
                pass
        if ptarget.is_file():
            print(c(C.G, "[preview] opening " + ptarget.name + " in your browser..."))
            open_browser(ptarget.resolve().as_uri())
            sess.last_cmd = cmd
            # v8.11: a successful preview IS the green verdict for the
            # loops - the old path returned 0 while the previous run's
            # last_failed stayed alive (a later /fix then 'repaired' the
            # stale error) and the fix-round brake stayed latched
            sess.last_failed = None
            sess.fix_rounds = 0
            return 0
        print(c(C.Y, "[preview] " + cmd + " does not exist in the workspace "
                     "- nothing to open"))
        return None
    # a pure-prose hint (no latin/digit token at all - e.g. the model wrote
    # 'Run: refresh your browser page') can never be a command - do not
    # shell it, and never let its 127 feed the auto-fix loop
    if not re.search(r"[A-Za-z0-9]", cmd):
        print(c(C.Y, "[i] that Run hint is a sentence, not a command - nothing to run."))
        print(c(C.D, "    (برای دیدن سایت، جواب باید با 'Preview: index.html' تمام شود یا از /serve استفاده کنید)"))
        return None
    # ---- v6.3 security gate (BEFORE policy: deny wins over everything) ----
    if nsec is not None:
        scr = nsec.screen(cmd)
        action = nsec.decide(scr["verdict"], origin=origin, auto=auto,
                             secure=(nsec.is_secure(sess.ws) if origin == "web"
                                     else None))
        reasons = "; ".join(scr["reasons"])
        if action == "block":
            print(c(C.R, "[security] command blocked: " + reasons))
            print(c(C.D, "    cmd: " + cmd[:160]))
            nsec.audit(sess.ws, "run", cmd, origin=origin, verdict="deny",
                       reason=reasons or "policy")
            return None
        if action == "ask":
            print(c(C.Y, "[security] risky command: " + reasons))
            ans = ask("    run anyway? [y/N] ")
            if ans.strip().lower() not in ("y", "yes"):
                nsec.audit(sess.ws, "run", cmd, origin=origin,
                           verdict="deny", reason=reasons + " (user refused)")
                print(c(C.D, "    cancelled."))
                return None
        nsec.audit(sess.ws, "run", cmd, origin=origin,
                   verdict=scr["verdict"], reason=reasons)
        if scr["verdict"] == "confirm":
            print(c(C.Y, "[security] " + reasons + " - continuing (this is audited)"))
    if npol is not None:
        verdict = npol.check_command(sess.policy, cmd)
        if verdict == "deny":
            print(c(C.R, "[policy] command denied by this project's policy: " + cmd))
            print(c(C.D, "    review: /policy   (un-deny: /policy allow <pattern>)"))
            return None
    # ---- v8.8: THE PRE-RUN GATE (before the shell, after the guards) -----
    # A file that cannot parse is never handed to the shell: the user asked
    # to be SURE about syntax before a run, not to read the traceback after
    # it. The exact per-file errors ride in sess.last_failed so the auto
    # fix machinery (web autofix / auto loop / verify loop) gets one bounded
    # fix round with the real files attached - the loop the user reported
    # ('run -> error -> fix -> never done') now starts from evidence, not
    # from a crash.
    prerun = _prerun_gate(sess, cmd)
    if prerun:
        report = "\n".join("SYNTAX ERROR in %s: %s" % (rel, prob)
                           for rel, prob in prerun)
        for rel, prob in prerun:
            print(c(C.R, "[pre-run] %s: %s" % (rel, prob)))
        print(c(C.Y, "[pre-run] the command was NOT executed - "
                     "fix the syntax error(s) first"))
        print(c(C.D, "    (دروازه‌ی پیش از اجرا: ورودی این دستور خطای سینتکس دارد - "
                     "اجرا انجام نشد تا اول درست شود)"))
        emit_event({"t": "prerun_reject", "cmd": cmd[:200],
                    "errors": [{"name": rel, "problem": prob}
                               for rel, prob in prerun]})
        if flightlog is not None:
            try:
                flightlog.warn("prerun.reject",
                               "pre-run syntax gate refused the command",
                               cmd=cmd[:160],
                               files=", ".join(rel for rel, _p in prerun[:6]))
            except Exception:
                pass
        sess.last_failed = {"cmd": cmd, "code": "prerun",
                            "output": report
                            + "\n(pre-run gate: the command never ran)"}
        if not auto:
            offer_fix(sess)
        return PRERUN_EXIT
    sess.last_cmd = cmd
    # ---- v6.8: LOCAL SANDBOX (opt-in, /sandbox on) -------------------------
    # When a container runtime exists and the sandbox is on, the command
    # runs inside it: no network, RAM/CPU capped by the engine, workspace
    # bind-mounted. Nothing installed -> the classic screened path stays.
    sb_engine = None
    sb_argv = None
    sb_name = None
    if sandbox is not None:
        try:
            scfg = sandbox.load_config(sess.ws)
            if scfg.get("on"):
                sb_engine, sb_argv = sandbox.wrap(
                    sess.ws, ["bash", "-lc", cmd], cfg=scfg)
                if sb_engine is None:
                    print(c(C.Y, "[sandbox] unavailable - " + str(sb_argv)))
                    sb_engine = None
                elif sb_engine in ("docker", "podman"):
                    # v6.8.1: a named container can be KILLED on timeout -
                    # _kill_tree only kills the local CLI process; the
                    # daemon-side container would keep running forever.
                    sb_name = f"nova-{os.getpid()}-{int(time.time() * 1000)}"
                    sb_argv.insert(2, "--name")
                    sb_argv.insert(3, sb_name)
        except Exception as e:
            # v6.9: an exception used to fail OPEN silently - the command
            # then ran with full permissions although the user armed the
            # sandbox. Loud on the console; still fail-open (usable dev
            # machine) but visible.
            print(c(C.Y, "[sandbox] disabled by error: " + str(e)[:200]))
            sb_engine = None
    # ---- v6.8: CPU/RAM CEILING (not just the wall timeout) ----------------
    popen_extra, job = {}, None
    if rlimits is not None and not sb_engine:
        try:
            popen_extra, job = rlimits.popen_kwargs(
                int(sess.limits.get("cpu_s") or 0),
                int(sess.limits.get("ram_mb") or 0))
        except Exception:
            popen_extra, job = {}, None
    # ---- v6.8.3: deterministic, UTF-8 child processes ---------------------
    # stdin=DEVNULL: an interactive script (input()) used to inherit the
    # server's stdin and HANG the whole Run click until the wall timeout
    # (or crash with a confusing EOF) - now it gets a clean EOF instantly
    # and the output is screened below for a human hint.
    # PYTHONUTF8/PYTHONIOENCODING: on Windows a child printing Persian text
    # used to die with UnicodeEncodeError (cp1252 console) - the user saw
    # 'the generated code is broken' when the code was fine.
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONUTF8", "1")
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    _lim = sess.limits or {}
    _limtag = ""
    if _lim.get("cpu_s") or _lim.get("ram_mb"):
        _limtag = f", CPU<={_lim.get('cpu_s') or '∞'}s"
        if _lim.get("ram_mb"):
            _limtag += f", RAM<={_lim['ram_mb']}MB"
    if sb_engine:
        _limtag += f", sandbox: {sb_engine}"
    print(c(C.D, "\n$ " + cmd + f"   (cwd: {sess.ws}, timeout: {sess.run_timeout}s{_limtag})"))
    try:
        if sb_engine:
            proc = subprocess.Popen(
                sb_argv, cwd=str(sess.ws),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                env=child_env,
                start_new_session=(os.name != "nt"),
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
            )
        else:
            proc = subprocess.Popen(
                cmd, shell=True, cwd=str(sess.ws),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                env=child_env,
                start_new_session=(os.name != "nt"),  # own process group (POSIX)
                **popen_extra,
                # This path also runs when nova is driven from the web UI
                # (a packaged windowed .exe has no console of its own), so
                # suppress the extra cmd.exe window Windows would otherwise
                # pop up for every /run - output is already piped above.
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
            )
        if job is not None:
            job.assign(proc.pid)
    except Exception as e:
        if job is not None:
            job.close()   # v6.8.1: no kernel handle leak on a failed spawn
        print(c(C.R, "[!] failed to start: " + str(e)))
        return None
    out_buf, err_buf = [], []
    threads = [
        threading.Thread(target=_drain, args=(proc.stdout, RUN_OUTPUT_CAP, out_buf), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, RUN_OUTPUT_CAP, err_buf), daemon=True),
    ]
    for t in threads:
        t.start()
    timed_out = False
    try:
        proc.wait(timeout=sess.run_timeout)
    except KeyboardInterrupt:
        # Ctrl+C must never leak the child (and its pipes) behind the prompt
        print(c(C.Y, "\n[!] interrupted - killing the process tree..."))
        _kill_tree(proc)
        if job is not None:
            job.close()   # v6.8.1: no handle leak on Ctrl+C
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        for t in threads:
            t.join(timeout=5)
        raise
    except subprocess.TimeoutExpired:
        timed_out = True
        print(c(C.Y, f"\n[!] timeout after {sess.run_timeout}s - killing the process tree..."))
        _kill_tree(proc)
        if sb_name:
            # v6.8.1: the container lives in the daemon - kill it by name
            try:
                subprocess.run([sb_argv[0], "kill", sb_name],
                               capture_output=True, timeout=15)
            except Exception:
                pass
        if job is not None:
            job.close()   # v6.8.1: no handle leak on the timeout path
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
    for t in threads:
        t.join(timeout=5)  # never blocks forever even if an orphan holds a pipe
    if job is not None:
        job.close()   # Windows: terminate the job (kill-on-close also set)
    out, err = "".join(out_buf), "".join(err_buf)
    if len(out) >= RUN_OUTPUT_CAP:
        out += "\n... [output capped at %d chars to protect RAM]" % RUN_OUTPUT_CAP
    if len(err) >= RUN_OUTPUT_CAP:
        err += "\n... [output capped at %d chars to protect RAM]" % RUN_OUTPUT_CAP
    if timed_out:
        print(c(C.Y, "[!] process killed"))
        print(c(C.Y, "(raise it: /timeout 300   |   long-running servers: use /serve)"))
        combined = err + ("\n" if err and out else "") + out
        sess.last_failed = {"cmd": cmd, "code": "timeout", "output": combined}
        if not auto:
            offer_fix(sess)
        return -1
    if out:
        print(c(C.D, "--- stdout ---"))
        print(truncate(out, 2000))
    if err:
        print(c(C.R, "--- stderr ---"))
        print(truncate(err, 2000))
    code = proc.returncode
    if code == 0:
        print(c(C.G, "[ok] exit code 0"))
        if flightlog is not None:
            try:
                flightlog.log("run.verdict", "command passed",
                              cmd=cmd[:160], exit=0)
            except Exception:
                pass
        sess.last_failed = None
        # v8.8: a green run re-arms the auto-fix brake (the session just
        # proved the current state works - old failed rounds are history)
        sess.fix_rounds = 0
        # a successful run on top of applied files = a proven solution:
        # count it for the self-built skills and clean the feedback gate
        if sess.touched and skills is not None and sess.last_request:
            try:
                made = skills.record_success(sess.ws, sess.last_request, cmd)
                if made.startswith("auto:"):
                    print(c(C.G, "[skill] auto-saved a learned skill: " + made.split(":", 1)[1] +
                                 "  (see: /skill list)"))
            except Exception:
                pass
        # v8.11: a green run proves the CURRENT state works - clear the
        # whole gate note. Lint/guardian/probe leftovers used to survive
        # and ride a later 'files written but no Run line' prompt,
        # injecting already-resolved findings into a fresh turn.
        sess.last_feedback = None
    else:
        print(c(C.R, f"[fail] exit code {code}"))
        if flightlog is not None:
            try:
                flightlog.warn("run.verdict", "command failed",
                               cmd=cmd[:160], exit=code)
            except Exception:
                pass
        combined = err + ("\n" if err and out else "") + out
        # v6.8.3: an input()-driven program now fails CLEANLY (stdin is
        # DEVNULL) - tell the user what actually happened instead of
        # letting it look like broken generated code.
        if "EOFError" in combined or "EOF when reading a line" in combined:
            print(c(C.Y, "[i] this program asks for keyboard input (input()) - the web "
                         "face cannot send keystrokes. Run it in a terminal, or ask "
                         "Nova for a non-interactive version (menu / arguments)."))
            print(c(C.D, "    (برنامه منتظر تایپ کاربر است - اجرای تعاملی را در ترمینال انجام دهید)"))
        sess.last_failed = {"cmd": cmd, "code": code, "output": combined}
        if is_unrunnable_failure(code, combined):
            # v7.7: 'command not found' is NOT a code error - a fix round
            # against it only rewrote healthy files
            print(c(C.Y, "[i] the OS could not run this as a command - there is no "
                         "code error to fix. For a website, the answer should end "
                         "with 'Preview: index.html' (opened in your browser now), "
                         "or use /serve."))
        elif not auto:
            offer_fix(sess)
    return code

def collect_error_files(sess, output, cmd):
    """Find workspace files mentioned in an error output / command and attach them."""
    names = []
    def add(n):
        # v7.1.0 fix: keep the RAW name here - the old lstrip("/") turned a
        # POSIX traceback path '/home/ws/main.py' into 'home/ws/main.py'
        # BEFORE the absolute-path rebase could see it, so the rebase never
        # fired on Linux/macOS and /fix ran without the failing file.
        n = n.strip()
        if n and n not in names:
            names.append(n)
    for m in PY_TRACEBACK_RE.finditer(output):
        add(m.group(1))
    for m in GENERIC_FILE_RE.finditer(output):
        add(m.group(1))
    for m in re.finditer(r"[\w./\\-]+\.(?:py|js|html|css|json)", cmd or ""):
        add(m.group(0))
    picked = []
    for n in names:
        if len(picked) >= MAX_FIX_FILES:
            break
        if is_secret_path(n):
            continue    # never auto-attach credential files for debugging
        if sess.ignore is not None and sess.ignore.matches(n):
            continue    # .novaignore: never pull excluded files into context
        # v6.9: a traceback with an ABSOLUTE path ('File "C:\\proj\\main.py"'
        # or '/home/z/ws/main.py') could never match after safe_join re-rooted
        # it under the workspace - the fix round then ran without the file.
        # Workspace-absolute paths are re-based; anything outside stays out.
        # v7.1.0: the check now sees the RAW name (see add() above), so
        # POSIX absolute paths are re-based too, not only Windows ones.
        try:
            n_posix = n.replace("\\", "/")
            if os.path.isabs(n_posix) or re.match(r"^[A-Za-z]:", n_posix):
                rel = os.path.relpath(n_posix,
                                      str(sess.ws).replace("\\", "/"))
                if rel.startswith(".."):
                    continue
                n = rel.replace("\\", "/")
            else:
                n = n_posix.lstrip("/")
        except (ValueError, OSError):
            pass
        try:
            p = safe_join(sess.ws, n)
        except ValueError:
            continue
        if p.is_file():
            try:
                picked.append((n, truncate(p.read_text(encoding="utf-8", errors="replace"), MAX_FIX_CHARS)))
            except OSError:
                continue
    return picked

def offer_fix(sess):
    ans = ask("Ask Nova Code to fix this error? [Y/n]: ").strip().lower()
    if ans in ("n", "no"):
        return
    fix_flow(sess)


# --------------------------------------------------------------- auto loop
def auto_build(sess, user_text):
    """v7.13: the INSTRUMENTED entry to the autonomous loop. Wraps the
    real build->run->fix machinery in the honest agent loop phase
    machine (observe -> decide -> execute -> test -> fix -> verify) so
    the dashboard can show what is happening and the finish is only
    claimed with evidence (CompletionDetector)."""
    loop = None
    if intel is not None:
        try:
            loop = intel.AgentLoop(str(sess.ws), emit=emit_event)
            loop.start(user_text)
        except Exception:
            loop = None
    try:
        _auto_build_inner(sess, user_text, loop)
    finally:
        if loop is not None:
            try:
                if not loop.run.get("result"):
                    fbk = getattr(sess, "last_feedback", None) or {}
                    tests = fbk.get("tests") or {}
                    # v8.0 honesty fix: an early exit used to be recorded
                    # as "done" with fabricated evidence - lint_ok was
                    # True whenever the gate never ran (empty fbk) and
                    # tests_ok was True whenever no test setup existed
                    # ("no test setup detected" returned ok=True). Empty/
                    # unknown is now None; only a really-green gate is
                    # evidence, so failed builds are no longer logged as
                    # honest successes.
                    lint_ok = (not (fbk.get("syntax") or [])) if fbk else None
                    tests_ok = tests.get("ok") if tests.get("cmd") else None
                    evidence = {"lint_ok": lint_ok,
                                "tests_ok": tests_ok,
                                "run_ok": None}
                    loop.finish(
                        ok=bool(lint_ok is True and tests_ok is not False),
                        evidence=evidence,
                        note=("loop ended without an explicit verify - "
                              "verdict from the quality gate only") if fbk
                        else "loop ended early - nothing was applied or "
                             "verified")
            except Exception:
                pass


def _auto_build_inner(sess, user_text, loop=None):
    """The /loop autonomous engine - Nova Code's answer to Claude-Code-style
    agentic building on slow hardware:
      1. the model writes files/edits -> applied automatically (backups kept)
      2. its 'Run: <cmd>' line        -> executed (confirmed unless yolo)
      3. on failure                   -> the error goes straight back for a fix
    ...up to AUTO_MAX_STEPS rounds. Shell commands run in the workspace
    folder with capped output and the full kill-tree guarantee - but they
    carry the FULL user permissions (cwd-only confinement, no security
    sandbox), which is why every command is confirmed unless yolo is on.
    Self-defense: if the SAME error comes back twice in a row, the loop stops
    instead of burning slow generations on a fix that is not landing."""
    text = user_text
    if loop is not None:
        try:
            loop.phase("decide", why="plan the first build step")
        except Exception:
            pass
    last_sig = None
    last_norm = None
    recent_norms = []   # v8.11: the last few NORMALIZED errors - the old
                        # consecutive-only check was evaded by alternating
                        # failures (A, B, A, B) and every fresh /loop reset
                        # it to empty
    for step in range(1, AUTO_MAX_STEPS + 1):
        print(c(C.B, f"\n=== auto step {step}/{AUTO_MAX_STEPS} ==="))
        try:
            res = chat_turn(sess, text, auto=True)
        except KeyboardInterrupt:
            print(c(C.Y, "\n[auto] interrupted - auto mode stays ON. Continue manually or /auto off."))
            return
        if loop is not None:
            try:
                loop.phase("execute",
                           why="model wrote/applied changes (step %d)" % step,
                           next="run or test the result")
            except Exception:
                pass
        if res["run_cmd"]:
            cmd = res["run_cmd"]
            # v8.11: the gates refused the model's files (nothing landed
            # on disk) but the answer still carries a Run: line - it
            # points at the OLD code. Running it would fail identically
            # and the loop would declare 'the fix is not landing' though
            # the fix never landed. Feed the refusal back instead.
            _refused = getattr(sess, "batch_refused", False)
            if not res.get("applied") \
                    and (res.get("files") or res.get("edits")) \
                    and _refused:
                # v8.11: the fresh per-turn flag (raised by the three
                # gates at refusal) keeps a merely-stale last_feedback
                # from misfiring this guard
                sess.batch_refused = False
                print(c(C.Y, "[auto] the gates refused the model's files - "
                             "nothing was written, so the run is skipped "
                             "and the refusal goes back to the model."))
                text = ("AUTO MODE: your files were REFUSED by the quality "
                        "gates - nothing is on disk. Fix the exact problems "
                        "and re-output the complete files.\n\n")
                fb = _feedback_fix_note(sess)
                if fb:
                    text += fb
                continue
            if _looks_like_server(cmd):
                print(c(C.D, "[auto] server/preview command detected - start it yourself with: /serve"))
                return
            # ---- per-command policy (v5.0): allow skips the ask, deny stops
            verdict = npol.check_command(sess.policy, cmd) if npol else "ask"
            if verdict == "deny":
                print(c(C.R, "[policy] command denied by this project's policy - "
                             "auto loop stops (review: /policy)"))
                return
            if not sess.auto_yolo and verdict != "allow":
                ans = ask(f"Auto-run this command? [Y/n]: ({cmd}) ").strip().lower()
                if ans in ("n", "no"):
                    print(c(C.D, "[auto] stopped before running the command (still in auto mode)."))
                    return
            print(c(C.D, "[auto] running: " + cmd))
            if loop is not None:
                try:
                    loop.phase("test", why="run: %s" % cmd[:120])
                except Exception:
                    pass
            try:
                code = run_command(sess, cmd, auto=True)
            except KeyboardInterrupt:
                print(c(C.Y, "\n[auto] interrupted during the run - auto mode stays ON."))
                return
            if code == 0:
                print(c(C.G, "[auto] command succeeded - task complete."))
                if sess.touched:
                    print(c(C.D, "(changed files: /changes   |   mistakes: /undo)"))
                if loop is not None:
                    try:
                        loop.finish(ok=True, evidence={"run_ok": True},
                                    note="verify command exited 0")
                    except Exception:
                        pass
                return
            if code is None:
                print(c(C.Y, "[auto] command could not start - stopping."))
                return
            f = sess.last_failed or {"cmd": cmd, "code": code, "output": ""}
            sig = (f.get("code"), (f.get("output") or "")[-2000:])
            norm = error_signature(f)
            # v8.8: the same-error stop also fires when only cosmetic
            # details (line numbers, timings) differ between rounds.
            # v8.11: the check now looks at the last few normalized
            # errors, not just the previous round - alternating failures
            # (A, B, A, B) used to evade it until the step budget died.
            if sig == last_sig or norm == last_norm or norm in recent_norms:
                print(c(C.Y, "[auto] the SAME error came back - the fix is not landing. "
                             "Stopping to protect your time."))
                print(c(C.D, "    Try: /fix with a hint, /read the file yourself, or /clear then rephrase."))
                if loop is not None:
                    try:
                        plan = intel.RecoveryManager.handle(
                            (f.get("output") or "")[-2000:],
                            int(loop.run.get("attempts", 0)) + 1) \
                            if intel is not None else {}
                        loop.record("same error twice -> giving up "
                                    "(recovery: %s)"
                                    % plan.get("action", "stop"))
                    except Exception:
                        pass
                return
            # v8.11: web-parity guards - the same failure kinds the web
            # face already refuses to 'fix' (v7.7). Feeding a command the
            # OS never ran, or a timed-out run, to a fix round only
            # rewrote healthy files or chased working servers.
            if is_unrunnable_failure(f.get("code"), f.get("output") or ""):
                print(c(C.Y, "[auto] the OS never ran this command - there is "
                             "no code error to fix (check the command itself)."))
                return
            if f.get("code") == "timeout" or code == -1:
                print(c(C.Y, "[auto] the run was killed at the timeout, which alone "
                             "proves nothing - stopping the fix loop. "
                             "(If it is a server, preview it with /serve.)"))
                return
            # v8.11: the step limit ends the loop right after this
            # round - no fix round can be armed, so none is counted
            if step >= AUTO_MAX_STEPS:
                break
            # v8.11: THE FIX BUDGET - the terminal /loop used to run
            # without the brake the web face got in v8.8, so a fix that
            # kept introducing a new bug burned round after round.
            if fix_budget_left(sess) <= 0:
                print(c(C.Y, "[auto] the fix budget is used up - "
                             + str(MAX_FIX_ROUNDS) + " fix round(s) without a "
                             "green run. Stopping here instead of looping "
                             "(a green run or /autofix on re-arms it)."))
                print(c(C.D, "    (بودجه‌ی اصلاح تمام شد - به‌جای لوپ بی‌پایان ایستادیم. "
                             "اجرای سبز یا /autofix on دوباره فعال می‌کند)"))
                return
            bump_fix_round(sess)
            last_sig = sig
            last_norm = norm
            recent_norms.append(norm)
            if len(recent_norms) > 3:
                recent_norms.pop(0)
            if loop is not None:
                try:
                    loop.attempt()
                    plan = intel.RecoveryManager.handle(
                        (f.get("output") or "")[-2000:],
                        int(loop.run.get("attempts", 0))) \
                        if intel is not None else {}
                    loop.phase("fix", why="command failed (exit %d) - "
                               "strategy: %s" % (code, plan.get(
                                   "action", "fix_targeted")),
                               next="send the error back for a targeted fix")
                except Exception:
                    pass
            # v8.11: the fix round now carries the involved files -
            # /verify and the web face attach them; the /loop silently
            # did not, so small local models usually could not land the
            # fix without seeing the file and the budget burned dry.
            picked = collect_error_files(sess, f["output"], f["cmd"])
            attach_blocks = ""
            if picked:
                print(c(C.D, "Auto-attaching files mentioned in the error: "
                            + ", ".join(n for n, _ in picked)))
                attach_blocks = "\n".join(
                    f"\n--- attached file: {n} (current content) ---\n{content}\n--- end of file ---"
                    for n, content in picked)
            text = ("AUTO MODE: the command you proposed failed. Fix the root cause: for a few "
                    "changed lines output === EDIT: === blocks (SEARCH must match the file exactly "
                    "once), otherwise output the COMPLETE corrected files with === FILE: ===. "
                    "If you must see a file first, output [READ: path] alone. End with the exact "
                    "Run: command to verify.\n\n"
                    f"Command: {f['cmd']}\nExit code: {f['code']}\nOutput tail:\n---\n"
                    f"{truncate(f['output'], MAX_ERROR_CHARS)}\n---"
                    + attach_blocks)
            fb = _feedback_fix_note(sess)
            if fb:
                text += "\n\n" + fb
        elif res["applied"]:
            text = ("AUTO MODE: your files were written, but no 'Run: <command>' line was "
                    "found. Reply with the single exact command that verifies the work "
                    "(compile / run / test) as a 'Run: ...' line - or output more files "
                    "first if any are still missing.")
            fb = _feedback_fix_note(sess)
            if fb:
                text += "\n\n" + fb
        else:
            # pure explanation / question answered - nothing to verify.
            # v8.11: an EMPTY answer (stream died, tool rounds burned
            # out, only a dangling [READ: x]) is NOT 'an explanation' -
            # the old code recorded a false success with zero files
            # written. Only a real prose answer completes the loop.
            if not (res.get("answer") or "").strip():
                print(c(C.Y, "[auto] the model produced no answer and no "
                             "files - stopping instead of declaring success."))
                return      # the outer finally records the honest verdict
            if loop is not None:
                try:
                    loop.finish(ok=True,
                                evidence={"waived": "no build needed - "
                                          "answered as explanation"})
                except Exception:
                    pass
            return
        # the model must never lose the thread: inject the live plan status
        if nova_todo is not None and sess.todo:
            text = nova_todo.status_prompt(sess.todo) + "\n\n" + text
    print(c(C.Y, f"[auto] step limit ({AUTO_MAX_STEPS}) reached - auto mode stays ON. "
               "Review the last output, then continue with /fix, /verify, /run or another message."))

def _read_ws_file(sess, name):
    """v8.4 helper: read an applied workspace file for the guardian's
    post-apply review (missing/unreadable = empty body, the fleet
    simply has nothing to say about it)."""
    try:
        return (Path(sess.ws) / name).read_text(
            encoding="utf-8", errors="replace")[:guardian.MAX_GUARD_FILE_CHARS]
    except Exception:
        return ""


def _feedback_fix_note(sess):
    """Machine-readable quality-gate result -> short text the auto/verify
    loops append to the next fix prompt. '' when everything is green."""
    fbk = getattr(sess, "last_feedback", None)
    if not fbk:
        return ""
    parts = []
    for rel, problem in fbk.get("syntax") or []:
        parts.append(f"- SYNTAX ERROR in {rel}: {problem}")
    for tag, problem in fbk.get("lint") or []:
        parts.append(f"- LINT ({tag}): {problem}")
    # v8.4: the code guardian fleet's findings ride along too - the fix
    # round must see what the sub-sub-agents caught, not just the linter
    for fname, ln, msg in fbk.get("guardian") or []:
        where = f"line {ln}" if ln else "file"
        parts.append(f"- GUARDIAN ({fname}, {where}): {msg}")
    # v8.5: the bug hunter's findings ride along too - a dead button or
    # a crashed entry script is exactly what the fix round must see
    for fname, ln, msg in fbk.get("probe") or []:
        where = f"line {ln}" if ln else "file"
        parts.append(f"- BUG HUNTER ({fname}, {where}): {msg}")
    tests = fbk.get("tests")
    if tests and tests.get("cmd") and not tests.get("ok"):
        parts.append(f"- TESTS FAILED ({tests['report']}). Output tail:\n"
                     f"{(tests.get('tail') or '')[:1200]}")
    if not parts:
        return ""
    return ("QUALITY GATE (ran automatically after your files were applied) "
            "found problems - fix them FIRST:\n" + "\n".join(parts)[:2600])


# ---- v8.8: the fix-loop brake -------------------------------------------
# The user's report: the run -> fix -> run cycle "gets stuck in a loop and
# never finishes". Two honest brakes: (1) a session-level budget of
# CONSECUTIVE automatic fix rounds without a green run - when it runs out,
# Nova stops and says so instead of silently cycling forever (a green run
# or a manual /autofix on re-arms it); (2) error_signature() above, which
# makes the existing 'same error twice' stop actually fire when only line
# numbers/timings differ between rounds.
MAX_FIX_ROUNDS = max(1, min(8, _envint("NOVA_FIX_ROUNDS", 3)))


def fix_budget_left(sess):
    """How many automatic fix rounds the session may still fire (v8.8)."""
    try:
        return max(0, MAX_FIX_ROUNDS - int(getattr(sess, "fix_rounds", 0)))
    except Exception:
        return MAX_FIX_ROUNDS


def bump_fix_round(sess):
    """Count one fired automatic fix round (v8.8)."""
    try:
        sess.fix_rounds = int(getattr(sess, "fix_rounds", 0)) + 1
    except Exception:
        sess.fix_rounds = 1


def reset_fix_rounds(sess):
    """Re-arm the fix budget: after a green run, a workspace switch, or a
    manual /autofix on (v8.8)."""
    try:
        sess.fix_rounds = 0
    except Exception:
        pass


def build_fix_message(sess):
    """v6.8.3: the fix prompt for sess.last_failed, shared by the REPL
    fix_flow (interactive) and the web face's one-round auto-fix after a
    failed Run click. Returns the message string (or None when there is
    nothing to fix)."""
    f = sess.last_failed
    if not f:
        return None
    picked = collect_error_files(sess, f["output"], f["cmd"])
    attach_blocks = ""
    if picked:
        print(c(C.D, "Auto-attaching files mentioned in the error: " + ", ".join(n for n, _ in picked)))
        attach_blocks = "\n".join(
            f"\n--- attached file: {n} (current content) ---\n{content}\n--- end of file ---"
            for n, content in picked
        )
    return (
        "A command failed inside the workspace. Fix the root cause: for a few changed lines\n"
        "output === EDIT: === blocks (SEARCH must match the file exactly once); otherwise\n"
        "rewrite the COMPLETE corrected files with the === FILE: === format.\n\n"
        f"Command: {f['cmd']}\n"
        f"Exit code: {f['code']}\n"
        "Output (stdout/stderr tail):\n"
        "---\n"
        f"{truncate(f['output'], MAX_ERROR_CHARS)}\n"
        "---\n"
        + attach_blocks +
        "\nIf the output alone is not enough, review the attached files carefully for logic bugs,\n"
        "fix everything you find, then give me the exact command to re-run.\n"
        "If you must see another file first, output [READ: path] alone as the last line."
        # note: pending /load attachments are appended by chat_turn() itself -
        # composing them here as well would send every attachment TWICE
    )


def fix_flow(sess):
    f = sess.last_failed
    if not f:
        print(c(C.Y, "[!] no failed command recorded. Run something with /run or /check first."))
        return
    msg = build_fix_message(sess)
    if msg:
        chat_turn(sess, msg)


def verify_flow(sess, cmd=None):
    """AUTOMATIC VERIFY LOOP - run the command; if it fails, send the error to
    the model, apply its fix WITHOUT asking (backups kept, /undo works), and
    re-run - up to VERIFY_MAX_STEPS rounds, zero manual intervention.
    Self-defense for slow machines:
      - the same error twice in a row stops the loop (the fix is not landing);
      - server-like commands are refused (they never exit 0 - use /serve);
      - if the model's fix renames the entry point, its own Run: line is
        adopted for the next round."""
    cmd = (cmd or sess.last_cmd or "").strip()
    if not cmd:
        print(c(C.Y, "[!] nothing to verify yet - use:  /verify <command>   "
                    "e.g.:  /verify " + py_run_name() + " main.py"))
        return False
    if _looks_like_server(cmd):
        print(c(C.Y, "[!] that looks like a long-running server - preview it with /serve instead."))
        print(c(C.D, "    /verify is for commands that must finish with exit code 0."))
        return False
    print(c(C.B, f"[verify] goal: '{cmd}' must exit 0 - up to {VERIFY_MAX_STEPS} "
               "run -> auto-fix -> re-run round(s)."))
    last_sig = None
    last_norm = None
    recent_norms = []   # v8.11: same anti-alternation memory as /loop
    for step in range(1, VERIFY_MAX_STEPS + 1):
        print(c(C.B, f"=== verify step {step}/{VERIFY_MAX_STEPS} ==="))
        code = run_command(sess, cmd, auto=True)   # never prompts
        if code == 0:
            print(c(C.G, f"[verify] SUCCESS - '{cmd}' exited 0."))
            if sess.touched:
                print(c(C.D, "(changed files: /changes   |   mistakes: /undo)"))
            return True
        if code is None:
            print(c(C.Y, "[verify] the command could not even start - stopping."))
            return False
        f = sess.last_failed or {"cmd": cmd, "code": code, "output": ""}
        sig = (f.get("code"), (f.get("output") or "")[-2000:])
        norm = error_signature(f)
        # v8.8 + v8.11: cosmetic-only drift OR any of the last few
        # normalized errors repeating -> the fix is not landing
        if sig == last_sig or norm == last_norm or norm in recent_norms:
            print(c(C.Y, "[verify] the SAME error came back - Nova is not making progress."))
            print(c(C.D, "    Try: /fix with a hint, /read the file yourself, or /clear then rephrase."))
            return False
        # v8.11: web-parity skips - a fix round against 'command not
        # found' or a timeout only rewrote healthy files
        if is_unrunnable_failure(f.get("code"), f.get("output") or ""):
            print(c(C.Y, "[verify] the OS never ran this command - there is "
                         "no code error to fix (check the command itself)."))
            return False
        if f.get("code") == "timeout" or code == -1:
            print(c(C.Y, "[verify] the run was killed at the timeout - that alone "
                         "proves nothing. (For servers use /serve.)"))
            return False
        # v8.11: the loop ends after this round's report - no fix round
        # can be armed, so none is counted
        if step == VERIFY_MAX_STEPS:
            break  # no fix round after the last failed run
        # v8.11: the same session-level brake the web face has
        if fix_budget_left(sess) <= 0:
            print(c(C.Y, "[verify] the fix budget is used up (" + str(MAX_FIX_ROUNDS)
                         + " round(s) without a green run) - stopping instead of "
                         "looping. A green run or /autofix on re-arms it."))
            print(c(C.D, "    (بودجه‌ی اصلاح تمام شد - ایستادیم. اجرای سبز یا "
                         "/autofix on دوباره فعال می‌کند)"))
            return False
        bump_fix_round(sess)
        last_sig = sig
        last_norm = norm
        recent_norms.append(norm)
        if len(recent_norms) > 3:
            recent_norms.pop(0)
        # ---- automatic fix round: error + involved files -> model ----------
        picked = collect_error_files(sess, f["output"], f["cmd"])
        attach_blocks = ""
        if picked:
            print(c(C.D, "Auto-attaching files mentioned in the error: "
                        + ", ".join(n for n, _ in picked)))
            attach_blocks = "\n".join(
                f"\n--- attached file: {n} (current content) ---\n{content}\n--- end of file ---"
                for n, content in picked)
        msg = (
            "VERIFY MODE (automatic fix round): this command failed. Fix the root cause.\n"
            "For a few changed lines output === EDIT: === blocks (SEARCH must match the\n"
            "file exactly once); otherwise output the COMPLETE corrected files with the\n"
            "=== FILE: === format. End with the exact re-run command as 'Run: <command>'.\n\n"
            f"Command: {f['cmd']}\n"
            f"Exit code: {f['code']}\n"
            "Output (tail):\n"
            "---\n"
            f"{truncate(f['output'], MAX_ERROR_CHARS)}\n"
            "---\n"
            + attach_blocks +
            "\nIf the output alone is not enough, review the attached files for the bug.\n"
            "If you must see another file first, output [READ: path] alone as the last line."
            # pending /load attachments are appended by chat_turn() - do NOT
            # compose them here as well (they would be sent twice)
        )
        fb = _feedback_fix_note(sess)
        if fb:
            msg += "\n\n" + fb
        print(c(C.D, "[verify] sending the error to Nova for an automatic fix ..."))
        try:
            res = chat_turn(sess, msg, auto=True)
        except KeyboardInterrupt:
            print(c(C.Y, "\n[verify] interrupted - stopping the loop (auto mode unchanged)."))
            return False
        if not res["applied"]:
            print(c(C.Y, "[verify] Nova did not produce applicable files/edits - stopping."))
            print(c(C.D, "    (its answer is above; continue manually with /fix or /run)"))
            return False
        new_cmd = (res.get("run_cmd") or "").strip()
        if new_cmd and new_cmd != cmd and not _looks_like_server(new_cmd):
            cmd = new_cmd  # the fix may rename the entry point - follow it
            print(c(C.D, "[verify] next round runs Nova's own command: " + cmd))
    print(c(C.Y, f"[verify] {VERIFY_MAX_STEPS} round(s) reached without a green run - stopping."))
    print(c(C.D, "    The last error is saved - a manual /fix can still solve it."))
    return False


def _cmd_verify(sess, arg=""):
    verify_flow(sess, arg.strip() or None)

# --------------------------------------------------------------- serve (websites)
class _PreviewServer:
    """In-process preview server bound to 127.0.0.1 (daemon thread). It
    exposes the SAME lifecycle surface as the old `python -m http.server`
    subprocess (poll / terminate / kill / wait) so /serve, /status and
    stop_serve keep working unchanged - and adds guards the stdlib handler
    lacks: dotfiles (e.g. .env, .git/), anything resolving outside the
    workspace (symlink escape) and .. tricks are all refused with 404."""

    def __init__(self, ws, port):
        from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
        ws_root = Path(ws).resolve()

        class _GuardedHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ws_root), **kwargs)

            def translate_path(self, path):
                p = Path(super().translate_path(path))
                blocked = str(ws_root / ".nova" / "404-blocked")
                try:
                    rel = p.resolve().relative_to(ws_root)
                except ValueError:
                    return blocked        # outside the workspace
                if any(part.startswith(".") for part in rel.parts):
                    return blocked        # dotfiles never leave the machine
                return str(p)

            def list_directory(self, path):
                # v7.1.0: the autoindex used to LIST dotfile names (.env,
                # .git/ ...) even though fetching them 404s - names alone
                # leak project structure. Real filtered listing instead.
                import io
                import html as _html
                import urllib.parse as _up
                try:
                    entries = [e for e in os.listdir(str(path))
                               if not e.startswith(".")]
                except OSError:
                    self.send_error(404, "No such directory")
                    return None
                entries.sort(key=str.lower)
                rows = []
                for name in entries:
                    full = os.path.join(str(path), name)
                    isdir = os.path.isdir(full)
                    disp = _html.escape(name + ("/" if isdir else ""))
                    href = _up.quote(name) + ("/" if isdir else "")
                    rows.append(f'<li><a href="{href}">{disp}</a></li>')
                body = ("<html>\n<head>\n<meta charset=\"utf-8\">\n"
                        "<title>Directory listing</title>\n</head>\n"
                        "<body>\n<h1>Directory listing</h1>\n<hr>\n<ul>\n"
                        + "\n".join(rows) +
                        "\n</ul>\n<hr>\n</body>\n</html>\n"
                        ).encode("utf-8", "replace")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return io.BytesIO(body)

            def log_message(self, fmt, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _GuardedHandler)
        self.port = self.httpd.server_address[1]
        self._alive = True
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    # -- lifecycle shims so the old subprocess-style callers keep working --
    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        if self._alive:
            self._alive = False
            self.httpd.shutdown()
            self.httpd.server_close()

    kill = terminate

    def wait(self, timeout=None):
        self._thread.join(timeout=timeout)


def cmd_serve(sess, arg):
    if sess.serve_proc and sess.serve_proc.poll() is None:
        stop_serve(sess)
        return
    port = int(arg) if arg.isdigit() else 8000
    if not (1024 <= port <= 65535):
        print(c(C.Y, "[!] usage: /serve [port]  (1024-65535, default 8000)"))
        return
    try:
        proc = _PreviewServer(sess.ws, port)
    except OSError as e:
        print(c(C.R, f"[!] could not start server on port {port} ({e}) - try: /serve {port + 1}"))
        return
    except Exception as e:
        print(c(C.R, "[!] failed to start server: " + str(e)))
        return
    sess.serve_proc = proc
    sess.serve_port = proc.port
    url = f"http://localhost:{proc.port}"
    print(c(C.G, "Preview server running: " + url))
    print(c(C.D, "Serving folder: " + str(sess.ws)))
    print(c(C.D, "Open " + url + " in your browser. Run /serve again to stop it."))
    print(c(C.D, "(bound to 127.0.0.1 - only this computer can see the site; "
               "dotfiles like .env are never served)"))
    open_browser(url)

# --------------------------------------------------------------- static check
def cmd_check(sess, arg=""):
    print(c(C.D, "Running static analysis on the workspace..."))
    issues = []
    py_files = [p for p in sorted(sess.ws.rglob("*.py"))
                if not any(part in IGNORED_DIRS for part in p.parts)]
    js_files = [p for p in sorted(sess.ws.rglob("*.js"))
                if not any(part in IGNORED_DIRS for part in p.parts)]
    for p in py_files:
        rel = p.relative_to(sess.ws).as_posix()
        # v6.9: ast.parse instead of py_compile - a "read-only check" used
        # to write .pyc files into the user's project, and in a read-only
        # workspace the bytecode write was reported as a SYNTAX error of a
        # perfectly healthy file (offer_fix then "fixed" healthy code).
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="replace"),
                      filename=str(p))
        except SyntaxError as e:
            issues.append((rel, f"line {e.lineno}: {e.msg}"))
        except (OSError, ValueError) as e:
            issues.append((rel, f"{type(e).__name__}: {e}"))
    node = shutil.which("node")
    if node:
        for p in js_files:
            rel = p.relative_to(sess.ws).as_posix()
            try:
                r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True, timeout=20)
                if r.returncode != 0:
                    issues.append((rel, (r.stderr or "syntax error").strip()))
            except Exception as e:
                issues.append((rel, f"{type(e).__name__}: {e}"))
    elif js_files:
        print(c(C.D, "(node not found - skipped JS syntax check)"))
    checked = len(py_files) + (len(js_files) if node else 0)
    if checked == 0:
        print(c(C.Y, "[!] no .py / .js files to check."))
        return
    if issues:
        for rel, err in issues:
            print(c(C.R, f"  [x] {rel}"))
            print(truncate(err, 1200))
        combined = "\n\n".join(f"{rel}:\n{err}" for rel, err in issues)
        sess.last_failed = {"cmd": "/check (static analysis)", "code": 1, "output": combined}
        print(c(C.R, f"[fail] {len(issues)} of {checked} file(s) have problems."))
        offer_fix(sess)
    else:
        print(c(C.G, f"[ok] all {checked} file(s) passed the static check."))

# --------------------------------------------------------------- commands
def cmd_help(sess=None, arg=""):
    """Generated from the TOOLS registry - a new/removed/renamed tool shows up
    here automatically, with zero extra bookkeeping."""
    print(c(C.B, "\nCommands:"))
    for t in TOOLS:
        if not tool_available(t):
            continue
        print("  " + c(C.CY, t["usage"].ljust(20)) + c(C.D, t["help"]))
    if ns is None and any(t.get("needs_ns") for t in TOOLS):
        print(c(C.Y, "  (web tools are hidden - nova_search.py is missing next to nova.py)"))
    print(c(C.D, "\nAnything else you type goes to the model. Persian chat is fine - "
               "code and filenames stay English.\n"))

def cmd_ls(sess, arg=""):
    count = 0
    stop = False
    def walk(d, prefix):
        nonlocal count, stop
        if stop:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        entries = [p for p in entries if p.name not in IGNORED_DIRS and not p.name.startswith(".")]
        for i, p in enumerate(entries):
            if count >= 200:
                print(prefix + "...")
                stop = True
                return
            last = (i == len(entries) - 1)
            conn = "\\-- " if last else "|-- "
            if p.is_dir():
                print(prefix + conn + c(C.B, p.name + "/"))
                count += 1
                walk(p, prefix + ("    " if last else "|   "))
                if stop:
                    return
            else:
                try:
                    size = c(C.D, "  " + human_size(p.stat().st_size))
                except OSError:
                    size = ""
                print(prefix + conn + p.name + size)
                count += 1
    print(str(sess.ws) + "/")
    walk(sess.ws, "")
    if count == 0:
        print(c(C.D, "(workspace is empty)"))

def cmd_read(sess, arg):
    if not arg:
        print(c(C.Y, "[!] usage: /read main.py"))
        return
    if sess.ignore is not None and sess.ignore.matches(arg):
        print(c(C.Y, f"[!] '{arg}' is in .novaignore - hidden from the agent's view "
                     "(/novaignore to review the rules)."))
        return
    try:
        p = safe_join(sess.ws, arg)
    except ValueError as e:
        print(c(C.R, "[!] " + str(e)))
        return
    if not p.is_file():
        print(c(C.Y, "[!] file not found (or it is a folder): " + arg))
        return
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(c(C.R, "[!] cannot read: " + str(e)))
        return
    print(c(C.D, f"--- {arg} ({len(text)} chars) ---"))
    print(truncate(text, MAX_READ_CHARS))

def _attach(sess, name, content, success_note=None):
    """Attach one item to the user's next message, honoring MAX_ATTACHMENTS.
    EVERY attachment path goes through here (/load, /search, /learn, /docs,
    /review), so the context-window cap cannot be bypassed and credential
    files are blocked in ONE place. Returns True when attached."""
    if len(sess.loads) >= MAX_ATTACHMENTS:
        print(c(C.Y, f"[!] too many attachments ({len(sess.loads)}) - the context window would overflow."))
        print(c(C.D, "    Send the current message first, then attach more."))
        return False
    if is_secret_path(name):
        print(c(C.R, f"[!] '{name}' can hold credentials - attaching it would risk "
                     "leaking secrets (to a cloud provider too). Blocked."))
        print(c(C.D, "    If you really need it, open the file and paste only the relevant lines."))
        return False
    if sess.ignore is not None and sess.ignore.matches(name):
        print(c(C.Y, f"[!] '{name}' is in .novaignore - it stays out of the model's "
                     "context (remove the rule to attach it)."))
        return False
    sess.loads.append((name, content))
    if success_note:
        print(c(C.G, success_note))
    return True


def cmd_load(sess, arg):
    if not arg:
        print(c(C.Y, "[!] usage: /load css/style.css"))
        return
    try:
        p = safe_join(sess.ws, arg)
    except ValueError as e:
        print(c(C.R, "[!] " + str(e)))
        return
    if not p.is_file():
        print(c(C.Y, "[!] file not found (or it is a folder): " + arg))
        return
    try:
        content = truncate(p.read_text(encoding="utf-8", errors="replace"), MAX_LOAD_CHARS)
    except OSError as e:
        print(c(C.R, "[!] cannot read: " + str(e)))
        return
    if _attach(sess, arg, content):
        print(c(C.G, f"Attached {arg} ({len(sess.loads)} pending) - sent with your next message."))

def list_models_detailed():
    """All locally installed Ollama models as clean dicts (nova_models.
    parse_tags shape): [{name, size, family, params, quant, modified}].
    [] when Ollama is down or the payload is garbage - the /model table,
    the startup auto-pick and /disk degrade honestly instead of crashing."""
    if nmodels is None:
        return []
    try:
        return nmodels.parse_tags(http_get_json("/api/tags"))
    except Exception:
        return []

def list_installed_models():
    """Just the model names, server order (newest first)."""
    return nmodels.names_of(list_models_detailed()) if nmodels else []

# ------------------------------------------------------- v5.2: model FILES
# Method 2 of giving Nova a local brain: .gguf files the user downloaded
# into a models folder (NOVA_MODELS_DIR / ~/.nova/models / .nova/models).
# Discovery is a TTL-cached folder scan; RUNNING a file is resolved
# lazily: import into Ollama (preferred, cached) or spawn llama-server.

_LOCAL_SCAN = {"at": 0.0, "key": None, "list": []}
_LOCAL_SCAN_TTL = 20.0          # seconds - the web poll must not rescan
_IMPORT_LOCK = threading.Lock() # terminal + web must not double-import


def list_local_models(ws=None, force=False):
    """Runnable + informational model-file entries for this workspace
    (TTL-cached; `force` for interactive /model and settings changes).
    Fail-soft: a broken scanner just yields []."""
    if lmodels is None:
        return []
    key = str(ws) if ws is not None else ""
    now = time.time()
    if not force and _LOCAL_SCAN["key"] == key \
            and now - _LOCAL_SCAN["at"] < _LOCAL_SCAN_TTL:
        return _LOCAL_SCAN["list"]
    try:
        entries = lmodels.scan_dirs(lmodels.model_dirs(ws))
    except Exception:
        entries = []
    _LOCAL_SCAN.update(at=now, key=key, list=entries)
    return entries


def _find_local_entry(model_id, entries=None):
    """'file:<name>' (or a bare file name) -> entry dict, or None."""
    if lmodels is None:
        return None
    want = str(model_id).strip()
    if want.startswith(lmodels.LOCAL_PREFIX):
        want = want[len(lmodels.LOCAL_PREFIX):]
    want = want.strip().strip("\"'").lower()
    if not want:
        return None
    entries = entries if entries is not None else list_local_models()
    for e in entries:                       # exact id first (no ext)
        if e.get("name", "").lower() == want:
            return e
    for e in entries:                       # then the real file name
        try:
            fn = Path(e.get("file", "")).name.lower()
        except Exception:
            fn = ""
        if fn == want or fn == want + ".gguf":
            return e
    return None


def _match_local_entry(arg, entries, installed_count=0):
    """Resolve /model <arg> against the LOCAL FILE section: by id, file
    name, or the CONTINUOUS row number after the Ollama rows."""
    a = (arg or "").strip()
    if not a:
        return None
    if a.isdigit():
        idx = int(a)
        pos = idx - installed_count
        if 1 <= pos <= len(entries):
            return entries[pos - 1]
        return None
    return _find_local_entry(a, entries)


def _local_cache_path(ws):
    return Path(ws) / ".nova" / "local_models.json"


def _local_cache_load(ws):
    """{abs file path: {ollama, size, at}} - fail-soft, size-capped."""
    if ws is None:
        return {}
    try:
        p = _local_cache_path(ws)
        if not p.is_file() or p.stat().st_size > 100_000:
            return {}
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _local_cache_get(ws, file_path):
    d = _local_cache_load(ws)
    rec = d.get(str(Path(file_path).resolve()))
    return rec.get("ollama", "") if isinstance(rec, dict) else ""


def _local_cache_set(ws, file_path, ollama_name):
    if ws is None:
        return
    try:
        p = _local_cache_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        d = _local_cache_load(ws)
        d[str(Path(file_path).resolve())] = {
            "ollama": ollama_name,
            "size": Path(file_path).stat().st_size,
            "at": datetime.now().isoformat(timespec="seconds")}
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass                              # cache is best-effort only


def _ollama_alive(timeout=4):
    try:
        http_get_json("/api/tags", timeout=timeout)
        return True
    except Exception:
        return False


def _ollama_exec():
    """ollama CLI path (the server may run while PATH lacks it - then the
    plain name is the honest last try)."""
    return shutil.which("ollama") or "ollama"


def import_gguf_to_ollama(entry, ws=None, quiet=False):
    """One-time import of a .gguf file into the local Ollama library
    (`ollama create <name> -f Modelfile` with FROM <file>). Returns the
    ollama model name, or None after printing a short reason. The
    deterministic name + the .nova/local_models.json cache make this a
    once-per-file operation even across restarts."""
    if lmodels is None or nmodels is None:
        return None
    path = entry.get("file", "")
    name = lmodels.ollama_import_name(path)
    with _IMPORT_LOCK:
        if name in list_installed_models():     # already imported once
            _local_cache_set(ws, path, name)
            return name
        modelfile = Path(ws or Path.cwd()) / ".nova" / "tmp"
        try:
            modelfile.mkdir(parents=True, exist_ok=True)
            modelfile = modelfile / ("Modelfile-" + name)
            modelfile.write_text('FROM "' + str(Path(path).resolve()) + '"\n',
                                 encoding="utf-8")
        except OSError as e:
            if not quiet:
                print(c(C.R, "[!] cannot write the import recipe: " + str(e)))
            return None
        size_s = nmodels.fmt_size(entry.get("size")) or "?"
        if not quiet:
            print(c(C.B, f"[*] importing the model file into Ollama (one-time): {name}"))
            print(c(C.D, f"    source: {path}  ({size_s})"))
            print(c(C.D, "    the file is copied into Ollama's storage -"
                         " big files take a while (NOVA_IMPORT_TIMEOUT)"))
        cmd = [_ollama_exec(), "create", name, "-f", str(modelfile)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=_envint("NOVA_IMPORT_TIMEOUT", 1800))
        except subprocess.TimeoutExpired:
            if not quiet:
                print(c(C.R, "[!] ollama create timed out - is the disk very slow?"
                             "  (raise: NOVA_IMPORT_TIMEOUT=<seconds>)"))
            return None
        except OSError as e:
            if not quiet:
                print(c(C.R, "[!] cannot run the ollama CLI: " + str(e)))
                print(c(C.D, "    (ollama serve can be running while 'ollama' is"
                             " not on PATH - fix PATH or use llama-server)"))
            return None
        finally:
            try:
                modelfile.unlink(missing_ok=True)
            except OSError:
                pass
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            reason = " / ".join(tail[-2:])[:300] if tail else f"exit {proc.returncode}"
            if not quiet:
                print(c(C.R, "[!] ollama create failed: " + reason))
            return None
        _local_cache_set(ws, path, name)
        if not quiet:
            print(c(C.G, "[+] imported - ready to chat with " + name))
        return name


def ensure_local_model(sess=None, entry=None, quiet=False):
    """Make a LOCAL FILE model actually runnable, NOW.
    Returns (mode, value): ("ollama", imported_name) or
    ("llamacpp", provider_cfg) - or (None, error_message). Order:
    cached Ollama import -> live import -> llama.cpp server."""
    if lmodels is None:
        return (None, "local model support is unavailable (nova_localmodels.py missing)")
    if entry is None and sess is not None:
        ws = getattr(sess, "ws", None)
        entry = _find_local_entry(sess.model, list_local_models(ws))
    if entry is None:
        return (None, "model file not found in the model folders (/model shows them)")
    if not entry.get("runnable", False):
        return (None, entry.get("note") or "this file cannot run directly"
                     " - convert it to GGUF first")
    ws = getattr(sess, "ws", None) if sess is not None else None
    cached = _local_cache_get(ws, entry["file"])
    if cached and cached in list_installed_models():
        return ("ollama", cached)
    if _ollama_alive():
        name = import_gguf_to_ollama(entry, ws=ws, quiet=quiet)
        if name:
            return ("ollama", name)
        # import failed -> try the llama.cpp fallback below
    handle = None
    try:
        handle = lmodels.start_llama_server(
            entry["file"],
            # v8.3: the session's local window (custom setting wins over
            # the global) - llama-server gets it as its -c flag.
            ctx=(sess._effective_num_ctx() if sess is not None else NUM_CTX),
            log_dir=(Path(ws) / ".nova" / "tmp") if ws else None)
    except lmodels.LocalModelError as e:
        return (None, str(e))
    except Exception as e:
        return (None, "cannot start llama-server: " + str(e))
    return ("llamacpp", lmodels.openai_cfg(handle))


def _model_route_note(sess):
    """Honest, SIDE-EFFECT-FREE note for /status + repl: how the current
    file: model would run (never imports, never spawns)."""
    if lmodels is None or not str(sess.model).startswith(lmodels.LOCAL_PREFIX):
        return ""
    entry = _find_local_entry(sess.model, list_local_models(sess.ws))
    if entry is None:
        return " (file missing from the model folders!)"
    cached = _local_cache_get(sess.ws, entry["file"])
    if cached:
        return f" (via Ollama as {cached})"
    if not entry.get("runnable", False):
        return " (" + (entry.get("note") or "not runnable") + ")"
    return " (local file - runtime resolves on first use)"


def _select_local_file(sess, entry, quiet=False):
    """Pin a model-file entry as the session model (terminal /model and
    the web dropdown share this). Returns True on success."""
    cat = entry.get("category", "general")
    if not quiet and cat not in ("general", "code"):
        print(c(C.Y, "[!] note: '%s' lives in the local/%s category folder -"
                     " it is meant for the %s modules, not for the coding"
                     " agent's brain (a GENERAL model in local/ is the safe"
                     " pick here)" % (entry.get("name"), cat, "voice/photo")))
    mode, val = ensure_local_model(sess, entry=entry, quiet=quiet)
    if mode is None:
        print(c(C.R, "[!] " + str(val)))
        return False
    sess.model = entry["id"]
    sess.save_profile_field("model", entry["id"])
    if mode == "ollama":
        print(c(C.G, "Model set: " + entry["id"]
                     + "  (runs via Ollama as '" + val + "')"))
    else:
        print(c(C.G, "Model set: " + entry["id"]
                     + "  (runs via llama.cpp server on " + val.get("base", "?") + ")"))
    return True

def resolve_session_model(sess, installed=None, quiet=False):
    """v5.2 model resolution for a fresh session (terminal AND web).

    Priority: already-set model (profile / NOVA_MODEL / memory) honoured
    when it still exists (a 'file:<name>' model must exist in the model
    folders) -> DEFAULT_MODEL exact/tag variant -> best auto-pick from
    the installed list -> first runnable model FILE from the folders.
    Returns the model to use and prints one honest line about what
    happened (unless quiet). Fail-soft: with Ollama DOWN the current
    choice is kept untouched and nothing misleading is printed; an EMPTY
    library falls back to local model files, else prints pull guidance."""
    if nmodels is None:
        return sess.model
    down = False
    if installed is None:
        try:
            tags = http_get_json("/api/tags")
            installed = nmodels.names_of(nmodels.parse_tags(tags))
        except Exception:
            installed, down = [], True
    if down:
        return sess.model          # cannot see the library - change nothing
    chosen = sess.model
    env_model = os.environ.get("NOVA_MODEL", "").strip()
    if env_model and chosen in ("", DEFAULT_MODEL):
        chosen = env_model          # explicit NOVA_MODEL override (documented)
    # v5.2: a local FILE model is resolved against the model FOLDERS,
    # never against the Ollama tag list.
    if lmodels is not None and str(chosen).startswith(lmodels.LOCAL_PREFIX):
        if _find_local_entry(chosen, list_local_models(getattr(sess, "ws", None))) is not None:
            if not quiet:
                print(c(C.G, "[model] using local model file "
                             + chosen[len(lmodels.LOCAL_PREFIX):]
                             + "  (/model for the list)"))
            return chosen
        if not quiet:
            print(c(C.Y, "[!] local model file '" + chosen + "' is no longer"
                         " in the model folders."))
        chosen = ""                 # fall through to the normal resolution
    if chosen and installed and chosen not in installed \
            and not any(n.split(":")[0] == chosen.split(":")[0] for n in installed):
        if not quiet:
            print(c(C.Y, f"[!] model '{chosen}' is not installed on this machine."))
        chosen = ""                     # fall through to auto-pick below
    if not chosen or chosen not in installed:
        chosen = nmodels.resolve_choice(DEFAULT_MODEL, installed) or ""
    if not chosen:
        chosen = nmodels.pick_default(installed)
    if not chosen:
        # v5.2: no Ollama model, but maybe the user dropped a model file
        # into a models folder - that is a perfectly good brain too.
        # v6.1: prefer GENERAL then code-category files; a model from
        # local/voice or local/photo is a specialist and stays a fallback.
        loc = [e for e in list_local_models(getattr(sess, "ws", None))
               if e.get("runnable")]
        loc.sort(key=lambda e: {"general": 0, "code": 1}
                 .get(e.get("category", "general"), 2))
        if loc:
            chosen = loc[0]["id"]
            if not quiet:
                print(c(C.G, "[model] no Ollama model installed - using the"
                             " local model file " + loc[0]["name"]))
            return chosen
        if not quiet:
            print(c(C.Y, "[!] no models available yet. Either pull one:"))
            print(c(C.D, "      ollama pull qwen2.5-coder:3b"))
            print(c(C.D, "    or drop a .gguf file into a models folder"
                         " (see /model - folders: NOVA_MODELS_DIR, ~/.nova/models)."))
            print(c(C.D, "    Nova starts anyway - chat needs at least one model."))
        return sess.model or ""
    if chosen != sess.model and not quiet:
        print(c(C.G, "[model] using " + chosen + "  (change any time:  /model)"))
    return chosen

def cmd_model(sess, arg):
    """v6.1: TWO ways to pick a local brain, one table:
      [Ollama]  every model pulled into the local Ollama library
      [Files]   model files in the model folders (NOVA_MODELS_DIR,
                <app>/local, ~/.nova/models, .nova/models) - imported
                once on demand. A [cat] tag shows the category folder
                the file lives in (code/voice/photo/general)."""
    cfg = _provider_cfg()
    if not arg:
        print(f"Current model : {sess.model}{_model_route_note(sess)}")
        print(f"Provider      : {cfg['label']} ({cfg.get('kind', 'ollama')})")
        if cfg.get("kind", "ollama") == "ollama":
            models = list_models_detailed()
            locals_ = list_local_models(sess.ws, force=True)
            n_oll = len(models)
            if models:
                print(c(C.B, f"\n  Ollama models ({n_oll}):"))
                for i, name, size, desc in nmodels.table_rows(models):
                    line = f"  {i:>3}  {name}"
                    if size:
                        line += f"  ({size})"
                    if desc:
                        line += c(C.D, "   " + desc)
                    mark = c(C.G, " *") if name == sess.model else "  "
                    print(mark + line)
                note = nmodels.table_overflow_note(models)
                if note:
                    print(c(C.D, "      " + note))
            else:
                # v5.2 fix: an EMPTY library must not claim Ollama is down
                if _ollama_alive():
                    print(c(C.D, "\n  Ollama models: (none installed yet -"
                                 " pull one, or use the local files below)"))
                else:
                    print(c(C.Y, "\n  Ollama models : (could not read -"
                                 " is Ollama running?)"))
            if lmodels is not None:
                if locals_:
                    print(c(C.B, f"\n  Local model files ({len(locals_)}):")
                          + c(C.D, "  model files in your model folders"
                                   " (local/, local/code, local/voice, local/photo...)"))
                    dirs = lmodels.model_dirs(sess.ws)
                    folders = ", ".join(str(p) for _l, p, _e in dirs)
                    print(c(C.D, f"  folders: {folders}"))
                    cap = nmodels.table_limit() if nmodels else 20
                    for j, e in enumerate(locals_[:cap], n_oll + 1):
                        size_s = _model_fmt_size(e.get("size"))
                        desc = " · ".join(p for p in (e.get("arch"), e.get("params"),
                                                      e.get("quant")) if p)
                        if e.get("part_total", 1) > 1:
                            desc += (f" · {e['parts']}/{e['part_total']} parts"
                                     if desc else f"{e['parts']}/{e['part_total']} parts")
                        cat = e.get("category", "general")
                        line = f"  {j:>3}  {e['name']}  [{e['format']}]"
                        if cat != "general":
                            line += c(C.B, f" [{cat}]")
                        if size_s:
                            line += f"  ({size_s})"
                        if desc:
                            line += c(C.D, "   " + desc.strip(" ·"))
                        if not e.get("runnable", False):
                            line += c(C.Y, "   (not runnable"
                                           + (": " + e["note"] if e.get("note") else "") + ")")
                        mark = c(C.G, " *") if e["id"] == sess.model else "  "
                        print(mark + line)
                    extra = len(locals_) - cap
                    if extra > 0:
                        print(c(C.D, f"      ... and {extra} more local files"))
                else:
                    print(c(C.D, "\n  Local model files: none found - drop model files"
                                 " into a models folder:"))
                    dirs = lmodels.model_dirs(sess.ws) if lmodels else []
                    for _l, p, exists in dirs:
                        print(c(C.D, f"      {p}" + ("" if exists else "   (will be created on use)"
                                                     if _l == "project" else "")))
                    print(c(C.D, "      categories: <folder>/code  <folder>/voice"
                                 "  <folder>/photo   (or the folder root = general)"))
            print(c(C.D, "\n  Switch: /model <name>   or by row number: /model 2"
                         "   (numbers run across BOTH sections)"))
            print(c(C.D, "  Pull more:  ollama pull <model>   (browse: https://ollama.com/library)"))
        else:
            print(c(C.D, "Any model name of this provider works:  /model <name>   (see their model catalog)"))
        return
    if cfg.get("kind", "ollama") == "ollama":
        installed = list_installed_models()
        full = nmodels.resolve_choice(arg, installed) if installed else None
        if full is not None:
            sess.model = full
            sess.save_profile_field("model", full)
            print(c(C.G, "Model set: " + full))
            return
        # not an Ollama model - try the LOCAL FILE section (by name or row)
        if lmodels is not None:
            locals_ = list_local_models(sess.ws, force=True)
            entry = _match_local_entry(arg, locals_, installed_count=len(installed))
            if entry is not None:
                _select_local_file(sess, entry)
                return
            if not installed:
                print(c(C.Y, "[!] cannot reach Ollama (or no models installed)."
                             "  Start it with:  ollama serve"))
            else:
                print(c(C.Y, f"[!] '{arg}' matches no Ollama model and no local"
                             " model file."))
            print(c(C.D, "    Pull it:  ollama pull " + arg
                         + "   |   see what exists:  /model"))
            return
        print(c(C.Y, "[!] cannot reach Ollama (or no models installed)."
                     "  Start it with:  ollama serve"))
        return
    sess.model = arg
    sess.save_profile_field("model", arg)
    print(c(C.G, "Model set: " + arg + "  (provider: " + cfg["label"] + ")"))


def cmd_provider(sess, arg):
    """Show or switch the AI provider - the brain behind the SAME agent.
    The local Ollama library (any installed model) stays one command
    away:  /provider ollama   then  /model  to pick one."""
    if providers is None:
        print(c(C.Y, "[!] nova_providers.py is missing next to nova.py - only Ollama works."))
        return
    parts = arg.split()
    if not parts:
        cfg = _provider_cfg()
        print(f"Provider : {cfg['label']} ({cfg['kind']})   model: {sess.model}")
        print(c(C.B, f"Available providers ({len(providers.names())}):"))
        for name in providers.names():
            info = providers.entry(name) or {}
            if info.get("kind") == "ollama":
                key = c(C.G, "local - no key needed")
            elif not info.get("needs_key", True):
                key = c(C.G, "local - no key needed")
            else:
                is_set, masked = providers.key_status(name)
                src = providers.key_source(name)
                where = ".nova/providers.json" if src == "file" else f"env {info.get('key_env') or '?'}"
                key = ((c(C.G, "key set (" + masked + ")") if is_set
                        else c(C.Y, "key MISSING")) + f" - {where}")
            mark = "*" if name == cfg.get("name") else " "
            custom_mark = c(C.P, " [custom]") if name not in providers.PROVIDERS else ""
            print(f"  {mark} {name:<14} {info.get('label', ''):<26} {key}{custom_mark}")
        print(c(C.D, "Switch:  /provider <name> [model]    e.g.:  /provider openai   |"
                 "   /provider groq llama-3.3-70b-versatile"))
        print(c(C.D, "Keys:    /key <provider> <the-key>     Models:  /catalog <provider>"))
        print(c(C.D, "Sections (per-task brains):  /brain      Custom:  /custom add ..."))
        print(c(C.D, "Back to the local brain:  /provider ollama"))
        return
    name = parts[0].lower()
    model = parts[1].strip() if len(parts) > 1 else None
    try:
        cfg = providers.set_provider(name, model=model)
    except Exception as e:
        if providers is not None and isinstance(e, providers.ProviderError):
            print(c(C.R, "[!] " + str(e)))
            return
        raise
    sess.model = cfg["model"] or ""
    if cfg["kind"] == "ollama":
        # No hardcoded default any more: resolve against what IS installed
        # (exact / tag variant / best auto-pick) so /provider ollama can
        # never strand the session on a model this machine does not have.
        sess.model = resolve_session_model(sess, quiet=True)
        print(c(C.G, f"Provider set: {cfg['label']}   (model: {sess.model or 'none yet - see /model'})"))
        if sess.model:
            # explicit switch -> pin it (overwrites any stale cloud model
            # left in the profile); startup auto-picks stay unpinned
            sess.save_profile_field("model", sess.model)
    else:
        print(c(C.G, f"Provider set: {cfg['label']}   (model: {sess.model})"))
        sess.save_profile_field("model", sess.model)
    sess.save_profile_field("provider", cfg["name"])    # v5.0 per-project profile
    if cfg["kind"] != "ollama":
        print(c(C.D, "Cloud brain active - your files and tools stay local. "
                     "Back anytime:  /provider ollama"))


# ------------------------------------------------------- v6.6 provider suite
def _provider_exists(name):
    return providers is not None and providers.entry(name) is not None


def cmd_key(sess, arg):
    """v6.6: set/list provider API keys. Keys live in the workspace vault
    (.nova/providers.json, chmod 600 on POSIX); env vars keep working and
    the vault wins when both exist. Saving a key AUTO-DETECTS the
    provider's models (one GET, cached for a day)."""
    if providers is None:
        print(c(C.Y, "[!] nova_providers.py is missing - key management unavailable."))
        return
    parts = arg.split(maxsplit=1) if arg else []
    if not parts:
        print(c(C.B, "API keys (the vault wins over env vars):"))
        for name in providers.names():
            info = providers.entry(name) or {}
            if info.get("kind") == "ollama" or not info.get("needs_key", True):
                print(f"  {name:<14} {'-' * 12}  local - no key needed")
                continue
            is_set, masked = providers.key_status(name)
            src = providers.key_source(name)
            mark = (c(C.G, "set  ") if is_set else c(C.Y, "MISS ")) + masked
            print(f"  {name:<14} {mark}  ({'vault' if src == 'file' else 'env ' + (info.get('key_env') or '?')})")
        print(c(C.D, "Set:    /key <provider> <the-key>      e.g.  /key groq gsk_..."))
        print(c(C.D, "Clear:  /key <provider> clear          Detect:  /catalog <provider>"))
        return
    name = parts[0].strip().lower()
    val = parts[1].strip() if len(parts) > 1 else ""
    if not _provider_exists(name):
        print(c(C.Y, f"[!] unknown provider '{name}'. See:  /provider"))
        return
    info = providers.entry(name) or {}
    if info.get("kind") == "ollama":
        print(c(C.Y, f"[!] '{name}' is the local Ollama - it needs no key."))
        return
    if not val:
        is_set, masked = providers.key_status(name)
        print(f"  {name}: " + (f"key set ({masked}), source: {providers.key_source(name)}"
                              if is_set else "no key"))
        print(c(C.D, "Set:  /key " + name + " <the-key>"))
        return
    if val.lower() in ("clear", "del", "remove", "off", "delete"):
        err = providers.del_key(sess.ws, name)
        print(c(C.G, f"  key removed from the vault ({err or 'ok'})"
                     + ("" if err else " - an env var takes over again if one is set")))
        return
    if len(val) > 400:
        print(c(C.Y, "[!] that key is too long to be real (400 char cap)."))
        return
    err = providers.set_key(sess.ws, name, val)
    if err:
        print(c(C.R, "[!] " + err))
        return
    is_set, masked = providers.key_status(name)
    print(c(C.G, f"  key saved for {name} ({masked}) - stored in .nova/providers.json"))
    # v6.6 headline feature: detect the models this key can use, right now
    try:
        models = providers.discover(name, force=True, timeout=10)
        print(c(C.G, f"  model detection: {len(models)} models found"))
        for m in models[:10]:
            print("    - " + m)
        if len(models) > 10:
            print(c(C.D, f"    ... and {len(models) - 10} more  (/catalog {name})"))
        if models:
            print(c(C.D, f"  use one anywhere:  /brain talk {name}/{models[0]}"))
    except Exception as e:
        msg = str(e) if not isinstance(e, providers.ProviderError) else str(e)
        print(c(C.Y, f"  key saved, but model detection failed: {msg}"))
        print(c(C.D, f"  you can still type the model name yourself:  /provider {name} <model>"))


def cmd_catalog(sess, arg):
    """v6.6: list the models of one provider (auto-detected from its API;
    cached - at most one request per provider per day)."""
    if providers is None:
        print(c(C.Y, "[!] nova_providers.py is missing."))
        return
    name = arg.strip().lower() or _provider_cfg().get("name", "ollama")
    if not _provider_exists(name):
        print(c(C.Y, f"[!] unknown provider '{name}'. See:  /provider"))
        return
    if (providers.entry(name) or {}).get("kind") == "ollama":
        detailed = list_models_detailed()
        if not detailed:
            print(c(C.Y, "[!] cannot reach Ollama (or nothing installed)."
                         "  ollama pull <model>"))
            return
        print(c(C.B, f"Ollama models ({len(detailed)}):"))
        for i, mname, size, desc in nmodels.table_rows(detailed):
            line = f"  {i:>3}  {mname}"
            if size:
                line += f"  ({size})"
            if desc:
                line += "   " + desc
            print(line)
        return
    print(c(C.D, f"Detecting models for '{name}' (cached for a day) ..."))
    try:
        models = providers.discover(name, force=False, timeout=10)
    except Exception as e:
        print(c(C.R, "[!] " + str(e)))
        return
    if not models:
        print(c(C.Y, "[!] the provider returned no models - type the name manually:"
                     f"  /provider {name} <model>"))
        return
    print(c(C.B, f"{providers.entry(name).get('label', name)} models ({len(models)}):"))
    for i, m in enumerate(models[:60], 1):
        print(f"  {i:>3}  {m}")
    if len(models) > 60:
        print(c(C.D, f"  ... and {len(models) - 60} more"))
    print(c(C.D, f"Switch the whole agent:  /provider {name} <model>"))
    print(c(C.D, f"Use one for ONE section:  /brain <section> {name}/<model>"))


def cmd_think(sess, arg):
    """v7.14: show or flip the THINK protocol (visible reasoning).
      /think            -> current mode + whether the serving brain reasons
                           natively or gets the forced protocol
      /think auto       -> force reasoning ONLY for models without their own
      /think on         -> force the === THINK === block for EVERY brain
      /think off        -> no forced block (native <think> still captured)
    Stored per workspace in .nova/think.json."""
    if think is None:
        print(c(C.Y, "[!] nova_think.py is missing - the THINK layer is "
                     "unavailable."))
        return
    a = (arg or "").strip().lower()
    if a in think.MODES:
        try:
            think.set_mode(sess.ws, a)
        except Exception as e:
            print(c(C.R, "[!] " + str(e)))
            return
    elif a and a not in ("status", "?"):
        print(c(C.Y, "[!] usage: /think [auto|on|off]"))
        return
    m = think.mode(sess.ws)
    serve = getattr(sess, "_think_model", "") or sess.model
    native = think.capable(serve)
    forced = think.should_force(sess.ws, serve)
    label = {"auto": "خودکار", "on": "همیشه روشن",
             "off": "خاموش"}.get(m, m)
    print(c(C.B, "تفکر مدل (THINK): " + label))
    print(c(C.D, "  مغز فعال: " + str(serve)
                 + ("  [استدلال بومی]" if native
                    else "  [استدلال اجباری با پروتکل THINK]")))
    print(c(C.D, "  این نوبت: " + ("بلوک فکر اجباری دارد"
                                   if forced else "بدون بلوک اجباری")))
    print(c(C.D, "  فرمت:  === THINK === ... === END ===  پیش از پاسخ"))
    print(c(C.D, "  خاموش‌سازی کامل: NOVA_THINK=0  (هر بلوک <think> بومی "
                 "همچنان از پاسخ جدا می‌شود)"))


def cmd_brain(sess, arg):
    """v6.6: per-section brains. Each section can run on its OWN
    provider+model - a big careful brain for coding, a fast cheap one for
    talk and utility calls. Stored per workspace."""
    if providers is None:
        print(c(C.Y, "[!] nova_providers.py is missing."))
        return
    parts = arg.split()
    if not parts:
        cfg = _provider_cfg()
        print(c(C.B, "Per-section brains (empty = the active brain, "
                     f"{cfg.get('name')}/{sess.model}):"))
        for sec in providers.SECTIONS:
            target = providers.route_target(sec)
            label = providers.SECTION_LABELS.get(sec, sec)
            if target:
                print(f"  {sec:<9} -> {c(C.G, target):<50} {label}")
            else:
                print(f"  {sec:<9} -> {c(C.D, '(active brain)'):<50} {label}")
        print(c(C.D, "Set:  /brain <section> <provider/model>   e.g.  /brain talk groq/llama-3.3-70b-versatile"))
        print(c(C.D, "Clear:  /brain <section> off"))
        return
    sec = parts[0].lower()
    if sec not in providers.SECTIONS:
        print(c(C.Y, f"[!] unknown section '{sec}'. Sections: "
                     + ", ".join(providers.SECTIONS)))
        return
    if len(parts) == 1:
        t = providers.route_target(sec)
        print(f"  {sec}: " + (t or "(active brain)"))
        return
    target = " ".join(parts[1:]).strip()
    err = providers.set_route(sess.ws, sec, target)
    if err:
        print(c(C.R, "[!] " + err))
        return
    if target and target.lower() not in ("off", "none", "clear", "default"):
        print(c(C.G, f"  {sec} brain -> {target}"))
        print(c(C.D, "  (the key must exist:  /key "
                     + target.split('/')[0] + " <the-key>  - see /brain)"))
    else:
        print(c(C.G, f"  {sec} back on the active brain"))


def cmd_custom(sess, arg):
    """v6.6: user-defined providers - any OpenAI-compatible (or
    Anthropic/Gemini-wire) endpoint with a name of your choice."""
    if providers is None:
        print(c(C.Y, "[!] nova_providers.py is missing."))
        return
    parts = arg.split()
    if not parts or parts[0] in ("list", "ls"):
        customs = providers.customs()
        if not customs:
            print(c(C.D, "No custom providers yet."))
            print(c(C.D, "Add:  /custom add <name> <base-url> [model] [kind]"
                         "   e.g.  /custom add relay https://my.box/v1 qwen2.5-coder-7b"))
            return
        print(c(C.B, f"Custom providers ({len(customs)}):"))
        for ct in customs:
            is_set, masked = providers.key_status(ct["name"])
            key = c(C.G, "key " + masked) if is_set else c(C.Y, "no key")
            print(f"  {ct['name']:<14} {ct['kind']:<9} {ct['base']}  "
                  f"model: {ct.get('model') or '?'}  {key}")
        print(c(C.D, "Remove:  /custom del <name>"))
        return
    sub = parts[0].lower()
    if sub == "add":
        vals = arg.split(maxsplit=4)
        # /custom add <name> <base> [model] [kind]
        if len(vals) < 3:
            print(c(C.Y, "[!] usage: /custom add <name> <base-url> [model] [kind(openai|anthropic|gemini)]"))
            return
        name, base = vals[1].lower(), vals[2]
        model = ""
        kind = "openai"
        # v6.7 fix: vals was built with split(maxsplit=4), so vals[3] is
        # ALREADY one whitespace-free token - the old vals[3].split()
        # always produced a 1-element list and the kind argument
        # (vals[4]) was silently ignored: an Anthropic/Gemini endpoint
        # was saved with the OpenAI wire format and every call failed.
        rest = vals[3:] if len(vals) > 3 else []
        if rest:
            model = rest[0]
            if len(rest) > 1 and rest[1].lower() in ("openai", "anthropic", "gemini"):
                kind = rest[1].lower()
        err = providers.add_custom(sess.ws, name, base, model=model, kind=kind)
        if err:
            print(c(C.R, "[!] " + err))
            return
        print(c(C.G, f"  custom provider '{name}' saved ({kind} wire to {base})"))
        if model:
            print(c(C.D, f"  use it:  /provider {name}   |   route it:  /brain talk {name}/{model}"))
        else:
            print(c(C.D, f"  set its model:  /provider {name} <model>   "
                         "or detect:  /catalog " + name))
        return
    if sub in ("del", "remove", "rm"):
        if len(parts) < 2:
            print(c(C.Y, "[!] usage: /custom del <name>"))
            return
        err = providers.del_custom(sess.ws, parts[1].lower())
        if err:
            print(c(C.R, "[!] " + err))
            return
        print(c(C.G, f"  custom provider '{parts[1].lower()}' removed "
                     "(key + routing cleaned too)"))
        return
    print(c(C.Y, "[!] usage: /custom [list | add <name> <base> [model] [kind] | del <name>]"))


def cmd_saver(sess, arg):
    """v6.6: the request economy - what Nova SAVED (tokens, credits,
    requests) and the budget caps. Every utility answer served from the
    local cache is a request that never touched the provider."""
    if providers is None:
        print(c(C.Y, "[!] nova_providers.py is missing."))
        return
    parts = arg.split()
    eco = providers.economy()
    if not parts:
        st = econ.stats(sess.ws) if econ is not None else {"counters": {}}
        cnt = st.get("counters", {})
        mt = eco.get("max_tokens", {})
        print(c(C.B, "Request economy (this workspace, today):"))
        print(f"  responses cached      : {cnt.get('cache_hits', 0)}"
              f"  (cache {'ON' if eco.get('cache') else 'OFF'}"
              f"{', talk ' + ('ON' if eco.get('cache_talk', True) else 'OFF')})")
        print(f"  requests saved        : {cnt.get('requests_saved', 0)}")
        print(f"  tokens saved (est.)   : {cnt.get('tokens_saved', 0):,}")
        print(f"  requests blocked      : {cnt.get('blocked', 0)}"
              f"  (daily budget guards)")
        print(f"  output caps           : talk={mt.get('talk', 0) or 'off'}"
              f"  utility={mt.get('utility', 0) or 'off'}  coding={'off' if not mt.get('coding') else mt.get('coding')}")
        print(f"  daily budget          : ${eco.get('daily_budget_usd', 0) or 0:g}"
              f"  /  {eco.get('daily_token_budget', 0) or 0:,} tokens  (0 = unlimited)")
        print(c(C.D, "Toggle the cache:  /saver cache on|off      Budget:  /saver budget <usd>"))
        print(c(C.D, "Talk cache (resends): /saver talkcache on|off"))
        print(c(C.D, "Token budget:      /saver tokens <n>          (local Ollama: all free)"))
        return
    sub = parts[0].lower()
    if sub == "cache" and len(parts) > 1 and parts[1].lower() in ("on", "off"):
        want = parts[1].lower() == "on"
        err = providers.set_economy(sess.ws, {"cache": want})
        print(c(C.G, f"  response cache {'ON' if want else 'OFF'}"
                     + ("" if not err else " - " + err)))
        return
    if sub == "talkcache" and len(parts) > 1 and parts[1].lower() in ("on", "off"):
        # v7.8: identical RESENT talk turns served from the local cache
        want = parts[1].lower() == "on"
        err = providers.set_economy(sess.ws, {"cache_talk": want})
        print(c(C.G, f"  talk response cache {'ON' if want else 'OFF'}"
                     + ("" if not err else " - " + err)))
        return
    if sub == "budget" and len(parts) > 1:
        try:
            v = float(parts[1])
        except ValueError:
            print(c(C.Y, "[!] usage: /saver budget <usd-per-day>  (0 = unlimited)"))
            return
        err = providers.set_economy(sess.ws, {"daily_budget_usd": max(0.0, v)})
        print(c(C.G, f"  daily budget: ${max(0.0, v):g}" + ("" if not err else " - " + err)))
        return
    if sub == "tokens" and len(parts) > 1 and parts[1].isdigit():
        err = providers.set_economy(sess.ws, {"daily_token_budget": max(0, int(parts[1]))})
        print(c(C.G, f"  daily token budget: {max(0, int(parts[1])):,}"
                     + ("" if not err else " - " + err)))
        return
    if sub == "clear":
        if econ is not None:
            econ.cache_clear(sess.ws)
            print(c(C.G, "  response cache cleared (counters kept)."))
        return
    print(c(C.Y, "[!] usage: /saver [cache on|off | talkcache on|off | "
                 "budget <usd> | tokens <n> | clear]"))


# ------------------------------------------------------- v6.6: web helpers
def web_ctx_state(sess):
    """v8.3: everything the web Context Engine panel needs - effective
    windows, compression settings and the live usage estimate. Fail-soft:
    a missing engine module still returns the global defaults."""
    cs = getattr(sess, "ctx_settings", None) or {}
    local = NUM_CTX
    cloud = max(2048, _envint("NOVA_CLOUD_CTX", 16384))
    custom = False
    if ctxengine is not None and cs.get("custom"):
        custom = True
        if isinstance(cs.get("local_ctx"), int):
            local = cs["local_ctx"]
        if isinstance(cs.get("cloud_ctx"), int):
            cloud = cs["cloud_ctx"]
    try:
        win = sess._prompt_ctx()
        used = sess._ctx_used_tokens()
        backend = "local" if sess._local_brain() else "cloud"
    except Exception:
        win, used, backend = local, 0, "local"
    return {"local_ctx": local, "cloud_ctx": cloud,
            "auto_compact": bool(cs.get("auto_compact", True)),
            "threshold": cs.get("compact_threshold", 0.85),
            "keep_recent": cs.get("keep_recent", 4),
            "custom": custom, "backend": backend,
            "win": win, "used": used,
            "ratio": round(used / max(1, win), 2),
            "history": len(getattr(sess, "history", [])),
            "bounds": {"local_min": 512, "local_max": 262144,
                       "cloud_min": 2048, "cloud_max": 4000000,
                       "threshold_min": 0.5, "threshold_max": 0.95,
                       "keep_min": 2, "keep_max": 16}}


def web_guardian_state(sess):
    """v8.4: everything the web Code Guardian panel needs - the four
    switches, the fleet size and the external validators found on THIS
    machine. Fail-soft: a missing module still returns a sane payload."""
    s = getattr(sess, "guardian_settings", None) or {}
    out = {"on": True, "model": True, "web": True, "reject_syntax": True,
           "custom": False, "langs": 0, "tools": []}
    if guardian is not None:
        out.update({k: guardian.enabled(s, k)
                    for k in ("on", "model", "web", "reject_syntax")})
        out["custom"] = bool(s.get("custom"))
        out["langs"] = guardian.lang_count()
        try:
            out["tools"] = guardian.tools_available()
        except Exception:
            out["tools"] = []
    out["env_off"] = os.environ.get("NOVA_GUARDIAN", "") == "0"
    return out


def web_probe_state(sess):
    """v8.5: everything the web Bug Hunter panel needs - the six
    switches plus what THIS machine can actually do (playwright?).
    v8.6: the deep-sweep switches joined the payload. Fail-soft: a
    missing module still returns a sane payload."""
    s = getattr(sess, "probe_settings", None) or {}
    keys = ("on", "wiring", "deep", "smoke", "browser", "review",
            "reject_wiring", "reject_deep")
    out = {k: True for k in keys}
    out.update({"custom": False, "playwright": False,
                "env_off": os.environ.get("NOVA_PROBE", "") == "0"})
    if probe is not None:
        out.update({k: probe.enabled(s, k) for k in keys})
        out["custom"] = bool(s.get("custom"))
        try:
            out["playwright"] = probe.playwright_available()
        except Exception:
            out["playwright"] = False
    return out


def web_vision_state(sess):
    """v8.6: everything the web Vision panel needs - the LIVE answer to
    'can the active local brain see photos?' plus the approval policy.
    Fail-soft: a missing module still returns a sane payload."""
    out = {"vision": False, "via": "", "detail": "", "approve": True,
           "strict": False, "custom": False, "model": "",
           "backend": "local",
           "env_off": os.environ.get("NOVA_VISION_SHOW", "") == "0"}
    try:
        lcfg = _provider_cfg() or {}
    except Exception:
        lcfg = {}
    out["model"] = str(lcfg.get("model") or getattr(sess, "model", ""))
    out["backend"] = "local" if _is_free_local(lcfg) else "cloud"
    if vision is not None:
        s = getattr(sess, "vision_settings", None) or {}
        out["approve"] = vision.enabled(s, "approve")
        out["strict"] = vision.enabled(s, "strict")
        out["custom"] = bool(s.get("custom"))
        try:
            cap = _vision_capability(lcfg)
            out.update({"vision": bool(cap.get("vision")),
                        "via": str(cap.get("via") or ""),
                        "detail": str(cap.get("detail") or "")})
        except Exception:
            pass
    return out


def web_providers_state(sess):
    """Everything the web provider panel needs in ONE payload. Keys are
    masked (last 4 chars max) - a full key never goes to the browser."""
    if providers is None:
        return {"providers": [], "sections": [], "routing": {},
                "economy": {}, "stats": {}, "error": "provider layer missing"}
    out = []
    for name in providers.names():
        e = providers.entry(name) or {}
        is_set, masked = providers.key_status(name)
        try:
            models = providers.cached_models(name)[:200]
        except Exception:
            models = []
        out.append({
            "id": name, "label": e.get("label", name), "kind": e.get("kind", ""),
            "base": e.get("base", ""), "local": not e.get("needs_key", True),
            "custom": name not in providers.PROVIDERS,
            "key_set": is_set, "key_masked": masked,
            "key_env": e.get("key_env") or "",
            "model_default": e.get("model", ""), "models": models,
        })
    try:
        routing = providers.routing()
        eco = providers.economy()
    except Exception:
        routing, eco = {}, {}
    # v7.9 audit fix: a one-time migration hint - v7.8 stored b.ai keys
    # in the vault row 'blackbox' (then b.ai was guessed to be Blackbox);
    # v7.9 split them, so an old b.ai key now silently belongs to the
    # separate blackbox provider. Tell the user instead of staying mum.
    notes = []
    try:
        _by_id = {p["id"]: p for p in out}
        if _by_id.get("blackbox", {}).get("key_set") \
                and not _by_id.get("bai", {}).get("key_set"):
            notes.append(
                "کلید قدیمی b.ai شما روی پروایدر Blackbox ثبت شده (تقسیم "
                "v7.9) - اگر منظورتان سرویس واقعی b.ai است، کلید را برای "
                "B.AI هم وارد کنید.")
    except Exception:
        pass
    st = econ.stats(sess.ws) if econ is not None else {}
    # v7.9: what the clouds ACTUALLY consumed - requests / tokens /
    # credit-equivalent / context of the last request. The panel renders
    # it next to the savings counters.
    usage = {}
    if nova_cost is not None:
        try:
            usage = nova_cost.usage_summary(sess.ws)
        except Exception:
            usage = {}
    return {
        "providers": out,
        "sections": [{"id": s, "label": providers.SECTION_LABELS.get(s, s)}
                     for s in providers.SECTIONS],
        "routing": routing, "economy": eco, "stats": st,
        "usage": usage,
        "notes": notes,
        "active": _provider_cfg().get("name", "ollama"),
    }


def web_providers_action(sess, data):
    """One mutation from the web provider panel. Returns (ok, payload,
    http_status). NEVER echoes a full key back."""
    if providers is None:
        return (False, {"error": "provider layer missing"}, 501)
    action = str(data.get("action", "")).strip()
    if action == "set_key":
        name = str(data.get("provider", "")).strip().lower()
        key = str(data.get("key", "")).strip()
        if not _provider_exists(name):
            return (False, {"error": f"unknown provider '{name}'"}, 404)
        if not key or len(key) > 400:
            return (False, {"error": "key must be 1-400 characters"}, 400)
        e = providers.entry(name) or {}
        if e.get("kind") == "ollama":
            return (False, {"error": "ollama needs no key"}, 400)
        err = providers.set_key(sess.ws, name, key)
        if err:
            return (False, {"error": err}, 400)
        detected, det_err = [], ""
        try:
            detected = providers.discover(name, force=True, timeout=10)
        except Exception as ex:
            det_err = str(ex)[:300]
        return (True, {"ok": True, "key_masked": providers.key_status(name)[1],
                       "models_found": len(detected), "models": detected[:200],
                       "discover_error": det_err}, 200)
    if action == "del_key":
        name = str(data.get("provider", "")).strip().lower()
        if not _provider_exists(name):
            return (False, {"error": f"unknown provider '{name}'"}, 404)
        providers.del_key(sess.ws, name)
        return (True, {"ok": True}, 200)
    if action == "discover":
        name = str(data.get("provider", "")).strip().lower()
        if not _provider_exists(name):
            return (False, {"error": f"unknown provider '{name}'"}, 404)
        try:
            models = providers.discover(name, force=True, timeout=10)
        except Exception as ex:
            return (False, {"error": str(ex)[:300]}, 502)
        return (True, {"ok": True, "models_found": len(models),
                       "models": models[:200]}, 200)
    if action == "custom_add":
        err = providers.add_custom(
            sess.ws, str(data.get("name", "")), str(data.get("base", "")),
            model=str(data.get("model", "")),
            kind=str(data.get("kind", "openai")),
            label=str(data.get("label", "")))
        if err:
            return (False, {"error": err}, 400)
        return (True, {"ok": True}, 200)
    if action == "custom_del":
        err = providers.del_custom(sess.ws, str(data.get("name", "")))
        if err:
            return (False, {"error": err}, 404)
        return (True, {"ok": True}, 200)
    if action == "route":
        sec = str(data.get("section", "")).strip().lower()
        target = str(data.get("target", "")).strip()
        err = providers.set_route(sess.ws, sec, target)
        if err:
            return (False, {"error": err}, 400)
        return (True, {"ok": True, "routing": providers.routing()}, 200)
    if action == "economy":
        updates = data.get("updates")
        if not isinstance(updates, dict):
            return (False, {"error": "updates must be an object"}, 400)
        err = providers.set_economy(sess.ws, updates)
        if err:
            return (False, {"error": err}, 400)
        return (True, {"ok": True, "economy": providers.economy()}, 200)
    if action == "cost_reset":
        # v7.9: the usage panel's clear button (same as /cost reset).
        if nova_cost is None:
            return (False, {"error": "cost tracking unavailable"}, 501)
        err = nova_cost.reset(sess.ws)
        if err:
            return (False, {"error": err}, 500)
        return (True, {"ok": True, "usage": nova_cost.usage_summary(sess.ws)}, 200)
    return (False, {"error": "unknown action"}, 400)


# ------------------------------------------------------- v7.11 iran services
def web_iran_state(sess):
    """Payload for the web 'سرویس‌های ایرانی' panel: catalog + masked key
    status + per-service usage metering. Missing module degrades."""
    if iran is None:
        return {"categories": [], "services": [], "usage": {},
                "error": "nova_iran_services.py missing"}
    try:
        return iran.web_state(sess.ws)
    except Exception as e:
        return {"categories": [], "services": [],
                "usage": {}, "error": str(e)[:300]}


def web_iran_action(sess, data):
    """One mutation from the web panel: set_key / del_key / test / call.
    (ok, payload, http_status) - same shape as web_providers_action."""
    if iran is None:
        return (False, {"error": "nova_iran_services.py missing"}, 501)
    try:
        return iran.web_action(sess.ws, data)
    except Exception as e:
        return (False, {"error": str(e)[:300]}, 500)


# ================================================================ v7.12
# WEB SEARCH IN THE SIMPLE CHAT (گفت و گو tab)
# ---------------------------------------------------------------
# The talk turn used to be pure model weights - every "قیمت دلار امروز"
# question got a confident stale guess. v7.12 attaches a compact
# [WEB RESULTS] block to the turn when its wording implies fresh facts.
# Everything here is pure or file-atomic, so the tests can pin the
# heuristics without a server and without network.

TALK_WEB_FILE = ".nova/talk_web.json"
TALK_WEB_MODES = ("off", "auto", "always")
TALK_WEB_DEFAULT = "auto"
TALK_WEB_MAX_RESULTS = 6          # sources per turn (context diet)
TALK_WEB_SNIPPET_CAP = 240        # per-result snippet cap
TALK_WEB_QUERY_CAP = 120          # search query cap

# Recency / volatility markers that make cached weights a BAD answer.
# Persian first (ZWNJ is stripped before matching), English second.
_TALK_WEB_TRIGGERS = (
    # news / recency
    "اخبار", "خبر ", "خبری", "آخرین", "جدیدترین", "امروز", "امشب",
    "این هفته", "این ماه", "سال جاری", "به تازگی", "الان چه",
    "news", "latest", "today", "this week", "this month", "recent",
    "breaking", "current", "update", "up to date", "uptodate",
    # prices / markets / money
    "قیمت", "نرخ", "تومان", "دلار", "یورو", "ارز", "بورس", "سکه",
    "طلا", "بیت کوین", "ارز دیجیتال", "کریپتو",
    "price", "cost of", "rate of", "exchange", "bitcoin", "crypto",
    # weather / time-sensitive
    "آب و هوا", "هواشناسی", "دمای", "weather", "temperature in",
    "forecast",
    # sports / results / schedules
    "نتیجه بازی", "جدول رتبه", "رتبه بندی", "برنامه بازی", "زنده",
    "score", "standings", "fixture", "schedule",
    # explicit search intent ("جستوجو" = the ZWNJ-stripped form of
    # "جست‌وجو" - _talk_web_norm merges the word, so both spellings needed)
    "جستجو کن", "جستجو", "جستوجو", "جست و جو", "سرچ کن", "سرچ",
    "گوگل کن", "در اینترنت", "توی اینترنت", "از وب", "برام پیدا کن",
    "پیدا کن",
    "search for", "search about", "google", "look up", "browse the web",
    "on the internet", "find online",
)

# greetings / phatic lines never need a search (auto mode quiet)
_TALK_WEB_MIN_LEN = 12

_TALK_WEB_YEAR_RE = re.compile(r"\b20(?:2[5-9]|[3-9]\d)\b")   # 2025+
# solar-hijri years 1400+ (checked AFTER Persian digit folding -> ASCII)
_TALK_WEB_FA_YEAR_RE = re.compile(r"\b14[0-4]\d\b")


def _talk_web_norm(text):
    """Lowercase + strip ZWNJ/zero-width + Persian digit folding so the
    trigger list matches real chat input ('جست‌وجو' == 'جستوجو')."""
    t = str(text or "").lower()
    t = t.replace("\u200c", "").replace("\u200f", "").replace("\u200e", "")
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    for i, d in enumerate(fa_digits):
        t = t.replace(d, str(i))
    ar_digits = "٠١٢٣٤٥٦٧٨٩"
    for i, d in enumerate(ar_digits):
        t = t.replace(d, str(i))
    return t


def talk_needs_web(text, mode=None):
    """v7.12: should this talk turn carry web results?

    mode 'always' -> True, 'off' -> False, 'auto'/None -> heuristic:
    a recency/price/news/search-intent marker (or a forward year) inside
    a non-phatic message. Deliberately CONSERVATIVE - a wrong 'no' costs
    one stale answer, a wrong 'yes' costs latency on every greeting."""
    if mode == "off":
        return False
    if mode == "always":
        return True
    raw = str(text or "").strip()
    if len(raw) < _TALK_WEB_MIN_LEN:
        return False
    if raw.startswith("/"):            # talk-side commands handled earlier
        return False
    t = _talk_web_norm(raw)
    if _TALK_WEB_YEAR_RE.search(t) or _TALK_WEB_FA_YEAR_RE.search(t):
        return True
    return any(tr in t for tr in _TALK_WEB_TRIGGERS)


def talk_web_query(text):
    """Compact search query from a chat message: whitespace-collapsed,
    markdown-stripped, length-capped. Search engines rank natural
    language fine - we only remove noise, never translate (v7.10 already
    routes Persian queries to ir-fa + fa.wikipedia)."""
    t = re.sub(r"[*_`#>\[\]]+", " ", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > TALK_WEB_QUERY_CAP:
        t = t[:TALK_WEB_QUERY_CAP].rsplit(" ", 1)[0]
    return t


def talk_web_block(query, results):
    """Format the [WEB RESULTS] system block. Empty results -> empty
    string (no block). Numbered, capped, with an honest-use law."""
    rows = []
    for r in (results or [])[:TALK_WEB_MAX_RESULTS]:
        url = str((r or {}).get("url") or "").strip()
        if not url:
            continue
        title = str((r or {}).get("title") or url)[:120]
        snip = re.sub(r"\s+", " ", str((r or {}).get("snippet") or ""))
        snip = snip[:TALK_WEB_SNIPPET_CAP]
        rows.append((title, snip, url))
    if not rows:
        return ""
    lines = ["[WEB RESULTS - query: %s - %d results]" % (query, len(rows))]
    for i, (title, snip, url) in enumerate(rows, 1):
        lines.append("%d. %s" % (i, title))
        if snip:
            lines.append("   %s" % snip)
        lines.append("   %s" % url)
    lines.append(
        "Use these results when they answer the user; cite them inline "
        "like [1], [2] in plain prose. If they do not answer the "
        "question, say so honestly. Anything time-sensitive not covered "
        "by them may be outdated - say so.")
    return "\n".join(lines)


def talk_web_path(ws):
    """Workspace state file for the talk web mode."""
    return Path(str(ws or ".")) / TALK_WEB_FILE


def talk_web_get(ws):
    """Current mode for this workspace - off | auto | always. Missing or
    corrupt file = 'auto' (fail-soft)."""
    try:
        data = json.loads(talk_web_path(ws).read_text(encoding="utf-8"))
        mode = str((data or {}).get("mode") or "").strip().lower()
        if mode in TALK_WEB_MODES:
            return mode
    except Exception:
        pass
    return TALK_WEB_DEFAULT


def talk_web_set(ws, mode):
    """Persist the mode (atomic write). Returns the mode actually set."""
    mode = str(mode or "").strip().lower()
    if mode not in TALK_WEB_MODES:
        raise ValueError("mode must be one of " + "|".join(TALK_WEB_MODES))
    p = talk_web_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    # v7.14.1 fix: the atomic write returns an error string that used to
    # be dropped - a failed persistence silently reverted on next turn
    # v8.0 fix: the import is now fail-soft like every sibling module
    # (a partial install must degrade, not raise out of the setter).
    try:
        import nova_atomic
    except Exception:
        nova_atomic = None
    if nova_atomic is not None:
        err = nova_atomic.write_text_atomic(p, json.dumps(
            {"mode": mode}, ensure_ascii=False, indent=1))
        if err:
            raise OSError(err)
    else:
        p.write_text(json.dumps(
            {"mode": mode}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    return mode


# ------------------------------------------------- v7.13: intel web face
def web_intel_state(sess):
    """Payload for GET /api/intel - the live agent dashboard: what the
    agent is doing now (and why / next / tested), the task graph, the
    memory stats, the project profile and the last regression verdict.
    Every block is fail-soft: a missing store means an empty block,
    never a 500."""
    ws = Path(sess.ws)
    out = {"version": VERSION}
    if intel is None:
        out["available"] = False
        return out
    out["available"] = True
    try:
        it = intel.ProjectIntelligence(ws)
        data, _ = it.refresh_if_stale()
        prof = intel.project_profile(ws, intel=it)
        out["project"] = {
            "name": prof.get("name", ws.name),
            "files": prof.get("files", 0),
            "languages": prof.get("languages", {}),
            "frameworks": prof.get("frameworks", []),
            "entries": prof.get("entries", []),
            "tests_dir": prof.get("tests_dir", ""),
            "generated": data.get("generated", 0),
        }
    except Exception as e:
        out["project"] = {"error": str(e)[:200]}
    try:
        tg = intel.TaskGraph(ws / ".nova" / "tasks.json")
        rows = []
        for tid in sorted(tg.tasks):
            t = tg.tasks[tid]
            rows.append({"id": t["id"], "title": t["title"],
                         "status": t["status"], "deps": t.get("deps", []),
                         "tags": t.get("tags", []),
                         "note": t.get("note", "")})
        order, cycles = tg.order()
        out["tasks"] = {"list": rows, "progress": tg.progress(),
                        "ready": tg.ready(), "blocked": tg.blocked(),
                        "order": order, "cycles": cycles}
    except Exception as e:
        out["tasks"] = {"error": str(e)[:200]}
    try:
        mem = intel.SemanticMemory(ws / ".nova" / "memory_vec.json")
        recent = sorted(mem.records, key=lambda r: -r.get("ts", 0))[:8]
        out["memory"] = {
            "stats": mem.stats(),
            "recent": [{"id": r.get("id"), "text": r.get("text", "")[:200],
                        "kind": r.get("kind", "fact"),
                        "tags": r.get("tags", [])}
                       for r in recent if isinstance(r, dict)],
        }
    except Exception as e:
        out["memory"] = {"error": str(e)[:200]}
    try:
        out["status"] = intel.AgentStatus(ws).read()
    except Exception:
        out["status"] = {}
    try:
        out["regression"] = intel.load_json(
            ws / ".nova" / "regression.json", {})
    except Exception:
        out["regression"] = {}
    out["last_run"] = None
    try:
        lp = intel.AgentLoop.latest_run(ws)
        if lp:
            run = intel.load_json(lp, {})
            out["last_run"] = {
                "id": run.get("id"), "goal": run.get("goal", "")[:200],
                "phase": run.get("phase"), "result": run.get("result"),
                "evidence": run.get("evidence"),
                "attempts": run.get("attempts", 0),
                "phases": [{"phase": p.get("phase"),
                            "why": p.get("why", "")[:120]}
                           for p in (run.get("phases") or [])[-8:]],
            }
    except Exception:
        out["last_run"] = None
    return out


_INTEL_ACTIONS = ("rescan", "task_add", "task_set", "task_del",
                  "mem_remember", "mem_forget", "ctx", "impact",
                  "gentests", "regress_baseline", "regress_check",
                  "status_clear")


def web_intel_action(sess, data):
    """POST /api/intel mutations - follows the web_providers_action
    contract: (ok, payload, status). No TURN_LOCK: every action either
    touches its own .nova store or reads the project tree - none of
    them mutate the shared Session's in-flight turn state."""
    if intel is None:
        return False, {"error": "nova_intel.py missing"}, 501
    action = str(data.get("action", "")).strip()
    if action not in _INTEL_ACTIONS:
        return False, {"error": "unknown action",
                       "actions": list(_INTEL_ACTIONS)}, 400
    ws = Path(sess.ws)

    def _bad(msg, code=400):
        return False, {"error": str(msg)[:200]}, code

    try:
        if action == "rescan":
            data_scan = intel.ProjectIntelligence(ws).scan()
            return True, {"ok": True, "files": len(data_scan.get("files",
                           []))}, 200
        if action == "task_add":
            tg = intel.TaskGraph(ws / ".nova" / "tasks.json")
            title = str(data.get("title", "")).strip()
            if not title:
                return _bad("title is required")
            deps = data.get("deps") if isinstance(data.get("deps"),
                                                  list) else []
            tags = data.get("tags") if isinstance(data.get("tags"),
                                                  list) else []
            detail = str(data.get("detail", "")) if data.get("detail") \
                else ""
            tid = tg.add(title, deps=[str(d) for d in deps[:10]],
                         tags=[str(t) for t in tags[:10]], detail=detail)
            intel.AgentStatus(ws).set(
                task=tid, event="task added: %s" % title[:80])
            return True, {"ok": True, "id": tid}, 200
        if action in ("task_set", "task_del"):
            tg = intel.TaskGraph(ws / ".nova" / "tasks.json")
            tid = str(data.get("id", "")).strip()
            if action == "task_del":
                return (True, {"ok": bool(tg.remove(tid))}, 200)
            status = data.get("status")
            note = data.get("note")
            deps = data.get("deps")
            t = tg.set(tid,
                       status=str(status) if status else None,
                       note=str(note) if note is not None else None,
                       deps=[str(d) for d in deps] if isinstance(deps,
                                                                 list)
                       else None)
            intel.AgentStatus(ws).set(
                task=tid, event="task %s -> %s"
                % (tid, t.get("status", "?")))
            return True, {"ok": True, "task": t}, 200
        if action == "mem_remember":
            text = str(data.get("text", "")).strip()
            if not text:
                return _bad("text is required")
            mem = intel.SemanticMemory(ws / ".nova" / "memory_vec.json")
            kind = str(data.get("kind", "fact"))
            kind = kind if kind in ("fact", "decision", "event", "task",
                                    "kb") else "fact"
            tags = data.get("tags") if isinstance(data.get("tags"),
                                                  list) else []
            mid = mem.remember(text, kind=kind,
                               tags=[str(t) for t in tags[:8]])
            return True, {"ok": True, "id": mid}, 200
        if action == "mem_forget":
            mem = intel.SemanticMemory(ws / ".nova" / "memory_vec.json")
            return (True, {"ok": bool(mem.forget(str(data.get("id",
                     ""))))}, 200)
        if action == "ctx":
            query = str(data.get("query", "")).strip()
            if not query:
                return _bad("query is required")
            eng = intel.ContextEngine(ws, kb_path=sess.kb_path)
            text, sources = eng.assemble(query)
            return (True, {"ok": True, "text": text,
                           "sources": sources}, 200)
        if action == "impact":
            paths = data.get("paths")
            if not isinstance(paths, list) or not paths:
                return _bad("paths (list) is required")
            rep = intel.ImpactAnalyzer(ws).analyze(
                [str(p) for p in paths[:8]])
            return True, {"ok": True, "report": rep}, 200
        if action == "gentests":
            rel = str(data.get("path", "")).strip()
            if not rel:
                return _bad("path is required")
            out = intel.TestGenerator(ws).gen_for_file(rel)
            return (True, {"ok": True, "result": out}, 200) \
                if out.get("ok") else (False, {"error": out.get(
                    "error", "generation failed")}, 400)
        if action == "regress_baseline":
            if feedback is None:
                return _bad("nova_feedback.py missing", 501)
            rd = intel.RegressionDetector(
                ws, runner=lambda: feedback.run_tests(sess.ws))
            res = rd.baseline()
            return True, {"ok": True, "baseline": res}, 200
        if action == "regress_check":
            if feedback is None:
                return _bad("nova_feedback.py missing", 501)
            rd = intel.RegressionDetector(
                ws, runner=lambda: feedback.run_tests(sess.ws))
            res = rd.check()
            return True, {"ok": True, "result": res}, 200
        if action == "status_clear":
            intel.AgentStatus(ws).clear()
            return True, {"ok": True}, 200
    except ValueError as e:
        return _bad(e)
    except Exception as e:
        return (False, {"error": "intel action failed: %s"
                        % str(e)[:150]}, 500)
    return _bad("unreachable")


def web_talk_state(sess):
    """Payload for GET /api/talk/web - current mode + the legal values."""
    try:
        return {"mode": talk_web_get(sess.ws),
                "modes": list(TALK_WEB_MODES),
                "default": TALK_WEB_DEFAULT}
    except Exception as e:
        return {"mode": TALK_WEB_DEFAULT, "modes": list(TALK_WEB_MODES),
                "default": TALK_WEB_DEFAULT, "error": str(e)[:200]}


def cmd_services(sess, arg):
    """v7.11: Iranian services with API keys - list / key / clear /
    test / call. Examples:
      /services
      /services key kavenegar 1234567890
      /services test bale
      /services call kavenegar send_sms receptor=0912... message="سلام"
      /services call zibal sandbox_test
      /services clear kavenegar
    The agent can call this too (model-briefed): each call is metered."""
    if iran is None:
        print(c(C.Y, "[!] nova_iran_services.py is missing - Iranian "
                     "services unavailable."))
        return
    parts = (arg or "").strip().split(maxsplit=1)
    if not parts:
        print(c(C.B, f"سرویس‌های ایرانی ({len(iran.names())} سرویس، "
                     f"{len(iran.CATEGORIES)} دسته):"))
        for cid, clabel in iran.CATEGORIES:
            sids = [s for s in iran.names()
                    if (iran.entry(s) or {}).get("category") == cid]
            print(f"  {clabel}:")
            for sid in sids:
                e = iran.entry(sid) or {}
                is_set, masked = iran.key_status(sess.ws, sid)
                mark = (c(C.G, f"کلید: {masked}") if is_set
                        else c(C.Y, "بدون کلید"))
                free = (" [بدون کلید]" if e.get("needs_key") is False
                        and not (e.get("key_env") or e.get("key_names")) else "")
                print(f"    {sid:<12} {e.get('label', ''):<22} "
                      f"{mark}{free}")
        print(c(C.D, "کلید:   /services key <service> <key>   "
                     "مثال:  /services key kavenegar 1234..."))
        print(c(C.D, "تست:    /services test <service>        "
                     "(آزمایش رایگان امن)"))
        print(c(C.D, "فراخوانی: /services call <service> <action> "
                     "k=v ...  مثال:"))
        print(c(C.D, "          /services call kavenegar send_sms "
                     "receptor=09123456789 message=\"سلام از Nova\""))
        print(c(C.D, "حذف کلید: /services clear <service>      "
                     "پنل وب: کارت «سرویس‌های ایرانی» در تب مدل‌ها"))
        return
    op = parts[0].strip().lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    if op in ("key", "set"):
        toks = rest.split(maxsplit=1)
        if len(toks) < 2:
            print(c(C.Y, "[!] usage: /services key <service> <the-key>"))
            return
        sid, val = toks[0].strip().lower(), toks[1].strip()
        if iran.entry(sid) is None:
            print(c(C.Y, f"[!] unknown service '{sid}'. See: /services"))
            return
        err = iran.set_key(sess.ws, sid, val)
        if err:
            print(c(C.R, "[!] " + err))
            return
        is_set, masked = iran.key_status(sess.ws, sid)
        print(c(C.G, f"  کلید {sid} ذخیره شد ({masked}) - "
                     f".nova/{iran.CONFIG_FILE}"))
        return
    if op in ("clear", "del", "remove"):
        sid = rest.strip().lower()
        if iran.entry(sid) is None:
            print(c(C.Y, f"[!] unknown service '{sid}'. See: /services"))
            return
        err = iran.del_key(sess.ws, sid)
        print(c(C.G, f"  کلید {sid} حذف شد ({err or 'ok'})"))
        return
    if op == "test":
        sid = rest.strip().lower()
        if iran.entry(sid) is None:
            print(c(C.Y, f"[!] unknown service '{sid}'. See: /services"))
            return
        print(c(C.D, f"  تست امن {sid} ..."))
        res = iran.test_key(sess.ws, sid)
        _print_service_result(res)
        return
    if op == "call":
        import shlex
        # v8.10.1 fix: shlex raises ValueError on an unbalanced quote
        # (Persian text with a stray quote is realistic) - that used to
        # surface as an internal error instead of a usage hint.
        try:
            toks = shlex.split(rest)
        except ValueError:
            print(c(C.Y, "[!] bad quoting in the command - usage: "
                         "/services call <service> <action> [k=v ...]"))
            return
        if len(toks) < 2:
            print(c(C.Y, "[!] usage: /services call <service> <action> "
                         "[k=v ...]"))
            return
        sid, aid = toks[0].strip().lower(), toks[1].strip().lower()
        params = {}
        for tok in toks[2:]:
            if "=" not in tok:
                print(c(C.Y, f"[!] bad parameter (want k=v): {tok}"))
                return
            k, v = tok.split("=", 1)
            params[k.strip()] = v
        print(c(C.D, f"  {sid}.{aid} ..."))
        res = iran.run_action(sess.ws, sid, aid, params=params)
        _print_service_result(res)
        return
    print(c(C.Y, "[!] usage: /services [key|clear|test|call] ..."))


def _print_service_result(res):
    """Compact user-facing print of one service result (no key ever)."""
    if not isinstance(res, dict):
        print(c(C.R, "[!] bad result"))
        return
    if res.get("ok"):
        print(c(C.G, f"  OK  (HTTP {res.get('status')}، "
                     f"{res.get('ms', 0)}ms)"))
        for f, v in (res.get("fields") or {}).items():
            if v is not None:
                print(f"    {f}: {v}")
        if res.get("link"):
            print("    link: " + res["link"])
        dp = res.get("data_preview") or ""
        if dp:
            print(c(C.D, "    " + dp[:600]))
    else:
        print(c(C.R, "[!] " + str(res.get("error", "failed"))))


def cmd_mode(sess, arg):
    if not arg:
        print("Modes: " + ", ".join(f"{k} (temp {v})" for k, v in MODES.items()))
        print(c(C.D, "Current: " + sess.mode))
        return
    if arg in MODES:
        sess.mode = arg
        sess.save_profile_field("mode", arg)
        print(c(C.G, f"Mode set: {arg} (temperature {MODES[arg]})"))
    else:
        print(c(C.Y, "[!] unknown mode. Options: code | balanced | creative"))

def cmd_timeout(sess, arg):
    if not arg:
        print(f"/run timeout: {sess.run_timeout}s  (change with: /timeout 300)")
        print(c(C.D, f"(allowed range: 5-{RUN_TIMEOUT_CAP}s; startup default: NOVA_RUN_TIMEOUT env)"))
        return
    if arg.isdigit() and 5 <= int(arg) <= RUN_TIMEOUT_CAP:
        sess.run_timeout = int(arg)
        sess.save_profile_field("run_timeout", sess.run_timeout)
        print(c(C.G, f"/run timeout set to {sess.run_timeout}s"))
    else:
        print(c(C.Y, f"[!] usage: /timeout <seconds>  (5-{RUN_TIMEOUT_CAP})"))

def cmd_undo(sess, arg=""):
    """v5.0: unlimited undo over the persistent snapshot stack.
    /undo      restore the last apply batch
    /undo 3    walk back three batches"""
    n = 1
    # v6.2.1 fix: the old one-liner tested `arg.strip()` OUTSIDE the
    # `(arg or "")` guard, so cmd_undo(sess, None) crashed with
    # AttributeError - exactly the crash the guard was meant to prevent.
    _tokens = (arg or "").strip().split()
    raw = _tokens[0] if _tokens else ""
    if raw:
        if not raw.isdigit() or int(raw) < 1:
            print(c(C.Y, "[!] usage: /undo [n]  (n = how many applies to revert)"))
            return
        n = int(raw)
    if snaps is not None and snaps.list_units(sess.ws, snaps.AUTO_KIND):
        res = snaps.undo_units(sess.ws, n)
        for action, rel in res["restored"]:
            label = "restored" if action == "restored" else "deleted"
            print(c(C.G if action == "restored" else C.Y, f"  [{label}] {rel}"))
        for e in res["errors"]:
            print(c(C.R, "  [!] " + e))
        if res["undone"]:
            # v8.10.1 fix: the snapshot layer just undid the batch these
            # in-memory backups belong to. They used to survive - so when
            # the snapshot stack was exhausted, the next /undo fell into
            # the legacy path and RESTORED them, silently jumping the
            # workspace forward to a post-apply state again.
            sess.last_batch = []
            print(c(C.G, f"Undid {len(res['undone'])} apply batch(es) - "
                         f"{len(snaps.list_units(sess.ws, snaps.AUTO_KIND))} more step(s) available."))
            if sess.touched:
                print(c(C.D, "(/changes may still list files - 'clear' resets it)"))
            sess.rescan(silent=True)
            return
    # legacy fallback: the in-memory last batch (pre-v5.0 or empty stack)
    if not sess.last_batch:
        print(c(C.Y, "[!] nothing to undo - no files were overwritten."))
        return
    for target, bk in reversed(sess.last_batch):
        try:
            shutil.copy2(bk, target)
            print(c(C.G, f"Restored {target.relative_to(sess.ws).as_posix()} <- {bk.name}"))
        except OSError as e:
            print(c(C.R, f"[!] could not restore {target.name}: {e}"))
    sess.last_batch = []
    sess.rescan(silent=True)


def cmd_snapshot(sess, arg=""):
    """Manual full-workspace checkpoint, separate from auto /undo."""
    if snaps is None:
        print(c(C.Y, "[!] snapshots unavailable (nova_snapshots.py missing)"))
        return
    label = arg.strip()[:80]
    print(c(C.D, "Snapshotting the workspace (ignored/secret/oversized files skipped) ..."))
    uid, err, skipped = snaps.make_manual(sess.ws, label=label, ignore=sess.ignore)
    if err:
        print(c(C.R, "[!] snapshot failed: " + err))
        return
    n_files = len(snaps.find_manual(sess.ws, uid)["files"])
    print(c(C.G, f"Snapshot {uid} saved ({n_files} files)"
               + (f" - label: {label}" if label else "")))
    if skipped:
        print(c(C.D, f"  ({len(skipped)} skipped: too big / secret / unreadable)"))
    print(c(C.D, "Restore it later with:  /restore " + (label or uid)))


def cmd_snapshots(sess, arg=""):
    autos = snaps.list_units(sess.ws, snaps.AUTO_KIND) if snaps else []
    manuals = snaps.list_units(sess.ws, snaps.MANUAL_KIND) if snaps else []
    if not autos and not manuals:
        print(c(C.D, "No snapshots yet - units appear automatically with every apply."))
        return
    if manuals:
        print(c(C.B, f"Manual checkpoints ({len(manuals)}):"))
        for m in manuals:
            lbl = f" - {m['label']}" if m.get("label") else ""
            when = datetime.fromtimestamp(m.get("ts", 0)).strftime("%m-%d %H:%M")
            print(f"  {m['id']}  {when}{lbl}  ({len(m['files'])} files)")
    if autos:
        print(c(C.B, f"Auto undo units ({len(autos)}, newest first):"))
        for m in autos[:12]:
            when = datetime.fromtimestamp(m.get("ts", 0)).strftime("%m-%d %H:%M")
            note = f"  {m.get('note', '')[:46]}" if m.get("note") else ""
            print(f"  {m['id']}  {when}  {len(m['files'])} file(s){note}")
        if len(autos) > 12:
            print(c(C.D, f"  ... and {len(autos) - 12} older units"))
    print(c(C.D, "(/undo [n] reverts apply batches   |   /restore <label|id> "
               "goes back to a checkpoint)"))


def cmd_restore(sess, arg=""):
    ref = arg.strip()
    if not ref:
        print(c(C.Y, "[!] usage: /restore <label|id>   (see: /snapshots)"))
        return
    if snaps is None:
        print(c(C.Y, "[!] snapshots unavailable"))
        return
    meta = snaps.find_manual(sess.ws, ref)
    if meta is None:
        print(c(C.Y, f"[!] no manual checkpoint '{ref}' - see: /snapshots"))
        return
    when = datetime.fromtimestamp(meta.get("ts", 0)).strftime("%Y-%m-%d %H:%M")
    print(c(C.Y, f"Restore checkpoint {meta['id']} ({when})? The workspace goes "
                 "back to exactly this state. [y/N]: "), end="")
    if ask("").strip().lower() not in ("y", "yes"):
        print(c(C.D, "(cancelled)"))
        return
    res = snaps.restore_manual(sess.ws, meta, ignore=sess.ignore)
    for rel in res["written"]:
        print(c(C.G, f"  restored  {rel}"))
    for rel in res["deleted"]:
        print(c(C.Y, f"  removed   {rel}"))
    for rel in res["skipped"]:
        print(c(C.D, f"  skipped   {rel}"))
    for e in res["errors"]:
        print(c(C.R, "  [!] " + e))
    print(c(C.G, f"Checkpoint restored: {len(res['written'])} file(s) written, "
               f"{len(res['deleted'])} removed."))
    sess.rescan(silent=True)


def cmd_map(sess, arg=""):
    """Show the style map exactly as the model sees it."""
    print(c(C.B, "Project style map (injected into every prompt):"))
    print(sess.map_text or "(empty)")


def cmd_explain(sess, arg=""):
    sub = arg.strip().lower()
    if sub in ("on", ""):
        sess.explain = True
        print(c(C.G, "Explain mode ON - analysis only: no file writes, no shell "
                     "commands. (/explain off to edit again)"))
    elif sub == "off":
        sess.explain = False
        print(c(C.G, "Explain mode OFF - full editing is back."))
    else:
        print(c(C.Y, "[!] usage: /explain [on|off]"))


def cmd_secure(sess, arg=""):
    """v6.3: security posture for this workspace (/secure on|off|status)."""
    if nsec is None:
        print(c(C.Y, "[!] security layer unavailable (nova_security.py missing)"))
        return
    sub = arg.strip().lower()
    if sub in ("", "status", "show"):
        on = nsec.is_secure(sess.ws)
        print(c(C.B, "Security posture (workspace: " + sess.ws.name + ")"))
        print("  secure mode : " + (c(C.G, "ON") if on else c(C.Y, "off")))
        print(c(C.D, "  always      : destructive commands blocked (rm -rf /,"
                     " format, mkfs, fork bomb, ...) + every run/bg audited"))
        print(c(C.D, "  secure adds : web-proposed risky commands blocked, web face"
                     " needs its token even on localhost (after restart),"
                     " stricter rate limits"))
        print(c(C.D, "  change      : /secure on | /secure off   (or NOVA_SECURE=1)"))
        return
    if sub == "on":
        nsec.set_secure(True, ws=sess.ws)
        print(c(C.G, "Secure mode ON for this workspace - risky web commands are"
                     " blocked, everything is audited."))
        print(c(C.D, "  note: the token-even-on-localhost rule applies after the web"
                     " face restarts."))
        return
    if sub == "off":
        nsec.set_secure(False, ws=sess.ws)
        print(c(C.Y, "Secure mode OFF - destructive commands stay blocked, risky"
                     " ones ask first."))
        return
    print(c(C.Y, "[!] usage: /secure [on|off|status]"))


def cmd_log(sess, arg=""):
    """v6.3: professional error reporting - swallowed exceptions are kept
    in a bounded ring buffer + .nova/logs/nova.log instead of vanishing."""
    if nova_log is None:
        print(c(C.Y, "[!] nova_log.py missing"))
        return
    sub = arg.strip().lower()
    if sub in ("", "tail", "show"):
        entries = nova_log.tail(25)
        if not entries:
            print(c(C.D, "No warnings recorded this session. Fail-soft errors"
                         " are logged here now instead of vanishing."))
            return
        print(c(C.B, f"Recent warnings ({len(entries)}):"))
        print(nova_log.format_entries(entries))
        return
    if sub == "summary":
        counts = nova_log.summary()
        if not counts:
            print(c(C.D, "No warnings recorded this session."))
            return
        print(c(C.B, "Warnings by call site:"))
        for where, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {where}")
        return
    if sub == "clear":
        nova_log.reset()
        print(c(C.G, "In-memory log cleared."))
        return
    print(c(C.Y, "[!] usage: /log [tail|summary|clear]   (NOVA_DEBUG=1 mirrors to stderr)"))


def cmd_blackbox(sess, arg=""):
    """v8.0: the agent's black box - the behind-the-scenes decisions
    (brain picks, apply batches, run verdicts, recovery moves, sandbox
    refusals). Read-only by design; the file survives restarts."""
    if flightlog is None:
        print(c(C.Y, "[!] nova_flightlog.py missing"))
        return
    toks = arg.split()
    n = 30
    prefix = None
    for t in toks:
        if t.isdigit():
            n = max(1, min(int(t), 240))
        else:
            prefix = t
    entries = flightlog.read_file(n=n, where_prefix=prefix)
    if not entries:
        entries = flightlog.recent(n=n, where_prefix=prefix)
    if not entries:
        print(c(C.D, "The black box is empty - decisions land here as "
                     "the agent works (brain picks, applies, runs, "
                     "recovery, sandbox refusals)."))
        return
    print(c(C.B, f"Black box ({len(entries)} entries"
                 f"{', filter: ' + prefix if prefix else ''}):"))
    import time as _t
    for e in entries:
        ts = e.get("ts", 0)
        when = _t.strftime("%H:%M:%S", _t.localtime(ts)) if ts else "??:??:??"
        lvl = e.get("level", "info")
        col = C.R if lvl == "error" else (C.Y if lvl == "warn" else C.D)
        extra = " ".join(
            f"{k}={v}" for k, v in sorted(e.items())
            if k not in ("ts", "where", "level", "msg"))
        line = f"  [{when}] {e.get('where', '?')}: {e.get('msg', '')}"
        if extra:
            line += f"  ({extra})"
        print(c(col, line))
    st = flightlog.state()
    print(c(C.D, f"  -- file sink: {st.get('file')}, {st.get('file_bytes', 0)} "
                 "bytes, RAM ring " + str(st.get("ram_entries", 0)) + " --"))


def cmd_plugin(sess, arg=""):
    """v8.0: the plugin system - side tools that live OUTSIDE the core.
    /plugin list | run <plugin.tool> k=v ... | reload | key <NAME> <val>"""
    if plugins is None:
        print(c(C.Y, "[!] nova_plugins.py missing"))
        return
    toks = arg.split()
    sub = toks[0].lower() if toks else "list"
    if sub in ("", "list", "show"):
        print(c(C.B, plugins.cli_summary(sess.ws)))
        return
    if sub == "reload":
        st = plugins.load_plugins(sess.ws, force=True)
        print(c(C.G, f"reloaded {len(st.get('plugins', []))} plugin(s)"))
        for e in st.get("errors", []):
            print(c(C.Y, "[!] " + e))
        return
    if sub == "key" and len(toks) >= 2:
        val = toks[2] if len(toks) >= 3 else ""
        err = plugins.set_secret(sess.ws, toks[1].upper(), val)
        if err:
            print(c(C.R, "[!] " + err))
        else:
            print(c(C.G, "plugin secret " + toks[1].upper() +
                        (" saved" if val else " removed")))
        return
    if sub == "run" and len(toks) >= 2:
        qualified = toks[1]
        params = {}
        for kv in toks[2:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v
        r = plugins.run_tool(sess.ws, qualified, params)
        if r.get("ok"):
            print(c(C.G, f"[ok] {qualified} -> HTTP {r.get('status')} "
                         f"({r.get('ms')}ms)"))
            data = r.get("data")
            if data is not None:
                print(json.dumps(data, ensure_ascii=False,
                                 indent=1)[:2000])
            elif r.get("preview"):
                print(r["preview"][:800])
        else:
            print(c(C.R, "[!] " + str(r.get("error", "failed"))))
        return
    print(c(C.Y, "[!] usage: /plugin [list|run <plugin.tool> k=v ...|"
                 "reload|key <NAME> <value>]"))


def cmd_policy(sess, arg=""):
    """Per-command permission policy (allowlist/denylist)."""
    if npol is None:
        print(c(C.Y, "[!] policy unavailable (nova_policy.py missing)"))
        return
    parts = arg.strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    if sub in ("", "show", "list"):
        pol = npol.load_policy(sess.ws)
        print(c(C.B, "Command policy (.nova/policy.json):"))
        print(f"  default : {pol['default']}")
        print( "  allow   : " + (", ".join(pol["allow"]) if pol["allow"] else "(none)"))
        print( "  deny    : " + (", ".join(pol["deny"]) if pol["deny"] else "(none)"))
        print(c(C.D, "  deny beats allow. Patterns: fnmatch against the whole command "
                     "('python *', 'git push*', 'rm -rf *')."))
        print(c(C.D, "  change: /policy allow <pat> | /policy deny <pat> | "
                     "/policy default ask|allow|deny | /policy reset"))
        return
    if sub in ("allow", "deny"):
        if not rest:
            print(c(C.Y, f"[!] usage: /policy {sub} <pattern>"))
            return
        pol = npol.load_policy(sess.ws)
        pol[sub].append(rest)
        err = npol.save_policy(sess.ws, pol)
        print(c(C.R if sub == "deny" else C.G,
                f"{sub}ed: {rest}" + ("" if not err else "  (save failed: " + err + ")")))
        return
    if sub == "default":
        val = rest.lower()
        if val not in npol.VALID_DEFAULTS:
            print(c(C.Y, "[!] usage: /policy default ask|allow|deny"))
            return
        pol = npol.load_policy(sess.ws)
        pol["default"] = val
        err = npol.save_policy(sess.ws, pol)
        print(c(C.G, f"default for unlisted commands: {val}" +
                   ("" if not err else "  (save failed: " + err + ")")))
        return
    if sub == "reset":
        err = npol.save_policy(sess.ws, dict(npol.DEFAULT_POLICY))
        print(c(C.G, "policy reset to default=ask, no allow/deny rules" +
                   ("" if not err else "  (save failed: " + err + ")")))
        return
    print(c(C.Y, "[!] usage: /policy [show|allow <pat>|deny <pat>|default <v>|reset]"))


def cmd_novaignore(sess, arg=""):
    """Inspect the .novaignore view-exclusion list."""
    parts = arg.strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    p = sess.ws / ".novaignore"
    if sub == "check" and rest:
        if sess.ignore is None:
            print(c(C.Y, "[!] .novaignore support unavailable"))
            return
        hit = sess.ignore.matches(rest)
        print(("IGNORED" if hit else "visible") + f": {rest}")
        return
    if sub in ("", "show", "list"):
        if not p.is_file():
            print(c(C.D, "No .novaignore file - the agent sees every non-secret file."))
            print(c(C.D, "Create one (gitignore-style) to keep build output, datasets "
                         "or big assets out of the model's context."))
            return
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(c(C.R, "[!] cannot read: " + str(e)))
            return
        print(c(C.B, ".novaignore (excluded from the agent's VIEW):"))
        print(body.rstrip() or "(empty)")
        n = len(sess.ignore.rules) if sess.ignore else 0
        print(c(C.D, f"({n} rules active - edited the file? run /rescan)"))
        return
    print(c(C.Y, "[!] usage: /novaignore [show]   |   /novaignore check <path>"))


def cmd_todo(sess, arg=""):
    """Live task checklist (manual management; the model updates it too)."""
    if nova_todo is None:
        print(c(C.Y, "[!] plan support unavailable"))
        return
    items, msg = nova_todo.cmd_items_from_args(arg, sess.todo)
    sess.todo = items
    if msg and msg not in ("(no plan)",):
        print(c(C.D, msg))
    if items:
        print(c(C.B, f"Task plan ({nova_todo.progress(items)}):"))
        print(nova_todo.render(items))
    else:
        print(c(C.D, "No active plan. The model builds one automatically for "
                     "multi-step work (=== PLAN === block) - or add: /todo add <text>"))


def cmd_skill(sess, arg=""):
    """Self-built skills: reusable, learned approaches."""
    if skills is None:
        print(c(C.Y, "[!] skills unavailable (nova_skills.py missing)"))
        return
    parts = arg.strip().split(maxsplit=2)
    sub = parts[0].lower() if parts else "list"
    if sub == "save":
        if len(parts) < 3:
            print(c(C.Y, '[!] usage: /skill save <name> <instructions>'))
            return
        err = skills.add(sess.ws, parts[1], parts[2],
                         trigger=parts[1])
        print(c(C.G, "Skill saved." if not err else "[!] " + err))
        print(c(C.D, "It is injected into every prompt in this workspace and "
                     "gains priority as you use it."))
        return
    if sub == "list":
        allsk = skills.list_skills(sess.ws)
        if not allsk:
            print(c(C.D, "No skills yet. Save one: /skill save <name> <instructions>"))
            print(c(C.D, "Repeating the same successful task kind 3x also forges "
                         "one automatically."))
            return
        print(c(C.B, f"Skills ({len(allsk)}):"))
        for s in allsk:
            tag = " (auto)" if s.get("auto") else ""
            print(f"  {s['name']}{tag} [uses: {s.get('uses', 0)}]  {s.get('instructions', '')[:70]}")
        return
    if sub == "show":
        s = skills.get(sess.ws, parts[1] if len(parts) > 1 else "")
        if not s:
            print(c(C.Y, "[!] no such skill"))
            return
        print(c(C.B, s["name"] + f"  (uses: {s.get('uses', 0)})"))
        print(s.get("instructions", ""))
        return
    if sub in ("del", "rm", "delete"):
        if len(parts) < 2:
            print(c(C.Y, "[!] usage: /skill del <name>"))
            return
        err = skills.remove(sess.ws, parts[1])
        print(c(C.G, f"Deleted {parts[1]}." if not err else "[!] " + err))
        return
    print(c(C.Y, "[!] usage: /skill [list|save <name> <text>|show <name>|del <name>]"))


def cmd_autotest(sess, arg=""):
    sub = arg.strip().lower()
    if sub in ("on", "off"):
        sess.autotest = (sub == "on")
        sess.save_profile_field("autotest", sess.autotest)
    elif sub in ("", "status"):
        pass
    else:
        print(c(C.Y, "[!] usage: /autotest [on|off]"))
        return
    cmd, source = (feedback.detect_test_cmd(sess.ws)
                   if feedback is not None else (None, ""))
    state = "ON" if sess.autotest else "OFF"
    print(c(C.G if sess.autotest else C.D, f"Auto-tests: {state}"))
    if cmd:
        print(c(C.D, f"  detected test command ({source}): {cmd}"))
    else:
        print(c(C.D, "  no test setup detected in this workspace yet "
                     "(pytest / package.json test / unittest / make test)"))


def cmd_cost(sess, arg=""):
    """Token + cost ledger for the active (cloud) brains."""
    if nova_cost is None:
        print(c(C.Y, "[!] cost tracking unavailable"))
        return
    if arg.strip().lower() == "reset":
        # v7.9 audit fix: reset() returns an error string - a locked or
        # unreadable ledger used to print "cleared" while costs.json
        # survived untouched (the web action surfaces it; the CLI lied).
        err = nova_cost.reset(sess.ws)
        if err:
            print(c(C.Y, "[!] could not clear the ledger: " + err))
        else:
            print(c(C.G, "Cost ledger cleared."))
        return
    rep = nova_cost.report(sess.ws)
    def _line(tag, s):
        tok = f"{s['ptok']:,} in / {s['ctok']:,} out tok"
        cost = f"  ${s['cost']:.4f}" if s["cost"] else ""
        # v7.9: the user pays b.ai in CREDITS - show the equivalent
        # (B.AI law: 1 USD = 1,000,000 credits, X credits/token = X USD/1M).
        cred = f"  ~{nova_cost.credits_of(s['cost']):,.0f} credits" if s["cost"] else ""
        est = "  (some rows estimated)" if s["estimated_rows"] else ""
        print(f"  {tag:<6} {s['turns']:>4} request(s)  {tok}{cost}{cred}{est}")
    print(c(C.B, "Token & cost ledger (this workspace):"))
    _line("today", rep["today"])
    _line("total", rep["total"])
    if rep["total"]["per_model"]:
        print(c(C.D, "  per model:"))
        for key, m in rep["total"]["per_model"].items():
            cost = f"  ${m['cost']:.4f}" if m["cost"] else ""
            print(c(C.D, f"    {key}: {m['turns']} request(s), "
                         f"{m['ptok'] + m['ctok']:,} tok{cost}"))
    # v7.9: context gauge - what the LAST request filled of its window
    try:
        summ = nova_cost.usage_summary(sess.ws)
        last = summ.get("last_request")
        if last and last.get("context_tokens"):
            win = last.get("ctx_window")
            pct = last.get("ctx_pct")
            tail = (f" ({pct}% of the {win:,}-token window)" if pct is not None
                    else " (window size unknown)")
            print(c(C.D, f"  last request context: "
                         f"{last['context_tokens']:,} prompt tok{tail}"))
    except Exception:
        pass
    if rep["total"]["tok_per_sec"]:
        print(c(C.D, f"  measured speed: {rep['total']['tok_per_sec']} tok/s "
                     "(feeds /estimate)"))
    print(c(C.D, "  ollama (local) is free; cloud prices are approximate list "
                 "prices - override: .nova/pricing.json | credits use "
                 "b.ai's law: 1 USD = 1M credits"))


def cmd_estimate(sess, arg=""):
    """Price + duration estimate for a request BEFORE sending it."""
    if nova_cost is None:
        print(c(C.Y, "[!] estimates unavailable"))
        return
    text = arg.strip()
    if not text:
        print(c(C.Y, "[!] usage: /estimate <what you want to ask>   "
                     "e.g.: /estimate add a search page with pagination"))
        return
    cfg = _provider_cfg()
    prompt_chars = len(text) + len(sess.system_prompt()) + sum(
        len(m.get("content", "")) for m in sess.history)
    est = nova_cost.estimate_turn(sess.ws, prompt_chars, cfg.get("name", "ollama"),
                                  sess.model, expected_out_chars=6000)
    print(c(C.B, "Estimate for this request (rough):"))
    print(f"  prompt ~{est['prompt_tokens']:,} tok + answer ~{est['out_tokens']:,} tok")
    if est["price_known"]:
        cost = f"${est['cost_usd']:.4f}" if est["cost_usd"] else "$0.00 (local model)"
        print(f"  cost    ~{cost}")
    else:
        print(c(C.Y, "  cost    unknown model - add a price to .nova/pricing.json"))
    if est["est_seconds"] is not None:
        print(f"  time    ~{int(est['est_seconds'] // 60)}m {int(est['est_seconds'] % 60)}s "
               f"(measured {est['tok_per_sec']} tok/s on this machine)")
    elif cfg.get("kind") == "ollama":
        print(c(C.D, "  time    unknown yet - /run a request once and /estimate "
                     "learns your speed"))


def cmd_bg(sess, arg=""):
    """Run long jobs in the background; get noticed when they finish."""
    if nova_bg is None:
        print(c(C.Y, "[!] background tasks unavailable"))
        return
    arg = arg.strip()
    # v6.9: 'list' matched the BARE word only - '/bg list all' fell through
    # and ran 'list all' as a background SHELL command. Test the first word.
    if not arg or arg.split(maxsplit=1)[0].lower() in ("list", "status"):
        tasks = nova_bg.list_tasks(sess.ws)
        if not tasks:
            print(c(C.D, "No background tasks. Start one: /bg <command>"))
            return
        print(c(C.B, "Background tasks:"))
        for m in tasks:
            when = datetime.fromtimestamp(m.get("started", 0)).strftime("%m-%d %H:%M")
            print(f"  {m['id']}  [{m.get('status', '?')}]  {when}  {m.get('cmd', '')[:60]}")
        print(c(C.D, "(/bg log <id> | /bg kill <id>)"))
        return
    parts = arg.split(maxsplit=1)
    sub = parts[0].lower()
    # v6.2.1 fix: "/bg log" or "/bg kill" without an id used to fall through
    # and START A SHELL COMMAND named "log"/"kill" in the workspace. Catch
    # the subcommand names explicitly and show usage instead.
    if sub in ("log", "kill") and len(parts) < 2:
        print(c(C.Y, f"[!] usage: /bg {sub} <task-id>   (see: /bg list)"))
        return
    if sub == "log" and len(parts) > 1:
        meta, body = nova_bg.tail_log(sess.ws, parts[1].strip())
        if meta is None:
            print(c(C.Y, "[!] " + body))
            return
        print(c(C.B, f"{meta['id']} [{meta.get('status')}] {meta.get('cmd', '')}"))
        print(body or "(no output)")
        return
    if sub == "kill" and len(parts) > 1:
        print(c(C.Y, nova_bg.kill(sess.ws, parts[1].strip())))
        return
    # /bg <command> (same permission policy as foreground /run)
    if npol is not None:
        verdict = npol.check_command(sess.policy, arg)
        if verdict == "deny":
            print(c(C.R, "[policy] command denied by this project's policy "
                         "(background runs are gated too)"))
            return
    # v6.3 security gate: ask BEFORE start() so a risky command needs an
    # explicit yes; start() re-screens defensively for other callers.
    approved = False
    if nsec is not None:
        scr = nsec.screen(arg)
        if scr["verdict"] == "deny":
            print(c(C.R, "[security] command blocked: " + "; ".join(scr["reasons"])))
            nsec.audit(sess.ws, "bg", arg, origin="repl", verdict="deny",
                       reason="; ".join(scr["reasons"]))
            return
        if scr["verdict"] == "confirm":
            print(c(C.Y, "[security] risky command: " + "; ".join(scr["reasons"])))
            ans = ask("    run it in the BACKGROUND anyway? [y/N] ")
            if ans.strip().lower() not in ("y", "yes"):
                nsec.audit(sess.ws, "bg", arg, origin="repl", verdict="deny",
                           reason="; ".join(scr["reasons"]) + " (user refused)")
                print(c(C.D, "    cancelled."))
                return
            approved = True
    tid, err = nova_bg.start(sess.ws, arg, approved=approved)
    if err:
        print(c(C.Y, "[!] " + err))
        return
    print(c(C.G, f"[bg] started #{tid}: {arg[:70]}"))
    print(c(C.D, f"     keep working - I announce the finish here. check: /bg log {tid}"))


def _bg_notifications(sess):
    """Called between REPL prompts: report finished background tasks."""
    if nova_bg is None:
        return
    try:
        done = nova_bg.newly_finished(sess.ws, since_ts=sess.bg_notified)
        if done:
            now = int(time.time())
            for m in done:
                status = m.get("status", "?")
                mark = c(C.G, "FINISHED") if status == "finished" else \
                    c(C.R, status.upper())
                dur = f" - {m.get('dur', '?')}s" if m.get("dur") else ""
                print(c(C.Y, f"[bg] #{m['id']} {mark}{dur} - {m.get('cmd', '')[:56]} "
                             f"- /bg log {m['id']}"))
                emit_event({"t": "notify", "text": f"Background task {m['id']} "
                            f"{status}: {m.get('cmd', '')}", "bg_id": m["id"],
                            "status": status})
            sess.bg_notified = max(sess.bg_notified, now)
    except Exception:
        pass


def cmd_council(sess, arg=""):
    """Council mode: two brains answer the same question, optional judge."""
    if council is None or providers is None:
        print(c(C.Y, "[!] council mode unavailable"))
        return
    arg = arg.strip()
    if arg.lower().startswith("with "):
        spec = arg[5:].strip()
        err = council.save_partner(sess.ws, spec)
        print(c(C.G, f"Council partner set: {spec}" +
                   ("" if not err else "  (save failed: " + err + ")")))
        return
    if not arg:
        spec = council.load_partner(sess.ws)
        print(c(C.B, "Council mode - compare two brains on one question."))
        print(c(C.D, f"  partner: {spec or '(auto - first cloud key or 2nd local model)'}"))
        print(c(C.D, "  usage: /council <question>   |   /council with <provider[:model]>"))
        return
    question = arg
    spec = council.load_partner(sess.ws)
    # v6.6: a saved council ROUTE (.nova/providers.json, /brain council
    # provider/model) is the default partner - an explicit 'with <spec>'
    # still wins for the one call.
    if not spec and providers is not None:
        target = providers.route_target("council")
        if target:
            try:
                prov, model = providers.parse_target(target)
                spec = f"{prov}:{model}" if model else prov
            except Exception:
                spec = ""
    ollama_models = list_installed_models()
    try:
        pcfg = council.resolve_partner(spec, _provider_cfg().get("name", "ollama"),
                                       sess.model, providers, ollama_models)
    except ValueError as e:
        print(c(C.Y, "[!] " + str(e)))
        return
    prov_name, pmodel, plabel = pcfg
    print(c(C.B, f"\n=== COUNCIL ===\n  A: {_provider_cfg()['label']} ({sess.model})"
               f"\n  B: {plabel}"))
    msgs = sess.build_messages(sess.compose(question))
    # ---- answer A (active brain, streamed as usual) -----------------------
    print(c(C.D, "\n--- A answering ..."))
    answer_a, _ = stream_chat(sess.model, msgs, MODES[sess.mode], sess=sess)
    if not answer_a.strip():
        print(c(C.Y, "[council] brain A failed - council aborted."))
        return
    # ---- answer B (partner, collected) ------------------------------------
    print(c(C.D, "\n--- B answering ..."))
    try:
        if prov_name == "ollama":
            answer_b, usage = council.collect_ollama(
                pmodel, msgs, MODES[sess.mode], SOCK_TIMEOUT, OLLAMA_URL)
        else:
            cfgp = providers.resolve(prov_name)
            cfgp = dict(cfgp)
            cfgp["model"] = pmodel
            answer_b, usage = council.collect_provider(
                cfgp, pmodel, msgs, MODES[sess.mode], SOCK_TIMEOUT, providers)
        if nova_cost is not None:
            nova_cost.record(sess.ws, prov_name, pmodel,
                             usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                             actual=usage.get("actual", False), ok=bool(answer_b))
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(c(C.R, "[council] partner B failed: " + str(e)))
        print(c(C.D, "  (pick another partner: /council with <provider[:model]>)"))
        return
    print(c(C.B, f"\n=== B ({plabel}) ==="))
    print(answer_b)
    # ---- optional judge round ---------------------------------------------
    print(c(C.B, "\n=== verdict ==="))
    ask_judge = "" if NONINTERACTIVE else None
    if ask_judge is None:
        ans = ask("Ask brain A to judge & merge both answers? [Y/n]: ").strip().lower()
        ask_judge = ans
    if ask_judge in ("n", "no"):
        print(c(C.D, "(skipped the judge round)"))
        return
    print(c(C.D, "(A is judging ...)"))
    jmsg = [{"role": "user", "content": council.judge_prompt(
        question, answer_a, answer_b,
        f"{_provider_cfg()['label']} {sess.model}", plabel)}]
    verdict, _ = stream_chat(sess.model, jmsg, 0.3, sess=sess, section="utility")
    if verdict.strip():
        sess.transcript.append(("user", f"(council: {question[:80]})"))
        sess.transcript.append(("nova", "[council verdict] " + verdict[:2000]))
        sess.save_memory()


def cmd_pr(sess, arg=""):
    """Generate a PR title + description from this session's nova: commits."""
    if commitmsg is None:
        print(c(C.Y, "[!] git features unavailable"))
        return
    if not commitmsg.is_repo(sess.ws):
        print(c(C.Y, "[!] this workspace is not a git repository - "
                     "commits and PR drafts need one (git init)."))
        return
    prompt, n = commitmsg.build_pr_prompt(sess.ws, base=arg.strip())
    if n == 0:
        print(c(C.Y, "[!] no session commits found yet - apply some changes first "
                     "(auto-commits appear as 'nova: ...')."))
        return
    print(c(C.D, f"Composing a PR draft from {n} session commit(s) ..."))
    answer, _ = stream_chat(sess.model, [{"role": "user", "content": prompt}], 0.3,
                            sess=sess, section="utility")
    draft = answer.strip()
    if not draft:
        print(c(C.Y, "[!] the model returned nothing - try again."))
        return
    try:
        out = sess.ws / ".nova" / "PR.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# PR draft\n\n" + draft, encoding="utf-8")
        print(c(C.G, "PR draft saved to .nova/PR.md"))
    except OSError:
        pass
    print(draft)


def cmd_memory(sess, arg=""):
    """Conversation memory across terminal runs."""
    if nmem is None:
        print(c(C.Y, "[!] memory support unavailable"))
        return
    sub = arg.strip().lower()
    if sub == "clear":
        nmem.clear_memory(sess.ws)
        sess.history = []
        # v6.5 fix: the transcript is persisted by the very next
        # save_memory() - leaving it filled resurrected the "forgotten"
        # conversation in .nova/memory.json after the next turn.
        sess.transcript = []
        sess.last_composed = None
        print(c(C.G, "Memory cleared - this workspace's conversation is forgotten "
                     "(session continues fresh)."))
        return
    if sub == "off":
        sess.memory_on = False
        nmem.clear_memory(sess.ws)
        sess.transcript = []      # same resurrection hazard as /memory clear
        print(c(C.Y, "Memory OFF - conversations stay terminal-only and stored "
                     "memory was deleted. (/memory on to re-enable)"))
        return
    if sub == "on":
        sess.memory_on = True
        print(c(C.G, "Memory ON - conversations persist between terminal runs "
                     "(.nova/memory.json)."))
        return
    h, t, meta = None, None, None
    try:
        h, t, meta = nmem.load_memory(sess.ws)
    except ValueError as e:
        # v7.1.0: a SEALED memory file without a passphrase raised out of
        # here and surfaced as '[!] internal error' - same friendly message
        # as Session._load_memory instead.
        print(c(C.Y, "[memory] sealed - set NOVA_PASSPHRASE (or /unlock with "
                     "the passphrase) to read it: " + str(e)[:120]))
        return
    when = datetime.fromtimestamp(meta["ts"]).strftime("%Y-%m-%d %H:%M") \
        if meta.get("ts") else "-"
    print(c(C.B, "Cross-run conversation memory:"))
    print(f"  state    : {'ON' if sess.memory_on else 'OFF'}")
    print(f"  saved    : {when}")
    print(f"  stored   : {len(h)} message(s), {len(t)} transcript row(s)")
    print(c(C.D, "  (/memory clear | /memory on|off)") if not sub else
          c(C.Y, "[!] usage: /memory [show|clear|on|off]"))


def _coerce_profile_value(field, raw):
    """v6.9: /profile set used to accept any string - save_profile then
    silently DROPPED bad types ('300' as run_timeout, 'off' as autotest)
    while the UI reported success. Coerce + validate HERE so the user
    sees a real error instead of a setting that vanishes on restart."""
    raw = str(raw or "").strip()
    if field == "run_timeout":
        try:
            v = int(raw)
        except ValueError:
            return None, "run_timeout needs a number of seconds (5-3600)"
        if not (5 <= v <= 3600):
            return None, "run_timeout must be 5-3600"
        return v, ""
    if field == "autotest":
        low = raw.lower()
        if low in ("on", "true", "1", "yes"):
            return True, ""
        if low in ("off", "false", "0", "no"):
            return False, ""
        return None, "autotest is on|off"
    if field == "mode":
        if raw in MODES:
            return raw, ""
        return None, "mode is one of: " + ", ".join(MODES)
    return raw, ""


def cmd_profile(sess, arg=""):
    """Per-project settings profile (.nova/profile.json)."""
    if nproj is None:
        print(c(C.Y, "[!] profiles unavailable"))
        return
    parts = arg.strip().split(maxsplit=2)
    sub = parts[0].lower() if parts else "show"
    if sub in ("show", ""):
        prof = nproj.load_profile(sess.ws)
        print(c(C.B, "Per-project profile (.nova/profile.json):"))
        if prof:
            for k, v in prof.items():
                print(f"  {k:<12} {v}")
        else:
            print(c(C.D, "  (empty - stock defaults)"))
        print(c(C.D, "  /provider, /model, /mode, /timeout and /autotest "
                     "automatically persist here per workspace."))
        print(c(C.D, "  (/profile clear to forget)"))
        return
    if sub == "clear":
        err = nproj.clear_profile(sess.ws)
        print(c(C.G, "Profile cleared." + ("" if not err else "  (" + err + ")")))
        return
    if sub == "set" and len(parts) == 3:
        field, value = parts[1].lower(), parts[2].strip()
        known = {"provider", "model", "mode", "run_timeout", "autotest"}
        if field not in known:
            print(c(C.Y, f"[!] fields: {', '.join(sorted(known))}"))
            return
        if field in ("mode", "run_timeout", "autotest"):
            value, err0 = _coerce_profile_value(field, value)
            if value is None:
                print(c(C.Y, "[!] " + err0))
                return
        err = nproj.save_profile(sess.ws, {field: value})
        print(c(C.G, f"{field} -> {value}" + ("" if not err else "  (" + err + ")")))
        return
    print(c(C.Y, "[!] usage: /profile [show|set <field> <value>|clear]"))

def cmd_status(sess, arg=""):
    try:
        http_get_json("/api/tags")
        conn = c(C.G, "connected")
    except Exception:
        conn = c(C.R, "NOT connected")
    n_tools = sum(1 for t in TOOLS if tool_available(t))
    n_model_tools = sum(1 for t in TOOLS if t.get("model") and tool_available(t))
    toks = ", ".join("[" + a["name"] + ": ...]" for a in MODEL_ACTIONS
                     if tool_available(a)) or "none"
    # os.walk with pruned dirs: a plain rglob would descend into
    # node_modules/.git and crawl the whole tree on every /status
    n_files, file_cap = 0, 20000
    for root, dirs, names in os.walk(sess.ws):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        n_files += sum(1 for n in names if not n.startswith("."))
        if n_files > file_cap:
            break
    files_str = f"{file_cap}+ files" if n_files > file_cap else f"{n_files} files"
    serve = f"running on port {sess.serve_port}" if sess.serve_proc and sess.serve_proc.poll() is None else "off"
    prov = _provider_cfg()
    kb_n = len(ns.kb_entries(sess.kb_path)) if ns else 0
    cache_n = 0
    if ns:
        try:
            cache_n = sum(1 for _ in ns.CACHE_DIR.glob("*.json"))
        except Exception:
            pass
    # ---- v5.0 lines -------------------------------------------------------
    snap_n = len(snaps.list_units(sess.ws, snaps.AUTO_KIND)) if snaps else 0
    manual_n = len(snaps.list_units(sess.ws, snaps.MANUAL_KIND)) if snaps else 0
    cost_today = ""
    if nova_cost is not None:
        try:
            rep = nova_cost.report(sess.ws)
            if rep["today"]["turns"]:
                cost_today = f"  |  today: {rep['today']['turns']} turn(s)"
                if rep["today"]["cost"]:
                    cost_today += f", ${rep['today']['cost']:.4f}"
        except Exception:
            pass
    todo_prog = nova_todo.progress(sess.todo) if nova_todo else ""
    git_repo = commitmsg.is_repo(sess.ws) if commitmsg else False
    n_skills = len(skills.list_skills(sess.ws)) if skills else 0
    ctx_local, ctx_cloud = sess._ctx_wins()   # v8.3 context engine
    policy_s = f"default={sess.policy.get('default', 'ask')}" if sess.policy else "-"
    if sess.policy:
        policy_s += f", {len(sess.policy.get('allow', []))} allow, {len(sess.policy.get('deny', []))} deny"
    print(f"""  Agent      : {AGENT_NAME} v{VERSION} ({CODING_BRAND} module)
  Provider   : {prov['label']} ({prov['kind']})
  Model      : {sess.model}{_model_route_note(sess)}   mode: {sess.mode} (temperature {MODES[sess.mode]})
  Ollama     : {OLLAMA_URL}  [{conn}]
  Patience   : max silence {SOCK_TIMEOUT}s (NOVA_TIMEOUT) | keep_alive {KEEP_ALIVE} | ctx local {ctx_local}/cloud {ctx_cloud} (/ctxset)
  Web search : {'ready (DDG + Wikipedia + Stack Exchange)' if ns else 'UNAVAILABLE (nova_search.py missing)'}
  Tools      : {n_tools} commands ({n_model_tools} briefed to the model) | model tokens: {toks}
  Auto       : {('ON (yolo)' if sess.auto_yolo else 'ON') if sess.auto else 'off'} (max {AUTO_MAX_STEPS} steps)  |  changed this session: {len(sess.touched)} file(s)
  Loops      : tool rounds {MAX_TOOL_ROUNDS} | verify rounds {VERIFY_MAX_STEPS} | auto steps {AUTO_MAX_STEPS}
  Knowledge  : {kb_n} saved entries (/kb)  |  web cache: {cache_n} item(s)
  Undo       : {snap_n} auto unit(s) + {manual_n} checkpoint(s) (/undo [n], /snapshot)
  Git        : {'repo - auto-commits ON (nova: ...)' if git_repo else 'not a repo (auto-commit inactive)'}
  Safety     : explain={'ON' if sess.explain else 'off'}  autotest={'ON' if sess.autotest else 'off'}  guardian={'ON' if _guardian_master_on(sess) else 'off'} (fleet {guardian.lang_count() if guardian else 0}, /guardian)  hunter={'ON' if _probe_master_on(sess) else 'off'} (/probe)  vision={'ON' if (vision and (getattr(sess, 'vision_settings', None) or {}).get('approve', True)) else 'off'} (/vision)  policy: {policy_s}
  Plan       : {todo_prog or '-'} (/todo)  |  skills: {n_skills} (/skill list)
  Memory     : {'ON - conversation survives restarts' if sess.memory_on else 'OFF'}  |  bg tasks: /bg list
  Cost       : ledger ready (/cost, /estimate){cost_today}
  Workspace  : {sess.ws}  ({files_str})
  Preview    : {serve}
  /run       : timeout {sess.run_timeout}s   last: {sess.last_cmd or '-'}
  Context    : {len(sess.history)} messages in history (limit {HISTORY_LIMIT})
  Last failed: {'yes - use /fix' if sess.last_failed else '-'}""")

def cmd_export(sess, arg=""):
    if not sess.transcript:
        print(c(C.Y, "[!] nothing to export yet."))
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = sess.ws / f"nova_chat_{ts}.md"
    n = 1
    while out.exists():          # two exports within one second: no clobber
        n += 1
        out = sess.ws / f"nova_chat_{ts}_{n}.md"
    lines = ["# Nova Assistant chat export", f"_date: {datetime.now().isoformat(timespec='seconds')}_", ""]
    for role, text in sess.transcript:
        who = "**You**" if role == "user" else "**Nova Assistant**"
        lines += [who, "", text, "", "---", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(c(C.G, "Saved: " + str(out)))

# --------------------------------------------------------------- disk mode
# "Can this machine run a BIGGER model by keeping it on disk?" - YES, with
# honest caveats. Ollama memory-maps model files, so a model larger than
# RAM still runs: the OS pages the weights in from disk on demand. BUT every
# generated token must touch ALL weights once, so the part that does not fit
# in RAM is re-read from disk for every single token - speed drops to about
# (missing GB / disk bandwidth). /disk measures the real numbers instead of
# guessing and prints recipes to give the OS more room. Pure stdlib, fully
# fail-soft: works when Ollama is down and when RAM cannot be detected.
GB = 1024 ** 3

def _parse_meminfo(text):
    """Linux /proc/meminfo text -> {"MemTotal": kb, "MemAvailable": kb, ...}
    (int kilobytes for lines whose first field is numeric); None when nothing
    parses. Split from _read_meminfo so tests can feed synthetic text."""
    out = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0])
    return out or None

def _read_meminfo():
    """Linux memory info; None on other systems / on any failure."""
    try:
        return _parse_meminfo(
            Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

def detect_ram():
    """(total_bytes, available_bytes); (None, None) when undetectable.
    Windows via GlobalMemoryStatusEx, Linux via /proc/meminfo (real
    'available', not just 'free'), macOS/other POSIX via sysconf."""
    total = avail = None
    try:
        if os.name == "nt":
            import ctypes

            class _MSE(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = _MSE()
            st.dwLength = ctypes.sizeof(_MSE)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                total, avail = int(st.ullTotalPhys), int(st.ullAvailPhys)
        else:
            mi = _read_meminfo()
            if mi:
                if "MemTotal" in mi:
                    total = mi["MemTotal"] * 1024
                if "MemAvailable" in mi:
                    avail = mi["MemAvailable"] * 1024
            if total is None:  # macOS / other POSIX
                total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            if avail is None:
                avail = total  # conservative: assume all of it is usable
    except Exception:
        return None, None
    return total, avail

def model_sizes():
    """[(name, bytes_on_disk)] for every installed model; [] when Ollama is
    unreachable or the payload is unexpected - /disk must stay useful."""
    try:
        tags = http_get_json("/api/tags")
    except Exception:
        return []
    if not isinstance(tags, dict):
        return []
    out = []
    for m in tags.get("models") or []:
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("model") or ""
        size = m.get("size")
        if name and isinstance(size, (int, float)) and size > 0:
            out.append((name, int(size)))
    return out

def _disk_verdict(model_gb, avail_gb):
    """Pure verdict logic (unit-tested): (key, human line). The 0.85 headroom
    factor covers the KV cache, compute buffers and OS jitter so a model that
    merely 'equals free RAM' is not mislabeled as a full-speed fit."""
    if avail_gb is None:
        return "unknown", "RAM unknown - cannot judge"
    usable = avail_gb * 0.85
    if model_gb <= usable - 0.5:
        return "ram", "fits in free RAM (full speed)"
    if model_gb <= usable + 1.0:
        return "tight", "tight fit - close other apps for headroom"
    return "disk", "DISK-BACKED - runs from disk, slower (recipes below)"

def _print_speed_table(shortfall_gb):
    """Honest per-disk-type cost of re-reading the missing GB EVERY token.
    Bandwidth guesses are deliberately conservative: NVMe ~1.5, SATA ~0.4,
    HDD ~0.1 GB/s of sustained random-ish reads."""
    print(f"\n  Disk-mode speed estimate: ~{shortfall_gb:.1f} GB re-read from disk for EVERY token:")
    for label, bw in (("NVMe SSD", 1.5), ("SATA SSD", 0.4), ("Hard disk", 0.1)):
        sec = shortfall_gb / bw
        if sec >= 15:
            print(f"    {label:<10}: ~{sec:.0f} s/token  -> not practical")
        else:
            mins = max(int(sec * 300 / 60), 1)
            print(f"    {label:<10}: ~{sec:.1f} s/token  -> a 300-token answer in ~{mins} min")

def _print_disk_recipes(total_gb=None):
    """Copy-paste recipes to give the OS more room for disk-backed models.
    Nova Code NEVER runs these itself - they need sudo/admin rights."""
    swap_gb = "12" if (total_gb or 8) >= 8 else "8"
    print("\n  Give the model more room: use disk as overflow RAM (swap / pagefile):")
    if os.name == "nt":
        print("""    Windows - enlarge the pagefile:
      1. Win+R -> sysdm.cpl -> Advanced -> Performance 'Settings'
      2. Advanced -> Virtual memory 'Change' -> uncheck automatic management
      3. Custom size on your FASTEST drive, e.g. initial 4096 / maximum 12288 MB
      4. Set -> OK -> reboot""")
    else:
        print(f"""    Linux - create a {swap_gb} GB swap file (copy-paste):
      sudo fallocate -l {swap_gb}G /swapfile
      sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
      echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # survives reboot
    macOS: swap is automatic - nothing to do.""")
    print("""  Then pull a bigger model and re-run /disk, e.g.:  ollama pull qwen2.5-coder:7b
  Note: Ollama estimates memory before loading and may refuse a model it
  thinks cannot fit ('model requires more system memory...') - with swap
  active it usually loads. RAM is ALWAYS faster: a model that fits in RAM
  beats any disk-mode setup. SSD strongly recommended - on a hard disk this
  is too slow to be useful.""")

def _print_ram_kit():
    """Server-side Ollama env kit that slashes KV-cache RAM at a quality cost
    nobody notices on small models. Printed by /disk on EVERY path (even a
    RAM-fit machine benefits: freed RAM = room for a bigger model or window).
    Pure print - Nova Code never touches the user's Ollama config itself."""
    print("\n  Ollama RAM kit - cuts KV-cache RAM roughly in HALF (negligible quality loss):")
    if os.name == "nt":
        print("""    Windows (then quit Ollama from the tray and start it again):
      setx OLLAMA_NUM_PARALLEL 1
      setx OLLAMA_FLASH_ATTENTION 1
      setx OLLAMA_KV_CACHE_TYPE q8_0""")
    else:
        print("""    Linux (systemd service):  sudo systemctl edit ollama  ->  add under [Service]:
      Environment="OLLAMA_NUM_PARALLEL=1"
      Environment="OLLAMA_FLASH_ATTENTION=1"
      Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
    then: sudo systemctl restart ollama
    macOS / manual 'ollama serve': export the same three variables first.""")
    print("""    Why: PARALLEL=1 stops Ollama pre-allocating KV cache for several
    simultaneous requests; FLASH_ATTENTION + KV_CACHE_TYPE=q8_0 quantize the
    KV cache to ~half its memory. Agent-side extras:
      NOVA_NUM_CTX=2048      halve the context window (and its KV RAM)
                             (v8.3: /ctxset local 2048 does the same per
                             project - web Models tab has the panel)
      NOVA_KEEP_ALIVE=0      unload the model between messages (next message
                             reloads from disk - slower start, idle RAM free)""")

def cmd_disk(sess, arg=""):
    """RAM vs installed-model sizes: what fits, what is tight, what runs
    disk-backed - plus speed estimates, swap recipes and the Ollama RAM kit."""
    try:
        return _disk_report(sess)
    finally:
        _print_ram_kit()

def _disk_report(sess):
    """The measurement part of /disk (split out so the RAM kit prints on
    every early-return path). Fail-soft everywhere."""
    total, avail = detect_ram()
    prov = _provider_cfg()
    if prov.get("kind") not in ("ollama", "?"):
        print(c(C.D, f"  (note: active provider is {prov['label']} - "
                    "this advisor measures LOCAL Ollama models)"))
    if total is None:
        print(c(C.Y, "[!] could not detect RAM on this system - general advice:"))
        _print_disk_recipes()
        return
    t_gb, a_gb = total / GB, (avail or 0) / GB
    print(f"  RAM       : total {t_gb:.1f} GB, available {a_gb:.1f} GB")
    try:
        print(f"  Disk free : {shutil.disk_usage(sess.ws).free / GB:.1f} GB (workspace drive)")
    except Exception:
        pass
    sizes = model_sizes()
    if not sizes:
        print(c(C.Y, "  Models    : (Ollama not reachable - pull a model, then re-run /disk)"))
        _print_disk_recipes(t_gb)
        return
    base = sess.model.split(":")[0]
    print("  Models    :")
    disk_backed = []
    for name, size in sizes:
        key, line = _disk_verdict(size / GB, a_gb)
        cur = "*" if (name == sess.model or name.split(":")[0] == base) else " "
        print(f"    {cur} {name:<30} {human_size(size):>8}  -> {line}")
        if key == "disk":
            disk_backed.append(size / GB)
    if not disk_backed:
        print(c(C.G, "  Good news: every installed model fits in RAM - no disk mode needed."))
        print(c(C.D, "  Want a BIGGER brain? 'ollama pull qwen2.5-coder:7b' then re-run /disk."))
        return
    _print_speed_table(max(max(disk_backed) - a_gb, 0.1))
    _print_disk_recipes(t_gb)

# --------------------------------------------------------------- web research
def _need_search():
    if ns is None:
        print(c(C.Y, "[!] nova_search.py is missing next to nova.py - web research is disabled."))
        print(c(C.D, "    Everything else keeps working fully offline."))
        return False
    return True

def _offline_hint():
    print(c(C.D, "    (no internet? the agent still works fully offline; results are cached too)"))

def cmd_search(sess, arg):
    if not _need_search():
        return
    if not arg:
        print(c(C.Y, "[!] usage: /search css grid vs flexbox"))
        return
    print(c(C.D, "Searching the web (DuckDuckGo + Wikipedia + Stack Overflow, trusted first) ..."))
    try:
        results = ns.web_search(arg)
    except Exception as e:
        print(c(C.R, "[!] search failed: " + str(e)))
        _offline_hint()
        return
    for i, r in enumerate(results, 1):
        _, tier = ns.is_trusted(r["url"])
        print(f"  [{i}] ({ns.tier_badge(tier)}) " + c(C.B, r["title"][:72]))
        print("        " + c(C.D, r["url"]))
        if r.get("snippet"):
            print("        " + c(C.D, r["snippet"][:110]))
    ans = ui_input("Read a page into your next message? [number / a = top 3 / Enter = skip]: ").strip().lower()
    picks = []
    if ans == "a":
        picks = [r["url"] for r in results[:3]]
    elif ans.isdigit() and 1 <= int(ans) <= len(results):
        picks = [results[int(ans) - 1]["url"]]
    for u in picks:
        try:
            title, text = ns.fetch_page(u)
        except Exception as e:
            print(c(C.R, "[!] fetch failed: " + str(e)))
            continue
        _, tier = ns.is_trusted(u)
        if _attach(sess, f"web: {title[:40]}", f"{title}\n{u}\n{text}"):
            print(c(C.G, f"  attached: {title[:58]} ({len(text)} chars, {ns.tier_badge(tier)})"))
    if picks:
        print(c(C.D, "(attached research is sent with your next message - then just ask your question)"))

def _need_images():
    if imgsys is None:
        print(c(C.Y, "[!] nova_images.py is missing next to nova.py - photo search is disabled."))
        return False
    if not imgsys.available():
        print(c(C.Y, "[!] image search is off (NOVA_NO_IMAGES=1) or nova_search.py is missing."))
        return False
    return True

def cmd_img(sess, arg):
    """/img <query> [n] - search real photos on the internet and download
    the pick (default: the first) into assets/images/."""
    if not _need_images():
        return
    parts = str(arg or "").strip().split()
    n = 1
    if len(parts) > 1 and parts[-1].isdigit() and 1 <= int(parts[-1]) <= 8:
        n = int(parts.pop())
    query = " ".join(parts).strip()
    if not query:
        print(c(C.Y, "[!] usage: /img <query> [n]   e.g.:  /img mountain lake sunset 2"))
        return
    print(c(C.D, "Searching real photos (DuckDuckGo images / Openverse / Wikimedia) ..."))
    try:
        results = imgsys.search_images(query, limit=8)
    except Exception as e:
        print(c(C.R, "[!] image search failed: " + str(e)))
        _offline_hint()
        return
    if not results:
        print(c(C.Y, "[!] no photo found for that query (offline, or try an English query)."))
        return
    for i, r in enumerate(results, 1):
        dims = f"{r.get('width') or '?'}x{r.get('height') or '?'}"
        print(f"  [{i}] {r.get('source', '?'):9s} {dims:11s} "
              + c(C.B, (r.get('title') or '(untitled)')[:60]))
        print("        " + c(C.D, r.get("url", "")[:96]))
    pick = results[n - 1] if 1 <= n <= len(results) else results[0]
    used = n if 1 <= n <= len(results) else 1
    if used != n:
        print(c(C.Y, f"[i] only {len(results)} result(s) found - using [1]."))
    print(c(C.D, f"Downloading pick [{used}] ..."))
    # v8.6: the LOCAL AI must approve the selection before it lands in
    # assets (the user's law) - a REJECTED candidate is never written;
    # the honest rejection note is shown instead of a saved file.
    try:
        rel, meta = imgsys.save_result(
            pick, sess.ws,
            verify=lambda raw: _img_ai_verify(query, raw))
    except Exception as e:
        print(c(C.R, "[!] download failed: " + str(e)))
        _offline_hint()
        return
    if not rel:
        if meta.get("ai_rejected"):
            print(c(C.Y, "[!] the AI reviewer REJECTED that photo: "
                         + str(meta.get("ai_reason") or "unfit")
                         + " - try another number or a different query."))
            emit_event({"t": "note",
                        "text": "[img] AI rejected the pick: "
                                + str(meta.get("ai_reason") or "unfit")})
        else:
            print(c(C.R, "[!] could not download that photo "
                         f"({meta.get('error', 'unknown')}) - try another "
                         "number."))
        return
    print(c(C.G, f"  + {rel}  ({meta.get('bytes', 0) // 1024} KB, "
                 f"source: {pick.get('source', '?')})"))
    print(c(C.D, "Reference it in the site exactly like this: "
                 f'<img src="{rel}" alt="...">'))
    emit_event({"t": "note", "text": f"[img] '{query[:60]}' <- {rel} "
                                     f"({pick.get('source', '?')})"})

def cmd_imgdl(sess, arg):
    """/imgdl <url> [name] - download any image URL into assets/images/."""
    if not _need_images():
        return
    parts = str(arg or "").strip().split()
    if not parts:
        print(c(C.Y, "[!] usage: /imgdl <image-url> [name]"))
        return
    url = parts[0]
    name = parts[1] if len(parts) > 1 else None
    # v8.6: the LOCAL AI must approve the download before it lands in
    # assets (the user's law) - a rejected file is never written.
    try:
        rel, meta = imgsys.save_from_url(url, sess.ws, name=name,
                                         verify=_img_verify_human)
    except Exception as e:
        print(c(C.R, "[!] download failed: " + str(e)))
        _offline_hint()
        return
    if not rel:
        if meta.get("ai_rejected"):
            print(c(C.Y, "[!] the AI gatekeeper REJECTED that download: "
                         + str(meta.get("ai_reason") or "unfit image")))
            emit_event({"t": "note",
                        "text": "[imgdl] AI rejected the download: "
                                + str(meta.get("ai_reason") or "unfit")})
            return
        print(c(C.R, "[!] not a downloadable image "
                     f"({meta.get('error', 'unknown')}). "
                     "Only public http(s) image URLs are allowed."))
        return
    print(c(C.G, f"  + {rel}  ({meta.get('bytes', 0) // 1024} KB)"))
    emit_event({"t": "note", "text": f"[img] downloaded {rel}"})


def _need_fonts():
    if fontsys is None:
        print(c(C.Y, "[!] nova_fonts.py is missing next to nova.py - "
                     "the font library is disabled."))
        return False
    if not fontsys.available():
        print(c(C.Y, "[!] the font library is off (NOVA_NO_FONTS=1), "
                     "or app/fonts/index.json + woff2 files are missing."))
        return False
    return True


def cmd_fonts(sess, arg):
    """/fonts [fa|en|query] - list the local font library the agent picks
    from (name, category, weights). Persian first, English second."""
    if not _need_fonts():
        return
    lib = fontsys.library()
    q = str(arg or "").strip().lower()
    entries = sorted(lib.items(),
                     key=lambda kv: (kv[1].get("script", "") != "fa",
                                     kv[1].get("category", ""),
                                     kv[1].get("name", "")))
    if q in ("fa", "en"):
        entries = [(s, f) for s, f in entries
                   if f.get("script") == q]
    elif q:
        entries = [(s, f) for s, f in entries
                   if q in s.lower() or q in str(f.get("name", "")).lower()
                   or q in str(f.get("category", "")).lower()]
    if not entries:
        print(c(C.Y, "[!] no font matches that filter (try /fonts, /fonts fa, "
                     "/fonts display ...)"))
        return
    fa_n = sum(1 for _s, f in lib.items() if f.get("script") == "fa")
    en_n = len(lib) - fa_n
    print(c(C.B, f"Nova font library - {len(lib)} local, offline fonts "
                 f"({fa_n} Persian / {en_n} English), all free (SIL OFL):"))
    cur = None
    for slug, f in entries:
        script, cat = f.get("script", "?"), f.get("category", "?")
        if (script, cat) != cur:
            cur = (script, cat)
            label = {"fa": "فارسی", "en": "english"}.get(script, script)
            print(c(C.D, f"  [{label} / {cat}]"))
        ws = ",".join(sorted(f.get("weights", {}), key=lambda x: int(x or 0)))
        print(f"    {f.get('name', slug):24s} (weights: {ws})")
    print(c(C.D, "Nova picks the pairing automatically per project - "
                 "override per page with:"))
    print(c(C.D, '  <meta name="nova-fonts" content="heading=Lalezar; '
                 'body=Vazirmatn; mono=JetBrains Mono">'))
    emit_event({"t": "note", "text": f"[fonts] {len(entries)} font(s) listed "
                                     f"({fa_n} fa / {en_n} en available)"})

def cmd_learn(sess, arg):
    if not _need_search():
        return
    if not arg:
        print(c(C.Y, "[!] usage: /learn <topic>    e.g.:  /learn fastapi websocket"))
        return
    print(c(C.D, f"Learning '{arg}' - reading up to {ns.LEARN_PAGES} pages from different trusted domains ..."))
    try:
        digest, sources = ns.learn_topic(arg, status=lambda s: print(c(C.D, "  " + s)))
    except Exception as e:
        print(c(C.R, "[!] learning failed: " + str(e)))
        _offline_hint()
        return
    ns.kb_append(sess.kb_path, arg, digest)
    n = len(ns.kb_entries(sess.kb_path))
    print(c(C.G, f"Knowledge saved to {sess.kb_path.name} (now {n} entries)."))
    print(c(C.D, "(from now on it is injected into every conversation in this workspace)"))
    if ask("Also send it to the model now? [Y/n]: ").strip().lower() in ("", "y", "yes"):
        if _attach(sess, f"web research: {arg}", digest):
            print(c(C.G, "Attached - sent with your next message."))

def cmd_docs(sess, arg):
    if not _need_search():
        return
    if not arg or not arg.startswith(("http://", "https://")):
        print(c(C.Y, "[!] usage: /docs https://developer.mozilla.org/...   (full URL)"))
        return
    print(c(C.D, "Fetching: " + arg))
    try:
        title, text = ns.fetch_page(arg)
    except Exception as e:
        print(c(C.R, "[!] fetch failed: " + str(e)))
        _offline_hint()
        return
    _, tier = ns.is_trusted(arg)
    print(c(C.G, f"Got: {title[:70]} ({len(text)} chars, {ns.tier_badge(tier)} source)"))
    if _attach(sess, f"web page: {title[:40]}", f"{title}\n{arg}\n{text}"):
        print(c(C.D, "(sent with your next message)"))

def cmd_kb(sess, arg):
    if not _need_search():
        return
    entries = ns.kb_entries(sess.kb_path)
    sub = arg.split(maxsplit=1)[0].lower() if arg else ""
    if sub == "clear":
        if not entries:
            print(c(C.Y, "[!] knowledge base is already empty."))
            return
        if ask(f"Delete all {len(entries)} saved knowledge entries? [y/N]: ").strip().lower() in ("y", "yes"):
            try:
                sess.kb_path.unlink()
                print(c(C.G, "Knowledge base cleared."))
            except OSError as e:
                print(c(C.R, "[!] could not delete " + sess.kb_path.name + ": " + str(e)))
        else:
            print(c(C.D, "(kept)"))
        return
    if sub == "show":
        parts = arg.split()
        num = parts[1] if len(parts) > 1 else ""
        n = int(num) if num.isdigit() else 0
        if not (1 <= n <= len(entries)):
            print(c(C.Y, f"[!] usage: /kb show <1-{len(entries)}>" if entries else "[!] knowledge base is empty."))
            return
        e = entries[n - 1]
        print(c(C.B, f"\n[{n}] {e['topic']}   (saved {e['saved']})"))
        print(truncate(e["text"], MAX_READ_CHARS))
        return
    if sub == "load":
        # v5.1: no bundled book any more - load ANY user-chosen file
        # (markdown notes, API cheatsheets, style guides...) into the KB.
        rel = (arg.split(maxsplit=1)[1] if len(arg.split(maxsplit=1)) > 1 else "").strip()
        if not rel:
            print(c(C.Y, "[!] usage: /kb load <file>   e.g.:  /kb load docs/api-notes.md"))
            return
        try:
            p = safe_join(sess.ws, rel)
        except ValueError as e:
            print(c(C.R, "[!] " + str(e)))
            return
        if not p.is_file():
            print(c(C.Y, "[!] file not found (or it is a folder): " + rel))
            return
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(c(C.R, "[!] cannot read: " + str(e)))
            return
        text = raw.strip()
        if not text:
            print(c(C.Y, "[!] file is empty - nothing to learn."))
            return
        topic = "loaded: " + Path(rel).name
        ns.kb_append(sess.kb_path, topic, text[:2800])
        n = len(ns.kb_entries(sess.kb_path))
        print(c(C.G, f"Loaded '{rel}' into {sess.kb_path.name} (now {n} entries)."))
        print(c(C.D, "(injected up to the KB budget; raise with NOVA_KB_CHARS, /kb clear to drop)"))
        return
    if not entries:
        print(c(C.D, "Knowledge base is empty. Build it with:  /learn <topic>"))
        print(c(C.D, "(or import a file:  /kb load notes/architecture.md)"))
        return
    print(c(C.B, f"Knowledge base - {len(entries)} entries ({sess.kb_path.name}):"))
    for i, e in enumerate(entries, 1):
        print(f"  [{i}] " + c(C.B, e["topic"][:56]) + c(C.D, f"   saved {e['saved']}"))
    print(c(C.D, "(/kb show N - view an entry   |   /kb load <file> - import a file   |   "
               "/kb clear - delete all)"))

# --------------------------------------------------------------- repl
BANNER = """
  +--------------------------------------------------------+
  | {:^52} |
  | {:^52} |
  +--------------------------------------------------------+
""".format(f"{AGENT_NAME}  v{VERSION}",
           f"{CODING_BRAND} coding module | local AI, multi-model")

def repl(sess):
    print(c(C.P, BANNER))
    # v6.8: first-run setup wizard - once per workspace (skippable). Also
    # arms at-rest encryption when NOVA_PASSPHRASE is set.
    if secretbox is not None and nmem is not None:
        _pp = os.environ.get("NOVA_PASSPHRASE", "")
        if _pp:
            nmem.set_cipher(_pp)
            sess.lock_pass = _pp
            print(c(C.D, "  [lock] memory at rest: ENCRYPTED (NOVA_PASSPHRASE)"))
    _wiz = Path(sess.ws) / ".nova" / "doctor.json"
    if os.environ.get("NOVA_NO_WIZARD") != "1" and not _wiz.is_file():
        try:
            rep = run_doctor(sess.ws)
            n_ok = sum(1 for ch in rep["checks"] if ch["ok"])
            print(c(C.B, "\n  first-run check (setup wizard - /doctor to repeat):"))
            for ch in rep["checks"]:
                mark = c(C.G, "OK  ") if ch["ok"] else c(C.Y, "warn")
                print(f"    [{mark}] {ch['id']}: {ch['msg']}")
            print(c(C.D, f"    {n_ok}/{len(rep['checks'])} checks - "
                         "start by describing what you want to build.\n"))
        except Exception:
            pass  # the wizard must never block the REPL
    info = "" if (lmodels and str(sess.model).startswith(lmodels.LOCAL_PREFIX)) \
        else model_details(sess.model)
    print("  Model     : " + c(C.B, sess.model)
          + (c(C.D, "   (" + info + ")") if info else "")
          + c(C.D, _model_route_note(sess)))
    print("  Workspace : " + c(C.B, str(sess.ws)))
    kb_n = len(ns.kb_entries(sess.kb_path)) if ns else 0
    if kb_n:
        print(c(C.D, f"  Knowledge : {kb_n} learned entr{'y' if kb_n == 1 else 'ies'} in this workspace (/kb)"))
    print(c(C.D, "  Type /help for commands. Start a project by just describing it."))
    print(c(C.D, "  Weak hardware? The first answer can take minutes - a [waiting] timer will show it is alive.\n"))

    while True:
        try:
            if USE_COLOR and "readline" in sys.modules:
                # v6.5: readline measures the prompt with strlen(), counting
                # the invisible ANSI bytes - arrow keys / history recall
                # then garble the edited line. Wrap every escape in the
                # readline ignore-marker (\001..\002) so it is not counted.
                prompt = "\n\001" + C.G + "\002You > \001" + C.E + "\002"
            elif USE_COLOR:
                prompt = c(C.G, "\nYou > ")
            else:
                prompt = "\nYou > "
            line = input(prompt).strip()
        except KeyboardInterrupt:
            print(c(C.Y, "\n(interrupted - type /quit to exit)"))
            continue
        except EOFError:
            print(c(C.D, "\nBye!"))
            sess.save_memory()
            return
        if not line:
            _bg_notifications(sess)
            continue
        try:
            dispatch(sess, line)
        except KeyboardInterrupt:
            print(c(C.Y, "\n[interrupted]"))
        except Exception as e:  # never crash the loop on unexpected errors
            print(c(C.R, f"[!] internal error: {type(e).__name__}: {e}"))
            print(c(C.D, "(the session continues - if this repeats, please report it)"))
        _bg_notifications(sess)   # v5.0: finished background tasks surface here

# --------------------------------------------------------------- v3.0 commands
NOVA_MD_TEMPLATE = """# NOVA.md - project notes for Nova Code
(English only - this file is injected into the model's instructions.)

## What this project is
<one short paragraph>

## Stack & structure
- 

## Commands
- Run: 
- Test: 

## Conventions
- 

## Do not touch
- 
"""


def cmd_auto(sess, arg=""):
    """Toggle the autonomous build -> run -> fix loop."""
    sub = arg.strip().lower()
    if sub == "on":
        sess.auto = True
    elif sub == "off":
        sess.auto = False
        print(c(C.G, "Auto mode OFF - back to step-by-step."))
        return
    elif sub == "yolo":
        sess.auto = True
        sess.auto_yolo = True
        print(c(C.Y, "Auto mode ON + yolo: shell commands run WITHOUT confirmation."))
        print(c(C.D, "They run with your FULL user permissions - only the working "
                     "directory is the workspace. (/auto off to stop)"))
        return
    elif sub in ("", "status"):
        sess.auto = not sess.auto  # bare /auto toggles - the natural expectation
    else:
        print(c(C.Y, "[!] usage: /auto [on|off|yolo]"))
        return
    state = "ON" if sess.auto else "OFF"
    yolo = "  (yolo - no command confirmations)" if sess.auto and sess.auto_yolo else ""
    print(c(C.G if sess.auto else C.D, f"Auto mode: {state}{yolo}"))
    print(c(C.D, f"In auto mode every task runs up to {AUTO_MAX_STEPS} "
               "build -> run -> fix rounds automatically (files applied without asking, "
               "commands confirmed once)."))


def cmd_init(sess, arg=""):
    """Create NOVA.md - per-project memory that is injected as project law."""
    p = sess.ws / NOVA_MD_FILE
    if p.exists():
        print(c(C.Y, f"[!] {NOVA_MD_FILE} already exists - edit it directly; "
                     "it is re-read on every /rescan."))
        return
    try:
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(NOVA_MD_TEMPLATE)
    except OSError as e:
        print(c(C.R, "[!] cannot write: " + str(e)))
        return
    sess.rescan(silent=True)
    print(c(C.G, f"Created {NOVA_MD_FILE} - fill in the <placeholders> yourself or ask Nova to fill them."))
    print(c(C.D, "From now on it is injected into every conversation in this workspace "
               "(conventions, commands, structure outrank the model's defaults)."))


def cmd_compact(sess, arg=""):
    """Summarize the whole conversation into one message to free context
    (the /compact of small-context, weak-hardware life)."""
    if not sess.history:
        print(c(C.Y, "[!] nothing to compact - the conversation history is empty."))
        return
    transcript = "\n".join(
        (m["role"].upper() + ": " + m.get("content", "")[:4000])
        for m in sess.history)
    prompt = (
        "Summarize this coding conversation for a colleague who must continue the "
        "work with only this summary. Keep exactly: the project goal, files created "
        "or changed (with paths), key decisions, the exact commands that work, and "
        "the current status + next step. Maximum 150 words, plain text, no code "
        "blocks.\n\n--- conversation ---\n" + truncate(transcript, 12000)
        + "\n--- end of conversation ---")
    print(c(C.D, "Compacting the conversation (one model call, be patient on slow hardware) ..."))
    answer, _ = stream_chat(sess.model, [{"role": "user", "content": prompt}], 0.2,
                            sess=sess, section="utility")
    summary = answer.strip()
    if not summary:
        print(c(C.Y, "[!] compact failed (empty answer) - history kept unchanged."))
        return
    kept = len(sess.history)
    sess.history = [{"role": "user",
                     "content": "Conversation summary (older messages were compacted "
                                "with /compact - treat it as established context):\n"
                                + summary}]
    sess.transcript.append(("nova", f"[compact] {kept} messages replaced by a summary:\n{summary}"))
    print(c(C.G, f"Compacted: {kept} messages -> 1 summary message. Context is free again."))


# ----------------------------------------------------------- v8.3 ctxset
def _ctxset_report(sess):
    """One-line-per-fact status for /ctxset and the web panel."""
    local, cloud = sess._ctx_wins()
    cs = getattr(sess, "ctx_settings", None) or {}
    used = sess._ctx_used_tokens()
    backend = "local" if sess._local_brain() else "cloud"
    win = sess._prompt_ctx()
    pct = min(999, int(used * 100 / max(1, win)))
    lines = [
        f"backend           : {backend}  (active window {win} tokens)",
        f"local window      : {local} tokens" +
        ("  (custom)" if cs.get("custom") else "  (default - NOVA_NUM_CTX)"),
        f"cloud window      : {cloud} tokens" +
        ("  (custom)" if cs.get("custom") else "  (default - NOVA_CLOUD_CTX)"),
        f"auto compression  : {'on' if cs.get('auto_compact', True) else 'off'}"
        f"  (threshold {cs.get('compact_threshold', 0.85)}, newest "
        f"{cs.get('keep_recent', 4)} messages kept verbatim)",
        f"history           : {len(sess.history)} messages, ~{used} tokens "
        f"({pct}% of the active window)",
    ]
    return "\n".join(lines)


def _guardian_report(sess):
    """One-line-per-fact status for /guardian and the web panel."""
    s = getattr(sess, "guardian_settings", None) or {}
    tools = guardian.tools_available() if guardian else []
    langs = guardian.lang_count() if guardian else 0
    lines = [
        "master            : %s%s" % (
            "ON" if _guardian_master_on(sess) else "OFF",
            "  (NOVA_GUARDIAN=0)" if os.environ.get(
                "NOVA_GUARDIAN", "") == "0" else
            ("  (custom)" if s.get("custom") else "  (defaults)")),
        "fleet             : %d language sub-sub-agents" % langs,
        "model reviews     : %s  (parallel sub-agents on the local brain;"
        " never on a cloud key)" % ("on" if guardian.enabled(s, "model")
                                    else "off"),
        "dedicated search  : %s  (its own channel + cache; offline falls"
        " back to the built-in knowledge base)" % (
            "on" if guardian.enabled(s, "web") else "off"),
        "reject broken     : %s  (syntax errors refuse the whole batch"
        " BEFORE anything is written)" % (
            "on" if guardian.enabled(s, "reject_syntax") else "off"),
        "external tools    : %s" % (", ".join(tools) if tools
                                   else "none (structure + parsers still run)"),
    ]
    return "\n".join(lines)


def cmd_guardian(sess, arg=""):
    """v8.4 Code Guardian: the supervisor agent + the language fleet.
    /guardian              show the fleet state
    /guardian on|off       master switch
    /guardian model on|off parallel sub-agent reviews after each apply
    /guardian web on|off   the fleet's dedicated websearch enrichment
                           (offline always falls back to the built-in KB)
    /guardian reject on|off whether syntax errors refuse the batch
    /guardian langs        list every language the fleet covers
    /guardian audit        sweep the WHOLE workspace now (deterministic)
    /guardian reset        back to the defaults"""
    if guardian is None:
        print(c(C.Y, "[!] nova_guardian.py missing - the code guardian is"
                     " unavailable (the classic lint gate still runs)"))
        return
    parts = (arg or "").strip().split()
    if not parts:
        print(c(C.B, "Code Guardian (v8.4) - the supervisor + its fleet"))
        print(_guardian_report(sess))
        print(c(C.D, "  /guardian on|off | model on|off | web on|off |"
                     " reject on|off | langs | audit | reset"))
        return
    sub = parts[0].lower()
    if sub == "reset":
        err = guardian.reset_settings(sess.ws)
        if err:
            print(c(C.R, "[!] " + err))
            return
        sess.guardian_settings = guardian.load_settings(sess.ws)
        print(c(C.G, "Code guardian back to the defaults."))
        return
    if sub == "langs":
        print(c(C.B, "The fleet covers %d languages:" %
                     guardian.lang_count()))
        rows = []
        for lid, prof in guardian.LANGS.items():
            if lid == "generic":
                continue
            rows.append((prof["label"],
                         ", ".join(prof["exts"]) or "-",
                         prof["tool"] or ""))
        width = max(len(r[0]) for r in rows)
        for label, exts, tool in sorted(rows):
            extra = ("   [%s]" % tool) if tool else ""
            print("  %-*s  %-28s%s" % (width, label, exts, extra))
        print(c(C.D, "  (+ a generic structural profile for everything"
                     " else)"))
        return
    if sub == "audit":
        print(c(C.D, "[guardian] sweeping the workspace..."))
        found = guardian.audit_workspace(sess.ws)
        if not found:
            print(c(C.G, "[guardian] clean - no syntax problems found."))
            return
        print(c(C.Y, "[guardian] %d file(s) with problems:" % len(found)))
        for d in found[:20]:
            print(c(C.R, "  %s (%s)" % (d["file"], d["label"])))
            for line, msg in d["errors"][:4]:
                print("      line %s: %s" % (line or "?", msg))
            for line, msg in d["warns"][:2]:
                print(c(C.D, "      line %s: %s (warn)" % (line or "?", msg)))
        if len(found) > 20:
            print(c(C.D, "  ... and %d more" % (len(found) - 20)))
        return
    flag_map = {"model": "model", "web": "web", "reject": "reject_syntax"}
    if sub in ("on", "off"):
        ups = {"on": sub == "on"}
    elif sub in flag_map:
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            print(c(C.Y, "[!] usage: /guardian %s on|off" % sub))
            return
        ups = {flag_map[sub]: parts[1].lower() == "on"}
    else:
        print(c(C.Y, "[!] unknown subcommand - on | off | model | web |"
                     " reject | langs | audit | reset"))
        return
    err = guardian.save_settings(sess.ws, ups)
    if err:
        print(c(C.R, "[!] could not save: " + err))
        return
    sess.guardian_settings = guardian.load_settings(sess.ws)
    print(c(C.G, "Code guardian updated."))
    print(_guardian_report(sess))


def _probe_report(sess):
    """One-line-per-fact status for /probe and the web panel."""
    s = getattr(sess, "probe_settings", None) or {}
    pw = False
    if probe is not None:
        try:
            pw = probe.playwright_available()
        except Exception:
            pw = False
    return "\n".join([
        "master            : %s%s" % (
            "ON" if _probe_master_on(sess) else "OFF",
            "  (NOVA_PROBE=0)" if os.environ.get("NOVA_PROBE", "") == "0"
            else ("  (custom)" if s.get("custom") else "  (defaults)")),
        "wiring sweep      : %s  (ids/handlers/files/imports across the "
        "batch - dead wiring refuses it BEFORE anything is written)" % (
            "on" if probe.enabled(s, "wiring") else "off"),
        "smoke runs        : %s  (fresh entry scripts are executed with "
        "a tight timeout; crashes become findings)" % (
            "on" if probe.enabled(s, "smoke") else "off"),
        "browser probe     : %s  (headless console errors + button "
        "clicks when Playwright exists - %s)" % (
            "on" if probe.enabled(s, "browser") else "off",
            "available" if pw else "not installed (honest skip)"),
        "deep sweep        : %s  (v8.6: ANY code can carry a bug - "
        "undefined names, signature math, duplicate defs, unreachable "
        "code, stubs, extra functions)" % (
            "on" if probe.enabled(s, "deep") else "off"),
        "completeness      : %s  (request vs delivery, local brain "
        "only, advisory)" % ("on" if probe.enabled(s, "review")
                             else "off"),
    ])


def cmd_probe(sess, arg=""):
    """v8.5/v8.6 Bug Hunter: catches what syntax gates cannot.
    /probe                show the hunter state
    /probe on|off         master switch
    /probe wiring on|off  the cross-file wiring gate (dead ids/handlers/
                          files/imports refuse the batch pre-apply)
    /probe deep on|off    the v8.6 deep sweep (a bug can be a simple
                          function, extra code or missing code)
    /probe smoke on|off   execute fresh entry scripts (tight timeout)
    /probe browser on|off headless console + button clicks (Playwright)
    /probe review on|off  completeness review vs the request (local brain)
    /probe reject on|off  whether dead wiring refuses the batch
    /probe rejectdeep on|off  whether unambiguous deep findings refuse it
    /probe reset          back to the defaults"""
    if probe is None:
        print(c(C.Y, "[!] nova_probe.py missing - the bug hunter is "
                     "unavailable (the guardian + lint gates still run)"))
        return
    parts = (arg or "").strip().split()
    if not parts:
        print(c(C.B, "Bug Hunter (v8.5/v8.6) - the behavior probes"))
        print(_probe_report(sess))
        print(c(C.D, "  /probe on|off | wiring on|off | deep on|off |"
                     " smoke on|off | browser on|off | review on|off |"
                     " reject on|off | rejectdeep on|off | reset"))
        return
    sub = parts[0].lower()
    if sub == "reset":
        err = probe.reset_settings(sess.ws)
        if err:
            print(c(C.R, "[!] " + err))
            return
        sess.probe_settings = probe.load_settings(sess.ws)
        print(c(C.G, "Bug hunter back to the defaults."))
        return
    flag_map = {"wiring": "wiring", "smoke": "smoke",
                "browser": "browser", "review": "review",
                "reject": "reject_wiring", "deep": "deep",
                "rejectdeep": "reject_deep"}
    if sub in ("on", "off"):
        ups = {"on": sub == "on"}
    elif sub in flag_map:
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            print(c(C.Y, "[!] usage: /probe %s on|off" % sub))
            return
        ups = {flag_map[sub]: parts[1].lower() == "on"}
    else:
        print(c(C.Y, "[!] unknown subcommand - on | off | wiring | smoke"
                     " | browser | review | reject | reset"))
        return
    err = probe.save_settings(sess.ws, ups)
    if err:
        print(c(C.R, "[!] could not save: " + err))
        return
    sess.probe_settings = probe.load_settings(sess.ws)
    print(c(C.G, "Bug hunter updated."))
    print(_probe_report(sess))


def _vision_report(sess):
    """The /vision status block (plain, honest, one line per fact)."""
    st = getattr(sess, "vision_settings", None) or {}
    approve = vision.enabled(st, "approve") if vision else True
    strict = vision.enabled(st, "strict") if vision else False
    try:
        lcfg = _provider_cfg() or {}
    except Exception:
        lcfg = {}
    local = _is_free_local(lcfg)
    model = str(lcfg.get("model") or "") or "(no model)"
    if vision is None:
        cap = {"vision": False, "via": "missing",
               "detail": "nova_vision.py is missing next to nova.py"}
    else:
        cap = _vision_capability(lcfg)
    sees = (c(C.G, "YES") if cap.get("vision") else c(C.R, "NO")) \
        if local else c(C.Y, "n/a (cloud brain verifies)")
    print(f"""  Vision layer (v8.6) - the local AI approves internet photos
  Model      : {model}  ({'local' if local else 'cloud'})
  Sees photos: {sees}
  Detected by: {cap.get('via', '-')}  ({cap.get('detail', '-')})
  Approval   : {'ON - every /img pick, /imgdl download and AI photo fill needs a verdict' if approve else 'OFF - photos download without the AI gate'}
  Strict     : {'ON - a text-only local model refuses AI photo selection (placeholders only)' if strict else 'off - a text-only local model falls back to the cloud gate / honest pass'}""")


def cmd_vision(sess, arg=""):
    """v8.6 Vision layer: 100% automatic local-vision detection plus the
    approval policy for internet photos.
    /vision                 show the layer state
    /vision approve on|off  the local AI must approve every photo
    /vision strict on|off   a text-only local model refuses AI photos
    /vision check           force a fresh detection (drop the cache)
    /vision reset           back to the defaults"""
    if vision is None:
        print(c(C.Y, "[!] nova_vision.py is missing - the vision layer "
                     "is unavailable (photos pass unverified, pre-8.6 "
                     "behavior)"))
        return
    parts = (arg or "").strip().split()
    if not parts:
        print(c(C.B, "Vision layer (v8.6) - local-model photo approval"))
        _vision_report(sess)
        print(c(C.D, "  /vision approve on|off | strict on|off | check"
                     " | reset"))
        return
    sub = parts[0].lower()
    if sub == "reset":
        err = vision.reset_settings(sess.ws)
        if err:
            print(c(C.R, "[!] " + err))
            return
        sess.vision_settings = vision.load_settings(sess.ws)
        print(c(C.G, "Vision layer back to the defaults."))
        return
    if sub == "check":
        try:
            vision.clear_cache()
        except Exception:
            pass
        print(c(C.G, "Detection cache dropped - a fresh look:"))
        _vision_report(sess)
        return
    flag_map = {"approve": "approve", "strict": "strict"}
    if sub in flag_map:
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            print(c(C.Y, "[!] usage: /vision %s on|off" % sub))
            return
        err = vision.save_settings(
            sess.ws, {flag_map[sub]: parts[1].lower() == "on"})
        if err:
            print(c(C.R, "[!] could not save: " + err))
            return
        sess.vision_settings = vision.load_settings(sess.ws)
        print(c(C.G, "Vision layer updated."))
        _vision_report(sess)
        return
    print(c(C.Y, "[!] unknown subcommand - approve | strict | check |"
                 " reset"))


def cmd_ctxset(sess, arg=""):
    """v8.3 Context Engine: per-backend context windows + compression.
    /ctxset               show the current engine state
    /ctxset local 8192    local model window in tokens (Ollama num_ctx /
                          llama-server -c) - OVERRIDES the model default
    /ctxset cloud 65536   cloud provider window in tokens (kept separate
                          on purpose: cloud models have their own sizes)
    /ctxset auto on|off   smart digest when the conversation outgrows
                          the window (deterministic, no model call)
    /ctxset threshold .85 fold when the history reaches this share
    /ctxset keep 4        how many newest messages stay verbatim
    /ctxset reset         back to env/global defaults"""
    if ctxengine is None:
        print(c(C.Y, "[!] nova_ctxengine.py missing - context engine unavailable"))
        return
    parts = (arg or "").strip().split()
    if not parts:
        print(c(C.B, "Context Engine (v8.3)"))
        print(_ctxset_report(sess))
        print(c(C.D, "  /ctxset local <tokens> | cloud <tokens> | auto on|off |"
                     " threshold <0.5-0.95> | keep <2-16> | reset"))
        return
    sub = parts[0].lower()
    ups = {}
    if sub == "reset":
        err = ctxengine.reset_settings(sess.ws)
        if err:
            print(c(C.R, "[!] " + err))
            return
        sess.ctx_settings = ctxengine.load_settings(sess.ws)
        print(c(C.G, "Context engine reset to the env/global defaults."))
        return
    if sub in ("local", "cloud"):
        if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
            print(c(C.Y, f"[!] usage: /ctxset {sub} <tokens>"))
            return
        ups[sub + "_ctx"] = int(parts[1])
    elif sub == "auto":
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            print(c(C.Y, "[!] usage: /ctxset auto on|off"))
            return
        ups["auto_compact"] = parts[1].lower() == "on"
    elif sub == "threshold":
        try:
            ups["compact_threshold"] = float(parts[1])
        except (IndexError, ValueError):
            print(c(C.Y, "[!] usage: /ctxset threshold <0.5-0.95>"))
            return
    elif sub == "keep":
        if len(parts) < 2 or not parts[1].isdigit():
            print(c(C.Y, "[!] usage: /ctxset keep <2-16>"))
            return
        ups["keep_recent"] = int(parts[1])
    else:
        print(c(C.Y, "[!] unknown subcommand - local | cloud | auto |"
                     " threshold | keep | reset"))
        return
    err = ctxengine.save_settings(sess.ws, ups)
    if err:
        print(c(C.R, "[!] could not save: " + err))
        return
    sess.ctx_settings = ctxengine.load_settings(sess.ws)
    bad = ctxengine._valid_fields(ups)
    rejected = [k for k in ups if k not in bad]
    if rejected:
        print(c(C.Y, "[!] rejected out-of-range value(s): " + ", ".join(rejected)
                     + "  (kept the previous setting)"))
    print(c(C.G, "Context engine updated."))
    print(_ctxset_report(sess))
    if sub == "local":
        print(c(C.D, "  (Ollama requests carry it as num_ctx immediately;"
                     " a running llama-server picks it up on its next start)"))


def cmd_retry(sess, arg=""):
    """Discard the last answer and regenerate it."""
    if not sess.last_composed:
        print(c(C.Y, "[!] nothing to retry yet."))
        return
    if sess.history and sess.history[-1]["role"] == "assistant":
        sess.history.pop()           # the answer being regenerated
        if sess.history and sess.history[-1]["role"] == "user":
            sess.history.pop()       # its matching (composed) user message
    sess.transcript.append(("user", "(retry - the previous request was sent again)"))
    chat_turn(sess, sess.last_composed)


def cmd_review(sess, arg=""):
    """Strict senior-engineer code review of one workspace file."""
    if not arg:
        print(c(C.Y, "[!] usage: /review js/main.js"))
        return
    try:
        p = safe_join(sess.ws, arg)
    except ValueError as e:
        print(c(C.R, "[!] " + str(e)))
        return
    if not p.is_file():
        print(c(C.Y, "[!] file not found (or it is a folder): " + arg))
        return
    try:
        content = truncate(p.read_text(encoding="utf-8", errors="replace"),
                           MAX_LOAD_CHARS * 2)
    except OSError as e:
        print(c(C.R, "[!] cannot read: " + str(e)))
        return
    if not _attach(sess, arg, content):
        return
    prompt = ("Review the attached file like a strict senior engineer. List concrete "
              "problems only: bugs, security issues, edge cases, performance problems, "
              "unclear naming - ranked from most to least severe, each with a short "
              "hint about where it is and a one-line fix suggestion. Do NOT rewrite "
              "the whole file. If it is solid, say so in one line.")
    print(c(C.D, f"Reviewing {arg} ({len(content)} chars) ..."))
    chat_turn(sess, prompt)


def cmd_changes(sess, arg=""):
    """List files created/modified during this session."""
    if arg.strip().lower() in ("clear", "reset"):
        sess.touched = {}
        print(c(C.G, "Session change list cleared."))
        return
    if not sess.touched:
        print(c(C.D, "No files created or modified in this session yet."))
        return
    print(c(C.B, f"Files changed this session ({len(sess.touched)}):"))
    for name, kind in sess.touched.items():
        print(f"  [{kind:8s}] {name}")
    print(c(C.D, "(/changes clear - reset  |  /load <file> - show one to the model  |  "
               "/undo - restore the last batch)"))


# --------------------------------------------------------------- tool registry
# The SINGLE SOURCE OF TRUTH for every slash-command. /help, dispatch(),
# /status and the model's system-prompt briefing (model_tool_section) are all
# generated from this table.
#
#   ADD a tool    : write a normal `def cmd_x(sess, arg)` handler anywhere
#                   above, then add ONE entry here - done. Help, dispatch,
#                   /status and the model's own knowledge of its tools all
#                   update automatically.
#   REMOVE a tool : delete its entry (and optionally the handler).
#   UPGRADE a tool: edit its help / mhelp lines, or swap the handler.
#   Model view    : "model": True also teaches the tool to the model, with
#                   "mhelp" as its one-line explanation. Keep this flag for
#                   tools the model should recommend or that change how it
#                   answers; leave it off for pure user-utility commands.
#
# fields:
#   cmd      canonical "/name" (must be unique)
#   aliases  extra names that run the same handler (optional)
#   usage    display form, e.g. "/run <cmd>"
#   help     one line for the user
#   fn       handler(sess, arg)
#   model    also brief the model about this tool (needs "mhelp")
#   mhelp    one line for the MODEL (what it is good for)
#   needs_ns True -> hidden & disabled when nova_search.py is missing
# ------------------------------------------------------- v6.8: new toolbox
def cmd_hw(sess, arg=""):
    """/hw - hardware check + which local model tier fits + speculative
    decoding advice (zero network calls)."""
    if hardware is None:
        print(c(C.Y, "[!] nova_hardware.py missing"))
        return
    hw = hardware.detect()
    sg = hardware.suggest(hw)
    print(c(C.B, "hardware:"))
    print(hardware.report(hw, sg))
    spec = hardware.speculative(hw)
    print(c(C.D, "  Speculative decoding: " + spec["note"]))
    if spec.get("recipe"):
        print(c(C.D, "  recipe: " + spec["recipe"]))
    print(c(C.D, "  (v8.3: /ctxset local <tok> sets it per project and OVERRIDES the model default - web Models tab too)"))


def run_doctor(ws):
    """Setup wizard core (also served to the web face): offline checks,
    honest report. Returns the report dict."""
    checks = []
    # python version
    v = sys.version_info
    checks.append({"id": "python", "ok": v >= (3, 8),
                   "msg": f"python {v.major}.{v.minor}.{v.micro}"})
    # workspace writable
    try:
        (Path(ws) / ".nova").mkdir(parents=True, exist_ok=True)
        probe = Path(ws) / ".nova" / ".doctor_probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        checks.append({"id": "workspace", "ok": True, "msg": str(ws)})
    except OSError as e:
        checks.append({"id": "workspace", "ok": False, "msg": str(e)})
    # ollama server + models
    models = []
    try:
        models = list_installed_models()
        checks.append({"id": "ollama", "ok": bool(models),
                       "msg": (f"{len(models)} model(s) installed"
                               if models else "server up, no models - run: ollama pull qwen2.5-coder:1.5b")})
    except Exception:
        checks.append({"id": "ollama", "ok": False,
                       "msg": "not reachable - start it with: ollama serve"})
    # local gguf files
    try:
        lfiles = list_local_models(ws)
        n_run = sum(1 for e in lfiles if e.get("runnable"))
        checks.append({"id": "gguf", "ok": True,
                       "msg": f"{n_run} runnable .gguf file(s)" if n_run
                       else "no local .gguf files (fine, Ollama models are enough)"})
    except Exception:
        checks.append({"id": "gguf", "ok": True, "msg": "scan unavailable"})
    # hardware + suggestion
    if hardware is not None:
        hw = hardware.detect()
        sg = hardware.suggest(hw)
        checks.append({"id": "hardware", "ok": True,
                       "msg": f"RAM {hw.get('ram_gb') or '?'}GB, {hw.get('cores') or '?'} cores, "
                              f"{len(hw.get('gpus') or [])} GPU - suggested: "
                              f"{sg['params']} {sg['quant']}, num_ctx {sg['num_ctx']}"})
    # providers with keys
    try:
        if providers is not None:
            keyed = providers.names()
            with_keys = [n for n in keyed if providers.key_status(n)[0]]
            checks.append({"id": "providers", "ok": True,
                           "msg": f"{len(with_keys)} cloud provider(s) keyed"
                           if with_keys else "no cloud keys (local-only is fine: /key openai sk-...)"})
    except Exception:
        checks.append({"id": "providers", "ok": True, "msg": "unavailable"})
    # sandbox engines
    if sandbox is not None:
        eng = sandbox.detect_engines()
        checks.append({"id": "sandbox", "ok": True,
                       "msg": ", ".join(eng) if eng else
                       "no container runtime (optional - /sandbox stays off)"})
    # encryption
    checks.append({"id": "encryption", "ok": True,
                   "msg": "memory at rest: ENCRYPTED" if (nmem and nmem.encryption_on())
                   else "memory at rest: plaintext (optional: /lock <passphrase>)"})
    # benchmarks present?
    if bench is not None:
        data = bench.load(ws)
        n = len(data.get("models") or {})
        checks.append({"id": "bench", "ok": True,
                       "msg": f"{n} model(s) benchmarked (/bench)" if n
                       else "no benchmark data yet (optional: /bench)"})
    report = {"ok": all(ch["ok"] for ch in checks if ch["id"] != "python"
                        or v >= (3, 8)),
              "checks": checks,
              "ts": int(time.time())}
    # persist so the wizard only auto-runs once per workspace (atomic:
    # the web face's threaded GETs can hit this concurrently)
    try:
        d = Path(ws) / ".nova"
        d.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(report, ensure_ascii=False, indent=1)
        try:
            import nova_atomic as natom_mod
        except Exception:
            natom_mod = None
        if natom_mod is not None:
            natom_mod.write_text_atomic(d / "doctor.json", blob)
        else:
            (d / "doctor.json").write_text(blob, encoding="utf-8")
    except OSError:
        pass
    return report


def cmd_doctor(sess, arg=""):
    """/doctor - first-run setup wizard: checks python, workspace, Ollama,
    models, hardware, keys, sandbox, encryption - with copy-paste fixes."""
    rep = run_doctor(sess.ws)
    print(c(C.B, "=== Nova setup doctor ==="))
    for ch in rep["checks"]:
        mark = c(C.G, "OK  ") if ch["ok"] else c(C.R, "FAIL")
        print(f"  [{mark}] {ch['id']}: {ch['msg']}")
    n_ok = sum(1 for ch in rep["checks"] if ch["ok"])
    print(c(C.G if rep["ok"] else C.Y,
            f"=== {n_ok}/{len(rep['checks'])} checks passed ==="))


def cmd_timeline(sess, arg=""):
    """/timeline [n] - the visual history of every change unit (snapshot)
    Nova recorded: when, what note, which files. /timeline show <id>
    lists one unit's captured files."""
    if snaps is None:
        print(c(C.Y, "[!] nova_snapshots.py missing"))
        return
    parts = arg.split()
    if parts and parts[0] == "show" and len(parts) >= 2:
        units = snaps.list_units(sess.ws)
        u = next((x for x in units if x["id"] == parts[1]), None)
        if not u:
            print(c(C.Y, "[!] no such unit: " + parts[1]))
            return
        print(c(C.B, f"unit {u['id']}  ({len(u.get('files', []))} files, {u.get('note', '')})"))
        for f in u.get("files", [])[:40]:
            print("   ", f)
        return
    try:
        n = min(max(int(parts[0]) if parts else 15, 1), 50)
    except ValueError:
        n = 15
    # v6.9 fix: list_units already returns NEWEST-first; [-n:] took the
    # OLDEST n units and [::-1] printed them oldest->newest - the newest
    # changes never appeared at all.
    units = snaps.list_units(sess.ws)[:n]
    if not units:
        print(c(C.D, "Timeline is empty - apply some changes first."))
        return
    print(c(C.B, f"change timeline ({len(units)} unit(s), newest first):"))
    for u in units:
        ts = time.strftime("%m-%d %H:%M", time.localtime(u.get("ts", 0))) \
            if u.get("ts") else "?"
        nf = len(u.get("files", []))
        note = (u.get("note") or "")[:60]
        print(f"  {ts}  {u['id']}  {nf:>2d} file(s)  {note}")
    print(c(C.D, "(/timeline show <id> - files  |  /undo [n] - revert)"))


# ------------------------------------------------------- v7.5 power tools
def cmd_explore(sess, arg=""):
    """/explore [k] <request> - parallel multi-solution exploration: the
    model answers k times (LOCAL only - free), the answers are scored by
    the deterministic validator and the winner flows into the normal
    apply pipeline; the diffs between candidates are shown."""
    if explore is None or backend_policy is None:
        print(c(C.Y, "[!] explore is unavailable (nova_explore.py missing)"))
        return
    if not sess._local_brain():
        print(c(C.Y, "[!] explore runs on LOCAL brains only - a cloud API "
                     "would bill k times for one answer (use /brain coding "
                     "with a local model, or just ask normally)"))
        return
    parts = arg.split(None, 1)
    k = backend_policy.best_of_count("local")
    if parts and parts[0].isdigit():
        k = max(2, min(int(parts[0]), 4))
        arg = parts[1] if len(parts) > 1 else ""
    if not arg.strip():
        print(c(C.D, "usage: /explore [2-4] <request>"))
        return
    print(c(C.B, f"\n=== explore: {k} candidate answers ==="))
    sess._force_explore = k     # /explore overrides the difficulty gate
    try:
        result = chat_turn(sess, arg, auto=False)
    finally:
        sess._force_explore = 0
    ex = result.get("explore")
    if not ex:
        print(c(C.D, "(this answer came from a single generation - the task "
                     "was classified easy; /explore works best on real work)"))
        return
    print(c(C.B, f"\n=== candidate scores: "
                 + ", ".join(f"#{i + 1}={s}"
                             for i, s in enumerate(ex["scores"]))
                 + f" -> winner #{ex['chosen'] + 1} ==="))


def cmd_rag(sess, arg=""):
    """/rag [query | build | status] - the semantic codebase index."""
    if rag is None:
        print(c(C.Y, "[!] semantic RAG unavailable (nova_rag.py missing)"))
        return
    parts = arg.split(None, 1)
    sub = parts[0] if parts else ""
    if sub == "build":
        print(c(C.D, "[rag] building the semantic index (background)..."))
        rag.build_async(sess.ws, sess.ignore)
        return
    if sub == "status":
        st = rag.status(sess.ws)
        print(c(C.B, f"rag index: {st['chunks']} chunk(s), mode="
                     f"{st['mode'] or '-'}{' , building' if st['building'] else ''}"))
        if st.get("error"):
            print(c(C.D, "  note: " + st["error"]))
        print(c(C.D, "  (/rag <query> searches it | /rag build rebuilds)"))
        return
    q = arg.strip()
    if not q:
        st = rag.status(sess.ws)
        print(c(C.D, f"usage: /rag <query>   (index: {st['chunks']} chunks, "
                     f"mode {st['mode'] or 'not built'} - /rag build)"))
        return
    if not rag.load_index(sess.ws):
        print(c(C.Y, "[rag] no index yet - building in the background; "
                     "try again in a moment (/rag build to force)"))
        rag.build_async(sess.ws, sess.ignore)
        return
    hits = rag.search(sess.ws, q, k=5)
    if not hits:
        print(c(C.Y, "[rag] no matches (empty index or no signal)"))
        return
    print(c(C.B, f"semantic hits for \"{q[:60]}\":"))
    for f, ln, s, snip in hits:
        print(c(C.D, f"  {s:5.2f}  {f}:{ln}"))
        print("        " + snip.replace("\n", "\n        ")[:160])


def cmd_style(sess, arg=""):
    """/style [show|rebuild|clear] - the user's coding style profile."""
    if style is None:
        print(c(C.Y, "[!] style profile unavailable (nova_style.py missing)"))
        return
    sub = arg.strip().split()[0] if arg.strip() else "show"
    if sub == "rebuild":
        prof, err = style.refresh(sess.ws, sess.ignore)
        if err:
            print(c(C.Y, "[!] style save failed: " + err))
            return
        print(c(C.G, "[style] profile rebuilt from the workspace files"))
        sub = "show"
    if sub == "clear":
        try:
            p = style.style_path(sess.ws)
            if p.is_file():
                p.unlink()
            print(c(C.G, "[style] profile cleared - Nova stops matching it"))
        except OSError as e:
            print(c(C.Y, "[!] could not clear: " + str(e)))
        return
    prof = style.load(sess.ws)
    if not prof:
        print(c(C.D, "no style profile yet - it is built automatically "
                     "after the first apply (/style rebuild to force)"))
        return
    print(c(C.B, "observed coding style of this project:"))
    print(f"  indent: {prof.get('indent')} (width {prof.get('indent_width')})")
    print(f"  quotes: {prof.get('quotes')}   naming: {prof.get('naming')}")
    print(f"  comments: {prof.get('comment_lang')}   max line: ~{prof.get('max_line')}")
    if prof.get("frameworks"):
        print("  stack: " + ", ".join(prof["frameworks"]))
    print(c(C.D, "  (injected into every coding turn so new code blends in)"))


def cmd_route(sess, arg=""):
    """/route [fast <model>|strong <model>|off|status] - the EXPLICIT cloud
    difficulty map. Never a silent downgrade: with no map, cloud routing
    stays off; local routing (no cost) is automatic and separate."""
    if router is None:
        print(c(C.Y, "[!] router unavailable (nova_router.py missing)"))
        return
    m = router.load_route_map(sess.ws)
    parts = arg.strip().split()
    if not parts or parts[0] in ("status", "show"):
        print(c(C.B, "difficulty routing:"))
        print("  local  : automatic (easy=small model, hard=biggest) - free")
        print("  cloud  : " + ("OFF (1 answer, no switching)" if not m else
                             f"explicit map: fast={m.get('fast', '-') or '-'} "
                             f"strong={m.get('strong', '-') or '-'}"))
        print(c(C.D, "  set: /route fast <model-of-active-provider> | "
                     "/route strong <model> | /route off"))
        return
    if parts[0] == "off":
        err = router.save_route_map(sess.ws, "", "")
        print(c(C.G, "[route] cloud map cleared" if not err else
                 "[!] " + err))
        return
    if len(parts) >= 2 and parts[0] in ("fast", "strong"):
        fast = m.get("fast", "")
        strong = m.get("strong", "")
        if parts[0] == "fast":
            fast = parts[1]
        else:
            strong = parts[1]
        err = router.save_route_map(sess.ws, fast, strong)
        if err:
            print(c(C.Y, "[!] could not save the route map: " + err))
            return
        print(c(C.G, f"[route] cloud map saved: fast={fast or '-'} "
                     f"strong={strong or '-'}"))
        return
    print(c(C.D, "usage: /route [fast <model>|strong <model>|off|status]"))


def cmd_gitlog(sess, arg=""):
    """/gitlog [n] - the commit-per-edit history (the user's repo when the
    workspace is one, otherwise Nova's managed history repo)."""
    if commitmsg is None:
        print(c(C.Y, "[!] git history unavailable (nova_commitmsg.py missing)"))
        return
    try:
        n = min(max(int(arg.strip()), 1), 50) if arg.strip().isdigit() else 15
    except ValueError:
        n = 15
    mode = commitmsg.history_mode(sess.ws)
    if mode == "none":
        print(c(C.Y, "[!] git is not installed - install it for per-edit "
                     "history (all other features keep working)"))
        return
    if mode == "repo":
        rows = commitmsg.session_log(sess.ws, n)
        print(c(C.B, f"nova commits in the workspace repo (last {len(rows)}):"))
    else:
        rows = commitmsg.nova_log(sess.ws, n)
        print(c(C.B, f"commit-per-edit history (.nova/history.git, last "
                     f"{len(rows)}):"))
    if not rows:
        print(c(C.D, "  (empty - apply something first)"))
        return
    for h, subject in rows:
        print(f"  {h}  {subject}")


def cmd_graph(sess, arg=""):
    """/graph [--dot FILE | --mermaid FILE] - file dependency graph with
    cycle + orphan detection."""
    if depgraph is None:
        print(c(C.Y, "[!] nova_depgraph.py missing"))
        return
    out_dot, out_mmd = None, None
    toks = arg.split()
    i = 0
    while i < len(toks):
        if toks[i] == "--dot" and i + 1 < len(toks):
            out_dot = toks[i + 1]
            i += 2
        elif toks[i] == "--mermaid" and i + 1 < len(toks):
            out_mmd = toks[i + 1]
            i += 2
        else:
            i += 1
    print(c(C.D, "scanning imports..."))
    g = depgraph.build(sess.ws)
    if not g["nodes"]:
        print(c(C.Y, "[!] no .py/.js files found"))
        return
    print(c(C.B, depgraph.text_report(g)))
    for path, render, label in ((out_dot, depgraph.to_dot, "graphviz dot"),
                                (out_mmd, depgraph.to_mermaid, "mermaid")):
        if not path:
            continue
        try:
            t = safe_join(sess.ws, path)
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(render(g), encoding="utf-8", newline="\n")
            print(c(C.G, f"  wrote {label} -> {path}"))
        except (ValueError, OSError) as e:
            print(c(C.R, f"  {label}: {e}"))


def cmd_symbols(sess, arg=""):
    """/symbols <file> - syntax-aware skeleton (classes/functions with
    real signatures + line numbers) of one workspace file."""
    if astmap is None:
        print(c(C.Y, "[!] nova_astmap.py missing"))
        return
    name = (arg or "").strip()
    if not name:
        print(c(C.Y, "[!] usage: /symbols main.py"))
        return
    try:
        p = safe_join(sess.ws, name)
    except ValueError as e:
        print(c(C.R, "[!] " + str(e)))
        return
    if not p.is_file():
        print(c(C.Y, "[!] file not found: " + name))
        return
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(c(C.R, "[!] cannot read: " + str(e)))
        return
    syms = astmap.symbols_for(name, text)
    if not syms:
        print(c(C.D, f"(no symbols extracted for {name} - type not supported "
                     "or the file is data-only; the repomap still covers it)"))
        return
    print(c(C.B, f"{name}: {len(syms)} symbol(s)"))
    print(astmap.skeleton(syms))


def cmd_writedocs(sess, arg=""):
    """/writedocs - generate DOCS.md from docstrings + signatures (zero
    model calls, zero tokens). (/docs <url> stays the web-page reader)"""
    if quality is None:
        print(c(C.Y, "[!] nova_quality.py missing"))
        return
    name, err = quality.generate_docs(sess.ws)
    if err:
        print(c(C.Y, "[!] " + err))
        return
    print(c(C.G, f"wrote {name} - docstrings, classes, functions, "
                 "signatures and line numbers (edit freely, /writedocs overwrites)"))


def cmd_coverage(sess, arg=""):
    """/coverage - run the project's tests under coverage.py (when it is
    installed) and report the percentage + missed files."""
    if quality is None:
        print(c(C.Y, "[!] nova_quality.py missing"))
        return
    print(c(C.D, "running tests under coverage (may take a while) ..."))
    res = quality.run_coverage(sess.ws)
    if res.get("percent") is not None:
        print(c(C.G if res["percent"] >= 50 else C.Y,
                f"coverage: {res['percent']}%  (mode: {res['mode']})"))
    else:
        print(c(C.Y, f"coverage.py not installed - plain test run "
                     f"(mode: {res['mode']}). Install once:  pip install coverage"))
    if not res["ok"]:
        print(c(C.R, "[tests FAILED] " + res["report"][:600]))
    else:
        print(c(C.D, res["report"][:600]))


def cmd_lock(sess, arg=""):
    """/lock <passphrase>  - encrypt the conversation memory at rest
    (.nova/memory.json.enc). /lock (no arg) prompts HIDDEN (getpass).
    /lock off - back to plaintext. Wrong passphrase => the old memory
    simply stays unreadable until the right one is set (or /memory clear
    drops it)."""
    if secretbox is None or nmem is None:
        print(c(C.Y, "[!] nova_secretbox.py / nova_memory.py missing"))
        return
    sub = (arg or "").strip()
    if sub == "" and not NONINTERACTIVE:
        # v6.8.1: a passphrase typed at the prompt is echoed and lives in
        # readline history - the no-arg form asks for it hidden instead.
        try:
            import getpass
            sub = getpass.getpass("passphrase (input hidden): ").strip()
        except Exception:
            sub = ""
        if not sub:
            print(c(C.Y, "[!] no passphrase entered"))
            return
    if not sub or sub == "status":
        print(c(C.G if nmem.encryption_on() else C.D,
                "memory at rest: " + ("ENCRYPTED (/lock off to disable)"
                                      if nmem.encryption_on() else
                                      "plaintext - /lock <passphrase> to encrypt")))
        print(c(C.D, "  round-trip self-test: " + str(secretbox.self_test()[0])))
        return
    if sub.lower() == "off":
        nmem.set_cipher(None)
        sess.lock_pass = None
        print(c(C.Y, "encryption OFF - the next save writes plaintext "
                     "memory.json again."))
        return
    ok = nmem.set_cipher(sub)
    if ok:
        sess.lock_pass = sub
        print(c(C.G, "memory at rest: ENCRYPTED from now on "
                     "(.nova/memory.json.enc; the plaintext file is removed "
                     "on the next save). Same passphrase needed next run - "
                     "set it again via /lock or NOVA_PASSPHRASE."))
        sess.save_memory()   # re-save immediately: seal now, drop plaintext
    else:
        print(c(C.R, "[!] could not arm the cipher"))


def cmd_sandbox(sess, arg=""):
    """/sandbox [on|off|status|docker|podman|firejail|bwrap|image <n>|
    mem <2g>|cpus <2>] - run /run commands inside a local container."""
    if sandbox is None:
        print(c(C.Y, "[!] nova_sandbox.py missing"))
        return
    cfg = sandbox.load_config(sess.ws)
    toks = (arg or "").split()
    if not toks or toks[0] == "status":
        print(c(C.B, sandbox.status_line_all(sess.ws, cfg)))
        return
    if toks[0] == "files":
        print(c(C.B, sandbox.status_line_files()))
        print(c(C.D, "  (kill switch: NOVA_SANDBOX_FILES=0)"))
        return
    if toks[0] in ("on", "off"):
        sandbox.save_config(sess.ws, {"on": toks[0] == "on"})
        print(c(C.G if toks[0] == "on" else C.Y,
                "sandbox " + ("ON - /run commands execute inside the container "
                              "(no network by default)" if toks[0] == "on" else "OFF")))
        return
    if toks[0] in ("docker", "podman", "firejail", "bwrap"):
        sandbox.save_config(sess.ws, {"engine": toks[0], "on": True})
        print(c(C.G, f"sandbox engine: {toks[0]} (on)"))
        return
    if toks[0] == "image" and len(toks) >= 2:
        sandbox.save_config(sess.ws, {"image": toks[1]})
        print(c(C.G, "sandbox image: " + toks[1]))
        return
    if toks[0] == "mem" and len(toks) >= 2:
        sandbox.save_config(sess.ws, {"mem": toks[1]})
        print(c(C.G, "sandbox memory cap: " + toks[1]))
        return
    if toks[0] == "cpus" and len(toks) >= 2:
        sandbox.save_config(sess.ws, {"cpus": toks[1]})
        print(c(C.G, "sandbox cpu cap: " + toks[1]))
        return
    print(c(C.Y, "[!] usage: /sandbox [on|off|status|files|docker|podman|"
                 "firejail|bwrap|image <name>|mem <2g>|cpus <2>]"))


def cmd_limit(sess, arg=""):
    """/limit [cpu <sec>] [ram <MB|2g>] [off] - CPU/RAM ceilings for every
    /run command (NOT just a wall timeout)."""
    if rlimits is None:
        print(c(C.Y, "[!] nova_rlimits.py missing"))
        return
    toks = (arg or "").split()
    if not toks or toks[0] == "status":
        cpu = sess.limits.get("cpu_s")
        ram = sess.limits.get("ram_mb")
        print(c(C.D, f"limits: CPU {f'{cpu}s' if cpu else 'off'}, "
                     f"RAM {f'{ram}MB' if ram else 'off'}  "
                     "(env: NOVA_CPU_LIMIT / NOVA_RAM_LIMIT)"))
        return
    if toks[0] == "off":
        sess.limits = {"cpu_s": 0, "ram_mb": 0}
        print(c(C.Y, "CPU/RAM limits off."))
        return
    i = 0
    while i < len(toks):
        if toks[i] == "cpu" and i + 1 < len(toks):
            try:
                sess.limits["cpu_s"] = max(1, int(float(toks[i + 1])))
            except (ValueError, OverflowError):   # 'inf' raises OverflowError
                print(c(C.Y, "[!] bad cpu value: " + toks[i + 1]))
            i += 2
        elif toks[i] == "ram" and i + 1 < len(toks):
            mb = rlimits.parse_size(toks[i + 1])
            if mb:
                sess.limits["ram_mb"] = mb
                i += 2
            else:
                print(c(C.Y, "[!] bad ram value: " + toks[i + 1]))
                i += 2
        else:
            i += 1
    cpu = sess.limits.get("cpu_s")
    ram = sess.limits.get("ram_mb")
    print(c(C.G, f"limits: CPU {f'{cpu}s' if cpu else 'off'}, "
                 f"RAM {f'{ram}MB' if ram else 'off'} "
                 "(POSIX rlimits / Windows Job Objects - enforced by the OS)"))


def cmd_patch(sess, arg=""):
    """/patch <file.patch|last> - apply a REAL unified diff (git style)
    to the workspace, with validation, backup + snapshot. 'last' uses the
    model's last answer if it contained a ```diff block."""
    if diffview is None:
        print(c(C.Y, "[!] nova_diffview.py missing"))
        return
    src = (arg or "").strip()
    text = None
    if src == "last":
        text = sess.last_feedback_answer if hasattr(sess, "last_feedback_answer") else None
        text = text or (sess.history[-1]["content"] if sess.history and
                        sess.history[-1]["role"] == "assistant" else None)
        if not text:
            print(c(C.Y, "[!] no previous model answer with a patch"))
            return
        m = re.search(r"```diff\s*\n(.*?)```", text, re.S)
        if not m:
            # fallback: any fenced block (some models omit the 'diff' tag)
            m = re.search(r"```(?:\w+)?\s*\n(.*?)```", text, re.S)
        if m:
            text = m.group(1)
    else:
        try:
            p = safe_join(sess.ws, src)
            text = p.read_text(encoding="utf-8", errors="replace")
        except (ValueError, OSError) as e:
            print(c(C.R, "[!] " + str(e)))
            return
    files, problems = diffview.parse_patch(text)
    if problems:
        for pr in problems[:5]:
            print(c(C.Y, "[patch] " + pr))
    if not files:
        print(c(C.Y, "[!] no hunks parsed - is this a unified diff "
                     "(--- a/... +++ b/... @@ ...)?"))
        return
    sess.last_batch = []
    snap_batch, applied = [], []
    for rel, hunks in files.items():
        try:
            target = safe_join(sess.ws, rel)
            if not target.is_file():
                print(c(C.Y, f"[patch] {rel}: file does not exist - skipped "
                             "(patches change existing files)"))
                continue
            original = target.read_text(encoding="utf-8", errors="replace")
        except (ValueError, OSError) as e:
            print(c(C.R, f"[patch] {rel}: {e}"))
            continue
        new, n_applied, n_problems = diffview.apply_patch(original, hunks)
        for j, why in n_problems:
            print(c(C.Y, f"[patch] {rel} hunk {j}: {why}"))
        if not n_applied:
            continue
        bk = backup_file(sess, target)
        try:
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
        except OSError as e:
            print(c(C.R, f"[patch] {rel}: write failed: {e}"))
            continue
        sess.last_batch.append((target, bk))
        snap_batch.append((target, bk))
        sess.touched[rel] = "modified"
        applied.append(rel)
        print(c(C.G, f"  ~ {rel} [{n_applied}/{len(hunks)} hunks applied]"))
    if applied:
        sess.rescan(silent=True)
        if snaps is not None and snap_batch:
            snaps.push_auto_unit(sess.ws, snap_batch, note="patch: " + ", ".join(applied[:3]))
        if commitmsg is not None and commitmsg.is_repo(sess.ws):
            _git_autocommit(sess, applied)
        _feedback_gate(sess, applied)
    else:
        print(c(C.Y, "[patch] nothing applied"))


def cmd_bench(sess, arg=""):
    """/bench [model] - measure local models (speed + protocol compliance)
    so the right brain lands on the right section. Results: .nova/bench.json."""
    if bench is None:
        print(c(C.Y, "[!] nova_bench.py missing"))
        return
    names = [a.strip() for a in arg.split() if a.strip() and not a.startswith("-")]
    if not names:
        names = list_installed_models()[:bench.MAX_MODELS]
    if not names:
        print(c(C.Y, "[!] no installed Ollama models to benchmark"))
        return
    print(c(C.D, f"benchmarking {len(names)} model(s) - 3 tiny prompts each "
                 "(be patient on CPU)..."))
    for name in names:
        print(c(C.B, "  " + name + " ..."))
        try:
            row = bench.bench_model(name)
        except Exception as e:
            print(c(C.R, f"    failed: {e}"))
            continue
        err = bench.record(sess.ws, row)
        if err:
            print(c(C.Y, "    (could not save: " + err + ")"))
        print(c(C.D, f"    {row['tps']} tok/s, protocol "
                     f"{'OK' if row['protocol'] else 'FAIL'}, wall {row['wall']}s"))
    best_c, _ = bench.best_for(sess.ws, "coding")
    best_t, _ = bench.best_for(sess.ws, "talk")
    if best_c:
        print(c(C.G, f"best for coding: {best_c}"))
    if best_t:
        print(c(C.G, f"best for talk:   {best_t}"))
    print(c(C.D, "(ranking is used by the weak-answer auto-retry and shown "
                 "in /brain)"))


def _agent_chat(sess):
    """Utility chat fn for the sub-agent module (returns text or '')."""
    def _chat(prompt, section="utility"):
        answer, _complete = stream_chat(sess.model,
                                        [{"role": "user", "content": prompt}],
                                        0.4, sess=sess, section=section)
        return answer
    return _chat


def cmd_agent(sess, arg=""):
    """/agent <goal> - split the goal into independent sub-tasks and run
    them on PARALLEL local sub-agents (Ollama serves streams concurrently).
    Sub-agents DRAFT text only; nothing is applied without you."""
    if subagent is None:
        print(c(C.Y, "[!] nova_subagent.py missing"))
        return
    goal = (arg or "").strip()
    if not goal:
        print(c(C.Y, "[!] usage: /agent <goal to split>"))
        return
    chat = _agent_chat(sess)
    print(c(C.D, "planning sub-tasks (one utility call)..."))
    tasks = subagent.split_tasks(goal, chat)
    if not tasks:
        print(c(C.Y, "[!] the model could not split this goal - do it "
                     "yourself with several normal prompts"))
        return
    print(c(C.B, f"sub-tasks ({len(tasks)}):"))
    for i, t in enumerate(tasks, 1):
        print(f"  [{i}] {t}")
    print(c(C.D, f"running {len(tasks)} sub-agent(s) in parallel..."))
    global _PARALLEL_DEPTH
    _PARALLEL_DEPTH += 1
    try:
        results = subagent.run_parallel(
            tasks, lambda t: chat(
                f"You are one helper among several working independently. "
                f"Do YOUR sub-task only, concretely, in plain text with small "
                f"code snippets when useful (max ~200 lines total):\n{t}"))
    finally:
        _PARALLEL_DEPTH -= 1
    for i, (t, res, err) in enumerate(results, 1):
        print(c(C.B, f"\n--- sub-agent {i}: {t} ---"))
        if err:
            print(c(C.R, "(failed: " + err + ")"))
        else:
            print((res or "(empty)").strip()[:2500])
    print(c(C.D, "merging ..."))
    merged = subagent.merge_report(goal, results, chat)
    print(c(C.B, "\n=== merged plan ==="))
    print((merged or "(merge failed)").strip()[:3000])


def cmd_selftest(sess, arg=""):
    """/selftest [rounds] - the real self-test loop: the model writes
    tests for the files it just changed, the tests RUN, failures go back
    to the model for fixing - repeat until green or rounds exhausted."""
    rounds = 2
    try:
        rounds = min(max(int(arg.strip() or 2), 1), 4)
    except ValueError:
        rounds = 2
    if not sess.touched:
        print(c(C.Y, "[!] nothing changed in this session yet - apply some "
                     "files first (selftest hardens YOUR changes)"))
        return
    files = ", ".join(list(sess.touched)[:8])
    print(c(C.B, f"self-test loop: {rounds} round(s) max, target: {files}"))
    # v6.8.1: the apply-time feedback gate ALREADY runs the suite - running
    # it again right after doubled the wall time on weak hardware.
    _saved_autotest = sess.autotest
    sess.autotest = False
    try:
        for r in range(1, rounds + 1):
            print(c(C.B, f"--- round {r}/{rounds}: model writes the tests ---"))
            prompt = (
                f"Write focused unit tests for these files of the current project: "
                f"{files}. Detect the existing test framework first; if none, use "
                f"plain pytest-style functions in tests/test_nova_selftest.py. "
                f"Test the ACTUAL behavior, keep it small and deterministic. "
                f"Output the test file(s) with the === FILE: === format only.")
            result = chat_turn(sess, prompt, auto=True)
            if not result.get("applied"):
                print(c(C.Y, "[!] the model produced no test file - stopping"))
                return
            print(c(C.D, "running the test suite ..."))
            try:
                res = feedback.run_tests(sess.ws) if feedback else None
            except Exception as e:
                res = {"ok": True, "cmd": None, "report": f"(runner failed: {e})"}
            if res is None or not res.get("cmd"):
                print(c(C.Y, "[!] no test command detected - wrote tests but "
                             "cannot run them (add pytest)"))
                return
            if res.get("ok"):
                print(c(C.G, f"[selftest] GREEN after {r} round(s) - " + res["report"]))
                return
            print(c(C.Y, "[selftest] red: " + res["report"][:200]))
            if r == rounds:
                print(c(C.Y, "[selftest] rounds exhausted - the failing output is "
                             "in the transcript; fix manually or /fix"))
                return
            print(c(C.D, "asking the model to fix the failures..."))
            fix_prompt = (
                "The unit tests FAILED with this output:\n\n" +
                (res.get("tail") or res.get("report", ""))[:3000] +
                "\n\nDecide: is the TEST wrong or the CODE wrong? Fix whichever "
                "is at fault. Small change: === EDIT: === block; new content: "
                "=== FILE: === block. Then end with the exact re-run command as "
                "'Run: <command>'.")
            chat_turn(sess, fix_prompt, auto=True)
    finally:
        sess.autotest = _saved_autotest
    print(c(C.Y, "[selftest] finished (still red?) - check /changes"))


# ------------------------------------------------- v7.13: nova intel
# The intelligence layer's user face: the integrated project profile,
# the dependency-aware task graph, semantic memory, the context engine,
# impact analysis, regression detection, test skeletons, the critic
# and the multi-project registry. Every command degrades alone.
def _intel_need():
    if intel is None:
        print(c(C.Y, "[!] nova_intel.py missing - the intelligence layer "
                     "is not installed (everything else keeps working)"))
        return False
    return True


def _nova_home():
    """Home for CROSS-project stores (the workspaces registry). The
    per-project stores stay in <ws>/.nova/ - independence preserved.
    NOVA_HOME overrides (tests / portable installs)."""
    env = os.environ.get("NOVA_HOME", "")
    return Path(env) if env else (Path.home() / ".nova")


def cmd_intel(sess, arg=""):
    """/intel [rescan] - the integrated project intelligence profile."""
    if not _intel_need():
        return
    it = intel.ProjectIntelligence(sess.ws)
    if (arg or "").strip().lower() == "rescan":
        it.scan()
        print(c(C.G, "project intel rescanned."))
    else:
        _data, changed = it.refresh_if_stale()
        if changed:
            print(c(C.D, "(scan refreshed - the project changed since "
                         "the last look)"))
    print(c(C.B, it.summary_text()))
    st = it.stats()
    if not st["fresh"]:
        print(c(C.Y, "(the tree changed again - next query rescans)"))
    print(c(C.D, "(/intel rescan - force   |   /ctx <query> - auto "
                 "context   |   /tasks - the plan)"))


def cmd_tasks(sess, arg=""):
    """/tasks - the REAL dependency-aware task graph."""
    if not _intel_need():
        return
    tg = intel.TaskGraph(sess.ws / ".nova" / "tasks.json")
    parts = (arg or "").strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    try:
        if sub in ("", "list", "show"):
            print(c(C.B, tg.text_report()))
            print(c(C.D, "(/tasks add <title> [@t1,t2] - dependent task   |   "
                         "/tasks done t1   |   /tasks rm t1   |   "
                         "/tasks impact t1 - what depends on it)"))
        elif sub == "add":
            deps = []
            tags = []
            title_words = []
            for w in rest.split():
                if w.startswith("@") and len(w) > 1:
                    deps += [d for d in w[1:].split(",") if d]
                elif w.startswith("#") and len(w) > 1:
                    tags.append(w[1:])
                else:
                    title_words.append(w)
            tid = tg.add(" ".join(title_words), deps=deps, tags=tags)
            print(c(C.G, "added %s: %s" % (tid, tg.get(tid)["title"])))
            if deps:
                print(c(C.D, "blocked by: " + ", ".join(deps)))
        elif sub in ("done", "doing", "fail", "todo"):
            tid = rest.split()[0] if rest.split() else ""
            tg.set(tid, status={"done": "done", "doing": "doing",
                                "fail": "failed", "todo": "todo"}[sub])
            print(c(C.G, "%s -> %s" % (tid, sub)))
            if sub == "done":
                ready = tg.ready()
                if ready:
                    print(c(C.B, "now ready: " + ", ".join(ready)))
        elif sub == "note":
            bits = rest.split(maxsplit=1)
            if len(bits) < 2:
                print(c(C.Y, "[!] usage: /tasks note t1 <text>"))
                return
            tg.set(bits[0], note=bits[1])
            print(c(C.G, "note saved on %s" % bits[0]))
        elif sub == "dep":
            bits = rest.split()
            if len(bits) < 2:
                print(c(C.Y, "[!] usage: /tasks dep t2 t1[,t3]  "
                             "(t2 depends on t1,t3)"))
                return
            tg.set(bits[0], deps=[d for d in bits[1].split(",") if d])
            print(c(C.G, "%s now depends on %s" % (bits[0], bits[1])))
        elif sub == "rm":
            if tg.remove(rest.split()[0] if rest.split() else ""):
                print(c(C.G, "removed (dependent tasks updated)"))
            else:
                print(c(C.Y, "[!] no such task"))
        elif sub == "impact":
            tid = rest.split()[0] if rest.split() else ""
            deps_chain = tg.dependents(tid)
            if deps_chain:
                print(c(C.B, "if %s slips, these wait: %s"
                            % (tid, ", ".join(deps_chain))))
            else:
                print(c(C.D, "nothing depends on %s" % tid))
        elif sub == "ready":
            ready = tg.ready()
            print(c(C.B, "ready now: " + (", ".join(ready) or "(none)")))
            print(c(C.D, "blocked: " + (", ".join(tg.blocked()) or "(none)")))
        else:
            print(c(C.Y, "[!] usage: /tasks [add|done|doing|fail|todo|note|"
                         "dep|rm|impact|ready] ..."))
    except ValueError as e:
        print(c(C.Y, "[!] " + str(e)))


def cmd_mem(sess, arg=""):
    """/mem - the SEMANTIC project memory (remember / recall / forget)."""
    if not _intel_need():
        return
    mem = intel.SemanticMemory(sess.ws / ".nova" / "memory_vec.json")
    parts = (arg or "").strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else "stats"
    rest = parts[1] if len(parts) > 1 else ""
    if sub == "remember":
        if not rest:
            print(c(C.Y, "[!] usage: /mem remember <fact or decision> "
                         "[#tag]"))
            return
        tags = [w[1:] for w in rest.split() if w.startswith("#") and
                len(w) > 1]
        text = " ".join(w for w in rest.split()
                        if not (w.startswith("#") and len(w) > 1))
        kind = "decision" if any(w in text.lower() for w in
                                 ("decided", "we use", "from now on",
                                  "تصمیم", "قرار شد")) else "fact"
        mid = mem.remember(text, kind=kind, tags=tags)
        print(c(C.G, "remembered (%s): %s" %
                    (kind, (mem.recall(text, k=1) or [{}])[0].get(
                        "id", mid or ""))))
        print(c(C.D, "(recalled later by MEANING - /mem recall <words>)"))
    elif sub == "recall":
        if not rest:
            print(c(C.Y, "[!] usage: /mem recall <query>"))
            return
        hits = mem.recall(rest, k=6)
        if not hits:
            print(c(C.D, "nothing relevant in memory yet"))
            return
        for h in hits:
            print(c(C.B, "  %s  %.3f  [%s]" % (h["id"], h["score"],
                                               h["kind"]))
                  + " " + truncate(h["text"].replace("\n", " "), 100))
    elif sub == "forget":
        n = mem.forget(rest.strip())
        print(c(C.G, "forgot %d record(s)" % n) if n
              else print(c(C.Y, "[!] no such id")))
    else:
        print(c(C.B, mem.text_report()))
        print(c(C.D, "(/mem remember <text> | /mem recall <query> | "
                     "/mem forget <id>)"))


def cmd_ctx(sess, arg=""):
    """/ctx <query> - the Context Engine: the most precise context for
    one query, assembled from tasks + project + memory + KB."""
    if not _intel_need():
        return
    query = (arg or "").strip()
    if not query:
        print(c(C.Y, "[!] usage: /ctx <what you are about to do>"))
        return
    eng = intel.ContextEngine(sess.ws, kb_path=sess.kb_path)
    text, sources = eng.assemble(query)
    if not text:
        print(c(C.D, "no context earned for that query yet"))
        return
    print(c(C.B, text))
    print(c(C.D, "(sources: " + " > ".join(sources) +
                 "   |   sent to the model only when you ask for it)"))


def cmd_impact(sess, arg=""):
    """/impact <file...> - the blast radius BEFORE changing a file."""
    if not _intel_need():
        return
    paths = (arg or "").split()
    if not paths:
        print(c(C.Y, "[!] usage: /impact <file> [more files...]"))
        return
    try:
        report = intel.ImpactAnalyzer(sess.ws).text_report(paths)
    except Exception as e:
        print(c(C.R, "[!] impact analysis failed: " + str(e)))
        return
    print(c(C.B, report))


def cmd_regress(sess, arg=""):
    """/regress baseline|check - honest before/after test comparison."""
    if not _intel_need():
        return
    sub = (arg or "").strip().lower() or "check"
    runner = (lambda: feedback.run_tests(sess.ws)) if feedback else None
    if runner is None:
        print(c(C.Y, "[!] nova_feedback.py missing - no test runner"))
        return
    rd = intel.RegressionDetector(sess.ws, runner=runner)
    if sub == "baseline":
        res = rd.baseline()
        state = "green" if res.get("ok") else (
            "FAILING" if res.get("ok") is False else "no tests detected")
        print(c(C.G if res.get("ok") else C.Y,
                "baseline saved: %s%s" % (state,
                " (%s)" % res["cmd"] if res.get("cmd") else "")))
        return
    res = rd.check()
    verdict = res.get("verdict", "?")
    color = {"stable": C.G, "fixed": C.G, "new-fail": C.R,
             "still-failing": C.Y}.get(verdict, C.D)
    print(c(color, "[regress] %s - %s" % (verdict, res.get("note", ""))))
    if res.get("report_head") and verdict in ("new-fail", "error"):
        print(c(C.D, "  " + res["report_head"][:300]))


def cmd_gentests(sess, arg=""):
    """/gentests <file> - runnable test skeletons for changed/new code."""
    if not _intel_need():
        return
    rel = (arg or "").strip()
    if not rel:
        print(c(C.Y, "[!] usage: /gentests <file>   e.g.: /gentests "
                     "js/main.js"))
        return
    out = intel.TestGenerator(sess.ws).gen_for_file(rel)
    if out.get("ok"):
        print(c(C.G, "generated %d case(s): %s" % (out["cases"],
                                                   out["path"])))
        print(c(C.D, "(existence pins RUN green; smoke bodies SKIP until "
                     "you fill them - honest by construction)"))
    else:
        print(c(C.Y, "[!] " + out.get("error", "generation failed")))


def cmd_critic(sess, arg=""):
    """/critic - the staged self-review of this session's changed files."""
    if not _intel_need():
        return
    if not sess.touched:
        print(c(C.D, "nothing changed in this session yet - apply files "
                     "first, then /critic scores the batch"))
        return
    files = list(sess.touched)
    imp = {}
    try:
        imp = intel.ImpactAnalyzer(sess.ws).analyze(files)
    except Exception:
        pass
    fbk = getattr(sess, "last_feedback", None) or {}
    evidence = {"files": files, "syntax": fbk.get("syntax") or [],
                "lint": fbk.get("lint") or [], "impact": imp,
                "tests": fbk.get("tests")}
    print(c(C.B, intel.Critic.text_report(evidence)))
    plan = intel.SmartRollback.plan(sess.ws, "rollback"
                                    if evidence["syntax"] and
                                    (fbk.get("tests") or {}).get("ok") is
                                    False else "fix")
    if plan["rollback"] and plan["snapshot"]:
        print(c(C.Y, "last snapshot: %s (/undo restores it)"
                    % plan["snapshot"]))


def _workspaces_registry():
    return intel.Workspaces(_nova_home() / "workspaces.json")


def cmd_workspaces(sess, arg=""):
    """/workspaces - many projects, each independently remembered."""
    if not _intel_need():
        return
    reg = _workspaces_registry()
    parts = (arg or "").strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""
    if sub == "add":
        bits = rest.split(maxsplit=1)
        if not bits:
            print(c(C.Y, "[!] usage: /workspaces add <path> [name]"))
            return
        path = Path(bits[0]).expanduser()
        if not path.is_absolute():
            path = Path(sess.ws) / path
        entry, created = reg.register(path, name=bits[1] if len(bits) > 1
                                      else None)
        print(c(C.G, ("registered" if created else "updated") + ": "
                    + entry["name"] + "  " + entry["path"]))
        print(c(C.D, "(each project keeps its OWN .nova/ - tasks, memory "
                     "and intel never leak between projects)"))
    elif sub == "rm":
        if not rest:
            print(c(C.Y, "[!] usage: /workspaces rm <path-or-number>"))
            return
        rows = reg.list()
        target = None
        if rest.isdigit() and 1 <= int(rest) <= len(rows):
            target = rows[int(rest) - 1]["path"]
        else:
            for r in rows:
                if r["path"] == str(Path(rest).expanduser().resolve()):
                    target = r["path"]
        if target and reg.unregister(target):
            print(c(C.G, "removed from the registry (files untouched)"))
        else:
            print(c(C.Y, "[!] not found in the registry"))
    elif sub == "use":
        rows = reg.list()
        if not (rest.isdigit() and 1 <= int(rest) <= len(rows)):
            print(c(C.Y, "[!] usage: /workspaces use <number> (see "
                         "/workspaces)"))
            return
        target = rows[int(rest) - 1]
        sess.set_workspace(target["path"])
        print(c(C.G, "switched to: " + target["name"]))
    else:
        print(c(C.B, reg.text_report(current=str(sess.ws))))
        print(c(C.D, "(/workspaces add <path> [name] | use <n> | "
                     "rm <n>)"))


def cmd_loop(sess, arg=""):
    """/loop <goal> - the autonomous, instrumented agent loop."""
    goal = (arg or "").strip()
    if not goal:
        print(c(C.Y, "[!] usage: /loop <what to build>   - Nova plans, "
                     "writes, runs, fixes and verifies in rounds, then "
                     "reports honestly (dashboard: the Intel tab)"))
        return
    print(c(C.B, "[loop] starting the instrumented agent loop - phases: "
                 "observe > decide > execute > test > fix > verify"))
    auto_build(sess, goal)


def cmd_workspace(sess, arg):
    if arg:
        sess.set_workspace(arg)
    else:
        print("Workspace: " + str(sess.ws))
        sess.rescan()


def cmd_rescan(sess, arg=""):
    sess.rescan()


def cmd_clear(sess, arg=""):
    sess.history = []
    reset_fix_rounds(sess)   # v8.11: a conscious reset re-arms the fix brake
    print(c(C.G, "Conversation context cleared."))


def cmd_quit(sess, arg=""):
    stop_serve(sess)
    sess.save_memory()
    print(c(C.D, "Bye!"))
    raise SystemExit(0)


def _cmd_fix(sess, arg=""):
    fix_flow(sess)


def cmd_autofix(sess, arg=""):
    """v8.11: the terminal face of the web /autofix switch - shows or
    toggles the failed-run fix rounds and re-arms the fix budget (the
    loop-stop messages point HERE, so the command must exist)."""
    sub = (arg or "").strip().lower()
    if sub in ("on", "off"):
        sess.autofix = (sub == "on")
        if sess.autofix:
            reset_fix_rounds(sess)
    elif sub:
        print(c(C.Y, "[!] usage: /autofix [on|off]"))
        return
    state = "ON" if getattr(sess, "autofix", True) else "OFF"
    print(c(C.G, "[autofix] auto fix on failed run: " + state
                 + " - fix rounds left this session: "
                 + str(fix_budget_left(sess)) + "/" + str(MAX_FIX_ROUNDS)
                 + " (a green run or /autofix on re-arms it)"))


# ------------------------------------------------------- v6.0: the modules
# Nova Voice / Photo / PixelArt / Flow / Knowledge / platforms / per-module
# brain assignment - each import is guarded, each command degrades alone.
def _v6():
    try:
        from nova_modules import ModuleError, assign, flow, knowledge
        from nova_modules import photo, pixelart, voice
        return (assign, voice, photo, pixelart, knowledge, flow, ModuleError)
    except Exception:
        return None


def _v6_fail():
    print("[!] the module layer is not available in this install")


def cmd_voice(sess, arg):
    mods = _v6()
    if not mods:
        return _v6_fail()
    assign, voice, _p, _x, _k, _f, merr = mods
    text = (arg or "").strip()
    if not text:
        print("usage: /voice <text to speak>")
        return
    try:
        r = voice.synthesize(sess.ws, text, assign.resolve(sess.ws, "voice"))
        print("  Nova Voice [%s] -> %s" % (r["engine"], r["path"]))
        if r.get("note"):
            print("      " + r["note"])
    except merr as e:
        print("  [!] " + str(e))


def cmd_stt(sess, arg):
    mods = _v6()
    if not mods:
        return _v6_fail()
    assign, voice, _p, _x, _k, _f, merr = mods
    name = (arg or "").strip()
    if not name:
        print("usage: /stt <audio file in the workspace>  "
              "(needs an OpenAI-compatible STT server)")
        return
    try:
        p = (sess.ws / name).resolve() if hasattr(sess.ws, "__truediv__") else None
        if p is None or not p.is_file():
            print("  [!] audio file not found in the workspace: " + name)
            return
        try:
            p.relative_to(sess.ws.resolve())
        except ValueError:
            print("  [!] path must stay inside the workspace")
            return
        cfg = assign.resolve(sess.ws, "voice")
        if not cfg.get("url"):
            cfg["url"] = "http://127.0.0.1:8080/v1"
        text = voice.transcribe(sess.ws, p.read_bytes(), cfg, filename=p.name)
        print("  Nova Voice STT: " + (text[:2000] or "(empty)"))
    except merr as e:
        print("  [!] " + str(e))
    except OSError as e:
        print("  [!] read error: " + str(e)[:120])


def cmd_photo(sess, arg):
    mods = _v6()
    if not mods:
        return _v6_fail()
    assign, _v, photo, _x, _k, _f, merr = mods
    prompt = (arg or "").strip()
    if not prompt:
        print('usage: /photo "prompt"   (engine from /assign photo, '
              'offline engine always works)')
        return
    try:
        r = photo.generate(sess.ws, prompt, assign.resolve(sess.ws, "photo"))
        print("  Nova Photo [%s] -> %s" % (r["engine"], r["path"]))
        if r.get("note"):
            print("      " + r["note"])
    except merr as e:
        print("  [!] " + str(e))


def cmd_pixel(sess, arg):
    mods = _v6()
    if not mods:
        return _v6_fail()
    _a, _v, _p, pixel, _k, _f, merr = mods
    size, palette, words = 32, None, []
    for tok in (arg or "").split():
        if tok.startswith("--size="):
            try:
                size = int(tok.split("=", 1)[1])
            except ValueError:
                pass
        elif tok.startswith("--palette="):
            palette = tok.split("=", 1)[1]
        else:
            words.append(tok)
    prompt = " ".join(words).strip()
    if not prompt:
        print('usage: /pixel "prompt" [--size=32] [--palette=pico8]')
        return
    try:
        r = pixel.generate(sess.ws, prompt, size=size, palette=palette)
        print("  Nova PixelArt [%s %dx%d @x%d] -> %s  (seed %s)"
              % (r["plan"]["palette"], r["size"], r["size"], r["scale"],
                 r["path"], r["seed"]))
    except merr as e:
        print("  [!] " + str(e))


def cmd_flow(sess, arg):
    mods = _v6()
    if not mods:
        return _v6_fail()
    _a, _v, _p, _x, _k, flow, merr = mods
    parts = (arg or "").strip().split()
    action = parts[0] if parts else "list"
    try:
        if action == "list":
            items = flow.list_flows(sess.ws)
            if not items:
                print("  no saved flows yet - sample: /flow run idea-to-art "
                      "(save it from the web UI)")
                return
            for f in items:
                print("  %-24s %2d steps  %s" % (f["name"], f["steps"],
                                                 ",".join(f["types"])))
        elif action == "run":
            if len(parts) < 2:
                print("usage: /flow run <name> [k=v inputs]")
                return
            f = flow.get(sess.ws, parts[1])
            if f is None:
                print("  [!] flow not found: " + parts[1])
                return
            inputs = {}
            for tok in parts[2:]:
                k, _, v = tok.partition("=")
                if k:
                    inputs[k] = v
            snap = flow.run(sess.ws, f, inputs=inputs)
            for s in snap["steps"]:
                print("   [%s] %-12s %-10s %s" % (
                    {"done": "+", "skip": "~", "failed": "x"}.get(
                        s["status"], "?"),
                    s["id"], s["type"], s["detail"][:80]))
            print("  status: %s%s" % (snap["status"],
                                      (" - " + snap["error"]) if snap["error"] else ""))
        elif action == "show":
            f = flow.get(sess.ws, parts[1] if len(parts) > 1 else "")
            if f is None:
                print("  [!] flow not found")
                return
            print(json.dumps(f, ensure_ascii=False, indent=1))
        elif action == "del":
            print("  deleted" if flow.delete(sess.ws, parts[1] if len(parts) > 1 else "")
                  else "  not found")
        else:
            print("usage: /flow [list|run <name>|show <name>|del <name>]")
    except merr as e:
        print("  [!] " + str(e))


def cmd_knowledge(sess, arg):
    mods = _v6()
    if not mods:
        return _v6_fail()
    _a, _v, _p, _x, knowledge, _f, merr = mods
    parts = (arg or "").strip().split()
    action = parts[0] if parts else "stats"
    try:
        if action == "ingest":
            paths = parts[1:]
            if not paths:
                print("usage: /knowledge ingest <file|dir> [...]")
                return
            r = knowledge.ingest(sess.ws, paths)
            print("  ingested %d file(s), %d new chunks (%d total)"
                  % (r["files"], r["chunks"], r["total_chunks"]))
            if r["skipped"]:
                print("  skipped: " + ", ".join(r["skipped"][:6]))
        elif action == "search":
            q = " ".join(parts[1:])
            hits = knowledge.search(sess.ws, q, k=8)
            if not hits:
                print("  no hits")
                return
            for h in hits:
                print("  %.3f  %s" % (h["score"], h["doc"]))
                print("        " + h["text"][:130].replace("\n", " "))
        elif action == "stats":
            st = knowledge.stats(sess.ws)
            print("  docs: %(docs)d  chunks: %(chunks)d" % st)
        elif action == "reset":
            print("  removed %d index file(s)" % knowledge.reset(sess.ws)["removed"])
        else:
            print("usage: /knowledge [ingest|search|stats|reset] ...")
    except merr as e:
        print("  [!] " + str(e))


def cmd_platforms(sess, arg):
    try:
        import nova_platforms as platforms
    except Exception:
        return _v6_fail()
    parts = (arg or "").strip().split()
    action = parts[0] if parts else "list"
    if action == "list":
        items = platforms.all_platforms(sess.ws)
        for p in items:
            print("  %-12s %s" % (p["name"], p["base"]))
        if not items:
            print("  (none configured - presets: localai shimmy lmstudio vllm llamacpp)")
    elif action == "scan":
        print("  probing platforms ...")
        for r in platforms.scan(sess.ws, timeout=2.0):
            print("  [%s] %-10s %-34s %s" % (
                "ok " if r["ok"] else "-- ", r["name"], r["base"][:34],
                ("%d models" % len(r["models"])) if r["ok"] else r["note"]))
    elif action == "add" and len(parts) >= 3:
        cur = platforms.load_config(sess.ws)
        cur.append({"name": parts[1], "base": parts[2]})
        try:
            print("  saved %d platform(s)" % len(platforms.save_config(sess.ws, cur)))
        except Exception as e:
            print("  [!] " + str(e)[:160])
    elif action == "del" and len(parts) >= 2:
        cur = [p for p in platforms.load_config(sess.ws) if p["name"] != parts[1]]
        platforms.save_config(sess.ws, cur)
        print("  %d platform(s) remain" % len(cur))
    else:
        print("usage: /platforms [list|scan|add <name> <url>|del <name>]")


def cmd_assign(sess, arg):
    mods = _v6()
    if not mods:
        return _v6_fail()
    assign, _v, _p, _x, _k, _f, merr = mods
    parts = (arg or "").strip().split()
    if not parts:
        for row in assign.assignments_view(sess.ws):
            if row["assignable"]:
                print("  %-10s -> %s" % (row["id"],
                                         json.dumps(row["cfg"], ensure_ascii=False)))
        print("usage: /assign <module> <backend> [model=.. url=.. voice=.. path=..]")
        return
    try:
        cfg = {"backend": parts[1]}
        for tok in parts[2:]:
            k, _, v = tok.partition("=")
            if k:
                cfg[k] = v
        saved = assign.save_module(sess.ws, parts[0], cfg)
        print("  assigned %s -> %s" % (parts[0], json.dumps(saved, ensure_ascii=False)))
    except (merr, IndexError) as e:
        print("  [!] " + (str(e) if not isinstance(e, IndexError)
                          else "usage: /assign <module> <backend> [key=value ...]"))


TOOLS = [
    {"cmd": "/workspace", "aliases": ("/cd",), "usage": "/workspace [dir]",
     "fn": cmd_workspace,
     "help": "show or switch the workspace folder (created if missing)"},
    {"cmd": "/ls", "usage": "/ls", "fn": cmd_ls,
     "help": "show the project tree"},
    {"cmd": "/read", "usage": "/read <file>", "fn": cmd_read, "model": True,
     "help": "print a workspace file",
     "mhelp": "prints a workspace file - ask the user for it when you must see one"},
    {"cmd": "/load", "usage": "/load <file>", "fn": cmd_load, "model": True,
     "help": "attach a workspace file to your next message",
     "mhelp": "attaches a file to the user's next message"},
    {"cmd": "/search", "usage": "/search <query>", "fn": cmd_search,
     "needs_ns": True, "model": True,
     "help": "web search, trusted sources first; read a page into context",
     "mhelp": "trusted web search, results into the conversation"},
    {"cmd": "/learn", "usage": "/learn <topic>", "fn": cmd_learn,
     "needs_ns": True, "model": True,
     "help": "deep research: read trusted pages, save to the knowledge base",
     "mhelp": "deep research saved permanently - recommend for recurring topics"},
    {"cmd": "/docs", "usage": "/docs <url>", "fn": cmd_docs,
     "needs_ns": True, "model": True,
     "help": "read one documentation page (by URL) into context",
     "mhelp": "reads one documentation page into context"},
    {"cmd": "/kb", "usage": "/kb [show N|load <file>|clear]", "fn": cmd_kb,
     "needs_ns": True, "model": True,
     "help": "view learned knowledge, import a file, clear the base",
     "mhelp": "shows what the agent has already learned"},
    {"cmd": "/img", "usage": "/img <query> [n]", "fn": cmd_img,
     "needs_ns": True, "model": True,
     "help": "search REAL photos on the internet and download the pick "
             "into assets/images/ (no API keys needed)",
     "mhelp": "searches and downloads a real photo into the workspace - "
              "use for real image needs"},
    {"cmd": "/imgdl", "usage": "/imgdl <url> [name]", "fn": cmd_imgdl,
     "needs_ns": True, "model": True,
     "help": "download any public image URL into assets/images/ "
             "(SSRF-safe, 8 MB cap, magic-byte validated)",
     "mhelp": "downloads one image URL into the workspace"},
    {"cmd": "/fonts", "usage": "/fonts [fa|en|query]", "fn": cmd_fonts,
     "model": True,
     "help": "list the local, offline font library (66 fonts, Persian + "
             "English, SIL OFL) the agent picks from per project",
     "mhelp": "lists available local fonts - the design engine picks a "
              "pairing automatically; a page can override it with "
              '<meta name="nova-fonts" content="heading=...; body=...">'},
    {"cmd": "/model", "aliases": ("/models",), "usage": "/model [name|number]",
     "fn": cmd_model,
     "help": "show every local brain - Ollama models AND .gguf files from "
             "your models folders - or switch by name / row number"},
    {"cmd": "/provider", "usage": "/provider [name] [model]", "fn": cmd_provider,
     "help": "show or switch the AI brain: 30 built-in providers (local + "
             "cloud) plus your own custom ones (/custom)"},
    {"cmd": "/key", "usage": "/key [provider [key|clear]]", "fn": cmd_key,
     "help": "set or remove a provider API key (stored in the workspace "
             "vault); saving a key auto-detects that provider's models"},
    {"cmd": "/services", "usage": "/services [key|clear|test|call] ...",
     "fn": cmd_services, "model": True,
     "help": "سرویس‌های ایرانی با کلید API: پیامک (کاوه‌نگار، ملی‌پیامک، "
             "قاصدک، SMS.ir، فراز)، پرداخت (زرین‌پال، آیدی‌پی، زیبال، "
             "نکست‌پی، پی‌پینگ)، نقشه (نشان)، رمزارز (نوبیتکس، والکس، "
             "بیت‌پین، رمزینکس)، ربات (بله، ایتا، روبیکا)، ویدیو (آپارات)",
     "mhelp": "call Iranian services with API keys: /services lists them; "
              "/services test <sid> runs the free safe test; /services "
              "call <sid> <action> k=v ... executes (e.g. kavenegar "
              "send_sms receptor=09... message=..., zibal sandbox_test, "
              "bale get_me, nobitex market_stats). Keys are set via "
              "/services key <sid> <key> - every call is metered"},
    {"cmd": "/catalog", "usage": "/catalog [provider]", "fn": cmd_catalog,
     "help": "list the auto-detected models of a provider (1 request, "
             "cached a day)"},
    {"cmd": "/brain", "usage": "/brain [section] [provider/model|off]",
     "fn": cmd_brain,
     "help": "give EACH section its own brain: coding | talk | utility | "
             "council - e.g. a cheap fast model for talk, a big one for code"},
    {"cmd": "/think", "usage": "/think [auto|on|off]", "fn": cmd_think,
     "help": "visible reasoning: every brain shows HOW it thinks in a "
             "=== THINK === ... === END === block before its answer "
             "(auto = forced only for models without native reasoning; "
             "on = every brain; off = no forced block)"},
    {"cmd": "/custom", "usage": "/custom [add <name> <base-url> [model] [kind]] | del <name>",
     "fn": cmd_custom,
     "help": "your own providers: any OpenAI-compatible / Anthropic / "
             "Gemini endpoint (LM Studio, vLLM, relays...)"},
    {"cmd": "/saver", "usage": "/saver [cache on|off | budget <usd> | tokens <n> | clear]",
     "fn": cmd_saver,
     "help": "request economy: show what was SAVED (requests/tokens/credits), "
             "toggle the response cache, set daily budgets"},
    {"cmd": "/disk", "usage": "/disk", "fn": cmd_disk,
     "help": "RAM vs model-size advisor: fit check for every installed model, "
             "disk-mode speed estimate, swap/pagefile recipes"},
    {"cmd": "/mode", "usage": "/mode [name]", "fn": cmd_mode,
     "help": "generation mode: code | balanced | creative"},
    {"cmd": "/run", "usage": "/run <cmd>", "fn": run_command, "model": True,
     "help": "run a shell command inside the workspace (empty = repeat last)",
     "mhelp": "runs a shell command in the workspace"},
    {"cmd": "/fix", "usage": "/fix", "fn": _cmd_fix, "model": True,
     "help": "send the last failed command output to Nova Code for repair",
     "mhelp": "replays the last error to you for repair"},
    {"cmd": "/autofix", "usage": "/autofix [on|off]", "fn": cmd_autofix,
     "help": "show or toggle the automatic fix rounds after a failed Run; "
             "'on' re-arms the fix budget (v8.11)"},
    {"cmd": "/verify", "usage": "/verify [cmd]", "fn": _cmd_verify, "model": True,
     "help": "AUTO verify loop: run -> auto-fix -> re-run until exit code 0",
     "mhelp": "run - auto-fix - re-run loop until the command exits 0 - recommend it after fixes"},
    {"cmd": "/check", "usage": "/check", "fn": cmd_check, "model": True,
     "help": "static analysis: syntax-check every .py / .js file, auto-offer fixes",
     "mhelp": "syntax-checks all .py/.js files - recommend it after writing files"},
    {"cmd": "/serve", "usage": "/serve [port]", "fn": cmd_serve, "model": True,
     "help": "preview websites: serve the workspace (default port 8000)",
     "mhelp": "localhost website preview - for servers recommend /serve, never /run"},
    {"cmd": "/auto", "usage": "/auto [on|off|yolo]", "fn": cmd_auto,
     "help": "autonomous build -> run -> fix loop (bare command toggles)"},
    {"cmd": "/init", "usage": "/init", "fn": cmd_init,
     "help": "create NOVA.md project notes (auto-injected as project law)"},
    {"cmd": "/compact", "usage": "/compact", "fn": cmd_compact,
     "help": "summarize the conversation into one message to free context"},
    {"cmd": "/ctxset", "usage":
     "/ctxset [local <tok> | cloud <tok> | auto on|off | threshold <x> |"
     " keep <n> | reset]", "fn": cmd_ctxset,
     "help": "v8.3 context engine: per-backend window sizes (local vs"
             " cloud, overrides the model defaults) + smart compression"},
    {"cmd": "/guardian", "usage":
     "/guardian [on|off | model on|off | web on|off | reject on|off |"
     " langs | audit | reset]", "fn": cmd_guardian,
     "help": "v8.4 code guardian: the supervisor agent + the language"
             " fleet that keeps broken code off the disk (audit sweeps"
             " the whole workspace)"},
    {"cmd": "/probe", "usage":
     "/probe [on|off | wiring on|off | deep on|off | smoke on|off |"
     " browser on|off | review on|off | reject on|off | rejectdeep"
     " on|off | reset]", "fn": cmd_probe,
     "help": "v8.5/v8.6 bug hunter: catches what syntax cannot - dead"
             " buttons/ids, missing files, crashed entry scripts,"
             " headless-browser console errors, missing work vs the"
             " request, plus the v8.6 deep sweep: a bug can be a"
             " simple function, extra code or missing code"},
    {"cmd": "/vision", "usage":
     "/vision [approve on|off | strict on|off | check | reset]",
     "fn": cmd_vision,
     "help": "v8.6 vision layer: 100% automatic detection of whether"
             " the local model can see photos, plus the approval gate"
             " - the local AI must approve every internet photo"
             " (search fill, /img, /imgdl)"},
    {"cmd": "/retry", "usage": "/retry", "fn": cmd_retry,
     "help": "discard the last answer and regenerate it"},
    {"cmd": "/review", "usage": "/review <file>", "fn": cmd_review,
     "help": "strict code review of one file by the model"},
    {"cmd": "/changes", "usage": "/changes [clear]", "fn": cmd_changes,
     "help": "list files created/modified in this session"},
    {"cmd": "/timeout", "usage": "/timeout <sec>", "fn": cmd_timeout,
     "help": "change the /run timeout (5-3600 s, default 120)"},
    {"cmd": "/undo", "usage": "/undo [n]", "fn": cmd_undo, "model": True,
     "help": "restore previous file versions - walks back n apply batches",
     "mhelp": "restores previous versions of changed files"},
    {"cmd": "/snapshot", "usage": "/snapshot [label]", "fn": cmd_snapshot,
     "help": "manual full-workspace checkpoint before big changes"},
    {"cmd": "/snapshots", "usage": "/snapshots", "fn": cmd_snapshots,
     "help": "list undo units and manual checkpoints"},
    {"cmd": "/restore", "usage": "/restore <label|id>", "fn": cmd_restore,
     "help": "bring the workspace back to a manual checkpoint"},
    {"cmd": "/map", "usage": "/map", "fn": cmd_map,
     "help": "show the project style map the model sees (signatures per file)"},
    {"cmd": "/explain", "usage": "/explain [on|off]", "fn": cmd_explain, "model": True,
     "help": "analysis-only mode: no file writes, no shell commands",
     "mhelp": "analysis-only mode is active - recommend it for code reviews"},
    {"cmd": "/policy", "usage": "/policy [allow|deny|default|reset]", "fn": cmd_policy,
     "help": "per-command permission policy for shell runs (deny always wins)"},
    {"cmd": "/secure", "usage": "/secure [on|off|status]", "fn": cmd_secure,
     "help": "security posture: block destructive commands, audit every run, harden the web face"},
    # ---- v6.8: edit harness / autonomy / quality / security / UX ----------
    {"cmd": "/doctor", "usage": "/doctor", "fn": cmd_doctor,
     "help": "first-run setup wizard: python, workspace, Ollama, models, "
             "hardware, keys, sandbox, encryption - with copy-paste fixes"},
    {"cmd": "/hw", "usage": "/hw", "fn": cmd_hw,
     "help": "hardware check: RAM/GPU detected + the model tier/quant that "
             "fits + speculative-decoding recipe for llama.cpp"},
    {"cmd": "/timeline", "usage": "/timeline [n|show <id>]", "fn": cmd_timeline,
     "help": "visual change history (every apply is a unit): when, what, "
             "which files - /undo reverts any of them"},
    {"cmd": "/explore", "usage": "/explore [2-4] <request>", "fn": cmd_explore,
     "model": True,
     "help": "LOCAL ONLY: generate 2-4 candidate answers in parallel, score "
             "them and apply the best (zero extra cost on a local brain)",
     "mhelp": "generates several candidate solutions in parallel and keeps "
              "the best - recommend it for important or hard tasks"},
    {"cmd": "/rag", "usage": "/rag <query>|build|status", "fn": cmd_rag,
     "model": True,
     "help": "semantic codebase search with real embeddings - finds the "
             "right code even with zero shared words", 
     "mhelp": "searches this project's code by meaning - use it to locate "
              "where a feature lives before editing"},
    {"cmd": "/style", "usage": "/style [show|rebuild|clear]", "fn": cmd_style,
     "help": "show/rebuild the observed coding-style profile (indent, "
             "quotes, naming) that new code is matched against"},
    {"cmd": "/route", "usage": "/route [fast <model>|strong <model>|off]",
     "fn": cmd_route,
     "help": "EXPLICIT cloud model map by task difficulty (no silent "
             "downgrades) - local routing is automatic and free"},
    {"cmd": "/gitlog", "usage": "/gitlog [n]", "fn": cmd_gitlog,
     "model": True,
     "help": "commit-per-edit history: every applied file is its own commit "
             "(your repo, or .nova/history.git when there is none)",
     "mhelp": "shows the per-edit commit history of this project"},
    {"cmd": "/graph", "usage": "/graph [--dot FILE|--mermaid FILE]", "fn": cmd_graph,
     "help": "file dependency graph: import edges, circular imports, "
             "orphans, unresolved imports; exports dot/mermaid"},
    {"cmd": "/symbols", "usage": "/symbols <file>", "fn": cmd_symbols,
     "help": "syntax-aware skeleton of a file: classes/functions with real "
             "signatures + line numbers (AST for .py)"},
    {"cmd": "/patch", "usage": "/patch <file.patch|last>", "fn": cmd_patch,
     "help": "apply a real unified diff (git style) with validation, "
             "backup + snapshot; 'last' uses the model's last diff block"},
    {"cmd": "/writedocs", "usage": "/writedocs", "fn": cmd_writedocs,
     "help": "generate DOCS.md from docstrings + signatures (zero tokens)"},
    {"cmd": "/coverage", "usage": "/coverage", "fn": cmd_coverage,
     "help": "run the project's tests under coverage.py and show the "
             "percentage (pip install coverage for the full report)"},
    {"cmd": "/selftest", "usage": "/selftest [rounds]", "fn": cmd_selftest,
     "help": "self-test loop: model writes tests for its changes -> tests "
             "run -> failures fixed -> repeat until green (max 4 rounds)"},
    {"cmd": "/agent", "usage": "/agent <goal>", "fn": cmd_agent, "model": True,
     "help": "split a goal into independent sub-tasks and run them on "
             "PARALLEL local sub-agents (drafts only - nothing applied)",
     "mhelp": "fans a big goal out to parallel local helpers and merges their drafts"},
    {"cmd": "/bench", "usage": "/bench [model]", "fn": cmd_bench,
     "help": "benchmark installed local models (speed + protocol "
             "compliance) and rank them per section"},
    {"cmd": "/lock", "usage": "/lock <passphrase>|off|status", "fn": cmd_lock,
     "help": "encrypt the conversation memory at rest (.nova/memory.json.enc); "
             "same passphrase needed to restore it"},
    {"cmd": "/sandbox", "usage": "/sandbox [on|off|status|files|engine|image <n>|mem <m>|cpus <n>]",
     "fn": cmd_sandbox,
     "help": "run /run commands inside a local container (docker/podman/"
             "firejail/bwrap): no network, RAM/CPU capped; 'files' shows "
             "the agent file-sandbox state"},
    {"cmd": "/limit", "usage": "/limit [cpu <sec>] [ram <MB>] [off|status]",
     "fn": cmd_limit,
     "help": "CPU/RAM ceilings for every /run command (OS-enforced, not "
             "just a wall timeout)"},
    {"cmd": "/log", "usage": "/log [tail|summary|clear]", "fn": cmd_log,
     "help": "show swallowed warnings that used to vanish (NOVA_DEBUG=1 for live stderr)"},
    {"cmd": "/blackbox", "usage": "/blackbox [n] [filter]", "fn": cmd_blackbox,
     "help": "the agent's black box: brain picks, applies, run verdicts, "
             "recovery + sandbox decisions (survives restarts)"},
    {"cmd": "/plugin", "usage": "/plugin [list|run <plugin.tool> k=v ...|reload|key NAME val]",
     "fn": cmd_plugin, "model": True,
     "help": "user-defined side tools loaded from .nova/plugins/ (JSON)",
     "mhelp": "lists the user's plugin tools - prefer them for their "
              "domain tasks (weather, custom APIs, ...)"},
    {"cmd": "/novaignore", "usage": "/novaignore [check <path>]", "fn": cmd_novaignore,
     "help": "show the .novaignore view-exclusion list (gitignore-style)"},
    {"cmd": "/todo", "usage": "/todo [add|done|del|clear]", "fn": cmd_todo, "model": True,
     "help": "live task checklist (auto-built from the model's === PLAN === blocks)",
     "mhelp": "shows the current task plan - keep the === PLAN === block updated"},
    {"cmd": "/skill", "usage": "/skill [list|save|show|del]", "fn": cmd_skill, "model": True,
     "help": "learned approaches: /skill save <name> <instructions>",
     "mhelp": "lists learned skills worth reusing in this project"},
    {"cmd": "/autotest", "usage": "/autotest [on|off]", "fn": cmd_autotest,
     "help": "run detected tests automatically after every apply"},
    {"cmd": "/cost", "usage": "/cost [reset]", "fn": cmd_cost,
     "help": "token + USD ledger per model (cloud brains; ollama is free)"},
    {"cmd": "/estimate", "usage": "/estimate <request>", "fn": cmd_estimate,
     "help": "cost + duration estimate for a request BEFORE sending it"},
    {"cmd": "/bg", "usage": "/bg <cmd> | list | log <id> | kill <id>", "fn": cmd_bg,
     "help": "run a long command in the background, get notified on finish"},
    {"cmd": "/council", "usage": "/council <q> | with <provider[:model]>", "fn": cmd_council,
     "help": "two brains answer the same question + optional judge/merge round"},
    {"cmd": "/pr", "usage": "/pr [base]", "fn": cmd_pr,
     "help": "generate a PR title + description from this session's commits"},
    {"cmd": "/memory", "usage": "/memory [show|clear|on|off]", "fn": cmd_memory,
     "help": "conversation memory across terminal runs"},
    {"cmd": "/profile", "usage": "/profile [show|set|clear]", "fn": cmd_profile,
     "help": "per-project defaults (provider/model/mode/timeout persist)"},
    {"cmd": "/rescan", "usage": "/rescan", "fn": cmd_rescan,
     "help": "refresh the project file map (and .novaignore rules)"},
    {"cmd": "/clear", "usage": "/clear", "fn": cmd_clear,
     "help": "clear conversation context (recommended between tasks)"},
    {"cmd": "/voice", "usage": "/voice <text>", "fn": cmd_voice,
     "help": "Nova Voice: turn text into speech (engine from /assign voice)"},
    {"cmd": "/stt", "usage": "/stt <file>", "fn": cmd_stt,
     "help": "Nova Voice: transcribe a workspace audio file (STT server needed)"},
    {"cmd": "/photo", "usage": "/photo <prompt>", "fn": cmd_photo,
     "help": "Nova Photo: generate an image (offline engine or A1111/ComfyUI)"},
    {"cmd": "/pixel", "usage": "/pixel <prompt> [--size=32 --palette=pico8]",
     "fn": cmd_pixel,
     "help": "Nova PixelArt: fully-offline retro pixel art, seed-deterministic"},
    {"cmd": "/flow", "usage": "/flow [list|run|show|del]", "fn": cmd_flow,
     "help": "Nova Flow: run the multi-module workflows (the integration hub)"},
    {"cmd": "/knowledge", "usage": "/knowledge [ingest|search|stats|reset]",
     "fn": cmd_knowledge,
     "help": "Nova Knowledge: local document brain with TF-IDF search"},
    {"cmd": "/platforms", "usage": "/platforms [list|scan|add|del]",
     "fn": cmd_platforms,
     "help": "OpenAI-compatible platforms: LocalAI/Shimmy/LM Studio/vLLM/llama.cpp"},
    {"cmd": "/assign", "usage": "/assign [<module> <backend> key=value ...]",
     "fn": cmd_assign,
     "help": "give ONE module its OWN local or cloud brain"},
    {"cmd": "/status", "usage": "/status", "fn": cmd_status,
     "help": "show session info"},
    {"cmd": "/export", "usage": "/export", "fn": cmd_export,
     "help": "save the whole conversation to a markdown file"},
    {"cmd": "/help", "usage": "/help", "fn": cmd_help,
     "help": "show this help"},
    {"cmd": "/quit", "aliases": ("/exit", "/bye"), "usage": "/quit",
     "fn": cmd_quit, "help": "exit Nova Assistant"},
    # ------------------------------------------------- v7.13: nova intel
    {"cmd": "/intel", "usage": "/intel [rescan]", "fn": cmd_intel,
     "help": "the integrated project profile (languages, entries, "
             "symbols, imports)"},
    {"cmd": "/tasks", "usage": "/tasks [add|done|dep|impact|...]",
     "fn": cmd_tasks, "model": True,
     "help": "dependency-aware task graph (real DAG, ready/blocked)",
     "mhelp": "the real task plan with dependencies - add tasks here, "
              "mark done, ask 'impact' to see what waits on a task"},
    {"cmd": "/mem", "usage": "/mem remember|recall|forget ...",
     "fn": cmd_mem, "model": True,
     "help": "semantic project memory - recall facts/decisions by "
             "meaning, not just history",
     "mhelp": "remember durable facts/decisions and recall them later "
              "by meaning ('/mem recall login bug')"},
    {"cmd": "/ctx", "usage": "/ctx <query>", "fn": cmd_ctx, "model": True,
     "help": "auto-assembled context for one query (tasks + project + "
             "memory + KB, budgeted)",
     "mhelp": "use before big work: pulls the most relevant plan, "
              "project and memory context for the query"},
    {"cmd": "/impact", "usage": "/impact <file...>", "fn": cmd_impact,
     "model": True,
     "help": "blast radius BEFORE a change: importers, symbols, tests",
     "mhelp": "run BEFORE changing shared files - shows which files "
              "import the target and which tests cover it"},
    {"cmd": "/regress", "usage": "/regress [baseline|check]",
     "fn": cmd_regress,
     "help": "honest before/after test comparison (regression "
             "detection)"},
    {"cmd": "/gentests", "usage": "/gentests <file>", "fn": cmd_gentests,
     "model": True,
     "help": "generate runnable test skeletons for a changed/new file",
     "mhelp": "after writing a new module, generate test skeletons - "
              "existence pins run green, smoke bodies wait to be filled"},
    {"cmd": "/critic", "usage": "/critic", "fn": cmd_critic,
     "help": "staged self-review of this session's changes (score + "
             "verdict)"},
    {"cmd": "/workspaces", "usage": "/workspaces [add|use|rm]",
     "fn": cmd_workspaces,
     "help": "multi-project registry - each project remembered "
             "independently"},
    {"cmd": "/loop", "usage": "/loop <goal>", "fn": cmd_loop,
     "model": True,
     "help": "the autonomous instrumented loop: build -> run -> fix -> "
             "verify with an honest finish",
     "mhelp": "recommend for clear build goals: Nova plans, writes, "
              "runs, fixes and verifies in rounds and reports with "
              "evidence"},
]


# ------------------------------------------------- web Guide tab (v6.9)
# The browser's "راهنما" tab is generated from the SAME TOOLS registry as
# /help, so a new/renamed command appears there automatically. Persian
# one-liners (HELP_FA) keep the guide human for the app's actual audience;
# the English TOOLS "help" is the fallback for anything unmapped.
HELP_GROUPS = [
    ("start", "شروع و مسیریابی",
     ["/help", "/ls", "/read", "/load", "/workspace", "/map", "/changes",
      "/rescan", "/init", "/clear", "/export", "/status"]),
    ("brain", "مدل و مغز",
     ["/model", "/provider", "/key", "/catalog", "/brain", "/think", "/custom",
      "/saver", "/assign", "/platforms", "/disk", "/hw", "/bench", "/mode"]),
    ("build", "ساخت، اجرا و رفع اشکال",
     ["/run", "/serve", "/check", "/fix", "/verify", "/auto", "/timeout",
      "/undo", "/snapshot", "/snapshots", "/restore", "/timeline", "/patch",
      "/gitlog"]),
    ("quality", "کیفیت و بازبینی",
     ["/review", "/symbols", "/graph", "/coverage", "/writedocs", "/selftest",
      "/autotest", "/agent", "/council", "/explore", "/rag", "/style",
      "/route"]),
    ("security", "امنیت و سیاست",
     ["/policy", "/secure", "/sandbox", "/limit", "/lock", "/log",
      "/novaignore"]),
    ("intel", "هوش پروژه (وظایف، حافظه، تاثیر، حلقه عامل)",
     ["/intel", "/tasks", "/mem", "/ctx", "/impact", "/regress",
      "/gentests", "/critic", "/workspaces", "/loop"]),
    ("knowledge", "دانش و وب",
     ["/search", "/learn", "/docs", "/kb", "/img", "/imgdl", "/fonts", "/knowledge"]),
    ("modules", "ماژول‌ها (صدا / تصویر / پیکسل / جریان / دانش)",
     ["/voice", "/stt", "/photo", "/pixel", "/flow"]),
    ("session", "نشست و حافظه",
     ["/explain", "/todo", "/skill", "/cost", "/estimate", "/bg", "/pr",
      "/memory", "/profile", "/compact", "/retry", "/doctor", "/quit"]),
]

HELP_FA = {
    "/help": "فهرست همه دستورها",
    "/ls": "نمایش درخت پروژه",
    "/read": "چاپ محتوای یک فایل ورک‌اسپیس",
    "/load": "پیوست کردن فایل به پیام بعدی شما",
    "/workspace": "نمایش یا تعویض پوشه پروژه",
    "/map": "نقشه پروژه‌ای که مدل می‌بیند",
    "/changes": "فایل‌های ساخته/ویرایش‌شده این نشست",
    "/rescan": "بروزرسانی نقشه فایل‌ها",
    "/init": "ساخت NOVA.md — قوانین پروژه (خودکار تزریق می‌شود)",
    "/clear": "پاک کردن حافظه گفتگو (بین دو کار توصیه می‌شود)",
    "/export": "خروجی مارک‌داون کل گفتگو",
    "/status": "وضعیت نشست",
    "/model": "فهرست یا تعویض مدل محلی (Ollama + فایل‌های gguf)",
    "/provider": "نمایش یا تعویض مغز: ۳۰ پروایدر داخلی + دلخواه",
    "/key": "ذخیره کلید API (مدل‌ها خودکار شناسایی می‌شوند)",
    "/catalog": "مدل‌های شناسایی‌شده یک پروایدر (کش یک‌روزه)",
    "/brain": "مغز جداگانه هر بخش: کدنویسی، گفتگو، ابزار، شورا",
    "/think": "تفکر قابل مشاهده: هر مغز قبل از پاسخ در بلوک «=== THINK ===» "
              "می‌نویسد چه و چطور فکر می‌کند (auto/on/off)",
    "/custom": "افزودن پروایدر دلخواه (هر سرور سازگار با OpenAI/Anthropic/Gemini)",
    "/saver": "اقتصاد درخواست: کش پاسخ، بودجه روزانه، آمار صرفه‌جویی",
    "/assign": "مغز اختصاصی برای یک ماژول",
    "/platforms": "پلتفرم‌های لوکال: LM Studio / vLLM / LocalAI و...",
    "/disk": "مشاور RAM و دیسک برای انتخاب مدل مناسب",
    "/hw": "سخت‌افزار شما + مدل پیشنهادی + دستور llama.cpp",
    "/bench": "بنچمارک مدل‌های محلی (سرعت + رعایت پروتکل)",
    "/mode": "حالت تولید: code | balanced | creative",
    "/run": "اجرای دستور در ورک‌اسپیس (خالی = تکرار دستور قبلی)",
    "/serve": "پیش‌نمایش سایت روی localhost (پیش‌فرض پورت 8000)",
    "/check": "آنالیز استاتیک همه فایل‌های py/js",
    "/fix": "ارسال آخرین خطا به مدل برای رفع",
    "/verify": "حلقه خودکار: اجرا ← رفع ← اجرا تا خروجی کد ۰",
    "/auto": "حلقه خودساز: ساخت ← اجرا ← رفع (yolo = بدون تایید)",
    "/timeout": "تغییر مهلای اجرا (۵ تا ۳۶۰۰ ثانیه)",
    "/undo": "برگرداندن نسخه‌های قبلی فایل‌ها (n واحد به عقب)",
    "/snapshot": "چک‌پوینت دستی کل ورک‌اسپیس قبل از کارهای بزرگ",
    "/snapshots": "فهرست واحدهای undo و چک‌پوینت‌ها",
    "/restore": "بازگرداندن ورک‌اسپیس به یک چک‌پوینت",
    "/timeline": "خط زمانی تغییرات (هر اعمال = یک واحد)",
    "/explore": "تولید ۲ تا ۴ پاسخ موازی و انتخاب بهترین (فقط مدل لوکال)",
    "/rag": "جستجوی معنایی کدبیس با embedding واقعی", 
    "/style": "نمایش/بازسازی پروفایل سبک کدنویسی کاربر", 
    "/route": "نقشه صریح مدل ابری بر اساس سختی کار (بدون تنزل پنهان)",
    "/gitlog": "تاریخچه commit-per-edit (هر ویرایش یک کامیت)",
    "/patch": "اعمال یک فایل patch/دی‌ف به ورک‌اسپیس",
    "/review": "بازبینی سخت‌گیرانه یک فایل توسط مدل",
    "/symbols": "اسکلت AST فایل: کلاس‌ها و توابع با شماره خط",
    "/graph": "گراف وابستگی فایل‌ها + حلقه‌های واردات",
    "/coverage": "پوشش تست برای فایل‌های تغییر کرده",
    "/writedocs": "ساخت docstring و مستندات پروژه",
    "/selftest": "حلقه خودتستی: مدل تست می‌نویسد، اجرا می‌شود، رفع می‌کند",
    "/autotest": "اجرای خودکار تست‌ها بعد از هر اعمال",
    "/agent": "ساب‌ایجنت‌های موازی: هدف به زیرکارها تقسیم و موازی اجرا می‌شود",
    "/council": "دو مغز به یک سوال جواب می‌دهند + قاضی/ادغام",
    "/policy": "سیاست مجوز دستورهای شل (deny همیشه می‌برد)",
    "/secure": "حالت امن: مسدودسازی دستور مخرب، حسابرسی، توکن وب",
    "/sandbox": "اجرای دستورها در کانتینر بدون شبکه (docker/podman/...)",
    "/limit": "سقف CPU/RAM برای دستورهای اجراشده",
    "/lock": "رمزنگاری حافظه گفتگو با passphrase",
    "/log": "هشدارهای بلعیده‌شده (NOVA_DEBUG=1 برای زنده)",
    "/novaignore": "فایل‌های خارج از دید مدل (سبک gitignore)",
    "/search": "جستجوی وب از منابع معتبر",
    "/learn": "تحقیق عمیق و ذخیره دائمی در دانش",
    "/docs": "خواندن یک صفحه مستندات با URL",
    "/kb": "مشاهده/وارد کردن/پاک کردن دانش آموخته‌شده",
    "/img": "جستجوی عکس واقعی در اینترنت و دانلود آن در assets/images (بدون کلید API؛ تأیید هوش مصنوعی لوکال)",
    "/imgdl": "دانلود یک URL عکس در assets/images (امن، سقف ۸ مگابایت؛ تأیید هوش مصنوعی لوکال)",
    "/vision": "لایه بینایی: تشخیص خودکار قابلیت دیدن عکس مدل لوکال + گیت تأیید عکس اینترنتی توسط هوش مصنوعی لوکال",
    "/fonts": "فهرست کتابخانه فونت محلی (۶۶ فونت فارسی/انگلیسی، آفلاین) که ایجنت برای هر پروژه انتخاب می‌کند",
    "/knowledge": "مغز سند محلی پروژه (جستجوی TF-IDF)",
    "/explain": "حالت فقط‌تحلیل: بدون نوشتن فایل و اجرا",
    "/todo": "چک‌لیست زنده کار (از PLAN مدل ساخته می‌شود)",
    "/skill": "مهارت‌های آموخته‌شده برای استفاده دوباره",
    "/cost": "دفتر هزینه توکن و دلار (مغز ابری)",
    "/estimate": "برآورد هزینه و زمان قبل از ارسال درخواست",
    "/bg": "اجرای دستور طولانی در پس‌زمینه + اعلان پایان",
    "/pr": "تولید عنوان و توضیح PR از کامیت‌های این نشست",
    "/memory": "حافظه گفتگو بین اجراهای ترمینال",
    "/profile": "پیش‌فرض‌های هر پروژه (provider/model/mode/timeout)",
    "/compact": "خلاصه کردن گفتگو برای آزادسازی کانتکست",
    "/retry": "رد کردن آخرین جواب و تولید دوباره",
    "/doctor": "راه‌انداز اولیه: پایتون، Ollama، مدل، سخت‌افزار، کلید...",
    "/quit": "خروج از Nova Assistant",
    "/voice": "Nova Voice: تبدیل متن به گفتار (مغز از /assign voice)",
    "/stt": "Nova Voice: رونویسی یک فایل صوتی ورک‌اسپیس",
    "/photo": "Nova Photo: تولید تصویر (آفلاین یا A1111/ComfyUI)",
    "/pixel": "Nova PixelArt: پیکسل‌آرت رترو کاملاً آفلاین و seed-قطعی",
    "/flow": "Nova Flow: اجرای جریان‌های چندماژوله (هاب یکپارچه‌سازی)",
    "/intel": "پروفایل یکپارچه پروژه: زبان‌ها، فریم‌ورک‌ها، نمادها، گراف ایمپورت",
    "/tasks": "گراف وظایف واقعی با وابستگی (آماده/مسدود، ترتیب توپولوژیک)",
    "/mem": "حافظه معنایی پروژه: یادسپاری و بازیابی با معنا (نه فقط تاریخچه)",
    "/ctx": "انتخاب خودکار دقیق‌ترین کانتکست برای یک پرسش (بودجه‌دار)",
    "/impact": "تحلیل تاثیر قبل از تغییر: چه فایل‌هایی به این فایل وابسته‌اند",
    "/regress": "تشخیص پسرفت: مقایسه صادقانه وضعیت تست‌ها قبل و بعد از تغییر",
    "/gentests": "تولید خودکار اسکلت تست قابل اجرا برای فایل تغییرکرده/جدید",
    "/critic": "بازبینی مرحله‌ای تغییرات این نشست (امتیاز + حکم ship/fix/rollback)",
    "/workspaces": "مدیریت چند پروژه مستقل (ثبت، جابجایی، حذف از فهرست)",
    "/loop": "حلقه عامل خودمختار: ساخت ← اجرا ← رفع ← تایید با پایان صادقانه",
}


def web_help_payload():
    """Payload for GET /api/help - every TOOLS entry appears EXACTLY once,
    grouped; anything not listed in HELP_GROUPS lands in the "more" group.
    Generated at request time, so it can never drift from the registry."""
    by_cmd = {}
    for t in TOOLS:
        by_cmd[t["cmd"]] = t
        for a in t.get("aliases", ()):
            by_cmd.setdefault(a, t)
    groups, listed = [], set()

    def _item(t):
        return {"cmd": t["cmd"], "usage": t["usage"],
                "help": HELP_FA.get(t["cmd"]) or t["help"],
                "aliases": list(t.get("aliases", ()))}

    for gid, title, cmds in HELP_GROUPS:
        items = []
        for name in cmds:
            t = by_cmd.get(name)
            if t is None or id(t) in listed or not tool_available(t):
                continue
            listed.add(id(t))
            items.append(_item(t))
        if items:
            groups.append({"id": gid, "title": title, "items": items})
    rest = [t for t in TOOLS if id(t) not in listed and tool_available(t)]
    if rest:
        groups.append({"id": "more", "title": "سایر دستورها",
                       "items": [_item(t) for t in rest]})
    return {"groups": groups}


TOOL_INDEX = {}
for _t in TOOLS:
    for _name in (_t["cmd"],) + tuple(_t.get("aliases", ())):
        if _name in TOOL_INDEX:  # fail fast on a typo at import, not at runtime
            raise RuntimeError("duplicate tool name in TOOLS: " + _name)
        TOOL_INDEX[_name] = _t


def tool_available(tool):
    """False when the tool needs nova_search.py and it is missing."""
    return not (tool.get("needs_ns") and ns is None)


def find_tool(cmd):
    return TOOL_INDEX.get(cmd.lower())


def dispatch(sess, line):
    if not line.startswith("/"):
        # v8.11: /auto on now actually routes the next plain message
        # into the autonomous loop - the flag used to be written by
        # cmd_auto and read NOWHERE, so the documented "every task runs
        # up to N build -> run -> fix rounds automatically" never
        # happened (the help lied; only /loop reached the engine).
        if getattr(sess, "auto", False):
            auto_build(sess, line)
        else:
            chat_turn(sess, line)
        return
    parts = line.split(maxsplit=1)
    cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
    tool = find_tool(cmd)
    if tool is None:
        print(c(C.Y, f"[!] unknown command {cmd} - try /help"))
        return
    if not tool_available(tool):
        print(c(C.Y, "[!] web tools are disabled - nova_search.py is missing next to nova.py."))
        print(c(C.D, "    Everything else keeps working fully offline."))
        return
    tool["fn"](sess, arg)

# --------------------------------------------------------------- cli
# ONE program, TWO faces: the flag is the only difference.
USAGE = """\
Nova Assistant - one program, two faces (the Nova Code coding module inside)

  python3 nova.py [workspace]           terminal face (default)
  python3 nova.py --web                 web face - the same agent in the
                                        browser (files, tools, streaming)

Options:
  --web                 start the web face (serves http://localhost:8765)
  --host HOST           bind address for --web (default 127.0.0.1 - local only;
                        any other host auto-requires a printed access token)
  --port PORT           port for --web (default 8765)
  --workspace DIR       workspace folder (or pass it as a plain argument)
  --provider NAME       brain for this run: ollama | openai | openrouter |
                        groq | deepseek | anthropic | gemini | custom
  --list-models         print every usable local brain - the Ollama library
                        AND .gguf model files from your models folders -
                        then exit (same tables as /model inside)
  -h, --help            show this help
  -V, --version         show the version

Two ways to run a LOCAL model (both selectable via /model, or NOVA_MODEL):
  1. pull it into Ollama:              ollama pull qwen2.5-coder:3b
  2. drop a .gguf file you downloaded into a models folder:
       NOVA_MODELS_DIR=/path/to/folder   (default: ~/.nova/models,
                                          per-project: <workspace>/.nova/models)
     Nova imports the file into Ollama once (or runs llama.cpp's
     llama-server when Ollama is not available) - automatically.
Switch the brain while running:   /provider <name> [model]
Switch the model while running:   /model <name>   or by row number: /model 2
Cloud providers only need their key, e.g.:  export OPENAI_API_KEY=...
"""


def parse_args(argv):
    """Friendly manual arg parsing (zero deps). Returns an options dict.
    Raises ValueError with a short message on bad input (main turns that
    into a clean usage error) - no hidden exits, easy to test."""
    opts = {"workspace": "", "web": False, "host": "127.0.0.1", "port": 8765,
            "provider": "", "list_models": False, "help": False, "version": False}
    positional = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            opts["help"] = True
        elif a in ("-V", "--version"):
            opts["version"] = True
        elif a == "--web":
            opts["web"] = True
        elif a == "--host":
            i += 1
            if i >= len(argv) or not argv[i].strip():
                raise ValueError("--host needs a value")
            opts["host"] = argv[i].strip()
        elif a == "--port":
            i += 1
            if i >= len(argv):
                raise ValueError("--port needs a value")
            if not argv[i].isdigit():
                raise ValueError("--port must be a number (got: " + argv[i] + ")")
            p = int(argv[i])
            if not (1 <= p <= 65535):
                raise ValueError("--port must be 1-65535")
            opts["port"] = p
        elif a == "--workspace":
            i += 1
            if i >= len(argv):
                raise ValueError("--workspace needs a directory")
            opts["workspace"] = argv[i]
        elif a == "--provider":
            i += 1
            if i >= len(argv):
                raise ValueError("--provider needs a name (see --help)")
            opts["provider"] = argv[i]
        elif a == "--list-models":
            opts["list_models"] = True
        elif a.startswith("--"):
            raise ValueError("unknown option: " + a + "  (see --help)")
        elif a.startswith("-") and a != "-":
            # v6.9: a stray single-dash token used to become the WORKSPACE -
            # 'nova.py -x' silently created a folder named '-x' and started
            # there. Unknown single-dash options are refused like -- ones.
            raise ValueError("unknown option: " + a + "  (see --help)")
        else:
            positional.append(a)
        i += 1
    if positional:
        if opts["workspace"]:
            raise ValueError("workspace given twice (positional + --workspace)")
        opts["workspace"] = positional[0]
        if len(positional) > 1:
            raise ValueError("too many arguments: " + " ".join(positional[1:])
                             + "  (see --help)")
    return opts


def main():
    setup_terminal()
    try:
        args = parse_args(sys.argv[1:])
    except ValueError as e:
        print(c(C.R, "[!] " + str(e)))
        print(c(C.D, "  (usage: python3 nova.py --help)"))
        sys.exit(2)
    if args["help"]:
        print(USAGE)
        return
    if args["version"]:
        print(AGENT_NAME + " v" + VERSION
              + " - one program, two faces (terminal + web)"
              + " | " + CODING_BRAND + " coding module")
        return
    if lmodels is not None:
        try:
            lmodels.prepare_local_dirs()   # visible local/{code,voice,photo}
        except Exception:
            pass                           # read-only app dir must never bite
    if args["list_models"]:
        # Shell-friendly model catalogue: BOTH local sources (Ollama
        # library + model files), then exit. Exit 1 only when NEITHER
        # source offers a usable brain.
        models = list_models_detailed()
        locals_ = list_local_models(args.get("workspace") or None, force=True)
        if not models and not locals_:
            print("[!] no local models found.")
            print("    - pull one:            ollama pull qwen2.5-coder:3b  (is Ollama running?)")
            print("    - or drop a .gguf file into a models folder:")
            print("        NOVA_MODELS_DIR=/path/to/models   (or ~/.nova/models)")
            sys.exit(1)
        print("")
        if models:
            print(f"  Ollama models ({len(models)}):")
            for i, name, size, desc in nmodels.table_rows(models):
                line = f"  {i:>3}  {name}"
                if size:
                    line += f"  ({size})"
                if desc:
                    line += "   " + desc
                print(line)
            note = nmodels.table_overflow_note(models)
            if note:
                print("      " + note)
        else:
            print("  Ollama models: (none - is Ollama running?)")
        if locals_:
            print(f"\n  Local model files ({len(locals_)}):   model files in your model folders")
            cap = nmodels.table_limit() if nmodels else 20
            for j, e in enumerate(locals_[:cap], len(models) + 1):
                size_s = _model_fmt_size(e.get("size"))
                desc = " · ".join(p for p in (e.get("arch"), e.get("params"),
                                              e.get("quant")) if p)
                line = f"  {j:>3}  {e['name']}  [{e['format']}]"
                if e.get("category", "general") != "general":
                    line += " [" + e["category"] + "]"
                if size_s:
                    line += f"  ({size_s})"
                if desc:
                    line += "   " + desc
                if not e.get("runnable", False):
                    line += "   (not runnable)"
                print(line)
            extra = len(locals_) - cap
            if extra > 0:
                print(f"      ... and {extra} more local files")
            dirs = lmodels.model_dirs(args.get("workspace") or None)
            print("      folders: " + ", ".join(str(p) for _l, p, _e in dirs))
        print("")
        print("  use in Nova:  /model <name|number>   |   pick a default:  NOVA_MODEL=<name>")
        print("  model files:  NOVA_MODELS_DIR=/path/to/folder   (default: ~/.nova/models)")
        print("  categories:   <folder>/code  <folder>/voice  <folder>/photo   (folder root = general)")
        return
    if providers is not None and args["provider"]:
        try:
            # v6.7 fix: the vault (.nova/providers.json) holds the keys -
            # but it was only loaded inside Session.__init__, which runs
            # AFTER this. A key stored ONLY in the vault made
            # set_provider raise "needs an API key" and sys.exit(1) (or
            # fall back silently on the web face), breaking the
            # documented "file wins over env" contract at startup.
            _ws_env0 = os.environ.get("NOVA_WORKSPACE", "").strip()
            _ws0 = args["workspace"] or _ws_env0 or "nova-workspace"
            try:
                providers.load_config(Path(_ws0).expanduser().resolve())
            except Exception:
                pass
            cfg0 = providers.set_provider(args["provider"])
            # v6.9: the CLI flag outranks the workspace profile for THIS run
            # (the profile used to silently override it inside Session init
            # right after the banner already announced the flag's brain)
            global _CLI_PROVIDER
            _CLI_PROVIDER = args["provider"]
            shown = cfg0.get("model") or "auto (first message resolves it)"
            print(c(C.G, "Provider: " + cfg0["label"] + "  (model: " + shown + ")"))
        except Exception as e:
            if providers is not None and isinstance(e, providers.ProviderError):
                print(c(C.R, "[!] " + str(e)))
                if not args["web"]:
                    sys.exit(1)
            else:
                raise
    if args["web"]:
        if __name__ == "__main__":
            # the running script IS nova - make sure web_server imports THIS
            # instance (not a fresh copy) so all state stays in one brain
            sys.modules.setdefault("nova", sys.modules[__name__])
        import web_server
        web_server.serve(args)   # returns only on Ctrl+C
        return
    # v6.2.1 fix: honor NOVA_WORKSPACE the same way nova_assistant.py and
    # the v6 modules already do - before, the env var silently changed the
    # modules' workspace (voice/photo/flow output) while the agent itself
    # still used ./nova-workspace, splitting one project across two folders.
    _ws_env = os.environ.get("NOVA_WORKSPACE", "").strip()
    _run_terminal(args["workspace"] or _ws_env or "nova-workspace")


def _run_terminal(ws_arg):
    """The classic terminal face - same behavior as always, now aware of
    the active provider (Ollama checks only run for the Ollama brain)."""
    cfg = _provider_cfg()
    installed = None          # None = Ollama unreachable; [] = reachable, empty
    if cfg.get("kind") == "ollama":
        print(c(C.D, "[*] checking Ollama at " + OLLAMA_URL + " ..."))
        for attempt in (1, 2, 3):
            try:
                tags = http_get_json("/api/tags")
                # NOTE: parse the payload HERE so a dead Ollama raises (and
                # triggers the retry loop) while an empty library is just []
                installed = nmodels.names_of(nmodels.parse_tags(tags)) if nmodels else []
                break
            except Exception as e:
                if attempt == 3:
                    # warn, do NOT exit: the agent must still start so the
                    # workspace can be browsed and the provider switched
                    print(c(C.Y, "[!] cannot reach Ollama: " + str(e)))
                    print(c(C.D, "    Start it with:  ollama serve"))
                    print(c(C.D, "    Or set a custom URL:  NOVA_OLLAMA_URL=http://host:11434 python3 nova.py"))
                    print(c(C.D, "    (the agent starts anyway - Nova retries on your first message)"))
                    installed = None
                    break
                print(c(C.Y, f"    (attempt {attempt} failed - retrying; a slow machine may need a moment)"))
                time.sleep(2)
    else:
        print(c(C.D, "[*] brain: " + cfg["label"] + "  (model: " + cfg.get("model", "?") + ")"))
        print(c(C.D, "    the local Ollama library is one command away:  /provider ollama"))

    sess = Session(Path(ws_arg).expanduser().resolve())
    sess.ws.mkdir(parents=True, exist_ok=True)
    # v6.7 fix: re-read the provider AFTER Session init - the workspace
    # profile (applied in __init__) may have switched the active brain to
    # a cloud provider, while `installed` was probed against Ollama
    # BEFORE that. The old code then ran the Ollama-only resolver anyway,
    # auto-picked a local tag that "matched best" and hijacked the cloud
    # model -> every chat 404'd against the cloud API.
    cur = _provider_cfg()
    if installed is not None and cur.get("kind") in ("ollama", "?"):
        # v5.1: resolve against what IS installed (honours profile /
        # NOVA_MODEL / memory, falls back to the best local model).
        sess.model = resolve_session_model(sess, installed=installed)
    elif cur.get("kind") not in ("ollama", "?"):
        sess.model = cur.get("model", sess.model)
    # v8.7: the boot-time resolution above can silently change the brain
    # AFTER Session.__init__ wrote the tracker - the vision gate would
    # then ask about a model that is not serving (a seeing brain reported
    # text-only, or vice versa).
    _VISION_ACTIVE["model"] = sess.model
    atexit.register(stop_serve, sess)
    atexit.register(sess.save_memory)
    if lmodels is not None:
        atexit.register(lmodels.stop_all)   # kill any llama.cpp server we spawned
    if nova_bg is not None:
        nova_bg.prune(sess.ws)

    try:
        repl(sess)
    finally:
        stop_serve(sess)


# =====================================================================
# v8.1 AI IMAGE LAYERS (+ v8.6 VISION LAYER) - the connected brain
# helps FIND photos and MUST give the final verdict on every photo
# Nova puts on a page:
#
#   layer 1 (FIND)   _img_ai_queries  - a CLOUD brain turns the (often
#           Persian) request into precise English stock-photo phrases;
#           they join the nova_images search ladder as extra rungs.
#   layer 2 (VERIFY) _img_ai_verify  - the brain SEES the downloaded,
#           normalized photo and answers {"ok": true/false}.
#   v8.6 CHANGE - the user's law: when the ACTIVE brain is a LOCAL
#           model, the LOCAL model is THE approver - detected 100%
#           automatically (ollama /api/show capabilities / families /
#           gguf header keys / mmproj sidecar / name fallback, see
#           nova_vision.py). A cloud brain is asked only when the local
#           model cannot see (or is absent); strict mode refuses AI
#           photo selection entirely in that case. The SELECTION GATE
#           (_vision_selection_gate) may refuse the whole search before
#           one request leaves the machine, and /img + /imgdl (human
#           downloads) ride the same approval through
#           _vision_gate_verdict.
#
# Fail-soft law (the pipeline can never be bricked by the AI layer):
#   - dead network / quota / garbage answer -> the photo passes as
#     "unverified" with a visible note (pre-8.1 behavior), never a
#     build failure;
#   - only a CLEAR {"ok": false} verdict rejects a candidate (the next
#     ranked candidate is tried; placeholders stay the last resort);
#   - a circuit breaker stops hammering a dead brain (3 fails -> 5 min).
# Kill switches: NOVA_NO_IMG_AI=1 (AI layers only), NOVA_NO_IMAGES=1
# (whole image system), NOVA_VISION_SHOW=0 (name-regex detection only).
# Hooks stay None without the provider stack.
# =====================================================================
IMG_AI_VERIFY_TIMEOUT = 30        # seconds per vision verdict
IMG_AI_QUERY_TIMEOUT = 20         # seconds per phrase expansion
_IMG_AI_QCACHE = {}               # query(lower) -> [phrases]
_IMG_AI_STATE = {"fails": 0, "until": 0.0, "local": None}
# None = untested | True = local vision works | False = don't ask again

_IMG_AI_VERIFY_PROMPT = (
    "You are the strict photo reviewer of a website builder. The page "
    "needs ONE photo for this request: \"{q}\".\n"
    "Look at the attached photo. Approve it ONLY if it clearly and "
    "primarily shows the requested subject (and the requested color, "
    "when the request names one). Reject stock watermarks, logos, "
    "text posters, collages and anything unrelated.\n"
    "Answer with ONE JSON line only: {{\"ok\": true}} or "
    "{{\"ok\": false, \"reason\": \"<max 8 words>\"}}")

_IMG_AI_QUERY_PROMPT = (
    "Turn this image-search request into short English stock-photo "
    "search phrases a photo site understands. Request: \"{q}\".\n"
    "Rules: name the concrete subject; keep a named color; 2-5 words "
    "each; 3 phrases. Answer with ONLY a JSON array of strings, e.g. "
    "[\"red rose flower closeup\",\"red roses bouquet\"]")

# ---- v8.6 vision helpers ---------------------------------------------------
# (the name-regex shortcut moved into nova_vision.NAME_RE as the LAST rung
# only - the honest answer comes from ollama /api/show, the gguf header or
# an mmproj sidecar; see _vision_capability below)

def _vision_settings_now():
    """The ACTIVE workspace's vision settings for the sess-less image
    hooks (they run inside nova_images with no Session in hand - the
    _VISION_ACTIVE tracker carries the workspace). Fail-soft: any
    problem means the DEFAULTS (approve on, strict off)."""
    if vision is None:
        return {}
    ws = _VISION_ACTIVE.get("ws")
    if not ws:
        return {}
    try:
        return vision.load_settings(ws)
    except Exception:
        return {}


def _vision_capability(lcfg=None, lmodel=""):
    """v8.6: THE 100% AUTOMATIC answer to 'can the active LOCAL brain
    see a photo?'. nova_vision.detect() walks the ladder - ollama
    /api/show capabilities/families/projector, the gguf header keys of a
    file: brain, an mmproj sidecar, and only then the name regex -
    cached per model (600 s), offline-first, NEVER raises. A missing
    module or an unknown shape degrades to vision=False with an honest
    detail string (the callers treat that as 'the local model cannot
    see', the fail-soft law)."""
    if vision is None:
        return {"vision": False, "via": "missing",
                "detail": "nova_vision.py is missing"}
    lcfg = lcfg if isinstance(lcfg, dict) else {}
    kind = str(lcfg.get("kind") or "ollama").lower()
    # v8.7 CRITICAL fix: the provider config's model field is EMPTY for
    # Ollama (the active brain lives in sess.model). The _VISION_ACTIVE
    # tracker is written on every boot / model switch exactly for these
    # sess-less hooks - but nothing read it, so the whole v8.6 vision
    # layer kept asking about an empty model name and always answered
    # "cannot see" (the approval gate never ran, strict always refused).
    model = str(lmodel or _VISION_ACTIVE.get("model")
                or lcfg.get("model") or "")
    path = None
    prefix = lmodels.LOCAL_PREFIX if lmodels is not None else "file:"
    if model.startswith(prefix):
        try:
            entry = _find_local_entry(model)
            path = str(entry.get("file") or "") if entry else None
        except Exception:
            path = None
    vkind = kind if kind in ("ollama", "llamacpp") else "ollama"
    try:
        return vision.detect(vkind, model, base=OLLAMA_URL, path=path)
    except Exception:
        return {"vision": False, "via": "error",
                "detail": "detection failed (fail-soft)", "model": model}


def _vision_selection_gate(query):
    """nova_images.AI_GATE_HOOK - the SELECTION GATE the user asked for:
    BEFORE one internet photo is searched or downloaded for a page, the
    approval layer decides. Returns (ok, note) - only a clear False
    blocks (nova_images fails soft on anything else).
      approve=off                -> open (the user opted out)
      active brain is CLOUD      -> open (the v8.1 cloud gate verifies)
      local brain CAN see        -> open ('local-vision-on')
      local brain text-only      -> strict: REFUSE (placeholders only)
                                    | else: open with an honest note
    """
    if vision is None:
        return True, ""
    try:
        st = _vision_settings_now()
        if not vision.enabled(st, "approve"):
            return True, "approval-off"
        try:
            lcfg = _provider_cfg() or {}
        except Exception:
            lcfg = {}
        if not _is_free_local(lcfg):
            return True, "cloud-gate"
        cap = _vision_capability(lcfg)
        if cap.get("vision"):
            return True, "local-vision-on"
        if vision.enabled(st, "strict"):
            return False, ("strict mode: the local model cannot see "
                           "photos (vision-off)")
        return True, "local-text-only"
    except Exception:
        return True, ""          # a broken gate can never brick the fill


# the /imgdl verdict: no subject to match - the gate asks whether the
# chosen download is a real, intact image at all
_IMG_HUMAN_GATE_PROMPT = (
    "You are the download gatekeeper of a website builder. The user "
    "chose this image from the internet. Approve it ONLY if it is a "
    "real, intact image (a photo or an illustration - not an error "
    "page, a broken/placeholder file, a spam watermark sheet or "
    "anything that looks corrupted).\n"
    "Answer with ONE JSON line only: {{\"ok\": true}} or "
    "{{\"ok\": false, \"reason\": \"<max 8 words>\"}}")


def _img_verify_human(jpeg):
    """v8.6: /imgdl - the LOCAL AI must approve the download before it
    lands in assets (the user's law). approve=off -> pass with a note;
    otherwise the same local-first verdict pipeline as the fill."""
    st = _vision_settings_now()
    if vision is None or not vision.enabled(st, "approve"):
        return True, "approval-off"
    return _img_ai_verify("download check", jpeg,
                          prompt=_IMG_HUMAN_GATE_PROMPT)


def _img_ai_open():
    """True = the AI layers are paused (kill switch or breaker open)."""
    if os.environ.get("NOVA_NO_IMG_AI") == "1":
        return True
    return time.time() < _IMG_AI_STATE["until"]


def _img_ai_note_fail():
    """One more infra failure; three in a row close the breaker 5 min."""
    _IMG_AI_STATE["fails"] += 1
    if _IMG_AI_STATE["fails"] >= 3:
        _IMG_AI_STATE["until"] = time.time() + 300
        _IMG_AI_STATE["fails"] = 0


def _img_ai_note_ok():
    _IMG_AI_STATE["fails"] = 0


def _img_ai_parse_verdict(text):
    """(ok, reason) from the reviewer's answer. Robust against prose
    around the JSON, single quotes, uppercase, bare YES/NO words.
    (None, reason) = NO verdict readable - the caller fails soft."""
    if not text:
        return None, "empty answer"
    t = str(text)
    low = t.lower()
    m = re.search(r"\{[^{}]*\}", t, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0).replace("'", '"'))
            if isinstance(obj, dict) and isinstance(obj.get("ok"), bool):
                return obj["ok"], str(obj.get("reason") or "")[:80]
        except Exception:
            pass
    if re.search(r'"ok"\s*:\s*true', low):
        return True, ""
    if re.search(r'"ok"\s*:\s*false', low):
        return False, "rejected"
    # v8.7: the bare-word fallback used startswith("no"), which turned
    # POSITIVE prose like "not a watermark" / "nothing wrong" into a
    # hard REJECT (and any sentence starting with "yes..." into a pass).
    # Positive prefixes stay lenient; negatives need the whole word.
    stripped = low.strip()
    if re.match(r"^(yes|approve[ds]?|ok)\b", stripped):
        return True, ""
    if re.search(r"\b(no|reject(ed)?)\b", stripped):
        return False, "rejected"
    return None, "unreadable answer"


def _img_ai_cloud():
    """(cfg, model) of the brain that MUST verify photos: the cloud
    brain - the /brain 'utility' route when it points at a cloud
    provider, else the ACTIVE provider when it is cloud - else
    (None, '') so the local model gets its best-effort turn."""
    if providers is None:
        return None, ""
    cfg, model = None, ""
    try:
        rcfg, rmodel = providers.resolve_route("utility")
        if rcfg is not None and not _is_free_local(rcfg) \
                and rcfg.get("kind") not in ("?",):
            cfg, model = rcfg, rmodel
    except Exception:
        pass
    if cfg is None:
        try:
            acfg = _provider_cfg()
            if acfg and not _is_free_local(acfg) \
                    and acfg.get("kind") not in ("?",):
                cfg, model = acfg, str(acfg.get("model") or "")
        except Exception:
            cfg = None
    if cfg is not None and not cfg.get("key") and not cfg.get("key_optional"):
        return None, ""       # a 'cloud' config without a key is unusable
    return cfg, model


def _img_ai_thumb(jpeg):
    """Downscale to a cheap verification thumbnail (448px, JPEG q70) so
    one verdict costs kilobytes, not megabytes. Unreadable bytes and a
    missing Pillow pass the original through (frontier APIs accept it)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
        im.thumbnail((448, 448))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return buf.getvalue()
    except Exception:
        return jpeg


def _img_ai_messages(kind, prompt, b64):
    """Vision messages in the exact wire shape the provider kind wants.
    gemini/ollama ride the compact {'images': [b64]} form (nova_providers
    / _ollama_once convert it), openai and anthropic get native blocks."""
    if kind == "anthropic":
        return [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/jpeg",
                                         "data": b64}},
            {"type": "text", "text": prompt}]}]
    if kind in ("gemini", "ollama"):
        return [{"role": "user", "content": prompt, "images": [b64]}]
    return [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url",
         "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]


def _ollama_once(model, messages, timeout):
    """One collected non-streaming Ollama chat round-trip (vision via
    the message 'images' field). Raises on any problem - caller fails
    soft. 4 MB read cap like every other response in the project."""
    payload = {"model": model, "messages": messages, "stream": False,
               "keep_alive": KEEP_ALIVE,
               "options": {"temperature": 0.1, "num_predict": 160,
                           "num_ctx": NUM_CTX}}
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read(4_000_000).decode("utf-8", "replace"))
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"])[:200])
    return str((data.get("message") or {}).get("content", "") or "")


def _img_ai_verify(query, jpeg, prompt=None):
    """nova_images.AI_VERIFY_HOOK - the FINAL say on one photo.
    v8.6: when the ACTIVE brain is a LOCAL model that can SEE (detected
    automatically), the LOCAL model approves - the user's law. A cloud
    brain is the gate only when the local model cannot see or is
    absent. `prompt` overrides the subject-match prompt (the /imgdl
    integrity gate rides the same verdict pipeline). Returns
    (ok, verdict_tail):
      (True, 'ai-approved')    cloud said yes        -> store the photo
      (True, 'local-approved') local vision said yes -> store the photo
      (True, 'ai-soft'|'ai-unreachable'|...)  infra trouble -> fail soft
      (False, reason)          the AI REJECTED this candidate
    The fill/pick callers treat False as 'try the next candidate'."""
    q = str(query or "").strip()
    if not q or not jpeg:
        return True, ""
    if _img_ai_open():
        return True, "ai-cold"
    try:
        thumb = _img_ai_thumb(jpeg)
        if len(thumb) > 3_000_000:        # absurd even for frontier APIs
            return True, "ai-skip-size"
        b64 = base64.b64encode(thumb).decode("ascii")
    except Exception:
        return True, "ai-skip-size"
    prompt = prompt or _IMG_AI_VERIFY_PROMPT.format(q=q[:160])
    # ---- v8.6: the LOCAL brain gets the first (and preferred) say ----
    try:
        lcfg = _provider_cfg() or {}
    except Exception:
        lcfg = {}
    lkind = str(lcfg.get("kind", "ollama")).lower()
    # v8.7: same fix as _vision_capability - ask about the ACTIVE brain.
    lmodel = str(_VISION_ACTIVE.get("model") or lcfg.get("model") or "")
    # v8.7: honor the cached text-only verdict - the flag used to be
    # written and never read, so every photo re-ran the whole detection
    # ladder (and a broken local endpoint re-charged the breaker).
    local_capable = _IMG_AI_STATE.get("local") is not False \
        and _is_free_local(lcfg) and lkind in ("ollama", "?") and lmodel \
        and vision is not None
    if local_capable:
        cap = _vision_capability(lcfg, lmodel)
        if not cap.get("vision"):
            _IMG_AI_STATE["local"] = False   # text-only - stop asking
            # fall through: a cloud gate (if configured) still applies
        else:
            try:
                text = _ollama_once(
                    lmodel, _img_ai_messages("ollama", prompt, b64),
                    IMG_AI_VERIFY_TIMEOUT)
            except Exception:
                # v8.7: a TRANSIENT request failure must not cache the
                # permanent text-only verdict - the 5-minute breaker
                # below throttles the retry instead.
                _img_ai_note_fail()          # timed breaker, not forever
                return True, "local-unavailable"
            _img_ai_note_ok()
            ok, why = _img_ai_parse_verdict(text)
            if ok is None:
                return True, "local-soft"
            if not ok:
                return False, why or "local-rejected"
            return True, "local-approved"
    cfg, model = _img_ai_cloud()
    if cfg is not None:
        # ---- the CLOUD gate (mandatory verdict, fail-soft infra) ----
        try:
            text = providers.once(cfg, model,
                                  _img_ai_messages(
                                      str(cfg.get("kind", "openai")).lower(),
                                      prompt, b64),
                                  timeout=IMG_AI_VERIFY_TIMEOUT,
                                  max_tokens=160)
        except Exception:
            _img_ai_note_fail()
            return True, "ai-unreachable"
        _img_ai_note_ok()
        ok, why = _img_ai_parse_verdict(text)
        if ok is None:
            return True, "ai-soft"
        if not ok:
            return False, why or "rejected"
        return True, "ai-approved"
    return True, ""


def _img_ai_queries(query):
    """nova_images.AI_QUERY_HOOK - layer 1 (FIND): the CLOUD brain
    suggests precise English photo phrases for one request. [] when no
    cloud brain / breaker open / any error - the local ladder (fa->en
    dictionary + relaxation) still searches exactly as before."""
    q = str(query or "").strip()
    if not q or _img_ai_open():
        return []
    key = q.lower()
    hit = _IMG_AI_QCACHE.get(key)
    if hit is not None:
        return hit
    cfg, model = _img_ai_cloud()
    if cfg is None:
        return []
    try:
        text = providers.once(
            cfg, model,
            [{"role": "user",
              "content": _IMG_AI_QUERY_PROMPT.format(q=q[:160])}],
            timeout=IMG_AI_QUERY_TIMEOUT, max_tokens=160)
    except Exception:
        _img_ai_note_fail()
        return []
    _img_ai_note_ok()
    out = []
    m = re.search(r"\[[^\[\]]*\]", str(text), re.DOTALL)
    if m:
        try:
            arr = json.loads(m.group(0).replace("'", '"'))
            if isinstance(arr, list):
                out = [it.strip() for it in arr
                       if isinstance(it, str) and it.strip()]
        except Exception:
            pass
    if len(_IMG_AI_QCACHE) > 300:
        _IMG_AI_QCACHE.clear()
    _IMG_AI_QCACHE[key] = out[:4]
    return out[:4]


def _install_img_ai_hooks():
    """v8.1: wire the two AI image layers into nova_images. v8.6 adds
    the SELECTION GATE (the local-vision approval layer). Idempotent -
    a reload under NOVA_NO_IMG_AI=1 also CLEARS previously installed
    hooks (the call-time check in _img_ai_open stays the real gate)."""
    if imgsys is None:
        return
    if providers is None or os.environ.get("NOVA_NO_IMG_AI") == "1":
        try:
            imgsys.AI_QUERY_HOOK = None
            imgsys.AI_VERIFY_HOOK = None
            imgsys.AI_GATE_HOOK = None
        except Exception:
            pass
        return
    try:
        imgsys.AI_QUERY_HOOK = _img_ai_queries
        imgsys.AI_VERIFY_HOOK = _img_ai_verify
        imgsys.AI_GATE_HOOK = _vision_selection_gate
    except Exception:
        pass


_install_img_ai_hooks()

if __name__ == "__main__":
    main()
