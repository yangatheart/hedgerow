#!/usr/bin/env bash
# Start the Smart Agriculture MVP at http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements-dev.txt
fi
cd backend
exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" --reload --reload-dir app
