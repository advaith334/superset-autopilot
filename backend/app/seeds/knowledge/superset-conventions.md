# Superset — Code Conventions

## Python

- Python 3.10+. Type hints required on new code.
- Black + isort enforced. Don't re-format other code in your diff.
- Logging: `logger = logging.getLogger(__name__)`; never print.
- Errors: raise specific exception subclasses from `superset.exceptions`, not bare `Exception`.
- Database access: always through `superset/daos/*.py`. Never call `db.session.query(...)` from views.
- Commands (write path): subclass `superset.commands.base.BaseCommand`, override `run()` and `validate()`.

## TypeScript / React

- Functional components + hooks. New class components should be very rare.
- Styling: emotion (CSS-in-JS) via the `@superset-ui/core` theme.
- State: Redux for cross-cutting; local `useState` for view-internal.
- Path imports use `src/...`, not relative `../../../`.

## Testing

- Python: pytest. Use `pytest-mock` for mocks, not unittest.mock directly.
- TS: Jest + React Testing Library. No enzyme for new tests.
- Aim for one regression test per bug fix.
- Slow tests go in `tests/integration_tests/`. Fast in `tests/unit_tests/`.

## Commits

- Conventional commits: `fix(area): description`, `feat(area): ...`, etc.
- Reference the issue in the commit footer: `Fixes #1234`.

## What to avoid

- Don't add `# type: ignore` without an explanation comment.
- Don't suppress warnings broadly (`warnings.filterwarnings("ignore")`).
- Don't introduce new dependencies for a bug fix — match the existing ones.
