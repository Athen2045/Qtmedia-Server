param(
    [string]$Ffmpeg = (Join-Path (Split-Path -Parent $PSScriptRoot) "src-tauri\binaries\ffmpeg-x86_64-pc-windows-msvc.exe")
)

# Generates the native audio engine's decoder fixtures from synthetic tones:
# no third-party audio. Each lossless fixture is encoded from the same
# intermediate WAV as its .raw twin, so tests can assert bit-exact decoding.
$ErrorActionPreference = "Stop"
$out = Join-Path (Split-Path -Parent $PSScriptRoot) "src-tauri\tests\fixtures\audio"
$work = Join-Path ([System.IO.Path]::GetTempPath()) "qtmedia-fixtures-$([guid]::NewGuid())"
New-Item -ItemType Directory -Force -Path $out, $work | Out-Null

function Invoke-Ffmpeg([string[]]$Arguments) {
    & $Ffmpeg -hide_banner -loglevel error -y @Arguments
    if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed: $Arguments" }
}

# Left 440 Hz, right 660 Hz, 0.25 s, half scale.
$tone = "aevalsrc=0.5*sin(2*PI*440*t)|0.5*sin(2*PI*660*t):d=0.25"
try {
    Invoke-Ffmpeg @("-f", "lavfi", "-i", "$tone`:s=44100", "-c:a", "pcm_s16le", "$work\s16.wav")
    Invoke-Ffmpeg @("-i", "$work\s16.wav", "-c:a", "flac", "$out\sine_16_44100.flac")
    Invoke-Ffmpeg @("-i", "$work\s16.wav", "-f", "s16le", "-c:a", "pcm_s16le", "$out\sine_16_44100.raw")

    Invoke-Ffmpeg @("-f", "lavfi", "-i", "$tone`:s=96000", "-c:a", "pcm_s24le", "$work\s24.wav")
    Invoke-Ffmpeg @("-i", "$work\s24.wav", "-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24", "$out\sine_24_96000.flac")
    Invoke-Ffmpeg @("-i", "$work\s24.wav", "-f", "s24le", "-c:a", "pcm_s24le", "$out\sine_24_96000.raw")

    # LAME writes encoder delay/padding, which gapless decoding must remove.
    Invoke-Ffmpeg @("-i", "$work\s16.wav", "-c:a", "libmp3lame", "-b:a", "192k", "$out\sine_44100.mp3")

    # Tagged songs for the lyrics lookup's tag reader (Vorbis comments, ID3v2.3).
    $tags = @("-metadata", "title=Fixture Song", "-metadata", "artist=Fixture Artist", "-metadata", "album=Fixture Album")
    Invoke-Ffmpeg (@("-f", "lavfi", "-i", "sine=f=440:d=0.5:r=44100", "-ac", "2", "-c:a", "flac") + $tags + @("$out\tagged.flac"))
    Invoke-Ffmpeg (@("-f", "lavfi", "-i", "sine=f=440:d=0.5:r=44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "64k", "-id3v2_version", "3") + $tags + @("$out\tagged.mp3"))
    Get-ChildItem $out | Select-Object Name, Length
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
