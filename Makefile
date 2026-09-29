PYTHON ?= python3.13
VENV := .venv
BIN := $(VENV)/bin
COMPOSE := docker compose -f demo-system/docker-compose.yml
MODEL ?= groq:llama-3.3-70b-versatile

.DEFAULT_GOAL := help
.PHONY: help install up down ps logs test lint format eval-fake eval eval-baseline lock clean \
	dashboard-up api-dev api-test ui-install ui-dev ui-test ui-e2e

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

$(BIN)/opspilot: requirements.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --upgrade pip
	$(BIN)/python -m pip install --quiet -r requirements.lock
	$(BIN)/python -m pip install --quiet --no-deps -e .
	@touch $@

install: $(BIN)/opspilot ## Create .venv and install the pinned dependencies

up: ## Build and start the demo system (docker compose)
	$(COMPOSE) up -d --build

dashboard-up: ## Demo system plus the agent API (:8180) and the dashboard (:8100), in docker
	$(COMPOSE) --profile dashboard up -d --build

down: ## Stop the demo system (and the dashboard, if running) and remove their volumes
	$(COMPOSE) --profile dashboard down -v

ps: ## Show demo system containers
	$(COMPOSE) --profile dashboard ps

logs: ## Follow demo system logs
	$(COMPOSE) --profile dashboard logs -f --tail=50

test: install ## Run the test suite (integration tests run only if the stack is up)
	$(BIN)/pytest

lint: install ## Ruff lint and format check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: install ## Apply ruff fixes and formatting
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

# Deterministic harness check: simulated telemetry + the playbook model. No Docker, no API key.
# The playbook is deterministic, so any drop below 100% is a regression in the harness.
eval-fake: install ## Benchmark in the simulated environment with the playbook model (CI)
	$(BIN)/opspilot-eval --env simulated --model fake:playbook --fail-under 1.0

eval: install ## Real benchmark: live stack + LLM (needs `make up` and a key in .env)
	$(BIN)/opspilot-eval --env live --model $(MODEL) --verbose

eval-baseline: install ## Playbook baseline against the live stack (needs `make up`)
	$(BIN)/opspilot-eval --env live --model fake:playbook --verbose

# -- agent API and dashboard, run locally against the stack from `make up` -----------------

api-dev: install ## Agent API on :8180 against the local stack, reloading on code changes
	OPSPILOT_CHAOS_URL=$${OPSPILOT_CHAOS_URL:-http://localhost:8190} \
		$(BIN)/opspilot-api --port 8180 --reload

api-test: install ## Agent API tests (fake models, in-process tools, one real MCP server run)
	$(BIN)/pytest tests/api

ui/node_modules: ui/package.json ui/package-lock.json
	cd ui && npm ci --no-audit --no-fund
	@touch $@

ui-install: ui/node_modules ## Install the dashboard's pinned npm dependencies

ui-dev: ui/node_modules ## Dashboard on :8100 (next dev), proxying /api to the agent API on :8180
	cd ui && OPSPILOT_API_URL=$${OPSPILOT_API_URL:-http://localhost:8180} npm run dev

ui-test: ui/node_modules ## Dashboard format check, lint, typecheck and unit tests
	cd ui && npm run format:check && npm run lint && npm run typecheck && npm test

ui-e2e: ui/node_modules ## Dashboard production build and Playwright smoke tests (uses Google Chrome)
	cd ui && npm run build && npm run e2e

lock: ## Re-pin the full development environment into requirements.lock
	@echo "# Fully pinned development environment (Python 3.13). Regenerate with: make lock" > requirements.lock
	$(BIN)/python -m pip freeze --exclude-editable | grep -viE '^(hatchling|trove-classifiers|pathspec)==' >> requirements.lock

clean: ## Remove caches and local eval results
	rm -rf .pytest_cache .ruff_cache ui/.next ui/test-results ui/playwright-report
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find evals/results -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
