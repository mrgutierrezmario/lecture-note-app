#!/bin/bash
# Restore the AI Lecture Notes stack from a backup made by deploy/backup.sh.
#
#   deploy/restore.sh latest                    newest local daily bundle
#   deploy/restore.sh daily/lecture-notes-2026-09-15.tar.gz
#   deploy/restore.sh --from-remote latest      fetch the backups from the
#                                               off-site copy first (new machine)
#   deploy/restore.sh --no-audio latest         database + settings only
#
# On a blank machine: install Docker (and rclone if the backup is off-site),
# clone the repository, run deploy/restore.sh --from-remote latest. It recreates
# deploy/.env, the database, the saved settings/API keys, the Tailscale
# identity (same URL) and the audio, then starts the stack.
#
# On a running stack it REPLACES the database with the backup — everything
# recorded since the backup is lost. It asks before doing that.
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose -f compose.yml"
PROJECT=lecture-notes
BACKUP_DIR="${BACKUP_DIR:-$PWD/state/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-lecture-backup:}"

FROM_REMOTE=0; AUDIO=1; TARGET=""
for arg in "$@"; do
  case "$arg" in
    --from-remote) FROM_REMOTE=1 ;;
    --no-audio) AUDIO=0 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) TARGET="$arg" ;;
  esac
done
[ -n "$TARGET" ] || { sed -n '2,17p' "$0"; exit 1; }
log() { echo "[restore] $*"; }

# ── Fetch off-site copy ───────────────────────────────────────────────────────
if [ $FROM_REMOTE = 1 ]; then
  command -v rclone >/dev/null || { echo "rclone is needed for --from-remote (brew install rclone)." >&2; exit 1; }
  rclone listremotes | grep -qx "$RCLONE_REMOTE" || { echo "No rclone remote '$RCLONE_REMOTE' — run deploy/backup-setup.sh first." >&2; exit 1; }
  log "Downloading backups from $RCLONE_REMOTE ..."
  mkdir -p "$BACKUP_DIR"
  rclone copy "$RCLONE_REMOTE" "$BACKUP_DIR" --transfers 8 --stats-one-line -q
fi

# ── Pick the bundle ───────────────────────────────────────────────────────────
if [ "$TARGET" = latest ]; then
  BUNDLE=$(ls -1t "$BACKUP_DIR"/daily/$PROJECT-*.tar.gz 2>/dev/null | head -1)
  [ -n "$BUNDLE" ] || { echo "No bundles in $BACKUP_DIR/daily" >&2; exit 1; }
else
  BUNDLE="$TARGET"; [ -f "$BUNDLE" ] || BUNDLE="$BACKUP_DIR/$TARGET"
  [ -f "$BUNDLE" ] || { echo "Bundle not found: $TARGET" >&2; exit 1; }
fi
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
tar -C "$WORK" -xzf "$BUNDLE"
STAGE=$(ls -d "$WORK"/$PROJECT-*)
log "Restoring from $(basename "$BUNDLE") (made $(basename "$STAGE" | sed "s/$PROJECT-//"))"

# ── Secrets ───────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp "$STAGE/env" .env; log "Recreated deploy/.env from the backup."
elif ! cmp -s "$STAGE/env" .env; then
  log "NOTE: deploy/.env differs from the backup's copy; keeping the current one."
  log "      (The database password must match the one Postgres was created with.)"
fi

# ── Confirm if data would be replaced ─────────────────────────────────────────
if docker volume inspect "${PROJECT}_postgres-data" >/dev/null 2>&1; then
  echo
  echo "  This REPLACES the current database (and saved settings) with the backup."
  echo "  Lectures recorded after the backup will be gone."
  read -r -p "  Type 'restore' to continue: " answer
  [ "$answer" = restore ] || { echo "Cancelled."; exit 1; }
fi

# ── Start the data services only ──────────────────────────────────────────────
log "Starting postgres, minio, tailscale (app stays down while restoring)..."
$DC stop app >/dev/null 2>&1 || true
$DC up -d postgres minio minio-init tailscale-config tailscale
for i in $(seq 1 60); do $DC exec -T postgres pg_isready -q -U postgres && break; sleep 1; done

# ── Database ──────────────────────────────────────────────────────────────────
log "Restoring the database..."
$DC exec -T postgres psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS lecture_notes WITH (FORCE);" -c "CREATE DATABASE lecture_notes;"
gzip -dc "$STAGE/db.sql.gz" | $DC exec -T postgres psql -U postgres -d lecture_notes -q -v ON_ERROR_STOP=1 -o /dev/null
log "  $($DC exec -T postgres psql -U postgres -d lecture_notes -tAc \
  "select count(*) || ' users, ' || (select count(*) from sessions) || ' lectures, ' || (select count(*) from transcript_segments) || ' transcript segments' from users")"

# ── Volumes: app state (settings, API keys) and Tailscale identity ────────────
volume_restore() {  # <volume> <tar.gz>  — replaces the volume's contents
  docker run --rm -i -v "${PROJECT}_$1:/v" busybox:stable sh -c 'rm -rf /v/* /v/.[!.]* 2>/dev/null; tar -C /v -xzf -' < "$2"
}
log "Restoring saved settings..."
volume_restore app-state "$STAGE/app-state.tar.gz"
if [ -z "$($DC exec -T tailscale ls /var/lib/tailscale 2>/dev/null | grep -v '^$' || true)" ]; then
  log "Restoring the Tailscale identity (same URL as before)..."
  $DC stop tailscale >/dev/null
  volume_restore tailscale-state "$STAGE/tailscale-state.tar.gz"
else
  log "Tailscale is already signed in on this machine; keeping its identity."
fi

# ── Audio ─────────────────────────────────────────────────────────────────────
if [ $AUDIO = 1 ] && [ -d "$BACKUP_DIR/audio" ]; then
  log "Uploading audio chunks ($(du -sh "$BACKUP_DIR/audio" | cut -f1))..."
  $DC up -d tailscale >/dev/null
  tar -C "$BACKUP_DIR/audio" -cf - . | $DC run --rm -T --no-deps --entrypoint python app -m storage.audio_backup import
fi

# ── Bring everything up ───────────────────────────────────────────────────────
log "Starting the stack..."
./start.sh
