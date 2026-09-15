#!/bin/bash
# One-time setup for off-site backups: an encrypted folder in Google Drive via
# rclone, plus the nightly schedule. Safe to re-run.
#
#   deploy/backup-setup.sh
#
# What it does:
#   1. installs rclone if missing (Homebrew on a Mac)
#   2. connects rclone to a Google account — a browser window opens; sign in
#      with the account that should hold the backups (a dedicated one is a
#      good idea) and allow access. rclone only gets access to files it
#      creates itself (the drive.file scope), nothing else in that Drive.
#   3. wraps that in an encrypted remote called "lecture-backup" so nothing
#      readable ever leaves the machine — file names included. The passphrase
#      is generated here and printed ONCE: store it in a password manager. It
#      is what lets you decrypt the backups if this machine is gone.
#   4. schedules deploy/backup.sh nightly at 03:00 (launchd on macOS; prints a
#      cron line on Linux) and runs a first backup.
set -euo pipefail
cd "$(dirname "$0")"
REPO=$(cd .. && pwd)
GDRIVE_REMOTE=gdrive
CRYPT_REMOTE="${RCLONE_REMOTE:-lecture-backup:}"; CRYPT_REMOTE=${CRYPT_REMOTE%:}
DRIVE_FOLDER=LectureNotesBackups
log() { echo "[backup-setup] $*"; }

# ── 1. rclone ─────────────────────────────────────────────────────────────────
if ! command -v rclone >/dev/null; then
  if command -v brew >/dev/null; then log "Installing rclone..."; brew install rclone
  else echo "Install rclone first: https://rclone.org/install/" >&2; exit 1; fi
fi

# ── 2. Google Drive ───────────────────────────────────────────────────────────
if rclone listremotes | grep -qx "$GDRIVE_REMOTE:"; then
  log "Google Drive remote '$GDRIVE_REMOTE' already exists."
else
  echo
  echo "  A browser window will open. Sign in with the Google account that should"
  echo "  hold the backups and click Allow. (If you are on a machine without a"
  echo "  browser, rclone prints a link to open elsewhere.)"
  echo
  read -r -p "  Press Enter to continue..." _
  # rclone prints the finished section, token included, so keep it off the screen.
  rclone config create "$GDRIVE_REMOTE" drive scope drive.file >/dev/null
fi
rclone lsd "$GDRIVE_REMOTE:" >/dev/null 2>&1 || { echo "Google Drive is not reachable — run: rclone config reconnect $GDRIVE_REMOTE:" >&2; exit 1; }
log "Google Drive connected."

# ── 3. Encrypted remote ───────────────────────────────────────────────────────
if rclone listremotes | grep -qx "$CRYPT_REMOTE:"; then
  log "Encrypted remote '$CRYPT_REMOTE' already exists (passphrase unchanged)."
else
  PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  SALT=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  rclone config create "$CRYPT_REMOTE" crypt remote "$GDRIVE_REMOTE:$DRIVE_FOLDER" \
    password "$PASS" password2 "$SALT" filename_encryption standard directory_name_encryption true --obscure >/dev/null
  echo
  echo "============================================================"
  echo "  BACKUP PASSPHRASE — store this in your password manager now."
  echo "  Without it the off-site backups cannot be decrypted."
  echo
  echo "  password : $PASS"
  echo "  salt     : $SALT"
  echo
  echo "  To read the backups from another machine, run this setup again"
  echo "  there, choose the same Google account, and when asked, enter"
  echo "  these two values instead of generating new ones — or recreate the"
  echo "  remote by hand:"
  echo "    rclone config create $CRYPT_REMOTE crypt remote $GDRIVE_REMOTE:$DRIVE_FOLDER \\"
  echo "      password '<password>' password2 '<salt>' --obscure"
  echo "============================================================"
  echo
  read -r -p "  Press Enter once it is saved..." _
fi
rclone mkdir "$CRYPT_REMOTE:" && log "Encrypted folder ready: Google Drive → $DRIVE_FOLDER (contents unreadable without the passphrase)."

# ── 4. Schedule ───────────────────────────────────────────────────────────────
mkdir -p state/backups
if [ "$(uname)" = Darwin ]; then
  PLIST=~/Library/LaunchAgents/com.mgnetwork.lecture-backup.plist
  sed "s|__REPO__|$REPO|g; s|__HOME__|$HOME|g" mac/com.mgnetwork.lecture-backup.plist > "$PLIST"
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  log "Scheduled nightly at 03:00 (launchd: com.mgnetwork.lecture-backup). Log: deploy/state/backups/backup.log"
else
  log "Add this line with 'crontab -e' to run nightly at 03:00:"
  echo "  0 3 * * * $REPO/deploy/backup.sh >> $REPO/deploy/state/backups/backup.log 2>&1"
fi

# ── First backup ──────────────────────────────────────────────────────────────
log "Running the first backup now..."
./backup.sh
echo
log "Off-site copy: $(rclone size "$CRYPT_REMOTE:" 2>/dev/null | tr '\n' ' ')"
log "Restore anywhere with: deploy/restore.sh --from-remote latest"
