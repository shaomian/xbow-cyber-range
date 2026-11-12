#!/usr/bin/env bash
# XBow CyberRange platform manager (Linux / macOS) — background service mode
#
# Usage:
#   ./xbow.sh start [--prod] [--no-build] [--no-venv]   # dev mode by default
#   ./xbow.sh stop
#   ./xbow.sh restart [--prod] [--no-build] [--no-venv]
#   ./xbow.sh status
#   ./xbow.sh logs [backend|frontend] [-f|--follow]
#   ./xbow.sh install [--no-venv]
#   ./xbow.sh -h | --help
#
# Background mode: services run via nohup, survive SSH disconnect.
#   PID files : backend.pid / frontend.pid (repo root)
#   Logs      : backend/backend.log / frontend/frontend.log (append)
#
# Safety rules (do not regress):
#   - start refuses if the port is already occupied (double-start would
#     spawn a doomed process while the OLD one keeps serving stale code)
#   - stop only kills processes whose cmdline matches the expected marker
#     (uvicorn / npm-vite); a stale pid file never kills an innocent process
#   - stop TERM-waits up to 10s, then KILL; npm's vite child is killed too

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

BACKEND_LOG="$BACKEND_DIR/backend.log"
FRONTEND_LOG="$FRONTEND_DIR/frontend.log"
BACKEND_PID_FILE="$ROOT/backend.pid"
FRONTEND_PID_FILE="$ROOT/frontend.pid"

BACKEND_PORT=8000
FRONTEND_PORT=5173

CMD="start"
MODE="dev"            # dev | prod
USE_VENV=true
NO_BUILD=false
LOGS_FOLLOW=false
LOGS_TARGET="all"
PYTHON=""

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
XBow CyberRange platform manager (background mode)

Usage: ./xbow.sh <command> [options]

Commands:
  start      Start backend (and frontend in dev mode) in the background
  stop       Stop background services (validates PID first, never blind-kills)
  restart    stop + start
  status     Show running state of backend / frontend
  logs       Show logs: ./xbow.sh logs [backend|frontend] [-f|--follow]
  install    Only install dependencies, do not start anything

Options for start/restart:
  --prod         Production mode: build frontend, backend runs without --reload
  --no-build     (with --prod) skip frontend build
  --no-venv      Do not use a Python virtualenv

Default command is "start" in dev mode.
EOF
}

# ---------- arg parsing ----------
CMD="${1:-start}"
case "$CMD" in
  start|stop|restart|status|logs|install) shift || true;;
  -h|--help|help) usage; exit 0;;
  *) printf '[error] unknown command: %s (try --help)\n' "$CMD" >&2; exit 1;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    --prod)      MODE="prod"; shift;;
    --no-venv)   USE_VENV=false; shift;;
    --no-build)  NO_BUILD=true; shift;;
    -f|--follow) LOGS_FOLLOW=true; shift;;
    backend)     LOGS_TARGET="backend"; shift;;
    frontend)    LOGS_TARGET="frontend"; shift;;
    *)           die "unknown option: $1 (try --help)";;
  esac
done

# ---------- process helpers ----------
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

pid_cmdline() {
  local pid="$1"
  if [ -r "/proc/$pid/cmdline" ]; then
    tr '\000' ' ' < "/proc/$pid/cmdline"
  else
    ps -p "$pid" -o command= 2>/dev/null || true
  fi
}

pid_matches() {  # <pid> <regex>: only kill what we started
  local pid="$1" pattern="$2"
  pid_alive "$pid" || return 1
  pid_cmdline "$pid" | grep -qE "$pattern"
}

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":$port "
  elif command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | grep -i listen | grep -qE "[:.]$port[[:space:]]"
  else
    return 1
  fi
}

show_port_owner() {
  local port="$1"
  (ss -ltnp 2>/dev/null | grep ":$port ") || true
}

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
  die "Python >= 3.10 not found. Install it first."
}

detect_node() {
  if ! command -v node >/dev/null 2>&1; then
    die "Node.js not found. Install Node.js 18+."
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
    die "Docker not found. Install Docker first."
  fi
  if ! docker info >/dev/null 2>&1; then
    die "Cannot reach Docker daemon. Start docker service or add user to docker group."
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

  if ! "$PYTHON" -c "import fastapi, docker, mcp" 2>/dev/null; then
    log "installing backend dependencies ..."
    "$PYTHON" -m pip install --upgrade pip >/dev/null
    "$PYTHON" -m pip install -r "$BACKEND_DIR/requirements.txt"
  else
    ok "backend dependencies present."
  fi

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

# ---------- start ----------
start_backend() {
  local pid i
  if port_in_use "$BACKEND_PORT"; then
    if pid_matches "$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)" "uvicorn"; then
      die "backend already running (pid $(cat "$BACKEND_PID_FILE")). Use './xbow.sh restart' or 'stop'."
    fi
    warn "port $BACKEND_PORT is occupied by another process:"
    show_port_owner "$BACKEND_PORT"
    die "refusing to start backend on an occupied port."
  fi

  log "starting backend (uvicorn @ 0.0.0.0:$BACKEND_PORT, mode=$MODE) in background ..."
  cd "$BACKEND_DIR"
  if [ "$MODE" = "dev" ]; then
    nohup "$PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT" >> "$BACKEND_LOG" 2>&1 &
  else
    nohup "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" >> "$BACKEND_LOG" 2>&1 &
  fi
  echo $! > "$BACKEND_PID_FILE"
  cd "$ROOT"

  pid=$(cat "$BACKEND_PID_FILE")
  sleep 2
  pid_alive "$pid" || die "backend exited right after start; see $BACKEND_LOG"

  if command -v curl >/dev/null 2>&1; then
    for i in $(seq 1 30); do
      pid_alive "$pid" || die "backend exited during startup; see $BACKEND_LOG"
      if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
        ok "backend ready (pid $pid)."
        return 0
      fi
      sleep 1
    done
    warn "backend not ready after 30s; it may still be initializing — check: ./xbow.sh logs backend -f"
  else
    ok "backend started (pid $pid). (curl not found, skipping readiness check)"
  fi
}

start_frontend() {
  local pid i
  if port_in_use "$FRONTEND_PORT"; then
    if pid_matches "$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)" "npm|vite|node"; then
      die "frontend already running (pid $(cat "$FRONTEND_PID_FILE")). Use './xbow.sh restart' or 'stop'."
    fi
    warn "port $FRONTEND_PORT is occupied by another process:"
    show_port_owner "$FRONTEND_PORT"
    die "refusing to start frontend on an occupied port."
  fi

  log "starting frontend (vite @ 0.0.0.0:$FRONTEND_PORT) in background ..."
  cd "$FRONTEND_DIR"
  nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" >> "$FRONTEND_LOG" 2>&1 &
  echo $! > "$FRONTEND_PID_FILE"
  cd "$ROOT"

  pid=$(cat "$FRONTEND_PID_FILE")
  sleep 2
  pid_alive "$pid" || die "frontend exited right after start; see $FRONTEND_LOG"

  for i in $(seq 1 30); do
    pid_alive "$pid" || die "frontend exited during startup; see $FRONTEND_LOG"
    if port_in_use "$FRONTEND_PORT"; then
      ok "frontend ready (pid $pid)."
      return 0
    fi
    sleep 1
  done
  warn "frontend not listening after 30s; check: ./xbow.sh logs frontend -f"
}

# ---------- stop ----------
stop_one() {  # <pidfile> <marker-regex> <name> <port>
  local pidfile="$1" marker="$2" name="$3" port="$4"
  local pid i
  pid=$(cat "$pidfile" 2>/dev/null || true)
  if [ -n "$pid" ] && pid_matches "$pid" "$marker"; then
    log "stopping $name (pid $pid) ..."
    kill -TERM "$pid" 2>/dev/null || true
    # npm -> vite: children don't always get the signal, kill them too
    pkill -TERM -P "$pid" 2>/dev/null || true
    for i in $(seq 1 10); do
      pid_alive "$pid" || break
      sleep 1
    done
    if pid_alive "$pid"; then
      warn "$name did not exit in 10s, sending SIGKILL ..."
      kill -KILL "$pid" 2>/dev/null || true
      pkill -KILL -P "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
    if pid_alive "$pid"; then
      warn "$name (pid $pid) did not die even after SIGKILL; check manually."
    else
      ok "$name stopped."
    fi
  else
    rm -f "$pidfile" 2>/dev/null || true
    if port_in_use "$port"; then
      warn "$name: pid file stale/absent and port $port is held by an unknown process — NOT killing it:"
      show_port_owner "$port"
    else
      ok "$name not running."
    fi
  fi
}

# ---------- commands ----------
cmd_stop() {
  stop_one "$BACKEND_PID_FILE" "uvicorn" "backend" "$BACKEND_PORT"
  stop_one "$FRONTEND_PID_FILE" "npm|vite|node" "frontend" "$FRONTEND_PORT"
}

cmd_status() {
  local pid
  pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)
  if [ -n "$pid" ] && pid_matches "$pid" "uvicorn"; then
    ok "backend : running (pid $pid)"
  elif port_in_use "$BACKEND_PORT"; then
    warn "backend : pid file stale/absent, but port $BACKEND_PORT is held by an unknown process:"
    show_port_owner "$BACKEND_PORT"
  else
    log "backend : stopped"
  fi
  pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)
  if [ -n "$pid" ] && pid_matches "$pid" "npm|vite|node"; then
    ok "frontend: running (pid $pid)"
  elif port_in_use "$FRONTEND_PORT"; then
    warn "frontend: pid file stale/absent, but port $FRONTEND_PORT is held by an unknown process:"
    show_port_owner "$FRONTEND_PORT"
  else
    log "frontend: stopped"
  fi
  log "logs: $BACKEND_LOG / $FRONTEND_LOG  (./xbow.sh logs -f)"
}

cmd_logs() {
  local follow_args=""
  if [ "$LOGS_FOLLOW" = true ]; then
    follow_args="-f"
  fi
  case "$LOGS_TARGET" in
    backend)
      [ -f "$BACKEND_LOG" ] || { warn "no log yet: $BACKEND_LOG"; return 0; }
      tail -n 50 $follow_args "$BACKEND_LOG"
      ;;
    frontend)
      [ -f "$FRONTEND_LOG" ] || { warn "no log yet: $FRONTEND_LOG"; return 0; }
      tail -n 50 $follow_args "$FRONTEND_LOG"
      ;;
    *)
      if [ "$LOGS_FOLLOW" = true ]; then
        for f in "$BACKEND_LOG" "$FRONTEND_LOG"; do
          [ -f "$f" ] || warn "no log yet: $f"
        done
        exec tail -n 50 -f "$BACKEND_LOG" "$FRONTEND_LOG"
      else
        local f
        for f in "$BACKEND_LOG" "$FRONTEND_LOG"; do
          echo "===== $f ====="
          if [ -f "$f" ]; then tail -n 50 "$f"; else echo "(no log yet)"; fi
        done
      fi
      ;;
  esac
}

cmd_start() {
  detect_python
  check_docker
  setup_backend
  if [ "$MODE" = "dev" ]; then
    detect_node
    setup_frontend
  elif [ "$NO_BUILD" != "true" ]; then
    detect_node
    setup_frontend
    log "building frontend (production) ..."
    (cd "$FRONTEND_DIR" && npm run build)
    ok "frontend built -> frontend/dist"
  fi

  start_backend
  if [ "$MODE" = "dev" ]; then
    start_frontend
  fi

  if [ "$MODE" = "dev" ]; then
    cat <<EOF
------------------------------------------------------------
  Frontend :  http://127.0.0.1:$FRONTEND_PORT
  API docs :  http://127.0.0.1:$BACKEND_PORT/docs
  Login    :  admin / admin123   (change it ASAP)

  logs     :  ./xbow.sh logs -f
  status   :  ./xbow.sh status
  stop     :  ./xbow.sh stop
------------------------------------------------------------
EOF
  else
    cat <<EOF
------------------------------------------------------------
  Backend  :  http://0.0.0.0:$BACKEND_PORT
  API docs :  http://0.0.0.0:$BACKEND_PORT/docs
  Static   :  $FRONTEND_DIR/dist   (serve via nginx, see notes)
  Login    :  admin / admin123   (change it ASAP!)

  logs     :  ./xbow.sh logs backend -f
  status   :  ./xbow.sh status
  stop     :  ./xbow.sh stop
  Tip: serve frontend/dist with nginx and proxy /api -> :$BACKEND_PORT,
       set XBOW_CYBER_RANGE_CORS_ORIGINS in backend/.env accordingly.
------------------------------------------------------------
EOF
  fi
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

cmd_install() {
  detect_python
  check_docker
  setup_backend
  detect_node
  setup_frontend
  ok "dependencies installed. Run './xbow.sh start' (dev) or './xbow.sh start --prod'."
}

# ---------- main ----------
case "$CMD" in
  start)   cmd_start;;
  stop)    cmd_stop;;
  restart) cmd_restart;;
  status)  cmd_status;;
  logs)    cmd_logs;;
  install) cmd_install;;
  *)       usage; exit 1;;
esac
