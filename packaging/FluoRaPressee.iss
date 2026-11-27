; Inno Setup script for FluoRaPressée (work/work_updater.md 方針6/12, Step 4).
;
; Build with:  packaging\build_windows.ps1 -Installer
; which passes /DAppVersion=<PEP 440 version> and /DAppVersionNumeric=<a.b.c.d>.
;
; One installer does both a fresh installation and an in-place update. Saved as
; UTF-8 with a BOM so the Japanese messages below are read correctly.

#ifndef AppVersion
  #error Pass the version with /DAppVersion=... (packaging\build_windows.ps1 does this)
#endif
#ifndef AppVersionNumeric
  #define AppVersionNumeric "0.0.0.0"
#endif

#define AppName "FluoRaPressée"
#define AppExeName "FluoRaPressee.exe"
#define AnalysisExeName "FluoRaPressee-Analysis.exe"
#define DriverExeName "FluoRaPressee-OceanOpticsDriver.exe"
; Must match INSTALLER_MUTEX_PREFIX in src/core/runtime_env.py.
#define MutexPrefix "Global\FluoRaPresseeRunning:"

[Setup]
; NEVER change AppId. A different value makes Windows treat the build as another
; application, which would then be installed a second time next to this one.
AppId={{4ED49E72-6F8E-44EE-9A9D-E895C5F872E4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Hiroki Kobayashi (The University of Tokyo)
AppPublisherURL=https://github.com/khsacc/FluoraPressee
AppSupportURL=https://github.com/khsacc/FluoraPressee/issues
AppUpdatesURL=https://github.com/khsacc/FluoraPressee/releases
VersionInfoVersion={#AppVersionNumeric}
; Per-user installation, no administrator rights. Fixed forever: changing it would
; stop the installer from finding the previous installation.
PrivilegesRequired=lowest
DefaultDirName={autopf}\FluoRaPressee
UsePreviousAppDir=yes
; An update reuses the previous folder without asking.
DisableDirPage=auto
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; A running FluoRaPressée (any of the three executables, in any session) is
; detected and the user is asked to close it. The name depends on the install
; folder, so it is computed in [Code] (RunningMutexName).
AppMutex={code:RunningMutexName}
; Never close the app through the Restart Manager: that could bypass its own exit
; confirmation and stop a measurement or a cooling camera half way.
CloseApplications=no
RestartApplications=no
OutputDir=Output
OutputBaseFilename=FluoRaPressee-Setup-{#AppVersion}
#if FileExists(AddBackslash(SourcePath) + "..\logo\app_icon.ico")
SetupIconFile=..\logo\app_icon.ico
#endif
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
SetupLogging=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
japanese.OceanOpticsTask=Ocean Optics (SeaBreeze) の USB ドライバーをインストールする(管理者権限が必要)
english.OceanOpticsTask=Install the Ocean Optics (SeaBreeze) USB driver (requires administrator rights)
japanese.OceanOpticsGroup=Ocean Optics をお使いの場合:
english.OceanOpticsGroup=For Ocean Optics instruments:
japanese.OceanOpticsShortcut=Ocean Optics ドライバーのインストール
english.OceanOpticsShortcut=Install Ocean Optics driver
japanese.DebugShortcut=FluoRaPressée (デバッグモード)
english.DebugShortcut=FluoRaPressée (Debug mode)
japanese.AnalysisShortcut=FluoRaPressée Analysis
english.AnalysisShortcut=FluoRaPressée Analysis
japanese.AppRunning=FluoRaPressée が実行中です。%n%nすべての FluoRaPressée を閉じてから OK を押してください。中止する場合はキャンセルを押してください。
english.AppRunning=FluoRaPressée is running.%n%nClose every FluoRaPressée window, then click OK to continue, or click Cancel to stop.
japanese.AppRunningAborted=FluoRaPressée が実行中のため、インストールを中止しました。FluoRaPressée を閉じてから、もう一度実行してください。
english.AppRunningAborted=Installation was stopped because FluoRaPressée is running. Close it and run the installer again.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Hidden on updates: Inno Setup remembers the previous choice and would otherwise
; re-run the driver installation (and its UAC prompt) on every update. Reinstalling
; the driver is done from the Start menu instead.
Name: "oceanoptics"; Description: "{cm:OceanOpticsTask}"; GroupDescription: "{cm:OceanOpticsGroup}"; Flags: unchecked; Check: not IsUpgrade

[InstallDelete]
; The contents of _internal change with every library update; files left over from
; an older version cause confusing import errors. Safe because the app never writes
; user data into the install folder (方針3).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\FluoRaPressee\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:AnalysisShortcut}"; Filename: "{app}\{#AnalysisExeName}"
Name: "{group}\{cm:DebugShortcut}"; Filename: "{app}\{#AppExeName}"; Parameters: "--debug"
Name: "{group}\{cm:OceanOpticsShortcut}"; Filename: "{app}\{#DriverExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Only this small tool runs elevated (UAC prompt); the application itself does not.
Filename: "{app}\{#DriverExeName}"; Tasks: oceanoptics; Verb: runas; Flags: shellexec waituntilterminated
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; User data (%LOCALAPPDATA%\FluoraPressee) is deliberately not removed on uninstall:
; settings and calibration catalogues belong to the instrument.

[Code]
const
  MutexPrefix = '{#MutexPrefix}';

{ The same rule as installer_mutex_name() in src/core/runtime_env.py: drop a
  trailing separator, "\" -> "/", lower-case A-Z only. }
function MutexNameFor(Dir: String): String;
var
  Normalized: String;
begin
  Normalized := Dir;
  while (Length(Normalized) > 0) and
        ((Normalized[Length(Normalized)] = '\') or (Normalized[Length(Normalized)] = '/')) do
    SetLength(Normalized, Length(Normalized) - 1);
  StringChangeEx(Normalized, '\', '/', True);
  Result := MutexPrefix + Lowercase(Normalized);
end;

function UninstallKey(): String;
begin
  Result := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
end;

function PreviousAppDir(): String;
begin
  if not RegQueryStringValue(HKA, UninstallKey(), 'Inno Setup: App Path', Result) then
    Result := '';
end;

function IsUpgrade(): Boolean;
begin
  Result := PreviousAppDir() <> '';
end;

{ Used by AppMutex, which is checked when Setup (or Uninstall) starts - before the
  install folder is chosen. An update checks the previous folder; a fresh
  installation has nothing that could be running from its folder yet. }
function RunningMutexName(Param: String): String;
var
  Dir: String;
begin
  if IsUninstaller() then
    Dir := ExpandConstant('{app}')
  else
    Dir := PreviousAppDir();
  if Dir = '' then
    Result := MutexPrefix + '(not installed yet)'
  else
    Result := MutexNameFor(Dir);
  Log('FluoRaPressee running-mutex (start-up check): ' + Result);
end;

{ Checked again right before files are copied, now that the folder is final, in
  case FluoRaPressée was started while the wizard was open. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Name: String;
begin
  Result := '';
  Name := MutexNameFor(ExpandConstant('{app}'));
  Log('FluoRaPressee running-mutex (before copying files): ' + Name);
  while CheckForMutexes(Name) do
  begin
    if SuppressibleMsgBox(CustomMessage('AppRunning'), mbError, MB_OKCANCEL, IDCANCEL) <> IDOK then
    begin
      Result := CustomMessage('AppRunningAborted');
      exit;
    end;
  end;
end;
