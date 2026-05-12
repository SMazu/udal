# Architecture

`ibis-unified-lineage` is split into a small library and a heavier example
harness.

For product-level decisions and handoff context, read `docs/design.md` first.

## Core Library

The PyPI wheel should contain only `src/ibis_unified_lineage`:

- `models.py` defines stable lineage artifacts: datasets, columns,
  dependencies, edges, graphs, and graph merging.
- `extractor.py` walks Ibis operation trees and emits column dependency edges
  with roles such as `value`, `filter`, `join`, `group`, `order`, and `opaque`.
- `pipeline.py` defines `PipelineStage`, static multi-stage extraction, and
  derived transitive dependency traversal. It keeps direct/materialized lineage
  as the canonical graph and computes raw-to-output lineage from direct edges.
- `scanner.py` discovers supported lineage declarations across Python project
  roots and produces the same `PipelineStage` objects as explicit registration.
  Scanner failures are surfaced as structured diagnostics.
- `sqlglot_bridge.py` maps SQLGlot lineage output into the same graph model for
  SQL-string entry points.
- `ui.py` renders any `LineageGraph` as standalone arbitrary-depth DAG HTML
  without depending on the monthly revenue example.
- `py.typed` marks the package as typed for downstream type checkers.

Core code must not import example modules, CSV fixtures, Docker setup, database
clients, Spark, pandas, or test-only helpers.

## Lineage Model

Extraction remains static. The library builds lazy Ibis tables from
`DatasetRef.schema`, invokes stage builders only far enough to produce lazy Ibis
expressions, and traverses the expression graph. It does not run SQL, collect
data, call backend metadata APIs, or require Spark/Delta/Postgres/MySQL to be
available for lineage extraction.

The graph model distinguishes two views:

- Direct/materialized lineage is canonical. These edges preserve stage and
  materialization boundaries such as `raw.a -> mart.c -> mart.h`.
- Transitive lineage is derived on demand from the direct graph. This provides
  raw-to-selected-output pairs without flattening the stored graph.

The standalone HTML viewer embeds both views. Dataset nodes are laid out in
topological layers of arbitrary depth, with materialized datasets allowed at any
rank. Users can switch between direct and transitive edges and filter by
dataset, column, role, stage, and engine.

## Pipeline API And Scanner Responsibilities

`pipeline.py` is the production extraction layer. It should be used whenever a
caller can already provide `PipelineStage` objects, whether those objects come
from tests, explicit application code, orchestration metadata, or a future
adapter.

`scanner.py` is a discovery layer. It exists because production users should not
have to manually register every stage from many repositories. The scanner finds
documented declarations, returns `PipelineStage` objects, and reports
diagnostics. It does not bypass `extract_pipeline_lineage`, and it must not
guess lineage for unsupported Python. During module import, it prepends every
scanned root to `sys.path` so stage files in one repo can import catalog or
target metadata from another scanned repo.

## Scanning Conventions

`scan_ibis_project` scans one or more files or directories. It currently
supports these conventions:

- module-level `PipelineStage` objects,
- module-level collections named `LINEAGE_STAGES`, `PIPELINE_STAGES`, or
  `STAGES`,
- module metadata variables `LINEAGE_STAGE_ID`, `LINEAGE_INPUTS`,
  `LINEAGE_TARGET`, and a builder named `LINEAGE_BUILDER`, `build_lineage`,
  `build_job`, or `build`,
- `LINEAGE_JOBS` collections of dictionaries with `stage_id`, `inputs`,
  `target`, `builder`, and optional `metadata`.

Scanning is intentionally conservative. If arbitrary Python cannot be understood
through a documented convention, the scanner reports a skipped file or
diagnostic. It does not guess target datasets, infer schemas from live systems,
or execute Ibis queries.

The scanner stress example in `examples/multirepo_scan` scans four roots with
cross-repo imports and converging DAGs. It is the preferred local fixture for
validating multi-repo discovery behavior.

## Example Harness

`examples/monthly_revenue` proves the package against a realistic cross-engine
job:

- `config.py`: example config parser and fixture loader.
- `jobs.py`: Ibis monthly revenue transformation and example dataset metadata.
- `execution.py`: DuckDB execution helper used to validate output values.
- `engine_io.py`: optional service-backed round trips through SQLite, DuckDB,
  Postgres, MySQL, Spark Delta/parquet, and Polars/parquet.
- `demo_run.py`: command-line entry point used by local and Docker smoke tests.
- `fixtures/monthly_revenue`: CSV data and expected output for the example.

`examples/multistage_pipeline` and `examples/multirepo_scan` are static lineage
examples. They are used to validate arbitrary-depth pipeline extraction and
multi-repo scanner discovery without starting external services.

The example is deliberately outside the wheel package. It may ship in the sdist
and repository, but it is not part of the runtime import surface.

## Testing Strategy

The test suite has two complementary modes:

- Source tests run with `uv run pytest tests` and can import both the core
  package and repository examples.
- Installed-wheel tests run through `scripts/uv_test_matrix.sh`. They install
  the built wheel into isolated uv environments across Python 3.10-3.14, then
  run the same tests from the repository. The script asserts that demo modules
  are not importable as `ibis_unified_lineage.*` from the wheel.

The Docker image repeats the installed-wheel matrix inside OrbStack/Docker and
runs the service-backed example against real local services.
