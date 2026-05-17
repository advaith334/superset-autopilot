#!/usr/bin/env bash
# Files real GitHub issues on the target fork so the live webhook fires.
# Each issue gets the `autopilot-demo` label so demo-cleanup-issues.sh can
# find them later.
#
# Usage:
#   bash scripts/demo-file-issues.sh                # all 7 seeded issues
#   bash scripts/demo-file-issues.sh 3              # just the first 3
#   bash scripts/demo-file-issues.sh 9001 9006      # specific seed numbers
#
# Requires:
#   - `gh` CLI authenticated with repo scope on $GITHUB_TARGET_REPO
#   - `jq`
#   - The ngrok tunnel + GitHub webhook configured (see README)

set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

REPO="${GITHUB_TARGET_REPO:?set in .env}"
SEEDS="${SEEDS_FILE:-scripts/seeds/issues.json}"
DELAY_SECONDS="${DEMO_DELAY_SECONDS:-4}"
LABEL="${DEMO_LABEL:-autopilot-demo}"

command -v gh >/dev/null || { echo "gh CLI required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }

# Ensure the label exists (idempotent; ignore "already_exists" error).
gh label create "$LABEL" --repo "$REPO" --description "Filed by autopilot demo script" --color "F9D71C" >/dev/null 2>&1 || true

# Pick which seeds to file.
TOTAL=$(jq 'length' "$SEEDS")
if [[ $# -eq 0 ]]; then
  INDICES=$(seq 0 $((TOTAL - 1)))
elif [[ "$1" =~ ^[0-9]+$ && $# -eq 1 && "$1" -le "$TOTAL" ]]; then
  INDICES=$(seq 0 $(($1 - 1)))
else
  # Treat args as seed `number` fields and find their indices.
  INDICES=""
  for n in "$@"; do
    idx=$(jq --arg n "$n" 'to_entries | map(select(.value.number == ($n | tonumber))) | .[0].key // -1' "$SEEDS")
    [[ "$idx" == "-1" ]] && { echo "warn: no seed with number=$n" >&2; continue; }
    INDICES="$INDICES $idx"
  done
fi

count=0
for i in $INDICES; do
  title=$(jq -r ".[$i].title" "$SEEDS")
  body=$(jq -r ".[$i].body" "$SEEDS")
  # Add the demo label and append a "filed by demo" footer so the audience can tell.
  body="${body}

---
_Filed by \`scripts/demo-file-issues.sh\` for the Superset Autopilot demo._"

  out=$(gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$LABEL" 2>&1)
  url=$(echo "$out" | tail -1)
  num=$(echo "$url" | grep -oE '[0-9]+$' || echo "?")
  printf "  #%s  %s\n" "$num" "$title"
  count=$((count + 1))
  # Brief gap so the audience sees the dashboard pick them up one at a time.
  if (( count < TOTAL )); then
    sleep "$DELAY_SECONDS"
  fi
done

echo
echo "Filed $count issue(s) on $REPO with label \`$LABEL\`."
echo "Watch the dashboard: http://localhost:3001/d/autopilot"
