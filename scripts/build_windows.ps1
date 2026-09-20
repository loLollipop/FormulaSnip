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
    -LiteralPath (Join-Path $projectRoot "pyproject.toml") `
    -Pattern '^version\s*=\s*"([^"]+)"\s*$' `
    -Label "pyproject.toml"
$packageVersion = Get-SingleVersion `
    -LiteralPath (Join-Path $projectRoot "formulasnip\__init__.py") `
    -Pattern '^__version__\s*=\s*"([^"]+)"\s*$' `
    -Label "formulasnip/__init__.py"
$installerVersion = Get-SingleVersion `
    -LiteralPath (Join-Path $projectRoot "installer\FormulaSnip.iss") `
    -Pattern '^\s*#define\s+AppVersion\s+"([^"]+)"\s*$' `
    -Label "installer/FormulaSnip.iss"
if ($appVersion -ne $packageVersion -or $appVersion -ne $installerVersion) {
    throw "Version mismatch: pyproject.toml=$appVersion, formulasnip/__init__.py=$packageVersion, installer/FormulaSnip.iss=$installerVersion."
}
$archivePath = Join-Path $distDirectory "FormulaSnip-v$appVersion-windows-x64.zip"
$modelLockPath = Join-Path $projectRoot "MODEL_ASSETS.json"
$bundledModelPath = Join-Path $projectRoot "build\bundled-models\MathCraft\models\mathcraft-formula-rec"

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

    uv run python scripts\prepare_bundled_model.py `
        --lock $modelLockPath `
        --destination $bundledModelPath
    if ($LASTEXITCODE -ne 0) { throw "Bundled MathCraft model preparation failed." }

    uv run pyinstaller --noconfirm --clean FormulaSnip.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $executablePath = Join-Path $applicationDirectory "FormulaSnip.exe"
    if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
        throw "The expected executable was not generated: $executablePath"
    }

    $smokeProcess = Start-Process `
        -FilePath $executablePath `
        -ArgumentList "--smoke-preview" `
        -WindowStyle Hidden `
        -PassThru
    if (-not $smokeProcess.WaitForExit(30000)) {
        $smokeProcess.Kill()
        throw "The frozen formula preview smoke test timed out."
    }
    if ($smokeProcess.ExitCode -ne 0) {
        throw "The frozen formula preview smoke test failed with exit code $($smokeProcess.ExitCode)."
    }

    $modelSmokeProcess = Start-Process `
        -FilePath $executablePath `
        -ArgumentList "--smoke-model" `
        -WindowStyle Hidden `
        -PassThru
    if (-not $modelSmokeProcess.WaitForExit(120000)) {
        $modelSmokeProcess.Kill()
        throw "The frozen offline MathCraft model smoke test timed out."
    }
    if ($modelSmokeProcess.ExitCode -ne 0) {
        throw "The frozen offline MathCraft model smoke test failed with exit code $($modelSmokeProcess.ExitCode)."
    }

    foreach ($documentName in @("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "MODEL_ASSETS.json")) {
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
