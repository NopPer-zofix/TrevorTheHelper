.PHONY: install lint format typecheck test check migrate telegram-login up down

PY ?= python

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy

test:
	pytest

# `make lint test` is the acceptance gate; this adds type-checking.
check: lint typecheck test

migrate:
	alembic upgrade head

# One-time interactive login (phone, code, 2FA) for the read-only reader account. Writes the
# session to ./data/, which docker-compose mounts into the indexer. Run before `make up`.
telegram-login:
	$(PY) -m aggregator.sources.telegram.login

up:
	docker compose up --build

down:
	docker compose down
