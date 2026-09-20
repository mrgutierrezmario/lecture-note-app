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

### Public links (2026-09-20)
- README header now links the **live site** and the repo's Website field is
  set (both `https://mgnts-note-app.tail3659a6.ts.net`). Decision: fine to
  publish — visitors land on the sign-in page and the read-only demo. That
  makes the **empty demo the one visible gap**: share a public-safe lecture
  with `test` (History → person icon → `test` → Share).
- The checkout's `origin` had been switched to the insidertrack repo by
  another tool/session (git refused the push, nothing landed wrong); fixed
  by editing `.git/config`. One session per repo from now on.

### Other projects touched from this session (2026-09-20)
- **insidertrack-mcp** (new repo, private, v0.1.0): MCP server over
  InsiderTrack's API — nine read tools, two resources, two prompts, bearer /
  `X-API-Key` auth, rate limit, audit log, stateless streamable HTTP; runs
  as the `mcp` service in the InsiderTrack stack behind `/mcp` on its
  Funnel URL; connected to claude.ai as a custom connector (No sign-in +
  `X-API-Key`). Its `CLAUDE.md` is the working-notes file for that repo.
- **InsiderTrack**: Ollama added as a local provider; the daily Model Desk
  brief prefers it (`AI_BATCH_PROVIDER=ollama`), cloud keys kept for
  visitor notes and vision; Admin → AI usage table per job/provider.
- InsiderTrack's folder is now `../insidertrack` (renamed to match the
  repo; Compose project name pinned so nothing restarted). Its Dependabot
  majors (React 19 / Vite 8 / TS 7, pydantic 2.13) were validated against a
  restored dump and merged; its live site rebuild is pending a quiet day.
  All three projects have a `deploy/OPERATIONS.md` in the same shape.
- **Project #4 designed, not started**: `../homelab-gitops/DESIGN.md` — k3s
  + Argo CD + Tailscale operator running *staging copies* of the three apps
  restored from the nightly backups; production stays on Compose. Decision
  pending on where it runs (a VM on the mini vs a second box) after a week
  of memory measurements. Start after the LinkedIn post and a week of MCP
  use.
- Lessons that cost time today: Tailscale serve strips its path prefix;
  `docker compose up` on a dependent service re-runs one-shot config
  containers (use `--no-deps`; serve.json now written atomically); a
  stateful MCP server loses clients on restart (now stateless).

### v1.1.0 — UI polish after the demo/sharing work (2026-09-19, afternoon)
- Settings and History panels: the panel clips to its radius and an inner
  `.settings-scroll` body scrolls, so the scrollbar no longer squares off
  the right-hand corners. Phone layout keeps full height.
- Share dialog reworked at the operator's request: dropdown of users +
  **Share** button, current viewers listed with Remove; lecture title as a
  subtitle line, one-line explanation.
- Settings footer centred; History footer note is a lead line + 3 bullets.
- Sign-in card: company name (small caps) under the logo, logo sized by
  width (104 px) — it is a 2:1 mark and looked tiny in a square box.
- README: origin paragraph in the Timeline, refreshed sign-in / History /
  Settings screenshots (1× crops supplied by the operator).
- Settings help text: "60-second notes" → "running notes"; storage note
  moved under the storage field.
- Released as **v1.1.0** (minor: sharing + demo are new features since
  1.0.0).
- **Operator runbook** `deploy/OPERATIONS.md`: the to-do list (automatic
  things, weekly Dependabot glance, monthly pull + rebuild on the first
  Monday, restore drill every few months, major-bump validation, yearly
  items, site-down and data-loss steps, account recovery, where things
  live). Linked from the README. Calendar reminder (.ics, first Monday
  monthly 09:00 from 2026-10-05) handed to the operator to import.
- Noticed: "GDP and CPI Class" is *owned* by `test`, not shared — fine for
  the demo, but the operator cannot rename/keep it from the admin account.

### Demo account and lecture sharing (2026-09-19/20)
- **Demo account** (migration 015 `users.is_demo`): "Try the demo" on the
  sign-in page (`POST /api/auth/demo`, open path, rate-limited per IP)
  signs into the flagged account without a password. Read-only: reads,
  chat (10/10 min, not stored, no history), exports; websocket connects
  but `start`/audio ignored; 403 on every write (`session_writer` /
  `forbid_demo`); Settings opens read-only (Models, Sign-up, Ollama) with
  keys/users hidden. Admin: *Demo* switch on Add user, "demo" badge.
  Account **`test`** created (random password; never needed).
- **Sharing** (migration 016 `session_shares`, `chat_messages.user_id`):
  person icon on a History row → dropdown of registered users + **Share**
  button, list of current viewers with Remove (`GET /api/auth/users/names`,
  no emails; `PUT …/shares` replaces the set). Viewers: "shared by X" tag, `can_edit=false`,
  read/own chat/exports/live socket, no writes. Replaced the short-lived
  "Assign to user" (which *moved* ownership; the operator's clicks on it
  moved two lectures to `test` — moved back). `PATCH …/owner` kept as an
  admin API (no UI).
- Dialog buttons centred (btn-primary's icon padding); PDF builder crashed
  on plain-paragraph notes (`KeyError: 'base'`) — fixed + test.
- The March "GDP and CPI Class" transcript is prototype-era nonsense — fine
  as a dated artifact, not as a demo sample. **Operator to record a short
  public-safe sample lecture and share it with `test`**; nothing is shared
  with the demo at the moment.

### Repo hygiene and GitHub settings (2026-09-19)
- Scrubbed hostnames/mailbox names/GCP project id from CHECKPOINT (they
  had crept back since 09-18; the hostname remains in ~40 commits of
  public history — decision: leave, site is login/approval/rate-limit
  gated and force-push is now blocked). Untracked the personal
  `design/profile-README.md` (kept on disk, git-ignored). VS Code path
  made relative. Root `start.sh`/`docker-compose.yml` are the dev
  quick-start — keep; `design/*.dc.html` are the redesign mockups — keep.
- GitHub: enabled Dependabot security alerts + automatic security fixes,
  secret scanning + push protection, CodeQL default setup; branch
  protection on `main` (CI checks required, no force-push/deletion,
  admins not enforced so direct deploy commits still work). Operator to
  set the **social preview image** (Settings → General) with
  `design/screenshots/lecture-dark.png`.

### Version 1.0.0 released (2026-09-19)
- `VERSION` file at the repo root is the single source: backend
  (`core/version.py` → FastAPI version, `/health` "version"), Vite
  (`__APP_VERSION__`, Settings footer "v1.0.0"), Docker (copied to both
  stages). `package.json` at 1.0.0. `CHANGELOG.md` (Keep a Changelog).
- Tag `v1.0.0`, GitHub release "v1.0.0 — first release" (notes = changelog
  section), marked Latest; README release badge + "Versions and releases"
  (how to cut the next one: bump VERSION + package.json, changelog, commit,
  tag, `gh release create`).
- Contributors: Claude appears via the Co-Authored-By trailer; decision:
  keep it and own it — README "How it was built" section added. **From
  2026-09-19 commits carry no Claude trailer** (operator instruction, saved
  in memory); earlier history untouched.
- **Timeline made public** (README "Timeline" table + CHANGELOG "Before
  1.0.0"): first commit 2026-01-29, first real lecture 2026-03-26, work in
  Jan/Mar/Apr/Sep, daily use through the summer, v1.0.0 on 09-19 — mined
  from `backup-full-history-2026-09-14` (95 commits; still never pushed).
- **"GDP and CPI Class" (2026-03-26) restored** into the live DB from the
  09-13 snapshot (session, 24 segments, 2 notes versions; audio chunk rows
  marked deleted; owner = admin) so History shows the first recorded class.
  Screenshot `design/screenshots/history-timeline.png` under the README
  timeline (March → September rows).

### Code-quality audit (2026-09-19, late)
- Verified: ruff format/check clean on all 51 backend files; docstrings on
  every public module/class/function (D100–D107: none missing); every
  frontend component/hook has a header comment (useTheme.js added).
- ruff rule set widened and **enforced in CI**: `E, W, F, I, D1, B, UP,
  SIM, C4` (B008 ignored — FastAPI `Depends()` idiom). Applied across the
  codebase: `X | None` annotations (88), `raise … from e` in every except
  block (13), `contextlib.suppress` for try/except/pass, literal dicts,
  one collapsed if. 42 tests green; deployed; CI green.
- Dependabot: #6 (checkout v7) merged; #7/#8 (setup-node/-python v7)
  conflicted after #6, applied directly on main and closed.

### Remote restore drill, chat fixes (2026-09-19, evening)
- **`restore-drill.sh --from-remote` PASSED on the Mac** — fetched from
  the new account's Google Drive (5 min), restored 5 lectures / 2848
  segments / 3007 chunks / settings, app healthy. Disaster recovery from
  the off-site copy alone is proven.
- **Chat "I don't see that covered" after long recordings** — root cause:
  the context was sized for the configured provider (Gemini: up to 300k
  chars); when Gemini's quota was spent the cascade handed that prompt to
  llama3, which Ollama truncates from the front (notes + instructions
  lost) → refusal. Fix: on fallback to Ollama, re-ask with a local-sized
  context (notes 8k, transcript tail 10k, docs 4k); prompt now treats
  summary/overview requests as always answerable. Verified: llama3
  summarises the 2 h lecture (50 s) instead of refusing.
- **Chat controls**: × on a message removes that question+answer (server
  `DELETE …/chat/{id}`, pair semantics); bin in the header clears the
  conversation (`DELETE …/chat`); answers return stored ids.
- Operator: Claude credits deferred to next payday.

### Google Drive folder selector (2026-09-19)
- Settings → Google Drive → **Choose existing folder…** opens Google's
  Picker (loaded on demand from apis.google.com) with the user's own
  short-lived access token (`GET /api/drive/picker-token`), the Picker
  API key and the app id (= Cloud project number, first part of the OAuth
  client id) — that combination makes the picked folder accessible under
  `drive.file`. `PATCH /api/drive {folder_id}` reads the folder back to
  confirm access and store its name.
- Admin: Settings → API keys → **Google Drive folder selector** → API key
  (`google_picker_api_key`, overrides file). Operator enabled the Google
  Picker API, created a key restricted to it and to the site, saved it;
  picked a folder and exported to it successfully.
- Tests: +2 (app id, picker availability) → 42.
- Settings sub-section renamed **Google Drive folder selector** (operator
  kept missing "Picker API key"). README: "Folder selector (optional)" —
  enable Google Picker API, create + restrict the key (Websites, Picker
  API only), paste into Settings; how the token/app-id handshake works.
  Guide notes the button appears only once an admin enabled it.

### Backend reorganised into packages (2026-09-19)
- `app/ui_backend/` now has only `main.py` at the top level; modules moved
  with `git mv` into `core/` (config, database, models, schemas,
  settings_store), `accounts/` (auth, ratelimit), `ai/` (transcriber,
  notes_generator, providers, image_analyzer, document_processor),
  `storage/` (s3_client, quota, cleanup, audio_backup), `exports/`
  (documents_export, mp3_export), `integrations/` (google_drive, mailer),
  `realtime/` (websocket_handler), `scripts/` (manage_users). `routes/`,
  `alembic/`, `tests/` unchanged.
- Imports rewritten mechanically (`import x` → `from pkg import x`, so
  `x.attr` call sites are untouched); path lookups that moved a level
  (`STATE_DIR`, the PDF logo) adjusted; ruff isort first-party list updated.
- Invocations changed: `python -m storage.audio_backup` (backup/restore/
  drill scripts), `python -m scripts.manage_users` (start.sh, README).
- Verified: ruff clean, 40 tests, and a full restore drill on the built
  image (migrations, health, Whisper, websocket, CLI) before deploying.
- Both READMEs describe the new layout (root: Project layout tree; backend
  README: package table). **License unchanged** — PolyForm Noncommercial
  1.0.0 covers the same code; new deps reportlab (BSD) and python-docx
  (MIT) are permissive; pymupdf (AGPL) is dev-only, not shipped.

### Dependency review, phone fixes, docs (2026-09-19)
- **Dependabot PRs**: #5 (20 Python bumps: FastAPI 0.109→0.141, pydantic
  2.6→2.13, websockets 12→17, faster-whisper 1.0→1.2, av 12→18, bcrypt
  4→5 …) validated by restoring production data into the drill stack with
  the PR image (`DRILL_IMAGE=`), then a real Whisper transcription and a full
  websocket session inside it — merged. #3 (React 18→19, Vite 6→8, uuid,
  react-markdown) built clean, no removed APIs in use — merged. #1 (Python
  3.14 base image) and #2 (Node 25, non-LTS) declined; dependabot.yml now
  ignores major/minor Python and major Node base-image bumps. Live stack
  runs the new set. bcrypt 5 raises on >72-byte passwords → validation cap.
- **Restore drill**: `DRILL_IMAGE` runs a candidate image (staging test);
  the drill no longer runs Tailscale at all (a busybox placeholder holds the
  network slot — an unsigned-in node restarted every minute and took the
  app's networking with it).
- **PDF/Word**: answers keep paragraphs/bullets (were flattened); Word gets
  a rule under the title. **Phone**: five export buttons as a full-width
  row, app-bar buttons shrink (MP3 / Sign out were cut off). **Transcript**
  follows only while at the bottom, scrolls its own pane (no more page
  drag on phones), "Jump to latest" pill.
- **README**: dark hero (theme-swap tried and reverted by request), light
  desktop shot re-cropped, phone composite dark-only; new sections on
  monitoring (`/health` + UptimeRobot), recording controls, notes editing,
  exports; config table gained WHISPER_LANGUAGE/VOCABULARY,
  REGISTRATION_APPROVAL, SUPPORT_EMAIL, BACKUP_NOTIFY_EMAIL, GOOGLE_CLIENT_*.

### PDF / Word export and stored chat (2026-09-18, late)
- `documents_export.py`: one branded document per lecture — title +
  "Recorded … · duration · Notes version", Contents strip, **1. Notes**
  (Markdown → blue H2s, blue bullets, bold/italic/code), **2. Questions &
  answers** (YOU label + bold question; AI · model label + tinted block with
  blue left rule), **3. Full transcript** (~30 s paragraphs, grey monospace
  time column). PDF via **reportlab 5.0.1** (new dependency), Word via
  python-docx (header/footer, shaded answers, two-column transcript table).
  Logo resolved from `dist/` in the image, `public/` in dev.
- Endpoints `GET /api/session/{id}/export/lecture.pdf|.docx` (filename from
  the title); toolbar buttons PDF/Word; History → Download → PDF/Word;
  Google Drive export now also uploads `lecture.pdf` + `lecture.docx`.
- **Chat stored per lecture** (migration 014 `chat_messages`; images not
  stored): `GET …/chat` reloads it when a lecture is reopened; deleted with
  the lecture; privacy page updated (questions are retained with the lecture).
- **Bug fixed**: `transcript.txt` timestamps were chunk-relative (all
  `00:0x`); now absolute (`chunk × 5 s + offset`) — same in the exports.
- Tests: +6 (builders, grouping, subtitle, inline runs) → 38 passing.
- Mockup kept at `design/pdf-mockup.pdf` (generated from the real lecture).

### Gap list, items 5, 6, 1, 9 (2026-09-18, evening)
- **Self-service account deletion**: Settings → Your account → Delete
  account (password-confirmed `DELETE /api/auth/me`): removes lectures,
  transcripts, notes, documents, audio objects, Drive link (revoked),
  reset tokens; signs out. Last admin cannot delete themselves. Tested.
- **Dependabot** (`.github/dependabot.yml`): weekly grouped pip + npm,
  monthly Docker + Actions.
- **Tests + CI**: `app/ui_backend/tests/` — 32 pytest tests (auth tokens,
  passwords, lockout/usage caps, notes merge + focus prompt, WebM header,
  Whisper prompt, Drive helpers, settings validation, provider cascade,
  API smoke via TestClient without a DB). conftest stubs faster-whisper
  and isolates STATE_DIR. `.github/workflows/ci.yml`: ruff + pytest +
  frontend build on push/PR — **green on first run**; README badge.
  `requirements-dev.txt`; ruff per-file ignore D103 for tests.
- **Old do-not-reply housekeeping**: new account added as project
  **Owner** (both listed). Changing the consent-screen support email was
  abandoned — Google demands Search Console ownership of
  `<tailnet>.ts.net` from the editing account; published config
  untouched. **Backups moved**: rclone reconnected as
  `<new do-not-reply mailbox>`, full re-upload (3007 chunks, ~225 MB,
  10 min) completed; old account's `LectureNotesBackups` folder can be
  trashed.

### Gap list, items 2–8 (2026-09-18)
- **Wake lock** while recording (re-acquired on visibility); guide notes the
  phone limits. **/health** checks Postgres + MinIO, GET or HEAD, 503 when
  degraded. **Container logs** capped 20 MB × 5 per service.
- **Uptime monitor**: UptimeRobot (account = business email) hits
  `/health` every 5 min; alerts to the business email.
- **Restore drill** `deploy/restore-drill.sh`: restores the newest bundle
  into throwaway project `lecture-drill` (own volumes, port 8020, unsigned
  Tailscale node), verifies users/lectures/segments/notes/schema/audio/
  settings/health, tears down. **PASSED** on the 09-18 bundle (5 lectures,
  2848 segments, 3007 audio objects). `--from-remote` (rclone, Mac) not yet
  run — the true DR path; ask the operator to run it once.
- **Transcription accuracy**: Whisper `initial_prompt` = lecture title +
  per-lecture key terms ("Aa" button, migration 012 `sessions.vocabulary`)
  + server-wide *Spelling hints* (Settings). *Transcription language*
  setting (fixed code or auto). Prompt applied on connect/start/PATCH.
- **Notes steering/editing**: per-lecture *notes focus* (migration 013)
  appended to the extraction prompt; `PATCH /api/session/{id}` for
  title/terms/focus; `PUT …/notes` saves an edited version that later
  passes merge into; `POST …/notes/regenerate` rebuilds from the whole
  transcript (fresh). Notes pane: pencil (edit) and sparkle (regenerate,
  not while recording). Tested on the real lecture, then restored (v29 =
  v26 content).
- **Per-user caps** (`ratelimit.allow`): 40 chat / 15 image / 20 uploads
  per 10 min, admins exempt, 429 + Retry-After.
- **Speaker separation (gap 9) — deliberately not built.** Discussed
  2026-09-18: pyannote diarization would double CPU load live; in the real
  setups (Zoom via BlackHole = one mixed channel without the user's own
  voice; in-person = far, quiet students lumped together) labels add little.
  If ever wanted: post-lecture background job after Stop, opt-in per
  lecture, ~1 day + Hugging Face model access.

### Recording controls and onboarding email (2026-09-16 → 18)
- **Mute no longer drops chunks**: it disabled the mic track *and* stopped
  sending; muting in the first 5 s lost the WebM header chunk so nothing
  after it decoded, and any mute shifted timestamps. Chunks are always
  sent now (muted = silence, skipped by the server's RMS gate). Status line
  reports "mic muted" / "mic on".
- **Pause / Resume** while recording (`MediaRecorder.pause()`; next chunk
  after resume is a plain continuation). Lecture stays open — no final
  notes, no export. After Stop the button reads **Continue recording**
  when the lecture has content (server already accepted a fresh header).
- **Mute names its device**: with a virtual input (BlackHole, Loopback,
  aggregate) the switch reads "Mute BlackHole 2ch" and the tooltip says it
  silences the meeting audio, not the user — use Zoom's own mute for that.
  Guide gained a Mac virtual-audio-device paragraph (routing, two mutes,
  aggregate device to capture own questions).
- **Approved-account email** now carries onboarding: audio kept N days
  (from Settings), download or Keep (limit from Settings), connect Google
  Drive, tab audio / speakerphone tip, link to `/guide`. Preview sent to
  the business inbox and checked.

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
- **Admin approval for sign-ups** (migration 011, `users.approved`):
  Settings → Sign-up has *Allow anyone…* and *Require my approval…*; both
  are **on** on this server. Flow: register → confirm email → every admin
  with an email gets "New account request" with a one-time approve link
  (7 days, `/api/auth/approve?token=`) → also a **pending** badge +
  Approve button in Settings → Users → user emailed "Your account is
  active". Login meanwhile: 403 `approval_pending`. Tested end to end by
  the operator from a phone (sign-up → confirm → approve link → active
  email); test accounts deleted. Sign-up form hides the password fields
  once the account is created.
- **Email addresses** (updated 2026-09-18): sender is now
  `<new do-not-reply mailbox>` (new App Password, set by the operator in
  `deploy/.env`; test email verified). Reply-To, backup-failure alerts,
  the admin account's email (→ approval requests, admin password reset)
  and the privacy contact are `<business email>`. The **old**
  `<old do-not-reply mailbox>` still owns the Google Cloud project
  `lecture-notes` (consent screen support email, both OAuth clients) and
  the backup Drive folder — optional housekeeping: add the new account as
  project Owner and `rclone config reconnect gdrive:` as the new account.
- **Privacy policy** at `/privacy` (public, no sign-in): formal, numbered
  sections — what is stored, AI providers, Google Drive scope/tokens/
  revocation, backups, choices, contact. Contact line comes from
  `SUPPORT_EMAIL` in `deploy/.env` (set to the business address; blank =
  generic wording in the public repo).
- **User guide** at `/guide` (public): 11 sections — getting started,
  recording controls, online classes/calls (speakerphone rule), slides,
  asking questions (follow-ups, pasted images), downloads, History/keep/
  quota/retention, Google Drive, phone install, account, privacy. Both
  static pages share `public/pages.css`; `/name` serves `name.html`.
- **Links**: sign-in page footer (guide · privacy), Settings footer, and a
  **?** icon button in the app bar right of Settings (opens the guide in a
  new tab so a recording is never interrupted).
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
2. ~~Sign-up~~ — reopened 2026-09-15 evening **with admin approval**
   (see above); invite codes not needed.
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
10. Optional: Claude API credits (operator: next payday). Demo account
    built (see above) — **needs a sample lecture shared with `test`**.
    Speaker separation
    **dropped from the list** 2026-09-19 — no benefit for the actual setups
    (mixed Zoom channel / far-field phone mic) against real CPU and setup
    cost; revisit only if usage shifts to in-room, discussion-heavy classes.
    Suggested next *project*:
    an AWS deployment option (ECS + RDS + S3, IaC) — résumé value and a
    "runs at home or in the cloud" story; fits as project #2 for LinkedIn.

**Status 2026-09-19:** feature-complete and stable. Nothing required is
open; remaining items are optional.

**Dependabot routine** (the one recurring chore): every Monday it opens PRs
bumping pinned libraries; GitHub emails the owner on open and when CI
finishes. Since 2026-09-19 `.github/workflows/dependabot-auto-merge.yml`
auto-merges **patch and minor** bumps once CI is green (repo settings
"Allow auto-merge" + "delete branch on merge" enabled via API) and comments
on majors / Docker base images, which a person validates with
`DRILL_IMAGE=… deploy/restore-drill.sh` before merging. Python/Node
base-image majors are ignored in dependabot.yml. Merging changes the repo
only — the live site updates on the next image build (`git pull` +
`deploy/start.sh`; first Monday of the month). Ignoring PRs breaks nothing;
they just accumulate (see the 2026-09-19 dependency review for the worked
example).
11. ~~Operator to run `deploy/restore-drill.sh --from-remote`~~ — done
    2026-09-19, PASSED against the new account's Drive.
12. ~~Revoke the two Gmail App Passwords that passed through chat~~ — done
    2026-09-19 (both accounts). The current sender password
    (the new do-not-reply mailbox) was entered directly into `deploy/.env`, never in
    chat.
13. stock-tracker's report emails are failing on a revoked App Password —
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
