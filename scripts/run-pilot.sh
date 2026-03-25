#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/open-webui" ]]; then
  echo "Missing venv. Install: /opt/homebrew/bin/python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export DATA_DIR="${DATA_DIR:-$ROOT/data}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export OFFLINE_MODE="${OFFLINE_MODE:-true}"
export ENABLE_VERSION_UPDATE_CHECK="${ENABLE_VERSION_UPDATE_CHECK:-false}"
export WEBUI_AUTH="${WEBUI_AUTH:-false}"

mkdir -p "$DATA_DIR"
exec "$ROOT/.venv/bin/open-webui" serve --host 127.0.0.1 --port 8080
