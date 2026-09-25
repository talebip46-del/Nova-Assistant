@echo off
REM =====================================================================
REM  Nova Assistant Installer for Windows (v6.0)
REM  Requires: Ollama for Windows + Python 3 (both free).
REM  v6.0: multi-module (Voice/Photo/Pixel/Flow/Knowledge). Nova runs on
REM  ANY model in the local Ollama library, AND on
REM  .gguf model files placed in a models folder (~/.nova/models or
REM  NOVA_MODELS_DIR). This script just makes sure at least one Ollama
REM  model exists. Nova auto-discovers both sources.
REM  EnableDelayedExpansion: %errorlevel% / %BASE% INSIDE parenthesized
REM  blocks would expand at PARSE time (before the command even runs).
REM =====================================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Nova Assistant Installer
echo.
echo   Nova Assistant Installer - local AI assistant for Ollama
echo   Nova Code module: builds real projects (websites, tools, games)
echo.

REM ---- 1) Ollama ----
where ollama >nul 2>&1
if !errorlevel! neq 0 (
    color 0C
    echo [ERROR] Ollama not found on this system.
    echo.
    echo Please download and install Ollama for Windows first:
    echo     https://ollama.com/download
    echo.
    echo After installing Ollama, run this script again.
    pause
    exit /b 1
)
echo [OK] Ollama found.

REM ---- 2) Python ----
set "Pycmd="
where py >nul 2>&1
if !errorlevel! equ 0 set "Pycmd=py"
if not defined Pycmd (
    where python >nul 2>&1
    if !errorlevel! equ 0 set "Pycmd=python"
)
if not defined Pycmd (
    color 0E
    echo [WARN] Python 3 not found - the Nova Assistant agent needs it.
    echo        Install from https://www.python.org/downloads/
    echo        and check "Add python.exe to PATH" during setup.
    echo.
    echo Installer continues - but install Python before using novacode.bat
)

REM ---- 3) Local models ----
echo.
echo [3/3] Checking your local Ollama models...
set "MODEL_COUNT=0"
for /f "skip=1 delims=" %%l in ('ollama list 2^>nul') do set /a MODEL_COUNT+=1

REM explicit override:  install.bat <model>  - make sure it is there.
REM Quoted use of %~1: an unquoted arg would let & ^ or | execute.
if not "%~1"=="" (
    set "BASE=%~1"
    echo [*] Pulling !BASE! ^(explicitly requested^) ...
    ollama pull "!BASE!"
    if errorlevel 1 (
        color 0C
        echo [ERROR] Pulling !BASE! failed - check the name and your connection.
        pause
        exit /b 1
    )
    echo [OK] !BASE! is ready!
    goto model_done
)

if !MODEL_COUNT! gtr 0 (
    echo [OK] !MODEL_COUNT! model^(s^) already installed:
    ollama list
    echo.
    echo Nova auto-picks a good coding model at startup.
    echo Switch any time inside the agent:  /model
    echo ^(or set NOVA_MODEL=^<name^> before starting^)
) else (
    set "BASE=qwen2.5-coder:3b"
    set "BASE_INFO=Qwen2.5-Coder 3B, ~1.9 GB download, ~2.5 GB RAM while running"
    set RAM_GB=0
    for /f %%a in ('powershell -NoProfile -command "[int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)" 2^>nul') do set RAM_GB=%%a
    if !RAM_GB! gtr 0 if !RAM_GB! leq 5 (
        set "BASE=qwen2.5-coder:1.5b"
        set "BASE_INFO=Qwen2.5-Coder 1.5B ^(light^), ~1.0 GB download, ~1.4 GB RAM while running"
    )
    echo.
    echo Model to pull : !BASE!  ^(!BASE_INFO!^)
    echo On very weak hardware the FIRST answer can take several minutes - this is
    echo normal. Nova never cuts a slow answer off.
    echo.
    echo [*] Pulling !BASE! ...
    echo     ^(no time limit - a slow connection just takes longer; an interrupted
    echo      download resumes where it stopped^)
    ollama pull "!BASE!"
    if errorlevel 1 (
        color 0C
        echo [ERROR] Pulling !BASE! failed - check your connection and re-run.
        pause
        exit /b 1
    )
    echo [OK] !BASE! is ready!
)
:model_done

REM ---- 4) Done ----
echo.
echo ==============================================
echo   Nova Assistant installed successfully!
echo ==============================================
echo.
echo   Start coding    : nova.bat               (terminal assistant)
echo   Web agent       : nova.bat --web         (same agent, in the browser)
echo   Old launcher    : novacode.bat           (still works - same program)
echo   Model picker    : /model                 (Ollama models + your .gguf files)
echo   Model files     : drop .gguf into %USERPROFILE%\.nova\models (or NOVA_MODELS_DIR)
echo   Other brains    : /provider openai ^| openrouter ^| groq ^| deepseek ^| anthropic ^| gemini ^| custom
echo   Inside agent    : type /help for all commands
echo   Build a website : describe it, then /serve to preview
echo   Slow machine    : long answers are normal; a [waiting] timer shows progress
echo   Tuning          : NOVA_MODEL / NOVA_TIMEOUT / NOVA_RUN_TIMEOUT / NOVA_NUM_CTX / NOVA_KEEP_ALIVE
echo   Free RAM later  : ollama stop ^<model-name^>
echo   Full guide      : see README.md (section: weak laptop)
echo.
pause
