@echo off
setlocal enabledelayedexpansion
title OpenReach - Starting...
color 0F
mode con: cols=90 lines=35

echo.
echo   ============================================================
echo.
echo     OPENREACH - Social Media Outreach Agent
echo.
echo   ============================================================
echo.
echo   Starting up... Please wait.
echo.

:: ---------------------------------------------------------------
:: 1. Find Python 3.11+
:: ---------------------------------------------------------------
set "PY="

:: Try each Python candidate; if found but version too low, continue
:: trying the next candidate instead of giving up.

where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
    echo   [CHECK] Found %PY_VER%
    python -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
    if !errorlevel!==0 (
        set "PY=python"
        goto :python_ok
    )
    echo   [CHECK] %PY_VER% is too old, trying next...
)

where python3 >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%i in ('python3 --version 2^>^&1') do set PY_VER=%%i
    echo   [CHECK] Found %PY_VER%
    python3 -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
    if !errorlevel!==0 (
        set "PY=python3"
        goto :python_ok
    )
    echo   [CHECK] %PY_VER% is too old, trying next...
)

where py >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%i in ('py -3 --version 2^>^&1') do set PY_VER=%%i
    echo   [CHECK] Found %PY_VER% ^(py launcher^)
    py -3 -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
    if !errorlevel!==0 (
        set "PY=py -3"
        goto :python_ok
    )
    echo   [CHECK] %PY_VER% is too old.
)

:: None of the candidates met the version requirement
echo.
echo   [ERROR] Python 3.11 or newer is required.
if defined PY_VER echo           Best found: %PY_VER%
echo.
echo   Download Python: https://www.python.org/downloads/
echo.
echo   IMPORTANT: During installation, check the box that says
echo              "Add Python to PATH"
echo.
pause
exit /b 1

:python_ok
echo   [  OK ] Using %PY% (%PY_VER%)

:: ---------------------------------------------------------------
:: 2. Create virtual environment if needed
:: ---------------------------------------------------------------
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo   [SETUP] Creating virtual environment...
    %PY% -m venv "%~dp0.venv"
    if %errorlevel% neq 0 (
        echo.
        echo   [ERROR] Failed to create virtual environment.
        echo           Try running: %PY% -m venv .venv
        echo.
        pause
        exit /b 1
    )
    echo   [SETUP] Virtual environment created.
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "VENV_PIP=%~dp0.venv\Scripts\pip.exe"

:: ---------------------------------------------------------------
:: 3. Install / update dependencies
:: ---------------------------------------------------------------
if not exist "%~dp0.venv\.deps_installed" (
    echo   [SETUP] Installing dependencies ^(first run, may take a minute^)...
    "%VENV_PIP%" install --quiet --upgrade pip >nul 2>&1
    "%VENV_PIP%" install --quiet -r "%~dp0requirements.txt"
    if %errorlevel% neq 0 (
        echo.
        echo   [ERROR] Failed to install dependencies.
        echo           Check your internet connection and try again.
        echo.
        echo   You can also try manually:
        echo     .venv\Scripts\pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo done > "%~dp0.venv\.deps_installed"
    echo   [SETUP] Dependencies installed.
) else (
    echo   [CHECK] Dependencies already installed.
)

:: ---------------------------------------------------------------
:: 4. Install Playwright browser if needed
:: ---------------------------------------------------------------
if not exist "%~dp0.venv\.pw_installed" (
    echo   [SETUP] Installing browser engine ^(first run, may take a minute^)...
    "%VENV_PY%" -m playwright install chromium >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo   [WARNING] Could not install Playwright browser automatically.
        echo             The agent will try again when you start a campaign.
        echo.
    ) else (
        echo done > "%~dp0.venv\.pw_installed"
        echo   [SETUP] Browser engine installed.
    )
) else (
    echo   [CHECK] Browser engine ready.
)

:: ---------------------------------------------------------------
:: 5. Hand off to the Python launcher (handles Ollama + startup)
:: ---------------------------------------------------------------
echo.
echo   [START] Launching OpenReach...
echo.

"%VENV_PY%" "%~dp0openreach\launcher.py"
set LAUNCH_ERR=%errorlevel%

if %LAUNCH_ERR% neq 0 (
    echo.
    echo   ============================================================
    echo   OpenReach exited with an error ^(code %LAUNCH_ERR%^).
    echo   If you need help, visit:
    echo     https://github.com/Coolcorbinian/OpenReach/issues
    echo   ============================================================
    echo.
)

echo.
echo   Press any key to close this window...
pause >nul
