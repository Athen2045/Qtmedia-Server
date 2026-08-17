[CmdletBinding()]
param()

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
            if ($LASTEXITCODE -ne 0) {
                continue
            }
            return $candidate
        }
        catch {
            continue
        }
    }

    throw "Python 3.11+ was not found. Install Python, ensure 'py' or 'python' is on PATH, and rerun this script."
}

function Assert-Python311OrNewer {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Launcher
    )

    $versionScript = @"
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
"@

    & $Launcher.Command @($Launcher.Arguments + @("-c", $versionScript)) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11+ is required for Blackbird setup."
    }
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
$configuredBlackbirdRoot = $env:PRIVATE_SEARCH_BLACKBIRD_ROOT
$blackbirdRoot = if ([string]::IsNullOrWhiteSpace($configuredBlackbirdRoot)) {
    Join-Path $projectRoot "var\\tools\\blackbird"
} else {
    [System.IO.Path]::GetFullPath($configuredBlackbirdRoot)
}
$targetVenv = Join-Path $blackbirdRoot ".venv"
$requirementsPath = Join-Path $blackbirdRoot "requirements.txt"
$usernameDataPath = Join-Path $blackbirdRoot "data\wmn-data.json"
$venvPython = Join-Path $targetVenv "Scripts\\python.exe"

if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw "Blackbird requirements file not found: $requirementsPath"
}
if ([System.StringComparer]::OrdinalIgnoreCase.Equals($targetVenv, $projectVenv)) {
    throw "Refusing to install Blackbird into the main project .venv."
}

$launcher = Resolve-PythonLauncher
Assert-Python311OrNewer -Launcher $launcher

Write-Host "Creating or updating Blackbird venv at $targetVenv"
Invoke-Python -Launcher $launcher -Arguments @("-m", "venv", $targetVenv)

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "Blackbird venv was created but python.exe is missing: $venvPython"
}

Write-Host "Upgrading pip inside the Blackbird venv"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed inside $targetVenv"
}

Write-Host "Installing Blackbird requirements from $requirementsPath"
& $venvPython -m pip install -r $requirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Blackbird requirements install failed."
}

if (-not (Test-Path -LiteralPath $usernameDataPath -PathType Leaf)) {
    Write-Host "Downloading the initial WhatsMyName username database"
    Invoke-WebRequest `
        -Uri "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json" `
        -OutFile $usernameDataPath
}

Write-Host ""
Write-Host "Blackbird setup complete."
Write-Host "Worker interpreter: $venvPython"
Write-Host "Initial username database is installed. External list updates remain disabled unless PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES=1 is set explicitly."
