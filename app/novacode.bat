@echo off
REM Nova Assistant - legacy alias launcher (same as nova.bat)
REM EnableDelayedExpansion: %errorlevel% INSIDE the parenthesized block
REM below would expand at parse time and wrongly re-run the 'py' branch.
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Nova Assistant - local AI assistant (Nova Code module)
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

REM v6.5: this alias promised to be "the same as nova.bat" but silently
REM lacked the module routing - 'novacode.bat voice ...' reached nova.py,
REM which treated 'voice' as a positional WORKSPACE (junk directory).
REM Routing + quoted-argument handling now match nova.bat exactly.
set "FIRST=%~1"
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
