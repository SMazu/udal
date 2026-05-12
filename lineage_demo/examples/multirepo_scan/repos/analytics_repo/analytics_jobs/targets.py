from __future__ import annotations

from ibis_unified_lineage import DatasetRef

ANALYTICS_CUSTOMER_LTV = DatasetRef(
    name="customer_ltv",
    engine="postgres",
    database="analytics",
    logical_name="analytics.customer_ltv",
)
ANALYTICS_REGION_MARGIN = DatasetRef(
    name="region_margin",
    engine="postgres",
    database="analytics",
    logical_name="analytics.region_margin",
)
EXEC_SCORECARD = DatasetRef(
    name="scorecard",
    engine="duckdb",
    database="exec",
    logical_name="exec.scorecard",
)
