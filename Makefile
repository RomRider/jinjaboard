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
	uv pip install -r requirements-test.txt -p $(PYTHON)

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
	$(HASS) -c /config

clean:
	find . -name '__pycache__' -not -path './src/node_modules/*' -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf custom_components/jinjaboard/www

ci: typecheck test-backend test-frontend
