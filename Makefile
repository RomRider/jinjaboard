PYTHON ?= /home/vscode/.local/ha-venv/bin/python
HASS ?= /home/vscode/.local/ha-venv/bin/hass

.PHONY: help install install-backend install-frontend \
        test test-backend test-frontend typecheck build run clean ci

help:
	@echo "install           - install backend + frontend dependencies"
	@echo "install-backend   - pip-install requirements-test.txt into \$$PYTHON"
	@echo "install-frontend  - npm install in src/"
	@echo "test              - run backend + frontend test suites"
	@echo "test-backend      - pytest"
	@echo "test-frontend     - vitest"
	@echo "typecheck         - tsc --noEmit"
	@echo "build             - bundle src/ into custom_components/jinjaboard/www/"
	@echo "run               - start a real HA instance against /config (devcontainer only)"
	@echo "clean             - remove build artifacts and caches"
	@echo "ci                - everything CI runs: typecheck, test-backend, test-frontend"

install: install-backend install-frontend

install-backend:
	# --system: PYTHON may point at a bare interpreter that isn't itself a
	# venv (e.g. CI's actions/setup-python one) — uv otherwise refuses to
	# install into it. Harmless when PYTHON is a real venv (e.g. the
	# devcontainer's ha-venv): the explicit -p path is still what's targeted,
	# --system only relaxes the "is this a venv" safety check.
	uv pip install --system -r requirements-test.txt -p $(PYTHON)
	# home-assistant-frontend isn't a pip dependency of the `homeassistant`
	# package itself (HA's own requirements-installer resolves it lazily at
	# runtime from the `frontend` component's manifest.json) but our tests
	# need it present up front. Read the exact version HA's own manifest
	# wants for whichever `homeassistant` version just got installed above,
	# rather than hand-pinning a second version number that can silently
	# drift out of sync with the first (as happened once already).
	uv pip install --system "$$($(PYTHON) -c 'import json, pathlib, homeassistant.components.frontend as f; print(json.loads(pathlib.Path(f.__file__).with_name("manifest.json").read_text())["requirements"][0])')" -p $(PYTHON)

install-frontend:
	cd src && npm install

test: test-backend test-frontend

test-backend:
	$(PYTHON) -m pytest

test-frontend:
	cd src && npm run test

typecheck:
	cd src && npm run typecheck

build:
	cd src && npm run build

run:
	container start-debug

clean:
	find . -name '__pycache__' -not -path './src/node_modules/*' -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf custom_components/jinjaboard/www

ci: typecheck test-backend test-frontend
