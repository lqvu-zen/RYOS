# -*- mode: python ; coding: utf-8 -*-
import os

try:
    import tkinterdnd2
    _dnd_path = os.path.dirname(tkinterdnd2.__file__)
    _dnd_datas = [(_dnd_path, 'tkinterdnd2')]
    _dnd_imports = ['tkinterdnd2']
except ImportError:
    _dnd_datas = []
    _dnd_imports = []

a = Analysis(
    ['ryos/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.')] + _dnd_datas,
    hiddenimports=_dnd_imports + [
        'ryos',
        'ryos.__main__',
        'ryos.db',
        'ryos.interpreter',
        'ryos.notifications',
        'ryos.settings',
        'ryos.startup',
        'ryos.ui',
        'ryos.ui.app',
        'ryos.ui.cards',
        'ryos.ui.dialogs',
        'ryos.ui.pipeline',
        'ryos.ui.theme',
        'ryos.ui.widgets',
    ],
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
    name='RYOS',
    icon='icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
