#!/usr/bin/env bash
# XBow CyberRange platform launcher for Linux / macOS (mirror of start.bat)
#
# Usage:
#   ./start.sh                # dev mode: backend(uvicorn --reload) + frontend(vite)
#   ./start.sh --prod         # production: build frontend, run backend without --reload
#   ./start.sh --install-only # only install dependencies, do not start
#   ./start.sh --no-venv      # do not use a Python virtualenv
#   ./start.sh --no-build     # (with --prod) skip frontend build
#   ./start.sh -h | --help
#
# Make executable first:  chmod +x start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

MODE="dev"            # dev | prod
INSTALL_ONLY=false
USE_VENV=true
NO_BUILD=false
PYTHON=""
BACKEND_PID=""
FRONTEND_PID=""

# ---------- colors ----------
if [ -t 1 ]; then
  C_RESET=$'\033[0m';  C_CYAN=$'\033[36m';  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_RED=$'\033[31m';  C_BOLD=$'\033[1m'
else
  C_RESET=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""
fi

log()  { printf '%s[info]%s %s\n'  "$C_CYAN"   "$C_RESET" "$*"; }
ok()   { printf '%s[ok]%s %s\n'    "$C_GREEN"  "$C_RESET" "$*"; }
warn() { printf '%s[warn]%s %s\n'  "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%s[error]%s %s\n' "$C_RED"    "$C_RESET" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
XBow CyberRange launcher (Linux / macOS)

Usage: ./start.sh [options]

Options:
  --prod           Production mode: build frontend, run backend without --reload
  --install-only   Only install dependencies, do not start services
  --no-venv        Do not use a Python virtualenv (install to user/global env)
  --no-build       (with --prod) skip frontend build
  -h, --help       Show this help

Default (no args): dev mode — starts backend (uvicorn --reload) and frontend (vite),
                    mirroring start.bat on Windows.
EOF
}

# ---------- arg parsing ----------
while [ $# -gt 0 ]; do
  case "$1" in
    --prod)         MODE="prod"; shift;;
    --install-only) INSTALL_ONLY=true; shift;;
    --no-venv)      USE_VENV=false; shift;;
    --no-build)     NO_BUILD=true; shift;;
    -h|--help)      usage; exit 0;;
    *)              die "unknown option: $1 (try --help)";;
  esac
done

# ---------- prerequisites ----------
detect_python() {
  local cmd
  for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
        PYTHON="$cmd"
        ok "Python: $($PYTHON -V 2>&1)  ($PYTHON)"
        return 0
      fi
    fi
  done
  die "Python >= 3.10 not found. Install it first:
  Debian/Ubuntu:  sudo apt install python3 python3-venv
  macOS (brew):   brew install python@3.11"
}

detect_node() {
  if ! command -v node >/dev/null 2>&1; then
    die "Node.js not found. Install Node.js 18+:
  macOS:  brew install node   (or use nvm)
  Linux:  use nvm or your distro's Node 18+ package"
  fi
  local major
  major=$(node -v | sed 's/^v//' | cut -d. -f1)
  if [ "$major" -lt 18 ]; then
    die "Node.js >= 18 required (found $(node -v))."
  fi
  command -v npm >/dev/null 2>&1 || die "npm not found. Install Node.js 18+."
  ok "Node: $(node -v) , npm $(npm -v)"
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    die "Docker not found. Install Docker:
  Debian/Ubuntu:  https://docs.docker.com/engine/install/
  macOS:          brew install --cask docker   (then launch Docker Desktop)"
  fi
  if ! docker info >/dev/null 2>&1; then
    cat >&2 <<EOF
${C_RED}[error]${C_RESET} Cannot reach Docker daemon. Common fixes:
  - Linux:   start the service  ->  sudo systemctl start docker
             add your user       ->  sudo usermod -aG docker \$USER   (then log out & in)
  - macOS:   start the Docker Desktop app
EOF
    exit 1
  fi
  ok "Docker daemon reachable."
}

# ---------- setup ----------
setup_backend() {
  if [ "$USE_VENV" = true ]; then
    if [ ! -d "$VENV_DIR" ]; then
      log "creating virtualenv at backend/.venv ..."
      "$PYTHON" -m venv "$VENV_DIR"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PYTHON="python"          # venv's python is now on PATH
  fi

  if ! "$PYTHON" -c "import fastapi, docker" 2>/dev/null; then
    log "installing backend dependencies ..."
    "$PYTHON" -m pip install --upgrade pip >/dev/null
    "$PYTHON" -m pip install -r "$BACKEND_DIR/requirements.txt"
  else
    ok "backend dependencies present."
  fi

  # ensure .env exists
  if [ ! -f "$BACKEND_DIR/.env" ] && [ -f "$BACKEND_DIR/.env.example" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    warn "created backend/.env from .env.example."
    warn ">> For production, edit SECRET_KEY and the admin password! <<"
  fi
}

setup_frontend() {
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log "installing frontend dependencies ..."
    (cd "$FRONTEND_DIR" && npm install)
  else
    ok "frontend dependencies present."
  fi
}

# ---------- run ----------
cleanup() {
  echo
  log "stopping services ..."
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  [ -n "${BACKEND_PID:-}"  ] && kill "$BACKEND_PID"  2>/dev/null || true
  wait 2>/dev/null || true
}

start_dev() {
  log "starting backend  (uvicorn --reload @ http://0.0.0.0:8000) ..."
  (cd "$BACKEND_DIR" && "$PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
  BACKEND_PID=$!
  sleep 2
  log "starting frontend (vite @ http://0.0.0.0:5173) ..."
  (cd "$FRONTEND_DIR" && npm run dev) &
  FRONTEND_PID=$!

  trap cleanup EXIT INT TERM
  ok "started. Press Ctrl+C to stop both services."
  cat <<EOF
------------------------------------------------------------
  Frontend :  http://127.0.0.1:5173
  API docs :  http://127.0.0.1:8000/docs
  Login    :  admin / admin123   (change it ASAP)
------------------------------------------------------------
EOF
  wait
}

start_prod() {
  if [ "$NO_BUILD" != "true" ]; then
    log "building frontend (production) ..."
    (cd "$FRONTEND_DIR" && npm run build)
    ok "frontend built -> frontend/dist"
  fi
  log "starting backend in production mode (no --reload) ..."
  (cd "$BACKEND_DIR" && "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000) &
  BACKEND_PID=$!
  trap cleanup EXIT INT TERM
  cat <<EOF
------------------------------------------------------------
  Backend  :  http://0.0.0.0:8000
  API docs :  http://0.0.0.0:8000/docs
  Static   :  $FRONTEND_DIR/dist   (serve via nginx, see notes)
  Login    :  admin / admin123   (change it ASAP!)
------------------------------------------------------------
  Tip: serve frontend/dist with nginx and proxy /api -> :8000,
       set XBOW_CYBER_RANGE_CORS_ORIGINS in backend/.env accordingly.
------------------------------------------------------------
EOF
  wait
}

# ---------- main ----------
echo "${C_BOLD}==== XBow CyberRange launcher ====${C_RESET}  (mode=$MODE, venv=$USE_VENV)"
detect_python
detect_node
check_docker
setup_backend
setup_frontend

if [ "$INSTALL_ONLY" = true ]; then
  ok "dependencies installed. Run './start.sh' (dev) or './start.sh --prod' to start."
  exit 0
fi

if [ "$MODE" = "prod" ]; then
  start_prod
else
  start_dev
fi
