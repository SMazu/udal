# Ibis Unified Lineage

`ibis-unified-lineage` extracts engine-agnostic column lineage from lazy Ibis
expression graphs before a query is executed. The same logical job should emit
the same dependency graph whether an input table lives in Spark Delta, SQLite,
Postgres, MySQL, DuckDB, Polars, parquet, or another Ibis backend.

The importable package is intentionally small:

- `ibis_unified_lineage.models`: dataset, column, edge, and graph models.
- `ibis_unified_lineage.extractor`: Ibis expression graph lineage extraction.
- `ibis_unified_lineage.pipeline`: materialized stage registration, pipeline
  extraction, and derived transitive lineage.
- `ibis_unified_lineage.scanner`: project/folder scanning that discovers
  supported stage declarations and returns structured diagnostics.
- `ibis_unified_lineage.sqlglot_bridge`: SQLGlot SQL lineage mapped into the
  shared graph model.
- `ibis_unified_lineage.ui`: standalone arbitrary-depth DAG HTML viewer
  generation.

Everything demo-specific lives outside `src/` under `examples/monthly_revenue`.
That example contains the config parser, CSV fixtures, engine seeding code,
DuckDB execution smoke test, and service-backed runner.

Read `docs/design.md` for the production design and handoff context.

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

## Multi-Stage Pipeline Lineage

The canonical graph is direct/materialized lineage: each edge describes how one
stage writes one materialized target from its declared inputs. Raw-to-final
lineage is derived from those direct edges.

```python
from ibis_unified_lineage import DatasetRef, PipelineStage, extract_pipeline_lineage

raw_orders = DatasetRef(
    name="orders",
    engine="spark-delta",
    schema={"customer_id": "int64", "amount": "float64"},
    logical_name="sales.orders",
)
customer_revenue = DatasetRef(
    name="customer_revenue",
    engine="duckdb",
    logical_name="mart.customer_revenue",
)

def build_customer_revenue(tables):
    orders = tables["orders"]
    return orders.group_by(orders.customer_id).agg(total_amount=orders.amount.sum())

graph = extract_pipeline_lineage(
    [
        PipelineStage(
            stage_id="customer_revenue",
            inputs={"orders": raw_orders},
            target=customer_revenue,
            builder=build_customer_revenue,
        )
    ]
)
```

`PipelineStage.builder` is invoked only to construct lazy Ibis expressions. The
library does not execute the query or connect to the backend while extracting
lineage. Input datasets must provide schemas unless they are produced by an
earlier discovered stage.

Use `transitive_dependency_pairs(graph)` when a caller needs raw source columns
for a selected final output column.

### Pipeline API vs. Scanner Mode

Use the pipeline API when the caller already has structured job metadata, such
as an orchestration manifest, a test fixture, or a framework integration that
can construct `PipelineStage` objects directly. This is the canonical extraction
path: `extract_pipeline_lineage` receives stages, builds lazy Ibis expressions,
and emits the direct/materialized `LineageGraph`.

Use scanner mode when the caller has Python job repositories rather than an
already-built stage list. `scan_ibis_project` discovers supported declarations,
reports diagnostics for files it cannot understand safely, and returns
`PipelineStage` objects. It is not a separate extractor. The normal production
flow is:

```python
scan = scan_ibis_project(["repo_a/jobs", "repo_b/jobs"])
if scan.diagnostics or scan.duplicate_target_conflicts or scan.unresolved_input_datasets:
    ...
graph = extract_pipeline_lineage(scan.stages)
```

In short: `pipeline.py` owns the lineage model and extraction workflow;
`scanner.py` helps production users avoid manually assembling every stage.

## Scanning Mode

Explicit stage registration is supported, but production projects can also scan
folders or many repos for known declarations:

```python
from ibis_unified_lineage import scan_ibis_project, extract_pipeline_lineage

scan = scan_ibis_project(["jobs", "shared_transforms"])
graph = extract_pipeline_lineage(scan.stages)
```

When scanning multiple roots, the scanner adds every scanned root to the import
path for each stage import. This lets a stage in one repository import shared
dataset metadata or target references from another scanned repository while
still producing ordinary `PipelineStage` objects.

Initial supported conventions are:

- modules exporting `PipelineStage` objects,
- modules exporting lists/tuples of `PipelineStage` as `LINEAGE_STAGES`,
  `PIPELINE_STAGES`, or `STAGES`,
- modules exposing `LINEAGE_STAGE_ID`, `LINEAGE_INPUTS`, `LINEAGE_TARGET`, and a
  builder named `LINEAGE_BUILDER`, `build_lineage`, `build_job`, or `build`,
- modules exporting `LINEAGE_JOBS` as mappings with `stage_id`, `inputs`,
  `target`, `builder`, and optional `metadata`.

If a file cannot be understood safely, the scanner reports diagnostics, skipped
files, duplicate target conflicts, and unresolved inputs rather than inventing
lineage.

The multi-repo scanner example in `examples/multirepo_scan` scans four separate
roots: a shared catalog repo plus mart, analytics, and operations job repos. The
resulting DAG materializes several datasets and converges into
`exec.scorecard`.

```bash
uv run --no-editable --reinstall-package ibis-unified-lineage \
  python -m examples.multirepo_scan.demo_run \
  --artifacts artifacts/multirepo-scan
```

## Deep Multi-Stage Example

The static multi-stage example lives in `examples/multistage_pipeline`. It
generates a five-layer DAG:

```text
raw.a + raw.b -> mart.c
raw.d + raw.e + raw.f -> mart.g
mart.c + mart.g + raw.a -> mart.h
mart.h + mart.c -> mart.i
mart.i + raw.f -> mart.k
```

Generate its lineage JSON and HTML UI:

```bash
uv run --no-editable python -m examples.multistage_pipeline.demo_run \
  --artifacts artifacts/multistage-lineage
```

Override logical dataset engines without changing lineage:

```bash
uv run --no-editable python -m examples.multistage_pipeline.demo_run \
  --artifacts artifacts/multistage-lineage-swapped \
  --table-engine raw.a=spark-delta \
  --table-engine mart.c=postgres \
  --table-engine mart.k=polars
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
