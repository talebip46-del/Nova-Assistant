#!/usr/bin/env python3
# =====================================================================
#  Nova Code - local model discovery (v5.1)
#
#  Nova is NO LONGER tied to one custom-built model. Whatever sits in
#  the local Ollama library is fair game: this module reads the model
#  catalogue (/api/tags), turns it into clean records, picks a sane
#  DEFAULT for a fresh workspace and matches what the user typed in
#  /model <name|number>.
#
#  Pure standard library. Every function here is a PURE function of its
#  inputs - no network, no prints - so the offline test suite can hammer
#  every malformed payload a broken proxy or a future Ollama version
#  might produce without any server running.
#
#  Defensive rules (each one earned by a real-world shape):
#    - payload not a dict / "models" not a list  -> []
#    - an entry that is not a dict               -> skipped
#    - name missing / empty / non-string         -> skipped
#    - duplicate names (Ollama can list a model
#      twice across name/model aliases)          -> first wins
#    - sizes that are nonsense                   -> kept, size=None
#    - embedding models never become the AUTO pick
# =====================================================================
import os
import re

# Words that mark an EMBEDDING model. /api/chat with one of them is an
# instant 400 - so the auto-pick must never land on one (the user can
# still select them explicitly from the /model table).
EMBED_MARKERS = ("embed", "bge-", "minilm", "gte-", "e5-", "arctic",
                 "snowflake", "jina-embed", "nomic")

# Auto-pick preference: a coding-capable brain is what Nova is FOR, so
# names containing earlier keywords win over later ones. Everything is
# matched case-insensitively against the model name.
PREFER_KEYWORDS = ("coder", "code", "deepseek", "qwen", "codellama",
                   "codestral", "starcoder", "devstral", "llama", "mistral",
                   "gemma", "phi", "granite", "command")

MAX_NAME_LEN = 120          # sanity cap - a 4 KB 'name' is garbage
_NAME_SAFE_RE = re.compile(r"[\w./:^\-+ ]+$")   # what a model name may contain


def _clean_name(raw):
    """Validate one model name. Returns '' for anything that is not a
    plain, sane model name (guards the profile file and later JSON
    payloads the name is echoed into)."""
    if not isinstance(raw, str):
        return ""
    name = raw.strip()
    if not name or len(name) > MAX_NAME_LEN:
        return ""
    if "\n" in name or "\r" in name or "\t" in name:
        return ""
    if not _NAME_SAFE_RE.match(name):
        return ""
    return name


def _clean_size(raw):
    """int size in bytes, or None - booleans/strings/floats stay sane."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return int(raw) if raw > 0 else None


def _clean_str(raw, cap=80):
    """Short display string ('family', 'parameter_size', ...)."""
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    return s[:cap] if s else ""


def parse_tags(payload):
    """One /api/tags JSON body -> ordered list of clean model dicts:
    {name, size, family, params, quant, modified}. Never raises: any
    surprise shape degrades to fewer/emptier fields, never an exception.
    Order follows the server (Ollama sends newest first) - the /model
    table and the number picker rely on that stability."""
    if not isinstance(payload, dict):
        return []
    models = payload.get("models")
    if not isinstance(models, list):
        return []
    out, seen = [], set()
    for m in models:
        if not isinstance(m, dict):
            continue
        # Ollama fills both "name" and "model" with the same string; if
        # they ever diverge, either is acceptable as the identifier.
        name = _clean_name(m.get("name")) or _clean_name(m.get("model"))
        if not name or name in seen:
            continue
        seen.add(name)
        details = m.get("details") if isinstance(m.get("details"), dict) else {}
        out.append({
            "name": name,
            "size": _clean_size(m.get("size")),
            "family": _clean_str(details.get("family")),
            "params": _clean_str(details.get("parameter_size")),
            "quant": _clean_str(details.get("quantization_level")),
            "modified": _clean_str(m.get("modified_at"), cap=40),
        })
    return out


def names_of(models):
    """[dict] -> [str] (the only part most callers need)."""
    return [m["name"] for m in models if isinstance(m, dict) and m.get("name")]


def is_embedding_model(name):
    """True when the name smells like an embedding model."""
    n = (name or "").lower()
    return any(marker in n for marker in EMBED_MARKERS)


def pick_default(names, env_model=""):
    """Deterministic DEFAULT model for a fresh workspace.

    Order of truth:
      1. NOVA_MODEL env (explicit user override - honoured even when it
         is not installed; startup prints a warning in that case)
      2. the best coding-capable installed model
      3. any installed model (embedding models only as a last resort)
      4. '' - nothing installed, the caller shows guidance

    Ties break alphabetically, which also prefers the smallest tag of a
    family (1.5b before 7b) - Nova's weak-hardware-first philosophy.
    """
    env = (env_model or os.environ.get("NOVA_MODEL", "")).strip()
    if env:
        return env
    clean = [n for n in (names or []) if isinstance(n, str) and n]
    if not clean:
        return ""
    normal = [n for n in clean if not is_embedding_model(n)]

    def rank(name):
        low = name.lower()
        for i, kw in enumerate(PREFER_KEYWORDS):
            if kw in low:
                return i
        return len(PREFER_KEYWORDS)

    pool = normal or clean
    return sorted(pool, key=lambda n: (rank(n), n))[0]


def resolve_choice(arg, names):
    """Match what the user typed in `/model <arg>` against the installed
    names. Returns the full installed name, or None.

    Priority (a model literally named '5' beats index 5):
      1. exact name
      2. base name match WITHOUT an explicit tag (qwen2.5-coder ->
         qwen2.5-coder:7b) - first hit in server order
      3. 1-based index into the /model table

    v6.5: priority 2 no longer fires when the user typed an EXPLICIT tag
    ("/model llama3:8b" with only llama3:latest + llama3:70b installed)
    - it used to silently chat with whichever variant sorted first (on a
    weak-hardware assistant that could load a 70B). An explicit tag that
    is not installed is now an honest None.
    """
    arg = (arg or "").strip()
    if not arg:
        return None
    names = [n for n in (names or []) if isinstance(n, str) and n]
    if arg in names:
        return arg
    if ":" not in arg:
        base = arg.strip().lower()
        if base:
            for n in names:
                if n.split(":")[0].strip().lower() == base:
                    return n
    if arg.isdigit():
        idx = int(arg)
        if 1 <= idx <= len(names):
            return names[idx - 1]
    return None


# --------------------------------------------------------------- display
def fmt_size(size):
    """Bytes -> '1.9 GB' style ('' for unknown). Small units matter for
    the day Ollama lists something tiny; GB cap matches nova.py.
    bool is an int subclass in Python - True must not print as '1 B'."""
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        return ""
    n = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0
    return ""


def _row_label(m):
    """Compact 'family - params - quant' description for one model."""
    parts = [p for p in (m.get("family"), m.get("params"), m.get("quant")) if p]
    return " · ".join(parts)


DEFAULT_TABLE_ROWS = 40


def table_limit():
    """Row cap for the /model table (NOVA_MODEL_TABLE, default 40).
    A nonsense env value just means the default - never an error."""
    raw = os.environ.get("NOVA_MODEL_TABLE", "").strip()
    if raw.isdigit() and 5 <= int(raw) <= 500:
        return int(raw)
    return DEFAULT_TABLE_ROWS


def table_rows(models, max_rows=None):
    """The /model table: list of (index, name, size_str, desc) tuples,
    capped at max_rows (default: table_limit()). Pure - the caller
    decides how to paint it."""
    if max_rows is None:
        max_rows = table_limit()
    rows = []
    for i, m in enumerate(models[:max_rows], 1):
        rows.append((i, m.get("name", ""), fmt_size(m.get("size")),
                     _row_label(m)))
    return rows


def table_overflow_note(models, max_rows=None):
    """'' or the '... and N more' note for a capped table."""
    if max_rows is None:
        max_rows = table_limit()
    extra = len(models) - max_rows
    return f"... and {extra} more (raise: NOVA_MODEL_TABLE={max_rows * 2})" \
        if extra > 0 else ""


def web_list(models, cap=60):
    """Compact list for /api/info: capped dicts with only what the
    browser dropdown needs. Names are already validated by parse_tags,
    so the page can safely build <option> elements from them."""
    out = []
    for m in models[:cap]:
        out.append({"name": m.get("name", ""),
                    "size": fmt_size(m.get("size")),
                    "params": m.get("params", "")})
    return out
