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
; Show the operation and version before any choices, including on updates.
DisableWelcomePage=no
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
japanese.UpdateRunningAborted=FluoRaPressée が実行中のため、更新を中止しました。FluoRaPressée を閉じてから、もう一度実行してください。
english.UpdateRunningAborted=The update was stopped because FluoRaPressée is running. Close it and run the installer again.
japanese.InstallTitle=FluoRaPressée の新規インストール
english.InstallTitle=Install FluoRaPressée
japanese.InstallWelcome=FluoRaPressée %1 を新規インストールします。%n%n「次へ」を押して、インストール先とオプションを確認してください。
english.InstallWelcome=FluoRaPressée %1 will be installed on this computer.%n%nClick Next to choose the destination folder and options.
japanese.InstallVersion=インストールするバージョン: %1
english.InstallVersion=Version to install: %1
japanese.UpdateTitle=FluoRaPressée の更新
english.UpdateTitle=Update FluoRaPressée
japanese.UpdateWelcome=既存の FluoRaPressée を検出しました。%n%n%1%n%n前回と同じ場所のプログラムを更新します。設定と較正データは引き継がれます。%n%n「次へ」を押して、更新内容を確認してください。
english.UpdateWelcome=An existing FluoRaPressée installation was found.%n%n%1%n%nThe program will be updated in its existing folder. Settings and calibration data will be preserved.%n%nClick Next to review the update.
japanese.UpdateVersions=現在のバージョン: %1%n更新後のバージョン: %2
english.UpdateVersions=Current version: %1%nTarget version: %2
japanese.UnknownVersion=不明
english.UnknownVersion=Unknown
japanese.UpdateReady=更新の準備完了
english.UpdateReady=Ready to Update
japanese.UpdateReadyDescription=FluoRaPressée を更新する準備ができました。
english.UpdateReadyDescription=FluoRaPressée is ready to be updated.
japanese.UpdateReadyAction=「更新」を押すと更新を開始します。設定と較正データは引き継がれます。
english.UpdateReadyAction=Click Update to begin. Settings and calibration data will be preserved.
japanese.UpdateButton=更新(&U)
english.UpdateButton=&Update
japanese.UpdatePreparing=更新の準備中
english.UpdatePreparing=Preparing to Update
japanese.UpdatePreparingDescription=FluoRaPressée の更新を準備しています。
english.UpdatePreparingDescription=Preparing to update FluoRaPressée.
japanese.UpdateInstalling=更新中
english.UpdateInstalling=Updating
japanese.UpdateInstallingDescription=FluoRaPressée を更新しています。しばらくお待ちください。
english.UpdateInstallingDescription=Please wait while FluoRaPressée is being updated.
japanese.UpdateFinished=FluoRaPressée の更新完了
english.UpdateFinished=FluoRaPressée Update Complete
japanese.UpdateFinishedDescription=FluoRaPressée %1 への更新が完了しました。設定と較正データは引き継がれました。
english.UpdateFinishedDescription=FluoRaPressée has been updated to %1. Settings and calibration data have been preserved.
japanese.UpdateRestartDescription=FluoRaPressée %1 への更新を完了するには、コンピューターを再起動してください。
english.UpdateRestartDescription=Restart your computer to complete the update to FluoRaPressée %1.
japanese.UpdateCancel=FluoRaPressée の更新を中止しますか？
english.UpdateCancel=Do you want to cancel the FluoRaPressée update?

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

var
  UpgradeMode: Boolean;
  PreviousVersion: String;

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
  Result := UpgradeMode;
end;

function InitializeSetup(): Boolean;
begin
  { Snapshot before Setup writes its own uninstall registration. A fresh install
    must not turn into an update halfway through the wizard. }
  UpgradeMode := PreviousAppDir() <> '';
  if not RegQueryStringValue(HKA, UninstallKey(), 'DisplayVersion', PreviousVersion) then
    PreviousVersion := '';
  if IsUpgrade() then
    Log('FluoRaPressee installer mode: update; previous version: ' + PreviousVersion)
  else
    Log('FluoRaPressee installer mode: install');
  Result := True;
end;

function VersionSummary(): String;
var
  DisplayVersion: String;
begin
  if IsUpgrade() then
  begin
    DisplayVersion := PreviousVersion;
    if DisplayVersion = '' then
      DisplayVersion := CustomMessage('UnknownVersion');
    Result := FmtMessage(CustomMessage('UpdateVersions'), [DisplayVersion, '{#AppVersion}']);
  end
  else
    Result := FmtMessage(CustomMessage('InstallVersion'), ['{#AppVersion}']);
end;

procedure InitializeWizard();
var
  HeightChange: Integer;
begin
  if IsUpgrade() then
  begin
    WizardForm.Caption := CustomMessage('UpdateTitle');
    WizardForm.WelcomeLabel1.Caption := CustomMessage('UpdateTitle') + #13#10;
    WizardForm.WelcomeLabel2.Caption := FmtMessage(CustomMessage('UpdateWelcome'), [VersionSummary()]);
    WizardForm.FinishedHeadingLabel.Caption := CustomMessage('UpdateFinished') + #13#10;
    PageFromID(wpReady).Caption := CustomMessage('UpdateReady');
    PageFromID(wpReady).Description := CustomMessage('UpdateReadyDescription');
    PageFromID(wpPreparing).Caption := CustomMessage('UpdatePreparing');
    PageFromID(wpPreparing).Description := CustomMessage('UpdatePreparingDescription');
    PageFromID(wpInstalling).Caption := CustomMessage('UpdateInstalling');
    PageFromID(wpInstalling).Description := CustomMessage('UpdateInstallingDescription');
  end
  else
  begin
    WizardForm.Caption := CustomMessage('InstallTitle');
    WizardForm.WelcomeLabel1.Caption := CustomMessage('InstallTitle') + #13#10;
    WizardForm.WelcomeLabel2.Caption := FmtMessage(CustomMessage('InstallWelcome'), ['{#AppVersion}']);
  end;
  HeightChange := WizardForm.WelcomeLabel1.AdjustHeight;
  WizardForm.WelcomeLabel2.Top := WizardForm.WelcomeLabel2.Top + HeightChange;
  WizardForm.WelcomeLabel2.Height := WizardForm.WelcomeLabel2.Height - HeightChange;
  HeightChange := WizardForm.FinishedHeadingLabel.AdjustHeight;
  WizardForm.FinishedLabel.Top := WizardForm.FinishedLabel.Top + HeightChange;
end;

procedure AppendReadySection(var Memo: String; Section, NewLine: String);
begin
  if Section <> '' then
    Memo := Memo + NewLine + NewLine + Section;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := VersionSummary();
  AppendReadySection(Result, MemoUserInfoInfo, NewLine);
  AppendReadySection(Result, MemoDirInfo, NewLine);
  AppendReadySection(Result, MemoTypeInfo, NewLine);
  AppendReadySection(Result, MemoComponentsInfo, NewLine);
  AppendReadySection(Result, MemoGroupInfo, NewLine);
  AppendReadySection(Result, MemoTasksInfo, NewLine);
end;

procedure CurPageChanged(CurPageID: Integer);
var
  HeightChange: Integer;
begin
  if not IsUpgrade() then
    exit;
  if CurPageID = wpReady then
  begin
    WizardForm.NextButton.Caption := CustomMessage('UpdateButton');
    WizardForm.ReadyLabel.Caption := CustomMessage('UpdateReadyAction');
    HeightChange := WizardForm.ReadyLabel.AdjustHeight;
    WizardForm.ReadyMemo.Top := WizardForm.ReadyMemo.Top + HeightChange;
    WizardForm.ReadyMemo.Height := WizardForm.ReadyMemo.Height - HeightChange;
  end
  else if CurPageID = wpFinished then
  begin
    { Keep Inno Setup's restart choices and post-install launch list intact. }
    if WizardForm.YesRadio.Visible then
      WizardForm.FinishedLabel.Caption := FmtMessage(CustomMessage('UpdateRestartDescription'), ['{#AppVersion}']) + #13#10
    else
      WizardForm.FinishedLabel.Caption :=
        FmtMessage(CustomMessage('UpdateFinishedDescription'), ['{#AppVersion}']) + #13#10#13#10 +
        SetupMessage(msgClickFinish) + #13#10;
    HeightChange := WizardForm.FinishedLabel.AdjustHeight;
    WizardForm.RunList.Top := WizardForm.RunList.Top + HeightChange;
    WizardForm.RunList.Height := WizardForm.RunList.Height - HeightChange;
    WizardForm.YesRadio.Top := WizardForm.YesRadio.Top + HeightChange;
    WizardForm.NoRadio.Top := WizardForm.NoRadio.Top + HeightChange;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if IsUpgrade() and Confirm then
  begin
    Cancel := SuppressibleMsgBox(CustomMessage('UpdateCancel'), mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2, IDYES) = IDYES;
    Confirm := False;
  end;
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
      if IsUpgrade() then
        Result := CustomMessage('UpdateRunningAborted')
      else
        Result := CustomMessage('AppRunningAborted');
      exit;
    end;
  end;
end;
