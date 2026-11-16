# WealthOS — common tasks.
.DEFAULT_GOAL := help
PY := .venv/bin/python
SHELL := /bin/bash

.PHONY: help setup data cohort models all dev api web test test-e2e lint clean db-reset

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv, install dependencies, run migrations
	python3.12 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt
	$(PY) -m pip install -q -e .
	cd frontend && pnpm install
	cd backend && ../$(PY) -m alembic upgrade head

data: ## Stages 01-04 — ingest, fetch, splice, validate, seed the database
	$(PY) -m ml.pipelines.p01_ingest_market
	$(PY) -m ml.pipelines.p02_fetch_external
	$(PY) -m ml.pipelines.p03_build_prices
	$(PY) -m ml.pipelines.p03b_validate_adjustment
	$(PY) -m ml.pipelines.p04_seed_database --reset

cohort: ## Stages 05-07 — holding priors, synthetic investors, feature tables
	$(PY) -m ml.pipelines.p05_big_sharks_priors
	$(PY) -m ml.pipelines.p06_generate_cohort --investors 10000
	$(PY) -m ml.pipelines.p07_features

models: ## Stages 08-11 — train, evaluate, measure Copilot grounding
	$(PY) -m ml.pipelines.p08_train_clustering
	$(PY) -m ml.pipelines.p09_train_anomaly
	for h in 1 3 6 12; do $(PY) -m ml.pipelines.p10_train_forecast --horizon $$h; done
	$(PY) -m ml.pipelines.p11_eval_copilot

all: data cohort models ## Run the whole pipeline end to end

api: ## Run the API on :8010
	cd backend && PYTHONPATH=.. ../$(PY) -m uvicorn app.main:app --reload --port 8010

web: ## Run the web app on :3000
	cd frontend && pnpm dev --port 3000

dev: ## Run both, API in the background
	@cd backend && PYTHONPATH=.. ../$(PY) -m uvicorn app.main:app --port 8010 & \
	 sleep 4 && cd frontend && pnpm dev --port 3000

test: ## Run the Python test suite
	$(PY) -m pytest -q

test-e2e: ## Run Playwright against a running stack
	cd frontend && npx playwright test

lint: ## Type-check the frontend
	cd frontend && npx tsc --noEmit && pnpm lint

db-reset: ## Drop and recreate the database, then re-seed
	dropdb --if-exists wealthos && createdb wealthos
	cd backend && ../$(PY) -m alembic upgrade head
	$(PY) -m ml.pipelines.p04_seed_database --reset

clean: ## Remove caches and build output
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache frontend/.next frontend/test-results frontend/playwright-report
