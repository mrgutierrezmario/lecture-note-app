#!/bin/sh
# Docker marks a container `unhealthy` but never restarts it on its own. This
# loop watches the tailscale service's healthcheck (the public-URL probe in
# compose.yml) and, when it fails, restarts tailscale and then the app — both,
# because the app runs inside the tailscale container's network namespace and
# loses its network when that namespace is recreated. Data is untouched.
#
# Runs in the `watchdog` service (deploy/watchdog/Dockerfile) with the Docker
# socket mounted.
set -u

PROJECT=${PROJECT:?compose project name}
INTERVAL=${INTERVAL:-30}     # seconds between checks
COOLDOWN=${COOLDOWN:-300}    # seconds to wait after a restart before judging again

log() { echo "$(date -u +%FT%TZ) $*"; }
cid() {
  docker ps -q \
    -f "label=com.docker.compose.project=$PROJECT" \
    -f "label=com.docker.compose.service=$1"
}

log "watching '$PROJECT': tailscale health every ${INTERVAL}s"
while :; do
  ts=$(cid tailscale)
  if [ -n "$ts" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$ts" 2>/dev/null)" = unhealthy ]; then
    log "tailscale is unhealthy (public URL not answering): restarting tailscale, then app"
    docker restart "$ts" >/dev/null && log "tailscale restarted" || log "tailscale restart FAILED"
    app=$(cid app)
    if [ -n "$app" ]; then
      docker restart "$app" >/dev/null && log "app restarted" || log "app restart FAILED"
    fi
    log "cooling down ${COOLDOWN}s"
    sleep "$COOLDOWN"
    continue
  fi
  sleep "$INTERVAL"
done
