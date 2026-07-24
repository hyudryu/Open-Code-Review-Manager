@echo off
rem OpenCodeReview Control Center - one-click launcher (Windows)
rem Double-click or run: start.bat [--build]
setlocal
set "ROOT=%~dp0"

rem Forward --build to the PowerShell script's -Build switch.
set "PSARGS="
if /I "%~1"=="--build" set "PSARGS=-Build"
if /I "%~1"=="-build" set "PSARGS=-Build"

where powershell >nul 2>nul
if %ERRORLEVEL%==0 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start.ps1" %PSARGS%
) else (
    pwsh -NoProfile -File "%ROOT%scripts\start.ps1" %PSARGS%
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [start] Launch failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)
endlocal
