from __future__ import annotations

from ibis_unified_lineage.execution import assert_frame_equalish, execute_monthly_revenue_with_duckdb
from ibis_unified_lineage.sample_data import expected_monthly_revenue, sample_frames


def test_monthly_revenue_job_executes_in_duckdb() -> None:
    """Verify the CSV-backed monthly revenue fixtures execute in DuckDB."""

    actual = execute_monthly_revenue_with_duckdb(sample_frames())
    assert_frame_equalish(actual, expected_monthly_revenue())
