#!/usr/bin/env bash
# Creates (or refreshes) a `demo-seeds` branch in the Superset fork and applies
# small, targeted regressions that match the issue payloads in seeds/issues.json.
# These are intentionally trivial so the fix surface area is small for a demo.
#
# Safe to run repeatedly: branches off the current main/master, force-resets the
# demo-seeds branch each invocation.

set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

FORK="${SUPERSET_FORK_PATH:-/Users/advaith/Dev/others/superset}"
SEED_BRANCH="${SEED_BRANCH:-demo-seeds}"

if [[ ! -d "$FORK/.git" ]]; then
  echo "ERROR: $FORK is not a git checkout" >&2; exit 1
fi

echo "Seeding bugs into $FORK on branch '$SEED_BRANCH'"
echo "(originating from current HEAD: $(git -C "$FORK" rev-parse --short HEAD))"
echo

BASE=$(git -C "$FORK" symbolic-ref --short HEAD)
git -C "$FORK" diff --quiet --exit-code 2>/dev/null || {
  echo "ERROR: $FORK has uncommitted changes; stash or commit them first." >&2
  exit 1
}

# Recreate the branch from the current HEAD.
git -C "$FORK" branch -D "$SEED_BRANCH" 2>/dev/null || true
git -C "$FORK" checkout -b "$SEED_BRANCH"

applied=0; skipped=0
apply_patch() {
  local label="$1"; shift
  if "$@"; then
    echo "  ✓ $label"; applied=$((applied + 1))
  else
    echo "  ⚠ $label — target not found / already applied, skipping"; skipped=$((skipped + 1))
  fi
}

# Bug 9001 / 9007: CSV trailing-newline strip. Touch utils/csv.py in a harmless,
# reversible way to give Devin a real surface to find.
apply_patch "9001 csv trailing-newline" bash -c '
  f="'"$FORK"'/superset/utils/csv.py"
  [[ -f "$f" ]] || exit 1
  grep -q "DEMO_SEED_9001" "$f" && exit 1
  # Append a function that strips trailing newlines (the bug surface).
  cat >> "$f" <<PY

# DEMO_SEED_9001 — intentional regression for the autopilot demo.
def _strip_trailing_newlines_demo_seed(value):
    """Buggy: drops the final newline from multi-line cells. See issue #9001."""
    if isinstance(value, str) and value.endswith("\n"):
        return value[:-1]
    return value
PY
'

# Bug 9006: missing aria-label — drop a marker file the locator will find via grep.
apply_patch "9006 missing aria-label marker" bash -c '
  d="'"$FORK"'/superset-frontend/src/dashboard/components/Header"
  [[ -d "$d" ]] || exit 1
  m="$d/DEMO_SEED_9006_aria_label_TODO.md"
  [[ -f "$m" ]] && exit 1
  cat > "$m" <<MD
# TODO (demo seed #9006): missing aria-label on Refresh button

The Refresh IconButton in HeaderActionsDropdown lacks an \`aria-label\` attribute.
Screen readers announce it as just "button". Add \`aria-label="Refresh dashboard"\`.
MD
'

git -C "$FORK" add -A
git -C "$FORK" commit -m "demo: seed regressions for autopilot demo (#9001, #9006)" >/dev/null

echo
echo "Done. applied=$applied skipped=$skipped"
echo "Branch '$SEED_BRANCH' is ready. Return to '$BASE' with:"
echo "  git -C $FORK checkout $BASE"
