#!/bin/bash
# Wait for Postgres, apply migrations, then serve.
set -e

host="${POSTGRES_HOST:-postgres}"
echo "[app] waiting for postgres at $host..."
for i in $(seq 1 60); do
  pg_isready -q -h "$host" -p 5432 && break
  sleep 1
done

echo "[app] applying migrations..."
(cd alembic && alembic upgrade head)

echo "[app] starting on :8000"
# Trust X-Forwarded-For only from 127.0.0.1: Funnel and the optional Cloudflare
# tunnel both reach the app there (same network namespace). With '*', uvicorn
# takes the left-most address, which any client can write, so rate limits keyed
# on the client IP could be sidestepped; with a trusted proxy it takes the
# right-most untrusted one — the real visitor.
exec uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
