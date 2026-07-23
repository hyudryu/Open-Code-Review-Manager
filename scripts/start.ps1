# Production startup — the ONE command (SPEC §2/§37):
#   powershell -ExecutionPolicy Bypass -File scripts/start.ps1
# Builds the frontend when needed, then runs `python -m app`, which serves the
# API + MCP + built UI on http://127.0.0.1:8787, applies DB migrations, and
# starts the queue and webhook workers.
#
# Options:
#   -Build   force a frontend rebuild even if frontend\dist exists
param(
    [switch]$Build
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "[start] creating backend virtualenv..."
    python -m venv backend\.venv
}

# Install backend deps if the package is not importable.
& $VenvPy -c "import app" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[start] installing backend dependencies..."
    & $VenvPy -m pip install -e "backend"
    if ($LASTEXITCODE -ne 0) { throw "backend dependency install failed" }
}

# Build the frontend when dist is missing (or -Build was passed).
if ($Build -or -not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    Write-Host "[start] building frontend..."
    if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
        Push-Location frontend; npm install; Pop-Location
    }
    Push-Location frontend; npm run build; Pop-Location
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
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

$port = $env:OCR_CC_PORT
if (-not $port) { $port = "8787" }
Write-Host "[start] OpenCodeReview Control Center → http://127.0.0.1:$port"
Set-Location (Join-Path $Root "backend")
& $VenvPy -m app
