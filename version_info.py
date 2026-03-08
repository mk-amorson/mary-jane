"""Generate PyInstaller version info file from version.py."""

from version import __version__

parts = [int(x) for x in __version__.split(".")]
while len(parts) < 4:
    parts.append(0)
v = tuple(parts[:4])

VERSION_INFO = f"""
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v},
    prodvers={v},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'MJ Port'),
            StringStruct('FileDescription', 'Mary Jane - Majestic Multiplayer Helper'),
            StringStruct('FileVersion', '{__version__}'),
            StringStruct('InternalName', 'MaryJane'),
            StringStruct('OriginalFilename', 'Mary Jane.exe'),
            StringStruct('ProductName', 'Mary Jane'),
            StringStruct('ProductVersion', '{__version__}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

if __name__ == "__main__":
    with open("version_info.txt", "w") as f:
        f.write(VERSION_INFO.strip())
    print(f"Generated version_info.txt for v{__version__}")
