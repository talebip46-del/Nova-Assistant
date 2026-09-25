#!/usr/bin/env python3
# =====================================================================
#  Nova Code - hardware detection & local-model guidance (v6.8)
#
#  Answers "can THIS machine run THIS model well?" with ZERO network
#  calls and ZERO dependencies:
#
#    detect()    RAM / cores / GPU (nvidia-smi, rocm-smi) / OS / arch
#    suggest()   best model size + quantization + num_ctx for the box
#    speculative() honest speculative-decoding support check: Ollama
#                does not expose a draft model today; llama.cpp's
#                llama-server does - we produce the exact launch flags.
#    report()    one human text block for /hw and the setup wizard
#
#  Fail-soft everywhere: an unreadable /proc or a missing nvidia-smi
#  degrades that single field, never the module.
# =====================================================================
import ctypes
import os
import platform
import re
import shutil
import subprocess

GIANT_DIV = 1024 ** 3


# --------------------------------------------------------------- RAM
def _ram_bytes_linux():
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb * 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        if page > 0 and pages > 0:
            return page * pages
    except (ValueError, OSError, AttributeError):
        pass
    return None


def _ram_bytes_windows():
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys)
    except Exception:
        pass
    return None


def _ram_bytes_darwin():
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                             capture_output=True, timeout=3, text=True)
        return int(out.stdout.strip())
    except Exception:
        return None


def ram_bytes():
    """Total physical RAM in bytes, or None when undetectable."""
    if os.name == "nt":
        return _ram_bytes_windows()
    if platform.system() == "Darwin":
        return _ram_bytes_darwin()
    return _ram_bytes_linux()


# --------------------------------------------------------------- GPU
def _nvidia_gpus():
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=4, text=True)
        gpus = []
        for line in out.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[0]:
                try:
                    vram_mb = int(float(parts[1]))
                except ValueError:
                    vram_mb = 0
                gpus.append({"name": parts[0][:80], "vram_gb": round(vram_mb / 1024, 1)})
        return gpus
    except Exception:
        return []


def _rocm_gpus():
    if not shutil.which("rocm-smi"):
        return []
    try:
        out = subprocess.run(["rocm-smi", "--showproductname"],
                             capture_output=True, timeout=4, text=True)
        names = []
        for m in re.finditer(r"Card series:\s*(.+)", out.stdout or ""):
            names.append({"name": m.group(1).strip()[:80], "vram_gb": 0.0})
        return names
    except Exception:
        return []


def gpus():
    return _nvidia_gpus() or _rocm_gpus()


# --------------------------------------------------------------- detect
def detect():
    """One snapshot dict: ram_gb, cores, gpus, os, arch, machine."""
    rb = ram_bytes()
    return {
        "ram_gb": round(rb / GIANT_DIV, 1) if rb else None,
        "cores": os.cpu_count(),
        "gpus": gpus(),
        "os": platform.system() or os.name,
        "machine": platform.machine() or "?",
        "python": platform.python_version(),
    }


# --------------------------------------------------------------- guidance
def suggest(hw=None):
    """Model tier + quantization + num_ctx advice for this machine.
    Honest rules of thumb (GGUF Q4_K_M sizes, ~0.55 GB/B params):
    weights should fit in ~60% of RAM without a GPU, or ~85% of the
    largest VRAM with one."""
    hw = hw or detect()
    ram = hw.get("ram_gb") or 0
    vram = max([g.get("vram_gb") or 0 for g in hw.get("gpus", [])] or [0])
    budget = ram * 0.60
    if vram >= 4:
        budget = max(budget, vram * 0.85)
    if budget <= 3:
        tier, quant, note = "0.5B-1.5B", "Q4_K_M", "very small RAM - expect slow, tiny models only"
    elif budget <= 6:
        tier, quant, note = "3B", "Q4_K_M", "entry level - great for chat, basic edits"
    elif budget <= 12:
        tier, quant, note = "7B-8B", "Q4_K_M", "the sweet spot for coding helpers"
    elif budget <= 24:
        tier, quant, note = "13B-14B", "Q4_K_M", "solid reasoning on CPU+GPU boxes"
    elif budget <= 48:
        tier, quant, note = "32B", "Q4_K_M", "near-API quality, needs patience on CPU"
    else:
        tier, quant, note = "70B+", "Q4_K_M", "workstation class"
    num_ctx = 2048 if (not ram or ram < 8) else 4096
    if vram >= 12 and (ram or 0) >= 16:
        num_ctx = 8192
    return {"params": tier, "quant": quant, "num_ctx": num_ctx,
            "note": note, "budget_gb": round(budget, 1)}


def speculative(hw=None, server_exe=None, draft_model=None):
    """Speculative decoding support check. Ollama: NOT exposed (as of
    2025 API). llama.cpp llama-server: yes (-md draft.gguf --draft N).
    vLLM: yes (speculative_config). We return a dict with a copy-paste
    recipe when a llama-server binary exists."""
    hw = hw or detect()
    llama_server = server_exe or _find_llama_server()
    ollama_path = shutil.which("ollama")
    if llama_server:
        d = draft_model or "<draft-model.gguf>"
        cmd = (f'"{llama_server}" -m <main-model.gguf> '
               f'-md "{d}" --draft 16 --draft-min 4 -c 4096 --port 8080')
        return {"supported": True, "engine": "llama.cpp",
                "recipe": cmd,
                "note": "draft model 0.5B of the SAME family works best; "
                        "2-3x faster on CPU for greedy-ish decoding"}
    return {"supported": False, "engine": "ollama" if ollama_path else None,
            "recipe": None,
            "note": "Ollama does not expose speculative decoding yet - "
                    "run the GGUF through llama.cpp's llama-server to get it"}


def _find_llama_server():
    """Same discovery rule as nova_localmodels: NOVA_LLAMA_SERVER env,
    then PATH."""
    env = os.environ.get("NOVA_LLAMA_SERVER", "").strip()
    if env and os.path.isfile(env):
        return env
    for name in ("llama-server", "llama-server.exe"):
        p = shutil.which(name)
        if p:
            return p
    return None


# --------------------------------------------------------------- report
def report(hw=None, sg=None):
    """Compact human-readable block for /hw + the setup wizard."""
    hw = hw or detect()
    sg = sg or suggest(hw)
    lines = []
    ram = f"{hw['ram_gb']} GB" if hw.get("ram_gb") else "unknown"
    lines.append(f"  RAM:        {ram}")
    lines.append(f"  CPU cores:  {hw.get('cores') or '?'}  ({hw.get('os') or '?'} {hw.get('machine', '')})")
    if hw.get("gpus"):
        for g in hw["gpus"]:
            vram = f", {g['vram_gb']} GB VRAM" if g.get("vram_gb") else ""
            lines.append(f"  GPU:        {g['name']}{vram}")
    else:
        lines.append("  GPU:        none detected (CPU-only inference)")
    lines.append(f"  Suggested:  {sg['params']} model, {sg['quant']}, "
                 f"num_ctx {sg['num_ctx']}  - {sg['note']}")
    return "\n".join(lines)
