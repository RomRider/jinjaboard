#!/usr/bin/env bash
# Installs every dependency this repo needs for local development, run on
# every container start (not just create) so a `git pull` that changed
# package.json/requirements-test.txt is picked up without a full rebuild.
# Delegates to `make install` (see Makefile) so there's one definition of
# what "installed" means, shared with manual/CI use. Both installs are
# idempotent/fast no-ops when nothing changed, so running them
# unconditionally on every start is cheap.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
make install
