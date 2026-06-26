#define MyAppName "Codex Record Migrator"
#define MyAppChineseName "Codex 记录备份迁移工具"
#define MyAppVersion "0.1.1"
#define MyAppPublisher "Local"
#define MyAppExeName "CodexRecordMigrator.exe"

[Setup]
AppId={{B86FEA1A-51E4-4A97-9EAF-2C0E75D73B90}
AppName={#MyAppChineseName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Codex Record Migrator
DefaultGroupName={#MyAppChineseName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=CodexRecordMigratorSetup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\build\main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppChineseName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppChineseName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppChineseName}}"; Flags: nowait postinstall skipifsilent
