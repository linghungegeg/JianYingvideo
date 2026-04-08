#define AppName "__APP_DISPLAY_NAME__"
#define AppVersion "__APP_VERSION__"
#define AppPublisher "__APP_PUBLISHER__"
#define AppURL "https://www.zysj.site"
#define AppExeName "__APP_EXE_NAME__"
#define DistRoot "__DIST_ROOT__"
#define InstallSubdir "__INSTALL_SUBDIR__"

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
AllowNoIcons=yes
OutputDir={src}\..
OutputBaseFilename=__OUTPUT_BASE_FILENAME__
SetupIconFile=__SETUP_ICON_FILE__
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
LanguageDetectionMethod=locale
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableDirPage=no
DisableStartupPrompt=yes
DirExistsWarning=no
UninstallDisplayIcon={app}\{#AppExeName}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=*.exe,*.dll,*.pyd,*.zip

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\\ChineseSimplified.isl"

[Files]
Source: "{#DistRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistRoot}\branding\*"; DestDir: "{app}\branding"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\VideoFactoryDesktop"
Type: filesandordirs; Name: "{userappdata}\VideoFactoryDesktop"
Type: filesandordirs; Name: "{localappdata}\Temp\VideoFactoryDesktop"
Type: filesandordirs; Name: "{tmp}\VideoFactoryDesktop"
Type: filesandordirs; Name: "{app}\branding"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\branding\app_icon.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\branding\app_icon.ico"

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
