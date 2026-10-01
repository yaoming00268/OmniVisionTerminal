; 全能视像解析终端 — Inno Setup 安装版脚本
#define MyAppName "全能视像解析终端"
#define MyAppVersion "2.3.0"
#define MyAppPublisher "VisionTerminal"
#define MyAppLauncherExe "PhantomLauncher\PhantomLauncher.exe"
#define MyAppDesktopExe "PhantomCore\PhantomCore.exe"
#define MyAppWebExe "PhantomCore\PhantomCore.exe"

[Setup]
AppId={{E5B4F2A1-7C3D-4B9E-9A15-2D6C8E0F4B23}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=全能视像解析终端_安装版_v2.3.0
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=1
LZMAUseSeparateProcess=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#MyAppName}

[Languages]
Name: "cn"; MessagesFile: "ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\App\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppLauncherExe}"
Name: "{group}\桌面窗口模式"; Filename: "{app}\{#MyAppDesktopExe}"; Parameters: "--desktop"
Name: "{group}\WebUI 模式"; Filename: "{app}\{#MyAppWebExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppLauncherExe}"; Tasks: desktopicon
Name: "{autodesktop}\桌面窗口模式"; Filename: "{app}\{#MyAppDesktopExe}"; Parameters: "--desktop"; Tasks: desktopicon
Name: "{autodesktop}\WebUI 模式"; Filename: "{app}\{#MyAppWebExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppLauncherExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
