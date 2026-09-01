#!/usr/bin/env bash
#
# ApexLedger — one-command installer (Linux / macOS / WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/faqihrayhan/apexledger/main/install.sh | bash
#
# What it does:
#   1. Clones (or updates) the repo to ~/apexledger
#   2. Creates an isolated Python venv and installs the backend
#   3. Runs `apexledger init` — Postgres container + database + migrations
#   4. Prints how to start the server (`apexledger serve`)
#
# Requirements: git, python3 (>=3.11), docker (for the database container).
# Safe to re-run — every step is idempotent.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/faqihrayhan/apexledger.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/apexledger}"
BRANCH="${BRANCH:-main}"

blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }

# --- Preflight ---------------------------------------------------------------

say()  { blue "==> $*"; }
die()  { red "ERROR: $*"; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed. $2"
}

say "ApexLedger installer (Community Edition)"

need git    "Install it from https://git-scm.com/downloads"
need python3 "Version 3.11 or newer required."
need docker  "Docker runs the database container. https://docs.docker.com/get-docker/"

# Docker daemon reachable?
if ! docker info >/dev/null 2>&1; then
  die "Docker is installed but not running. Start Docker Desktop (or 'systemctl start docker') and re-run."
fi

PYV="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" \
  || die "Python 3.11+ required, found $PYV."

say "Requirements OK (python $PYV, docker $(docker --version | cut -d, -f1 | cut -d' ' -f3))"

# --- Clone or update -----------------------------------------------------------

if [ -d "$INSTALL_DIR/.git" ]; then
  say "Updating existing checkout at $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --quiet origin
  git -C "$INSTALL_DIR" reset --quiet --hard "origin/$BRANCH"
else
  say "Cloning ApexLedger to $INSTALL_DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

# --- Python environment --------------------------------------------------------

if [ ! -x "$INSTALL_DIR/backend/.venv/bin/python" ]; then
  say "Creating virtual environment (backend/.venv)"
  (cd "$INSTALL_DIR/backend" && python3 -m venv .venv)
fi

say "Installing backend dependencies"
"$INSTALL_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/backend/.venv/bin/pip" install --quiet -e "$INSTALL_DIR/backend"

# --- Database + migrations -----------------------------------------------------

say "Initializing database (container + migrations)"
(cd "$INSTALL_DIR/backend" && ./.venv/bin/python cli.py init)

# --- Done ----------------------------------------------------------------------

green ""
green "ApexLedger installed at: $INSTALL_DIR"
green ""
green "Start the server:"
blue "  $INSTALL_DIR/backend/.venv/bin/python cli.py serve"
green ""
green "Then open http://localhost:8000 in your browser —"
green "the setup wizard appears on first visit."
green ""
blue "Desktop app (karyawan pabrik):"
blue "  install ApexLedger_*.msi / .exe / .dmg / .AppImage, lalu isi IP server:"
blue "  http://<ip-server-pabrik>:8000"
