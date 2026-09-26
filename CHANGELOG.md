# Changelog

All notable changes to AI Lecture Notes. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The current version lives in the
`VERSION` file and is shown in Settings and at `/health`.

## [Unreleased]

### Added
- **Self-healing public URL**: the `tailscale` service now has a healthcheck that fetches the public Funnel URL end to end, and a new `watchdog` service restarts `tailscale` and `app` after three consecutive misses. Covers tailscaled's HTTPS listener hanging while the node still reports online (the 2026-09-20 outage), which `/health` and the uptime monitor could only report, not fix.

- **Chat helps with the assignment**: "make a strategy", "brainstorm", "explain X", "outline my answer" are now answered — using the lecture as the brief and the assistant's own knowledge for the rest, with the lecture's part marked. Questions about what the professor said stay grounded in the transcript. Answer cap raised from 600 to 1500 tokens.
- **Recording survives losing the microphone**: when Zoom, a phone call or a backgrounded tab takes the mic, the recorder now restarts itself on the same session (retrying for 10 minutes, and immediately when the tab returns), instead of silently sending nothing while the page still said Recording.
- **Delete lectures in bulk**: History has a checkbox per lecture, "Select all" and "Delete N selected" in a bar that stays pinned while scrolling. The confirmation names every lecture it will delete. Kept lectures and the one open in the workspace (it may be recording) can't be selected, and while anything is ticked the per-row delete buttons are hidden so a row's trash can't be mistaken for the bulk delete.

### Changed
- **Delete confirmations** ask "Are you sure…?", say plainly there is no trash or undo, and explain how to keep a copy first (Download menu or Google Drive). Every dangerous confirmation now opens with Cancel focused, so a reflexive Enter can't delete.

### Fixed
- `deploy/start.sh` falsely reported "Funnel is not enabled" (and could have tried to create a second admin): `grep -q` closing the pipe early made `pipefail` fail the check. It also now pulls images anonymously when the Docker credential helper cannot run (e.g. from a dev container shell), instead of failing the build.
- **Times were hours off** (4 h in New York): the API sent UTC timestamps without a zone, so browsers read them as local time. They now end in `Z` and every viewer sees their own local time. PDF and Word exports — downloads and "Save to Google Drive" — print the recorded time in the reader's timezone with the zone shown ("05:47 PM EDT"), and date the page header, footer and Drive folder where the reader is. Without a browser timezone (the automatic Drive export after a recording) they print UTC, labelled.
- **Lectures without a transcript were invisible** in History, so they could be neither seen nor deleted — including a recording whose transcription failed, whose audio still counted toward the storage quota. History now lists every lecture that holds anything (transcript, audio, notes or documents); only the empty sessions created by page loads stay hidden.

## [1.1.0] — 2026-09-19

### Added
- **Share a lecture** read-only with other accounts (person icon in History → pick a user → Share; Remove revokes). Viewers see it in their History with a "shared by" tag, can read, ask their own questions and export, and can follow the live transcript while it is being recorded.
- **Demo account**: "Try the demo" on the sign-in page opens a read-only visitor account with the lectures shared to it; Settings is view-only for it, nothing can be changed or recorded.

### Changed
- Sign-in page shows the company name under the logo.
- Settings and History dialogs scroll inside their rounded frame (the scrollbar no longer squares off the corners); History's footer note is a short list; Settings footer centred.
- Settings help text: notes interval wording, storage note placed under the storage field.

### Fixed
- PDF export crashed on notes that contained plain paragraphs.
- Demo sign-in was blocked by the auth middleware.

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

[1.1.0]: https://github.com/mrgutierrezmario/lecture-note-app/releases/tag/v1.1.0
[1.0.0]: https://github.com/mrgutierrezmario/lecture-note-app/releases/tag/v1.0.0
