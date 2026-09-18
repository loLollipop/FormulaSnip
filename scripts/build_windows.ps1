[CmdletBinding()]
param(
    [switch]$SkipSync,
    [switch]$SkipInstaller,
    [string]$ReleaseNotesPath
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$distDirectory = Join-Path $projectRoot "dist"
$applicationDirectory = Join-Path $distDirectory "FormulaSnip"
$versionMatch = Select-String `
    -LiteralPath (Join-Path $projectRoot "pyproject.toml") `
    -Pattern '^version = "([^"]+)"$'
if ($null -eq $versionMatch -or $versionMatch.Matches.Count -ne 1) {
    throw "Unable to read one project version from pyproject.toml."
}
$appVersion = $versionMatch.Matches[0].Groups[1].Value
$archivePath = Join-Path $distDirectory "FormulaSnip-v$appVersion-windows-x64.zip"

if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
    throw "FormulaSnip Windows packages must be built on Windows."
}
if ([IntPtr]::Size -ne 8) {
    throw "FormulaSnip v$appVersion must be built with a 64-bit Python runtime."
}

Push-Location $projectRoot
try {
    if (-not $SkipSync) {
        uv sync --locked --extra packaging
        if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
    }

    uv run pyinstaller --noconfirm --clean FormulaSnip.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $executablePath = Join-Path $applicationDirectory "FormulaSnip.exe"
    if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
        throw "The expected executable was not generated: $executablePath"
    }

    foreach ($documentName in @("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md")) {
        Copy-Item `
            -LiteralPath (Join-Path $projectRoot $documentName) `
            -Destination (Join-Path $applicationDirectory $documentName) `
            -Force
    }
    Copy-Item `
        -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_LICENSES") `
        -Destination (Join-Path $applicationDirectory "THIRD_PARTY_LICENSES") `
        -Recurse `
        -Force

    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    Push-Location $distDirectory
    try {
        tar.exe -a -c -f (Split-Path -Leaf $archivePath) "FormulaSnip"
        if ($LASTEXITCODE -ne 0) { throw "ZIP creation failed." }
    }
    finally {
        Pop-Location
    }

    $archive = Get-Item -LiteralPath $archivePath
    Write-Output "Executable: $executablePath"
    Write-Output "Archive: $($archive.FullName) ($([Math]::Round($archive.Length / 1MB, 1)) MiB)"

    if (-not $SkipInstaller) {
        $installerArguments = @{}
        if (-not [string]::IsNullOrWhiteSpace($ReleaseNotesPath)) {
            $installerArguments.ReleaseNotesPath = $ReleaseNotesPath
        }
        & (Join-Path $PSScriptRoot "build_installer.ps1") @installerArguments
    }
}
finally {
    Pop-Location
}
