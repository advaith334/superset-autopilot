#!/usr/bin/env bash
# Closes (does not delete — GH only lets you delete via the API on org repos)
# every issue on the target fork that has the `autopilot-demo` label.
#
# Run between demo takes so the next run starts clean.

set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

REPO="${GITHUB_TARGET_REPO:?set in .env}"
LABEL="${DEMO_LABEL:-autopilot-demo}"

command -v gh >/dev/null || { echo "gh CLI required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }

# Portable replacement for `mapfile` (macOS ships bash 3.2).
NUMS=()
while IFS= read -r line; do NUMS+=("$line"); done < <(
  gh issue list --repo "$REPO" --label "$LABEL" --state open --limit 100 \
    --json number --jq '.[].number' || true
)

if [[ ${#NUMS[@]} -eq 0 ]]; then
  echo "No open issues with label \`$LABEL\` on $REPO."
  exit 0
fi

echo "Closing ${#NUMS[@]} demo issue(s)..."
for n in "${NUMS[@]}"; do
  gh issue close "$n" --repo "$REPO" --reason "not planned" \
    --comment "Closed by \`scripts/demo-cleanup-issues.sh\`." >/dev/null
  printf "  closed #%s\n" "$n"
done
