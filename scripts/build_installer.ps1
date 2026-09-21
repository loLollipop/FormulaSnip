[CmdletBinding()]
param(
    [string]$IsccPath,
    [string]$ReleaseNotesPath
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$applicationDirectory = Join-Path $projectRoot "dist\FormulaSnip"
$installerScript = Join-Path $projectRoot "installer\FormulaSnip.iss"
$pyprojectPath = Join-Path $projectRoot "pyproject.toml"
$maximumReleaseNotesLength = 4000

function Get-SingleVersion {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Version source was not found: $LiteralPath"
    }
    $resolvedPath = (Resolve-Path -LiteralPath $LiteralPath).Path
    $content = [System.IO.File]::ReadAllText(
        $resolvedPath,
        [System.Text.Encoding]::UTF8
    )
    $matches = [System.Text.RegularExpressions.Regex]::Matches(
        $content,
        $Pattern,
        [System.Text.RegularExpressions.RegexOptions]::Multiline
    )
    if ($matches.Count -ne 1) {
        throw "Unable to read exactly one version from $Label."
    }
    return $matches[0].Groups[1].Value
}

$appVersion = Get-SingleVersion `
    -LiteralPath $pyprojectPath `
    -Pattern '^version\s*=\s*"([^"]+)"\s*$' `
    -Label "pyproject.toml"
$packageVersion = Get-SingleVersion `
    -LiteralPath (Join-Path $projectRoot "formulasnip\__init__.py") `
    -Pattern '^__version__\s*=\s*"([^"]+)"\s*$' `
    -Label "formulasnip/__init__.py"
$installerVersion = Get-SingleVersion `
    -LiteralPath $installerScript `
    -Pattern '^\s*#define\s+AppVersion\s+"([^"]+)"\s*$' `
    -Label "installer/FormulaSnip.iss"
if ($appVersion -ne $packageVersion -or $appVersion -ne $installerVersion) {
    throw "Version mismatch: pyproject.toml=$appVersion, formulasnip/__init__.py=$packageVersion, installer/FormulaSnip.iss=$installerVersion."
}

if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
    throw "FormulaSnip installers must be built on Windows."
}
if (-not (Test-Path -LiteralPath (Join-Path $applicationDirectory "FormulaSnip.exe") -PathType Leaf)) {
    throw "Build the portable application first: scripts\build_windows.ps1 -SkipInstaller"
}
uv run --locked --project $projectRoot python (Join-Path $PSScriptRoot "verify_release_bundle.py") $applicationDirectory
if ($LASTEXITCODE -ne 0) { throw "Release bundle hygiene verification failed." }

foreach ($documentName in @("LICENSE", "README.md", "SECURITY.md", "PRIVACY.md", "THIRD_PARTY_NOTICES.md")) {
    Copy-Item `
        -LiteralPath (Join-Path $projectRoot $documentName) `
        -Destination (Join-Path $applicationDirectory $documentName) `
        -Force
}
Copy-Item `
    -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_LICENSES") `
    -Destination $applicationDirectory `
    -Recurse `
    -Force

if ([string]::IsNullOrWhiteSpace($ReleaseNotesPath)) {
    $ReleaseNotesPath = Join-Path $projectRoot "RELEASE_NOTES.md"
}
if (-not (Test-Path -LiteralPath $ReleaseNotesPath -PathType Leaf)) {
    throw "Release notes were not found: $ReleaseNotesPath"
}
$releaseNotes = [System.IO.File]::ReadAllText(
    (Resolve-Path -LiteralPath $ReleaseNotesPath).Path,
    [System.Text.Encoding]::UTF8
).Trim()
if ([string]::IsNullOrWhiteSpace($releaseNotes)) {
    throw "Release notes must not be empty."
}
if ($releaseNotes.Length -gt $maximumReleaseNotesLength) {
    throw "Release notes exceed the $maximumReleaseNotesLength character client limit."
}

$metadataDirectories = @(
    Get-ChildItem `
        -LiteralPath (Join-Path $applicationDirectory "_internal") `
        -Directory `
        -Filter "formulasnip-*.dist-info"
)
if ($metadataDirectories.Count -ne 1) {
    throw "Expected one packaged FormulaSnip metadata directory, found $($metadataDirectories.Count)."
}
$metadataPath = Join-Path $metadataDirectories[0].FullName "METADATA"
$packagedVersionMatch = Select-String -LiteralPath $metadataPath -Pattern '^Version: (.+)$'
if ($null -eq $packagedVersionMatch -or $packagedVersionMatch.Matches.Count -ne 1) {
    throw "Unable to read the packaged FormulaSnip version from $metadataPath."
}
$packagedVersion = $packagedVersionMatch.Matches[0].Groups[1].Value.Trim()
if ($packagedVersion -ne $appVersion) {
    throw "Packaged app version $packagedVersion does not match project version $appVersion. Rebuild the portable application first."
}

$retiredRapidEntries = @(
    (Join-Path $applicationDirectory "_internal\rapid_latex_ocr"),
    (Join-Path $applicationDirectory "_internal\rapid_latex_ocr-0.0.9.dist-info"),
    (Join-Path $applicationDirectory "_internal\formulasnip\recognition\rapid_config.yaml")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($null -ne $retiredRapidEntries) {
    throw "The portable directory still contains the retired RapidLaTeXOCR backend. Rebuild it with scripts\build_windows.ps1 -SkipInstaller first: $retiredRapidEntries"
}

$modelLockPath = Join-Path $projectRoot "MODEL_ASSETS.json"
$packagedModelLockPath = Join-Path $applicationDirectory "_internal\MODEL_ASSETS.json"
$bundledModelPath = Join-Path $applicationDirectory "_internal\MathCraft\models\mathcraft-formula-rec"
$prepareModelScript = Join-Path $projectRoot "scripts\prepare_bundled_model.py"
$modelLockHash = (Get-FileHash -LiteralPath $modelLockPath -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not (Test-Path -LiteralPath $packagedModelLockPath -PathType Leaf)) {
    throw "The packaged MODEL_ASSETS.json is missing. Rebuild the portable application first."
}
$packagedModelLockHash = (
    Get-FileHash -LiteralPath $packagedModelLockPath -Algorithm SHA256
).Hash.ToLowerInvariant()
if ($packagedModelLockHash -ne $modelLockHash) {
    throw "The packaged MODEL_ASSETS.json does not match the project lock. Rebuild the portable application first."
}
$modelLock = Get-Content -LiteralPath $modelLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$modelBundleEntries = @($modelLock.files)
if ($modelBundleEntries.Count -eq 0) {
    throw "The model lock does not contain files for the update installer."
}
$encodedModelEntries = [System.Collections.Generic.List[string]]::new()
$seenModelPaths = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($modelBundleEntry in $modelBundleEntries) {
    $modelBundleFile = [string]$modelBundleEntry.path
    $modelBundleSize = $modelBundleEntry.size
    $modelBundleSha256 = [string]$modelBundleEntry.sha256
    if (
        [string]::IsNullOrWhiteSpace($modelBundleFile) -or
        [System.IO.Path]::IsPathRooted($modelBundleFile) -or
        $modelBundleFile -notmatch '^[A-Za-z0-9._/-]+$' -or
        $modelBundleFile.Contains("\\") -or
        (($modelBundleFile -split '/') -contains "..") -or
        (($modelBundleFile -split '/') -contains ".") -or
        -not $seenModelPaths.Add($modelBundleFile)
    ) {
        throw "The model lock contains an unsafe or duplicate file path for the update installer."
    }
    if (
        $modelBundleSize -isnot [int] -and
        $modelBundleSize -isnot [long]
    ) {
        throw "The model lock contains an invalid file size for the update installer."
    }
    $modelBundleSize = [long]$modelBundleSize
    if ($modelBundleSize -le 0) {
        throw "The model lock contains an invalid file size for the update installer."
    }
    if ($modelBundleSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "The model lock contains an invalid SHA-256 for the update installer."
    }
    $encodedModelPath = $modelBundleFile.Replace('/', '\')
    $encodedModelEntries.Add(
        "$encodedModelPath;$modelBundleSize;$modelBundleSha256"
    )
}
$modelBundleManifest = $encodedModelEntries -join "|"
uv run --project $projectRoot python $prepareModelScript `
    --lock $modelLockPath `
    --destination $bundledModelPath `
    --verify-only
if ($LASTEXITCODE -ne 0) {
    throw "The packaged MathCraft formula model failed verification."
}

if (-not $IsccPath) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $candidates = @()
    if ($null -ne $command) {
        $candidates += $command.Source
    }
    $candidates += @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    $IsccPath = $candidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
}

if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw "Inno Setup 6 was not found. Install it with: winget install --id JRSoftware.InnoSetup --exact"
}

Push-Location $projectRoot
try {
    & $IsccPath "/Qp" "/DAppVersion=$appVersion" $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Full Inno Setup compilation failed."
    }
    & $IsccPath `
        "/Qp" `
        "/DAppVersion=$appVersion" `
        "/DUpdatePackage=1" `
        "/DModelLockSha256=$modelLockHash" `
        "/DModelBundleEntries=$modelBundleManifest" `
        $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Lightweight Inno Setup compilation failed."
    }
}
finally {
    Pop-Location
}

$installerPath = Join-Path $projectRoot "dist\FormulaSnip-v$appVersion-windows-x64-setup.exe"
$updateInstallerPath = Join-Path $projectRoot "dist\FormulaSnip-v$appVersion-windows-x64-update.exe"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "The expected installer was not generated: $installerPath"
}
if (-not (Test-Path -LiteralPath $updateInstallerPath -PathType Leaf)) {
    throw "The expected lightweight installer was not generated: $updateInstallerPath"
}

$installer = Get-Item -LiteralPath $installerPath
$updateInstaller = Get-Item -LiteralPath $updateInstallerPath
Write-Output "Installer: $($installer.FullName) ($([Math]::Round($installer.Length / 1MB, 1)) MiB)"
Write-Output "Update installer: $($updateInstaller.FullName) ($([Math]::Round($updateInstaller.Length / 1MB, 1)) MiB)"

$legacyManifestPath = Join-Path $projectRoot "dist\FormulaSnip-update.json"
$manifestV2Path = Join-Path $projectRoot "dist\FormulaSnip-update-v2.json"
$installerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$updateInstallerHash = (Get-FileHash -LiteralPath $updateInstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$legacyManifest = [ordered]@{
    schema_version = 1
    version = $appVersion
    tag = "v$appVersion"
    notes = $releaseNotes
    asset = [ordered]@{
        name = $installer.Name
        size = $installer.Length
        sha256 = $installerHash
    }
}
$manifestV2 = [ordered]@{
    schema_version = 2
    version = $appVersion
    tag = "v$appVersion"
    notes = $releaseNotes
    model_bundle_sha256 = $modelLockHash
    asset = $legacyManifest.asset
    update_asset = [ordered]@{
        name = $updateInstaller.Name
        size = $updateInstaller.Length
        sha256 = $updateInstallerHash
    }
}
$legacyManifestJson = $legacyManifest | ConvertTo-Json -Depth 3
$manifestV2Json = $manifestV2 | ConvertTo-Json -Depth 3
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($legacyManifestPath, $legacyManifestJson, $utf8NoBom)
[System.IO.File]::WriteAllText($manifestV2Path, $manifestV2Json, $utf8NoBom)
Write-Output "Legacy update manifest: $legacyManifestPath"
Write-Output "Update manifest v2: $manifestV2Path"
Write-Output "Release notes: $ReleaseNotesPath"
