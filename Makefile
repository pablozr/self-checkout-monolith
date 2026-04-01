.PHONY: up down logs test lint check

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker_smtp

test:
	pytest -q

lint:
	ruff check .

check: lint test
