# Changelog

All notable changes to AI Lecture Notes. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The current version lives in the
`VERSION` file and is shown in Settings and at `/health`.

## [1.0.0] — 2026-09-19

First release: the app as used daily for a graduate lecture series.

### Recording
- Live transcription in the browser (5-second chunks over a WebSocket, Whisper on the server), on desktop and phones (installable home-screen app; screen kept awake).
- Pause/Resume, mute (device-aware), tab audio for online classes, "Don't keep audio", Continue recording after a stop.
- Audio buffered in the browser across disconnects and server restarts — nothing lost.
- Key terms per lecture and server-wide spelling hints fed to Whisper; transcription language setting.

### Notes and questions
- Incremental notes (headings, key points, definitions, deadlines) merged as the lecture goes on; per-lecture focus; edit in place or regenerate.
- "Ask about the lecture": answers from the transcript, notes and uploaded slides/documents/images, with follow-up questions; chat kept with the lecture; remove or clear exchanges.
- Pluggable providers — local Ollama, Claude, Gemini, OpenAI — with automatic cascade and a visible "which model answered" label.

### Exports and Drive
- Markdown notes, text transcript, MP3 (built on demand with progress), and a formatted PDF / Word document (notes, Q&A, transcript with times).
- Per-user Google Drive: connect your own account (`drive.file` scope), automatic save after each lecture, create a folder path or pick an existing folder with Google's chooser.

### Accounts and operations
- Username/email sign-in, self-registration with email confirmation and optional admin approval, password reset by email, rate-limited sign-in, self-service account deletion; per-user quotas, retention, and up to five "kept" lectures.
- Docker Compose stack with a fixed public HTTPS URL via Tailscale Funnel; `/health` for uptime monitoring; nightly encrypted off-site backups with a scripted restore drill; container log rotation; Dependabot; CI (ruff + pytest + frontend build).
- Privacy policy and user guide served by the app.

## Before 1.0.0

Development began on 2026-01-29 (first prototype: browser recording, Whisper,
Ollama notes, Postgres + MinIO). The first real lectures were recorded on
2026-03-26; March and April brought WebSocket streaming, mute, downloads,
Claude for slides and images, and fixes found in live classes. The app was in
daily classroom use through the summer. The pre-release history was squashed
at the public release on 2026-09-14 because it contained personal details.

[1.0.0]: https://github.com/mrgutierrezmario/lecture-note-app/releases/tag/v1.0.0
