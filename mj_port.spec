# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None
ROOT = os.path.dirname(os.path.abspath(SPEC))

import importlib.util
_vgamepad_spec = importlib.util.find_spec('vgamepad')
_vgamepad_dir = os.path.dirname(_vgamepad_spec.origin) if _vgamepad_spec else None

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'assets', 'fonts'), os.path.join('assets', 'fonts')),
        (os.path.join(ROOT, 'assets', 'icons'), os.path.join('assets', 'icons')),
        (os.path.join(ROOT, 'assets', 'sounds'), os.path.join('assets', 'sounds')),
        (os.path.join(ROOT, 'assets', 'reference'), os.path.join('assets', 'reference')),
    ] + ([
        (os.path.join(_vgamepad_dir, 'win', 'vigem', 'client'), os.path.join('vgamepad', 'win', 'vigem', 'client')),
        (os.path.join(_vgamepad_dir, 'win', 'vigem', 'install'), os.path.join('vgamepad', 'win', 'vigem', 'install')),
    ] if _vgamepad_dir else []),
    hiddenimports=[
        'PyQt5.QtMultimedia',
        'PyQt5.QtNetwork',
        'PyQt5.QtSvg',
        'cv2',
        'numpy',
        'pytesseract',
        'windows_capture',
        'PIL',
        'aiohttp',
        'win32gui',
        'win32api',
        'win32con',
        'pymem',
        'vgamepad',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Mary Jane',
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
    icon=os.path.join(ROOT, 'assets', 'icons', 'app.ico'),
    version=os.path.join(ROOT, 'version_info.txt'),
)
