.DEFAULT_GOAL := help
SHELL := /bin/bash

BACKEND_PY := backend/.venv/bin/python
BACKEND_BIN := backend/.venv/bin

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------- setup
.PHONY: env
env: ## Create .env from .env.example if it does not exist
	@test -f .env || (cp .env.example .env && echo "Created .env — set POSTGRES_PASSWORD before use.")

.PHONY: install
install: env ## Install backend and frontend dependencies
	uv venv --python 3.12 backend/.venv
	cd backend && uv pip install -e ".[dev]"
	cd frontend && npm install

# ------------------------------------------------------------ infrastructure
.PHONY: up
up: ## Start PostgreSQL/PostGIS and Redis
	docker compose up -d postgres redis

.PHONY: up-all
up-all: ## Start the entire stack in Docker
	docker compose up -d --build

.PHONY: down
down: ## Stop all containers
	docker compose down

.PHONY: reset-db
reset-db: ## Destroy and recreate the database volume (DATA LOSS)
	docker compose down -v
	docker compose up -d postgres redis

# --------------------------------------------------------------- database
.PHONY: migrate
migrate: ## Apply migrations to head
	cd backend && ../$(BACKEND_BIN)/alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a revision: make migration m="add x"
	cd backend && ../$(BACKEND_BIN)/alembic revision --autogenerate -m "$(m)"

.PHONY: seed-sources
seed-sources: ## Register the data source provenance manifest
	$(BACKEND_PY) scripts/register_data_sources.py

# ------------------------------------------------------------------- run
.PHONY: backend
backend: ## Run the API with reload
	cd backend && ../$(BACKEND_BIN)/uvicorn app.main:app --reload --port 8000

.PHONY: frontend
frontend: ## Run the Next.js dev server
	cd frontend && npm run dev

# ------------------------------------------------------------------ checks
.PHONY: test
test: ## Run the backend test suite
	cd backend && ../$(BACKEND_BIN)/pytest

.PHONY: lint
lint: ## Lint and format-check the backend
	cd backend && ../$(BACKEND_BIN)/ruff check .
	cd backend && ../$(BACKEND_BIN)/ruff format --check .

.PHONY: typecheck
typecheck: ## Type-check the frontend
	cd frontend && npx tsc --noEmit

.PHONY: check
check: lint test typecheck ## Run every check

.PHONY: health
health: ## Probe the running API
	@curl -sf http://localhost:8000/health/ready | python3 -m json.tool
