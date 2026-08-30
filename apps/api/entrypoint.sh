#!/bin/sh
set -e

echo "[entrypoint] applying database migrations..."
alembic upgrade head

echo "[entrypoint] starting WHAT IF API..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
