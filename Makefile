.PHONY: install dev worker test lint format migrate migration docker-up docker-down docker-build docker-logs docker-logs-worker docker-restart docker-clean migrate-docker status

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

docker-logs:
	docker compose logs -f

docker-logs-worker:
	docker compose logs -f worker

docker-restart:
	docker compose restart

docker-clean:
	docker compose down -v

migrate-docker:
	docker compose exec app alembic upgrade head

status:
	@echo "=== Containers ==="
	@docker compose ps
	@echo "\n=== Health ==="
	@curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
	@echo "\n=== Ready ==="
	@curl -s http://localhost:8000/api/v1/health/ready | python3 -m json.tool
