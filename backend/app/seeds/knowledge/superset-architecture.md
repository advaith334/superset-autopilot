# Apache Superset — Architecture Cheatsheet

Quick orientation for any agent working in this codebase.

## Top-level layout

- `superset/` — Python Flask backend. Models, views (REST + GraphQL via Flask-AppBuilder), commands, daos.
- `superset-frontend/` — TypeScript + React. Plugins for chart types, sliceable UI components.
- `tests/` — pytest. Unit and integration. Many tests need a live Postgres/Redis (use docker-compose-light.yml).
- `docs/` — Docusaurus user docs.

## Key Python entry points

- `superset/views/base_api.py` — base REST API class. All `/api/v1/*` endpoints inherit from this.
- `superset/commands/` — write-path operations as Command objects (CQRS-ish).
- `superset/daos/` — read-path. Always go through DAOs, never raw SQLAlchemy.
- `superset/sql_lab.py` — async query execution. Touches Celery.
- `superset/charts/data/query_context.py` — chart query context (timezone, time grain, filters).
- `superset/utils/csv.py` — CSV export helpers. RFC 4180 quoting nuances live here.

## Conventions

- Use `flask db migrate -m "..."` for schema changes; never edit migrations after they're released.
- All API responses go through Marshmallow schemas in `superset/.../schemas.py`.
- Feature flags live in `superset/config.py` under `DEFAULT_FEATURE_FLAGS`.
- Pre-commit must pass: black, isort, mypy, pylint, eslint, prettier.

## Running tests

- Unit: `pytest tests/unit_tests/...` — fast.
- Integration: `tests/integration_tests/...` — needs Postgres + Redis + Celery.
- Frontend: `cd superset-frontend && npm test`.

## Common pitfalls

- Timezone handling: timestamps inside the engine are UTC; presentation layer converts via the user's preference.
- The `@expose` decorator on view methods means the route is auto-registered — be careful with renames.
- Many charts rely on jinja templating in SQL; preserve template variables when refactoring.
