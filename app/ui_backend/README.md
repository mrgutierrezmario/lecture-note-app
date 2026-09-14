# Lecture Notes Backend

FastAPI backend for AI Lecture Notes. See the root `README.md` for the full setup guide;
this file covers backend-specific details.

## Setup

### Prerequisites

- Python 3.11+
- ffmpeg installed and in PATH
- PostgreSQL running with `lecture_notes` database
- MinIO running with `lecture-audio` bucket
- Ollama running with `llama3` pulled

### Installation

```bash
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

# Run database migrations (alembic.ini lives in alembic/)
(cd alembic && alembic upgrade head)
```

### Running

Use the root `start.sh` to start all services together, or run the backend directly:

```bash
venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Configuration

Settings are defined in `config.py` and can be overridden with a `.env` file in this directory.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/lecture_notes` | Postgres connection string |
| `WHISPER_MODEL` | `small` | Whisper model size — `small` keeps up with realtime on CPU |
| `NOTES_INTERVAL_SECONDS` | `60` | Seconds between automatic notes generation |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `llama3` | Ollama model for notes generation |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | MinIO endpoint |
| `S3_ACCESS_KEY` | `minioadmin` | MinIO access key |
| `S3_SECRET_KEY` | `minioadmin` | MinIO secret key |
| `S3_BUCKET` | `lecture-audio` | Bucket for audio chunks |
| `AUDIO_RETENTION_DAYS` | `14` | Days to keep audio before cleanup |
| `CLEANUP_INTERVAL_HOURS` | `24` | How often the cleanup task runs |

## Whisper Models

| Model | Speed | Accuracy | Notes |
|-------|-------|----------|-------|
| `tiny` | Fastest | Low | Development/testing only |
| `base` | Fast | Decent | Quick demos |
| `small` | Moderate | Good | **Current default** — ~1.1s per 5s chunk on CPU, keeps up with realtime |
| `medium` | Slow | Better | Good balance |
| `large-v3` | Slowest | Best | Best accuracy, but slower than realtime on CPU — GPU or offline reruns only |

Models are downloaded from HuggingFace on first use and cached in `~/.cache/huggingface/hub/`. A container rebuild that resets the home volume clears this cache, and the next run re-downloads.

## Notes Generation

Notes are generated every `NOTES_INTERVAL_SECONDS` and immediately on recording stop.

- **Ollama available**: uses `llama3` to produce structured markdown with Outline, Key Concepts, Definitions, Examples, Action Items, and Questions sections
- **Ollama unavailable**: falls back to a regex heuristic that extracts the same sections from the raw transcript

## API Documentation

Visit http://localhost:8000/docs for interactive Swagger UI.

## Troubleshooting

### ffmpeg not found

```bash
brew install ffmpeg       # macOS
sudo apt install ffmpeg   # Ubuntu/Debian
```

### Database connection errors

Confirm PostgreSQL is running and the `lecture_notes` database exists:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -c "\l"
```

### Ollama not generating notes

Confirm Ollama is running and `llama3` is available:

```bash
curl http://localhost:11434/api/tags
ollama list
```

### Out of memory with large-v3

Switch to a smaller model in `.env`:

```env
WHISPER_MODEL=medium
```

### First transcription is slow

The Whisper model loads into memory on the first chunk. With `large-v3` expect 10–20 seconds on the first request. Subsequent chunks are faster.
