#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/app/ui_backend"
FRONTEND="$ROOT/app/ui_frontend"

log() { echo "[start.sh] $*"; }

# ── Cleanup stale processes ───────────────────────────────────────────────────
log "Stopping any previously running services..."
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "vite --host" 2>/dev/null || true
sleep 1

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_PID=""
log "Checking Ollama..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    log "Ollama already running."
else
    log "Starting Ollama..."
    ollama serve > /tmp/ollama.log 2>&1 &
    OLLAMA_PID=$!
    for i in $(seq 1 15); do
        sleep 1
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            log "Ollama started (pid $OLLAMA_PID)."
            break
        fi
        if [ "$i" -eq 15 ]; then
            log "WARNING: Ollama did not start in time. AI chat and notes may be unavailable."
        fi
    done
fi

# ── Backend ───────────────────────────────────────────────────────────────────
log "Starting backend..."
cd "$BACKEND"
venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
log "Backend started (pid $BACKEND_PID). Logs: /tmp/backend.log"

# ── Frontend ──────────────────────────────────────────────────────────────────
log "Starting frontend..."
cd "$FRONTEND"
npm run dev -- --host > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
log "Frontend started (pid $FRONTEND_PID). Logs: /tmp/frontend.log"

log ""
log "All services running:"
log "  Backend:  http://localhost:8000"
log "  Frontend: http://localhost:5173"
log "  Ollama:   http://localhost:11434"
log ""
log "Press Ctrl+C to stop all services."

# ── Shutdown ──────────────────────────────────────────────────────────────────
trap 'log "Stopping..."; kill $BACKEND_PID $FRONTEND_PID $OLLAMA_PID 2>/dev/null; exit 0' INT TERM
wait
