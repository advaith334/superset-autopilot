.PHONY: help up down logs logs-app ps doctor teardown rebuild migrate

SHELL := /bin/bash
COMPOSE := docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Bring up the plane
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Stack is up:"
	@echo "  - API docs:    http://localhost:8000/docs"
	@echo "  - Prometheus:  http://localhost:9090"

down: ## Stop the plane (preserve volumes)
	$(COMPOSE) down

teardown: ## Stop and delete all volumes
	$(COMPOSE) down -v

rebuild: ## Rebuild all images
	$(COMPOSE) build --no-cache

logs: ## Tail logs for all services
	$(COMPOSE) logs -f --tail=100

logs-app: ## Tail backend app logs
	$(COMPOSE) logs -f --tail=200 app

ps: ## Show container status
	$(COMPOSE) ps

doctor: ## Verify the backend is reachable
	@echo "Checking app...";  curl -fsS http://localhost:8000/health && echo " OK"

migrate: ## Run DB migrations (Alembic)
	$(COMPOSE) exec app alembic upgrade head
