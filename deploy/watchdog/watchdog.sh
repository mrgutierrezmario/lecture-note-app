#!/bin/sh
# Keeps a Tailscale-fronted compose stack reachable. Docker marks containers
# `unhealthy` but never restarts them, and services that share the tailscale
# container's network namespace (network_mode: service:tailscale) lose their
# network every time tailscale starts, since each start gets a new namespace
# (2026-10-05: the app answered nothing and could not resolve postgres for 7
# hours). Each pass:
#
#   1. Tailscale unhealthy (its public-URL healthcheck, when it has one) and
#      the internet reachable: restart it, wait for it to log in, then
#      re-attach the dependants. While the internet is down a restart cannot
#      help, so hold instead.
#   2. Re-attach any dependant that started before tailscale's current start
#      (Docker or this script restarted tailscale underneath it).
#   3. Restart a service (dependants, cloudflared, any WATCHED ones) that
#      exited with an error or never started, or whose own healthcheck has
#      failed UNHEALTHY_STREAK checks in a row; and cloudflared when it has
#      exited or has had no connection to Cloudflare for CF_READY_FAILS passes.
#
# A service stopped on purpose (`docker compose stop`, exit 0/137/143) is left
# alone. Data is untouched. Runs as the `watchdog` service with the Docker
# socket mounted; the same script is used by every stack on the Mac mini.
set -u

PROJECT=${PROJECT:?compose project name}
DEPENDANTS=${DEPENDANTS:-app cloudflared}  # services in tailscale's network namespace
CLOUDFLARED=${CLOUDFLARED-cloudflared}     # tunnel service ("" if none)
WATCHED=${WATCHED:-}                       # other services to restart when unhealthy or crashed
# Where tailscale's container can reach cloudflared's /ready (needs a fixed
# --metrics address). Loopback when cloudflared shares tailscale's namespace.
CF_READY_URL=${CF_READY_URL:-http://127.0.0.1:20241/ready}
INTERVAL=${INTERVAL:-30}             # seconds between passes
COOLDOWN=${COOLDOWN:-300}            # after restarting tailscale, before judging its health again
READY_TIMEOUT=${READY_TIMEOUT:-180}  # seconds to wait for tailscale to log in after a restart
SETTLE=${SETTLE:-20}                 # seconds tailscale must be up before dependants are re-attached
UNHEALTHY_STREAK=${UNHEALTHY_STREAK:-20}  # failed healthchecks in a row before a restart (~10 min at 30 s)
CF_READY_FAILS=${CF_READY_FAILS:-10}      # passes without a tunnel connection before a restart (~5 min)
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
restart() {
  log "$1 $2: restarting"
  docker restart "$3" >/dev/null && log "$1 restarted" || log "$1 restart FAILED"
}
# Why a stopped container should be started again ("" if it should not).
stopped_reason() {
  status=$(field "$2" '{{.State.Status}}')
  case "$status" in
    running|restarting|paused|removing) return ;;
    created) echo "never started$(err "$2")"; return ;;
  esac
  code=$(field "$2" '{{.State.ExitCode}}')
  # cloudflared only exits on its own (e.g. DNS not ready at start).
  if [ "$1" = "$CLOUDFLARED" ]; then echo "exited (code $code)"; return; fi
  case "$code" in 0|137|143) ;; *) echo "exited with an error (code $code)$(err "$2")" ;; esac
}
err() { e=$(field "$1" '{{.State.Error}}'); [ -n "$e" ] && echo ": $e"; }

# Restart dependants attached to an older tailscale namespace, and any
# service that is stopped by mistake or unhealthy for too long.
check_services() {
  ts=$1
  ts_start=$(started "$ts")
  for svc in $(echo "$DEPENDANTS $CLOUDFLARED $WATCHED" | tr ' ' '\n' | awk 'NF && !seen[$0]++'); do
    c=$(cid "$svc")
    [ -n "$c" ] || continue
    reason=$(stopped_reason "$svc" "$c")
    if [ -z "$reason" ] && [ "$(field "$c" '{{.State.Status}}')" = running ]; then
      case " $DEPENDANTS " in
        *" $svc "*) [ "$(started "$c")" -lt "$ts_start" ] && reason="attached to tailscale's previous network" ;;
      esac
      streak=$(field "$c" '{{if .State.Health}}{{.State.Health.FailingStreak}}{{else}}0{{end}}')
      [ -z "$reason" ] && [ "${streak:-0}" -ge "$UNHEALTHY_STREAK" ] &&
        reason="unhealthy for $streak checks in a row"
    fi
    [ -n "$reason" ] && restart "$svc" "$reason" "$c"
  done
}

# cloudflared can run with no connection to Cloudflare; restart it after
# CF_READY_FAILS passes without one (only while the internet is up).
cf_fails=0
check_tunnel() {
  [ -n "$CLOUDFLARED" ] || return
  c=$(cid "$CLOUDFLARED")
  if [ -z "$c" ] || [ "$(field "$c" '{{.State.Status}}')" != running ] ||
     [ $(( $(date -u +%s) - $(started "$c") )) -lt 60 ]; then
    cf_fails=0; return
  fi
  if docker exec "$1" wget -qO- -T 5 "$CF_READY_URL" 2>/dev/null | grep -q '"status":200'; then
    cf_fails=0; return
  fi
  internet_up || return
  cf_fails=$((cf_fails + 1))
  if [ "$cf_fails" -ge "$CF_READY_FAILS" ]; then
    restart "$CLOUDFLARED" "has had no connection to Cloudflare for $cf_fails checks" "$c"
    cf_fails=0
  fi
}

log "watching '$PROJECT' every ${INTERVAL}s (dependants: $DEPENDANTS; tunnel: ${CLOUDFLARED:-none}${WATCHED:+; also: $WATCHED})"
held=0
while :; do
  ts=$(cid tailscale)
  if [ -z "$ts" ] || [ "$(field "$ts" '{{.State.Status}}')" != running ]; then
    sleep "$INTERVAL"; continue
  fi

  if [ "$(field "$ts" '{{if .State.Health}}{{.State.Health.Status}}{{end}}')" = unhealthy ]; then
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
    check_services "$ts"
    log "cooling down ${COOLDOWN}s"
    sleep "$COOLDOWN"
    continue
  fi
  [ "$held" = 1 ] && log "internet back; tailscale healthy again" && held=0

  # Only once tailscale has settled and logged in, so nothing re-attaches to
  # a namespace that is still coming up (or about to be replaced).
  if [ $(( $(date -u +%s) - $(started "$ts") )) -ge "$SETTLE" ] && ts_ready "$ts"; then
    check_services "$ts"
    check_tunnel "$ts"
  fi
  sleep "$INTERVAL"
done
