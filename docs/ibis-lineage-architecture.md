# Engine-Agnostic Column Lineage For Ibis

## Why SQLGlot Lineage Works The Way It Does

SQLGlot computes lineage from SQL ASTs plus metadata rather than from a separate
logical-plan IR. The core sequence is:

1. Parse SQL into a SQLGlot AST.
2. Expand named sources and CTEs when definitions are supplied.
3. Run `qualify`, which attaches table/source context to column references.
4. Build `Scope` objects, where each `SELECT`, CTE, derived table, union branch,
   and subquery has a map of visible sources.
5. For each selected output column, recursively walk referenced columns through
   the scope graph until a physical table leaf or unknown source is reached.

That design is intentional. SQLGlot is a parser, optimizer, transpiler, and SQL
generator, so keeping lineage on the AST lets it preserve the ability to turn the
same optimized representation back into readable SQL for many dialects. A
logical plan can make lineage simpler, but it also creates another representation
that must be faithfully lowered back to SQL. SQLGlot instead invests in robust
AST traversal, qualification, and scopes.

For Ibis this matters because modern SQL backends compile Ibis expressions into
SQLGlot expressions. SQLGlot lineage is therefore a strong fit for validating the
SQL that Ibis will send to DuckDB, Postgres, MySQL, SQLite, Spark SQL, and other
SQL engines. It is not enough by itself, because Ibis also targets non-SQL
execution paths such as Polars, and because Ibis dataframe expressions already
contain richer typed operation semantics before SQL generation.

## Ibis Hook Points

Ibis builds a typed expression graph from `Expr` wrappers over immutable
operation `Node` instances. Relation operations such as `Project`, `Filter`,
`Aggregate`, `JoinChain`, `Union`, `SQLStringView`, and `DatabaseTable` are the
right static lineage hook because they exist before any backend-specific
compiler runs.

The primary implementation hook is therefore:

```text
Ibis Expr/Table -> Expr.op() -> operation DAG -> lineage graph
```

For SQL string nodes (`SQLStringView` and `SQLQueryResult`) the secondary hook is:

```text
SQL string or SQLGlot AST -> SQLGlot lineage -> normalized lineage graph
```

For execution, lineage emission should wrap `execute`, `create_table`, `insert`,
and file writes, but those wrappers should only attach run metadata. They should
not be the only way to obtain lineage; static extraction must work from importable
job code without executing the backend.

## Cross-Engine Strategy

The library separates logical lineage from physical placement.

`DatasetRef` describes a logical table:

- catalog, database/schema, table name
- physical engine, such as spark-delta, duckdb, postgres, mysql, sqlite, polars,
  parquet, or any future Ibis backend
- optional URI/path/connection alias
- schema

`ColumnRef` points to a column in a `DatasetRef`.

`ColumnLineage` maps one output `ColumnRef` to one or more input `ColumnRef`
values, with transform metadata such as identity, projection, aggregate, join
predicate, filter predicate, window context, literal, or opaque SQL/UDF.

Because physical placement is metadata, changing `orders` from Spark Delta to
SQLite should only change the source dataset's engine field. The dependency
shape remains stable as long as the Ibis job expression is unchanged.

## Extraction Strategy

The extractor walks Ibis relation nodes recursively:

- `DatabaseTable`, `UnboundTable`, `InMemoryTable`: source leaves.
- `Field`: direct column dependency.
- `Project`: each output column is traced through its value expression.
- `Filter`, `Sort`, `Limit`, `Distinct`, `FillNull`, `DropNull`, `Sample`: keep
  parent column mappings, adding predicate/context dependencies where relevant.
- `Aggregate`: group outputs trace to group expressions; metric outputs trace to
  aggregate argument columns.
- `JoinChain`: output columns trace to the selected left/right fields; join
  predicates are recorded as row-context dependencies.
- `Union` and other set operations: each output column traces to matching columns
  from each branch.
- `SQLStringView` and `SQLQueryResult`: use SQLGlot lineage when source schemas
  are available; otherwise mark as opaque but keep table-level lineage.
- UDF/raw SQL/unknown nodes: collect visible `Field` descendants when possible
  and mark transform confidence as partial or opaque.

This gives engine-agnostic lineage for all Ibis backends because it does not
depend on the execution engine's optimizer.

## Execution Demo Strategy

The end-to-end demo uses multiple physical systems but one logical Ibis job:

- `orders`: Spark-created Delta/parquet table.
- `customers`: SQLite table.
- `fx_rates`: Postgres table.
- `promotions`: MySQL table.
- `returns`: parquet data read through Polars/DuckDB.

For deterministic local execution, the demo federates the small example into
DuckDB after the physical systems are populated. That keeps execution testable in
one image while preserving physical source metadata for lineage. The lineage is
extracted from the Ibis expression and is compared across two physical placement
variants to prove that dependency shape is stable when a table moves engines.

## Programmatic UI

The UI is generated from the normalized lineage JSON. It renders:

- dataset nodes grouped by engine
- column nodes for each input and output
- directed edges from source columns to derived output columns
- transform labels and confidence flags
- a backend-change comparison view

The UI must be a generated static artifact so it can be attached to CI, a data
job run, or a local developer workflow without requiring a separate server.

## Validation Plan

1. Unit-test Ibis extraction against projections, filters, joins, aggregations,
   windows, set operations, literals, and opaque SQL strings.
2. Validate compiled SQL with SQLGlot lineage for SQL-capable backends where the
   query can be rendered.
3. Run an end-to-end Docker image that starts Spark, Postgres, MySQL, SQLite,
   DuckDB, and Polars data setup.
4. Execute the unified job and compare the output rows.
5. Extract lineage for the Spark/Delta placement and for a SQLite placement of
   the same logical `orders` table.
6. Assert the column dependency pairs are identical after ignoring physical engine
   metadata.
7. Generate and inspect the static lineage UI.
