from __future__ import annotations

from examples.monthly_revenue.config import load_default_config
from examples.monthly_revenue.engine_io import collect_configured_frames


def test_job_config_loads_csv_fixtures_with_declared_schema(tmp_path) -> None:
    """Verify configured CSV fixtures load with stable columns and summary data."""

    config = load_default_config()
    frames, summary = collect_configured_frames(config, tmp_path, service_mode=False)

    assert set(frames) == set(config.tables)
    assert summary["mode"] == "csv-fixtures"
    for name, table in config.tables.items():
        assert list(frames[name].columns) == list(table.schema)
        assert summary["tables"][name]["rows"] == len(frames[name])


def test_engine_overrides_update_metadata_without_changing_logical_names() -> None:
    """Verify table and target engines can be swapped from configuration."""

    config = load_default_config()
    moved = config.with_engine_overrides(
        {"orders": "sqlite", "returns": "duckdb"},
        target_engine="postgres",
    )

    assert moved.tables["orders"].engine == "sqlite"
    assert moved.tables["orders"].kind == "table"
    assert moved.tables["returns"].engine == "duckdb"
    assert moved.target.engine == "postgres"
    assert moved.registry()["orders"].logical_name == "sales.orders"
