#!/usr/bin/env bash
# Installs every dependency this repo needs for local development, run on
# every container start (not just create) so a `git pull` that changed
# package.json/requirements-test.txt is picked up without a full rebuild.
# Both installs are idempotent/fast no-ops when nothing changed, so running
# them unconditionally on every start is cheap.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "==> Installing frontend dependencies (src/)"
(cd src && npm install)

echo "==> Installing backend test dependencies (/home/vscode/.local/ha-venv)"
uv pip install -r requirements-test.txt -p /home/vscode/.local/ha-venv/bin/python
