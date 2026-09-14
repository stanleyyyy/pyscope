; ===========================================================================
; Inno Setup script for pyscope
; Produces a single, shareable Setup exe:  installer\Output\pyscope-Setup.exe
;
; Build:  iscc installer\pyscope.iss           (or installer\build_installer.bat)
;         iscc /DAppVersion=0.3.0 ...          to stamp a version (CI does this)
;
; Bundles the PyInstaller output (dist\pyscope\), so target machines need
; NOTHING else - no Python. Installs per-user (no admin prompt), puts the
; console launcher on the user's PATH, and creates Start Menu + optional
; Desktop shortcuts.
; ===========================================================================

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName    "pyscope"
#define AppExe     "pyscope.exe"
#define CliExe     "pyscope-cli.exe"

[Setup]
AppId={{3F6A2E0D-7B41-4C8E-9A2F-5D1E8C4B7A90}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Stanislav Ruzani
AppPublisherURL=https://github.com/stanleyyyy/pyscope
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install -> no UAC prompt; change to "admin" to install for all users.
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=pyscope-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\pyscope\assets\pyscope.ico
UninstallDisplayIcon={app}\{#AppExe}
; The bundle is one-directory; remove the whole thing on uninstall.
UninstallFilesDir={app}\uninstall
ChangesEnvironment=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "addtopath";   Description: "Add pyscope-cli to the user &PATH (for --list-devices etc.)"; GroupDescription: "Command line:"

[Files]
; The PyInstaller bundle (built by build.bat -> dist\pyscope\).
Source: "..\dist\pyscope\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Docs.
Source: "..\README.md";      DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";               Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\{#AppName} (simulator)";   Filename: "{app}\{#AppExe}"; Parameters: "--simulate"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}";     Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";         Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Append {app} to the user's PATH so `pyscope-cli` works from any prompt.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath('{app}')

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  { Look for the path with leading and trailing semicolon, case-insensitively. }
  Result := Pos(';' + Lowercase(Param) + ';', ';' + Lowercase(OrigPath) + ';') = 0;
end;
