# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the loushang CLI binary (committed build config).
#
# The loushang package resolves several public surfaces through
# importlib.import_module() with string module paths (loushang.harness,
# loushang.harness.events, loushang.harness.session,
# loushang.harness.transcript, loushang.harness.resources.packages,
# loushang.work). Static analysis cannot see those imports, so every
# loushang.* submodule is included explicitly via collect_submodules().
# Platform-conditional stdlib imports (fcntl/termios/tty/msvcrt) are listed
# as well.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
datas += collect_data_files('loushang')

hiddenimports = collect_submodules('loushang')
hiddenimports += [
    # ---- platform-conditional stdlib imports ----
    'fcntl',
    'termios',
    'tty',
    'msvcrt',
]

a = Analysis(
    ['src/loushang/coding/cli/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='loushang',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
