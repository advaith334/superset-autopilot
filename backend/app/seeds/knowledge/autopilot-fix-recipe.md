# Autopilot — Definition of a "good fix"

When the Superset Autopilot dispatches you to fix an issue, follow this recipe.

## 1. Read the case file first

The case file URL is in the prompt. Fetch it before doing anything else. It contains:
- The full GitHub issue (title, body, comments, labels, reporter)
- `reporter_narrative` — what the reporter claims happens
- `code_pointers` — files from a ripgrep over the codebase that probably touch the bug
- `classification` — our heuristic guess at bug type + severity + confidence
- `acceptance_criteria`
- `budget` — ACU cap and wall-clock cap. Stay within it.

## 2. You own reproduction

The autopilot does not pre-reproduce. Your session is the only place reproduction happens.

- Stand up whatever environment you need (ephemeral Superset, unit-test harness, or just run the tests).
- Write a failing test that captures the bug **before** changing any production code. The test is the proof of reproduction.
- If you can't reproduce, post an investigative summary on the issue and stop. Do not push speculative fixes.

## 3. Minimal diff

- Touch only files in `code_pointers.symbol_matches` or `code_pointers.stack_trace_files` unless you have strong evidence to expand.
- No drive-by refactors. No formatting changes outside the diff.
- No adding feature flags for a bug fix.

## 4. PR body template

```
## Summary
<1-2 sentences>

## Issue
Fixes #<github_number>

## Reproduction
<how you reproduced it; include the failing-test path>

## Approach
<why this fix vs alternatives>

## Test plan
- [ ] Added regression test at <path>
- [ ] `pytest <test path>` passes locally
- [ ] CI green
```

## 5. CI failures

If the autopilot sends a follow-up message about a CI failure, do not give up — read the log snippet in the message, find the failing assertion, and push another commit. The session stays open.

## 6. Stop conditions

- **One PR per session.** Open exactly one pull request. Do not open additional PRs on different branches "as alternatives" — pick the best approach and commit to it.
- **Wrap up as soon as the PR is up and CI is queued.** Post a one-line summary in the session and stop. The session stays alive in case CI fails — the autopilot will message you here if so.
- Budget exhausted → stop, summarize what's done, leave the PR in draft.
- Same test fails 3+ times with different attempted fixes → stop and post a "needs human" comment on the issue.
