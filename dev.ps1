param([switch]$SetupOnly)

$VENV_DIR = "venv"
$BACKEND_PORT = 8000
$FRONTEND_PORT = 5173

function Print-Header { Write-Host "`n=== $args ===" -ForegroundColor Cyan }
function Print-Info  { Write-Host "  $args" -ForegroundColor Gray }
function Print-Ok    { Write-Host "  [OK] $args" -ForegroundColor Green }
function Print-Do    { Write-Host "  >>> $args" -ForegroundColor Yellow }

# Python venv
Print-Header "Python environment"
if (-not (Test-Path "$VENV_DIR\Scripts\python.exe")) {
    Print-Do "Creating venv..."
    python -m venv $VENV_DIR
}
. "$VENV_DIR\Scripts\Activate.ps1"
Print-Ok "venv activated"

# Python deps (cache-bust by requirements.txt hash)
$reqHashFile = ".requirements.hash"
$reqHash = (Get-FileHash "requirements.txt" -Algorithm MD5).Hash
$prevHash = ""
if (Test-Path $reqHashFile) { $prevHash = (Get-Content $reqHashFile -Raw).Trim() }

if ($reqHash -ne $prevHash) {
    Print-Do "Installing Python dependencies..."
    pip install -r requirements.txt | Out-Null
    $reqHash | Set-Content $reqHashFile
    Print-Ok "Dependencies installed"
} else {
    Print-Ok "Dependencies up to date"
}

# Playwright browsers
python -c "import playwright" 2>$null
if ($LASTEXITCODE -ne 0) {
    Print-Do "Installing Playwright browsers..."
    playwright install chromium | Out-Null
    Print-Ok "Playwright chromium installed"
}

# Frontend deps
Print-Header "Frontend environment"
if (-not (Test-Path "frontend\node_modules\.package-lock.json")) {
    Print-Do "Installing frontend dependencies..."
    Push-Location frontend
    npm install | Out-Null
    Pop-Location
    Print-Ok "Frontend dependencies installed"
} else {
    Print-Ok "Frontend dependencies up to date"
}

# Start servers
Print-Header "Starting servers"
Print-Info "Backend:  http://127.0.0.1:$BACKEND_PORT"
Print-Info "Frontend: http://127.0.0.1:$FRONTEND_PORT"
Write-Host ""

if ($SetupOnly) {
    Write-Host "Setup complete. Run .\dev.ps1 to start servers."
    exit 0
}

$beJob = Start-Job -Name "leadops-backend" -ScriptBlock {
    param($Dir, $Port)
    Set-Location $Dir
    & "venv\Scripts\python.exe" -m uvicorn backend.core.server:app --reload --host 0.0.0.0 --port $Port
} -ArgumentList (Get-Location).Path, $BACKEND_PORT

try {
    Push-Location frontend
    npm run dev
} finally {
    Pop-Location
    Print-Info "Stopping backend..."
    Stop-Job $beJob -ErrorAction SilentlyContinue
    Remove-Job $beJob -ErrorAction SilentlyContinue
    Print-Ok "Stopped"
}
