.PHONY: dev dev-back dev-front test test-heavy test-front lint lint-fix type-check migrate migration check install help

PYTHON := python3
BACKEND := cd backend &&

help:
	@echo "Dev:       make dev | make dev-back | make dev-front"
	@echo "Tests:     make test | make test-heavy | make test-front"
	@echo "Quality:   make lint | make lint-fix | make type-check | make check"
	@echo "DB:        make migrate | make migration msg='describe change'"
	@echo "Setup:     make install"

# ── Dev servers ──────────────────────────────────────────────────────────────

dev:
	./start.sh

dev-back:
	$(BACKEND) uvicorn main:app --reload

dev-front:
	cd frontend && npm run dev

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	$(BACKEND) pytest -x -q

test-heavy:
	$(BACKEND) pytest -m heavy -v

test-cov:
	$(BACKEND) pytest -q --cov=. --cov-report=term-missing

test-front:
	cd frontend && npm run build

test-all: test test-front

# ── Quality ──────────────────────────────────────────────────────────────────

lint:
	$(BACKEND) ruff check .

lint-fix:
	$(BACKEND) ruff check . --fix

type-check:
	$(BACKEND) mypy .

check: lint type-check test test-front

# ── Database ──────────────────────────────────────────────────────────────────

migrate:
	$(BACKEND) alembic upgrade head

migration:
	$(BACKEND) alembic revision --autogenerate -m "$(msg)"

# ── Setup ────────────────────────────────────────────────────────────────────

install:
	$(BACKEND) pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install
	pre-commit install
