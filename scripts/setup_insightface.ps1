[CmdletBinding()]
param(
    [string]$OnnxRuntimeGpuSpec = "onnxruntime-gpu==1.27.0"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

function Resolve-PythonLauncher {
    $candidates = @(
        @{ Command = "py"; Arguments = @("-3.11") },
        @{ Command = "py"; Arguments = @("-3") },
        @{ Command = "python"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        $commandInfo = Get-Command -Name $candidate.Command -ErrorAction SilentlyContinue
        if ($null -eq $commandInfo) {
            continue
        }

        try {
            & $candidate.Command @($candidate.Arguments + @("--version")) | Out-Null
            return $candidate
        }
        catch {
            continue
        }
    }

    throw "Python 3.11+ was not found. Install Python, ensure 'py' or 'python' is on PATH, and rerun this script."
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Launcher,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Launcher.Command @($Launcher.Arguments + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Launcher.Command) $($Launcher.Arguments + $Arguments -join ' ')"
    }
}

$scriptDir = Split-Path -Parent $PSCommandPath
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$projectVenv = Join-Path $projectRoot ".venv"
$insightfaceRoot = (Resolve-Path (Join-Path $projectRoot "Update\\insightface")).Path
$packageRoot = (Resolve-Path (Join-Path $insightfaceRoot "python-package")).Path
$targetVenv = Join-Path $insightfaceRoot ".venv"
$venvPython = Join-Path $targetVenv "Scripts\\python.exe"

if ([System.StringComparer]::OrdinalIgnoreCase.Equals($targetVenv, $projectVenv)) {
    throw "Refusing to install InsightFace into the main project .venv."
}
if (-not (Test-Path -LiteralPath (Join-Path $packageRoot "setup.py") -PathType Leaf)) {
    throw "InsightFace python-package setup.py not found: $packageRoot"
}

$launcher = Resolve-PythonLauncher

Write-Host "Creating or updating InsightFace venv at $targetVenv"
Invoke-Python -Launcher $launcher -Arguments @("-m", "venv", $targetVenv)

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "InsightFace venv was created but python.exe is missing: $venvPython"
}

Write-Host "Upgrading packaging tools inside the InsightFace venv"
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) {
    throw "Packaging tool upgrade failed inside $targetVenv"
}

Write-Host "Removing any CPU-only ONNX Runtime package before GPU install"
& $venvPython -m pip uninstall -y onnxruntime onnxruntime-gpu
if ($LASTEXITCODE -gt 1) {
    throw "Unable to remove existing ONNX Runtime packages cleanly."
}

Write-Host "Installing InsightFace runtime dependencies with $OnnxRuntimeGpuSpec"
& $venvPython -m pip install numpy onnx opencv-python tqdm requests scipy scikit-image $OnnxRuntimeGpuSpec
if ($LASTEXITCODE -ne 0) {
    throw "InsightFace dependency install failed."
}

Write-Host "Installing the uploaded InsightFace package in editable mode without reintroducing CPU-only onnxruntime"
& $venvPython -m pip install -e $packageRoot --no-deps
if ($LASTEXITCODE -ne 0) {
    throw "InsightFace package install failed."
}

Write-Host "Checking available ONNX Runtime providers"
$providerScript = @"
import sys
import onnxruntime

providers = list(onnxruntime.get_available_providers())
print("providers=" + ",".join(providers))
if "CUDAExecutionProvider" in providers:
    print("status=CUDAExecutionProvider")
    sys.exit(0)
if "CPUExecutionProvider" in providers:
    print("status=CPUExecutionProvider (degraded)")
    sys.exit(0)
print("status=none")
sys.exit(1)
"@

$providerOutput = & $venvPython -c $providerScript
if ($LASTEXITCODE -ne 0) {
    throw "ONNX Runtime provider check failed. Output:`n$providerOutput"
}

Write-Host $providerOutput
Write-Host ""
Write-Host "InsightFace setup complete."
Write-Host "Worker interpreter: $venvPython"
Write-Host "No model weights were downloaded. Provision them later with the documented manual step if you need local embeddings."
