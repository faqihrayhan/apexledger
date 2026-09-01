# ApexLedger — one-command installer (Windows PowerShell).
#
#   irm https://raw.githubusercontent.com/faqihrayhan/apexledger/main/install.ps1 | iex
#
# What it does:
#   1. Clones (or updates) the repo to ~\apexledger
#   2. Creates an isolated Python venv and installs the backend
#   3. Runs `apexledger init` — Postgres container + database + migrations
#   4. Prints how to start the server (`apexledger serve`)
#
# Requirements: git, Python 3.11+, Docker Desktop (for the database).

$ErrorActionPreference = "Stop"

$RepoUrl    = "${env:REPO_URL -as [string]}"
if (-not $RepoUrl) { $RepoUrl = "https://github.com/faqihrayhan/apexledger.git" }
$InstallDir = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { "$HOME\apexledger" }
$Branch     = if ($env:BRANCH)     { $env:BRANCH }     else { "main" }

function Say($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Okay($msg) { Write-Host $msg    -ForegroundColor Green }
function Die($msg)  { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

Say "ApexLedger installer (Community Edition)"

foreach ($tool in @("git", "python", "docker")) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    Die "'$tool' is required but not installed."
  }
}

try { docker info | Out-Null } catch {
  Die "Docker Desktop is installed but not running. Start it and re-run."
}

$pyv = (& python -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))")
if ((& python -c "import sys; print(1 if sys.version_info >= (3,11) else 0)") -ne "1") {
  Die "Python 3.11+ required, found $pyv."
}

Say "Requirements OK (python $pyv)"

if (Test-Path "$InstallDir\.git") {
  Say "Updating existing checkout at $InstallDir"
  git -C $InstallDir fetch --quiet origin
  git -C $InstallDir reset --quiet --hard "origin/$Branch"
} else {
  Say "Cloning ApexLedger to $InstallDir"
  git clone --depth 1 --branch $Branch $RepoUrl $InstallDir
}

if (-not (Test-Path "$InstallDir\backend\.venv\Scripts\python.exe")) {
  Say "Creating virtual environment (backend\.venv)"
  Push-Location "$InstallDir\backend"
  python -m venv .venv
  Pop-Location
}

Say "Installing backend dependencies"
& "$InstallDir\backend\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$InstallDir\backend\.venv\Scripts\python.exe" -m pip install --quiet -e "$InstallDir\backend"

Say "Initializing database (container + migrations)"
Push-Location "$InstallDir\backend"
& ".\.venv\Scripts\python.exe" cli.py init
Pop-Location

Okay ""
Okay "ApexLedger installed at: $InstallDir"
Okay ""
Okay "Start the server:"
Say  "  $InstallDir\backend\.venv\Scripts\python.exe cli.py serve"
Okay "Then open http://localhost:8000 — the setup wizard appears on first visit."
Okay ""
Say "Desktop app (karyawan pabrik): install ApexLedger_*.msi / .exe,"
Say "lalu isi IP server pabrik: http://<ip-server-pabrik>:8000"
