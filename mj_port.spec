# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None
ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'fonts'), 'fonts'),
        (os.path.join(ROOT, 'icons'), 'icons'),
        (os.path.join(ROOT, 'sounds'), 'sounds'),
        (os.path.join(ROOT, 'reference'), 'reference'),
    ],
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Exclude server/ code from bundle
a.pure = [x for x in a.pure if not x[0].startswith('server')]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MJPort',
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
    icon=None,
)
