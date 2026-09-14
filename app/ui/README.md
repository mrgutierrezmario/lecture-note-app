# Lecture Notes Frontend

React + Vite frontend for AI Lecture Notes. See the root `README.md` for the full setup guide;
this file covers frontend-specific details.

## Setup

### Prerequisites

- Node.js 18+
- Backend running at http://localhost:8000

### Installation

```bash
npm install
```

### Running

Use the root `start.sh` to start all services together, or run directly:

```bash
npm run dev
```

Open http://localhost:5173.

## Features

- Audio device selection — pick any input including virtual audio devices (BlackHole, etc.)
- Browser tab audio capture via `getDisplayMedia`
- Mic mute toggle (without stopping the recording)
- Real-time transcript via WebSocket streaming
- AI notes rendered as markdown, updated every 60 seconds
- Export notes (`.md`), transcript (`.txt`), and audio (`.mp3`)
- File upload for supplementary documents (PDF, PPTX)
- Chat pane for querying the session content
- Session title and UUID-based persistence

## Audio Capture

The app supports three audio modes, which can be combined:

1. **Mic / virtual device** — select from the "Audio input" dropdown. To capture Zoom or system audio on macOS, select your virtual audio device (e.g. BlackHole) here.
2. **Browser tab audio** — enable "Also capture browser tab audio", then pick a Chrome Tab in the system share dialog and check "Share tab audio".
3. **Mixed** — both mic and tab audio are merged via Web Audio API before being sent to the backend.

## Proxy

Vite proxies `/api` and `/ws` to `http://localhost:8000`, so the frontend and backend can run on different ports without CORS issues.

## Browser Support

Requires:
- MediaRecorder API with `audio/webm;codecs=opus`
- WebSocket API
- ES2020+

Tested on Chrome 90+, Firefox 85+, Safari 14+, Edge 90+.

## Troubleshooting

### Microphone access denied

Grant microphone permissions in the browser. In Chrome, click the lock icon in the address bar.

### WebSocket connection failed

Ensure the backend is running at http://localhost:8000. Check `/tmp/backend.log` for errors.

### Virtual audio device not appearing in dropdown

Ensure the device is installed and enabled at the OS level. Reload the page — the app re-enumerates devices on mount and on `devicechange` events.

### Tab audio not working

The browser requires a user gesture to call `getDisplayMedia`. Make sure you click "Start Recording" yourself (not programmatically). In the system share dialog, select a Chrome Tab and check "Share tab audio".
