from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ibis_unified_lineage.config import JobConfig, TableConfig


class EngineIOError(RuntimeError):
    """Error raised when configured fixture data cannot be loaded through an engine."""


def collect_configured_frames(
    config: JobConfig,
    artifacts: str | Path,
    *,
    service_mode: bool = False,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Load configured input data, optionally round-tripping through engines.

    Args:
        config: Job configuration containing input table specs and CSV fixtures.
        artifacts: Directory for engine files such as SQLite databases, parquet
            files, and local Spark table paths.
        service_mode: When true, seed/read each table through its configured
            physical engine. When false, read the CSV fixtures directly.

    Returns:
        A tuple of frames keyed by Ibis table name and a structured summary of
        how each frame was loaded.
    """

    artifacts = Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)

    fixture_frames = config.load_frames()
    if not service_mode:
        return fixture_frames, {
            "mode": "csv-fixtures",
            "tables": {
                name: {
                    "engine": table.engine,
                    "kind": table.kind,
                    "csv": str(config.fixture_root / table.csv_path),
                    "rows": len(fixture_frames[name]),
                }
                for name, table in config.tables.items()
            },
        }

    collected: dict[str, pd.DataFrame] = {}
    summaries: dict[str, Any] = {}
    for name, table in config.tables.items():
        frame, summary = seed_and_collect_table(table, fixture_frames[name], artifacts)
        collected[name] = frame
        summaries[name] = summary
    return collected, {"mode": "service-backed", "tables": summaries}


def seed_and_collect_table(
    table: TableConfig,
    frame: pd.DataFrame,
    artifacts: str | Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Seed and read one configured table through its declared engine.

    Args:
        table: Table configuration.
        frame: Fixture frame to seed.
        artifacts: Directory for engine-local files.

    Raises:
        EngineIOError: If the configured engine is unsupported or fails.

    Returns:
        The collected frame and a per-table engine summary.
    """

    artifacts = Path(artifacts)
    engine = _normalize_engine(table.engine)
    try:
        if engine == "sqlite":
            return _roundtrip_sqlite(table, frame, artifacts)
        if engine == "duckdb":
            return _roundtrip_duckdb(table, frame, artifacts)
        if engine == "postgres":
            return _roundtrip_postgres(table, frame)
        if engine == "mysql":
            return _roundtrip_mysql(table, frame)
        if engine in {"parquet-polars", "polars-parquet", "polars"}:
            return _roundtrip_polars_parquet(table, frame, artifacts)
        if engine in {"spark-delta", "spark-parquet", "spark"}:
            return _roundtrip_spark(table, frame, artifacts, prefer_delta=engine == "spark-delta")
        if engine in {"csv", "pandas", "in-memory"}:
            return _coerce_frame_to_schema(frame, table.schema), {
                "engine": table.engine,
                "kind": table.kind,
                "rows": len(frame),
                "mode": "in-memory",
            }
    except Exception as exc:  # pragma: no cover - exercised by service integration.
        message = f"Failed to load table {table.name!r} through engine {table.engine!r}: {exc}"
        raise EngineIOError(message) from exc

    supported = "sqlite, duckdb, postgres, mysql, parquet-polars, spark-delta, csv"
    raise EngineIOError(f"Unsupported engine {table.engine!r} for table {table.name!r}. Supported: {supported}")


def _roundtrip_sqlite(
    table: TableConfig,
    frame: pd.DataFrame,
    artifacts: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = Path(table.uri) if table.uri else artifacts / f"{table.name}.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        _coerce_frame_to_schema(frame, table.schema).to_sql(table.name, conn, if_exists="replace", index=False)
        columns = ", ".join(_quote_sqlite(name) for name in table.schema)
        result = pd.read_sql_query(f"SELECT {columns} FROM {_quote_sqlite(table.name)}", conn)
    return _coerce_frame_to_schema(result, table.schema), {
        "engine": "sqlite",
        "kind": table.kind,
        "path": str(path),
        "rows": len(result),
    }


def _roundtrip_duckdb(
    table: TableConfig,
    frame: pd.DataFrame,
    artifacts: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    import duckdb

    path = Path(table.uri) if table.uri else artifacts / f"{table.name}.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        seed_frame = _coerce_frame_to_schema(frame, table.schema)
        con.register("_seed_frame", seed_frame)
        con.execute(f"CREATE OR REPLACE TABLE {_quote_duckdb(table.name)} AS SELECT * FROM _seed_frame")
        columns = ", ".join(_quote_duckdb(name) for name in table.schema)
        result = con.execute(f"SELECT {columns} FROM {_quote_duckdb(table.name)}").fetchdf()
    finally:
        con.close()
    return _coerce_frame_to_schema(result, table.schema), {
        "engine": "duckdb",
        "kind": table.kind,
        "path": str(path),
        "rows": len(result),
    }


def _roundtrip_postgres(
    table: TableConfig,
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    import psycopg

    columns = list(table.schema)
    with psycopg.connect(_postgres_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {_quote_pg(table.name)}")
            cur.execute(_create_table_sql(table.name, table.schema, dialect="postgres"))
            placeholders = ", ".join(["%s"] * len(columns))
            cur.executemany(
                f"INSERT INTO {_quote_pg(table.name)} ({_column_list(columns, 'postgres')}) VALUES ({placeholders})",
                _rows(_coerce_frame_to_schema(frame, table.schema), columns),
            )
            cur.execute(f"SELECT {_column_list(columns, 'postgres')} FROM {_quote_pg(table.name)}")
            rows = cur.fetchall()
    result = pd.DataFrame(rows, columns=columns)
    return _coerce_frame_to_schema(result, table.schema), {
        "engine": "postgres",
        "kind": table.kind,
        "table": table.name,
        "rows": len(result),
    }


def _roundtrip_mysql(
    table: TableConfig,
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    import MySQLdb

    columns = list(table.schema)
    conn = MySQLdb.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        user=os.getenv("MYSQL_USER", "lineage"),
        passwd=os.getenv("MYSQL_PASSWORD", "lineage"),
        db=os.getenv("MYSQL_DATABASE", table.database or "lineage"),
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {_quote_mysql(table.name)}")
        cur.execute(_create_table_sql(table.name, table.schema, dialect="mysql"))
        placeholders = ", ".join(["%s"] * len(columns))
        cur.executemany(
            f"INSERT INTO {_quote_mysql(table.name)} ({_column_list(columns, 'mysql')}) VALUES ({placeholders})",
            _rows(_coerce_frame_to_schema(frame, table.schema), columns),
        )
        conn.commit()
        cur.execute(f"SELECT {_column_list(columns, 'mysql')} FROM {_quote_mysql(table.name)}")
        rows = cur.fetchall()
    finally:
        conn.close()
    result = pd.DataFrame(rows, columns=columns)
    return _coerce_frame_to_schema(result, table.schema), {
        "engine": "mysql",
        "kind": table.kind,
        "table": table.name,
        "rows": len(result),
    }


def _roundtrip_polars_parquet(
    table: TableConfig,
    frame: pd.DataFrame,
    artifacts: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    import polars as pl

    path = Path(table.uri) if table.uri else artifacts / f"{table.name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(_coerce_frame_to_schema(frame, table.schema)).write_parquet(path)
    result = pl.read_parquet(path).to_pandas()
    return _coerce_frame_to_schema(result, table.schema), {
        "engine": "parquet-polars",
        "kind": "parquet",
        "path": str(path),
        "rows": len(result),
    }


def _roundtrip_spark(
    table: TableConfig,
    frame: pd.DataFrame,
    artifacts: Path,
    *,
    prefer_delta: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    spark_root = artifacts / "spark"
    spark_root.mkdir(parents=True, exist_ok=True)
    delta_path = Path(table.uri) if table.uri and prefer_delta else spark_root / f"{table.name}_delta"
    parquet_path = Path(table.uri) if table.uri and not prefer_delta else spark_root / f"{table.name}_parquet"
    seed_frame = _spark_safe_frame(_coerce_frame_to_schema(frame, table.schema))

    try:
        if not prefer_delta:
            raise RuntimeError("Configured for Spark parquet storage")
        from delta import configure_spark_with_delta_pip
        from pyspark.sql import SparkSession

        builder = _delta_spark_builder()
        spark = configure_spark_with_delta_pip(builder).getOrCreate()
        storage_format = "delta"
        write_path = delta_path
        spark.createDataFrame(seed_frame).write.format("delta").mode("overwrite").save(str(write_path))
        result = spark.read.format("delta").load(str(write_path)).toPandas()
        delta_error = None
    except Exception as exc:
        from pyspark.sql import SparkSession

        spark = _plain_spark_builder(SparkSession.builder).getOrCreate()
        storage_format = "parquet-fallback" if prefer_delta else "parquet"
        write_path = parquet_path
        spark.createDataFrame(seed_frame).write.mode("overwrite").parquet(str(write_path))
        result = spark.read.parquet(str(write_path)).toPandas()
        delta_error = repr(exc) if prefer_delta else None
    finally:
        try:
            spark.stop()
        except Exception:
            pass

    return _coerce_frame_to_schema(result, table.schema), {
        "engine": "spark",
        "kind": table.kind,
        "storage_format": storage_format,
        "path": str(write_path),
        "delta_error": delta_error,
        "rows": len(result),
    }


def _delta_spark_builder(builder: Any | None = None) -> Any:
    if builder is None:
        from pyspark.sql import SparkSession

        builder = SparkSession.builder
    return (
        builder.appName("ibis-unified-lineage-demo")
        .master("local[1]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.driver.memory", "1g")
        .config("spark.sql.shuffle.partitions", "1")
    )


def _plain_spark_builder(builder: Any | None = None) -> Any:
    if builder is None:
        from pyspark.sql import SparkSession

        builder = SparkSession.builder
    return (
        builder.appName("ibis-unified-lineage-demo")
        .master("local[1]")
        .config("spark.driver.memory", "1g")
        .config("spark.sql.shuffle.partitions", "1")
    )


def _create_table_sql(name: str, schema: Mapping[str, str], *, dialect: str) -> str:
    columns = ", ".join(
        f"{_quote_identifier(column, dialect)} {_sql_type(dtype, dialect)}"
        for column, dtype in schema.items()
    )
    return f"CREATE TABLE {_quote_identifier(name, dialect)} ({columns})"


def _column_list(columns: list[str], dialect: str) -> str:
    return ", ".join(_quote_identifier(column, dialect) for column in columns)


def _quote_identifier(identifier: str, dialect: str) -> str:
    if dialect == "postgres":
        return _quote_pg(identifier)
    if dialect == "mysql":
        return _quote_mysql(identifier)
    if dialect == "duckdb":
        return _quote_duckdb(identifier)
    return _quote_sqlite(identifier)


def _quote_pg(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_mysql(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _quote_sqlite(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_duckdb(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sql_type(dtype: str, dialect: str) -> str:
    normalized = dtype.lower()
    if normalized in {"string", "str"}:
        return "TEXT" if dialect == "postgres" else "VARCHAR(255)"
    if normalized in {"int64", "int32", "int16", "int8"}:
        return "BIGINT"
    if normalized in {"float64", "float32", "double"}:
        return "DOUBLE PRECISION" if dialect == "postgres" else "DOUBLE"
    if normalized in {"boolean", "bool"}:
        return "BOOLEAN"
    return "TEXT"


def _rows(frame: pd.DataFrame, columns: list[str]) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for values in frame[columns].itertuples(index=False, name=None):
        rows.append(tuple(None if pd.isna(value) else value for value in values))
    return rows


def _coerce_frame_to_schema(frame: pd.DataFrame, schema: Mapping[str, str]) -> pd.DataFrame:
    result = frame.copy()
    for column, dtype in schema.items():
        normalized = dtype.lower()
        if normalized in {"string", "str"}:
            result[column] = result[column].astype("string")
        elif normalized in {"int64", "int32", "int16", "int8"}:
            result[column] = result[column].astype(normalized)
        elif normalized in {"float64", "float32", "double"}:
            result[column] = result[column].astype("float64" if normalized == "double" else normalized)
        elif normalized in {"boolean", "bool"}:
            result[column] = result[column].astype("boolean")
    return result[list(schema.keys())]


def _spark_safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if pd.api.types.is_string_dtype(result[column]):
            result[column] = result[column].astype(object)
        if str(result[column].dtype) == "boolean":
            result[column] = result[column].astype(bool)
    return result


def _normalize_engine(engine: str) -> str:
    return engine.strip().lower().replace("_", "-")


def _postgres_dsn() -> str:
    return (
        f"host={os.getenv('POSTGRES_HOST', '127.0.0.1')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'finance')} "
        f"user={os.getenv('POSTGRES_USER', 'postgres')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'postgres')}"
    )
