@echo off
REM Nova Assistant - launcher (starts the local AI assistant).
REM 'novacode.bat' remains as an alias for the same program.
REM EnableDelayedExpansion: %errorlevel% INSIDE the parenthesized block
REM below would expand at parse time and wrongly re-run the 'py' branch.
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Nova Assistant - local AI assistant
cd /d "%~dp0"

set "Pycmd="
where py >nul 2>&1
if !errorlevel! equ 0 set "Pycmd=py"
if not defined Pycmd (
    where python >nul 2>&1
    if !errorlevel! equ 0 set "Pycmd=python"
)
if not defined Pycmd (
    echo [!] Python 3 is required. Install from https://www.python.org/downloads/
    echo     and check "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

REM v6.5 fix: a quoted first argument ("build my project") used to expand
REM inside the if-comparisons as ""build my project"" - the embedded spaces
REM made cmd abort with a syntax error before Python ever started.
REM %~1 strips the surrounding quotes; the delayed-expansion !FIRST! keeps
REM the comparison a single token.
set "FIRST=%~1"

REM v6.0: module subcommands route to the module CLI
REM v6.5: 'serve' was missing here - it reached nova.py, which treated it
REM as a positional WORKSPACE (junk ./serve directory + terminal REPL
REM instead of the web dashboard).
if /i "!FIRST!"=="voice" goto module
if /i "!FIRST!"=="stt" goto module
if /i "!FIRST!"=="photo" goto module
if /i "!FIRST!"=="pixel" goto module
if /i "!FIRST!"=="flow" goto module
if /i "!FIRST!"=="knowledge" goto module
if /i "!FIRST!"=="models" goto module
if /i "!FIRST!"=="platforms" goto module
if /i "!FIRST!"=="assign" goto module
if /i "!FIRST!"=="serve" goto module
"%Pycmd%" nova.py %*
goto end
:module
"%Pycmd%" nova_assistant.py %*
goto end
:end
pause
