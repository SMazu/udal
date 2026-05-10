# Ibis Unified Lineage Demo

This folder contains a prototype library and end-to-end demo for extracting
engine-agnostic column lineage from Ibis expressions.

## Local Tests

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest tests
```

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

The image starts Postgres and MariaDB, writes a Spark Delta orders table, writes
SQLite customers, Postgres FX rates, MySQL promotions, and Polars parquet returns,
then executes the unified Ibis job through DuckDB federation. It emits:

- `monthly_revenue.csv`
- `lineage_spark_orders.json`
- `lineage_sqlite_orders.json`
- `lineage.html`
- `summary.json`

The demo also verifies that column dependency pairs remain identical when the
logical `orders` table moves from Spark Delta to SQLite.
