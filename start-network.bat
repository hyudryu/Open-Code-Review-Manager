@echo off
rem OpenCodeReview Manager — network-facing launcher (0.0.0.0)
rem Binds on all interfaces so the UI is reachable from other machines.
rem Uses port 8373 (different from the default 8372) to run alongside
rem a local instance without conflict.
rem Uses a separate data directory (network-data) to avoid instance lock.
rem
rem Double-click or run: start-network.bat [--port 8373] [--build]

setlocal

set "ROOT=%~dp0"

rem Parse optional --port and --build flags.
set "PORT="
set "BUILD="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--build" (
    set "BUILD=1"
    shift
    goto parse_args
)
if /I "%~1"=="--port" (
    if "%~2"=="" (
        echo [start-network] ERROR: --port requires a value.
        pause
        exit /b 2
    )
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
echo [start-network] ERROR: unknown option "%~1".
pause
exit /b 2

:args_done

rem Default port if not overridden.
if not defined PORT set PORT=8373

rem Use a separate data directory for the network instance to avoid conflicts
set "NETWORK_DATA_DIR=%ROOT%network-data"

rem Create the network data directory if it doesn't exist
if not exist "%NETWORK_DATA_DIR%" mkdir "%NETWORK_DATA_DIR%"

set "VENV_PY=%ROOT%backend\.venv\Scripts\python.exe"

rem Build frontend if --build was passed and dist is missing.
if defined BUILD (
    if not exist "%ROOT%frontend\dist\index.html" (
        echo [start-network] building frontend...
        pushd "%ROOT%frontend"
        if not exist "node_modules" npm install
        npm run build
        popd
    )
)

echo [start-network] OpenCodeReview Manager -> http://0.0.0.0:%PORT%
echo [start-network] (accessible from other machines on the network)
echo [start-network] (data directory: %NETWORK_DATA_DIR%)
echo [start-network] Ctrl-C to stop.

rem Launch the server bound to 0.0.0.0 (all interfaces) on the chosen port
rem with a separate data directory to avoid instance lock conflicts
rem Set OCR_CC_ALLOW_ALL_ORIGINS=true to accept CORS from any origin
rem (needed when accessed from other machines on the network)
set "OCR_CC_DATA_DIR=%NETWORK_DATA_DIR%"
set "OCR_CC_ALLOW_ALL_ORIGINS=true"
"%VENV_PY%" -m app --host 0.0.0.0 --port %PORT%

endlocal
