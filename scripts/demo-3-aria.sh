#!/usr/bin/env bash
# Demo bug #3 of 3 — missing aria-label on the dashboard toolbar Refresh button.
# Trivial frontend a11y fix. Useful in the demo as a "fast win" that Devin
# can complete quickly to show throughput on top of the deeper bugs in
# scripts #1 and #2.

set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

REPO="${GITHUB_TARGET_REPO:?set in .env}"
LABEL="${DEMO_LABEL:-autopilot-demo}"

command -v gh >/dev/null || { echo "gh CLI required" >&2; exit 1; }

gh label create "$LABEL" --repo "$REPO" --description "Filed by autopilot demo script" --color "F9D71C" >/dev/null 2>&1 || true

TITLE="Missing aria-label on dashboard toolbar Refresh button"
read -r -d '' BODY <<'EOF' || true
**Issue**
Screen readers announce the dashboard toolbar Refresh button as just "button" because the `aria-label` attribute is missing on the IconButton.

**File**
`superset-frontend/src/dashboard/components/Header/HeaderActionsDropdown.tsx` (or wherever the Refresh button lives in the header).

**Fix**
Add `aria-label="Refresh dashboard"` to the IconButton. Should be a one-liner.

**Why this matters**
Accessibility / WCAG compliance — screen-reader users currently can't tell the Refresh button apart from any other unlabeled icon button on the page.

---
_Filed by `scripts/demo-3-aria.sh` for the Superset Autopilot demo._
EOF

echo "→ Filing demo issue 3/3 (a11y missing aria-label) on $REPO ..."
url=$(gh issue create --repo "$REPO" --title "$TITLE" --body "$BODY" --label "$LABEL" | tail -1)
echo "✓ Filed: $url"
echo "Watch the dashboard: http://localhost:3001/d/autopilot"
