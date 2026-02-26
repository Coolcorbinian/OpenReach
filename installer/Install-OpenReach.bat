@echo off
setlocal enabledelayedexpansion
title OpenReach Installer
color 0F
mode con: cols=80 lines=30

echo.
echo   ============================================================
echo.
echo     OPENREACH - One-Click Installer
echo.
echo   ============================================================
echo.
echo   This will download and install OpenReach on your computer.
echo.
echo   What gets installed:
echo     - Python 3.13 (if not already installed)
echo     - OpenReach application from GitHub
echo     - Chromium browser engine for automation
echo     - Ollama AI runtime (optional, if selected)
echo.
echo   Total download: 0.5-5 GB  ^|  Time: 5-20 minutes
echo   Requires: Windows 10/11, 4 GB RAM, 2 GB disk space
echo.
echo   Press any key to start, or close this window to cancel.
echo.
pause >nul

echo.
echo   [1/2] Downloading installer script from GitHub...
echo.

:: ---------------------------------------------------------------------------
:: Download the full GUI installer (setup.ps1) from the OpenReach repository
:: and run it. This keeps the standalone installer tiny while leveraging the
:: full wizard experience with progress bars and component detection.
:: ---------------------------------------------------------------------------

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
  "$setupDir = Join-Path $env:TEMP 'openreach_bootstrap'; " ^
  "New-Item -ItemType Directory -Path $setupDir -Force | Out-Null; " ^
  "$setupPath = Join-Path $setupDir 'setup.ps1'; " ^
  "Write-Host '  Downloading...' -ForegroundColor Cyan; " ^
  "try { " ^
  "  $headers = @{ 'User-Agent'='OpenReach-Installer/1.0'; 'Accept'='application/vnd.github.v3.raw' }; " ^
  "  Invoke-WebRequest -Uri 'https://api.github.com/repos/Coolcorbinian/OpenReach/contents/installer/setup.ps1?ref=master' -Headers $headers -OutFile $setupPath -UseBasicParsing; " ^
  "} catch { " ^
  "  Write-Host ''; " ^
  "  Write-Host '  Download failed. Please check your internet connection.' -ForegroundColor Red; " ^
  "  Write-Host \"  Error: $_\" -ForegroundColor DarkGray; " ^
  "  Read-Host '  Press Enter to exit'; " ^
  "  exit 1; " ^
  "} " ^
  "if (-not (Test-Path $setupPath)) { " ^
  "  Write-Host '  Download failed - file not found.' -ForegroundColor Red; " ^
  "  Read-Host '  Press Enter to exit'; " ^
  "  exit 1; " ^
  "} " ^
  "Write-Host '  [2/2] Launching installer wizard...' -ForegroundColor Cyan; " ^
  "Write-Host ''; " ^
  "& $setupPath; " ^
  "$exitCode = $LASTEXITCODE; " ^
  "Remove-Item $setupDir -Recurse -Force -ErrorAction SilentlyContinue; " ^
  "exit $exitCode"

if %errorlevel% neq 0 (
    echo.
    echo   Something went wrong. Please try one of the following:
    echo.
    echo   1. Right-click this file and choose "Run as administrator"
    echo   2. Make sure you have an active internet connection
    echo   3. Visit https://github.com/Coolcorbinian/OpenReach for help
    echo.
    pause
)
