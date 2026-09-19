# Operator runbook

What the person running AI Lecture Notes has to do, and when. Everything
else in the stack looks after itself. The README explains *how* each piece
works; this page is only the *to-do list*.

All commands run on the server (the Mac mini), from the repository folder.

## Nothing to do

These run without you:

| What | When | How you'd know it failed |
|---|---|---|
| Backup (database + settings + audio → encrypted off-site copy) | nightly 03:00 | Email to `BACKUP_NOTIFY_EMAIL`; `deploy/state/backups/backup.log` |
| Audio cleanup (recordings older than the retention period) | daily | — (transcripts and notes are never deleted) |
| Container restarts after a crash or reboot | always | Uptime monitor email |
| Log rotation (20 MB × 5 per service) | always | — |
| Dependabot patch/minor updates | Mondays, merged when CI passes | GitHub email per PR |
| Security advisories | as published | GitHub email + Security tab |

## Weekly (2 minutes, Monday)

Read the Dependabot emails. Green and merged → nothing to do. A PR with a
comment from the auto-merge workflow is a **major** bump or a Docker
base-image change; it waits for you (see *When you have 20 minutes*).

## Monthly (10 minutes, first Monday — not during a class)

Pull the month's merged updates and rebuild the running image:

```bash
git pull
deploy/start.sh
curl -s http://localhost:8010/health     # want "status":"healthy"
```

The app restarts for about a minute; Postgres and MinIO stay up, nothing is
lost. If a security PR merged mid-month, do this that week instead of
waiting.

**Broken after the rebuild?** Return to the last release and rebuild, then
look at the app log:

```bash
git checkout v1.1.0                      # the last tag that worked
deploy/start.sh
docker compose -f deploy/compose.yml logs --tail=100 app
```

## Every few months (5 minutes)

Prove the backup restores — a backup that has never been restored is a
hope, not a backup:

```bash
deploy/restore-drill.sh --from-remote
```

It fetches the off-site copy, restores it into a throwaway stack on port
8020, checks accounts, lectures, settings and audio came back, and tears
everything down. Ends with `PASSED` or a reason.

## When you have 20 minutes

A Dependabot PR that was **not** auto-merged (major bump, or a base image):
build the candidate and run it against a restored copy of real data before
merging.

```bash
git fetch origin && git checkout <the dependabot branch>
docker build -t lecture-notes-app:candidate -f deploy/Dockerfile .
DRILL_IMAGE=lecture-notes-app:candidate deploy/restore-drill.sh
git checkout main
```

`PASSED` → merge the PR on GitHub. Anything else → close it with a comment
saying what failed; Dependabot will not reopen it. Python and Node major
base images are ignored by design (native wheels lag new Pythons).

## Yearly

- January: update the copyright year in `LICENSE` and the README footer.
- Check the Tailscale machine still has **key expiry disabled** (admin
  console → the machine) and that the Google OAuth consent screen is still
  *In production*.

## When the site is down

The uptime monitor emails you. In order:

1. Is the Mac on and signed in? (A reboot needs Docker Desktop running;
   it starts at sign-in.)
2. `docker compose -f deploy/compose.yml ps` — everything should say
   `running`/`healthy`. Something restarting in a loop →
   `docker compose -f deploy/compose.yml logs --tail=100 <service>`.
3. `curl -s http://localhost:8010/health` — `degraded` names the part
   that is failing (`database` or `storage`).
4. Reachable locally but not from the internet → Tailscale:
   `docker compose -f deploy/compose.yml logs --tail=50 tailscale`, and
   check the machine in the Tailscale admin console.
5. Still stuck → `deploy/stop.sh && deploy/start.sh` restarts the whole
   stack without touching data.

## When data is lost

Disk died, wrong thing deleted, machine replaced:

```bash
deploy/restore.sh latest          # from the local copy
deploy/restore.sh --from-remote latest   # from the off-site copy (new machine)
```

The restore needs the backup passphrase (password manager) and, on a new
machine, `deploy/backup-setup.sh` first to reconnect the off-site remote.

## Accounts

- New sign-ups email you an **Approve** link; pending accounts also show in
  Settings → Users.
- Lost admin password: password reset by email works for admins too; if
  mail is broken:
  `docker compose -f deploy/compose.yml exec app python -m scripts.manage_users passwd admin`

## Where things live

| | |
|---|---|
| Secrets and config | `deploy/.env` (git-ignored, mode 600) |
| Backups, local copy | `deploy/state/backups/` |
| Backups, off-site | the rclone remote set up by `backup-setup.sh` |
| Backup schedule | `~/Library/LaunchAgents/com.mgnetwork.lecture-backup.plist` |
| App log | `docker compose -f deploy/compose.yml logs app` |
| Version running | Settings footer, or `/health` |
