<#
.SYNOPSIS
    Install (and optionally upgrade) FluoRaPressée silently and smoke-test the result.

.DESCRIPTION
    Used by .github/workflows/release.yml (work/work_updater.md Step 5) on a
    throw-away runner. Do NOT run this on a development PC: it really installs
    FluoRaPressée for the current user (方針10).

.PARAMETER Installer
    The new installer to test.

.PARAMETER PreviousInstaller
    An installer of the latest published release, installed first so that the new
    one is tested as an in-place update. Omit for the very first release.
#>
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$PreviousInstaller = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\FluoRaPressee"

function Install-Silently {
    param([string]$Path, [string]$ExpectedMode = "")
    Write-Host "Installing $Path"
    $process = Start-Process -FilePath $Path -Wait -PassThru -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$Path.log`""
    )
    if (Test-Path "$Path.log") { Get-Content "$Path.log" | Select-String "FluoRaPressee|Error|error" }
    if ($process.ExitCode -ne 0) {
        throw "$Path exited with code $($process.ExitCode)"
    }
    if ($ExpectedMode) {
        $log = Get-Content -LiteralPath "$Path.log" -Raw
        if ($log -notmatch "FluoRaPressee installer mode: $ExpectedMode(?:;|\r?\n)") {
            throw "Installer did not detect expected mode: $ExpectedMode"
        }
    }
}

if ($PreviousInstaller) {
    Install-Silently $PreviousInstaller
    # Something an older version shipped that the new one does not: [InstallDelete]
    # must remove it (方針6).
    New-Item -ItemType File -Force -Path (Join-Path $InstallDir "_internal\stale-file-from-old-version.txt") | Out-Null
}
if ($PreviousInstaller) {
    Install-Silently $Installer -ExpectedMode "update"
} else {
    Install-Silently $Installer -ExpectedMode "install"
}

$stale = Join-Path $InstallDir "_internal\stale-file-from-old-version.txt"
if (Test-Path $stale) { throw "_internal was not cleared on update" }

# Even the first release must exercise existing-install detection. The same exe
# is also used to reinstall the same version, so this must remain update mode.
Install-Silently $Installer -ExpectedMode "update"

$SmokeData = Join-Path ([System.IO.Path]::GetTempPath()) "FluoRaPressee-install-test-$PID"
$PreviousDataDir = $env:FLUORAPRESSEE_DATA_DIR  # restored below, as in build_windows.ps1
$env:FLUORAPRESSEE_DATA_DIR = $SmokeData
try {
    foreach ($exe in @("FluoRaPressee.exe", "FluoRaPressee-Analysis.exe")) {
        $process = Start-Process -FilePath (Join-Path $InstallDir $exe) -ArgumentList "--smoke-test" -Wait -PassThru
        Get-ChildItem (Join-Path $SmokeData "logs") -Filter "app-*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { Get-Content $_.FullName }
        if ($process.ExitCode -ne 0) {
            throw "Installed $exe --smoke-test failed with exit code $($process.ExitCode)"
        }
    }
}
finally {
    if ($null -eq $PreviousDataDir) {
        Remove-Item Env:FLUORAPRESSEE_DATA_DIR -ErrorAction SilentlyContinue
    } else {
        $env:FLUORAPRESSEE_DATA_DIR = $PreviousDataDir
    }
}
Write-Host "Install test passed."
