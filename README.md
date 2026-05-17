# Superset Autopilot

Event-driven system that ingests GitHub issues from a Superset fork, builds a structured case file, hands it to Devin via the Devin API, and tracks the resulting PRs through merge. Operator surface is a single Grafana page.

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

## Quickstart

```bash
cp .env.example .env          # fill in real values
make up                       # bring up the plane
make doctor                   # sanity-check
make migrate                  # run DB migrations (after PR2 lands)
make file-issues              # file seeded issues on your fork
```

Auto-dispatch (`AUTO_DISPATCH_THRESHOLD=0.0`) sends every ready triage run to Devin without a human click. Raise the threshold to surface a manual-review queue.

## Open

| URL | Why |
|---|---|
| http://localhost:3001/d/autopilot | The Grafana dashboard |
| http://localhost:8000/docs | Backend API (FastAPI Swagger) |
| http://localhost:9090 | Prometheus |

## Trust boundaries

| Plane | AWS creds? | S3 access |
|---|---|---|
| Backend container | Yes | Mints pre-signed URLs |
| Devin sessions | No | Pre-signed GETs only, TTL <= 15 min |

Devin never holds AWS credentials.
