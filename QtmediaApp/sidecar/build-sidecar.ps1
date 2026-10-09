param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $appRoot ".venv\Scripts\python.exe"
$dist = Join-Path $PSScriptRoot "dist"
$work = Join-Path $PSScriptRoot "build"
$destinationDirectory = Join-Path $appRoot "src-tauri\binaries"
$destination = Join-Path $destinationDirectory "qtmedia-engine-$TargetTriple.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "QtmediaApp/.venv is required before building the sidecar."
}

New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
& $python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work "$PSScriptRoot\qtmedia-engine.spec"
Copy-Item -LiteralPath (Join-Path $dist "qtmedia-engine.exe") -Destination $destination -Force
Write-Output $destination
