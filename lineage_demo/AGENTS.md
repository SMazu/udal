# Agent Handoff Notes

This directory is intended to become the root of a standalone PyPI package named
`ibis-unified-lineage`. Treat the importable library and the monthly revenue
example as separate products:

- Core library: `src/ibis_unified_lineage`.
- Example, fixtures, service setup, and demo runner: `examples/monthly_revenue`.
- Tests: `tests`.
- Docker/OrbStack integration image: `docker`.
- Release notes and handoff docs: `docs`.

Start with `docs/design.md`, then `docs/architecture.md`, then this file.
Those three documents preserve the current technical context from this agent
thread.

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
- Multi-stage lineage is now a first-class library feature. Use
  `PipelineStage`, `extract_pipeline_lineage`, and
  `transitive_dependency_pairs` for cascading materialized jobs.
- Scanning mode is implemented in `scan_ibis_project`. It discovers documented
  stage declarations and returns the same `PipelineStage` objects used by
  explicit registration. It must remain conservative and diagnostic-rich rather
  than guessing lineage from arbitrary Python.
- The HTML UI is an arbitrary-depth dataset DAG viewer. Do not reintroduce the
  old fixed source/intermediate/final three-column layout.
- `examples/multistage_pipeline` is the handoff example for static deep DAG
  lineage and UI generation.

## Context From The Previous Agent

The lineage design was derived from earlier research into Spark/Databricks
lineage, Unity Catalog concepts, Ibis expression graphs, and SQLGlot lineage.
The important implementation decision is to extract logical column lineage from
the static Ibis expression graph before execution. Backend-specific table
locations are represented as metadata on `DatasetRef`; logical lineage is keyed
by stable names such as `sales.orders` and `mart.monthly_revenue`.

The canonical graph remains direct/materialized lineage. Each edge represents a
dependency across a stage boundary or within a stage output. Raw-to-final
lineage is derived by traversing the direct graph and should not replace the
canonical stored graph. The library must not execute queries to extract lineage.
Stage builders are invoked only to construct lazy Ibis expressions from declared
schemas.

SQLGlot lineage is AST/scope-based rather than logical-plan-based. The package
keeps this separate in `sqlglot_bridge.py` and maps SQLGlot output into the same
`LineageGraph` model used by the Ibis extractor.

Scanner conventions currently supported:

- module-level `PipelineStage` objects,
- collections named `LINEAGE_STAGES`, `PIPELINE_STAGES`, or `STAGES`,
- module metadata variables `LINEAGE_STAGE_ID`, `LINEAGE_INPUTS`,
  `LINEAGE_TARGET`, and a builder named `LINEAGE_BUILDER`, `build_lineage`,
  `build_job`, or `build`,
- `LINEAGE_JOBS` collections of dictionaries with `stage_id`, `inputs`,
  `target`, `builder`, and optional `metadata`.

If a file cannot be imported or understood safely, preserve the current behavior
of reporting a structured diagnostic. Do not silently skip suspicious lineage
markers and do not invent target/input metadata.

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
uv run --no-editable python -m examples.multistage_pipeline.demo_run \
  --artifacts artifacts/multistage-lineage
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
