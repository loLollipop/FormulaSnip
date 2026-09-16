#ifndef AppVersion
  #define AppVersion "0.2.1"
#endif

#define AppName "FormulaSnip"
#define AppPublisher "FormulaSnip contributors"
#define AppExeName "FormulaSnip.exe"
#define AppUrl "https://github.com/loLollipop/FormulaSnip"

[Setup]
AppId={{2A0D2279-A23A-42B5-A431-045BC9778139}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
AppComments=Local formula snipping and recognition for Word and MathType workflows
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=FormulaSnip-v{#AppVersion}-windows-x64-setup
SetupIconFile=..\formulasnip\assets\formulasnip.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Windows Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimp"; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist\FormulaSnip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; A directory-mode upgrade must not leave metadata from an older FormulaSnip
; build beside the new metadata. Keep this wildcard limited to this package's
; dist-info directories; model directories are deliberately untouched.
Type: filesandordirs; Name: "{app}\_internal\formulasnip-*.dist-info"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "公式截图识别"
Name: "{autoprograms}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "公式截图识别"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Check: not IsAutoUpdate
Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Flags: nowait runhidden; Check: IsAutoUpdate

[UninstallDelete]
; RapidLaTeXOCR downloads these files after installation, so Inno does not
; know about them automatically. Keep the uninstall target narrow and remove
; only the backend's generated model directory.
Type: filesandordirs; Name: "{app}\_internal\rapid_latex_ocr\models"

[Code]
function IsAutoUpdate: Boolean;
begin
  Result := CompareText(ExpandConstant('{param:AUTOUPDATE|0}'), '1') = 0;
end;
