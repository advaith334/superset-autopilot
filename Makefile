.PHONY: help up down logs logs-app ps doctor teardown rebuild migrate \
        tf-init tf-apply tf-destroy

SHELL := /bin/bash
COMPOSE := docker compose
TF := terraform -chdir=backend/terraform
TFVARS ?= prod.tfvars

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Bring up the plane
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Stack is up:"
	@echo "  - Grafana:    http://localhost:3001 (admin/admin)"
	@echo "    └ Dashboard: http://localhost:3001/d/autopilot"
	@echo "  - API docs:    http://localhost:8000/docs"

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

doctor: ## Verify the backend + grafana are reachable
	@echo "Checking app...";     curl -fsS http://localhost:8000/health && echo " OK"
	@echo "Checking grafana..."; curl -fsS http://localhost:3001/api/health && echo " OK"

migrate: ## Run DB migrations (Alembic)
	$(COMPOSE) exec app alembic upgrade head

tf-init: ## Initialize Terraform
	$(TF) init

tf-apply: ## Apply Terraform (defaults to prod.tfvars; override with TFVARS=...)
	$(TF) apply -auto-approve -var-file=$(TFVARS)

tf-destroy: ## Tear down Terraform-managed resources
	$(TF) destroy -auto-approve -var-file=$(TFVARS)
