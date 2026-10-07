# PyInstaller spec for ShadowSnip.
#
#   pip install pyinstaller
#   python make_icon.py        # writes shadowsnip.ico
#   pyinstaller ShadowSnip.spec
#
# Produces dist\ShadowSnip.exe on Windows and dist/ShadowSnip on Linux: one
# file, no console, no Python needed. PyInstaller builds for the system it
# runs on, so each platform's build is made on that platform (the GitHub
# workflow in .github/workflows/build.yml does both).

import sys

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Trim the bundle: pull in nothing from the scientific stack that
        # Pillow can drag along but ShadowSnip never touches.
        "numpy", "scipy", "matplotlib", "tkinter", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtWebEngineCore",
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ShadowSnip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # no PowerShell window
    # Windows embeds the icon in the .exe. Linux executables carry no icon;
    # install.sh points the launcher entry at shadowsnip.png instead.
    icon="shadowsnip.ico" if sys.platform == "win32" else None,
)
