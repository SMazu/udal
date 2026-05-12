from __future__ import annotations

from ibis_unified_lineage import DatasetRef

MART_ORDER_USD = DatasetRef(name="order_usd", engine="duckdb", database="mart", logical_name="mart.order_usd")
MART_CUSTOMER_FEATURES = DatasetRef(
    name="customer_features",
    engine="duckdb",
    database="mart",
    logical_name="mart.customer_features",
)
MART_PRODUCT_INVENTORY = DatasetRef(
    name="product_inventory",
    engine="duckdb",
    database="mart",
    logical_name="mart.product_inventory",
)
