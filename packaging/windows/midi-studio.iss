; MIDI Studio - Windows installer (Inno Setup 6).  v22ze-195
; Built by .github/workflows/windows.yml; installs for the current user only
; (no administrator password) and can add a desktop icon.
#ifndef MyAppVersion
  #define MyAppVersion "0.0"
#endif

[Setup]
AppId={{7C1D8E52-4B0A-4F7E-9A3B-5E2F6D1C9A10}
AppName=MIDI Studio
AppVersion={#MyAppVersion}
AppPublisher=MIDI Studio (open source, MIT licence)
AppPublisherURL=https://github.com/winthrom/midi-studio
DefaultDirName={autopf}\MIDI Studio
DefaultGroupName=MIDI Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=midi-studio.ico
UninstallDisplayIcon={app}\MIDI-Studio.exe
OutputBaseFilename=MIDI-Studio-Setup

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Icons:"

[Files]
Source: "..\..\dist\windows\MIDI-Studio\*"; DestDir: "{app}"; Excludes: "MIDI-Studio-selftest.exe"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\docs\MIDI-Studio-User-Guide.pdf"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MIDI Studio"; Filename: "{app}\MIDI-Studio.exe"
Name: "{group}\MIDI Studio User Guide"; Filename: "{app}\MIDI-Studio-User-Guide.pdf"
Name: "{group}\Uninstall MIDI Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MIDI Studio"; Filename: "{app}\MIDI-Studio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MIDI-Studio.exe"; Description: "Start MIDI Studio now"; Flags: nowait postinstall skipifsilent
