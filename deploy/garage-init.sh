#!/bin/bash
# Prepare Garage for the app: node layout, access key, bucket. Idempotent —
# start.sh and restore.sh run it on every start; each step is skipped when
# already done. Needs S3_ACCESS_KEY / S3_SECRET_KEY in deploy/.env.
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose -f compose.yml"
g() { $DC exec -T garage /garage "$@" 2>/dev/null; }
log() { echo "[garage] $*"; }

KEY_ID=$(grep -E '^S3_ACCESS_KEY=' .env | cut -d= -f2-)
KEY_SECRET=$(grep -E '^S3_SECRET_KEY=' .env | cut -d= -f2-)
[ -n "$KEY_ID" ] && [ -n "$KEY_SECRET" ] || { echo "S3_ACCESS_KEY/S3_SECRET_KEY missing in deploy/.env" >&2; exit 1; }

for i in $(seq 1 30); do g status >/dev/null && break; sleep 1; done
g status >/dev/null || { echo "Garage did not start" >&2; exit 1; }

# 1. A single-node layout (one zone, one copy).
if g layout show | grep -q "No nodes currently have a role"; then
  NODE=$(g status | awk 'f && $1 ~ /^[0-9a-f]{16}$/ {print $1; exit} /HEALTHY NODES/ {f=1}')
  g layout assign -z dc1 -c 10G "$NODE" >/dev/null
  g layout apply --version 1 >/dev/null
  log "layout applied (node $NODE)"
fi

# 2. The app's access key, imported with the ID and secret from .env.
g key info "$KEY_ID" >/dev/null || { g key import --yes -n lecture-notes "$KEY_ID" "$KEY_SECRET" >/dev/null; log "key imported"; }

# 3. The audio bucket, owned by that key.
g bucket info lecture-audio >/dev/null || { g bucket create lecture-audio >/dev/null; log "bucket created"; }
g bucket allow --read --write --owner lecture-audio --key "$KEY_ID" >/dev/null
log "ready"
