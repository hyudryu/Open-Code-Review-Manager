@echo off
rem OpenCodeReview Manager - one-click launcher (Windows)
rem Double-click or run: start.bat [--build]
setlocal
set "ROOT=%~dp0"

rem Forward --build to the PowerShell script's -Build switch.
set "PSARGS="
if /I "%~1"=="--build" set "PSARGS=-Build"
if /I "%~1"=="-build" set "PSARGS=-Build"

rem Prefer the full System32 path so a trimmed PATH cannot break the launch.
set "PS1=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PS1%" goto :run
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PS1=pwsh"
    goto :run
)
where powershell >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PS1=powershell"
    goto :run
)
echo [start] ERROR: neither powershell.exe nor pwsh was found on this system.
pause
exit /b 1

:run
"%PS1%" -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start.ps1" %PSARGS%
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [start] Launch failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)
endlocal
