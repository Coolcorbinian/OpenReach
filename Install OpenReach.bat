@echo off
title OpenReach Installer
:: This wrapper launches the PowerShell installer wizard.
:: It bypasses execution policy so non-technical users don't hit blocks.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\setup.ps1"
if %errorlevel% neq 0 (
    echo.
    echo   Something went wrong. Please try running as Administrator.
    echo   Right-click "Install OpenReach.bat" and choose "Run as administrator"
    echo.
    pause
)
