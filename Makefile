COMPOSE ?= docker compose
PYTHON ?= .\venv\Scripts\python.exe

.PHONY: up down build logs ps restart init-env migrate-db verify-db

init-env:
	@if exist .env (echo .env already exists, leaving it unchanged.) else (copy .env.example .env >NUL && echo Created .env from .env.example.)

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

restart:
	$(COMPOSE) down
	$(COMPOSE) up --build -d

migrate-db:
	$(PYTHON) -m app.scripts.migrate_sqlite_to_postgres

verify-db:
	$(PYTHON) -m app.scripts.verify_postgres_data
