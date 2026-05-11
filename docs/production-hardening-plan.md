# Production Hardening Plan For The Ibis Lineage Library

## Current Prototype Gaps

The first implementation proves that engine-agnostic lineage can be extracted
from Ibis expression graphs and validated in a service-backed demo. It is still
prototype-shaped in several important ways.

1. Demo inputs are hard-coded in Python. A production library needs an explicit
   table/job configuration model so users can swap `orders` from Spark Delta to
   SQLite, move `fx_rates` from Postgres to DuckDB, or change the target engine
   without editing library code.
2. Demo data is embedded in Python. Fixtures should live in portable files such
   as CSV so the same data can be loaded into any configured engine and inspected
   outside Python.
3. Service setup is table-specific. Seeding `customers`, `fx_rates`, and
   `promotions` has hard-coded table names and schemas instead of dispatching on
   engine and table specification.
4. Output execution and lineage target metadata are coupled too loosely. The demo
   executes through DuckDB, but the configured target dataset should still be a
   first-class object that can represent DuckDB, SQLite, Postgres, Spark Delta, or
   another destination.
5. The UI renders one final lineage graph well enough, but the layout assumes a
   source-to-target view. Multi-stage jobs need source, intermediate, and final
   dataset tiers.
6. The tests cover only a shallow job graph. Real pipelines often materialize
   intermediate datasets and then use those intermediates downstream.
7. The extractor does not expose enough knobs for context lineage. Join, filter,
   and group dependencies are useful, but strict column-value lineage and
   context-aware lineage should be separable options.
8. Public functions and data models lack Google-style docstrings, making the
   code harder to navigate without reading implementation details.
9. The docs explain how to run the demo, but not the model, extension points,
   configuration shape, supported engines, artifact contract, or known limits.
10. SQLGlot support is only a bridge. SQL string source expansion, schema
    qualification, and reconciliation against Ibis lineage need more tests.
11. Error handling is demo-grade. Engine setup errors should include table,
    engine, action, and remediation context.
12. Observability is missing. A production library should emit OpenLineage,
    structured JSON, and optional warehouse tables, not only local files.
13. CI quality gates are incomplete. There is no lint/type/doc build gate yet.
14. Performance characteristics are unknown for large expression graphs.
15. The Docker image is useful for demonstration but not hardened for secrets,
    non-root operation, pinned OS packages, or minimal image size.

## Hardening Work In This Pass

This pass upgrades the most important design seams. Items marked complete are
implemented in the current codebase.

1. Complete: Add a JSON-backed `JobConfig` / `TableConfig` model.
2. Complete: Move canonical demo data into CSV fixtures.
3. Complete: Add generic engine dispatch for seeding/reading configured tables.
4. Complete: Add CLI overrides for table engines and target engine.
5. Complete: Generalize the UI to render source, intermediate, and final tiers.
6. Complete: Add stage graph merging for multi-hop lineage.
7. Complete: Add multi-stage tests for `A+B -> C`, `D+E+F -> G`, and `C+G -> H`.
8. Complete: Add Google-style docstrings to public library APIs and tests.
9. Complete: Expand the docs so users can understand the library without opening every
   source file.

## Remaining Production Work After This Pass

Some work belongs in future focused milestones:

1. Strict vs context lineage policy options in the extractor.
2. OpenLineage and DataHub/OpenMetadata emitters.
3. SQLGlot source expansion tests for nested CTEs, views, and dialect-specific
   SQL.
4. Property-based tests over random expression trees.
5. Contract tests against real Ibis backends beyond the demo engines.
6. Static code discovery for multi-file user jobs.
7. Type checking, linting, doc generation, and CI packaging.
8. Secure, minimal production containers.
