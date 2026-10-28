# Repository instructions

- Hire-steward is the current product name; use `hire-steward` for new machine-safe metadata. Preserve established database names, migration IDs, module imports, and `JOBPILOT_*` test variables unless a separately reviewed compatibility migration requires a change.
- Treat `docs/` specifications and accepted ADRs as the source of truth. Record significant decisions in an ADR and update `docs/memory.md` after each meaningful milestone.
- Keep the backend a typed modular monolith. Use the root `pyproject.toml` and `uv.lock`; do not add infrastructure or dependencies without a concrete need and review.
- Run fast checks with `uv run --locked pytest -m "not postgres" -q`, `uv lock --check`, and `uv run --locked python -m compileall -q backend/app backend/migrations`.
- Run PostgreSQL integration tests only with `JOBPILOT_TEST_DATABASE_URL` pointing to the dedicated `jobpilot_test` database. Tests create and remove isolated per-test schemas; never point them at a normal development or user database.
- Keep compensation policy deterministic. Publicly supplied or model-generated compensation is unverified; never let a model, client field, score, or evidence reference set trusted state or authorize submission. Unpaid work remains independently ineligible.
- Keep credentials out of tracked files, prompts, test fixtures, and ordinary logs. Do not access external job sites or submit applications during routine development or CI.
- Preserve existing user changes. Do not commit or push unless the user explicitly asks. Keep the eight external reference repositories excluded and unchanged.
