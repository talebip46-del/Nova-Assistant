#!/usr/bin/env python3
# =====================================================================
#  Nova Code - the IDIOM LIBRARY (v7.5.0)
#
#  A small library of proven, dependency-free code patterns. How it is
#  injected depends on the backend (nova_backend.prompt_profile):
#    local_small    - "USE these patterns" (a weak model leans on them)
#    cloud_frontier - "OPTIONAL suggestions - ignore freely" (a strong
#                     model keeps its own style; the library must never
#                     rigidify it or cap its creativity)
#
#  Every idiom is short, stdlib-only and battle-tested. The text block
#  is capped so the prompt budget stays safe on 4 GB machines.
#  Fail-soft everywhere: any error returns "" (zero prompt impact).
# =====================================================================

# language detection keyword tables (checked against the USER'S words)
_LANG_HINTS = {
    "python": ("python", "django", "flask", "py ", "script", "اسکریپت پایتون",
               "پایتون", "بوت", "کرال", "اسکرپر"),
    "javascript": ("javascript", " js ", "node", "react", "vue", "جاوااسکریپت",
                   "نود"),
    "web": ("html", "css", "website", "landing", "page", "site", "وب", "سایت",
            "صفحه", "لندینگ", "فرم"),
    "sql": ("sql", "database", "sqlite", "query", "table", "دیتابیس", "پایگاه",
            "کوئری", "جدول"),
}

# name -> (language, when-to-use line, pattern lines)
_IDIOMS = {
    "safe_int": ("python", "turn untrusted text into a number",
                 "def safe_int(v, default=0):\n"
                 "    try:\n"
                 "        return int(str(v).strip())\n"
                 "    except (ValueError, TypeError):\n"
                 "        return default"),
    "read_file": ("python", "read a text file with a clear failure",
                  "from pathlib import Path\n"
                  "def read_text(path, default=\"\"):\n"
                  "    try:\n"
                  "        return Path(path).read_text(encoding=\"utf-8\")\n"
                  "    except OSError as e:\n"
                  "        print(f\"cannot read {path}: {e}\")\n"
                  "        return default"),
    "cli_loop": ("python", "entry point + main()",
                 "def main():\n    ...\n\n"
                 "if __name__ == \"__main__\":\n"
                 "    main()"),
    "param_sql": ("sql", "EVERY user value is a ? parameter",
                  "cur.execute(\"SELECT * FROM users WHERE id = ?\", (user_id,))"),
    "dom_safe": ("javascript", "guard DOM lookups before use",
                 "const btn = document.getElementById(\"go\");\n"
                 "if (btn) {\n"
                 "    btn.addEventListener(\"click\", () => { ... });\n"
                 "}"),
    "fetch_guard": ("javascript", "async fetch with error handling",
                    "async function load(url) {\n"
                    "    try {\n"
                    "        const r = await fetch(url);\n"
                    "        if (!r.ok) throw new Error(\"HTTP \" + r.status);\n"
                    "        return await r.json();\n"
                    "    } catch (e) {\n"
                    "        console.error(\"load failed:\", e);\n"
                    "        return null;\n"
                    "    }\n"
                    "}"),
    "html_skeleton": ("web", "viewport + relative css/js paths",
                      "<!doctype html>\n"
                      "<html lang=\"fa\" dir=\"rtl\">\n"
                      "<head>\n"
                      "  <meta charset=\"utf-8\">\n"
                      "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
                      "  <link rel=\"stylesheet\" href=\"css/style.css\">\n"
                      "</head>\n"
                      "<body>\n"
                      "  <script src=\"js/main.js\"></script>\n"
                      "</body>\n"
                      "</html>"),
    "responsive_card": ("web", "responsive card grid without media queries",
                        ".cards { display: grid;\n"
                        "  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));\n"
                        "  gap: 16px; }"),
}

# which idioms fit which language (order = presentation order)
_BY_LANG = {
    "python": ("cli_loop", "safe_int", "read_file"),
    "sql": ("param_sql",),
    "javascript": ("dom_safe", "fetch_guard"),
    "web": ("html_skeleton", "responsive_card"),
}


def detect_language(text):
    """Coarse language guess from the user's words (fail-soft -> 'python')."""
    t = " " + str(text or "").lower() + " "
    for lang, hints in _LANG_HINTS.items():
        for h in hints:
            if h in t:
                return lang
    return "python"


def pick(text, lang=None, limit=4):
    """Idiom names fitting the request (deterministic order, capped)."""
    try:
        lang = lang or detect_language(text)
        names = list(_BY_LANG.get(lang, ()))
        if lang in ("javascript", "web"):
            names += _BY_LANG["python"][:1]   # a shared helper idiom
        return names[:max(1, int(limit))]
    except Exception:
        return []


def _render(name, indent=""):
    lang, when, code = _IDIOMS[name]
    lines = [f"- {name} ({when}):", ""]
    lines += [indent + ln for ln in code.splitlines()]
    return "\n".join(lines)


def suggest_text(text, profile="cloud_frontier", lang=None, cap_chars=1400):
    """The context block for one turn. cloud_frontier = OPTIONAL hints the
    model may ignore; local_small = firmer 'lean on these' guidance.
    Returns '' when nothing fits or anything goes wrong (zero impact)."""
    try:
        names = pick(text, lang)
        if not names:
            return ""
        if profile == "cloud_frontier":
            head = ("## Optional idiom hints (you may ignore every one)\n"
                    "If your own approach is better, skip this section "
                    "entirely - it is only a fallback reference:\n")
        else:
            head = ("## Proven patterns for this task (lean on them)\n"
                    "These tiny dependency-free patterns already pass the "
                    "quality bar - reuse them instead of inventing weaker "
                    "variants:\n")
        body = "\n".join(_render(n) for n in names)
        out = head + body
        return out[:cap_chars]
    except Exception:
        return ""


def library_size():
    """How many idioms ship (for /doctor + tests)."""
    return len(_IDIOMS)
