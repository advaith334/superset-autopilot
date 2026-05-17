#!/usr/bin/env bash
# Demo bug #2 of 3 — off-by-one in /api/v1/chart pagination on the page boundary.
# A medium-difficulty Python/Flask bug that exercises a different code path
# from #1 — useful to show Devin can reason across the codebase, not just
# fix one type of issue.

set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

REPO="${GITHUB_TARGET_REPO:?set in .env}"
LABEL="${DEMO_LABEL:-autopilot-demo}"

command -v gh >/dev/null || { echo "gh CLI required" >&2; exit 1; }

gh label create "$LABEL" --repo "$REPO" --description "Filed by autopilot demo script" --color "F9D71C" >/dev/null 2>&1 || true

TITLE="Off-by-one in /api/v1/chart pagination — last item skipped on page boundary"
read -r -d '' BODY <<'EOF' || true
**Steps to reproduce**
1. Have exactly 21 charts in your workspace.
2. Request `GET /api/v1/chart/?q=(page:0,page_size:20)` — you get 20 charts back. ✓
3. Request `GET /api/v1/chart/?q=(page:1,page_size:20)` — you get **0** charts instead of the 21st.

**Expected behavior**
The last page should contain the 21st chart.

**Actual behavior**
Off-by-one in the offset calculation in `superset/views/base_api.py` (or the chart REST view that inherits from it). The boundary case (`total == page_size * N + 0`) is being treated as "no more pages."

**Why this matters**
Any client paging through more than `page_size` charts misses the final item silently.

---
_Filed by `scripts/demo-2-pagination.sh` for the Superset Autopilot demo._
EOF

echo "→ Filing demo issue 2/3 (API pagination off-by-one) on $REPO ..."
url=$(gh issue create --repo "$REPO" --title "$TITLE" --body "$BODY" --label "$LABEL" | tail -1)
echo "✓ Filed: $url"
echo "Watch the dashboard: http://localhost:3001/d/autopilot"
