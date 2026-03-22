#define AppName "__APP_NAME__"
#define AppVersion "1.0.0"
#define AppPublisher "__APP_NAME__"
#define AppURL "https://www.zysj.site"
#define AppExeName "__APP_EXE_NAME__"
#define DistRoot "__DIST_ROOT__"
#define InstallSubdir "__APP_NAME__"

[Setup]
AppId={{6B6EECCE-52E7-4E53-A2D6-6FC6A5B87D51}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={code:GetDefaultInstallDir}
DefaultGroupName={#AppName}
AllowNoIcons=no
OutputDir=.
OutputBaseFilename={#AppName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableDirPage=no
DirExistsWarning=no
UninstallDisplayIcon={app}\{#AppExeName}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=*.exe,*.dll,*.pyd,*.zip

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#DistRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function GetDefaultInstallDir(Param: string): string;
var
  PreferredDrive: string;
begin
  PreferredDrive := ExpandConstant('{src}');
  if (Length(PreferredDrive) >= 2) and (PreferredDrive[2] = ':') then
  begin
    Result := Copy(PreferredDrive, 1, 2) + '\{#InstallSubdir}';
    exit;
  end;

  if DirExists('D:\') then
  begin
    Result := 'D:\{#InstallSubdir}';
    exit;
  end;

  if DirExists('E:\') then
  begin
    Result := 'E:\{#InstallSubdir}';
    exit;
  end;

  Result := ExpandConstant('{localappdata}\Programs\{#InstallSubdir}');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if WizardSilent then
  begin
    SuppressibleMsgBox('当前安装包不使用静默安装，请在安装界面选择安装位置后继续。', mbInformation, MB_OK, IDOK);
  end;
end;
