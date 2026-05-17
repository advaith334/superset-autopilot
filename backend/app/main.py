"""Backend skeleton — health + Prometheus metrics only.

Later phases add the GitHub webhook, triage worker, dispatcher, and Devin
monitor. The single-container deployment, prom scrape, and compose plane all
work off this skeleton."""

import logging

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

log = logging.getLogger("autopilot")
logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="autopilot", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
