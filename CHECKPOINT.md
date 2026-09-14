# Checkpoint — 2026-09-14 (evening update)

> Supersedes the 2026-03-29 checkpoint (kept at the bottom for history). The
> app now runs as its own Docker stack on the Mac mini with a fixed public URL,
> user accounts, and a redesigned UI. 53 commits landed on `main` across
> 2026-09-13/14; the "Later on 2026-09-14" section lists the evening's work.

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
  - Images still go Claude first (falls back to llava until credits exist).
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

### Deployment history (for context)
Dev container with supervisor → own Docker Compose stack → Ollama moved
native for the GPU. Cloudflare quick tunnel was used briefly; Tailscale Funnel
is the permanent URL. Docker memory: 12 GB → 8 GB after Ollama left Docker.

## Open Items

1. **Add API credits** at console.anthropic.com → Plans & Billing, then verify
   an image upload logs `provider: claude/claude-opus-5` (or switch
   Slides & images to Gemini, which already works).
2. **Turn off Settings → Sign-up** once the intended users have accounts.
3. Re-add the phone home-screen app from the new URL and update bookmarks
   (the URL itself is confirmed live).
4. Optional: revoke/re-create the two Gmail App Passwords that passed through
   chat (`deploy/.env` holds the current ones).
5. stock-tracker's report emails are failing on a revoked App Password —
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
