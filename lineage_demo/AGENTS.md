# Agent Handoff Notes

This directory is intended to become the root of a standalone PyPI package named
`ibis-unified-lineage`. Treat the importable library and the monthly revenue
example as separate products:

- Core library: `src/ibis_unified_lineage`.
- Example, fixtures, service setup, and demo runner: `examples/monthly_revenue`.
- Tests: `tests`.
- Docker/OrbStack integration image: `docker`.
- Release notes and handoff docs: `docs`.

## Current State

- Python package metadata is in `pyproject.toml` and uses Hatchling.
- Dependency and virtualenv management must remain uv-only. Use `uv add`,
  `uv add --dev`, `uv sync`, `uv build`, and `uv run`.
- Supported Python range is `>=3.10,<3.15`; the test matrix covers 3.10, 3.11,
  3.12, 3.13, and 3.14.
- The wheel intentionally contains only `ibis_unified_lineage`. It must not
  package demo fixtures, engine setup code, or the monthly revenue runner.
- The monthly revenue example still exercises Spark Delta, SQLite, Postgres,
  MySQL, Polars/parquet, and DuckDB through one Docker image.

## Context From The Previous Agent

The lineage design was derived from earlier research into Spark/Databricks
lineage, Unity Catalog concepts, Ibis expression graphs, and SQLGlot lineage.
The important implementation decision is to extract logical column lineage from
the static Ibis expression graph before execution. Backend-specific table
locations are represented as metadata on `DatasetRef`; logical lineage is keyed
by stable names such as `sales.orders` and `mart.monthly_revenue`.

SQLGlot lineage is AST/scope-based rather than logical-plan-based. The package
keeps this separate in `sqlglot_bridge.py` and maps SQLGlot output into the same
`LineageGraph` model used by the Ibis extractor.

The prior uv work found two packaging issues that should stay guarded:

- Installed-wheel tests are required because editable/source tests can hide
  missing package data or stale install problems.
- On macOS, hidden `.pth` files can make editable installs unreliable. Release
  and demo commands use `uv run --no-editable` where they need to exercise an
  installed package.

## Verification Commands

Run these from this directory unless noted otherwise:

```bash
uv sync --dev
uv run pytest tests
scripts/uv_test_matrix.sh
rm -rf dist
uv build
```

Run these from the parent repository root:

```bash
docker build -f lineage_demo/docker/Dockerfile -t ibis-unified-lineage-demo:latest .
docker run --rm -v "$PWD/lineage_demo/artifacts/docker-e2e:/artifacts" ibis-unified-lineage-demo:latest
docker run --rm --entrypoint /app/scripts/uv_test_matrix.sh ibis-unified-lineage-demo:latest
```

## Release Guidance

Read `docs/release.md` before publishing. Prefer PyPI Trusted Publishing with a
GitHub Actions environment named `pypi`; do not add long-lived PyPI tokens to
repository secrets unless the owner explicitly requires it.

Before the first public upload, the owner must confirm:

- final PyPI project name availability,
- license text,
- repository URL and maintainers,
- whether the package should stay alpha or move to beta/stable classifiers.

## Boundaries To Preserve

- Do not import `examples.*` from `src/ibis_unified_lineage`.
- Do not add CSV fixtures, databases, Docker setup, or test-only helpers under
  `src/`.
- Add new example pipelines under `examples/<name>` and test fixtures under
  `tests` or that example directory.
- Keep generated files out of git. `artifacts/`, `.venv/`, `.pytest_cache/`,
  and build outputs should remain ignored.
- Keep docs and tests updated in the same change as behavior changes.
