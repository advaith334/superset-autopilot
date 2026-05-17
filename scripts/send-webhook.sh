#!/usr/bin/env bash
# Fires a fake GitHub `issues.opened` webhook at the ingest service.
#
# Usage:
#   bash scripts/send-webhook.sh                    # default seeded issue
#   ISSUE_NUMBER=99 ISSUE_TITLE="..." bash ...      # override
#
# Reads GITHUB_WEBHOOK_SECRET from .env (or env) to sign the request, so the
# ingest service's HMAC check passes.

set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

: "${GITHUB_WEBHOOK_SECRET:?set in .env}"

INGEST_URL="${INGEST_URL:-http://localhost:8000}"
ISSUE_NUMBER="${ISSUE_NUMBER:-1001}"
ISSUE_TITLE="${ISSUE_TITLE:-CSV export drops trailing newlines on multi-line cells}"
ISSUE_BODY="${ISSUE_BODY:-When exporting a chart to CSV, rows whose cells contain trailing newlines lose the final newline. Repro: create a query whose column contains a string ending in \\\\n, export to CSV, observe the value is truncated.}"
ISSUE_REPO="${ISSUE_REPO:-${GITHUB_TARGET_REPO:-advaith334/superset}}"
ISSUE_USER="${ISSUE_USER:-demo-reporter}"

PAYLOAD=$(cat <<JSON
{
  "action": "opened",
  "issue": {
    "number": ${ISSUE_NUMBER},
    "title": "${ISSUE_TITLE}",
    "body": "${ISSUE_BODY}",
    "html_url": "https://github.com/${ISSUE_REPO}/issues/${ISSUE_NUMBER}",
    "user": { "login": "${ISSUE_USER}" },
    "labels": [{ "name": "bug" }]
  },
  "repository": { "full_name": "${ISSUE_REPO}" }
}
JSON
)

SIG="sha256=$(printf '%s' "$PAYLOAD" | openssl dgst -sha256 -hmac "$GITHUB_WEBHOOK_SECRET" | awk '{print $2}')"

echo "POST ${INGEST_URL}/webhook/github (issue #${ISSUE_NUMBER})"
curl -fsS -X POST "${INGEST_URL}/webhook/github" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issues" \
  -H "X-Hub-Signature-256: ${SIG}" \
  --data-binary "${PAYLOAD}" \
  | python3 -m json.tool
echo ""
