#ifndef AppVersion
  #define AppVersion "0.2.12"
#endif
#ifdef UpdatePackage
  #ifndef ModelLockSha256
    #error ModelLockSha256 is required for a lightweight update package
  #endif
  #ifndef ModelBundleEntries
    #error ModelBundleEntries is required for a lightweight update package
  #endif
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
#ifdef UpdatePackage
DefaultDirName={code:GetRegisteredInstallPath}
DisableDirPage=yes
UsePreviousAppDir=no
#else
DefaultDirName={localappdata}\Programs\{#AppName}
#endif
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
#ifdef UpdatePackage
OutputBaseFilename=FormulaSnip-v{#AppVersion}-windows-x64-update
#else
OutputBaseFilename=FormulaSnip-v{#AppVersion}-windows-x64-setup
#endif
SetupIconFile=..\formulasnip\assets\formulasnip.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
#ifdef UpdatePackage
Compression=lzma2/fast
SolidCompression=no
#else
Compression=lzma2/max
SolidCompression=yes
#endif
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
#ifdef UpdatePackage
; Preserve the compatible model already installed on the machine. The code
; gate below rejects this package unless the exact lock and all locked files
; are present.
Source: "..\dist\FormulaSnip\*"; DestDir: "{app}"; Excludes: "_internal\MathCraft\models\*,_internal\MODEL_ASSETS.json,MODEL_ASSETS.json"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
Source: "..\dist\FormulaSnip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[InstallDelete]
; A directory-mode upgrade must not leave metadata from an older FormulaSnip
; build beside the new metadata. Keep this wildcard limited to this package's
; dist-info directories; model cleanup is separately gated to full Setup below.
Type: filesandordirs; Name: "{app}\_internal\formulasnip-*.dist-info"
; Versions before the MathCraft-only release bundled RapidLaTeXOCR and could
; download its weights below this exact package directory. Remove only that
; retired backend during an upgrade; `rapidocr` is still required by MathCraft.
Type: filesandordirs; Name: "{app}\_internal\rapid_latex_ocr"
Type: filesandordirs; Name: "{app}\_internal\rapid_latex_ocr-*.dist-info"
Type: files; Name: "{app}\_internal\formulasnip\recognition\rapid_config.yaml"
#ifndef UpdatePackage
; A full Setup owns the bundled model and must remove stale or extra files
; before copying the release-locked bundle. Lightweight updates preserve it.
Type: filesandordirs; Name: "{app}\_internal\MathCraft\models\mathcraft-formula-rec"
#endif

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "公式截图识别"
Name: "{autoprograms}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "公式截图识别"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Check: not IsAutoUpdate
Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Flags: nowait; Check: IsAutoUpdate

[Code]
function IsAutoUpdate: Boolean;
begin
  Result := CompareText(ExpandConstant('{param:AUTOUPDATE|0}'), '1') = 0;
end;

#ifdef UpdatePackage
var
  RegisteredInstallPath: String;

function NextDelimited(var Remaining: String; Delimiter: String): String;
var
  Separator: Integer;
begin
  Separator := Pos(Delimiter, Remaining);
  if Separator = 0 then
  begin
    Result := Remaining;
    Remaining := '';
  end
  else
  begin
    Result := Copy(Remaining, 1, Separator - 1);
    Delete(Remaining, 1, Separator + Length(Delimiter) - 1);
  end;
end;

function GetRegisteredInstallPath(Param: String): String;
begin
  Result := RegisteredInstallPath;
end;

function InitializeSetup: Boolean;
var
  InstallPath: String;
  ModelPath: String;
  ModelEntries: String;
  ModelEntry: String;
  ModelRelativePath: String;
  ExpectedSize: String;
  ExpectedSha256: String;
  ModelFilePath: String;
  ActualSize: Int64;
begin
  Result := False;
  if not RegQueryStringValue(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{2A0D2279-A23A-42B5-A431-045BC9778139}_is1',
    'InstallLocation',
    InstallPath
  ) or not FileExists(AddBackslash(InstallPath) + '{#AppExeName}') then
  begin
    MsgBox(
      '未找到现有 FormulaSnip 安装。请下载完整 Setup 安装包。',
      mbError,
      MB_OK
    );
    Exit;
  end;
  RegisteredInstallPath := RemoveBackslashUnlessRoot(InstallPath);
  if ExpandConstant('{param:DIR|}') <> '' then
  begin
    MsgBox(
      '轻量更新包不能重定向安装目录。请使用已注册的安装位置。',
      mbError,
      MB_OK
    );
    Exit;
  end;

  if CompareText(
    GetSHA256OfFile(AddBackslash(InstallPath) + '_internal\MODEL_ASSETS.json'),
    '{#ModelLockSha256}'
  ) <> 0 then
  begin
    MsgBox(
      '现有 MathCraft 模型版本与此更新不兼容。请下载完整 Setup 安装包。',
      mbError,
      MB_OK
    );
    Exit;
  end;

  ModelPath := AddBackslash(InstallPath) +
    '_internal\MathCraft\models\mathcraft-formula-rec\';
  ModelEntries := '{#ModelBundleEntries}';
  while ModelEntries <> '' do
  begin
    ModelEntry := NextDelimited(ModelEntries, '|');
    ModelRelativePath := NextDelimited(ModelEntry, ';');
    ExpectedSize := NextDelimited(ModelEntry, ';');
    ExpectedSha256 := NextDelimited(ModelEntry, ';');
    ModelFilePath := ModelPath + ModelRelativePath;
    if (ModelRelativePath = '') or (ExpectedSize = '') or
       (ExpectedSha256 = '') or (ModelEntry <> '') or
       not FileSize64(ModelFilePath, ActualSize) or
       (ActualSize <> StrToInt64(ExpectedSize)) or
       (CompareText(GetSHA256OfFile(ModelFilePath), ExpectedSha256) <> 0) then
    begin
      MsgBox(
        '现有 MathCraft 模型文件不完整或已损坏。请下载完整 Setup 安装包。',
        mbError,
        MB_OK
      );
      Exit;
    end;
  end;
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if CompareText(
    RemoveBackslashUnlessRoot(ExpandConstant('{app}')),
    RegisteredInstallPath
  ) <> 0 then
    Result := '轻量更新包只能安装到现有 FormulaSnip 的注册位置。';
end;
#endif
