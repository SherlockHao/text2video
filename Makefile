.PHONY: install dev worker test lint format migrate migration docker-up docker-down docker-build

install:
	pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	python -m arq app.ai.worker.WorkerSettings

test:
	pytest -v

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check --fix .

migrate:
	alembic upgrade head

migration:
	alembic revision --autogenerate -m "$(msg)"

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-build:
	docker compose build
