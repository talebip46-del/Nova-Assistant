# =====================================================================
#  NovaAssistant.spec - PyInstaller build for Nova Assistant (v6.2)
#
#  Produces ONE dist folder (dist/NovaAssistant/) containing:
#    NovaAssistant.exe   windowed (no console). Double-click -> the web
#                        dashboard starts on 127.0.0.1 and opens in the
#                        browser. Any CLI args behave like
#                        `nova_assistant.py <args>`.
#    novacode.exe        console build (novacode_entry.py) - the classic
#                        terminal agent (`novacode.exe`), the web server
#                        (`novacode.exe serve` - routed to nova_assistant,
#                        v6.7: 'serve' used to be mistaken for a workspace
#                        by nova.py's no-subcommand parser), --list-models
#                        and the module CLI (voice/photo/flow/...).
#    web/index.html      the whole web face, bundled as data.
#
#  Build (on Windows, from this folder):
#      pip install pyinstaller
#      pyinstaller NovaAssistant.spec --noconfirm
#
#  Notes:
#  - onedir (not onefile) on purpose: instant start, no temp-extraction,
#    and the user can drop model files into local/ right next to the exe
#    (nova_localmodels.own_models_root() anchors there when frozen).
#  - the child-process windows that Windows would otherwise flash for
#    every background command are already suppressed in code via
#    CREATE_NO_WINDOW (nova.py / nova_bg.py / nova_localmodels.py).
#  - the web/ data is looked up bundled first, then NEXT TO THE EXE
#    (web_server._resolve_web_dir), so the UI can be updated by swapping
#    that folder without a rebuild.
# =====================================================================
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ICON = SPEC_DIR / "build_assets" / "NovaAssistant.ico"
ICON_ARG = str(ICON) if ICON.is_file() else None

block_cipher = None


def _a(script):
    return Analysis(
        [str(SPEC_DIR / script)],
        pathex=[str(SPEC_DIR)],
        binaries=[],
        datas=[(str(SPEC_DIR / "web"), "web"),
               (str(SPEC_DIR / "fonts"), "fonts")],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=["tkinter", "unittest", "pydoc_data"],
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )


a_main = _a("exe_entry.py")
a_cli = _a("novacode_entry.py")

pyz_main = PYZ(a_main.pure, a_main.zipped_data, cipher=block_cipher)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)

exe_main = EXE(
    pyz_main,
    a_main.binaries,
    a_main.zipfiles,
    a_main.datas,
    name="NovaAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed: the dashboard IS the interface
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_ARG,
)

exe_cli = EXE(
    pyz_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    name="novacode",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # console: terminal agent needs a real REPL
    icon=ICON_ARG,
)

coll = COLLECT(
    exe_main,
    a_main.binaries,
    a_main.zipfiles,
    a_main.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NovaAssistant",
)
