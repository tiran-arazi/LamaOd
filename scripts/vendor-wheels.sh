#!/usr/bin/env bash
# Run on a machine WITH internet. Copy "wheels-offline/" + this repo to the air-gapped server, then:
#   py -3.12 -m venv .venv
#   .venv\Scripts\pip install --no-index --find-links=wheels-offline -r requirements.txt
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
rm -rf wheels-offline
mkdir -p wheels-offline
. .venv/bin/activate
pip download -r requirements.txt -d wheels-offline
echo "Wheels saved under $ROOT/wheels-offline"
