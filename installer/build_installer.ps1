$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$AppId = "StructuralSteel_Beta_Model_2"
$DistDir = Join-Path $Root "dist\$AppId"
$OutputDir = Join-Path $Root "installer_output"
$InstallerPath = Join-Path $OutputDir "${AppId}_Setup.exe"
$InnoScript = Join-Path $PSScriptRoot "${AppId}.iss"

if (-not (Test-Path -LiteralPath $DistDir)) {
    throw "PyInstaller output not found: $DistDir"
}

if (-not (Test-Path -LiteralPath $InnoScript)) {
    throw "Inno Setup script not found: $InnoScript"
}

$isccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $null
foreach ($candidate in $isccCandidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        $iscc = $candidate
        break
    }
}

if (-not $iscc) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) {
        $iscc = $command.Source
    }
}

if (-not $iscc) {
    throw "Inno Setup compiler ISCC.exe was not found. Install Inno Setup 6, then rerun this script."
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
if (Test-Path -LiteralPath $InstallerPath) {
    Remove-Item -LiteralPath $InstallerPath -Force
}

& $iscc $InnoScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Installer was not created: $InstallerPath"
}

Get-Item -LiteralPath $InstallerPath
