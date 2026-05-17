#!/usr/bin/env bash
# Demo bug #1 of 3 — CSV export drops trailing newline on multi-line cells.
# Files a real GitHub issue on the fork, which triggers the live autopilot
# pipeline end-to-end. Watch http://localhost:3001/d/autopilot.

set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

REPO="${GITHUB_TARGET_REPO:?set in .env}"
LABEL="${DEMO_LABEL:-autopilot-demo}"

command -v gh >/dev/null || { echo "gh CLI required" >&2; exit 1; }

# Ensure label exists (idempotent).
gh label create "$LABEL" --repo "$REPO" --description "Filed by autopilot demo script" --color "F9D71C" >/dev/null 2>&1 || true

TITLE="CSV export drops trailing newline on multi-line string cells"
read -r -d '' BODY <<'EOF' || true
**Steps to reproduce**
1. Create a chart whose query returns a column with values ending in a newline (e.g. concatenated multi-line text).
2. Export the chart to CSV.
3. Open the CSV and inspect the affected column.

**Expected behavior**
The trailing newline should be preserved (RFC 4180-style quoting).

**Actual behavior**
The final newline is silently stripped on rows that have only the newline in the cell. Repro hits `superset/utils/csv.py` in `df_to_escaped_csv`.

**Environment**
Superset 4.x

---
_Filed by `scripts/demo-1-csv.sh` for the Superset Autopilot demo._
EOF

echo "→ Filing demo issue 1/3 (CSV trailing-newline bug) on $REPO ..."
url=$(gh issue create --repo "$REPO" --title "$TITLE" --body "$BODY" --label "$LABEL" | tail -1)
echo "✓ Filed: $url"
echo "Watch the dashboard: http://localhost:3001/d/autopilot"
