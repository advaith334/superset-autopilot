.PHONY: help up down logs logs-app ps doctor teardown rebuild migrate \
        tf-init tf-apply tf-destroy seed-bugs \
        webhook-demo triage-trigger dispatch sessions \
        file-issues demo-1 demo-2 demo-3 cleanup-issues reset-state \
        ssh-ec2 doctor-ec2 logs-ec2 sessions-ec2 issues-ec2 \
        triage-trigger-ec2 dispatch-ec2 reset-state-ec2

SHELL := /bin/bash
COMPOSE := docker compose
TF := terraform -chdir=backend/terraform
TFVARS ?= prod.tfvars

# ── EC2 demo target (override via env if the box moves) ──
EC2_HOST     ?= 44.208.208.66
EC2_USER     ?= ec2-user
EC2_SSH_KEY  ?= ~/.ssh/autopilot
EC2_API      ?= http://$(EC2_HOST):8000
EC2_SSH      := ssh -i $(EC2_SSH_KEY) $(EC2_USER)@$(EC2_HOST)

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

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

webhook-demo: ## Fire a fake HMAC-signed webhook directly at the app (HMAC-path debug)
	bash scripts/send-webhook.sh

triage-trigger: ## Manually re-trigger triage for issue ID=N
	@test -n "$(ID)" || (echo "usage: make triage-trigger ID=<issue_id>" && exit 1)
	curl -fsS -X POST http://localhost:8000/triage/$(ID) | python3 -m json.tool

dispatch: ## Manually dispatch a Devin session
	@test -n "$(TRIAGE_RUN_ID)" || (echo "usage: make dispatch TRIAGE_RUN_ID=<id>" && exit 1)
	curl -fsS -X POST http://localhost:8000/dispatch/$(TRIAGE_RUN_ID) | python3 -m json.tool

sessions: ## List all Devin sessions
	curl -fsS http://localhost:8000/sessions | python3 -m json.tool

seed-bugs: ## Apply seeded regressions to the Superset fork on a 'demo-seeds' branch
	bash scripts/seed-bugs.sh

file-issues: ## File ALL seeded GitHub issues on the fork at once
	bash scripts/demo-file-issues.sh $(N)

demo-1: ## File demo bug #1: CSV trailing-newline (Python/utils)
	bash scripts/demo-1-csv.sh

demo-2: ## File demo bug #2: API pagination off-by-one (Python/views)
	bash scripts/demo-2-pagination.sh

demo-3: ## File demo bug #3: missing aria-label (frontend a11y)
	bash scripts/demo-3-aria.sh

cleanup-issues: ## Close all open issues with the autopilot-demo label on the fork
	bash scripts/demo-cleanup-issues.sh

reset-state: ## DESTRUCTIVE — wipe all autopilot tables (LOCAL postgres)
	@echo "About to TRUNCATE all LOCAL autopilot tables. Ctrl+C to abort."; sleep 3
	docker exec autopilot-postgres psql -U autopilot -d autopilot \
	  -c "TRUNCATE issues, triage_runs, devin_sessions, pull_requests, events RESTART IDENTITY CASCADE"

# ──────────────────────────────────────────────────────────────
# EC2 targets — same operations as above, pointed at the demo box.
# Override host/key with: make doctor-ec2 EC2_HOST=1.2.3.4 EC2_SSH_KEY=~/.ssh/foo
# ──────────────────────────────────────────────────────────────

ssh-ec2: ## SSH into the EC2 demo box
	$(EC2_SSH)

doctor-ec2: ## Health-check the EC2 backend + grafana
	@echo "Checking EC2 app...";     curl -fsS $(EC2_API)/health && echo " OK"
	@echo "Checking EC2 grafana..."; curl -fsS http://$(EC2_HOST):3001/api/health && echo " OK"

logs-ec2: ## Tail backend app logs on EC2
	$(EC2_SSH) 'cd superset-devin-autopilot && docker compose logs -f --tail=200 app'

sessions-ec2: ## List Devin sessions on EC2
	curl -fsS $(EC2_API)/sessions | python3 -m json.tool

issues-ec2: ## List recent ingested issues on EC2
	curl -fsS "$(EC2_API)/issues?limit=20" | python3 -m json.tool

triage-trigger-ec2: ## Manually re-trigger triage on EC2 for issue ID=N
	@test -n "$(ID)" || (echo "usage: make triage-trigger-ec2 ID=<issue_id>" && exit 1)
	curl -fsS -X POST $(EC2_API)/triage/$(ID) | python3 -m json.tool

dispatch-ec2: ## Manually dispatch a Devin session on EC2
	@test -n "$(TRIAGE_RUN_ID)" || (echo "usage: make dispatch-ec2 TRIAGE_RUN_ID=<id>" && exit 1)
	curl -fsS -X POST $(EC2_API)/dispatch/$(TRIAGE_RUN_ID) | python3 -m json.tool

reset-state-ec2: ## DESTRUCTIVE — wipe all autopilot tables on EC2 (clears dedup history)
	@echo "About to TRUNCATE all autopilot tables on $(EC2_HOST). Ctrl+C to abort."; sleep 3
	$(EC2_SSH) 'docker exec autopilot-postgres psql -U autopilot -d autopilot \
	  -c "TRUNCATE issues, triage_runs, devin_sessions, pull_requests, events RESTART IDENTITY CASCADE"'
