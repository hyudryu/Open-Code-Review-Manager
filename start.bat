@echo off
rem OpenCodeReview Manager - one-click launcher (Windows)
rem Double-click or run: start.bat [--build] [--port 8372]
setlocal
set "ROOT=%~dp0"

rem Forward launcher args to the PowerShell script.
set "PSARGS="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--build" (
    set "PSARGS=%PSARGS% -Build"
    shift
    goto parse_args
)
if /I "%~1"=="-build" (
    set "PSARGS=%PSARGS% -Build"
    shift
    goto parse_args
)
if /I "%~1"=="--port" (
    if "%~2"=="" (
        echo [start] ERROR: --port requires a value.
        pause
        exit /b 2
    )
    set "PSARGS=%PSARGS% -Port %~2"
    shift
    shift
    goto parse_args
)
echo [start] ERROR: unknown option "%~1".
pause
exit /b 2

:args_done

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
