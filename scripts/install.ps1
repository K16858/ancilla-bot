# Ancilla one-liner installer for Windows (irm ... | iex)
$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:ANCILLA_REPO_URL) { $env:ANCILLA_REPO_URL } else { "https://github.com/K16858/ancilla-bot.git" }
$Root = if ($env:ANCILLA_ROOT) { $env:ANCILLA_ROOT } else { Join-Path $env:LOCALAPPDATA "ancilla" }
$BinDir = Join-Path $Root "bin"

Write-Host "Ancilla installer"
Write-Host ""

function Assert-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

Assert-Command git

$Python = $null
foreach ($cand in @("python", "py")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
        & $cand -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        if ($LASTEXITCODE -eq 0) {
            $Python = $cand
            break
        }
    } catch {
        continue
    }
}

if (-not $Python) {
    throw "Python 3.11+ is required."
}

& $Python -c "import venv" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "python -m venv is not available."
}

Write-Host "Using Python: $Python"
Write-Host "Install root: $Root"

New-Item -ItemType Directory -Force -Path (Split-Path $Root) | Out-Null
if (Test-Path (Join-Path $Root ".git")) {
    Write-Host "Updating existing checkout..."
    git -C $Root pull --ff-only
} else {
    Write-Host "Cloning repository..."
    git clone $RepoUrl $Root
}

Push-Location $Root
try {
    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        & $Python -m venv .venv
    }
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -e .

    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $Launcher = Join-Path $BinDir "ancilla.cmd"
    @"
@echo off
set ANCILLA_ROOT=$Root
cd /d "%ANCILLA_ROOT%" || exit /b 1
"%ANCILLA_ROOT%\.venv\Scripts\ancilla.exe" %*
"@ | Set-Content -Path $Launcher -Encoding ASCII

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not ($userPath -split ";" | Where-Object { $_ -eq $BinDir })) {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$BinDir", "User")
        Write-Host "Added to User PATH: $BinDir"
    }
    if (-not ($env:Path -split ";" | Where-Object { $_ -eq $BinDir })) {
        $env:Path = "$env:Path;$BinDir"
    }

    Write-Host ""
    Write-Host "Installed launcher: $Launcher"
    Write-Host ""
    Write-Host "Next:"
    Write-Host "  ancilla install core"
    Write-Host "  ancilla setup"
    Write-Host "  ancilla start"
} finally {
    Pop-Location
}
