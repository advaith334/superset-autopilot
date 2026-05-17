# Superset Autopilot

Event-driven system that ingests GitHub issues from a Superset fork, builds a structured case file, hands it to Devin via the Devin API, and tracks the resulting PRs through merge. Operator surface is a single Grafana page.

## Live demo

The backend is hosted on EC2 — no local setup needed to see it run.

| URL | What it is |
|---|---|
| http://44.208.208.66:3001/d/autopilot | Grafana dashboard (login: `admin` / `admin`) |
| http://44.208.208.66:8000/webhook/github | GitHub webhook target |

Trigger a demo issue → Superset PR flow with one command:

```bash
# Single demo scenario
curl -X POST http://44.208.208.66:8000/dispatch/1

# All three
for i in 1 2 3; do curl -X POST http://44.208.208.66:8000/dispatch/$i; done
```

Then watch the dashboard update.

## Layout

```
superset-autopilot/
├── backend/           # FastAPI app + stateful infra
│   ├── app/                                  (backend code)
│   ├── alembic/                              (DB migrations)
│   ├── postgres, prometheus                  (data plane configs)
│   └── terraform/                            (S3 + IAM, optional EC2)
├── frontend/          # Grafana provisioning + the Autopilot dashboard
└── scripts/           # demo + seed + cleanup runners
```

## Prerequisites

- Docker Desktop (Compose v2)
- Terraform >= 1.6 (only if using AWS bits)
- AWS IAM user that can create S3 buckets
- Devin API key + org ID
- A GitHub fork to operate on, with a PAT and webhook → `https://<your-tunnel>/webhook/github`

## Quickstart (local dev)

```bash
cp .env.example .env          # fill in real values
make up                       # bring up the plane
make doctor                   # sanity-check
make migrate                  # run DB migrations (after PR2 lands)
make file-issues              # file seeded issues on your fork
```

Auto-dispatch (`AUTO_DISPATCH_THRESHOLD=0.0`) sends every ready triage run to Devin without a human click. Raise the threshold to surface a manual-review queue.

Local URLs once `make up` is done:

| URL | Why |
|---|---|
| http://localhost:3001/d/autopilot | The Grafana dashboard |
| http://localhost:8000/docs | Backend API (FastAPI Swagger) |
| http://localhost:9090 | Prometheus |

## Demo scenarios

Three seeded bugs you can fire end-to-end. Each one files a real GitHub issue on your fork (via `gh`), which fires the webhook, runs triage, auto-dispatches to Devin, and ends with a PR.

```bash
make demo-1          # CSV trailing-newline bug (Python/utils)
make demo-2          # API pagination off-by-one (Python/views)
make demo-3          # missing aria-label (frontend a11y)

# or all three at once
make file-issues
```

Watch the Grafana dashboard while it runs. Webhook → triage is seconds; Devin → PR is typically 5–30 min depending on the bug.

Need `gh` authenticated against your fork and the env vars in `.env` populated (`GITHUB_TARGET_REPO`, `GITHUB_WEBHOOK_SECRET`, `DEVIN_API_KEY`, etc.).

## Cleanup

```bash
make cleanup-issues  # close all open issues with the autopilot-demo label
make reset-state     # truncate autopilot DB tables (destructive)
make down            # stop containers (preserve volumes)
make teardown        # stop containers AND delete volumes
```

If you provisioned the EC2 host, tear that down too:
```bash
make tf-destroy TFVARS=ec2.tfvars
```
S3 buckets persist (they're in `main.tf`, not gated on EC2). Drop them manually with `aws s3 rb s3://autopilot-prod-artifacts --force` if you want a zero-trace teardown.

## Hosted deployment

The same docker-compose stack runs on EC2 via `backend/terraform`. See [`backend/terraform/EC2-DEPLOY.md`](backend/terraform/EC2-DEPLOY.md) for the walkthrough. Current live host: `44.208.208.66`.

## Trust boundaries

| Plane | AWS creds? | S3 access |
|---|---|---|
| Backend container | Yes | Mints pre-signed URLs |
| Devin sessions | No | Pre-signed GETs only, TTL <= 15 min |

Devin never holds AWS credentials.
