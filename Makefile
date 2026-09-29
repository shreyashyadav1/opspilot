PYTHON ?= python3.13
VENV := .venv
BIN := $(VENV)/bin
COMPOSE := docker compose -f demo-system/docker-compose.yml
MODEL ?= groq:llama-3.3-70b-versatile

.DEFAULT_GOAL := help
.PHONY: help install up down ps logs test lint format eval-fake eval eval-baseline lock clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

$(BIN)/opspilot: requirements.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --upgrade pip
	$(BIN)/python -m pip install --quiet -r requirements.lock
	$(BIN)/python -m pip install --quiet --no-deps -e .
	@touch $@

install: $(BIN)/opspilot ## Create .venv and install the pinned dependencies

up: ## Build and start the demo system (docker compose)
	$(COMPOSE) up -d --build

down: ## Stop the demo system and remove its volumes
	$(COMPOSE) down -v

ps: ## Show demo system containers
	$(COMPOSE) ps

logs: ## Follow demo system logs
	$(COMPOSE) logs -f --tail=50

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

lock: ## Re-pin the full development environment into requirements.lock
	@echo "# Fully pinned development environment (Python 3.13). Regenerate with: make lock" > requirements.lock
	$(BIN)/python -m pip freeze --exclude-editable | grep -viE '^(hatchling|trove-classifiers|pathspec)==' >> requirements.lock

clean: ## Remove caches and local eval results
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find evals/results -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
