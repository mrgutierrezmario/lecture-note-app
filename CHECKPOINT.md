# Checkpoint — 2026-09-14 (public release)

> Supersedes the 2026-03-29 checkpoint (kept at the bottom for history). The
> app now runs as its own Docker stack on the Mac mini with a fixed public URL,
> user accounts, and a redesigned UI. The repository history was squashed to a
> single "initial public release" commit on 2026-09-14 in preparation for
> making it public; the full development history exists only in a local,
> never-pushed backup branch on the Mac mini's dev container.

## State of the Project

Live and in use at **https://<TS_HOSTNAME>.<tailnet>.ts.net** (Tailscale Funnel,
valid Let's Encrypt certificate, fixed URL). Everything below is deployed and
committed; the running container matches `main`.

## What's Running (Mac mini, Docker Desktop, 8 GB VM)

| Service | Where | Notes |
|---|---|---|
| `lecture-notes-app` | Docker (`deploy/compose.yml`) | FastAPI backend + built React UI on one port (:8000 → Mac :8010) |
| `lecture-notes-postgres` | Docker, named volume | 18-alpine; migrations run on container start |
| `lecture-notes-minio` | Docker, named volume | audio chunks, bucket `lecture-audio` |
| `lecture-notes-tailscale` | Docker, named volume | Funnel → app; key expiry disabled |
| Ollama | **Native on the Mac** (`brew`, launch agent in `deploy/mac/`) | GPU (Metal); `OLLAMA_MAX_LOADED_MODELS=1`; app reaches it at `host.docker.internal:11434` — now only the fallback for notes/chat, plus llava for images |

All containers are `restart: unless-stopped`; the stack has survived two
Docker restarts on its own. the previous Docker Ollama container is
stopped — its port 11434 now belongs to the native one.

```bash
deploy/start.sh    # build/update + start everything (safe to re-run)
deploy/stop.sh     # stop; data kept
docker compose -f deploy/compose.yml logs -f app
```

Config lives in `deploy/.env` (git-ignored): DB/MinIO passwords, `SECRET_KEY`,
`OLLAMA_BASE_URL`, `OLLAMA_MODELS` (shares an existing Ollama model directory on the Mac),
Gmail credentials for reset emails, `PUBLIC_URL`.

## What Changed (2026-09-13 → 14)

### UI redesign
- MG Network brand assets (favicons, logo mark, manifest); design tokens in
  `index.css`; light/dark with a **System / Light / Dark** picker in Settings
  (`data-theme`, no flash on load).
- App bar (brand · title · username · Connected · History · Settings · sign-out) + toolbar
  (one primary Record button, grouped exports, switches). Cards with headers
  and empty states. Mobile layout (stacked toolbar, 44 px targets, 16 px
  inputs, full-screen settings, actions row on phones).
- Proper PWA manifest (`AI Lecture Notes`, `start_url`, `scope`, maskable icon)
  so "Add to Home screen" builds a clean app package on Android.

### Accounts
- `users` table (bcrypt), signed httpOnly login cookie (30 days), admin flag.
- **Self-registration** (username + email + password) with an admin switch
  **Settings → Sign-up** to close it; sign in with **username or email**.
- **Forgot password**: single-use 60-minute links emailed from
  a dedicated do-not-reply Gmail account (Gmail App Password, same SMTP approach as
  stock-tracker). Admins can also reset passwords from Settings → Users.
- Admin account: `admin` (owner's email on file).
- `manage_users.py` CLI for bootstrapping.

### Per-user features
- **History** drawer: own lectures (admins see all, with owner), rename,
  delete, delete-audio-only; open a past lecture read-only (transcript, notes,
  exports, chat); **New lecture** to return.
- **Storage quota**: retained audio per user, default 500 MB
  (`storage_quota_mb`, admin-editable) with per-user overrides; usage bar in
  History; recording refused when over quota, or audio stops being kept if the
  quota fills mid-lecture. Upload size capped at 50 MB.
- Every lecture is owned by whoever recorded it; routes and the recording
  websocket enforce it. Pre-account lectures (no owner) are admin-only.

### Recording / transcription
- **Fixed a long-standing bug**: the first 5 s of every lecture was being
  re-transcribed on every chunk (the whole first blob was used as the WebM
  header). Continuation chunks now decode to 5 s, not 10 s; transcripts are
  contiguous and more accurate. Old lectures still carry the duplication.
- Mic permission is requested on a tap ("Enable microphone" / Start), never on
  page load — fixes the installed-app case where the launch-time prompt got
  auto-denied. Precise "blocked" guidance for installed app vs. browser.
- **Silence warning** after 15 s of digital silence while recording (OS mutes
  the mic during phone/Zoom calls). Phone-only tip: use speakerphone to
  capture the other side of a call.
- MP3/notes/transcript downloads use direct attachment links (the blob-URL
  approach looped in Android's media viewer).
- Uploads accept **.docx** and **images** (transcribed via Claude → llava →
  BLIP).

### Models
- Notes: `llama3` on native Ollama (GPU). Measured: ~21 tok/s; 3 simultaneous
  recordings keep up with real-time transcription, a 4th falls behind.
- Claude vision: API key saved in Settings (persists in the `app-state`
  volume; a bug where an empty env var shadowed it on restart is fixed).
  **Account has no credits yet** → images currently fall back to llava.
- Whisper stays on `small` (user had accuracy issues with `base`).

### Later on 2026-09-14
- **History downloads**: each row has a download menu (transcript, notes,
  MP3) so nothing needs to be opened first; entries grey out when notes or
  audio don't exist.
- **Keep (lock) lectures**: `sessions.locked` (migration 007). A kept lecture
  is excluded from the 14-day audio cleanup and cannot be deleted (whole or
  audio-only) until unlocked. Regular users: up to `max_locked_lectures`
  (default 5, Settings-editable); **admins unlimited**. History shows a lock
  toggle, a "kept" tag and "Kept: n of 5". Kept audio still counts toward the
  storage quota.
- **Old lectures assigned to admin**: all 64 ownerless sessions now belong to
  `admin` (7 with transcripts); nothing is unowned.
- **Themed dialogs**: `Dialog.jsx` (`useDialog().confirm/prompt/notice`)
  replaces every `window.confirm/prompt/alert`. Deleting audio, a lecture or a
  user requires explicit confirmation with a red action button; rename,
  password reset and quota use prompt mode; the quota-refused notice uses it.
  Built on theme tokens — light and dark. Stylesheet audited: no hard-coded
  colours remain.
- **Tooltips**: instant themed tooltips (`data-tip`) on every icon button,
  also on keyboard focus; anchored right for right-edge clusters; hidden on
  touch devices.
- History row actions ordered *download · rename · keep · delete audio ·
  delete lecture*; Delete-audio uses a crossed-out note icon and turns red.
- Retention note in History reworded (admin/user variants).
- **Bug fixed**: upload card and chat pane duplicated on every lecture switch
  (two siblings shared the same React key).
- **"Save storage" renamed "Don't keep audio"** (also in the over-quota
  message and README); tooltips added to every toolbar control (record/stop,
  each export, mic selector, the three switches, Connected, New lecture,
  username). Long tooltips wrap and anchor to the nearest screen edge.
- **App bar order**: `username · ● Connected · History · Settings · sign-out`
  (username leads the group, shown on phones too, ellipsised at 90 px).
- **AI providers** (`providers.py`): one call for text (`generate_text`) and
  one for cloud vision (`describe_image_cloud`). Settings has an always-visible
  **API keys** section (Claude, Gemini, OpenAI — all can be saved at once) and
  two independent selectors: **Notes & chat** (Ollama / Claude / Gemini /
  OpenAI) and **Slides & images** (Claude / Gemini / OpenAI / local llava).
  Cloud failures fall back to Ollama (text) or llava → BLIP (images).
  - **Gemini is live**: key saved, `text_provider=gemini`, model
    `gemini-3.6-flash` (Google retired 2.5-flash for new keys). The model
    field is a dropdown fed from Google's live model list (`/api/settings/
    gemini-models`), "Gemini Flash Latest" alias auto-tracks releases.
  - Newer Flash models are *thinking* models: the provider turns thinking off
    with whichever knob the model accepts (`thinkingLevel` vs
    `thinkingBudget`, probed once per model) and uses a 2048-token floor,
    else answers come back empty (`MAX_TOKENS`). One retry on 503/429.
  - Slides & images now go Gemini first as well (see the cascade below).
- **Hostname renamed**: the original name → the current `TS_HOSTNAME`, so the URL is
  **https://<TS_HOSTNAME>.<tailnet>.ts.net** (cert issued 02:57; public DNS
  propagating). `PUBLIC_URL` in `deploy/.env` updated. The old URL is dead;
  the phone home-screen app must be re-added from the new one.
- **Branding**: full name "M.G. Network and Technology Solutions" in the app
  bar, tab title, logo alt text and manifest description.
- **URL verified live** (DNS published, cert valid, login + websocket OK);
  old `mg-notes` address confirmed dead.
- Small polish: status text reads "Connected to session: <id>"; the lecture
  title field is focused on load and after New lecture (desktop only — on
  touch devices focusing would raise the keyboard over the page) and its
  placeholder is "Name your lecture…" (an outside label was tried and
  rejected as odd-looking).
- **Data note**: 27 test lectures (incl. both Sept 9 recordings) were deleted
  via History during testing; intentionally left deleted. Yesterday's
  pre-migration snapshot is kept at
  `deploy/state/backups/lecture_notes-snapshot-2026-09-13.sql.gz` (43 MB,
  git-ignored) and the old MinIO volume still has that audio, should any of it
  ever be wanted. The Sept 9 lectures that appeared in earlier notes tests are
  therefore gone from the live DB.

### After the public release (2026-09-14 late → 2026-09-15)
- `app/ui` renamed **`app/ui_frontend`** (Dockerfile, start.sh, main.py, README
  updated); `.gitattributes` keeps design mockups out of GitHub language stats;
  README status badges; repo description and topics set via `gh`.
- **Chat context**: was capped at the last 4,000 transcript characters and
  never included the notes → now latest notes + full transcript for cloud
  providers (300k chars), notes + 16k chars for Ollama (num_ctx raised to 8192).
- **Notes reliability** (found on a 113-minute recording where notes stopped
  at minute 26 while the transcript continued): the notes loop was only
  started by the Record button and died on a WebSocket reconnect; audio
  arriving now restarts it. Backlog catch-up was truncated to 3k chars → now
  processed in provider-sized windows, re-sliced if a cloud call falls back
  to Ollama; merge skips repeated bullets/terms. That lecture's notes were
  regenerated (v26 covers the full recording).
- **Fallback visibility**: chat replies show which model answered and, in
  amber, why a cloud provider fell back (quota, overloaded, no credits, key
  rejected…); a notes pass that fell back reports on the status line.
- **MP3 export with progress**: built in the background
  (`POST …/export/audio.mp3/prepare`, `GET …/status`), spinner with percent
  on the toolbar button and in History; finished files cached 30 min; mono
  80 kbps (a third the size of the old 192k stereo); longer ffmpeg limit.
- **Gemini free tier**: one long lecture at 60-second notes exhausts a
  model's daily request quota; the app fell back to llama3 correctly. Each
  model has its own quota, so the model was rotated (`gemini-flash-latest`,
  then `gemini-flash-lite-latest` on 2026-09-15 after both `flash` variants
  returned 503/429). Pay-as-you-go on the Google project removes the cap.

### Provider cascade and 120-second notes (2026-09-15)
- **Cloud cascade**: every text and vision request tries the chosen provider,
  then any *other* cloud provider that has a saved key, then the local
  Ollama/llava models (`providers._cloud_cascade`). With Gemini chosen and a
  Claude key saved, Gemini → Claude → local. Claude stays a selectable option
  in Settings; nothing was removed. The reply records which provider answered
  and why the primary was skipped, so the amber fallback notice is accurate.
  First real run: Gemini 503 → Claude "no credits" → llava, exactly as designed.
- **Settings now**: notes/chat = Gemini, slides & images = Gemini, notes
  interval **120 s** (halves request volume against free-tier quotas; notes
  still catch up on the whole backlog each pass).
- Phone home-screen app re-added from the current URL.

### Google Drive for users (2026-09-15)
- Settings → Google Drive: connect own Google account (OAuth, `drive.file` +
  email scopes), auto-save switch (default on), folder path with **Create
  folder** (created immediately; nested paths OK; moving the folder in Drive
  is fine — tracked by id), disconnect (revokes at Google).
- Export = `notes.md`, `transcript.txt`, `recording.mp3` into
  `<folder>/<date title>/`; re-export updates in place (`drive_files` table).
  Background job (`google_drive.py`), History row shows a spinning "Saving to
  Drive: <step>" badge, auto-saves report steps on the recorder status line.
- Admin config: Settings → API keys → Google Drive (OAuth client); the
  Google Drive section sits right under it for admins. `google_client_id` in
  overrides, `GOOGLE_CLIENT_SECRET` in STATE_DIR/.env. Migrations 008, 009.
- Refresh tokens Fernet-encrypted with SECRET_KEY. `index.html` now served
  `no-cache` (stale UI after deploys was confusing).
- Tested end to end by the operator (connected with the do-not-reply
  account; files landed; folder creation works).

### Hardening and polish (2026-09-15, evening)
- **Sign-up closed** (Settings → Sign-up off; admins add accounts).
- **Audio buffering across disconnects**: the browser queues chunks (and
  start/stop, in order) while the socket is down and replays them on
  reconnect; status pill shows "Buffering Ns"; a `resume` message restores
  the server's in-memory per-session options. Reconnect backoff 1 s → 15 s.
- **Sign-in rate limiting** (`ratelimit.py`): 5 failures / 10 min per client
  address *and* per account → 60 s lockout, doubling, 429 + Retry-After;
  forgot-password and resend-verification limited per address. Verified the
  Funnel passes real client IPs (so it is per-client, not global).
- **Email verification** for self-registration (migration 010:
  `users.email_verified`, `password_resets.purpose`): 202 + emailed link
  (24 h) that signs the user in; login refused (403 + resend) until then;
  admin-created accounts and password resets count as verified; "unverified"
  badge in Users. Tested end to end with a plus-address; test user deleted.
- **README screenshots**: hero (dark lecture with transcript, notes and a
  follow-up chat question) + collapsible gallery. Raw captures live in
  `design/screenshots/raw/` (git-ignored: browser chrome shows personal
  tabs); `Untitled*.pdf` ignored everywhere after two raw PDFs slipped into a
  commit — history rewritten (2 commits) and force-pushed, verified clean.
- **Chat**: replies render Markdown; the last 8 exchanges are sent with each
  question so follow-ups ("when is that due?") resolve.
- **Privacy policy** at `/privacy` (public, no sign-in): what is stored,
  AI providers, Google Drive scope/tokens/revocation, backups, controls,
  contact (`SUPPORT_EMAIL` in `deploy/.env`, blank = generic). Linked from
  the sign-in page and the Settings footer.
- **Audio retention** is now a live admin setting (Settings → Audio
  retention); set to **7 days** on this server. UI texts read the value.
- **Fixed**: stale transcript/notes/status painted over a new session when
  the user moved on before a past lecture finished loading.

### Reboot resilience and backups (2026-09-15)
- **FileVault turned off** on the Mac mini so automatic login works; Docker
  Desktop starts at sign-in; the whole stack came back on its own after the
  reboot. Trade-off noted: disk is no longer encrypted at rest (matters only
  if the Mac is physically stolen — rotate `deploy/.env` secrets then).
- **Dev environment** (`~/mgntsdev`): `dev` container now `restart:
  unless-stopped`, `shutdownAction: none`. Its Docker Ollama service moved
  behind `--profile ollama` and the container removed — it published port
  11434 and raced the native GPU Ollama on every boot (native won this time;
  had Docker won, the app would silently have run on the CPU).
- **Backups built**: `deploy/backup.sh` (pg_dump + .env + app-state +
  Tailscale identity bundle, 14 daily / 8 weekly; incremental audio mirror via
  `audio_backup.py` running inside the app container, so no bind mounts or
  MinIO credentials on the host), `deploy/restore.sh` (same machine or blank
  machine with `--from-remote`; restores the Tailscale identity so the URL
  survives), `deploy/backup-setup.sh` (rclone → Google Drive `drive.file`
  scope → encrypted `lecture-backup:` remote, launchd at 03:00, first run).
  Failure email via `BACKUP_NOTIFY_EMAIL`. Tested: bundle restored into a
  throwaway Postgres (1 user, 104 lectures, 1567 segments, alembic 007);
  audio import idempotent. `start.sh`/`backup.sh` no longer `source .env`
  (a value with spaces, `MAIL_FROM_NAME`, broke it) — safe loader instead.
- **Data note**: the manual snapshot `deploy/state/backups/lecture_notes-
  snapshot-2026-09-13.sql.gz` (612 MB uncompressed) still holds 32 sessions
  that are no longer in the live database — untitled dev/test recordings
  from March–May plus two untitled ~1.5 h recordings from 2026-09-09 —
  presumably deleted from History on purpose. Keep the snapshot; individual
  sessions can be pulled out of it if ever wanted.

### Public-release preparation (2026-09-14)
- **PEP 8**: whole backend formatted with ruff (line length 100, isort);
  `pyproject.toml` pins the config and now enforces docstrings (`D1`).
  Ruff also surfaced real fixes: a duplicate route function name
  (`admin_reset_password`), `== False` → `.is_(False)`, an ambiguous `l`.
- **Documentation**: module/class/function docstrings on all 32 backend
  modules (100%), header comments on every frontend component/hook; dead
  Claude helpers removed from `routes/sessions.py`; pydantic v2 config style.
- **README** rewritten as a from-scratch guide (dev + Docker production,
  public URL, accounts, providers, configuration table, troubleshooting).
- **License**: PolyForm Noncommercial 1.0.0 (© M.G. Network and Technology
  Solutions) — noncommercial use free, commercial use needs a separate license.
  (MIT was added first and replaced before anything went public.)
- **Scrubbed** personal details from tracked files (email, hostname, tailnet,
  home paths); verified no secrets ever existed in any commit.
- **History squashed**: `main` is one commit; old branches deleted on GitHub.
  Local backup branch `backup-full-history-2026-09-14` — do not push it.

### Deployment history (for context)
Dev container with supervisor → own Docker Compose stack → Ollama moved
native for the GPU. Cloudflare quick tunnel was used briefly; Tailscale Funnel
is the permanent URL. Docker memory: 12 GB → 8 GB after Ollama left Docker.

## Open Items

1. Optional: **Claude API credits** at console.anthropic.com → Plans &
   Billing. Claude is the second link in the cascade; without credits it is
   skipped in about a second and the local model answers instead.
2. ~~Turn off Settings → Sign-up~~ — closed 2026-09-15 (admins add
   accounts; invite codes not built).
3. ~~Re-add the phone home-screen app from the new URL~~ — done 2026-09-15.
4. ~~Flip the GitHub repository to public~~ — done 2026-09-14; description,
   topics and badges set. Ask GitHub Support to GC old commits if desired.
5. ~~Notes interval 120 s~~ — set 2026-09-15. Pay-as-you-go on the Google AI
   project is still the only way to remove the free-tier daily caps.
6. ~~Chunks dropped while the server restarts~~ — client-side buffering
   built 2026-09-15 (up to 30 min queued in the browser).
7. ~~Reboot behaviour~~ — FileVault off, auto-login + Docker at sign-in
   enabled, verified 2026-09-15.
8. ~~Run `deploy/backup-setup.sh`~~ — done 2026-09-15: rclone → do-not-reply
   Google Drive (`LectureNotesBackups`, encrypted), launchd 03:00, first sync
   completed (~150 MB, 5 min). Passphrase is in the operator's password
   manager. rclone uses its own OAuth client ("Lecture App rclone backups",
   Desktop type) from the Google Cloud project `lecture-notes` owned by the
   do-not-reply account — rclone's shared client_id is being retired in 2026
   and was heavily throttled. Note: `drive.file` scope means rclone only sees
   the folder it created; a half-uploaded folder from the shared client was
   trashed by hand.
9. ~~Per-user Google Drive export~~ — built 2026-09-15; consent screen
   **published (In production)** the same evening. Google required a home
   page + privacy policy URL + authorized domain for an external app, so
   `/privacy` was added (operator contact from `SUPPORT_EMAIL`) and the
   app's own Funnel host was used as the domain. Any Google account can
   now connect a Drive.
10. Optional next features: Google Picker folder chooser (~3 h, needs an API
    key); invite codes for sign-up; Claude API credits.
11. Optional: revoke/re-create the two Gmail App Passwords that passed through
   chat (`deploy/.env` holds the current ones).
12. stock-tracker's report emails are failing on a revoked App Password —
   unrelated to this app, but noticed while diagnosing.

## Feature Reference (what users have)

| Area | Regular user | Admin |
|---|---|---|
| Record, live transcript, notes, chat, uploads | own lectures | same |
| History: open (read-only), rename, delete, delete audio, download | own lectures | all lectures, owner shown |
| Keep lectures (skip cleanup, block deletion) | up to 5 | unlimited |
| Storage quota (retained audio) | 500 MB default, per-user override | same, sets overrides |
| Accounts | self-register (if open), email or username login, forgot password, change own email/password | manage users, reset passwords, quotas, close sign-up |
| Models / API keys / provider choice / limits | — | Settings |

## Known Limits (by design)

- Phones cannot record the far side of a phone/VoIP call (OS restriction);
  use speakerphone, a second device, or Tab audio on a computer.
- Sign-up open = anyone with the URL can register. No login rate limiting.
- One shared Whisper: comfortable for ~3 simultaneous recordings. With notes
  on Gemini, Ollama is idle during lectures, which helps.
- Cloud providers see transcripts (Gemini free tier may use data to improve
  models); Ollama keeps everything on the Mac.
- 16 GB Mac: Docker 8 GB + one Ollama model (~5 GB) + macOS is the budget;
  `OLLAMA_MAX_LOADED_MODELS=1` keeps it there.
- Dev container quirk: it carries its own `POSTGRES_PASSWORD` in its
  environment, which Compose would use over `deploy/.env`. Run compose from
  the Mac, or with `env -u POSTGRES_PASSWORD …` from the container.

---

# Checkpoint — 2026-03-29 (historical)

> Superseded 2026-09-07. The container was rebuilt since this was written:
> the HuggingFace weight cache was cleared, and the default Whisper model moved
> back to `small` (`large-v3` runs slower than realtime on CPU). Superseded
> again 2026-09-14 by the Docker stack above.

The app ran from the dev container via `./start.sh` (Ollama → backend →
frontend) on localhost:5173, with Postgres and MinIO installed in the
container. Whisper was briefly `large-v3`, later reverted to `small`.
