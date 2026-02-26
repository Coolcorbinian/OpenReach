@echo off
setlocal enabledelayedexpansion
title OpenReach Installer
:: =========================================================================
::  OpenReach Standalone Installer
::  =========================================================================
::  This single file can be downloaded from https://cormass.com and run
::  directly. It will download the full installer from GitHub and execute it.
::
::  Copyright (c) 2026 Cormass Group -- MIT License
:: =========================================================================

:: Check for PowerShell
where powershell.exe >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo   ERROR: PowerShell is required but was not found on this system.
    echo   Please install PowerShell or use a Windows 10/11 machine.
    echo.
    pause
    exit /b 1
)

:: Create temp directory
set "TEMP_DIR=%TEMP%\openreach_bootstrap"
if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"

echo.
echo   ======================================================
echo     OpenReach Installer
echo     AI-Powered Browser Agent
echo   ======================================================
echo.
echo   Downloading installer from GitHub...
echo.

:: Download the setup.ps1 script from GitHub
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "try { " ^
    "  $wc = New-Object System.Net.WebClient; " ^
    "  $wc.Headers.Add('User-Agent', 'OpenReach-Installer/1.0'); " ^
    "  $wc.DownloadFile('https://raw.githubusercontent.com/Coolcorbinian/OpenReach/master/installer/setup.ps1', '%TEMP_DIR%\setup.ps1'); " ^
    "  Write-Host '  Download complete.' -ForegroundColor Green; " ^
    "} catch { " ^
    "  Write-Host \"  ERROR: Failed to download installer: $_\" -ForegroundColor Red; " ^
    "  exit 1; " ^
    "}"

if %errorlevel% neq 0 (
    echo.
    echo   ERROR: Could not download the installer from GitHub.
    echo   Please check your internet connection and try again.
    echo.
    echo   You can also install manually:
    echo   https://github.com/Coolcorbinian/OpenReach
    echo.
    pause
    exit /b 1
)

:: Also download the icon for the installer UI
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "try { " ^
    "  $wc = New-Object System.Net.WebClient; " ^
    "  $wc.Headers.Add('User-Agent', 'OpenReach-Installer/1.0'); " ^
    "  $wc.DownloadFile('https://raw.githubusercontent.com/Coolcorbinian/OpenReach/master/installer/openreach.ico', '%TEMP_DIR%\openreach.ico'); " ^
    "} catch { }" 2>nul

echo.
echo   Launching installer wizard...
echo.

:: Run the installer wizard
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TEMP_DIR%\setup.ps1"

set "EXIT_CODE=%errorlevel%"

:: Cleanup
if exist "%TEMP_DIR%\setup.ps1" del /q "%TEMP_DIR%\setup.ps1" 2>nul
if exist "%TEMP_DIR%\openreach.ico" del /q "%TEMP_DIR%\openreach.ico" 2>nul
rmdir "%TEMP_DIR%" 2>nul

if %EXIT_CODE% neq 0 (
    echo.
    echo   The installer encountered an issue.
    echo   Try running this file as Administrator:
    echo   Right-click ^> Run as administrator
    echo.
    pause
)

exit /b %EXIT_CODE%
