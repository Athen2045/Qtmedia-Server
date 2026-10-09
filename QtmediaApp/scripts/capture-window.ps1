param(
    [string]$ProcessName = "Qtmedia",
    [string]$OutputPath = "$PSScriptRoot\..\artifacts\qtmedia-window.png"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class WindowCaptureNative {
    [StructLayout(LayoutKind.Sequential)]
    public struct Rect { public int Left; public int Top; public int Right; public int Bottom; }
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr handle);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr handle, IntPtr deviceContext, uint flags);
}
"@

$process = Get-Process -Name $ProcessName | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $process) {
    throw "No visible $ProcessName window was found."
}
[WindowCaptureNative]::ShowWindow($process.MainWindowHandle, 9) | Out-Null
[WindowCaptureNative]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 600
$rect = New-Object WindowCaptureNative+Rect
if (-not [WindowCaptureNative]::GetWindowRect($process.MainWindowHandle, [ref]$rect)) {
    throw "Unable to read the window bounds."
}
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $deviceContext = $graphics.GetHdc()
    try {
        $captured = [WindowCaptureNative]::PrintWindow($process.MainWindowHandle, $deviceContext, 2)
    } finally {
        $graphics.ReleaseHdc($deviceContext)
    }
    if (-not $captured) {
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
    }
    $directory = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}
Write-Output (Resolve-Path $OutputPath)
