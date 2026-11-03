.PHONY: install lint format typecheck test check migrate up down

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

up:
	docker compose up --build

down:
	docker compose down
