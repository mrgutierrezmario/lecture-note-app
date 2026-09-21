#!/bin/bash
# Start (or update) the whole AI Lecture Notes stack in its own containers.
# Safe to re-run: rebuilds the app image if code changed, restarts what needs it,
# leaves data alone. Run it again after pulling new code.
#
#   deploy/start.sh            build + start everything, print the public URL
#   deploy/stop.sh             stop (data is kept in Docker volumes)
#   docker compose -f deploy/compose.yml logs -f app     follow the app log
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose -f compose.yml"

log() { echo "[start] $*"; }
# Load deploy/.env without `source` (values may contain spaces, e.g. MAIL_FROM_NAME).
load_env() {
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key=${line%%=*}; val=${line#*=}
    case "$val" in \"*\") val=${val#\"}; val=${val%\"} ;; \'*\') val=${val#\'}; val=${val%\'} ;; esac
    export "$key=$val"
  done < "$1"
}
gen() { python3 -c "import secrets; print(secrets.token_urlsafe(${1:-24}))"; }

command -v docker >/dev/null || { echo "Docker is not installed or not on PATH." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running — start Docker Desktop first." >&2; exit 1; }

# Every image here is public, so a Docker credential helper that cannot run
# (a dev container's helper outside VS Code, a missing keychain) must not
# stop the pulls: fall back to an empty Docker config for this run.
creds=$(python3 -c "import json,os; print(json.load(open(os.path.expanduser('~/.docker/config.json'))).get('credsStore',''))" 2>/dev/null || true)
if [ -n "$creds" ] && ! echo | "docker-credential-$creds" list >/dev/null 2>&1; then
  log "Docker credential helper '$creds' is not working here; pulling anonymously."
  export DOCKER_CONFIG; DOCKER_CONFIG=$(mktemp -d); echo '{}' > "$DOCKER_CONFIG/config.json"
fi

# ── First run: create deploy/.env with generated secrets ──────────────────────
if [ ! -f .env ]; then
  log "Creating deploy/.env with generated secrets..."
  cp .env.example .env
  sed -i.bak "s|^SECRET_KEY=$|SECRET_KEY=$(gen 32)|; s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=$(gen)|; s|^MINIO_ROOT_PASSWORD=$|MINIO_ROOT_PASSWORD=$(gen)|" .env
  rm -f .env.bak
fi
load_env .env

# Bundled Ollama only when nothing external is configured.
if [ -z "${OLLAMA_BASE_URL:-}" ] || [ "${OLLAMA_BASE_URL}" = "http://ollama:11434" ]; then
  export COMPOSE_PROFILES=bundled-ollama
  BUNDLED_OLLAMA=1
else
  BUNDLED_OLLAMA=0
fi

# ── Build and start ───────────────────────────────────────────────────────────
log "Building and starting containers (first build takes a few minutes)..."
$DC up -d --build --remove-orphans

# ── Ollama models (bundled Ollama only) ───────────────────────────────────────
if [ "$BUNDLED_OLLAMA" = 1 ]; then
  for i in $(seq 1 30); do $DC exec -T ollama ollama list >/dev/null 2>&1 && break; sleep 2; done
  for model in "${OLLAMA_MODEL:-llama3}" llava; do
    if ! $DC exec -T ollama ollama list 2>/dev/null | grep "^${model}" >/dev/null; then
      log "Pulling Ollama model $model (one-time, several GB)..."
      $DC exec -T ollama ollama pull "$model"
    fi
  done
fi

# ── Tailscale: sign in once ───────────────────────────────────────────────────
ts() { $DC exec -T tailscale tailscale "$@"; }
for i in $(seq 1 30); do ts status >/dev/null 2>&1 && break; ts status 2>&1 | grep "Logged out\|NeedsLogin\|log in" >/dev/null && break; sleep 2; done
if ! ts status >/dev/null 2>&1; then
  URL=$($DC logs tailscale 2>&1 | grep -oE 'https://login\.tailscale\.com/a/[a-z0-9]+' | tail -1)
  echo
  echo "============================================================"
  echo "  Tailscale needs a one-time sign-in. Open this on any device:"
  echo "    ${URL:-<waiting for link — run: docker compose -f deploy/compose.yml logs tailscale>}"
  echo "  (Tip: set TS_AUTHKEY in deploy/.env to skip this in future.)"
  echo "============================================================"
  echo
  log "Waiting for sign-in..."
  for i in $(seq 1 300); do ts status >/dev/null 2>&1 && break; sleep 2; done
  ts status >/dev/null 2>&1 || { echo "Still not signed in — re-run deploy/start.sh after signing in." >&2; exit 1; }
fi
ts status >/dev/null 2>&1 && log "Tailscale connected as $(ts status --self=true --peers=false 2>/dev/null | awk 'NR==1{print $2}')"

# ── App health ────────────────────────────────────────────────────────────────
log "Waiting for the app..."
for i in $(seq 1 90); do
  $DC exec -T app curl -fs http://localhost:8000/health >/dev/null 2>&1 && break
  sleep 2
done
$DC exec -T app curl -fs http://localhost:8000/health >/dev/null 2>&1 || {
  echo "App did not become healthy. Logs:" >&2; $DC logs --tail=40 app >&2; exit 1; }

# ── First admin ───────────────────────────────────────────────────────────────
if ! $DC exec -T app python -m scripts.manage_users list 2>/dev/null | grep " admin" >/dev/null; then
  ADMIN="${ADMIN_USERNAME:-admin}"
  log "No admin account yet — creating '$ADMIN'..."
  $DC exec -T app python -m scripts.manage_users create "$ADMIN" --admin --generate
  echo "  ^ save this password; change it in Settings > Your password after signing in."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
PUBLIC=$(ts funnel status 2>/dev/null | grep -oE 'https://[a-z0-9.-]+\.ts\.net' | head -1)
echo
echo "============================================================"
echo "  AI Lecture Notes is running."
echo "  Public URL:  ${PUBLIC:-(Funnel not active yet — run deploy/start.sh again in a minute)}"
echo "  Local URL:   http://localhost:${APP_PORT:-8010}"
echo "============================================================"
if [ "$BUNDLED_OLLAMA" = 0 ]; then
  if $DC exec -T app python -c "import httpx,sys; sys.exit(0 if httpx.get('${OLLAMA_BASE_URL}/api/tags', timeout=5).status_code==200 else 1)" 2>/dev/null; then
    echo "  Notes model: external Ollama at ${OLLAMA_BASE_URL} (reachable)"
  else
    echo "  WARNING: external Ollama at ${OLLAMA_BASE_URL} is not reachable — notes will use the basic fallback until it is."
  fi
fi
if [ -n "$PUBLIC" ] && ! ts funnel status 2>/dev/null | grep "Funnel on" >/dev/null; then
  echo "  Funnel is not enabled for your Tailscale account yet. Run:"
  echo "    docker compose -f deploy/compose.yml exec tailscale tailscale funnel --bg 8000"
  echo "  and open the link it prints, then re-run deploy/start.sh."
fi
