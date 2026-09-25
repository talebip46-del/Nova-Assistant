@echo off
REM =====================================================================
REM  build_exe.bat - one-click Windows build of Nova Assistant (v6.2)
REM
REM  What it does:
REM    1. checks Python + PyInstaller (offers to install it)
REM    2. regenerates the app icon (scripts\make_icon.py)
REM    3. builds dist\NovaAssistant\ with:
REM         NovaAssistant.exe   (windowed dashboard, double-click it)
REM         novacode.exe        (console terminal agent)
REM         web\                (the bundled web face)
REM    4. prints where the build landed
REM
REM  Requirements: Python 3.10+ on PATH. PyInstaller is a BUILD-time
REM  tool only - the produced exe still runs the app with zero
REM  dependencies, exactly like the source version.
REM =====================================================================
setlocal
cd /d "%~dp0"

echo.
echo   Nova Assistant - exe build
echo   ==========================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo   [!] Python was not found on PATH. Install Python 3.10+ first.
  goto :fail
)

python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
  echo   [i] PyInstaller is not installed yet - installing...
  python -m pip install --upgrade pyinstaller
  if errorlevel 1 (
    echo   [!] could not install PyInstaller. Check your internet/pip.
    goto :fail
  )
)

echo   [i] generating app icon...
python scripts\make_icon.py
if errorlevel 1 (
  echo   [!] icon generation failed - continuing WITHOUT a custom icon
)

echo   [i] building ^(takes a few minutes on the first run^)...
python -m PyInstaller NovaAssistant.spec --noconfirm --clean
if errorlevel 1 (
  echo   [!] PyInstaller build failed. Read the log above.
  goto :fail
)

echo.
echo   ============================================================
echo   Build OK:  dist\NovaAssistant\NovaAssistant.exe
echo              dist\NovaAssistant\novacode.exe
echo   Tip: drop .gguf models into  local\  next to the exe
echo        ^(local\code, local\voice, local\photo for categories^)
echo   ============================================================
goto :done

:fail
echo.
echo   Build FAILED.
endlocal
exit /b 1

:done
endlocal
exit /b 0
