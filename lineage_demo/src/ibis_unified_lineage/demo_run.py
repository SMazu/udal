from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from ibis_unified_lineage import build_monthly_revenue_job, extract_lineage, logical_registry, mart_dataset, unbound_tables
from ibis_unified_lineage.execution import assert_frame_equalish, execute_monthly_revenue_with_duckdb
from ibis_unified_lineage.sample_data import expected_monthly_revenue, sample_frames
from ibis_unified_lineage.ui import write_lineage_ui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", default="artifacts/lineage-demo")
    parser.add_argument("--service-mode", action="store_true")
    args = parser.parse_args(argv)

    artifacts = Path(args.artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)

    if args.service_mode:
        frames, service_summary = seed_and_collect_service_frames(artifacts)
    else:
        frames = sample_frames()
        service_summary = {"mode": "in-process-frames"}

    actual = execute_monthly_revenue_with_duckdb(frames)
    expected = expected_monthly_revenue()
    assert_frame_equalish(actual, expected)

    expr = build_monthly_revenue_job(unbound_tables())
    spark_graph = extract_lineage(
        expr,
        registry=logical_registry(order_engine="spark-delta"),
        target=mart_dataset(),
        job_name="monthly_revenue",
    )
    sqlite_graph = extract_lineage(
        expr,
        registry=logical_registry(order_engine="sqlite"),
        target=mart_dataset(),
        job_name="monthly_revenue",
    )
    if spark_graph.dependency_pairs() != sqlite_graph.dependency_pairs():
        raise AssertionError("Lineage dependency shape changed when orders moved from Spark Delta to SQLite")

    actual.to_csv(artifacts / "monthly_revenue.csv", index=False)
    (artifacts / "lineage_spark_orders.json").write_text(
        json.dumps(spark_graph.to_dict(), indent=2),
        encoding="utf-8",
    )
    (artifacts / "lineage_sqlite_orders.json").write_text(
        json.dumps(sqlite_graph.to_dict(), indent=2),
        encoding="utf-8",
    )
    html_path = write_lineage_ui(spark_graph, artifacts / "lineage.html")

    summary = {
        "status": "ok",
        "artifacts": {
            "monthly_revenue_csv": str(artifacts / "monthly_revenue.csv"),
            "lineage_spark_orders_json": str(artifacts / "lineage_spark_orders.json"),
            "lineage_sqlite_orders_json": str(artifacts / "lineage_sqlite_orders.json"),
            "lineage_html": str(html_path),
        },
        "service_summary": service_summary,
        "output_rows": len(actual),
        "dataset_count": len(spark_graph.datasets),
        "output_column_count": len(spark_graph.outputs),
        "edge_count": len(spark_graph.edges),
        "backend_invariant_dependency_pairs": len(spark_graph.dependency_pairs()),
    }
    (artifacts / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def seed_and_collect_service_frames(artifacts: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    frames = sample_frames()
    service_summary: dict[str, Any] = {"mode": "service-backed"}

    sqlite_path = artifacts / "customers.sqlite"
    seed_sqlite(sqlite_path, frames["customers"])
    service_summary["sqlite"] = str(sqlite_path)

    seed_postgres(frames["fx_rates"])
    service_summary["postgres"] = "finance.fx_rates"

    seed_mysql(frames["promotions"])
    service_summary["mysql"] = "marketing.promotions"

    returns_path = artifacts / "returns.parquet"
    seed_polars_parquet(returns_path, frames["returns"])
    service_summary["polars_parquet"] = str(returns_path)

    spark_info = seed_spark_orders(artifacts / "spark", frames["orders"])
    service_summary["spark"] = spark_info

    collected = {
        "orders": spark_info["frame"],
        "customers": read_sqlite(sqlite_path),
        "fx_rates": read_postgres(),
        "promotions": read_mysql(),
        "returns": read_polars_parquet(returns_path),
    }
    service_summary["spark"].pop("frame", None)
    return collected, service_summary


def seed_sqlite(path: Path, frame: pd.DataFrame) -> None:
    with sqlite3.connect(path) as conn:
        frame.to_sql("customers", conn, if_exists="replace", index=False)


def read_sqlite(path: Path) -> pd.DataFrame:
    with sqlite3.connect(path) as conn:
        return pd.read_sql_query("SELECT customer_id, region, segment FROM customers", conn)


def seed_postgres(frame: pd.DataFrame) -> None:
    import psycopg

    with psycopg.connect(_postgres_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS fx_rates")
            cur.execute(
                """
                CREATE TABLE fx_rates (
                  currency TEXT NOT NULL,
                  rate_month TEXT NOT NULL,
                  rate_to_usd DOUBLE PRECISION NOT NULL
                )
                """
            )
            cur.executemany(
                "INSERT INTO fx_rates (currency, rate_month, rate_to_usd) VALUES (%s, %s, %s)",
                [tuple(row) for row in frame[["currency", "rate_month", "rate_to_usd"]].itertuples(index=False, name=None)],
            )


def read_postgres() -> pd.DataFrame:
    import psycopg

    with psycopg.connect(_postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT currency, rate_month, rate_to_usd FROM fx_rates ORDER BY currency, rate_month")
            rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["currency", "rate_month", "rate_to_usd"])


def seed_mysql(frame: pd.DataFrame) -> None:
    import MySQLdb

    conn = MySQLdb.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        user=os.getenv("MYSQL_USER", "lineage"),
        passwd=os.getenv("MYSQL_PASSWORD", "lineage"),
        db=os.getenv("MYSQL_DATABASE", "marketing"),
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS promotions")
        cur.execute(
            """
            CREATE TABLE promotions (
              promo_id BIGINT NOT NULL,
              channel VARCHAR(64) NOT NULL,
              promo_discount_pct DOUBLE NOT NULL
            )
            """
        )
        cur.executemany(
            "INSERT INTO promotions (promo_id, channel, promo_discount_pct) VALUES (%s, %s, %s)",
            [tuple(row) for row in frame[["promo_id", "channel", "promo_discount_pct"]].itertuples(index=False, name=None)],
        )
        conn.commit()
    finally:
        conn.close()


def read_mysql() -> pd.DataFrame:
    import MySQLdb

    conn = MySQLdb.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        user=os.getenv("MYSQL_USER", "lineage"),
        passwd=os.getenv("MYSQL_PASSWORD", "lineage"),
        db=os.getenv("MYSQL_DATABASE", "marketing"),
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT promo_id, channel, promo_discount_pct FROM promotions ORDER BY promo_id")
        rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=["promo_id", "channel", "promo_discount_pct"])


def seed_polars_parquet(path: Path, frame: pd.DataFrame) -> None:
    import polars as pl

    path.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(frame).write_parquet(path)


def read_polars_parquet(path: Path) -> pd.DataFrame:
    import polars as pl

    return pl.read_parquet(path).to_pandas()


def seed_spark_orders(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    delta_path = path / "orders_delta"
    parquet_path = path / "orders_parquet"

    try:
        from delta import configure_spark_with_delta_pip
        from pyspark.sql import SparkSession

        builder = (
            SparkSession.builder.appName("ibis-unified-lineage-demo")
            .master("local[1]")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            .config("spark.driver.memory", "1g")
            .config("spark.sql.shuffle.partitions", "1")
        )
        spark = configure_spark_with_delta_pip(builder).getOrCreate()
        storage_format = "delta"
        write_path = delta_path
        spark.createDataFrame(frame).write.format("delta").mode("overwrite").save(str(write_path))
        collected = spark.read.format("delta").load(str(write_path)).toPandas()
    except Exception as exc:
        from pyspark.sql import SparkSession

        spark = (
            SparkSession.builder.appName("ibis-unified-lineage-demo")
            .master("local[1]")
            .config("spark.driver.memory", "1g")
            .config("spark.sql.shuffle.partitions", "1")
            .getOrCreate()
        )
        storage_format = "parquet-fallback"
        write_path = parquet_path
        spark.createDataFrame(frame).write.mode("overwrite").parquet(str(write_path))
        collected = spark.read.parquet(str(write_path)).toPandas()
        exc_message = repr(exc)
    else:
        exc_message = None
    finally:
        try:
            spark.stop()
        except Exception:
            pass

    return {
        "engine": "spark",
        "storage_format": storage_format,
        "path": str(write_path),
        "delta_error": exc_message,
        "frame": collected,
    }


def _postgres_dsn() -> str:
    return (
        f"host={os.getenv('POSTGRES_HOST', '127.0.0.1')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'finance')} "
        f"user={os.getenv('POSTGRES_USER', 'postgres')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'postgres')}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
