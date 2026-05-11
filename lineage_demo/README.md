# Ibis Unified Lineage Demo

This package is a working reference implementation for extracting
engine-agnostic column lineage from Ibis jobs. The important design choice is
that lineage is derived from the Ibis expression graph before execution, so the
same logical job produces the same dependency graph when a source table moves
from Spark Delta to SQLite, Postgres, MySQL, DuckDB, or parquet-backed Polars.

## Architecture

The library has five layers:

1. `JobConfig` and `TableConfig` describe logical tables, schemas, fixture CSVs,
   physical engines, target datasets, and backend-swap variants.
2. `engine_io` loads fixture data directly from CSV for fast tests or
   round-trips each table through its configured engine for service-backed
   integration runs.
3. Job builders, such as `build_monthly_revenue_job`, create Ibis expressions
   from a mapping of table names to Ibis tables. They do not know which engine
   owns each source table.
4. `IbisLineageExtractor` walks the Ibis operation tree and emits the shared
   `LineageGraph` model with value, filter, join, group, order, and opaque
   dependency roles.
5. `write_lineage_ui` writes a standalone HTML viewer that lays out source,
   intermediate, and final datasets from the graph itself.

`sqlglot_bridge.extract_sqlglot_lineage` is included for SQL strings and uses
SQLGlot's AST/scope lineage API, then maps the result into the same graph model.

## Configuration

The canonical demo config lives at
`fixtures/monthly_revenue/job_config.json`. Each input table declares:

- `name`: the table key used by the Ibis job.
- `logical_name`: the stable governance name used in backend-invariant lineage.
- `engine`: physical engine or storage system.
- `kind`: physical object kind, such as `table`, `delta`, or `parquet`.
- `csv`: fixture CSV path relative to the config file.
- `schema`: ordered Ibis type strings.

The packaged monthly revenue fixtures are intentionally bundled as demo and
installed-wheel test resources. Production jobs should provide their own config
path or resource root so lineage extraction is driven by the caller's datasets,
not by the example assets in the wheel.

Example override from the CLI:

```bash
uv run --no-editable python -m ibis_unified_lineage.demo_run \
  --artifacts artifacts/local-sqlite-orders \
  --table-engine orders=sqlite \
  --table-engine returns=duckdb \
  --target-engine postgres
```

The lineage dependencies remain keyed by logical names like `sales.orders` and
`mart.monthly_revenue`; engine changes update metadata, not the logical graph.

## Local Tests

This project uses `uv` exclusively for Python dependency management, virtual
environment management, package builds, and test execution. Add runtime or dev
dependencies with canonical commands such as `uv add PACKAGE` or
`uv add --dev PACKAGE`.

```bash
uv sync --dev
uv run pytest tests
```

Build the source distribution and wheel with the Hatchling backend:

```bash
uv build
```

Run the installed-wheel compatibility matrix across Python 3.10 through the
latest stable 3.14.x interpreter that uv resolves:

```bash
scripts/uv_test_matrix.sh
```

The test suite covers:

- CSV-backed fixture loading and engine override metadata.
- DuckDB execution of the monthly revenue job.
- Ibis extractor value/filter/join/group lineage.
- SQLGlot SQL lineage mapping into the common graph model.
- Backend-invariant lineage when `orders` moves from Spark Delta to SQLite.
- Materialized multi-stage lineage for `A+B -> C`, `D+E+F -> G`, and `C+G -> H`.
- Standalone HTML lineage UI generation.

## Local Demo

Run the demo without external services:

```bash
uv run --no-editable python -m ibis_unified_lineage.demo_run \
  --artifacts artifacts/local-smoke
```

The demo writes:

- `monthly_revenue.csv`
- `lineage.json`
- `lineage_base.json`
- `lineage_orders_sqlite.json`
- `lineage.html`
- `summary.json`

Open `lineage.html` to inspect the generated column-level graph.

## Single-Image Service Demo

Build the image from the repository root:

```bash
docker build -f lineage_demo/docker/Dockerfile -t ibis-unified-lineage-demo:latest .
```

Run the full service-backed example from the repository root:

```bash
docker run --rm \
  -v "$PWD/lineage_demo/artifacts/docker-e2e:/artifacts" \
  ibis-unified-lineage-demo:latest
```

The image starts Postgres and MariaDB, writes Spark Delta or parquet-fallback
orders, SQLite customers, Postgres FX rates, MySQL promotions, and Polars parquet
returns, then executes the unified Ibis job through DuckDB.

Run the same uv-managed installed-wheel Python matrix inside the image:

```bash
docker run --rm \
  --entrypoint /app/scripts/uv_test_matrix.sh \
  ibis-unified-lineage-demo:latest
```

## Adding A Job

1. Add CSV fixtures and a JSON job config with schemas for every table.
2. Write a job builder that accepts `Mapping[str, ibis.Table]` and returns an
   Ibis table expression.
3. Load configured tables with `JobConfig.unbound_tables()` for static lineage.
4. Call `extract_lineage(expr, registry=config.registry(), target=config.target)`.
5. Use `merge_lineage_graphs` when a pipeline materializes multiple stages.
6. Use `collect_configured_frames` and `execute_ibis_job_with_duckdb` for
   repeatable fixture execution tests.

## Current Limits

The current implementation is production-oriented but still a reference library.
Known follow-up milestones are tracked in
`../docs/production-hardening-plan.md`: strict context-lineage policies,
OpenLineage/DataHub emitters, deeper SQLGlot source expansion, property-based
expression tests, type/lint/doc CI, and a hardened non-root container image.
