#!/bin/sh
# Docker marks a container `unhealthy` but never restarts it on its own. This
# loop keeps the public URL up. The app and the optional cloudflared service
# run inside the tailscale container's network namespace, and every time
# tailscale starts it gets a new one: anything still attached to the old one
# has no network at all (2026-10-05: the app answered nothing and could not
# resolve postgres for 7 hours). So each pass:
#
#   1. Tailscale unhealthy (the public-URL probe in compose.yml) and the
#      internet reachable: restart it. While the internet is down a restart
#      cannot help and only makes tailscale log in again, so hold instead.
#   2. Wait for tailscale to be running and logged in before touching the
#      app or cloudflared, so they never attach to a namespace still coming up.
#   3. Restart the app / cloudflared when they started before tailscale's
#      current start (Docker or the watchdog restarted it underneath them), or
#      when cloudflared has exited.
#
# Data is untouched. Runs in the `watchdog` service (deploy/watchdog/Dockerfile)
# with the Docker socket mounted.
set -u

PROJECT=${PROJECT:?compose project name}
INTERVAL=${INTERVAL:-30}        # seconds between checks
COOLDOWN=${COOLDOWN:-300}       # seconds to wait after restarting tailscale before judging its health again
READY_TIMEOUT=${READY_TIMEOUT:-180}  # seconds to wait for tailscale to log in after a restart
SETTLE=${SETTLE:-20}            # seconds tailscale must stay up before dependants are re-attached
NET_PROBE=${NET_PROBE:-controlplane.tailscale.com 443}

log() { echo "$(date -u +%FT%TZ) $*"; }
# Container id for a compose service, running or not.
cid() {
  docker ps -aq \
    -f "label=com.docker.compose.project=$PROJECT" \
    -f "label=com.docker.compose.service=$1" | head -1
}
field() { docker inspect -f "$2" "$1" 2>/dev/null; }
# Container start time in epoch seconds (0 if unknown).
started() {
  s=$(field "$1" '{{.State.StartedAt}}')
  s=${s%%.*}; s=${s%Z}
  date -u -d "$(echo "$s" | tr T ' ')" +%s 2>/dev/null || echo 0
}
internet_up() { nc -z -w 5 $NET_PROBE >/dev/null 2>&1; }
ts_ready() {
  [ "$(field "$1" '{{.State.Status}}')" = running ] &&
    docker exec "$1" tailscale status --json 2>/dev/null | grep -q '"BackendState": "Running"'
}
wait_ts_ready() {
  waited=0
  until ts_ready "$1"; do
    [ "$waited" -ge "$READY_TIMEOUT" ] && return 1
    sleep 5; waited=$((waited + 5))
  done
}

# Restart the app and cloudflared if they are attached to an older tailscale
# namespace than the current one, or (cloudflared) have stopped.
reattach() {
  ts=$1
  ts_start=$(started "$ts")
  for svc in app cloudflared; do
    c=$(cid "$svc")
    [ -n "$c" ] || continue
    status=$(field "$c" '{{.State.Status}}')
    reason=""
    if [ "$status" = running ]; then
      [ "$(started "$c")" -lt "$ts_start" ] && reason="attached to tailscale's previous network"
    elif [ "$status" = exited ] || [ "$status" = dead ]; then
      # A deliberately stopped app is left alone; a stopped tunnel is not,
      # since it only exits on its own (e.g. DNS not ready at start).
      [ "$svc" = cloudflared ] && reason="exited (code $(field "$c" '{{.State.ExitCode}}'))"
    fi
    [ -n "$reason" ] || continue
    log "$svc $reason: restarting"
    docker restart "$c" >/dev/null && log "$svc restarted" || log "$svc restart FAILED"
  done
}

log "watching '$PROJECT': tailscale health every ${INTERVAL}s"
held=0
while :; do
  ts=$(cid tailscale)
  if [ -z "$ts" ] || [ "$(field "$ts" '{{.State.Status}}')" != running ]; then
    sleep "$INTERVAL"; continue
  fi

  if [ "$(field "$ts" '{{.State.Health.Status}}')" = unhealthy ]; then
    if ! internet_up; then
      [ "$held" = 1 ] || log "tailscale is unhealthy but $NET_PROBE is unreachable: internet down, holding"
      held=1
      sleep "$INTERVAL"; continue
    fi
    held=0
    log "tailscale is unhealthy (public URL not answering): restarting tailscale"
    docker restart "$ts" >/dev/null && log "tailscale restarted" || log "tailscale restart FAILED"
    if wait_ts_ready "$ts"; then
      log "tailscale is logged in"
    else
      log "tailscale not logged in after ${READY_TIMEOUT}s; re-attaching anyway"
    fi
    reattach "$ts"
    log "cooling down ${COOLDOWN}s"
    sleep "$COOLDOWN"
    continue
  fi
  [ "$held" = 1 ] && log "internet back; tailscale healthy again" && held=0

  # Tailscale restarted on its own (Docker's restart policy), or a dependant
  # is stale or stopped: re-attach once tailscale has settled and logged in.
  now=$(date -u +%s)
  if [ $((now - $(started "$ts"))) -ge "$SETTLE" ] && ts_ready "$ts"; then
    reattach "$ts"
  fi
  sleep "$INTERVAL"
done
