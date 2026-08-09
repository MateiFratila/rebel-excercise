export UV_CACHE_DIR := $(CURDIR)/.cache/uv
export PIP_CACHE_DIR := $(CURDIR)/.cache/pip
export DATABASE_URL ?= postgresql+asyncpg://faq:faq@localhost:5432/faq
export TEST_DATABASE_URL ?= $(DATABASE_URL)

BACKEND_CHECK_PROJECT ?= rebel_dot_check

.PHONY: check security evaluation compose-smoke backend-check frontend-check backend-dev frontend-dev

check: backend-check frontend-check

backend-check:
	@set -eu; \
	cleanup() { docker compose -p $(BACKEND_CHECK_PROJECT) down -v; }; \
	trap cleanup EXIT; \
	docker compose -p $(BACKEND_CHECK_PROJECT) up -d --wait postgres; \
	cd backend; \
	uv run alembic upgrade head; \
	uv run alembic check; \
	uv run ruff format --check .; \
	uv run ruff check .; \
	uv run mypy src; \
	uv run pytest

frontend-check:
	cd frontend && npm run lint
	cd frontend && npm run typecheck
	cd frontend && npm run test
	cd frontend && npm run build
	cd frontend && npm run test:e2e

security:
	cd backend && uv run pip-audit
	cd frontend && npm audit --audit-level=high

evaluation:
	cd backend && uv run python -m rebel_dot.ops.evaluate --check

compose-smoke:
	./scripts/compose-smoke.sh

backend-dev:
	cd backend && uv run uvicorn rebel_dot.api.app:create_app --factory --reload

frontend-dev:
	cd frontend && npm run dev
