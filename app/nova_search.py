#!/usr/bin/env python3
# =====================================================================
#  Nova Code - web research module (v3.4)
#  Keyless web search + page reading + trusted-source ranking.
#  Pure Python standard library. No API keys. No pip dependencies.
#
#  Backends (chosen because they work WITHOUT any API key):
#    1. DuckDuckGo HTML/Lite  - general web search (region-aware:
#                               Persian queries search with kl=ir-fa so
#                               Iranian sites surface first)
#    2. Wikipedia Action API  - encyclopedia fallback (JSON, en + fa -
#                               Persian queries also read fa.wikipedia)
#    3. StackExchange API     - coding Q&A fallback (JSON)
#
#  Results from ~390 trusted domains are ranked first:
#    tier 0 = official documentation (MDN, docs.python.org, react.dev, ...)
#    tier 1 = major reference / Q&A (Stack Overflow, Wikipedia, GitHub, ...)
#    tier 2 = quality tutorials (realpython, freecodecamp, ...)
#
#  IRANIAN WEB (v3.4): ~55 credible Iranian domains (zarinpal, bale.ai,
#  post.ir, aparat, digikala + mag, divar, snapp, tapsi, filimo, namava,
#  the news agencies, the Iranian magazines, banks/fintech, government
#  service portals, e-commerce, sports, education...) are trusted-ranked
#  EXACTLY like the English list - tagged 'fa', so any Persian query
#  (or latin query naming an Iranian brand) boosts them to the top.
#  Everything else stays fully searchable - the trusted list only
#  REORDERS, it never filters.
#
#  LANGUAGE-AWARE RANKING (v2.4, extended in v3.0/v3.3):
#    the trusted list is tagged by language (sql, javascript, python,
#    rust, go, c, cpp, csharp, java, php, ... 42 languages/ecosystems,
#    including regex, gdscript, wasm and assembly). detect_language() reads
#    the query and results whose OFFICIAL docs
#    belong to that language are boosted to the very top - so a SQL
#    question surfaces postgresql.org/sqlite.org first, a JavaScript
#    question surfaces MDN/react.dev first, and so on.
#
#  Weak-hardware / slow-network policy:
#    - every network timeout is generous and env-tunable
#    - every search & page is cached on disk (default 7 days), so repeated
#      lookups work instantly and even fully offline
#
#  Standalone test:
#      python3 nova_search.py "css flexbox center a div"
#      python3 nova_search.py --page https://docs.python.org/3/
#      python3 nova_search.py --learn "python argparse tutorial"
# =====================================================================
import hashlib
import html as html_mod
import http.client
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser
from pathlib import Path

VERSION = "3.4"

# ---- settings (all env-tunable) --------------------------------------------
def _envint(name, default, lo=1, hi=None):
    """Read an int env var safely: bad/empty value falls back to the
    default (a typo like NOVA_PAGE_CHARS=abc must never crash the agent)."""
    try:
        v = int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        v = default
    v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


SEARCH_TIMEOUT = _envint("NOVA_SEARCH_TIMEOUT", 45, lo=1)   # s per request
SEARCH_RETRIES = _envint("NOVA_SEARCH_RETRIES", 1, lo=0, hi=5)  # extra attempts
MAX_RESULTS = _envint("NOVA_SEARCH_RESULTS", 8, lo=1, hi=25)    # /search list size
LEARN_PAGES = _envint("NOVA_LEARN_PAGES", 3, lo=1, hi=8)        # /learn page count
QUICK_PAGES = 2                                                 # auto [SEARCH:] pages
PAGE_CHARS = _envint("NOVA_PAGE_CHARS", 1500, lo=200)           # text kept per page
KB_CHARS = _envint("NOVA_KB_CHARS", 3000, lo=200)               # KB injected in prompt
try:
    CACHE_DAYS = float(os.environ.get("NOVA_CACHE_DAYS", "7"))
except (TypeError, ValueError):
    CACHE_DAYS = 7.0
CACHE_DAYS = max(0.0, CACHE_DAYS)
CACHE_DIR = Path(os.environ.get("NOVA_CACHE_DIR", str(Path.home() / ".nova_cache")))
UA = "Mozilla/5.0 (X11; Linux x86_64) NovaAssistant/" + VERSION + " (local AI assistant)"

# ---- trusted sources (v2.4 -> v3.4: ~390 domains across ALL major languages)
# Every entry: (domain_suffix, tier, *language_tags)
#   tier 0 = official documentation        tier 1 = major reference / Q&A
#   tier 2 = quality tutorials / registries
# Language tags power detect_language(): when the query mentions a language
# (sql, javascript, rust, ...), results whose official docs carry that tag
# are boosted to the very front. Longest domain suffix wins; anything not
# listed is still searchable, just ranked after trusted results ([web]).
TRUSTED = [
    # -------- web core: HTML / CSS / JavaScript --------
    ("developer.mozilla.org", 0, "javascript", "html", "css"),
    ("w3.org", 0, "html"), ("whatwg.org", 0, "html"),
    ("caniuse.com", 0, "css"), ("web.dev", 0, "javascript", "css"),
    ("developer.chrome.com", 0, "javascript", "html", "css"),
    ("getbootstrap.com", 0, "css"), ("tailwindcss.com", 0, "css"),
    ("sass-lang.com", 0, "css"), ("lesscss.org", 0, "css"),
    ("postcss.org", 0, "css"),
    # -------- JavaScript frameworks & libraries --------
    ("react.dev", 0, "javascript"), ("vuejs.org", 0, "javascript"),
    ("nuxt.com", 0, "javascript"), ("angular.dev", 0, "javascript"),
    ("svelte.dev", 0, "javascript"), ("kit.svelte.dev", 0, "javascript"),
    ("nextjs.org", 0, "javascript"), ("astro.build", 0, "javascript"),
    ("solidjs.com", 0, "javascript"), ("preactjs.com", 0, "javascript"),
    ("alpinejs.dev", 0, "javascript"), ("htmx.org", 0, "javascript"),
    ("jquery.com", 0, "javascript"), ("threejs.org", 0, "javascript"),
    ("d3js.org", 0, "javascript"), ("chartjs.org", 0, "javascript"),
    ("leafletjs.com", 0, "javascript"), ("socket.io", 0, "javascript"),
    ("expressjs.com", 0, "javascript"), ("nestjs.com", 0, "javascript"),
    ("fastify.dev", 0, "javascript"), ("hono.dev", 0, "javascript"),
    ("koajs.com", 0, "javascript"), ("gatsbyjs.com", 0, "javascript"),
    ("remix.run", 0, "javascript"), ("qwik.dev", 0, "javascript"),
    ("redux.js.org", 0, "javascript"), ("rxjs.dev", 0, "javascript"),
    ("reactrouter.com", 0, "javascript"), ("tanstack.com", 0, "javascript"),
    ("pinia.vuejs.org", 0, "javascript"), ("router.vuejs.org", 0, "javascript"),
    ("storybook.js.org", 0, "javascript"), ("testing-library.com", 0, "javascript"),
    ("axios-http.com", 0, "javascript"), ("lodash.com", 0, "javascript"),
    ("date-fns.org", 0, "javascript"), ("day.js.org", 0, "javascript"),
    ("mui.com", 0, "javascript"), ("ant.design", 0, "javascript"),
    ("gsap.com", 0, "javascript"), ("phaser.io", 0, "javascript"),
    ("pixijs.com", 0, "javascript"), ("babylonjs.com", 0, "javascript"),
    ("dexie.org", 0, "javascript"), ("adonisjs.com", 0, "javascript"),
    ("zod.dev", 0, "typescript", "javascript"),
    # -------- JavaScript runtimes, build tools & testing --------
    ("nodejs.org", 0, "javascript"), ("deno.com", 0, "javascript"),
    ("bun.sh", 0, "javascript"), ("webpack.js.org", 0, "javascript"),
    ("vitejs.dev", 0, "javascript"), ("rollupjs.org", 0, "javascript"),
    ("esbuild.github.io", 0, "javascript"), ("parceljs.org", 0, "javascript"),
    ("babeljs.io", 0, "javascript"), ("eslint.org", 0, "javascript"),
    ("prettier.io", 0, "javascript"), ("jestjs.io", 0, "javascript"),
    ("vitest.dev", 0, "javascript"), ("mochajs.org", 0, "javascript"),
    ("playwright.dev", 0, "javascript"), ("pptr.dev", 0, "javascript"),
    ("cypress.io", 0, "javascript"), ("selenium.dev", 0, "javascript"),
    ("prisma.io", 0, "javascript", "sql"), ("sequelize.org", 0, "javascript", "sql"),
    ("knexjs.org", 0, "javascript", "sql"),
    ("graphql.org", 0, "graphql"), ("apollographql.com", 0, "graphql"),
    ("typescriptlang.org", 0, "typescript", "javascript"),
    # -------- Python: core & web --------
    ("python.org", 0, "python"), ("docs.python.org", 0, "python"),
    ("peps.python.org", 0, "python"), ("packaging.python.org", 0, "python"),
    ("huggingface.co", 0, "python"), ("docs.streamlit.io", 0, "python"),
    ("docs.djangoproject.com", 0, "python"), ("djangoproject.com", 0, "python"),
    ("palletsprojects.com", 0, "python"), ("fastapi.tiangolo.com", 0, "python"),
    ("docs.pydantic.dev", 0, "python"), ("docs.sqlalchemy.org", 0, "python", "sql"),
    ("docs.pytest.org", 0, "python"), ("docs.celeryq.dev", 0, "python"),
    ("docs.aiohttp.org", 0, "python"), ("scrapy.org", 0, "python"),
    ("pygame.org", 0, "python"), ("jupyter.org", 0, "python"),
    ("ipython.org", 0, "python"),
    ("docs.astral.sh", 0, "python"),           # ruff + uv
    ("python.langchain.com", 0, "python"), ("docs.llamaindex.ai", 0, "python"),
    ("ollama.com", 0, "python", "javascript"), ("docs.ollama.com", 0),
    ("sympy.org", 0, "python"), ("networkx.org", 0, "python"),
    ("docs.psycopg.org", 0, "python", "sql"), ("spacy.io", 0, "python"),
    ("nltk.org", 0, "python"),
    # -------- Python: data science & ML --------
    ("pandas.pydata.org", 0, "python"), ("numpy.org", 0, "python"),
    ("matplotlib.org", 0, "python"), ("docs.scipy.org", 0, "python"),
    ("scikit-learn.org", 0, "python"), ("pytorch.org", 0, "python"),
    ("tensorflow.org", 0, "python"), ("keras.io", 0, "python"),
    ("opencv.org", 0, "cpp", "python"), ("python-pillow.org", 0, "python"),
    # -------- creative coding --------
    ("p5js.org", 0, "javascript"), ("processing.org", 0, "java", "javascript"),
    ("godotengine.org", 0, "cpp"), ("sfml-dev.org", 0, "cpp"),
    ("libsdl.org", 0, "c", "cpp"), ("raylib.com", 0, "c", "cpp"),
    ("docs.unity3d.com", 0, "csharp", "cpp"),
    ("doc.qt.io", 0, "cpp"), ("qt.io", 0, "cpp"),
    ("boost.org", 0, "cpp"), ("vulkan.org", 0, "cpp"),
    ("glfw.org", 0, "c", "cpp"), ("openframeworks.cc", 0, "cpp"),
    # -------- Java / JVM / Kotlin --------
    ("docs.oracle.com", 0, "java"), ("openjdk.org", 0, "java"),
    ("dev.java", 0, "java"), ("spring.io", 0, "java"),
    ("maven.apache.org", 0, "java"), ("gradle.org", 0, "java", "kotlin"),
    ("hibernate.org", 0, "java"), ("kotlinlang.org", 0, "kotlin"),
    ("junit.org", 0, "java"), ("quarkus.io", 0, "java"),
    ("micronaut.io", 0, "java"), ("projectlombok.org", 0, "java"),
    ("logback.qos.ch", 0, "java"), ("slf4j.org", 0, "java"),
    ("tomcat.apache.org", 1, "java"),
    ("developer.android.com", 0, "kotlin", "java"),
    ("ktor.io", 0, "kotlin"),
    # -------- C / C++ --------
    ("cppreference.com", 0, "c", "cpp"), ("isocpp.org", 0, "cpp"),
    ("gcc.gnu.org", 0, "c", "cpp", "fortran"), ("clang.llvm.org", 0, "c", "cpp"),
    ("llvm.org", 0, "c", "cpp"), ("cmake.org", 0, "cpp"),
    ("gnu.org", 0, "c", "cpp", "bash"),
    # -------- C# / .NET / F# --------
    ("learn.microsoft.com", 0, "csharp", "powershell", "sql"),
    ("dotnet.microsoft.com", 0, "csharp"), ("fsharp.org", 0, "csharp"),
    # -------- Go --------
    ("go.dev", 0, "go"), ("pkg.go.dev", 0, "go"),
    ("gofiber.io", 0, "go"), ("echo.labstack.com", 0, "go"),
    # -------- Rust --------
    ("rust-lang.org", 0, "rust"), ("doc.rust-lang.org", 0, "rust"),
    ("docs.rs", 0, "rust"), ("bevy.org", 0, "rust"),
    ("tokio.rs", 0, "rust"), ("serde.rs", 0, "rust"),
    # -------- Go / PHP / Ruby / C# extras --------
    ("gin-gonic.com", 0, "go"), ("gorm.io", 0, "go"),
    ("guides.rubyonrails.org", 0, "ruby"), ("ruby-doc.org", 0, "ruby"),
    ("sinatrarb.com", 0, "ruby"),
    ("codeigniter.com", 0, "php"), ("doctrine-project.org", 0, "php"),
    ("avaloniaui.net", 0, "csharp"),
    # -------- PHP --------
    ("php.net", 0, "php"), ("laravel.com", 0, "php"), ("symfony.com", 0, "php"),
    ("getcomposer.org", 0, "php"), ("wordpress.org", 0, "php"),
    # -------- Ruby --------
    ("ruby-lang.org", 0, "ruby"), ("rubyonrails.org", 0, "ruby"),
    # -------- Swift / iOS --------
    ("swift.org", 0, "swift"), ("developer.apple.com", 0, "swift"),
    ("vapor.codes", 0, "swift"),
    # -------- Dart / Flutter --------
    ("dart.dev", 0, "dart"), ("flutter.dev", 0, "dart"),
    ("docs.flutter.dev", 0, "dart"), ("api.flutter.dev", 0, "dart"),
    # -------- other languages --------
    ("scala-lang.org", 0, "scala"), ("clojure.org", 0, "clojure"),
    ("elixir-lang.org", 0, "elixir"), ("hexdocs.pm", 0, "elixir"),
    ("erlang.org", 0, "erlang"), ("haskell.org", 0, "haskell"),
    ("hackage.haskell.org", 0, "haskell"), ("ocaml.org", 0, "ocaml"),
    ("perl.org", 0, "perl"), ("r-project.org", 0, "r"),
    ("tidyverse.org", 0, "r"), ("julialang.org", 0, "julia"),
    ("ziglang.org", 0, "zig"), ("nim-lang.org", 0, "nim"),
    ("lua.org", 0, "lua"), ("groovy-lang.org", 0, "java"),
    ("fortran-lang.org", 0, "fortran"), ("swi-prolog.org", 0, "prolog"),
    ("soliditylang.org", 0, "solidity"), ("mathworks.com", 0, "matlab"),
    ("octave.org", 0, "matlab"),
    ("docs.soliditylang.org", 0, "solidity"),
    ("docs.openzeppelin.com", 0, "solidity"), ("ethereum.org", 1, "solidity"),
    ("docs.scala-lang.org", 0, "scala"),
    ("stackage.org", 1, "haskell"), ("wiki.haskell.org", 1, "haskell"),
    ("phoenixframework.org", 0, "elixir"), ("elixirschool.com", 2, "elixir"),
    ("neovim.io", 0, "lua"), ("lua-users.org", 1, "lua"),
    ("openresty.org", 0, "lua"),
    ("perldoc.perl.org", 0, "perl"), ("metacpan.org", 1, "perl"),
    ("cran.r-project.org", 1, "r"), ("rdrr.io", 2, "r"),
    ("docs.julialang.org", 0, "julia"),
    # -------- SQL & databases --------
    ("postgresql.org", 0, "sql"), ("sqlite.org", 0, "sql"),
    ("mysql.com", 0, "sql"), ("mariadb.com", 0, "sql"), ("mariadb.org", 0, "sql"),
    ("mongodb.com", 0, "sql"), ("redis.io", 0, "sql"),
    ("clickhouse.com", 0, "sql"), ("elastic.co", 0, "sql"),
    ("supabase.com", 0, "sql"), ("neo4j.com", 0, "sql"),
    ("duckdb.org", 0, "sql"), ("cockroachlabs.com", 0, "sql"),
    ("docs.timescale.com", 0, "sql"),
    ("typeorm.io", 0, "javascript", "sql"), ("orm.drizzle.team", 0, "javascript", "sql"),
    ("cassandra.apache.org", 0, "sql"), ("couchdb.apache.org", 0, "sql"),
    ("trino.io", 0, "sql"), ("prestodb.io", 0, "sql"),
    ("influxdata.com", 0, "sql"),
    # -------- regex --------
    ("regular-expressions.info", 1, "regex"),
    # -------- git / devops / servers --------
    ("git-scm.com", 0, "git"), ("docs.github.com", 1, "git", "devops"),
    ("developer.hashicorp.com", 0, "devops"), ("owasp.org", 1), ("docs.docker.com", 0, "devops"),
    ("kubernetes.io", 0, "devops"), ("helm.sh", 0, "devops"),
    ("hashicorp.com", 0, "devops"), ("docs.ansible.com", 0, "devops"),
    ("nginx.org", 0, "devops", "linux"), ("caddyserver.com", 0, "devops"),
    ("prometheus.io", 0, "devops"), ("grafana.com", 0, "devops"),
    ("jenkins.io", 0, "devops"), ("grpc.io", 0),
    ("curl.se", 0, "linux", "c"),
    ("rabbitmq.com", 0, "devops"), ("kafka.apache.org", 0, "devops"),
    ("nats.io", 0, "devops"),
    ("meilisearch.com", 0, "devops"), ("typesense.org", 0, "devops"),
    ("traefik.io", 0, "devops"), ("circleci.com", 2, "devops"),
    ("swagger.io", 0, "devops"), ("openapis.org", 0, "devops"),
    ("docs.aws.amazon.com", 1, "devops"), ("cloud.google.com", 1, "devops"),
    # -------- webassembly / assembly --------
    ("webassembly.org", 0, "wasm"), ("rustwasm.github.io", 0, "wasm", "rust"),
    ("felixcloutier.com", 1, "assembly"),      # x86 instruction reference
    ("ref.x86asm.net", 1, "assembly"),
    ("sourceware.org", 1, "c", "assembly"),   # glibc + binutils docs
    # -------- major reference / Q&A (tier 1) --------
    ("stackoverflow.com", 1), ("stackexchange.com", 1), ("wikipedia.org", 1),
    ("github.com", 1, "git"), ("gist.github.com", 1, "git"),
    ("gitlab.com", 1, "git"), ("kernel.org", 1, "linux"),
    ("man7.org", 1, "linux", "bash"), ("archlinux.org", 1, "linux"),
    ("apache.org", 1), ("unicode.org", 1), ("json.org", 1), ("oauth.net", 1),
    ("yaml.org", 1), ("json-schema.org", 1), ("toml.io", 1),
    ("wiki.archlinux.org", 1, "linux"), ("man.archlinux.org", 1, "linux"),
    ("portswigger.net", 1),
    # -------- quality tutorials / registries (tier 2) --------
    ("w3schools.com", 2, "html", "css", "sql"), ("geeksforgeeks.org", 2),
    ("freecodecamp.org", 2), ("realpython.com", 2, "python"),
    ("css-tricks.com", 2, "css"), ("javascript.info", 2, "javascript"),
    ("dev.to", 2), ("digitalocean.com", 2), ("tldp.org", 2, "linux", "bash"),
    ("explainshell.com", 1, "bash"), ("shellcheck.net", 2, "bash"),
    ("baeldung.com", 2, "java"), ("phptherightway.com", 2, "php"),
    ("pypi.org", 2, "python"), ("npmjs.com", 2, "javascript"),
    ("crates.io", 2, "rust"), ("nuget.org", 2, "csharp"),
    ("mvnrepository.com", 2, "java"), ("packagist.org", 2, "php"),
    ("rubygems.org", 2, "ruby"), ("pub.dev", 2, "dart"),
    ("docker.com", 2, "devops"), ("kaggle.com", 2, "python", "r"),
    ("readthedocs.io", 2, "python"), ("readthedocs.org", 2, "python"),
    ("devdocs.io", 2), ("ss64.com", 2, "bash", "powershell"),
    ("hex.pm", 2, "elixir"), ("clojars.org", 2, "clojure"),
    ("ubuntu.com", 2, "linux"),
    # ---- v3.4: IRANIAN web (~55 credible domains, all tagged 'fa') ----
    # Payments / fintech / banks
    ("zarinpal.com", 0, "fa"), ("idpay.ir", 0, "fa"),
    ("zibal.ir", 0, "fa"), ("payping.ir", 0, "fa"),
    ("nextpay.org", 0, "fa"), ("bsi.ir", 0, "fa"),
    ("bankmellat.ir", 0, "fa"), ("bpi.ir", 0, "fa"),
    ("enbank.ir", 0, "fa"), ("cbi.ir", 0, "fa"),
    ("codal.ir", 0, "fa"), ("tsetmc.com", 0, "fa"),
    # Marketplaces / services / mobility
    ("digikala.com", 0, "fa"), ("mag.digikala.com", 1, "fa"),
    ("digistyle.com", 2, "fa"), ("divar.ir", 0, "fa"),
    ("sheypoor.com", 2, "fa"), ("torob.com", 2, "fa"),
    ("emalls.ir", 2, "fa"), ("basalam.com", 2, "fa"),
    ("snapp.ir", 0, "fa"), ("tapsi.ir", 0, "fa"),
    ("alibaba.ir", 0, "fa"), ("snapptrip.com", 2, "fa"),
    ("post.ir", 0, "fa"), ("enamad.ir", 0, "fa"),
    ("samandehi.ir", 0, "fa"),
    # Messaging / media / video
    ("bale.ai", 0, "fa"), ("eitaa.com", 2, "fa"),
    ("aparat.com", 0, "fa"), ("filimo.com", 0, "fa"),
    ("namava.ir", 2, "fa"),
    # News agencies / news sites
    ("irna.ir", 1, "fa"), ("isna.ir", 1, "fa"),
    ("tasnimnews.com", 1, "fa"), ("mehrnews.com", 1, "fa"),
    ("farsnews.ir", 1, "fa"), ("khabaronline.ir", 1, "fa"),
    ("yjc.ir", 1, "fa"), ("donya-e-eqtesad.com", 1, "fa"),
    # Iranian magazines / editorial (the user's emphasis)
    ("zoomit.ir", 1, "fa"), ("zoomg.ir", 1, "fa"),
    ("chetor.com", 1, "fa"), ("virgool.io", 2, "fa"),
    ("tebyan.net", 1, "fa"), ("varzesh3.com", 1, "fa"),
    # Government / public services
    ("iran.ir", 0, "fa"), ("gov.ir", 0, "fa"),
    ("adliran.ir", 0, "fa"), ("sabteahval.ir", 0, "fa"),
    ("tax.gov.ir", 0, "fa"), ("pol.ir", 2, "fa"),
    # Education / tech community
    ("sanjesh.org", 0, "fa"), ("maktabkhooneh.org", 1, "fa"),
    ("faradars.org", 2, "fa"), ("quera.org", 2, "fa"),
]
TIER_BADGE = {0: "official", 1: "trusted", 2: "community"}
UNKNOWN_TIER = 99

# precomputed suffix -> (tier, langs); lookup strips subdomain labels, so a
# hit is always the LONGEST registered suffix: O(labels) instead of scanning
# the whole list for every URL.
_TRUST_MAP = {}
for _dom, _tier, *_langs in TRUSTED:
    if _dom in _TRUST_MAP:
        # fail fast like nova.py's tool registry: a duplicate suffix means
        # one entry silently shadows the other - fix the list instead.
        raise RuntimeError("nova_search: duplicate trusted domain: " + _dom)
    _TRUST_MAP[_dom] = (_tier, frozenset(_langs))


def trust_info(url):
    """Return (tier, languages) for a URL. Longest domain suffix wins;
    unknown domains get (UNKNOWN_TIER, ())."""
    dom = domain_of(url)
    if not dom:
        return (UNKNOWN_TIER, frozenset())
    parts = dom.split(".")
    for i in range(len(parts)):
        hit = _TRUST_MAP.get(".".join(parts[i:]))
        if hit:
            return hit
    return (UNKNOWN_TIER, frozenset())


def is_trusted(url):
    """Backward-compatible check: return (trusted, tier) for a URL.
    Longest domain suffix wins."""
    tier, _langs = trust_info(url)
    return (tier != UNKNOWN_TIER, tier)


def tier_badge(tier):
    return TIER_BADGE.get(tier, "web")


# ---- language detection (v2.4) ----------------------------------------------
# Keywords per language. "strong" keywords detect the language on their own;
# "weak" keywords are ambiguous (go, r, c, node, ...) and only count when the
# query shows at least two signals (two weak hits, or a weak hit plus a
# generic programming word). Detection only BOOSTS ranking of matching
# official docs - a false negative costs nothing, a false positive just
# reorders trusted results, so the heuristic is intentionally conservative.
LANG_KW = {
    "python": {"strong": ["python", "python3", "django", "flask", "pip",
                          "numpy", "pandas", "matplotlib", "scipy", "pytest",
                          "fastapi", "pydantic", "sqlalchemy", "venv",
                          "virtualenv", "conda", "jupyter", "asyncio",
                          "tkinter", "pygame", "pathlib", "poetry",
                          "uvicorn", "gunicorn", "celery", "argparse",
                          "mypy", "ruff", "pyinstaller", "dataclass",
                          "decorator", "type hints", "langchain",
                          "llamaindex", "psycopg", "sympy", "streamlit",
                          "list comprehension"]},
    "javascript": {"strong": ["javascript", "js", "nodejs", "node.js",
                              "react", "vue", "vue.js", "angular", "svelte",
                              "npm", "es6", "ecmascript", "jquery", "express",
                              "next.js", "nextjs", "nuxt", "webpack", "vite",
                              "frontend", "dom", "promise", "fetch api",
                              "async await", "phaser", "pixijs", "babylon",
                              "gsap", "mui", "ant design", "dexie",
                              "adonis", "three.js", "rxjs", "dayjs"],
                   "weak": ["node", "await", "callback"]},
    "typescript": {"strong": ["typescript", "tsx", "tsconfig", "tsc", "zod"],
                   "weak": ["ts"]},
    "html": {"strong": ["html", "html5", "doctype", "meta tag",
                        "semantic html", "html tag"]},
    "css": {"strong": ["css", "css3", "flexbox", "grid", "scss", "sass",
                       "tailwind", "bootstrap", "stylesheet", "media query",
                       "pseudo class", "selector"]},
    "sql": {"strong": ["sql", "postgresql", "postgres", "mysql", "mariadb",
                       "sqlite", "sqlite3", "duckdb", "clickhouse",
                       "t-sql", "pl/sql", "transact-sql", "mssql",
                       "group by", "order by", "inner join", "left join",
                       "right join", "full outer", "primary key",
                       "foreign key", "create table", "alter table",
                       "drop table", "insert into", "union all",
                       "stored procedure", "select * from",
                       "window function", "common table expression",
                       "with recursive", "on conflict", "upsert",
                       "returning", "trino", "presto", "cassandra",
                       "rowid"],
            "weak": ["query", "schema", "migration", "transaction", "join",
                     "index", "database"]},
    "java": {"strong": ["java", "jvm", "jdk", "openjdk", "spring",
                        "spring boot", "maven", "gradle", "hibernate", "jsp",
                        "tomcat", "javafx", "intellij", "junit", "quarkus",
                        "micronaut", "lombok", "log4j", "slf4j", "jackson"]},
    "c": {"weak": ["c", "gcc", "clang", "malloc", "printf", "scanf",
                   "pointer", "pointers", "segmentation", "header file",
                   "stdio", "valgrind", "linker", "linking", "glibc",
                   "c99", "c11"]},
    "cpp": {"strong": ["c++", "cpp", "stl", "iostream", "cmake", "qt",
                       "opengl", "sfml", "sdl", "raylib", "unreal", "std::",
                       "gdscript", "godot", "boost", "vulkan", "glfw",
                       "openframeworks", "catch2"],
            "weak": ["vector", "template", "templates",
                     "polymorphism", "operator overloading",
                     "memory management"]},
    "csharp": {"strong": ["c#", "csharp", ".net", "dotnet", "asp.net",
                          "blazor", "wpf", "linq", "nuget", "unity", "xaml",
                          "maui", "f#", "fsharp"]},
    "go": {"strong": ["golang", "goroutine", "gofmt", "go.mod", "gin",
                      "gorm", "fiber", "gofiber", "pprof"],
           "weak": ["go", "defer", "channels"]},
    "rust": {"strong": ["rust", "cargo", "rustc", "tokio", "serde", "crates",
                        "borrow", "lifetime", "lifetimes", "wasm", "bevy",
                        "axum", "sqlx", "wgpu", "clap"]},
    "php": {"strong": ["php", "laravel", "symfony", "wordpress", "phpunit",
                       "eloquent", "xampp", "artisan", "codeigniter",
                       "doctrine", "mysqli", "pdo"],
            "weak": ["composer"]},
    "ruby": {"strong": ["ruby", "rails", "ruby on rails", "gemfile",
                        "bundler", "rake", "rspec", "sinatra", "erb",
                        "devise", "sidekiq", "haml"]},
    "swift": {"strong": ["swift", "swiftui", "uikit", "xcode", "ios",
                         "cocoa", "arkit", "spritekit", "vapor",
                         "swiftlint"],
              "weak": ["cocoapods"]},
    "kotlin": {"strong": ["kotlin", "ktor", "jetpack compose", "androidx",
                          "jetpack", "compose multiplatform"]},
    "dart": {"strong": ["flutter", "pubspec", "dartlang", "riverpod",
                        "widget tree"],
              "weak": ["dart", "widget"]},
    "r": {"strong": ["ggplot", "ggplot2", "dplyr", "tidyr", "tidyverse",
                     "rstudio", "cran", "shiny", "data.table", "posit"],
          "weak": ["r", "dataframe", "glm", "regression"]},
    "julia": {"strong": ["julia", "dataframes", "flux.jl"], "weak": ["dataframe"]},
    "scala": {"strong": ["scala", "sbt", "akka", "scalatest"]},
    "haskell": {"strong": ["haskell", "ghc", "cabal", "monad", "hackage",
                          "yesod", "aeson", "servant"]},
    "lua": {"strong": ["lua", "love2d", "luarocks", "neovim", "openresty",
                       "luajit", "lapis", "nvim"]},
    "perl": {"strong": ["perl", "cpan", "mojolicious", "perldoc"]},
    "bash": {"strong": ["bash", "zsh", "shell script", "bashrc", "awk",
                        "sed", "grep", "shebang", "cron", "systemctl",
                        "journalctl", "ufw", "bash script",
                        "shell scripting"],
             "weak": ["shell"]},
    "powershell": {"strong": ["powershell", "pwsh", "cmdlet",
                             "get-childitem", "wmi", "cim"],
                   "weak": ["ps1"]},
    "fortran": {"strong": ["fortran", "gfortran", "fortran90"]},
    "zig": {"strong": ["zig", "ziglang"]},
    "nim": {"strong": ["nim", "nimlang"]},
    "ocaml": {"strong": ["ocaml", "opam", "dune"]},
    "erlang": {"strong": ["erlang", "rebar3", "gen_server"],
               "weak": ["otp", "beam"]},
    "elixir": {"strong": ["elixir", "ecto", "phoenix", "mix.exs",
                         "liveview", "exunit"]},
    "clojure": {"strong": ["clojure", "clojurescript", "leiningen", "lein",
                          "reagent", "babashka"]},
    "solidity": {"strong": ["solidity", "hardhat", "truffle", "soliditylang",
                            "erc20", "erc-20", "smart contract",
                            "smart contracts", "openzeppelin", "erc-721",
                            "evm", "ganache", "sepolia", "remix ide"]},
    "matlab": {"strong": ["matlab", "simulink"], "weak": ["octave"]},
    "devops": {"strong": ["docker", "dockerfile", "docker-compose",
                          "docker compose", "kubernetes", "k8s", "kubectl",
                          "helm", "terraform", "ansible", "vagrant",
                          "ci/cd", "devops", "jenkins", "kustomize",
                          "argocd", "istio", "traefik", "github actions",
                          "gitlab ci", "nginx", "caddy", "prometheus",
                          "grafana", "rabbitmq", "kafka",
                          "cloudformation", "pulumi"],
               "weak": ["pipeline", "container", "orchestration"]},
    "git": {"strong": ["git", "github", "gitlab", "rebase", "merge conflict",
                       "gitignore", "pull request", "cherry-pick",
                       "git stash", "git blame", "squash"]},
    "linux": {"strong": ["linux", "ubuntu", "debian", "fedora", "centos",
                         "arch linux", "systemd", "apt", "dnf", "yum",
                         "kernel", "manjaro", "linux mint", "gnome", "kde",
                         "dpkg", "flatpak", "iptables", "nftables", "grub",
                         "wayland"],
              "weak": ["pacman", "pulseaudio", "alsa"]},
    "prolog": {"strong": ["prolog", "swi-prolog"]},
    "graphql": {"strong": ["graphql", "apollo", "graphiql", "resolver",
                          "hasura"]},
    "regex": {"strong": ["regex", "regexp", "regular expression",
                         "regular expressions", "lookahead", "lookbehind",
                         "capture group", "non-greedy", "negative lookahead",
                         "backreference", "lookaround", "pcre"]},
    "wasm": {"strong": ["webassembly", "wasm", "wasi", "wasmtime",
                        "emscripten"]},
    "fa": {"strong": ["zarinpal", "aparat", "digikala", "digistyle",
                      "divar.ir", "bale.ai", "snapptrip", "tapsi",
                      "filimo", "namava", "varzesh3", "tebyan",
                      "virgool", "eitaa", "basalam", "sheypoor",
                      "torob.com", "idpay", "zibal", "payping",
                      "khabaronline", "zoomit", "zoomg", "chetor"]},
    "assembly": {"strong": ["assembly language", "x86", "x86-64", "x86_64",
                           "nasm", "masm", "avx", "opcode", "disassembly",
                           "assembler", "instruction set"],
                 "weak": ["asm", "register", "registers", "stack frame"]},
}

# generic programming words that let a single ambiguous (weak) keyword count
_GENERIC_WORDS = ("error", "function", "compile", "compiler", "library",
                  "install", "array", "string", "loop", "code", "program",
                  "programming", "syntax", "variable", "debug", "module",
                  "command", "script", "build", "run", "import", "export",
                  "exception", "crash", "memory", "package", "framework",
                  "tutorial", "example", "documentation", "language",
                  "write", "file", "learn", "how to")


def _kw_pattern(kw):
    """Escape one keyword; add word boundaries only where the first/last
    character is a word character (so "c++" and ".net" still match).
    An empty/whitespace keyword can never crash the import - it compiles
    to a pattern that matches nothing."""
    kw = kw.strip().lower() if isinstance(kw, str) else ""
    if not kw:
        return r"(?!x)x"          # matches nothing, stays regex-valid
    esc = re.escape(kw)
    pre = r"\b" if (kw[0].isalnum() or kw[0] == "_") else ""
    suf = r"\b" if (kw[-1].isalnum() or kw[-1] == "_") else ""
    return pre + esc + suf


_LANG_PROG = {}
for _lang, _data in LANG_KW.items():
    _strong_kws = _data.get("strong") or []
    _strong = re.compile("|".join(_kw_pattern(k) for k in _strong_kws)
                         or r"(?!x)x", re.IGNORECASE)
    _weak = None
    if _data.get("weak"):
        _weak = re.compile("|".join(_kw_pattern(k) for k in _data["weak"]),
                           re.IGNORECASE)
    _LANG_PROG[_lang] = (_strong, _weak)


_FA_SCRIPT_RE = re.compile(r"[\u0600-\u06FF]")


def detect_language(query):
    """Return the frozenset of languages a query is about (may be empty).
    Conservative: ambiguous keywords need a second signal before counting.
    v3.4: ANY Persian-script query (or a query naming an Iranian brand in
    latin letters) detects 'fa' - fa-tagged Iranian domains are then
    boosted to the top of the ranked results."""
    q = str(query or "").lower()
    if not q.strip():
        return frozenset()
    langs = set()
    for lang, (strong, _weak) in _LANG_PROG.items():
        if strong.search(q):
            langs.add(lang)
    if _FA_SCRIPT_RE.search(q):
        langs.add("fa")
    if langs:
        return frozenset(langs)
    weak_hits = {}
    for lang, (_strong, weak) in _LANG_PROG.items():
        if weak is not None:
            found = set(m.group(0) for m in weak.finditer(q))
            if found:
                weak_hits[lang] = found
    if not weak_hits:
        return frozenset()
    generic = any(g in q for g in _GENERIC_WORDS)
    for lang, found in weak_hits.items():
        if len(found) >= 2 or generic:
            langs.add(lang)
    return frozenset(langs)


def domain_of(url):
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    netloc = netloc.split("@")[-1].split(":")[0]
    return netloc[4:] if netloc.startswith("www.") else netloc


def _resolve_host(host, timeout_s=3.0):
    """v6.5: socket.getaddrinfo has NO timeout parameter - a blackholed
    nameserver stalled every fetch ~10s per hop (per redirect!) before
    urlopen's own timeout even applied. Resolve in a daemon thread with
    a hard deadline; [] on timeout/failure (fail closed)."""
    box = []

    def _work():
        try:
            box.append(socket.getaddrinfo(host, None))
        except Exception:
            pass

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout_s)
    return box[0] if box else []


def _host_is_private(host):
    """True when `host` resolves to loopback / private / link-local /
    reserved space (SSRF guard: a fetched page must not be a window into
    the LAN, the Ollama API or a cloud metadata endpoint). Unresolvable
    hosts fail closed. NOVA_ALLOW_PRIVATE_FETCH=1 disables the guard for
    people who really want to /docs their own local server.
    v6.2.1 fix: the env-var check used to run AFTER the localhost
    early-return, so the documented escape hatch could never unlock
    http://localhost:8080/... (the exact use case it exists for)."""
    host = str(host or "").strip().strip("[]").lower()
    if not host:
        return True
    if os.environ.get("NOVA_ALLOW_PRIVATE_FETCH", "") == "1":
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True
    infos = _resolve_host(host)
    if not infos:
        return True            # cannot resolve in time -> treat as unsafe
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True
    return False


def safe_url(url):
    """Only plain http(s) URLs without credentials and WITHOUT private-
    network targets are allowed (returns None otherwise)."""
    try:
        u = urllib.parse.urlparse(url.strip())
    except Exception:
        return None
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    if u.username or u.password:
        return None
    if _host_is_private(u.hostname):
        return None
    return url.strip()


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but re-check EVERY target through safe_url - a
    trusted-looking URL must not be a trampoline into private networks."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if safe_url(str(newurl)) is None:
            raise urllib.error.HTTPError(
                newurl, code, "redirect blocked by the Nova safety policy", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """v6.5 SSRF fix: safe_url() resolves the hostname at CHECK time but
    urllib resolved it AGAIN at connect time - DNS rebinding (TTL-0 record
    answering 'public IP' to the check and '192.168.x.x' to the fetch)
    walked straight past the guard. This connection verifies the ACTUAL
    peer IP after connecting: whatever DNS said, a private destination is
    refused."""

    def connect(self):
        super().connect()
        self._nova_check_peer()

    def _nova_check_peer(self):
        try:
            peer = str(self.sock.getpeername()[0])
            ip = ipaddress.ip_address(peer)
            bad = (ip.is_private or ip.is_loopback or ip.is_link_local
                   or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
        except Exception:
            bad = True                       # cannot read the peer -> fail closed
        if bad and os.environ.get("NOVA_ALLOW_PRIVATE_FETCH", "") != "1":
            try:
                self.close()
            except Exception:
                pass
            raise urllib.error.URLError(
                "connection blocked by the Nova safety policy "
                "(the host resolved to a private address)")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    # v6.7 fix: borrowing _PinnedHTTPConnection.connect kept its __class__
    # cell, so the zero-arg super() inside resolved against
    # _PinnedHTTPConnection - which is NOT in this class's MRO - and EVERY
    # https fetch raised TypeError before any I/O (search/learn/docs were
    # dead since v6.5). Real method here; super() now reaches
    # HTTPSConnection.connect (socket + TLS wrap) as intended.
    def connect(self):
        super().connect()
        self._nova_check_peer()

    _nova_check_peer = _PinnedHTTPConnection._nova_check_peer


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        kw = {}
        ctx = getattr(self, "_context", None)
        if ctx is not None:
            kw["context"] = ctx
        chn = getattr(self, "_check_hostname", None)
        if chn is not None:
            kw["check_hostname"] = chn
        return self.do_open(_PinnedHTTPSConnection, req, **kw)


_OPENER = urllib.request.build_opener(_SafeRedirectHandler(),
                                      _SafeHTTPHandler(),
                                      _SafeHTTPSHandler())


# --------------------------------------------------------------- binary fetch
def http_get_bytes(url, timeout=None, max_bytes=8_000_000):
    """v7.2: GET a URL as RAW BYTES through the SAME SSRF-safe stack the
    text search uses (safe_url check -> every redirect re-checked -> the
    DNS-rebinding-pinned connection verifies the actual peer IP). Built
    for Nova's image system: returns (bytes, content_type, final_url) or
    raises. No gunzip/charset decoding here - the caller gets the raw
    payload and validates it (magic bytes) itself. A Content-Length above
    max_bytes refuses BEFORE reading (no wasted download); the read is
    capped at max_bytes anyway so a lying header cannot overflow RAM."""
    timeout = SEARCH_TIMEOUT if timeout is None else timeout
    checked = safe_url(url)
    if not checked:
        raise ValueError("only plain public http(s) URLs are allowed")
    req = urllib.request.Request(checked, headers={
        "User-Agent": UA,
        "Accept": "image/*,application/json;q=0.8,*/*;q=0.4",
        "Accept-Language": "en;q=0.9",
    })
    with _OPENER.open(req, timeout=timeout) as resp:
        cl = resp.headers.get("Content-Length", "")
        # v7.2 audit fix: '³'.isdigit() is True but int('³') raises - a
        # hostile Content-Length header must never crash the fetch that
        # the read-cap makes harmless anyway.
        if cl.isascii() and cl.isdigit() and int(cl) > max_bytes:
            raise ValueError("payload larger than the %d byte cap" % max_bytes)
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        raw = resp.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("payload larger than the %d byte cap" % max_bytes)
        return raw, ctype, resp.geturl()


def unwrap_ddg(href):
    """DDG wraps result links in /l/?uddg=<encoded> redirects - unwrap them."""
    href = href or ""
    if href.startswith("//"):
        href = "https:" + href
    m = re.search(r"[?&]uddg=([^&]+)", href)
    if m:
        href = urllib.parse.unquote(m.group(1))
    return href if href.startswith("http") else None


# --------------------------------------------------------------- HTTP
def _gunzip(raw, max_out=8_000_000):
    """Decompress a (possibly TRUNCATED) gzip body. Truncation raises
    EOFError - NOT an OSError - so the old `except OSError` fallback never
    ran for the exact case its comment described (>2 MB gzip pages cut by
    the max_bytes cap). Bad data can raise zlib.error too; both paths now
    degrade to the valid prefix instead of failing the whole fetch.
    v6.5: fed to zlib in small chunks with a HARD output cap - the old
    code expanded first and never checked the length, so a 2 MB gzip bomb
    (ratios above 1000:1 are trivial) allocated gigabytes of RAM before
    anyone looked; chunking also preserves the decompressed PREFIX of a
    truncated stream (a one-shot call raises without yielding any data)."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = bytearray()
    try:
        for i in range(0, len(raw), 65536):
            if len(out) > max_out:
                break
            out += d.decompress(raw[i:i + 65536], max_out - len(out) + 1)
            while len(out) <= max_out and d.unconsumed_tail:
                out += d.decompress(d.unconsumed_tail, max_out - len(out) + 1)
    except (zlib.error, EOFError, OSError):
        pass                           # keep whatever valid prefix came out
    if not out:
        return raw                     # nothing decompressed -> original bytes
    if len(out) > max_out:
        del out[max_out:]              # bomb / huge-page guard
    return bytes(out)


def http_get(url, timeout=None, max_bytes=2_000_000):
    """GET a URL, return (text, final_url). Handles gzip, charset, retries.
    Timeout is generous by design (NOVA_SEARCH_TIMEOUT, default 45 s)."""
    timeout = SEARCH_TIMEOUT if timeout is None else timeout
    url = safe_url(url)
    if not url:
        raise ValueError("only plain http(s) URLs are allowed")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
        "Accept-Language": "en;q=0.9",
    })
    last = None
    for attempt in range(SEARCH_RETRIES + 1):
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                raw = resp.read(max_bytes)
                gz = (raw[:2] == b"\x1f\x8b"
                      or "gzip" in resp.headers.get("Content-Encoding", ""))
                if gz:
                    raw = _gunzip(raw, max_out=min(max_bytes * 5, 8_000_000))
                m = re.search(r"charset=([\w-]+)", resp.headers.get("Content-Type", ""))
                charset = m.group(1) if m else None
                if not charset:
                    mm = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
                    charset = mm.group(1).decode("ascii", "replace") if mm else "utf-8"
                try:
                    text = raw.decode(charset, "replace")
                except (LookupError, UnicodeError):
                    text = raw.decode("utf-8", "replace")
                return text, resp.geturl()
        except Exception as e:
            last = e
            if attempt < SEARCH_RETRIES:
                time.sleep(1.5)
    raise last if last else RuntimeError("request failed")


# --------------------------------------------------------------- text extraction
class _Reader(HTMLParser):
    """Strip tags, keep readable text (pre/code preserved verbatim)."""
    # NOTE: "head" is deliberately NOT in SKIP - <title> lives inside <head>
    # and must be captured. Everything inside <head> that carries data
    # (script/style/noscript) is skipped individually anyway.
    SKIP = {"script", "style", "noscript", "svg", "iframe", "form",
            "nav", "footer", "aside", "button", "select", "option"}
    BLOCK = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3",
             "h4", "h5", "h6", "tr", "table", "ul", "ol", "pre", "blockquote",
             "hr", "dt", "dd", "main", "head", "body", "html"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._pre = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            # only the first title OUTSIDE skipped containers is the page
            # title; later ones (SVG <title> etc.) must not pollute it.
            self._in_title = (self.title == "" and self._skip == 0)
        if tag == "pre":
            self._pre += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        if tag == "pre":
            self._pre = max(0, self._pre - 1)

    def handle_data(self, data):
        if self._skip:            # skipping must win over title capture
            return
        if self._in_title:
            self.title += data
            return
        if self._pre:
            self.parts.append(data)
        else:
            d = data.strip()
            if d:
                self.parts.append(d + " ")


# hot regexes precompiled once (extract_text runs on every fetched page)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"\s+")
_RE_SPACES = re.compile(r"[ \t]+")
_RE_LINE_SP = re.compile(r" ?\n ?")
_RE_NL3 = re.compile(r"\n{3,}")


def extract_text(page_html):
    """Return (title, clean_text) from raw HTML."""
    r = _Reader()
    try:
        r.feed(page_html)
        r.close()
    except Exception:
        pass
    # <title> is CDATA: tag markup arrives verbatim, so strip it manually
    title = _RE_TAG.sub("", r.title)
    title = _RE_WS.sub(" ", title).strip()[:200]
    text = "".join(r.parts)
    text = _RE_SPACES.sub(" ", text)
    text = _RE_LINE_SP.sub("\n", text)
    text = _RE_NL3.sub("\n\n", text)
    return title, text.strip()


# --------------------------------------------------------------- DuckDuckGo
class _DDGParser(HTMLParser):
    """Collect results from the DDG html/lite endpoints. Links and snippets
    are paired at PARSE time (a result without a snippet keeps ''); the old
    two-parallel-lists approach shifted every later snippet onto the wrong
    result whenever one result had none."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []        # [{"href", "title", "snippet"}]
        self._href = None
        self._atext = []
        self._in_snip = False
        self._stext = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "a" and ("result__a" in cls or "result-link" in cls):
            self._href, self._atext = a.get("href", ""), []
        if "result__snippet" in cls or "result-snippet" in cls:
            self._in_snip, self._stext = True, []

    def handle_data(self, d):
        if self._href is not None:
            self._atext.append(d)
        if self._in_snip:
            self._stext.append(d)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.results.append({"href": self._href,
                                 "title": "".join(self._atext).strip(),
                                 "snippet": ""})
            self._href = None
        if self._in_snip and tag in ("a", "div", "td", "span"):
            snip = " ".join("".join(self._stext).split())
            for r in reversed(self.results):
                if not r["snippet"]:
                    r["snippet"] = snip
                    break
            self._in_snip = False


def _parse_ddg(page_html):
    p = _DDGParser()
    try:
        p.feed(page_html)
    except Exception:
        pass
    out = []
    for r in p.results:
        url = unwrap_ddg(r["href"])
        if not url or not r["title"]:
            continue
        out.append({"title": r["title"], "url": url, "snippet": r["snippet"]})
    return out


def ddg_search(query, max_results=MAX_RESULTS, region=None):
    """DuckDuckGo search (no API key). Tries html then lite endpoints.
    v3.4: `region` (e.g. 'ir-fa') is passed as the kl= parameter so the
    results are biased toward that locale - Persian queries ask for
    ir-fa and surface the credible Iranian sites first."""
    q = urllib.parse.quote_plus(query)
    extra = ("&kl=" + urllib.parse.quote_plus(region)) if region else ""
    last = None
    for base in ("https://html.duckduckgo.com/html/?q=",
                 "https://lite.duckduckgo.com/lite/?q="):
        try:
            page, _ = http_get(base + q + extra)
            low = page[:3000].lower()
            # specific block markers only - a generic word like "challenge"
            # also appears in legit result titles and must not abort DDG
            if any(m in low for m in ("anomaly detected", "unfortunately, bots",
                                      "captcha", "verify you are human",
                                      "unusual traffic")):
                last = RuntimeError("duckduckgo rate limit - use a fallback source")
                continue
            res = [r for r in _parse_ddg(page) if r["url"]][:max_results]
            if res:
                return res
            last = RuntimeError("duckduckgo returned no parseable results")
        except Exception as e:
            last = e
    raise last or RuntimeError("duckduckgo failed")


# --------------------------------------------------------------- JSON APIs
def wikipedia_search(query, max_results=3, lang="en"):
    """Wikipedia Action API search (no key). v3.4: `lang` picks the
    encyclopedia edition - Persian queries read fa.wikipedia.org, whose
    coverage of Iranian topics beats the English edition by far."""
    lang = str(lang or "en").lower()
    if lang not in ("en", "fa"):
        lang = "en"
    api = (f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
           "&format=json&origin=*&srlimit=" + str(max_results) +
           "&srsearch=" + urllib.parse.quote_plus(query))
    text, _ = http_get(api)
    data = json.loads(text)
    out = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        if not title:
            continue
        snip = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
        url = f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        out.append({"title": title + " - Wikipedia", "url": url, "snippet": snip})
    return out


def stack_search(query, max_results=4):
    api = ("https://api.stackexchange.com/2.3/search/advanced?order=desc"
           "&sort=relevance&site=stackoverflow&pagesize=" + str(max_results) +
           "&q=" + urllib.parse.quote_plus(query))
    text, _ = http_get(api)
    data = json.loads(text)
    items = sorted(data.get("items", []),
                   key=lambda it: not it.get("is_answered", False))
    out = []
    for it in items:
        link = it.get("link", "")
        if not link:
            continue
        title = html_mod.unescape(it.get("title", ""))
        score = it.get("score", 0)
        answered = "answered" if it.get("is_answered") else "unanswered"
        out.append({"title": f"Stack Overflow: {title} [{answered}, score {score}]",
                    "url": link, "snippet": "tags: " + ", ".join(it.get("tags", []))})
    return out[:max_results]


# --------------------------------------------------------------- text helpers
# hot regexes for strip_html (API bodies)
_RE_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_RE_BREAK = re.compile(r"<br\s*/?>|</p>|</pre>|</li>|</h\d>|</div>|</blockquote>", re.IGNORECASE)
_RE_INLINE = re.compile(r"[^\S\n]+")


def strip_html(raw):
    """Fast tag-stripper for small HTML fragments (API bodies)."""
    text = _RE_SCRIPT.sub(" ", raw)
    text = _RE_BREAK.sub("\n", text)
    text = _RE_TAG.sub("", text)
    text = html_mod.unescape(text)
    text = _RE_INLINE.sub(" ", text)
    text = _RE_NL3.sub("\n\n", text)
    return text.strip()


# --------------------------------------------------------------- ranking
def dedupe(results):
    seen, out = set(), []
    for r in results:
        key = domain_of(r.get("url", "")) + "|" + r.get("url", "").rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def rank_results(results, lang=None):
    """Trusted domains first (official > trusted > community > web), stable.
    When a language set is given, results whose official docs carry that
    language tag are boosted to the very front (score -1)."""
    lang = lang or frozenset()

    def score(r):
        tier, langs = trust_info(r.get("url", ""))
        if lang and (langs & lang):
            return -1
        return tier

    return sorted(results, key=score)


# --------------------------------------------------------------- cache
def _cache_path(key):
    h = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()
    return CACHE_DIR / (h[:2] + "_" + h[2:20] + ".json")


def cache_get(key):
    """Return cached payload or None (expired/corrupt/missing).
    v6.5: expired entries are DELETED on sight - the old code only ignored
    them logically, so nothing ever left ~/.nova_cache and months of use
    grew the folder without bound."""
    p = _cache_path(key)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) > CACHE_DAYS * 86400:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        return data.get("data")
    except Exception:
        return None


def cache_put(key, payload):
    tmp = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _cache_path(key)
        # v6.2.1 fix: the tmp name included NO pid/thread id, so two
        # writers of the same key (threaded web server + agent turn, or two
        # nova processes) shared one .tmp path - writer B's open-truncate
        # could land between A's write and A's os.replace, publishing a
        # truncated entry. v6.8.1: use nova_atomic's tmp_name (pid+thread+
        # counter) - the old "pid*1000 + tid%1000" still collided for two
        # live thread ids equal modulo 1000.
        try:
            import nova_atomic as _natom
            tmp = p.with_name(_natom.tmp_name(p))
        except Exception:
            tmp = p.with_suffix(".%d_%d.tmp" % (os.getpid(), threading.get_ident()))
        tmp.write_text(
            json.dumps({"ts": time.time(), "data": payload}, ensure_ascii=False),
            encoding="utf-8")
        os.replace(tmp, p)   # atomic: a crash mid-write can never leave a
                             # truncated cache file behind
        tmp = None
        # v6.8.1: sweep ORPHAN .tmp files older than an hour - a hard kill
        # between write_text and os.replace used to leak them forever
        # (galleries got this sweep in v6.7; the search cache did not).
        try:
            hour_ago = time.time() - 3600
            for t in CACHE_DIR.glob("*.tmp"):
                try:
                    if t.stat().st_mtime < hour_ago:
                        t.unlink()
                except OSError:
                    continue
        except OSError:
            pass
    except Exception:
        pass  # cache is best-effort, never fatal
    finally:
        # v6.5: a failed write used to leave its partial .tmp behind forever
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


# --------------------------------------------------------------- high level
def web_search(query, max_results=MAX_RESULTS, use_cache=True):
    """Merged search: DuckDuckGo first; Wikipedia + Stack Overflow as
    fallbacks. Ranked trusted-first, deduplicated, cached."""
    query = query.strip()
    if not query:
        raise ValueError("empty query")
    ck = "search:" + query.lower()
    if use_cache:
        hit = cache_get(ck)
        # validate the cached shape: old/corrupt cache files must never crash
        # a search (a dict or list of junk would raise here before v3.0)
        if (isinstance(hit, list) and hit
                and all(isinstance(r, dict) and r.get("url") for r in hit)):
            return hit[:max_results]
    results, errors = [], []
    lang = detect_language(query)      # ranked cache stores the boosted order
    fa = "fa" in lang
    try:
        results += ddg_search(query, max_results=max_results,
                              region=("ir-fa" if fa else None))
    except Exception as e:
        errors.append("web: " + str(e))
    if fa and len(results) < 6:
        # Persian: the Farsi encyclopedia covers Iranian topics the
        # english edition barely has (or has as one-line stubs)
        try:
            results += wikipedia_search(query, max_results=4, lang="fa")
        except Exception as e:
            errors.append("wikipedia-fa: " + str(e))
    if len(results) < 3:
        try:
            results += wikipedia_search(query)
        except Exception as e:
            errors.append("wikipedia: " + str(e))
        try:
            results += stack_search(query)
        except Exception as e:
            errors.append("stackoverflow: " + str(e))
    if not results:
        msg = "; ".join(errors) if errors else "no results"
        raise RuntimeError("search failed - " + msg)
    # v6.2.1 fix: cache the UNCAPPED ranked list. Before, the first
    # query's max_results (8) froze the cache, so a later /learn asking
    # for 24 candidates silently got only 8 from the cache.
    ranked = rank_results(dedupe(results), lang)
    if use_cache:
        cache_put(ck, ranked)
    return ranked[:max_results]


def fetch_stack_page(url):
    """Stack Overflow blocks plain HTML fetching (HTTP 403) - use the
    official StackExchange API instead: question body + top-voted answers.
    Returns (title, text) or None if this is not a question page / API fails."""
    m = re.search(r"/questions/(\d+)", url or "")
    if not m:
        return None
    qid = m.group(1)
    base = "https://api.stackexchange.com/2.3"
    try:
        raw, _ = http_get(f"{base}/questions/{qid}?site=stackoverflow&filter=withbody")
        items = json.loads(raw).get("items", [])
        if not items:
            return None
        it = items[0]
        title = html_mod.unescape(it.get("title", "Stack Overflow question"))
        parts = ["QUESTION: " + title,
                 strip_html(it.get("body", ""))[:600]]
    except Exception:
        return None
    try:
        raw, _ = http_get(f"{base}/questions/{qid}/answers"
                          "?order=desc&sort=votes&site=stackoverflow"
                          "&pagesize=2&filter=withbody")
        for it in json.loads(raw).get("items", [])[:2]:
            label = ("ACCEPTED ANSWER" if it.get("is_accepted")
                     else "ANSWER (score " + str(it.get("score", 0)) + ")")
            parts.append(label + ":\n" + strip_html(it.get("body", ""))[:800])
    except Exception:
        pass
    return title, "\n\n".join(parts)


def fetch_page(url, use_cache=True):
    """Download a page, extract readable text. Returns (title, text)."""
    url = safe_url(url)
    if not url:
        raise ValueError("only plain http(s) URLs are allowed")
    if use_cache:
        hit = cache_get("page:" + url)
        # validate the cached shape: corrupt/old cache must never crash /docs
        if isinstance(hit, dict) and isinstance(hit.get("text", ""), str):
            return hit.get("title", "") or "page", hit["text"]
    dom = domain_of(url)
    title = text = None
    if "stackoverflow.com" in dom or dom.endswith("stackexchange.com"):
        alt = fetch_stack_page(url)
        if alt:
            title, text = alt
    if text is None:
        raw, final_url = http_get(url)
        title, text = extract_text(raw)
        final_url = final_url or url
        title = title or dom or "page"   # never return an empty title
    else:
        final_url = url
    js_only = len(text) < 40
    if js_only:
        # a JS-only page (or a transiently broken render) must NOT be
        # cached: it would be served from cache for CACHE_DAYS days
        text = ("(this page has almost no readable static text - it is probably "
                "JavaScript-only. Try another source.)")
    text = text[:PAGE_CHARS]
    if use_cache and not js_only:
        payload = {"title": title, "text": text}
        cache_put("page:" + final_url, payload)
        if final_url != url:
            # also index under the original URL, otherwise redirected pages
            # would never produce a cache hit on a second lookup
            cache_put("page:" + url, payload)
    return title, text


def learn_topic(query, pages=LEARN_PAGES, status=lambda s: None):
    """Full research pass: search, pick the top pages from DIFFERENT domains,
    read each one. Returns (digest_text, sources list)."""
    query = query.strip()
    if not query:
        raise ValueError("empty topic")
    try:
        pages = int(pages)
    except (TypeError, ValueError):
        pages = LEARN_PAGES
    pages = max(1, min(pages, 8))   # env typos must never break /learn
    results = web_search(query, max_results=max(MAX_RESULTS, pages * 3))
    picked, seen = [], set()
    for r in results:
        dom = domain_of(r["url"])
        if dom in seen:
            continue
        seen.add(dom)
        picked.append(r)
        if len(picked) >= pages:
            break
    blocks, sources = [], []
    for i, r in enumerate(picked, 1):
        status(f"reading {i}/{len(picked)}: {r['url']}")
        try:
            title, text = fetch_page(r["url"])
        except Exception as e:
            status(f"  (failed: {e})")
            continue
        _, tier = is_trusted(r["url"])
        blocks.append(f"[{tier_badge(tier)}] {title}\n{r['url']}\n{text}")
        sources.append(r["url"])
        time.sleep(0.4)  # be polite to the servers
    if not sources:
        raise RuntimeError("no page could be read - try another topic")
    digest = (f"TOPIC: {query}\nDATE: {time.strftime('%Y-%m-%d')}\n"
              f"SOURCES: {len(sources)}\n\n" + "\n\n".join(blocks))
    return digest, sources


def quick_research(query):
    """Small auto-research used when the model sends a [SEARCH: ...] token."""
    return learn_topic(query, pages=QUICK_PAGES, status=lambda s: None)


# --------------------------------------------------------------- knowledge base
KB_BEGIN = "=== KNOWLEDGE:"
KB_END = "=== END ==="


def _kb_clean_topic(topic):
    """One-line, short topic that can never break the KB block format."""
    t = " ".join(str(topic).split())          # collapse newlines/tabs/spaces
    t = t.replace("===", "").replace("|", "/").replace("saved:", "saved-")
    return (t.strip()[:120]) or "untitled topic"


def kb_append(kb_path, topic, digest):
    """Append one knowledge entry to the workspace KB file."""
    topic = _kb_clean_topic(topic)
    # the digest is web text - make sure it can never forge a KB marker line
    digest = str(digest).replace(KB_BEGIN, "[KB]").replace(KB_END, "[END]")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    block = (f"\n{KB_BEGIN} {topic} | saved: {stamp} ===\n"
             f"{digest.strip()}\n{KB_END}\n")
    try:
        kb_path = Path(kb_path)
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        with open(kb_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(block)
    except OSError as e:
        raise RuntimeError("cannot write knowledge base: " + str(e))


def _kb_parse(raw):
    """Parse KB file content into [{topic, saved, text}]."""
    entries = []
    for m in re.finditer(
            re.escape(KB_BEGIN) + r"\s*(.+?)\s*\|\s*saved:\s*(.+?)\s*===\n(.*?)(?="
            + re.escape(KB_END) + ")", raw, re.DOTALL):
        entries.append({"topic": m.group(1).strip(),
                        "saved": m.group(2).strip(),
                        "text": m.group(3).strip()})
    return entries


def kb_entries(kb_path):
    """Parse the KB file back into [{topic, saved, text}]."""
    try:
        raw = Path(kb_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return _kb_parse(raw)


def kb_text(kb_path, limit=KB_CHARS):
    """KB content ready for prompt injection. Rebuilds WHOLE entries until
    the limit - an entry is never cut in half (a half entry could look like
    forged KB content), and parse failures mean an empty injection.
    A single oversized FIRST entry is cut in its TEXT but always keeps its
    closing === END === marker; oversized later entries are skipped so the
    budget goes to smaller whole entries behind them."""
    entries = kb_entries(kb_path)
    if not entries:
        return ""
    out, used = [], 0
    for e in entries:
        header = f"{KB_BEGIN} {e['topic']} | saved: {e['saved']} ===\n"
        if out and used + len(header) + len(e['text']) + len(KB_END) + 2 > limit:
            continue            # too big now - but a smaller later entry
                                # may still fit, so keep scanning
        block = header + e["text"] + "\n" + KB_END
        if len(block) > limit:            # single huge FIRST entry: cut TEXT
            keep = limit - len(header) - len(KB_END) - 2
            if keep < 0:
                # even an EMPTY block cannot fit this limit - skip it
                # (never emit a broken half-format entry)
                continue
            block = header + e["text"][:keep] + "\n" + KB_END
        out.append(block)
        used += len(block) + 2
    return "\n\n".join(out)


# --------------------------------------------------------------- CLI self-test
def _cli():
    args = sys.argv[1:]
    if not args:
        print('usage: python3 nova_search.py "<query>" '
              '| --page <url> | --learn "<topic>"')
        return 1
    if args[0] == "--page" and len(args) > 1:
        title, text = fetch_page(args[1])
        print("TITLE:", title)
        print("-" * 40)
        print(text)
        return 0
    if args[0] == "--learn" and len(args) > 1:
        digest, sources = learn_topic(" ".join(args[1:]), status=print)
        print(digest)
        print("\nsources:", *sources, sep="\n  ")
        return 0
    query = " ".join(args)
    print("Searching:", query)
    lang = detect_language(query)
    if lang:
        print("Languages:", ", ".join(sorted(lang)), "- official docs boosted")
    for i, r in enumerate(web_search(query), 1):
        _, tier = is_trusted(r["url"])
        print(f"  [{i}] ({tier_badge(tier)}) {r['title'][:78]}")
        print(f"       {r['url']}")
        if r.get("snippet"):
            print(f"       {r['snippet'][:110]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(_cli())
    except KeyboardInterrupt:
        print("\n(interrupted)")
        sys.exit(130)
    except Exception as e:
        print("[!] " + type(e).__name__ + ": " + str(e))
        sys.exit(1)
