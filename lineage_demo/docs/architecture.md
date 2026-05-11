# Architecture

`ibis-unified-lineage` is split into a small library and a heavier example
harness.

## Core Library

The PyPI wheel should contain only `src/ibis_unified_lineage`:

- `models.py` defines stable lineage artifacts: datasets, columns,
  dependencies, edges, graphs, and graph merging.
- `extractor.py` walks Ibis operation trees and emits column dependency edges
  with roles such as `value`, `filter`, `join`, `group`, `order`, and `opaque`.
- `sqlglot_bridge.py` maps SQLGlot lineage output into the same graph model for
  SQL-string entry points.
- `ui.py` renders any `LineageGraph` as standalone HTML without depending on
  the monthly revenue example.
- `py.typed` marks the package as typed for downstream type checkers.

Core code must not import example modules, CSV fixtures, Docker setup, database
clients, Spark, pandas, or test-only helpers.

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
