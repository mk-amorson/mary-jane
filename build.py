"""Build script: PyInstaller .exe + copy Tesseract + Inno Setup installer."""

import os
import sys
import glob
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
TESS_SRC = r"C:\Program Files\Tesseract-OCR"
TESS_DEST = os.path.join(DIST, "tesseract")

ISCC_PATHS = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def step(msg):
    print(f"\n{'=' * 60}\n  {msg}\n{'=' * 60}")


def run(cmd, **kwargs):
    print(f"  > {cmd}")
    subprocess.check_call(cmd, shell=True, **kwargs)


def find_iscc():
    for p in ISCC_PATHS:
        if os.path.isfile(p):
            return p
    # Try PATH
    try:
        subprocess.check_call("iscc /?" , shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "iscc"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main():
    # 1. Generate version info
    step("Generating version_info.txt")
    run(f'"{sys.executable}" version_info.py', cwd=ROOT)

    # 2. Build .exe with PyInstaller
    step("Building Mary Jane.exe with PyInstaller")
    run(f'"{sys.executable}" -m PyInstaller mj_port.spec --noconfirm', cwd=ROOT)

    exe_path = os.path.join(DIST, "Mary Jane.exe")
    if not os.path.isfile(exe_path):
        print(f"ERROR: {exe_path} not found")
        sys.exit(1)
    size_mb = os.path.getsize(exe_path) / (1024 * 1024)
    print(f"  Mary Jane.exe: {size_mb:.1f} MB")

    # 3. Copy Tesseract
    step("Copying Tesseract OCR")
    if not os.path.isdir(TESS_SRC):
        print(f"ERROR: Tesseract not found at {TESS_SRC}")
        sys.exit(1)

    if os.path.isdir(TESS_DEST):
        shutil.rmtree(TESS_DEST)
    os.makedirs(TESS_DEST, exist_ok=True)

    # tesseract.exe
    shutil.copy2(os.path.join(TESS_SRC, "tesseract.exe"), TESS_DEST)

    # All DLLs
    dll_count = 0
    for dll in glob.glob(os.path.join(TESS_SRC, "*.dll")):
        shutil.copy2(dll, TESS_DEST)
        dll_count += 1
    print(f"  Copied tesseract.exe + {dll_count} DLLs")

    # tessdata (only eng + rus)
    tessdata_dest = os.path.join(TESS_DEST, "tessdata")
    os.makedirs(tessdata_dest, exist_ok=True)
    for lang in ("eng", "rus"):
        src = os.path.join(TESS_SRC, "tessdata", f"{lang}.traineddata")
        if os.path.isfile(src):
            shutil.copy2(src, tessdata_dest)
            print(f"  Copied {lang}.traineddata")
        else:
            print(f"  WARNING: {src} not found")

    tess_size = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fns in os.walk(TESS_DEST)
        for f in fns
    ) / (1024 * 1024)
    print(f"  Tesseract total: {tess_size:.1f} MB")

    # 4. Build installer
    step("Building installer with Inno Setup")
    iscc = find_iscc()
    if iscc is None:
        print("WARNING: Inno Setup (ISCC.exe) not found.")
        print("Install from https://jrsoftware.org/issetup.exe")
        print(f"Skipping installer. Files ready in {DIST}/")
        return

    run(f'"{iscc}" installer.iss', cwd=ROOT)

    # Find output
    from version import __version__
    setup = os.path.join(DIST, f"Mary Jane Setup {__version__}.exe")
    if os.path.isfile(setup):
        setup_mb = os.path.getsize(setup) / (1024 * 1024)
        print(f"\n  Installer: {setup_mb:.1f} MB")
        print(f"  Path: {setup}")
    else:
        print(f"\n  WARNING: Expected {setup} not found, check Inno Setup output")

    step("Done!")


if __name__ == "__main__":
    main()
