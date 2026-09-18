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

if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
    throw "FormulaSnip installers must be built on Windows."
}
if (-not (Test-Path -LiteralPath (Join-Path $applicationDirectory "FormulaSnip.exe") -PathType Leaf)) {
    throw "Build the portable application first: scripts\build_windows.ps1 -SkipInstaller"
}

foreach ($documentName in @("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md")) {
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

$versionMatch = Select-String -LiteralPath $pyprojectPath -Pattern '^version = "([^"]+)"$'
if ($null -eq $versionMatch -or $versionMatch.Matches.Count -ne 1) {
    throw "Unable to read one project version from pyproject.toml."
}
$appVersion = $versionMatch.Matches[0].Groups[1].Value

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

$mathCraftWeights = Get-ChildItem `
    -LiteralPath $applicationDirectory `
    -Recurse `
    -File `
    -Filter "*.onnx" |
    Where-Object {
        $_.FullName -match '[\\/](mathcraft_ocr|rapidocr|onnxruntime[\\/]datasets)[\\/]'
    } |
    Select-Object -First 1
if ($null -ne $mathCraftWeights) {
    throw "MathCraft/RapidOCR model weights were found in the portable directory: $($mathCraftWeights.FullName)"
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
        throw "Inno Setup compilation failed."
    }
}
finally {
    Pop-Location
}

$installerPath = Join-Path $projectRoot "dist\FormulaSnip-v$appVersion-windows-x64-setup.exe"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "The expected installer was not generated: $installerPath"
}

$installer = Get-Item -LiteralPath $installerPath
Write-Output "Installer: $($installer.FullName) ($([Math]::Round($installer.Length / 1MB, 1)) MiB)"

$manifestPath = Join-Path $projectRoot "dist\FormulaSnip-update.json"
$installerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
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
$manifestJson = $manifest | ConvertTo-Json -Depth 3
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8NoBom)
Write-Output "Update manifest: $manifestPath"
Write-Output "Release notes: $ReleaseNotesPath"
