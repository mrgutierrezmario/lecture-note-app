#!/bin/bash
# Restore drill: prove a backup actually restores, without touching the live stack.
#
#   deploy/restore-drill.sh                 newest local bundle
#   deploy/restore-drill.sh --from-remote   fetch the off-site copy first (what a
#                                           real disaster recovery would do)
#   deploy/restore-drill.sh --keep          leave the drill stack running to poke at
#
# Restores the bundle + audio mirror into a throwaway Compose project
# ("lecture-drill": its own volumes, app on port $DRILL_PORT, a fresh Tailscale
# node that is never signed in, so it cannot collide with the live one), then
# checks that accounts, lectures, settings and audio came back and that the app
# answers, and tears everything down. Run it every so often; a backup that has
# never been restored is a hope, not a backup.
set -euo pipefail
cd "$(dirname "$0")"
DRILL=lecture-drill
DRILL_PORT="${DRILL_PORT:-8020}"
BACKUP_DIR="${BACKUP_DIR:-$PWD/state/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-lecture-backup:}"
FROM_REMOTE=0; KEEP=0
for arg in "$@"; do case "$arg" in --from-remote) FROM_REMOTE=1 ;; --keep) KEEP=1 ;; esac; done

log() { echo "[drill $(date '+%H:%M:%S')] $*"; }
fail() { echo "[drill] FAILED: $*" >&2; exit 1; }
WORK=$(mktemp -d)
DC="docker compose -p $DRILL -f compose.yml --env-file $WORK/drill.env"
cleanup() {
  status=$?
  if [ $KEEP = 1 ] && [ $status -eq 0 ]; then
    log "Drill stack left running (--keep): http://localhost:$DRILL_PORT — remove with:"
    log "  docker compose -p $DRILL -f deploy/compose.yml down -v --remove-orphans"
  else
    log "Tearing down the drill stack..."
    $DC down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
  [ $status -eq 0 ] && log "PASSED — the backup restores cleanly." || echo "[drill] exit $status" >&2
  exit $status
}
trap cleanup EXIT

# ── Bundle ────────────────────────────────────────────────────────────────────
if [ $FROM_REMOTE = 1 ]; then
  command -v rclone >/dev/null || fail "rclone is needed for --from-remote"
  log "Fetching the off-site copy into $WORK/remote ..."
  rclone copy "$RCLONE_REMOTE" "$WORK/remote" --transfers 8 -q
  SRC="$WORK/remote"
else
  SRC="$BACKUP_DIR"
fi
BUNDLE=$(ls -1t "$SRC"/daily/lecture-notes-*.tar.gz 2>/dev/null | head -1)
[ -n "$BUNDLE" ] || fail "no bundle under $SRC/daily"
tar -C "$WORK" -xzf "$BUNDLE"
STAGE=$(ls -d "$WORK"/lecture-notes-*)
log "Bundle: $(basename "$BUNDLE")"

# The bundle's .env gives the drill the same DB/MinIO passwords the dump and
# settings expect; ports and the Tailscale name are overridden so nothing
# clashes with the live stack.
grep -v '^\(APP_PORT\|TS_HOSTNAME\|TS_AUTHKEY\)=' "$STAGE/env" > "$WORK/drill.env"
printf 'APP_PORT=%s\nTS_HOSTNAME=%s\nTS_AUTHKEY=\n' "$DRILL_PORT" "$DRILL" >> "$WORK/drill.env"

# ── Data services ─────────────────────────────────────────────────────────────
log "Starting drill postgres/minio/tailscale (project $DRILL)..."
$DC up -d postgres minio minio-init tailscale-config tailscale >/dev/null 2>&1
for i in $(seq 1 60); do $DC exec -T postgres pg_isready -q -U postgres && break; sleep 1; done
$DC exec -T postgres pg_isready -q -U postgres || fail "postgres did not start"

# ── Restore ───────────────────────────────────────────────────────────────────
log "Restoring the database..."
gzip -dc "$STAGE/db.sql.gz" | $DC exec -T postgres psql -U postgres -d lecture_notes -q -v ON_ERROR_STOP=1 -o /dev/null
log "Restoring saved settings..."
docker run --rm -i -v "${DRILL}_app-state:/v" busybox:stable tar -C /v -xzf - < "$STAGE/app-state.tar.gz"
if [ -d "$SRC/audio" ]; then
  log "Uploading audio ($(du -sh "$SRC/audio" | cut -f1))..."
  tar -C "$SRC/audio" -cf - . | $DC run --rm -T --no-deps --entrypoint python app audio_backup.py import 2>&1 | grep -v "^INFO" | tail -1
fi

# ── App ───────────────────────────────────────────────────────────────────────
log "Starting the drill app..."
$DC up -d app >/dev/null 2>&1
for i in $(seq 1 90); do
  $DC exec -T app curl -fs http://localhost:8000/health >/dev/null 2>&1 && break; sleep 2
done
HEALTH=$($DC exec -T app curl -fs http://localhost:8000/health 2>/dev/null || true)
echo "$HEALTH" | grep -q '"status":"healthy"' || { $DC logs --tail=30 app >&2; fail "app not healthy: $HEALTH"; }

# ── Verify ────────────────────────────────────────────────────────────────────
Q() { $DC exec -T postgres psql -U postgres -d lecture_notes -tAc "$1"; }
USERS=$(Q "select count(*) from users"); ADMINS=$(Q "select count(*) from users where is_admin")
LECTURES=$(Q "select count(*) from sessions where id in (select session_id from transcript_segments)")
SEGMENTS=$(Q "select count(*) from transcript_segments"); NOTES=$(Q "select count(*) from notes_versions")
ALEMBIC=$(Q "select version_num from alembic_version")
CHUNKS_DB=$(Q "select count(*) from audio_chunks where not deleted_from_s3")
CHUNKS_S3=$($DC exec -T app python -c "
from s3_client import s3_client as s
n=sum(len(p.get('Contents',[])) for p in s.client.get_paginator('list_objects_v2').paginate(Bucket=s.bucket)); print(n)" 2>/dev/null | tail -1)
SETTINGS=$($DC exec -T app python -c "
import settings_store; o=settings_store._read_overrides(); print(len(o), 'settings;', 'gemini key' if settings_store.get_settings().gemini_api_key else 'no gemini key')" 2>/dev/null | tail -1)
log "Users: $USERS ($ADMINS admin) · lectures: $LECTURES · segments: $SEGMENTS · notes versions: $NOTES · schema: $ALEMBIC"
log "Audio: $CHUNKS_S3 objects in storage vs $CHUNKS_DB retained chunks in the database"
log "Settings restored: $SETTINGS"
log "Health: $HEALTH"
[ "$USERS" -ge 1 ] && [ "$ADMINS" -ge 1 ] || fail "no admin account came back"
[ "$CHUNKS_S3" -ge "$CHUNKS_DB" ] || fail "audio objects missing: $CHUNKS_S3 < $CHUNKS_DB"
