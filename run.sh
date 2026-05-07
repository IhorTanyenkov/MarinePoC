#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${PORT_TARIFF_BUILD_DIR:-$ROOT/build}"
API_PORT="${PORT_TARIFF_API_PORT:-8787}"
WEB_PORT="${PORT_TARIFF_WEB_PORT:-5179}"
RUN_DIR="$ROOT/.run"
LOG_DIR="$ROOT/.logs"
RUNTIME_DIR="${PORT_TARIFF_RUNTIME:-$ROOT/.runtime}"

mkdir -p "$RUN_DIR" "$LOG_DIR" "$RUNTIME_DIR"

cleanup() {
  echo
  echo "Stopping Port Tariff Agent PoC..."
  if [ -n "${API_PID:-}" ] && kill -0 "$API_PID" >/dev/null 2>&1; then
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${WEB_PID:-}" ] && kill -0 "$WEB_PID" >/dev/null 2>&1; then
    kill "$WEB_PID" >/dev/null 2>&1 || true
  fi
  rm -f "$RUN_DIR/api.pid" "$RUN_DIR/web.pid"
}
trap cleanup EXIT INT TERM

echo "Configuring/building Port Tariff core..."
cmake -S "$ROOT" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DFETCHCONTENT_UPDATES_DISCONNECTED=ON
cmake --build "$BUILD_DIR" --target port_tariff_core -j "${PORT_TARIFF_BUILD_JOBS:-4}"

if ! python3 - <<'PY' >/dev/null 2>&1
import fastapi
import uvicorn
import PyPDF2
import multipart
PY
then
  echo "Installing Python API dependencies..."
  python3 -m pip install -r "$ROOT/api/requirements.txt"
fi

(
  cd "$ROOT/web"
  if [ ! -e node_modules ]; then
    echo "Installing web dependencies..."
    npm install
  fi
)

echo "Starting FastAPI backend..."
PYTHONPATH="$ROOT/api" \
PORT_TARIFF_CORE_BIN="$BUILD_DIR/port_tariff_core" \
PORT_TARIFF_RUNTIME="$RUNTIME_DIR" \
PORT_TARIFF_PROVIDERS="$ROOT/data/model_providers.example.json" \
python3 -m uvicorn port_tariff_agent.server:app --host 127.0.0.1 --port "$API_PORT" \
  >"$LOG_DIR/api.log" 2>&1 &
API_PID=$!
echo "$API_PID" > "$RUN_DIR/api.pid"
echo "$API_PORT" > "$RUN_DIR/api.port"

echo "Starting React frontend..."
(
  cd "$ROOT/web"
  VITE_PORT_TARIFF_API="http://127.0.0.1:$API_PORT" \
    npm run dev -- --port "$WEB_PORT" >"$LOG_DIR/web.log" 2>&1
) &
WEB_PID=$!
echo "$WEB_PID" > "$RUN_DIR/web.pid"
echo "$WEB_PORT" > "$RUN_DIR/web.port"

sleep 1

echo
echo "Port Tariff Agent PoC is running"
echo "  UI:      http://127.0.0.1:$WEB_PORT"
echo "  API:     http://127.0.0.1:$API_PORT/api/health"
echo "  Logs:    $LOG_DIR"
echo "  Runtime: $RUNTIME_DIR"
echo
echo "Press Ctrl-C to stop backend and frontend."

wait -n "$API_PID" "$WEB_PID"
