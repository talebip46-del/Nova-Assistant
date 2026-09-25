#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - the module system (v6.0)
#
#  One program, many sections. Every section ("module") is a small,
#  independent engine that:
#    - owns its data under <workspace>/.nova/modules/<id>/
#    - can be assigned its OWN brain (local Ollama model, a .gguf file,
#      any OpenAI-compatible platform, a cloud provider, or a fully
#      offline built-in engine) - see assign.py
#    - is wired together by Nova Flow, the integration hub
#
#  Registry (MODULES) is the single source of truth for ids, titles and
#  allowed backends - the web UI, the CLI and Flow all read it.
# =====================================================================

# id -> human metadata. Backends:
#   offline     built-in engine, zero setup, always works
#   ollama      one of the installed Ollama models (LLM modules)
#   file        a .gguf model file from the model folders (LLM modules)
#   platform    any discovered OpenAI-compatible server (LocalAI, Shimmy,
#               LM Studio, vLLM, llama.cpp...) - url + model
#   cloud       a cloud provider from nova_providers (LLM modules)
#   a1111 / comfyui  dedicated image engines (photo module)
#   xtts / coqui / bark  dedicated speech engines (voice module):
#               XTTS-v2 API server, Coqui/Mozilla TTS server,
#               bark-server
#   piper     a local piper binary with a voice model file
MODULES = [
    {"id": "code", "icon": "⌨", "title": "Nova Code", "fa": "کدنویسی",
     "desc": "ایجنت کدنویسی کامل: ساخت/ویرایش فایل، اجرا، تست، گیت",
     "backends": ["ollama", "file", "platform", "cloud"],
     "default": {"backend": "auto"},
     "assignable": False},          # the agent brain = /model + /provider
    {"id": "assistant", "icon": "✶", "title": "Assistant Brain", "fa": "مغز دستیار",
     "desc": "مدل مورد استفاده در گره‌های LLM داخل جریان کار (Flow)",
     "backends": ["ollama", "file", "platform", "cloud"],
     "default": {"backend": "auto"},
     "assignable": True},
    {"id": "voice", "icon": "🔊", "title": "Nova Voice", "fa": "صدا",
     "desc": "تبدیل متن به گفتار و گفتار به متن: Piper / XTTS / Coqui / "
             "Bark / سازگار-با-OpenAI + موتور آفلاین",
     "backends": ["offline", "openai_compat", "xtts", "coqui", "bark",
                  "piper"],
     "default": {"backend": "offline"},
     "assignable": True},
    {"id": "photo", "icon": "🖼", "title": "Nova Photo", "fa": "تصویر",
     "desc": "تولید تصویر: موتور آفلاین داخلی یا A1111 / ComfyUI / LocalAI",
     "backends": ["offline", "a1111", "comfyui", "openai_compat"],
     "default": {"backend": "offline"},
     "assignable": True},
    {"id": "pixel", "icon": "👾", "title": "Nova PixelArt", "fa": "پیکسل‌آرت",
     "desc": "پیکسل‌آرت آفلاین: پالت‌های رترو، اسپرایت و صحنه، خروجی PNG",
     "backends": ["offline"],
     "default": {"backend": "offline"},
     "assignable": False},
    {"id": "flow", "icon": "🧩", "title": "Nova Flow", "fa": "جریان کار",
     "desc": "هاب ترکیبی: گردش‌کارهای چندمرحله‌ای بین همه ماژول‌ها",
     "backends": [], "default": {}, "assignable": False},
    {"id": "knowledge", "icon": "📚", "title": "Nova Knowledge", "fa": "دانش",
     "desc": "دانش محلی پروژه: خوردن اسناد، جستجوی TF-IDF، بسته‌ی زمینه",
     "backends": ["offline"], "default": {"backend": "offline"},
     "assignable": False},
]

_BY_ID = {m["id"]: m for m in MODULES}


def spec(module_id):
    """Metadata for one module id, or None."""
    return _BY_ID.get(str(module_id or "").strip())


def ids():
    return [m["id"] for m in MODULES]


def module_data_dir(ws, module_id, create=True):
    """<ws>/.nova/modules/<id>/ - every module keeps its outputs here."""
    from pathlib import Path
    p = Path(ws) / ".nova" / "modules" / str(module_id)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def module_status(ws, module_id):
    """Cheap health/summary for the web UI: file counts per module."""
    from pathlib import Path
    d = module_data_dir(ws, module_id, create=False)
    if not d.is_dir():
        return {"files": 0, "bytes": 0}
    files = 0
    total = 0
    try:
        for f in d.rglob("*"):
            if f.is_file():
                files += 1
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return {"files": files, "bytes": total}


class ModuleError(Exception):
    """A clean, user-readable module failure (bad config, dead engine,
    unsupported format...). Never a raw traceback."""
