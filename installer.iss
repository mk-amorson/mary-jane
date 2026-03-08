#define MyAppName "Mary Jane"
#define MyAppExeName "Mary Jane.exe"
#define MyAppPublisher "MJ Port"

; Read version from version.py at compile time
#define VersionFile FileOpen(SourcePath + "\version.py")
#define VersionLine FileRead(VersionFile)
#define MyAppVersion Copy(VersionLine, Pos('"', VersionLine) + 1, RPos('"', VersionLine) - Pos('"', VersionLine) - 1)
#expr FileClose(VersionFile)

[Setup]
AppId={{B3F45DC0-983C-4A6B-98AF-ED3F45DC983C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=Mary Jane Setup {#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=assets\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Main application
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Tesseract OCR
Source: "dist\tesseract\tesseract.exe"; DestDir: "{app}\tesseract"; Flags: ignoreversion
Source: "dist\tesseract\*.dll"; DestDir: "{app}\tesseract"; Flags: ignoreversion
Source: "dist\tesseract\tessdata\eng.traineddata"; DestDir: "{app}\tesseract\tessdata"; Flags: ignoreversion
Source: "dist\tesseract\tessdata\rus.traineddata"; DestDir: "{app}\tesseract\tessdata"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\update.bat"
Type: dirifempty; Name: "{app}"
