from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

import ibis
import pandas as pd

from ibis_unified_lineage.jobs import build_monthly_revenue_job


SORT_COLUMNS = ["region", "segment", "channel", "order_month"]


def execute_ibis_job_with_duckdb(
    frames: Mapping[str, pd.DataFrame],
    job_builder: Callable[[Mapping[str, ibis.Table]], ibis.Table],
    *,
    sort_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Execute an Ibis job against in-memory DuckDB tables.

    Args:
        frames: Input frames keyed by the Ibis table names expected by the job.
        job_builder: Callable that accepts a mapping of Ibis tables and returns
            an Ibis table expression.
        sort_columns: Optional deterministic sort columns for result checks.

    Returns:
        Executed pandas DataFrame.
    """

    con = ibis.duckdb.connect()
    for name, frame in frames.items():
        con.create_table(name, frame, overwrite=True)

    tables = {name: con.table(name) for name in frames}
    result = job_builder(tables).execute()
    if sort_columns:
        result = result.sort_values(sort_columns).reset_index(drop=True)
    return result


def execute_monthly_revenue_with_duckdb(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Execute the monthly-revenue demo job through DuckDB.

    Args:
        frames: Input frames keyed by canonical table name.

    Returns:
        Sorted monthly revenue output.
    """

    return execute_ibis_job_with_duckdb(frames, build_monthly_revenue_job, sort_columns=SORT_COLUMNS)


def assert_frame_equalish(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    """Assert equality for floating-point DataFrames used by the demo.

    Args:
        actual: Actual output DataFrame.
        expected: Expected output DataFrame.
    """

    actual_sorted = actual.sort_values(SORT_COLUMNS).reset_index(drop=True)
    expected_sorted = expected.sort_values(SORT_COLUMNS).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        actual_sorted,
        expected_sorted,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-9,
    )
