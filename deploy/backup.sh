#!/bin/bash
# Nightly backup of the AI Lecture Notes stack.
#
#   deploy/backup.sh              back up everything, prune old copies, sync off-site
#   deploy/backup.sh --no-remote  skip the off-site sync
#
# What is saved, under $BACKUP_DIR (default deploy/state/backups):
#   daily/lecture-notes-YYYY-MM-DD.tar.gz   Postgres dump (users, transcripts,
#                                           notes, history), deploy/.env, the
#                                           app-state volume (API keys, settings)
#                                           and the Tailscale identity
#   weekly/…                                Sunday's bundle, kept longer
#   audio/                                  mirror of the audio bucket (only new
#                                           chunks are fetched; chunks retention
#                                           has deleted are removed here too)
#
# Off-site: if rclone has a remote named $RCLONE_REMOTE (set up by
# deploy/backup-setup.sh — an encrypted folder in Google Drive), the whole
# backup directory is synced there. Restore with deploy/restore.sh.
#
# Runs from anywhere: only needs docker and (optionally) rclone on the host.
# Schedule it with deploy/mac/com.mgnetwork.lecture-backup.plist on a Mac, or
# a cron line on Linux:  0 3 * * * /path/to/deploy/backup.sh >> backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose -f compose.yml"
PROJECT=lecture-notes              # compose project name → volume prefix

BACKUP_DIR="${BACKUP_DIR:-$PWD/state/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-lecture-backup:}"
KEEP_DAILY="${KEEP_DAILY:-14}"
KEEP_WEEKLY="${KEEP_WEEKLY:-8}"
REMOTE=1; [ "${1:-}" = "--no-remote" ] && REMOTE=0

log() { echo "[backup $(date '+%Y-%m-%d %H:%M:%S')] $*"; }
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

# Email the operator on failure through the app's own mail account, when
# BACKUP_NOTIFY_EMAIL is set in deploy/.env (optional).
[ -f .env ] && load_env .env
notify_failure() {
  [ -n "${MAIL_USERNAME:-}" ] && [ -n "${MAIL_PASSWORD:-}" ] && [ -n "${BACKUP_NOTIFY_EMAIL:-}" ] || return 0
  printf 'From: %s\nTo: %s\nSubject: Lecture Notes backup FAILED on %s\n\nStep: %s\nCheck the backup log on the server.\n' \
    "${MAIL_FROM:-$MAIL_USERNAME}" "$BACKUP_NOTIFY_EMAIL" "$(hostname)" "$STEP" |
    curl -s --url "smtps://${MAIL_SERVER:-smtp.gmail.com}:${MAIL_PORT:-465}" \
      --mail-from "${MAIL_FROM:-$MAIL_USERNAME}" --mail-rcpt "$BACKUP_NOTIFY_EMAIL" \
      --user "$MAIL_USERNAME:$MAIL_PASSWORD" -T - >/dev/null 2>&1 || true
}
STEP=starting; WORK=""
trap 'status=$?; [ -n "$WORK" ] && rm -rf "$WORK"; [ $status -ne 0 ] && { log "FAILED during: $STEP (exit $status)"; notify_failure; }; exit $status' EXIT

command -v docker >/dev/null || { echo "docker not found on PATH" >&2; exit 1; }
$DC ps --status running --services 2>/dev/null | grep -qx postgres || { echo "The stack is not running (deploy/start.sh)." >&2; exit 1; }

DATE=$(date +%Y-%m-%d)
WORK=$(mktemp -d)
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/audio"
BUNDLE="$BACKUP_DIR/daily/$PROJECT-$DATE.tar.gz"
STAGE="$WORK/$PROJECT-$DATE"; mkdir -p "$STAGE"

# ── 1. Database ───────────────────────────────────────────────────────────────
STEP="database dump"; log "Dumping Postgres..."
$DC exec -T postgres pg_dump -U postgres --no-owner --no-privileges lecture_notes | gzip -6 > "$STAGE/db.sql.gz"
[ "$(gzip -dc "$STAGE/db.sql.gz" | grep -c 'PostgreSQL database dump complete')" = 1 ] || { echo "pg_dump output is incomplete" >&2; exit 1; }

# ── 2. Secrets and state ──────────────────────────────────────────────────────
STEP="state"; log "Copying .env, app state, Tailscale identity..."
cp .env "$STAGE/env"
volume_tar() { docker run --rm -v "${PROJECT}_$1:/v:ro" busybox:stable tar -C /v -czf - . ; }
volume_tar app-state       > "$STAGE/app-state.tar.gz"
volume_tar tailscale-state > "$STAGE/tailscale-state.tar.gz"

# ── 3. Bundle + prune ─────────────────────────────────────────────────────────
STEP="bundle"
tar -C "$WORK" -czf "$BUNDLE" "$(basename "$STAGE")"
log "Bundle: $BUNDLE ($(du -h "$BUNDLE" | cut -f1))"
[ "$(date +%u)" = 7 ] && cp "$BUNDLE" "$BACKUP_DIR/weekly/"
prune() { ( ls -1t "$1"/$PROJECT-*.tar.gz 2>/dev/null || true ) | tail -n +"$(( $2 + 1 ))" | xargs -I{} rm -f {}; }
prune "$BACKUP_DIR/daily" "$KEEP_DAILY"
prune "$BACKUP_DIR/weekly" "$KEEP_WEEKLY"

# ── 4. Audio mirror ───────────────────────────────────────────────────────────
STEP="audio mirror"; log "Mirroring audio bucket..."
AUDIO="$BACKUP_DIR/audio"
# What we already have, as "<key> <size>" — the container sends only the rest.
( cd "$AUDIO" && find . -type f ! -name MANIFEST -exec wc -c {} + ) |
  awk '$2 != "total" { sub(/^\.\//, "", $2); print $2, $1 }' |
  $DC exec -T app python -m storage.audio_backup export | tar -x -C "$AUDIO" -f -
# Remove local chunks that no longer exist in the bucket (retention / user delete).
if [ -f "$AUDIO/MANIFEST" ]; then
  ( cd "$AUDIO" && find . -type f ! -name MANIFEST | sed 's|^\./||' | sort > "$WORK/have" \
    && cut -d' ' -f1 MANIFEST | sort > "$WORK/want" \
    && comm -23 "$WORK/have" "$WORK/want" | xargs -I{} rm -f {} \
    && find . -type d -empty -delete )
fi
log "Audio: $(find "$AUDIO" -type f ! -name MANIFEST | wc -l | tr -d ' ') chunks, $(du -sh "$AUDIO" | cut -f1)"

# ── 5. Off-site ───────────────────────────────────────────────────────────────
STEP="off-site sync"
if [ $REMOTE = 1 ]; then
  if command -v rclone >/dev/null && rclone listremotes | grep -qx "$RCLONE_REMOTE"; then
    log "Syncing to $RCLONE_REMOTE ..."
    rclone sync "$BACKUP_DIR" "$RCLONE_REMOTE" --exclude 'backup.log' --transfers 8 --stats-one-line -q
    log "Off-site copy up to date."
  else
    log "No rclone remote '$RCLONE_REMOTE' — local backup only (run deploy/backup-setup.sh for off-site)."
  fi
fi
log "Done."
