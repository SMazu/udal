# Current Agent Context Handoff

This file preserves the working context from the Codex conversation that built
the current multi-stage lineage implementation. It is not a raw transcript; it
is the complete operational context a new Codex agent needs to continue without
losing design intent, user requirements, or verification history.

## User Requirements To Preserve

- Build a production-grade Python library for engine-agnostic column lineage on
  top of Ibis.
- Keep extraction static: lineage must come from lazy Ibis expressions and must
  not require executing queries.
- Keep direct/materialized lineage as the canonical graph. Transitive lineage is
  derived from direct edges.
- Support arbitrarily deep cascading jobs:
  - layer 1 raw datasets can create layer 2 datasets,
  - layer 2 and layer 1 datasets can create layer 3,
  - the pattern must continue for layer 4, layer 5, and beyond.
- Explicit stage registration is supported, but it is not the desired long-term
  user experience. Production users should not have to register every stage
  manually when their jobs live across many Python repositories.
- Scanning mode is required and must build on the same stage model rather than
  creating a second lineage path.
- The HTML UI cannot be a fixed source/intermediate/final three-column layout.
  It must support arbitrary-depth DAGs, direct lineage, transitive lineage, and
  filtering by dataset, column, role, stage, and engine.
- Documentation, examples, `AGENTS.md`, architecture docs, design docs, and code
  docstrings must be clean enough for a new agent to take over.
- Use uv exclusively for build, virtualenv management, package installation, and
  tests. Use canonical uv commands such as `uv add`, `uv build`, and `uv run`.
- Supported Python versions are 3.10 through 3.14.
- Keep small commits and push them.

## Research And Design Context

Earlier work in this thread researched Spark/Databricks lineage, Unity Catalog
concepts, Ibis expression graphs, SQLGlot, and SQLGlot lineage. The key product
decision is that this library should use Ibis expression graph analysis as the
primary source of static lineage and map other lineage sources, such as SQLGlot,
into the same `LineageGraph` model.

The SQLGlot author described SQLGlot lineage as AST/scope based rather than
logical-plan based. This project keeps that path separate in
`sqlglot_bridge.py`. Ibis extraction uses Ibis operation trees instead. Both
approaches converge into the shared model:

- `DatasetRef`
- `ColumnRef`
- `LineageEdge`
- `LineageGraph`

## Current Architecture

Core package:

- `src/ibis_unified_lineage/models.py`: dataset, column, edge, graph, merge, and
  dependency-pair models.
- `src/ibis_unified_lineage/extractor.py`: one-expression Ibis lineage
  extractor. It tags emitted edges with `stage_id`.
- `src/ibis_unified_lineage/pipeline.py`: production multi-stage API:
  `PipelineStage`, `extract_pipeline_lineage`, and
  `transitive_dependency_pairs`.
- `src/ibis_unified_lineage/scanner.py`: conservative Python project scanner
  that returns `PipelineStage` objects and diagnostics.
- `src/ibis_unified_lineage/sqlglot_bridge.py`: SQLGlot lineage bridge.
- `src/ibis_unified_lineage/ui.py`: standalone arbitrary-depth lineage DAG UI.

Examples:

- `examples/monthly_revenue`: service-backed cross-engine demo using Spark
  Delta/parquet, SQLite, Postgres, MySQL, Polars/parquet, and DuckDB.
- `examples/multistage_pipeline`: static deep-DAG lineage demo for
  `raw.a/raw.b -> mart.c`, `raw.d/raw.e/raw.f -> mart.g`,
  `mart.c/mart.g/raw.a -> mart.h`, `mart.h/mart.c -> mart.i`, and
  `mart.i/raw.f -> mart.k`.

Docs:

- `docs/design.md`: production design and API responsibilities.
- `docs/architecture.md`: package architecture and scanner conventions.
- `docs/release.md`: PyPI release checklist.
- `docs/gap-analysis.md`: closed gaps and remaining owner decisions.
- `AGENTS.md`: operating notes for future agents.

## Pipeline API vs Scanner Mode

This distinction matters.

`pipeline.py` is the canonical extraction layer. Use it when a caller already
has structured metadata or can create stage objects directly:

```python
graph = extract_pipeline_lineage(
    [
        PipelineStage(
            stage_id="stage_c",
            inputs={"a": raw_a, "b": raw_b},
            target=mart_c,
            builder=build_c,
        )
    ]
)
```

`scanner.py` is a discovery adapter. Use it when a production caller has Python
job folders or many repositories and wants the library to discover supported
stage declarations:

```python
scan = scan_ibis_project(["repo_a/jobs", "repo_b/jobs"])
graph = extract_pipeline_lineage(scan.stages)
```

The scanner must not compute lineage independently. It should discover
`PipelineStage` objects, report diagnostics, and feed the canonical pipeline
API. Future Airflow/Dagster/dbt/internal manifest adapters should follow the
same pattern.

## Scanner Conventions Implemented

`scan_ibis_project` supports:

- module-level `PipelineStage` objects,
- module-level lists or tuples of `PipelineStage`,
- collections named `LINEAGE_STAGES`, `PIPELINE_STAGES`, or `STAGES`,
- module metadata variables `LINEAGE_STAGE_ID`, `LINEAGE_INPUTS`,
  `LINEAGE_TARGET`, and a builder named `LINEAGE_BUILDER`, `build_lineage`,
  `build_job`, or `build`,
- `LINEAGE_JOBS` collections of dictionaries with `stage_id`, `inputs`,
  `target`, `builder`, and optional `metadata`.

The scanner returns:

- `stages`
- `skipped_files`
- `diagnostics`
- `duplicate_target_conflicts`
- `unresolved_input_datasets`

If a file cannot be understood safely, report a structured diagnostic. Do not
invent target/input metadata or silently flatten unknown logic.

## UI Context

The old UI had fixed panels for source datasets, intermediate datasets, and
final outputs. That was explicitly rejected by the user because production DAGs
can be deeper and more complex.

The current UI embeds:

- `dag.model = arbitrary-depth-materialized-dag`
- topological dataset layers
- dataset-level edges derived from column-level edges
- direct column edges
- derived transitive edges
- stage metadata
- filters for dataset, column, role, stage, and engine
- a mode switch for direct materialized lineage versus transitive raw-to-output
  lineage

The generated deep lineage page was inspected in the browser and showed:

- 10 datasets
- 5 layers
- 13 materialized output columns
- 83 direct column edges
- 24 transitive edges
- no browser console errors

The generated local artifact path was:

```text
lineage_demo/artifacts/multistage-lineage/deep_lineage.html
```

Generated artifacts are intentionally ignored by git.

## Verification Already Completed

Commands run from `lineage_demo` unless noted:

```bash
uv run pytest tests
rm -rf dist
uv build
scripts/uv_test_matrix.sh
uv run --no-editable python -m examples.multistage_pipeline.demo_run \
  --artifacts artifacts/multistage-lineage
uv run python -m compileall -q src examples tests
```

`scripts/uv_test_matrix.sh` installed the built wheel and passed on:

- Python 3.10
- Python 3.11
- Python 3.12
- Python 3.13
- Python 3.14

Docker/OrbStack verification from the repository root:

```bash
docker build -f lineage_demo/docker/Dockerfile -t ibis-unified-lineage-demo:latest .
docker run --rm \
  -v "$PWD/lineage_demo/artifacts/docker-e2e:/artifacts" \
  ibis-unified-lineage-demo:latest
```

The service-backed Docker demo passed with:

- Spark Delta orders
- SQLite customers
- Postgres FX rates
- MySQL promotions
- Polars/parquet returns
- DuckDB output

Known warnings seen during tests are DuckDB/Pandas deprecation or future
warnings in the example execution path, not lineage failures.

## Commits Pushed

The relevant pushed commits are:

- `bc164e9 feat: add production pipeline lineage DAG`
- `dae1587 docs: document production lineage handoff`

Earlier context commits include:

- `03bc8a2 refactor: isolate lineage package core`
- `c449529 docs: add lineage release handoff`
- `59ec889 feat: switch lineage demo packaging to uv`
- `68d42ce docs: document uv-only lineage workflow`

## Boundaries For The Next Agent

- Do not put example fixtures, engine setup, Docker service code, or test-only
  helpers inside `src/ibis_unified_lineage`.
- Do not make scanner mode a separate lineage extraction implementation.
- Do not flatten materialized boundaries in the canonical graph.
- Do not require live backend connections for lineage extraction.
- Do not reintroduce a fixed three-tier HTML layout.
- Keep package/library docs and examples updated with behavior changes.
- Keep using uv-only workflows.
- Preserve installed-wheel tests because editable installs can hide packaging
  mistakes.

## Likely Next Work

- Add type checking and linting once style choices are agreed.
- Add AST-only scanning for repositories that cannot be safely imported, while
  keeping it convention-based and diagnostic-rich.
- Add orchestrator/catalog adapters that emit `PipelineStage` objects.
- Add OpenLineage/DataHub emitters on top of `LineageGraph`.
- Add property-based tests for more Ibis operations.
- Add policy switches for propagation of filter/join/group context when users
  want stricter or looser lineage semantics.
- Finalize PyPI owner decisions: package name, license, repository URL,
  maintainers, and release classifier.
