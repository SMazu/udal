# Production Lineage Design

This document captures the current product design so the next agent can pick up
without relying on chat history.

## Product Direction

`ibis-unified-lineage` extracts column-level lineage from lazy Ibis expressions
without executing queries. The library is intended for a unified data access
layer where a logical pipeline may reference Spark Delta, DuckDB, SQLite,
Postgres, MySQL, Polars/parquet, or other Ibis-supported backends. Backend
placement is metadata; logical lineage is keyed by stable dataset names.

The canonical graph is direct/materialized lineage. If a pipeline writes
`raw.a + raw.b -> mart.c` and later writes `mart.c + mart.g -> mart.h`, the
stored graph keeps both materialization boundaries. Raw-to-final lineage is
computed from those direct edges with `transitive_dependency_pairs`.

## Core APIs

- `extract_lineage(expr, registry, target, job_name)` extracts one Ibis
  expression into a `LineageGraph`.
- `PipelineStage(stage_id, inputs, target, builder, metadata=None)` describes
  one materialized stage. `inputs` map builder aliases to `DatasetRef` objects.
- `extract_pipeline_lineage(stages, metadata=None)` topologically sorts stages,
  constructs lazy Ibis tables from declared schemas, invokes builders, extracts
  each stage, and merges the stage graphs.
- `transitive_dependency_pairs(graph, targets=None)` derives raw-source to
  selected-output pairs from the direct graph.
- `scan_ibis_project(...)` discovers supported Python stage declarations and
  returns `PipelineStage` objects plus diagnostics.
- `write_lineage_ui(graph, path)` writes a standalone arbitrary-depth DAG viewer
  with both direct and transitive edge data embedded.

Stage builders must only construct lazy Ibis expressions. They must not execute
queries, seed databases, collect frames, or depend on live backend connections.
Input datasets need schemas unless they are produced by an upstream discovered
stage whose schema can be inferred from its lazy expression.

## Pipeline API vs Scanner Mode

The pipeline API and scanner mode are intentionally different layers:

- `pipeline.py` is the canonical model and extraction path. It defines
  `PipelineStage`, validates stage ordering, invokes builders to create lazy
  Ibis expressions, extracts each materialization boundary, merges the direct
  graph, and derives transitive pairs.
- `scanner.py` is a discovery adapter. It scans files and folders for supported
  declarations, turns those declarations into `PipelineStage` objects, and
  reports structured diagnostics. It does not compute lineage independently and
  should not contain backend-specific extraction logic.

Use `PipelineStage` and `extract_pipeline_lineage` directly in tests, demos,
or integrations where orchestration metadata is already available. Use
`scan_ibis_project` in production repos where the caller wants the library to
discover declared Ibis jobs across many packages. The scanner result should be
validated first, then passed into the same extraction API:

```python
scan = scan_ibis_project(root_paths)
if scan.duplicate_target_conflicts or scan.unresolved_input_datasets:
    raise ValueError(scan.to_dict())
graph = extract_pipeline_lineage(scan.stages)
```

This layering is important for maintainability: every future discovery source,
including AST-only scanning, Airflow/Dagster/dbt adapters, or internal catalog
manifests, should produce `PipelineStage` objects and reuse
`extract_pipeline_lineage`.

## Scanner Contract

Scanning is required for production use because callers should not have to
manually register every stage. The scanner still builds on the same stage model;
there is no separate lineage path.

Supported conventions:

- module-level `PipelineStage` objects,
- module-level lists/tuples named `LINEAGE_STAGES`, `PIPELINE_STAGES`, or
  `STAGES`,
- module-level metadata `LINEAGE_STAGE_ID`, `LINEAGE_INPUTS`, `LINEAGE_TARGET`,
  and a builder named `LINEAGE_BUILDER`, `build_lineage`, `build_job`, or
  `build`,
- `LINEAGE_JOBS` as a list/tuple of dictionaries with `stage_id`, `inputs`,
  `target`, `builder`, and optional `metadata`.

The scanner imports convention-matching files so it can reuse real Python
objects and callables. It first does a lightweight AST/source marker check to
avoid importing unrelated files. If import or declaration parsing fails, it
returns structured diagnostics. It must not invent lineage for arbitrary Python.

Future work can add orchestrator adapters or a stricter AST-only scanner, but
those should produce `PipelineStage` objects and preserve the diagnostic-first
contract.

## UI Contract

The old three-column source/intermediate/final layout has been replaced. The UI
now embeds:

- `dag.model = arbitrary-depth-materialized-dag`,
- topological dataset `layers`,
- dataset-level edges derived from column edges,
- source, materialized, and final-output dataset classifications,
- direct column edges,
- derived `transitive_edges`,
- stage metadata from pipeline extraction.

The visual layout is free to accommodate deep DAGs. Materialized datasets can
appear at any graph depth. Controls support direct versus transitive edge mode
and filters for dataset, column, role, stage, and engine.

## Examples And Tests

`examples/monthly_revenue` remains the service-backed cross-engine demo. It
uses CSV fixtures and optional Docker/OrbStack services to exercise Spark
Delta/parquet, SQLite, Postgres, MySQL, Polars/parquet, and DuckDB execution.

`examples/multistage_pipeline` is the static multi-stage lineage demo. It
models:

- `raw.a + raw.b -> mart.c`
- `raw.d + raw.e + raw.f -> mart.g`
- `mart.c + mart.g + raw.a -> mart.h`
- `mart.h + mart.c -> mart.i`
- `mart.i + raw.f -> mart.k`

The tests cover source extraction, installed-wheel behavior, backend-invariant
lineage, explicit deep pipeline extraction, transitive raw-to-final lineage,
scanner discovery across multiple roots, scanner diagnostics, and arbitrary-depth
HTML payload generation.

## Current Verification

As of this handoff, the following commands have passed locally:

```bash
uv run pytest tests
rm -rf dist
uv build
scripts/uv_test_matrix.sh
```

The matrix installed the built wheel and ran tests on Python 3.10, 3.11, 3.12,
3.13, and 3.14. Existing warnings are DuckDB/Pandas deprecations in the example
execution path, not lineage failures.
