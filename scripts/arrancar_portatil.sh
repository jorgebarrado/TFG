#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
READER_MODE="${READER_MODE:-static}"

cd "$ROOT_DIR"

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "No existe .venv. Crea el entorno antes de arrancar el proyecto." >&2
  exit 1
fi

source "$ROOT_DIR/.venv/bin/activate"

export HF_HOME="${HF_HOME:-$ROOT_DIR/.cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME/transformers}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-True}"
mkdir -p "$TRANSFORMERS_CACHE"

if [[ "$READER_MODE" == "vite" ]]; then
  export READER_VITE_DEV_SERVER="${READER_VITE_DEV_SERVER:-http://$FRONTEND_HOST:$FRONTEND_PORT}"
else
  export READER_VITE_DEV_SERVER=""
fi

free_port() {
  local port="$1"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0

  echo "Liberando puerto $port..."
  kill $pids 2>/dev/null || true
  sleep 1

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0

  echo "Forzando cierre en puerto $port..."
  kill -9 $pids 2>/dev/null || true
}

run_backend() {
  free_port "$BACKEND_PORT"
  echo "Backend en http://$BACKEND_HOST:$BACKEND_PORT/"
  if [[ -n "$READER_VITE_DEV_SERVER" ]]; then
    echo "Reader con Vite en $READER_VITE_DEV_SERVER"
  else
    echo "Reader servido por Django en /static/reader/"
  fi
  python tfg_project/manage.py runserver "$BACKEND_HOST:$BACKEND_PORT"
}

run_frontend() {
  if [[ ! -d "$ROOT_DIR/frontend_reader/node_modules" ]]; then
    echo "Faltan dependencias del frontend. Ejecuta npm install en frontend_reader/." >&2
    exit 1
  fi

  free_port "$FRONTEND_PORT"
  echo "Frontend en http://$FRONTEND_HOST:$FRONTEND_PORT/"
  cd "$ROOT_DIR/frontend_reader"
  npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
}

run_checks() {
  python tfg_project/manage.py check
  (
    cd "$ROOT_DIR/frontend_reader"
    npm run build >/dev/null
  )
  echo "Entorno listo."
}

build_reader_static() {
  if [[ ! -d "$ROOT_DIR/frontend_reader/node_modules" ]]; then
    echo "Faltan dependencias del frontend. Ejecuta npm install en frontend_reader/." >&2
    exit 1
  fi

  echo "Compilando reader para que Django lo sirva en http://$BACKEND_HOST:$BACKEND_PORT/ ..."
  (
    cd "$ROOT_DIR/frontend_reader"
    npm run build >/dev/null
  )
}

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

wait_for_any() {
  while true; do
    if [[ -n "${BACKEND_PID:-}" ]] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      wait "$BACKEND_PID" 2>/dev/null || true
      return 0
    fi
    if [[ -n "${FRONTEND_PID:-}" ]] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      wait "$FRONTEND_PID" 2>/dev/null || true
      return 0
    fi
    sleep 1
  done
}

case "$MODE" in
  all)
    if [[ "$READER_MODE" == "vite" ]]; then
      echo "Arrancando backend y frontend..."
      run_backend &
      BACKEND_PID=$!
      run_frontend &
      FRONTEND_PID=$!
      trap cleanup EXIT INT TERM
      wait_for_any
    else
      echo "Arrancando la web completa desde Django..."
      build_reader_static
      run_backend
    fi
    ;;
  backend)
    run_backend
    ;;
  frontend)
    run_frontend
    ;;
  vite)
    READER_MODE="vite"
    export READER_VITE_DEV_SERVER="${READER_VITE_DEV_SERVER:-http://$FRONTEND_HOST:$FRONTEND_PORT}"
    echo "Arrancando backend y frontend con Vite..."
    run_backend &
    BACKEND_PID=$!
    run_frontend &
    FRONTEND_PID=$!
    trap cleanup EXIT INT TERM
    wait_for_any
    ;;
  check)
    run_checks
    ;;
  *)
    echo "Uso: scripts/arrancar_portatil.sh [all|backend|frontend|vite|check]" >&2
    exit 1
    ;;
esac
