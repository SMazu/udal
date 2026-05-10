from __future__ import annotations

from collections.abc import Mapping

import ibis
import pandas as pd

from ibis_unified_lineage.jobs import build_monthly_revenue_job


SORT_COLUMNS = ["region", "segment", "channel", "order_month"]


def execute_monthly_revenue_with_duckdb(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    con = ibis.duckdb.connect()
    for name, frame in frames.items():
        con.create_table(name, frame, overwrite=True)

    tables = {name: con.table(name) for name in frames}
    result = build_monthly_revenue_job(tables).execute()
    result = result.sort_values(SORT_COLUMNS).reset_index(drop=True)
    return result


def assert_frame_equalish(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
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
