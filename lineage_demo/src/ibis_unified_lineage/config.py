from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import ibis
import pandas as pd

from ibis_unified_lineage.models import DatasetRef


@dataclass(frozen=True)
class TableConfig:
    """Configuration for one logical input table.

    Attributes:
        name: Ibis table name used by the job builder.
        logical_name: Stable governance name used in lineage output.
        engine: Physical engine or storage system used by the demo runner.
        schema: Mapping of column names to Ibis type strings.
        csv_path: Fixture CSV path relative to the config fixture root.
        database: Optional database/schema namespace.
        catalog: Optional catalog namespace.
        kind: Physical object kind, such as `table`, `delta`, or `parquet`.
        uri: Optional physical URI/path for the dataset.
    """

    name: str
    logical_name: str
    engine: str
    schema: dict[str, str]
    csv_path: str
    database: str | None = None
    catalog: str | None = None
    kind: str = "table"
    uri: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TableConfig:
        """Build a table config from a JSON-compatible dictionary.

        Args:
            payload: Dictionary loaded from a job config file.

        Returns:
            A normalized table configuration.
        """

        return cls(
            name=str(payload["name"]),
            logical_name=str(payload.get("logical_name") or payload["name"]),
            engine=str(payload.get("engine", "ibis")),
            schema={str(k): str(v) for k, v in payload["schema"].items()},
            csv_path=str(payload.get("csv") or payload.get("csv_path") or ""),
            database=payload.get("database"),
            catalog=payload.get("catalog"),
            kind=str(payload.get("kind", "table")),
            uri=payload.get("uri"),
        )

    def with_overrides(self, overrides: Mapping[str, Any]) -> TableConfig:
        """Return a copy with selected fields overridden.

        Args:
            overrides: JSON-compatible field overrides. Unknown keys are ignored
                so variant configs can remain compact.

        Returns:
            A new table config.
        """

        allowed = {"engine", "kind", "database", "catalog", "uri", "logical_name", "name", "csv", "csv_path"}
        values = {key: value for key, value in overrides.items() if key in allowed}
        if "csv" in values:
            values["csv_path"] = values.pop("csv")
        return replace(self, **values)

    def to_dataset_ref(self) -> DatasetRef:
        """Convert the table config to the normalized lineage dataset model."""

        return DatasetRef(
            name=self.name,
            engine=self.engine,
            catalog=self.catalog,
            database=self.database,
            uri=self.uri,
            kind=self.kind,
            schema=self.schema.items(),
            logical_name=self.logical_name,
        )


@dataclass(frozen=True)
class JobConfig:
    """Configuration for an Ibis lineage demo job.

    Attributes:
        job_name: Human-readable job identifier.
        execution_engine: Engine used to execute the demo query.
        fixture_root: Directory containing fixture CSV files.
        tables: Input table configurations keyed by job table name.
        target: Output dataset configuration.
        expected_csv: Optional expected-output CSV path for result checks.
        lineage_variants: Optional backend override matrix used for invariance
            tests, for example moving `orders` from Spark Delta to SQLite.
    """

    job_name: str
    execution_engine: str
    fixture_root: Path
    tables: dict[str, TableConfig]
    target: DatasetRef
    expected_csv: str | None = None
    lineage_variants: dict[str, dict[str, Any]] | None = None

    @classmethod
    def from_path(cls, path: str | Path) -> JobConfig:
        """Load a job config from JSON.

        Args:
            path: Path to a JSON job config.

        Returns:
            Parsed job configuration with paths resolved relative to the file.
        """

        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        fixture_root = Path(payload.get("fixture_root", "."))
        if not fixture_root.is_absolute():
            fixture_root = path.parent / fixture_root
        target_payload = payload["target"]
        target = DatasetRef(
            name=str(target_payload["name"]),
            engine=str(target_payload.get("engine", payload.get("execution_engine", "ibis"))),
            catalog=target_payload.get("catalog"),
            database=target_payload.get("database"),
            uri=target_payload.get("uri"),
            kind=str(target_payload.get("kind", "table")),
            schema=target_payload.get("schema", {}).items(),
            logical_name=target_payload.get("logical_name"),
        )
        return cls(
            job_name=str(payload["job_name"]),
            execution_engine=str(payload.get("execution_engine", "duckdb")),
            fixture_root=fixture_root,
            tables={name: TableConfig.from_dict(spec) for name, spec in payload["tables"].items()},
            target=target,
            expected_csv=payload.get("expected_csv"),
            lineage_variants=payload.get("lineage_variants", {}),
        )

    def with_engine_overrides(
        self,
        table_engines: Mapping[str, str] | None = None,
        *,
        target_engine: str | None = None,
    ) -> JobConfig:
        """Return a config with table and target engine overrides applied.

        Args:
            table_engines: Mapping of table name to engine name.
            target_engine: Optional replacement target engine.

        Returns:
            A new job config.
        """

        table_engines = table_engines or {}
        unknown = set(table_engines) - set(self.tables)
        if unknown:
            raise KeyError(f"Unknown table engine override(s): {', '.join(sorted(unknown))}")
        tables = {}
        for name, table in self.tables.items():
            if name in table_engines:
                engine = table_engines[name]
                tables[name] = table.with_overrides({"engine": engine, "kind": _default_kind_for_engine(engine)})
            else:
                tables[name] = table
        target = replace(self.target, engine=target_engine) if target_engine else self.target
        return replace(self, tables=tables, target=target)

    def variant(self, name: str) -> JobConfig:
        """Return a named lineage variant from the config file.

        Args:
            name: Variant key in `lineage_variants`.

        Raises:
            KeyError: If the variant is unknown.

        Returns:
            A new config with variant table overrides applied.
        """

        if not self.lineage_variants or name not in self.lineage_variants:
            raise KeyError(f"Unknown lineage variant: {name}")
        variant = self.lineage_variants[name]
        tables = dict(self.tables)
        for table_name, overrides in variant.get("tables", {}).items():
            tables[table_name] = tables[table_name].with_overrides(overrides)
        target = self.target
        if "target" in variant:
            target_payload = dict(variant["target"])
            target = replace(target, **{key: value for key, value in target_payload.items() if hasattr(target, key)})
        return replace(self, tables=tables, target=target)

    def registry(self) -> dict[str, DatasetRef]:
        """Return lookup aliases for resolving Ibis table nodes to datasets."""

        registry: dict[str, DatasetRef] = {}
        for table in self.tables.values():
            dataset = table.to_dataset_ref()
            aliases = {table.name, dataset.key, dataset.qualified_name}
            for alias in aliases:
                if alias:
                    registry[alias] = dataset
        return registry

    def unbound_tables(self) -> dict[str, ibis.Table]:
        """Create unbound Ibis table expressions from configured schemas."""

        return {
            name: ibis.table(table.schema, name=table.name)
            for name, table in self.tables.items()
        }

    def load_frames(self) -> dict[str, pd.DataFrame]:
        """Load all configured CSV fixtures into pandas data frames."""

        return {
            name: read_csv_fixture(self.fixture_root / table.csv_path, table.schema)
            for name, table in self.tables.items()
        }

    def load_expected_frame(self) -> pd.DataFrame | None:
        """Load the configured expected-output CSV, if present."""

        if not self.expected_csv:
            return None
        return read_csv_fixture(self.fixture_root / self.expected_csv, dict(self.target.schema))


def read_csv_fixture(path: str | Path, schema: Mapping[str, str]) -> pd.DataFrame:
    """Read a fixture CSV using the configured schema.

    Args:
        path: CSV path.
        schema: Mapping of column name to Ibis type string.

    Returns:
        A pandas DataFrame with columns ordered as configured.
    """

    path = Path(path)
    dtype = {
        column: _pandas_dtype(dtype_name)
        for column, dtype_name in schema.items()
        if _pandas_dtype(dtype_name) is not None
    }
    frame = pd.read_csv(path, dtype=dtype)
    return frame[list(schema.keys())]


def default_config_path() -> Path:
    """Return the built-in monthly revenue demo config path."""

    return Path(__file__).resolve().parents[2] / "fixtures" / "monthly_revenue" / "job_config.json"


def load_default_config() -> JobConfig:
    """Load the built-in monthly revenue demo config."""

    return JobConfig.from_path(default_config_path())


def _pandas_dtype(dtype_name: str) -> str | None:
    normalized = dtype_name.lower()
    if normalized in {"string", "str"}:
        return "string"
    if normalized in {"int64", "int32", "int16", "int8"}:
        return normalized
    if normalized in {"float64", "float32", "double"}:
        return "float64" if normalized == "double" else normalized
    if normalized in {"boolean", "bool"}:
        return "boolean"
    return None


def _default_kind_for_engine(engine: str) -> str:
    normalized = engine.lower().replace("_", "-")
    if "delta" in normalized:
        return "delta"
    if "parquet" in normalized:
        return "parquet"
    return "table"
