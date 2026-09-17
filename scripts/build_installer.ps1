[CmdletBinding()]
param(
    [string]$IsccPath
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$applicationDirectory = Join-Path $projectRoot "dist\FormulaSnip"
$installerScript = Join-Path $projectRoot "installer\FormulaSnip.iss"
$pyprojectPath = Join-Path $projectRoot "pyproject.toml"

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

$rapidModelDirectory = Join-Path $applicationDirectory "_internal\rapid_latex_ocr\models"
if (
    (Test-Path -LiteralPath $rapidModelDirectory -PathType Container) -and
    (Get-ChildItem -LiteralPath $rapidModelDirectory -Recurse -File | Select-Object -First 1)
) {
    throw "Rapid model weights were found in the portable directory. Remove them or rebuild before creating a redistributable installer."
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
