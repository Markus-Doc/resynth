# RESYNTH installer for Windows.
# Run from PowerShell:
#   irm https://raw.githubusercontent.com/Markus-Doc/resynth/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/Markus-Doc/resynth"
$AppDir = Join-Path $env:LOCALAPPDATA "RESYNTH\app"
$WorkDir = Join-Path $env:USERPROFILE "RESYNTH"
$LauncherDir = Join-Path $env:LOCALAPPDATA "RESYNTH"

Write-Host ""
Write-Host "RESYNTH installer" -ForegroundColor Cyan
Write-Host "-----------------"

# 1. Python check
$python = Get-Command python -ErrorAction SilentlyContinue
$pyOk = $false
if ($python) {
    $v = & python -c "import sys; print(1 if sys.version_info >= (3, 11) else 0)" 2>$null
    if ($v -eq "1") { $pyOk = $true }
}
if (-not $pyOk) {
    Write-Host "Python 3.11 or newer is required. Attempting install via winget..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    Write-Host "Python installed. Close this window, open a NEW PowerShell window and run the installer again." -ForegroundColor Yellow
    return
}
Write-Host "Python: ok"

# 2. Git check (needed for download and for sealing)
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is required. Attempting install via winget..." -ForegroundColor Yellow
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    Write-Host "Git installed. Close this window, open a NEW PowerShell window and run the installer again." -ForegroundColor Yellow
    return
}
Write-Host "Git: ok"

# 3. Fetch or update the app
if (Test-Path (Join-Path $AppDir ".git")) {
    Write-Host "Updating RESYNTH..."
    git -C $AppDir pull --quiet
} else {
    Write-Host "Downloading RESYNTH..."
    New-Item -ItemType Directory -Force (Split-Path $AppDir) | Out-Null
    git clone --quiet --depth 1 $Repo $AppDir
}

# 4. Private environment for the app
Write-Host "Installing (this takes a minute)..."
& python -m venv (Join-Path $AppDir ".venv")
& (Join-Path $AppDir ".venv\Scripts\pip.exe") install --quiet --upgrade pip
& (Join-Path $AppDir ".venv\Scripts\pip.exe") install --quiet -e $AppDir

# 5. Workspace where research projects live
New-Item -ItemType Directory -Force $WorkDir | Out-Null

# 6. Launcher
$launcher = Join-Path $LauncherDir "RESYNTH.cmd"
@"
@echo off
set RESYNTH_ROOT=$WorkDir
cd /d "$WorkDir"
"$AppDir\.venv\Scripts\resynth.exe" %*
if "%1"=="" pause
"@ | Set-Content -Path $launcher -Encoding ASCII

# 7. Desktop shortcut, with permission
$answer = Read-Host "Create a desktop shortcut so you can double click to launch? (Y/n)"
if ($answer -eq "" -or $answer -match "^[Yy]") {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "RESYNTH.lnk"))
    $lnk.TargetPath = $launcher
    $lnk.WorkingDirectory = $WorkDir
    $lnk.Description = "RESYNTH research consolidation"
    $lnk.Save()
    Write-Host "Desktop shortcut created." -ForegroundColor Green
}

# 8. Start Menu entry
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "RESYNTH.lnk"
$shell2 = New-Object -ComObject WScript.Shell
$sm = $shell2.CreateShortcut($startMenu)
$sm.TargetPath = $launcher
$sm.WorkingDirectory = $WorkDir
$sm.Save()

Write-Host ""
Write-Host "RESYNTH is installed." -ForegroundColor Green
Write-Host "Launch it from the desktop shortcut, the Start Menu, or by running:"
Write-Host "  $launcher" -ForegroundColor Cyan
Write-Host "Your research projects will live in $WorkDir"
