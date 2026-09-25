#!/usr/bin/env bash
# =====================================================================
#  Nova Assistant Installer (v6.0) — Linux / macOS
#  v6.0 adds the module layer: Nova Voice / Photo / PixelArt / Flow /
#  Knowledge + per-module brains + OpenAI-compatible platform discovery.
#  Installs Ollama + Python, then makes sure you have at least ONE
#  local brain: either a model pulled into Ollama OR a .gguf model
#  file in your models folder (Nova discovers both automatically and
#  picks a good default; switch any time with /model inside the agent).
#  Explicit override:  ./install.sh qwen2.5-coder:1.5b   (or :7b)
#  All installer output is English.
# =====================================================================
set -euo pipefail

BOLD="\033[1m"; PURPLE="\033[35m"; CYAN="\033[36m"; GREEN="\033[32m"
YELLOW="\033[33m"; RED="\033[31m"; DIM="\033[2m"; NC="\033[0m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${PURPLE}${BOLD}"
cat <<'BANNER'
      _  _  _                _  _  _
     (_)(_)(_) _  _  _      (_)(_)(_) _  _  _
     _  _  _ (_)(_)(_) _   _  _  _ (_)(_)(_) _
    (_)(_)(_)(_)_  _  _(_) (_)(_)(_)(_)_  _  (_)
       _  _  _ (_)(_)(_)       _  _  _ (_)(_)(_) _
      (_)(_)(_)_  _  (_)      (_)(_)(_)_  _  (_)
         _  _ (_)  (_)           _  _ (_)  (_)
        (_)(_) (_) (_)          (_)(_) (_) (_)

      Nova Assistant  -  your local AI assistant
      Nova Code module: builds real projects (websites, tools, games)
BANNER
echo -e "${NC}"

# ---------------------------------------------------------- 1) Ollama
echo -e "${CYAN}${BOLD}[1/3] Checking Ollama...${NC}"
if command -v ollama >/dev/null 2>&1; then
    echo -e "${GREEN}Ollama is installed: $(ollama --version 2>/dev/null || echo 'ok')${NC}"
else
    echo -e "${YELLOW}Ollama not found. Installing...${NC}"
    case "$(uname)" in
        Linux)
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL https://ollama.com/install.sh | sh
            elif command -v wget >/dev/null 2>&1; then
                wget -qO- https://ollama.com/install.sh | sh
            else
                echo -e "${RED}Neither curl nor wget found.${NC} Install Ollama manually from https://ollama.com/download then re-run."
                exit 1
            fi
            ;;
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                brew install ollama
            else
                echo -e "${RED}Homebrew not found.${NC} Install Ollama from https://ollama.com/download then re-run."
                exit 1
            fi
            ;;
        *)
            echo -e "${RED}Unsupported OS for auto-install. On Windows use install.bat${NC}"
            exit 1
            ;;
    esac
    echo -e "${GREEN}Ollama installed successfully.${NC}"
fi

# ---------------------------------------------------------- 2) Python
echo -e "${CYAN}${BOLD}[2/3] Checking Python 3 (needed by nova.py)...${NC}"
PY="$(command -v python3 || true)"
if [ -z "${PY}" ]; then
    # a bare 'python' is acceptable ONLY if it really is Python 3
    # (on some systems it is still Python 2 - nova.py would not run)
    if command -v python >/dev/null 2>&1 \
            && python -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' >/dev/null 2>&1; then
        PY="$(command -v python)"
    fi
fi
if [ -n "${PY}" ]; then
    echo -e "${GREEN}Python found: ${PY} ($("${PY}" --version 2>&1))${NC}"
else
    echo -e "${RED}[!] Python 3 not found. The Nova Assistant agent needs it.${NC}"
    echo "    Ubuntu/Debian :  sudo apt install python3"
    echo "    Fedora        :  sudo dnf install python3"
    echo "    macOS         :  xcode-select --install   (or brew install python)"
    echo -e "${YELLOW}Installer continues - but install Python before using ./novacode${NC}"
fi

# ---------------------------------------------------------- 3) Local models
# v5.1: NO custom model is built any more. Nova runs on ANY model in
# the local Ollama library - it just has to be non-empty.
echo -e "${CYAN}${BOLD}[3/3] Checking your local Ollama models...${NC}"

MODELS="$(ollama list 2>/dev/null | tail -n +2 || true)"

if [ -n "${1:-}" ]; then
    # explicit override:  ./install.sh <model>  -> make sure it is there
    BASE="$1"
    echo -e "${DIM}Pulling ${BASE} (explicitly requested) ...${NC}"
    if ! ollama pull "${BASE}"; then
        echo -e "${RED}[!] pulling ${BASE} failed - check the name and your connection.${NC}"
        exit 1
    fi
    echo -e "${GREEN}${BASE} is ready!${NC}"
elif [ -n "${MODELS}" ]; then
    echo -e "${GREEN}Models already installed:${NC}"
    ollama list
    echo -e "${DIM}Nova auto-picks a good coding model at startup;${NC}"
    echo -e "${DIM}switch any time inside the agent:  /model   (or: NOVA_MODEL=<name>)${NC}"
else
    BASE="qwen2.5-coder:3b"
    BASE_INFO="Qwen2.5-Coder 3B, ~1.9 GB download, ~2.5 GB RAM while running"
    RAM_GB=0
    if [ -r /proc/meminfo ]; then
        RAM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
        # guard against empty/non-numeric awk output (an arithmetic error
        # here would kill the whole script under set -e)
        case "${RAM_KB}" in ''|*[!0-9]*) RAM_KB=0 ;; esac
        RAM_GB=$((RAM_KB / 1024 / 1024))
    elif command -v sysctl >/dev/null 2>&1; then
        RAM_B=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
        case "${RAM_B}" in ''|*[!0-9]*) RAM_B=0 ;; esac
        RAM_GB=$((RAM_B / 1024 / 1024 / 1024))
    fi
    if [ "${RAM_GB}" -gt 0 ] && [ "${RAM_GB}" -le 5 ] && [ -t 0 ]; then
        echo -e "${YELLOW}This machine has about ${RAM_GB} GB RAM.${NC}"
        LIGHT=""
        # only ask when a terminal is attached: under `curl | bash` the
        # read would swallow the NEXT LINE OF THE PIPED SCRIPT
        read -r -p "Pull the lighter 1.5B model instead (faster on weak hardware, ~1.0 GB download)? [y/N]: " LIGHT || LIGHT=""
        if [[ "${LIGHT}" =~ ^[Yy]$ ]]; then
            BASE="qwen2.5-coder:1.5b"
            BASE_INFO="Qwen2.5-Coder 1.5B (light), ~1.0 GB download, ~1.4 GB RAM while running"
        fi
    elif [ "${RAM_GB}" -gt 0 ] && [ "${RAM_GB}" -le 5 ]; then
        BASE="qwen2.5-coder:1.5b"
        BASE_INFO="Qwen2.5-Coder 1.5B (light), ~1.0 GB download, ~1.4 GB RAM while running"
    fi
    echo ""
    echo -e "  Model to pull: ${BOLD}${BASE}${NC}  (${BASE_INFO})"
    echo -e "  ${DIM}On very weak hardware the FIRST answer can take several minutes -${NC}"
    echo -e "  ${DIM}this is normal. Nova never cuts a slow answer off.${NC}"
    echo ""
    echo -e "${DIM}Pulling ${BASE} ... (no time limit - an interrupted download resumes)${NC}"
    if ! ollama pull "${BASE}"; then
        echo -e "${RED}[!] pulling ${BASE} failed - check your connection and re-run.${NC}"
        exit 1
    fi
    echo -e "${GREEN}${BASE} is ready!${NC}"
fi

chmod +x "${SCRIPT_DIR}/novacode" 2>/dev/null || true
chmod +x "${SCRIPT_DIR}/nova" 2>/dev/null || true

# optional smoke test with whichever model is now installed
FIRST_MODEL="$(ollama list 2>/dev/null | tail -n +2 | head -n1 | awk '{print $1}' || true)"
if [ -n "${FIRST_MODEL}" ] && [ -t 0 ]; then
    RUN_TEST=""
    read -r -p "Run a quick test now with ${FIRST_MODEL}? On weak hardware it can take several minutes [Y/n]: " RUN_TEST || RUN_TEST=""
    RUN_TEST="${RUN_TEST:-Y}"
    if [[ "${RUN_TEST}" =~ ^[Yy]$ ]]; then
        ollama run "${FIRST_MODEL}" "Reply with exactly: Nova Assistant is ready." || true
    fi
fi

echo ""
echo -e "${GREEN}${BOLD}================================================${NC}"
echo -e "${GREEN}${BOLD}  Nova Assistant installed successfully!${NC}"
echo -e "${GREEN}${BOLD}================================================${NC}"
echo ""
echo -e "  ${BOLD}Start coding:${NC}   ./nova               (terminal assistant)"
echo -e "  ${BOLD}Web agent:${NC}      ./nova --web         (same agent, in the browser)"
echo -e "  ${BOLD}Old launcher:${NC}   ./novacode           (still works - same program)"
echo -e "  ${BOLD}Model picker:${NC}   /model               (Ollama models + your .gguf files)"
echo -e "  ${BOLD}Model files:${NC}    drop .gguf files into ~/.nova/models (or set NOVA_MODELS_DIR)"
echo -e "  ${BOLD}Other brains:${NC}   /provider openai | openrouter | groq | deepseek | anthropic | gemini | custom"
echo -e "  ${BOLD}Inside agent:${NC}   type /help for all commands"
echo -e "  ${BOLD}Build a website:${NC} describe it, then /serve to preview"
echo -e "  ${BOLD}Slow machine:${NC}   long answers are normal; a [waiting] timer shows progress"
echo -e "  ${BOLD}Tuning:${NC}         NOVA_MODEL / NOVA_TIMEOUT / NOVA_RUN_TIMEOUT / NOVA_NUM_CTX / NOVA_KEEP_ALIVE"
echo -e "  ${BOLD}Free RAM later:${NC}  ollama stop <model-name>"
echo -e "  ${BOLD}Full guide:${NC}      README.md (section: weak laptop)"
echo ""
