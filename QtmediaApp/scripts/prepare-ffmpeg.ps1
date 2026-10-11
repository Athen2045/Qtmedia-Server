param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

# FFmpeg and FFprobe for yt-dlp (merging, audio extraction, FLAC conversion,
# cover art). Pinned to a gyan.dev release build (GPL, static) so every build
# ships the same verified binaries; yt-dlp finds ffprobe next to ffmpeg.
$Version = "9.0.2"
$ArchiveName = "ffmpeg-$Version-essentials_build.zip"
$ExpectedSha256 = @{
    "x86_64-pc-windows-msvc" = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
}
$BaseUrl = "https://github.com/GyanD/codexffmpeg/releases/download/$Version"

$ErrorActionPreference = "Stop"
$pinned = $ExpectedSha256[$TargetTriple]
if (-not $pinned) { throw "No pinned FFmpeg build for $TargetTriple." }

$appRoot = Split-Path -Parent $PSScriptRoot
$destinationDirectory = Join-Path $appRoot "src-tauri\binaries"
$work = Join-Path ([System.IO.Path]::GetTempPath()) "qtmedia-ffmpeg-$([guid]::NewGuid())"

New-Item -ItemType Directory -Force -Path $work, $destinationDirectory | Out-Null
try {
    $archive = Join-Path $work $ArchiveName
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri "$BaseUrl/$ArchiveName" -OutFile $archive -UseBasicParsing
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actual -ne $pinned) { throw "FFmpeg $Version archive checksum mismatch: $actual" }

    # Extract only the two programs (the archive also holds ffplay and docs).
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($tool in @("ffmpeg", "ffprobe")) {
            $entry = $zip.Entries | Where-Object { $_.FullName -like "*/bin/$tool.exe" } | Select-Object -First 1
            if (-not $entry) { throw "$tool.exe is missing from $ArchiveName." }
            $destination = Join-Path $destinationDirectory "$tool-$TargetTriple.exe"
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $true)
            $reported = @(& $destination -hide_banner -version)[0]
            if ($reported -notmatch "version $([regex]::Escape($Version))-") {
                throw "Unexpected $tool version: $reported"
            }
            Write-Output $destination
        }
    } finally {
        $zip.Dispose()
    }
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
