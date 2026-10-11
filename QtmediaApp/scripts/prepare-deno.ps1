param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

# Deno runs yt-dlp's YouTube challenge solver without file-system or network
# access. Pinned so every build ships the same verified runtime.
$Version = "2.9.7"
$ExpectedSha256 = @{
    "x86_64-pc-windows-msvc" = "a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238"
}

$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $PSScriptRoot
$destinationDirectory = Join-Path $appRoot "src-tauri\binaries"
$destination = Join-Path $destinationDirectory "deno-$TargetTriple.exe"
$archiveName = "deno-$TargetTriple.zip"
$baseUrl = "https://github.com/denoland/deno/releases/download/v$Version"
$work = Join-Path ([System.IO.Path]::GetTempPath()) "qtmedia-deno-$([guid]::NewGuid())"

New-Item -ItemType Directory -Force -Path $work, $destinationDirectory | Out-Null
try {
    $archive = Join-Path $work $archiveName
    Invoke-WebRequest -Uri "$baseUrl/$archiveName" -OutFile $archive -UseBasicParsing
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()

    $pinned = $ExpectedSha256[$TargetTriple]
    if ($pinned) {
        if ($actual -ne $pinned) { throw "Deno $Version archive checksum mismatch: $actual" }
    } else {
        # First run for a new version or target: compare with the published
        # checksum, then pin the printed value above.
        $published = (Invoke-WebRequest -Uri "$baseUrl/$archiveName.sha256sum" -UseBasicParsing).Content
        if ($published -is [byte[]]) { $published = [System.Text.Encoding]::ASCII.GetString($published) }
        if ($published -notmatch $actual) { throw "Deno $Version archive does not match its published checksum." }
        Write-Warning "No pinned checksum for $TargetTriple. Published value verified; pin: $actual"
    }

    Expand-Archive -LiteralPath $archive -DestinationPath $work -Force
    Copy-Item -LiteralPath (Join-Path $work "deno.exe") -Destination $destination -Force
    $reported = & $destination --version | Select-Object -First 1
    if ($reported -notmatch [regex]::Escape($Version)) { throw "Unexpected Deno version: $reported" }
    Write-Output $destination
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
