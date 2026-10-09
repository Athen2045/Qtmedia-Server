param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $PSScriptRoot
$source = (Get-Command ffmpeg -ErrorAction Stop).Source
$destinationDirectory = Join-Path $appRoot "src-tauri\binaries"
$destination = Join-Path $destinationDirectory "ffmpeg-$TargetTriple.exe"
New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
Copy-Item -LiteralPath $source -Destination $destination -Force
Write-Output $destination
