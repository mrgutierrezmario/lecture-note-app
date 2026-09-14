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
exec uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
