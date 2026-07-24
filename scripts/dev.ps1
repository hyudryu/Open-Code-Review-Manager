# Development startup: backend (uvicorn --reload :8787) + frontend (vite :5173).
# Usage: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "[dev] creating backend virtualenv..."
    python -m venv backend\.venv
    & $VenvPy -m pip install -e "backend[dev]"
}

if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    Write-Host "[dev] installing frontend dependencies..."
    Push-Location frontend; npm install; Pop-Location
}

# Load root .env (OCR_CC_* overrides) if present.
if (Test-Path (Join-Path $Root ".env")) {
    Get-Content (Join-Path $Root ".env") | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        $pair = $_ -split '=', 2
        if ($pair.Count -eq 2) {
            [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), "Process")
        }
    }
}

Write-Host "[dev] backend  → http://127.0.0.1:8787 (uvicorn --reload)"
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $Root "backend") `
    -FilePath $VenvPy -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8787", "--reload"

try {
    Write-Host "[dev] frontend → http://localhost:5173 (vite, proxies /api and /mcp)"
    Push-Location frontend
    npm run dev
    Pop-Location
} finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
