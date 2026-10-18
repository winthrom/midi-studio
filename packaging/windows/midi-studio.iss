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

[Code]
{ v22ze-199: clean up what the PROGRAM downloaded (never a LilyPond the user installed) }
function OurLilyPondDir(): String;
begin
  Result := ExpandConstant('{localappdata}\MIDI-Studio\ly');
end;

function AskRemoveLilyPond(ly: String): Boolean;
begin
  if UninstallSilent() then
    Result := True
  else
    Result := MsgBox('MIDI Studio downloaded its own copy of LilyPond (the program that prints scores) into:'#13#10#13#10 + ly + #13#10#13#10 +
                     'Remove it too?'#13#10#13#10 +
                     'A LilyPond that you installed or unpacked yourself is not touched.',
                     mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ly, cfg: String;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  ly := OurLilyPondDir();
  if DirExists(ly) then
  begin
    if AskRemoveLilyPond(ly) then
    begin
      DelTree(ly, True, True, True);
      RemoveDir(ExpandConstant('{localappdata}\MIDI-Studio'));
    end;
  end;
  cfg := ExpandConstant('{%USERPROFILE}\.midistudio_settings.json');
  if FileExists(cfg) then
  begin
    if not UninstallSilent() then
    begin
      if MsgBox('Also remove your saved MIDI Studio settings?'#13#10#13#10 + cfg + #13#10#13#10 +
                'Choose No if you may install MIDI Studio again.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DeleteFile(cfg);
    end;
  end;
end;
