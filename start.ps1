# AI Studio - launcher for Windows (PowerShell 5+). Double-click start.bat.
#
#   .\start.ps1               dev mode: backend (auto-reload) + Vite dev server
#   .\start.ps1 -Prod         builds the UI once, everything served on one port
#
# Options: -BackendPort 8000 -FrontendPort 5173 -NoBrowser -TorchVariant cuda|cpu
param(
    [switch]$Prod,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$NoBrowser,
    [ValidateSet('', 'cuda', 'cpu')][string]$TorchVariant = ''
)
$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Venv = Join-Path $Backend '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'

function Say($m) { Write-Host "[ai-studio] $m" -ForegroundColor Magenta }
function Warn($m) { Write-Host "[warn] $m" -ForegroundColor Yellow }
function Die($m) { Write-Host "[error] $m" -ForegroundColor Red; Read-Host 'Press Enter to exit'; exit 1 }
function Hash($path) { (Get-FileHash -Algorithm SHA256 $path).Hash }
# Run a native command quietly; $true when it exits with 0. Never throws
# (PowerShell 5 turns redirected stderr into errors under 'Stop').
function Probe([string]$exe, [string[]]$cmdArgs) {
    try {
        $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        & $exe @cmdArgs *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false } finally { $ErrorActionPreference = $old }
}

Write-Host "=== AI Studio ($(if ($Prod) { 'prod' } else { 'dev' })) ==="

# -- Python 3.10 - 3.12 (PyTorch 2.4 has no wheels for newer versions) ---------
$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in '3.12', '3.11', '3.10') {
        if (Probe 'py' @("-$v", '-c', 'import sys')) { $Python = @('py', "-$v"); break }
    }
}
if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Probe 'python' @('-c', 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)')) {
        $Python = @('python')
    }
}
if (-not $Python) { Die 'Python 3.10, 3.11 or 3.12 is required: https://www.python.org/downloads/ (tick "Add to PATH").' }

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die 'Node.js 18+ is required: https://nodejs.org' }
$NodeMajor = [int]((node -p 'process.versions.node.split(".")[0]'))
if ($NodeMajor -lt 18) { Die "Node.js 18+ is required (found $(node -v))." }

# -- Backend environment -------------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    Say 'Creating Python virtual environment...'
    $exe = $Python[0]; $pyArgs = @($Python | Select-Object -Skip 1) + @('-m', 'venv', $Venv)
    & $exe @pyArgs
    if ($LASTEXITCODE -ne 0) { Die 'venv creation failed.' }
}

if (-not $TorchVariant) {
    $TorchVariant = 'cpu'
    if ((Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and (Probe 'nvidia-smi' @())) {
        $TorchVariant = 'cuda'
    }
}

$Req = Join-Path $Backend 'requirements.txt'
$Stamp = Join-Path $Venv ".requirements-$TorchVariant.sha"
$Want = Hash $Req
if (-not (Test-Path $Stamp) -or (Get-Content $Stamp -Raw).Trim() -ne $Want) {
    Say "Installing backend dependencies (PyTorch: $TorchVariant) - the first run takes a while..."
    & $VenvPy -m pip install --upgrade pip | Out-Null
    if ($TorchVariant -eq 'cuda') {
        & $VenvPy -m pip install -r $Req --extra-index-url https://download.pytorch.org/whl/cu121
    } else {
        # CPU-only: smaller torch wheels, and skip GPU-only packages.
        $TmpReq = Join-Path $env:TEMP 'aistudio-req-cpu.txt'
        Get-Content $Req | Where-Object { $_ -notmatch '^xformers' -and $_ -notmatch '^onnxruntime==.*darwin' } |
            ForEach-Object { $_ -replace '^onnxruntime-gpu==([^;]*);.*', 'onnxruntime==$1' } |
            Set-Content -Encoding ascii $TmpReq
        & $VenvPy -m pip install -r $TmpReq --extra-index-url https://download.pytorch.org/whl/cpu
    }
    if ($LASTEXITCODE -ne 0) { Die 'Dependency installation failed (see the messages above).' }
    Set-Content -Path $Stamp -Value $Want
}

$EnvFile = Join-Path $Backend '.env'
if (-not (Test-Path $EnvFile) -and (Test-Path "$EnvFile.example")) {
    Copy-Item "$EnvFile.example" $EnvFile
    Say 'Created backend\.env from the example (edit it to add tokens).'
}

# -- Frontend environment ------------------------------------------------------
$NpmStamp = Join-Path $Frontend 'node_modules\.lock.sha'
$NpmWant = Hash (Join-Path $Frontend 'package-lock.json')
if (-not (Test-Path $NpmStamp) -or (Get-Content $NpmStamp -Raw).Trim() -ne $NpmWant) {
    Say 'Installing frontend packages...'
    Push-Location $Frontend
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { npm install --no-audit --no-fund }
    Pop-Location
    Set-Content -Path $NpmStamp -Value $NpmWant
}

# -- Optional services ---------------------------------------------------------
$OllamaUrl = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { 'http://localhost:11434' }
try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$OllamaUrl/api/tags" | Out-Null }
catch { Warn "Ollama not reachable at $OllamaUrl - the Agent tab needs it (https://ollama.com, then: ollama pull llama3.2)." }

function PortBusy($port) {
    try { return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
    catch { return $false }
}
if (PortBusy $BackendPort) { Die "Port $BackendPort is already in use (use -BackendPort)." }

# -- Launch --------------------------------------------------------------------
$env:BACKEND_PORT = "$BackendPort"
$env:FRONTEND_PORT = "$FrontendPort"
$procs = @()
try {
    if ($Prod) {
        Say 'Building the UI...'
        Push-Location $Frontend; npm run build; $ok = $LASTEXITCODE -eq 0; Pop-Location
        if (-not $ok) { Die 'UI build failed.' }
        $Url = "http://localhost:$BackendPort"
        $procs += Start-Process -PassThru -NoNewWindow -WorkingDirectory $Backend -FilePath $VenvPy `
            -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', "$BackendPort"
    } else {
        if (PortBusy $FrontendPort) { Die "Port $FrontendPort is already in use (use -FrontendPort)." }
        $Url = "http://localhost:$FrontendPort"
        $procs += Start-Process -PassThru -NoNewWindow -WorkingDirectory $Backend -FilePath $VenvPy `
            -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', "$BackendPort", `
            '--reload', '--reload-dir', '.', '--reload-exclude', '.venv'
        $procs += Start-Process -PassThru -NoNewWindow -WorkingDirectory $Frontend -FilePath 'node' `
            -ArgumentList 'node_modules\vite\bin\vite.js', '--port', "$FrontendPort", '--strictPort'
    }

    # Wait for the API, then open the browser.
    for ($i = 0; $i -lt 120; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 "http://127.0.0.1:$BackendPort/health" | Out-Null; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    Write-Host ''
    Say "Ready -> $Url   (API docs: http://localhost:$BackendPort/docs)"
    Say 'Close this window or press Ctrl+C to stop.'
    if (-not $NoBrowser) { Start-Process $Url }

    # Stop everything as soon as one server exits.
    while (-not ($procs | Where-Object { $_.HasExited })) { Start-Sleep -Seconds 1 }
}
finally {
    Say 'Stopping...'
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) {
            # /T also stops the reloader's child processes.
            Probe 'taskkill' @('/PID', "$($p.Id)", '/T', '/F') | Out-Null
        }
    }
}
