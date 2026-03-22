#define AppName "__APP_NAME__"
#define AppVersion "1.0.0"
#define AppPublisher "__APP_NAME__"
#define AppURL "https://www.zysj.site"
#define AppExeName "__APP_NAME__.exe"
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
DefaultDirName={autopf}\{#InstallSubdir}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=.
OutputBaseFilename={#AppName}Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："

[Files]
Source: "{#DistRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\logs"
Name: "{app}\user_data"
Name: "{app}\runtime_tools"
Name: "{app}\duo_cache"
Name: "{app}\mcp_cache"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
