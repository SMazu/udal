# Ibis Unified Lineage

`ibis-unified-lineage` extracts engine-agnostic column lineage from Ibis
expression graphs before a query is executed. The same logical job should emit
the same dependency graph whether an input table lives in Spark Delta, SQLite,
Postgres, MySQL, DuckDB, Polars, parquet, or another Ibis backend.

The importable package is intentionally small:

- `ibis_unified_lineage.models`: dataset, column, edge, and graph models.
- `ibis_unified_lineage.extractor`: Ibis expression graph lineage extraction.
- `ibis_unified_lineage.sqlglot_bridge`: SQLGlot SQL lineage mapped into the
  shared graph model.
- `ibis_unified_lineage.ui`: standalone HTML lineage viewer generation.

Everything demo-specific lives outside `src/` under `examples/monthly_revenue`.
That example contains the config parser, CSV fixtures, engine seeding code,
DuckDB execution smoke test, and service-backed runner.

## Quick Start

```python
import ibis

from ibis_unified_lineage import DatasetRef, extract_lineage

orders = ibis.table(
    {"customer_id": "int64", "amount": "float64", "status": "string"},
    name="orders",
)
expr = orders.filter(orders.status == "paid").group_by(orders.customer_id).agg(
    total_amount=orders.amount.sum(),
)

graph = extract_lineage(
    expr,
    registry={
        "orders": DatasetRef(
            name="orders",
            engine="duckdb",
            schema=orders.schema().items(),
            logical_name="sales.orders",
        )
    },
    target=DatasetRef(name="customer_revenue", engine="duckdb", logical_name="mart.customer_revenue"),
)

print(graph.to_dict())
```

## Monthly Revenue Example

The canonical cross-engine example lives in `examples/monthly_revenue`.
Its config is `examples/monthly_revenue/fixtures/monthly_revenue/job_config.json`.
The example proves that lineage stays keyed by logical dataset names such as
`sales.orders` and `mart.monthly_revenue` even when physical engines change.

Run the local example without external services:

```bash
uv run --no-editable python -m examples.monthly_revenue.demo_run \
  --artifacts artifacts/local-smoke
```

Override table engines from the CLI:

```bash
uv run --no-editable python -m examples.monthly_revenue.demo_run \
  --artifacts artifacts/local-sqlite-orders \
  --table-engine orders=sqlite \
  --table-engine returns=duckdb \
  --target-engine postgres
```

The run writes `monthly_revenue.csv`, lineage JSON files, `lineage.html`, and
`summary.json` into the artifact directory.

## Development

This project uses `uv` exclusively for dependency management, virtualenv
management, builds, and tests. Add dependencies with canonical commands such as
`uv add PACKAGE` or `uv add --dev PACKAGE`.

```bash
uv sync --dev
uv run pytest tests
```

Build the source distribution and wheel with Hatchling:

```bash
rm -rf dist
uv build
```

Run installed-wheel compatibility tests across Python 3.10 through 3.14:

```bash
scripts/uv_test_matrix.sh
```

The wheel matrix intentionally installs the built wheel in isolated uv
environments and asserts that demo modules are not importable from
`ibis_unified_lineage`.

## Docker Service Example

Build the single-image service demo from the repository root:

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
orders, SQLite customers, Postgres FX rates, MySQL promotions, and
Polars/parquet returns, then executes the unified Ibis job through DuckDB.

Run the same installed-wheel Python matrix inside the image:

```bash
docker run --rm \
  --entrypoint /app/scripts/uv_test_matrix.sh \
  ibis-unified-lineage-demo:latest
```

## Release Handoff

Read `AGENTS.md` first. Then follow `docs/release.md` for the PyPI release
checklist and `docs/gap-analysis.md` for remaining owner decisions.
