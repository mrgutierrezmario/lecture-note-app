# AI Lecture Notes

[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](app/ui_backend)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](app/ui_backend)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black)](app/ui)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](deploy)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-D7FF64.svg)](app/ui_backend/pyproject.toml)

Record a lecture from your browser, watch the transcript appear live, and get
structured notes generated every minute — then ask questions about the lecture
afterwards. Everything runs on your own machine; cloud AI providers are
optional.

**By M.G. Network and Technology Solutions.**

| | |
|---|---|
| Transcription | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on CPU, live, 5-second chunks |
| Notes & chat | Local [Ollama](https://ollama.com) (default) — or Claude, Gemini or OpenAI via API key |
| Slides & images | Claude / Gemini / OpenAI vision, falling back to local llava |
| Accounts | Username or email sign-in, self-registration, emailed password reset, admin role |
| Per user | Lecture history, per-user storage quota, "keep" up to 5 lectures from cleanup |
| Runs as | A Docker Compose stack (Postgres, MinIO, app) with a fixed public HTTPS URL via Tailscale Funnel — free, no domain needed |
| Works on | Desktop browsers and phones (installable as a home-screen app) |

---

## Contents

1. [How it works](#how-it-works)
2. [Quick start (development)](#quick-start-development)
3. [Production setup (Docker, one command)](#production-setup-docker-one-command)
4. [Public URL and phones](#public-url-and-phones)
5. [Accounts and roles](#accounts-and-roles)
6. [AI providers](#ai-providers)
7. [Recording tips](#recording-tips)
8. [Configuration reference](#configuration-reference)
9. [Storage, retention and quotas](#storage-retention-and-quotas)
10. [Project layout](#project-layout)
11. [Troubleshooting](#troubleshooting)
12. [Contributing](#contributing)

---

## How it works

```
Browser (React) ──WebSocket: 5 s WebM chunks──▶ FastAPI backend
                ◀── transcript segments, notes ──      │
                                                       ├─ ffmpeg → Whisper (CPU)      transcript
                                                       ├─ text provider (Ollama/…)    notes every 60 s, chat
                                                       ├─ vision provider (…/llava)   slides & images
                                                       ├─ Postgres                    sessions, transcripts, notes, users
                                                       └─ MinIO (S3)                  audio chunks (14-day retention)
```

- The browser records with `MediaRecorder` and streams 5-second chunks over a
  WebSocket. Each chunk is stored, transcribed, and its text pushed back
  immediately.
- Every 60 seconds the new transcript is sent to the text provider, which
  returns Markdown sections that are merged into the running notes.
- Uploaded PDFs/PowerPoint/Word files are text-extracted; images are read by a
  vision model. All of it becomes context for "Ask about the lecture".
- Audio is deleted after 14 days (transcripts and notes are kept) unless the
  user marks a lecture as *kept*.

---

## Quick start (development)

Runs the backend with auto-reload and the Vite dev server with hot reload.

### Prerequisites

- **Python 3.11+**, **Node.js 18+**, **ffmpeg** (`brew install ffmpeg` / `apt install ffmpeg`)
- **PostgreSQL** and **MinIO** — easiest via Docker: `docker compose up -d`
  (the root `docker-compose.yml` starts both with dev credentials and creates the bucket)
- **Ollama** with a model pulled: `brew install ollama && ollama pull llama3`
  (and `ollama pull llava` for local image reading)

### Steps

```bash
git clone <this repo> lecture-note-app && cd lecture-note-app

# Backend
cd app/ui_backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # defaults match the docker-compose dev services
(cd alembic && alembic upgrade head)   # create the tables

# First admin account
python manage_users.py create admin --admin      # prompts for a password

# Frontend
cd ../ui && npm install
```

Then start everything:

```bash
./start.sh        # Ollama → backend (:8000) → Vite (:5173), Ctrl+C stops all
```

Open http://localhost:5173, sign in as the admin you created, allow the
microphone, and press **Start recording**.

> The Vite dev server proxies `/api` and `/ws` to the backend, so there is no
> CORS setup. To test on a phone on the same Wi-Fi, use `npm run dev:https`
> (self-signed certificate — browsers only allow the microphone over HTTPS).

---

## Production setup (Docker, one command)

The production setup is a self-contained Docker Compose stack in `deploy/`:
Postgres, MinIO, the app (backend + built UI on one port), Tailscale for the
public URL, and optionally Ollama. Everything restarts on its own after a
reboot; all data lives in Docker volumes.

### Prerequisites

- Docker Desktop (Mac/Windows) or Docker Engine (Linux), with **≥ 8 GB** of
  memory available to containers
- A free [Tailscale](https://tailscale.com) account (for the public HTTPS URL)
- Optional but recommended on a Mac: Ollama installed natively for GPU speed
  (see [AI providers](#ai-providers))

### Steps

```bash
git clone <this repo> lecture-note-app && cd lecture-note-app
deploy/start.sh
```

`start.sh` is safe to re-run and does, in order:

1. Creates `deploy/.env` from `deploy/.env.example` with generated secrets
   (database and MinIO passwords, `SECRET_KEY`). Edit it afterwards if needed.
2. Builds the app image and starts all containers.
3. Pulls the Ollama models (bundled Ollama only).
4. Prints a **Tailscale sign-in link** the first time — open it, sign in with
   Google/GitHub/Microsoft, approve the device. Then enable Funnel once when
   prompted (`tailscale funnel --bg 8000` inside the container prints the link).
5. Creates the first admin account and prints its generated password.
6. Prints the public URL: `https://<TS_HOSTNAME>.<your-tailnet>.ts.net`.

Day-to-day:

```bash
deploy/start.sh                                  # after pulling new code: rebuild + restart what changed
deploy/stop.sh                                   # stop; data is kept
docker compose -f deploy/compose.yml logs -f app # follow the app log
docker compose -f deploy/compose.yml exec app python manage_users.py list
```

### Keeping it up after a reboot

- Every container is `restart: unless-stopped`, so once Docker is running the
  stack comes back by itself.
- On a Mac: set Docker Desktop to **start at sign-in**, and either enable
  automatic login or accept that a reboot needs one login at the keyboard.
- In the Tailscale admin console, open the machine and **Disable key expiry**
  so it never asks to re-authenticate.

### Sizing (a 16 GB Mac mini is plenty)

| Process | RAM |
|---|---|
| Docker VM (app + Whisper + Postgres + MinIO + Tailscale) | ~3 GB in use; cap at 8 GB |
| Native Ollama, one model loaded | ~5 GB (llama3) |
| macOS | ~3.5 GB |

Measured on an M-series Mac mini: three simultaneous recordings keep up with
real-time transcription; a fourth falls behind. Moving notes to a cloud
provider frees the CPU for Whisper.

---

## Public URL and phones

Browsers only allow microphone access over **HTTPS** (or `localhost`), so a
phone needs a real HTTPS address. The stack uses **Tailscale Funnel**: free,
no domain to buy, a fixed `https://<name>.<tailnet>.ts.net` URL with a valid
certificate, unlimited bandwidth. Change the name with `TS_HOSTNAME` in
`deploy/.env` and re-run `deploy/start.sh` (the old URL stops working).

Alternatives: a Cloudflare Tunnel with your own domain, or any reverse proxy
with a certificate in front of port 8000 — the app doesn't care which.

**Phones:** open the URL in Chrome/Safari and use *Add to Home screen* for an
app icon. The first tap on *Enable microphone* or *Start recording* asks for
the mic. Phones cannot record the *other* side of a phone/Zoom call (the OS
gives the mic to the call) — put the call on speakerphone, record from a
second device, or on a computer use **Tab audio** to capture a Zoom window.

---

## Accounts and roles

Everyone signs in with a username **or** email and a password (bcrypt
hashed). Logins last 30 days.

| | Regular user | Admin |
|---|---|---|
| Record, live transcript, notes, chat, uploads | own lectures | same |
| History: open (read-only), rename, delete, delete audio, download | own lectures | all lectures, owner shown |
| Keep lectures (skip cleanup, block deletion) | up to 5 | unlimited |
| Storage quota (retained audio) | 500 MB default | sets per-user overrides |
| Accounts | self-register (if open), forgot password, change own email/password | manage users, reset passwords, close sign-up |
| Models, API keys, provider choice, limits | — | Settings |

- **Self-registration** is on by default. Anyone with the URL can create an
  account until you turn it off in **Settings → Sign-up** — do that once your
  users are enrolled.
- **Forgot password** emails a single-use, one-hour link. It needs outgoing
  mail configured (`MAIL_*` in `deploy/.env`; a Gmail address with an App
  Password works well — use a dedicated `…donotreply@gmail.com` account so
  replies don't land in your inbox). Without mail, the link isn't offered and
  admins reset passwords from **Settings → Users**.
- Shell fallback: `manage_users.py create|list|passwd|delete`.

---

## AI providers

Two jobs, each with its own provider selector in **Settings → Models**:

| Job | Options | Fallback |
|---|---|---|
| **Notes & chat** | Local Ollama (default, private) · Claude · Gemini · OpenAI | Ollama |
| **Slides & images** | Claude (best on dense slides) · Gemini · OpenAI · local llava | llava, then a BLIP caption |

Paste API keys under **Settings → API keys**; all three can be saved at once
and each job picks independently. A cloud failure (bad key, quota, outage)
falls back automatically so a lecture never loses its notes.

- **Gemini** has a free, rate-limited tier — get a key at
  [aistudio.google.com](https://aistudio.google.com). The model dropdown is
  fetched live from Google, so it never goes stale; "Gemini Flash Latest"
  tracks the newest release automatically.
- **Claude** and **OpenAI** need prepaid API credits (a chat subscription is
  not API access).
- **Privacy note:** with a cloud provider selected, lecture transcripts are sent
  to that provider. Local Ollama keeps everything on your machine.

### Native Ollama on a Mac (recommended)

Docker cannot use Apple's GPU, so the bundled Ollama runs on CPU. A native
install uses Metal and is faster, and frees the CPU for transcription:

```bash
brew install ollama
brew services start ollama          # or use deploy/mac/com.mgnetwork.ollama.plist (see inside)
ollama pull llama3 && ollama pull llava
```

then set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `deploy/.env`
and re-run `deploy/start.sh`. On a 16 GB machine, the launch agent in
`deploy/mac/` keeps only one model in memory at a time.

---

## Recording tips

| Control | What it does |
|---|---|
| Microphone dropdown | Which input to record. A virtual device (e.g. BlackHole on macOS) captures system audio |
| Tab audio | Also record a browser tab (Zoom in a browser, a video) alongside the mic — desktop only |
| Mute mic | Pause the microphone without stopping the recording |
| Don't keep audio | Transcribe without storing the recording: no MP3 later, no quota used |
| Keep (lock) in History | Exempt a lecture from the 14-day audio cleanup and from deletion |

**Zoom on macOS:** setting Zoom's speaker to BlackHole silences your own
output. Create a *Multi-Output Device* in Audio MIDI Setup containing both
your speakers and BlackHole, set it as the system output, and pick BlackHole
as the app's microphone.

The app warns after 15 seconds of digital silence (typically the OS holding
the mic for a call).

---

## Configuration reference

Production config lives in `deploy/.env` (created by `start.sh`); development
config in `app/ui_backend/.env`. Everything not listed has a sensible default
in `app/ui_backend/config.py`. Settings marked *panel* can also be changed at
runtime from the admin Settings panel and persist in the app-state volume.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | generated | Signs login cookies; changing it signs everyone out |
| `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD` | generated | Internal service credentials |
| `TS_HOSTNAME` | `lecture-notes` | First part of the public URL |
| `TS_AUTHKEY` | — | Optional Tailscale auth key to skip the interactive sign-in |
| `APP_PORT` | `8010` | Local port on the host for `http://localhost:<port>` |
| `OLLAMA_BASE_URL` | bundled | Point at a native Ollama: `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` *(panel)* | `llama3` | Local notes/chat model |
| `WHISPER_MODEL` *(panel, restart)* | `small` | `base` is faster, `medium`/`large-v3` more accurate but slower than real time on CPU |
| `NOTES_INTERVAL_SECONDS` *(panel)* | `60` | How often notes regenerate |
| `STORAGE_QUOTA_MB` *(panel)* | `500` | Retained audio per user (0 = unlimited) |
| `MAX_LOCKED_LECTURES` *(panel)* | `5` | Kept lectures per regular user (admins unlimited) |
| `MAX_UPLOAD_MB` | `50` | Largest document/image upload |
| `AUDIO_RETENTION_DAYS` | `14` | Audio deleted after this many days |
| `REGISTRATION_OPEN` *(panel)* | `true` | Whether the sign-in page offers "Create account" |
| `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_REPLY_TO` | — | SMTP (Gmail App Password) for reset emails |
| `PUBLIC_URL` | — | Base URL used in emailed links |
| `SESSION_DAYS` | `30` | Login cookie lifetime |

API keys (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`) are entered
in the Settings panel and stored in the app-state volume; leave them out of
`deploy/.env` (an empty value there would shadow the saved key).

---

## Storage, retention and quotas

- **Audio** is stored in MinIO as 5-second WebM chunks (~5 MB per lecture-hour)
  and deleted after `AUDIO_RETENTION_DAYS`. **Transcripts and notes are kept
  indefinitely.**
- Each user has a **quota** on retained audio. Over quota, a new recording is
  refused with an explanation (they can still record with *Don't keep audio*);
  if the quota fills mid-lecture, the transcript continues and only the audio
  stops being kept. Users free space by deleting a lecture's audio (keeping its
  transcript) from History.
- **Kept** lectures are exempt from cleanup and cannot be deleted until unlocked.
- A cleanup pass runs every 24 h; trigger one manually with
  `POST /api/admin/cleanup_audio` (admin).

---

## Project layout

```
app/ui_backend/          FastAPI backend
  main.py                app wiring; serves the built UI in production
  websocket_handler.py   the recording socket: chunks in, transcript/notes out
  transcriber.py         ffmpeg + faster-whisper
  notes_generator.py     incremental notes (extract → merge)
  providers.py           Ollama / Claude / Gemini / OpenAI behind one interface
  auth.py, routes/auth.py  accounts, cookie sessions, registration, password reset
  routes/sessions.py     per-lecture API: transcript, notes, exports, uploads, chat
  routes/history.py      lecture list, rename, delete, keep, quota usage
  routes/settings.py     admin settings, API keys, provider tests
  quota.py, cleanup.py   storage accounting and retention
  models.py, alembic/    schema and migrations (applied on startup)
  manage_users.py        CLI for accounts
app/ui/                  React + Vite frontend (src/components, src/hooks)
deploy/                  compose.yml, Dockerfile, start.sh/stop.sh, mac/ launch agent
```

Backend code is formatted and linted with [ruff](https://docs.astral.sh/ruff/)
(`app/ui_backend/pyproject.toml`): `venv/bin/ruff format . && venv/bin/ruff check .`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Microphone needs HTTPS" | Phones and remote browsers require HTTPS; use the Tailscale URL or `npm run dev:https` |
| Mic blocked in the installed phone app | Long-press the app icon → App info → Permissions → Microphone → Allow |
| Transcript lags behind | Too many simultaneous recordings, or Whisper model too large for the CPU — use `small` |
| Notes never appear | The first pass runs 60 s after recording starts; check **Settings → Models** for the active provider and the app log (`docker compose … logs app`) |
| Ollama "killed" / notes fall back to heuristics | Not enough memory to load the model — raise Docker's memory or use a smaller model |
| Gemini "model not available" | Google retired that model name; pick another from the dropdown (or "Gemini Flash Latest") |
| Empty Gemini answers (`MAX_TOKENS`) | Handled automatically (thinking is disabled per model); update if it recurs |
| Password reset email never arrives | `MAIL_*` unset, or the Gmail App Password was revoked — re-create it |
| Recording during a phone/Zoom call captures silence | The OS gives the mic to the call; use speakerphone or Tab audio on a computer |

---

## Contributing

Issues and pull requests are welcome. Before opening a PR:

```bash
cd app/ui_backend && venv/bin/ruff format . && venv/bin/ruff check .   # must pass (includes docstring checks)
cd ../ui && npm run build                                                 # must build
```

Never commit `.env` files, `deploy/.env`, or anything under `deploy/state/`
(all git-ignored). API keys belong in the Settings panel, not in the repo.

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — © 2026 M.G. Network and Technology Solutions.

Free to use, modify and share for **noncommercial** purposes: personal study,
research, hobby projects, and use by educational institutions, charities and
other noncommercial organizations. **Commercial use requires a separate
license** — contact the copyright holder.
