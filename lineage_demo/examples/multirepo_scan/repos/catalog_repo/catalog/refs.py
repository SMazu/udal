from __future__ import annotations

from ibis_unified_lineage import DatasetRef

RAW_ORDERS = DatasetRef(
    name="orders",
    engine="spark-delta",
    database="raw",
    schema={
        "order_id": "int64",
        "customer_id": "int64",
        "product_id": "int64",
        "region": "string",
        "currency": "string",
        "gross_amount": "float64",
        "discount_pct": "float64",
        "order_status": "string",
    },
    logical_name="raw.orders",
)
RAW_FX_RATES = DatasetRef(
    name="fx_rates",
    engine="postgres",
    database="raw",
    schema={"currency": "string", "rate_to_usd": "float64"},
    logical_name="raw.fx_rates",
)
RAW_CUSTOMERS = DatasetRef(
    name="customers",
    engine="sqlite",
    database="raw",
    schema={"customer_id": "int64", "segment": "string", "region": "string", "signup_days": "int64"},
    logical_name="raw.customers",
)
RAW_RETURNS = DatasetRef(
    name="returns",
    engine="parquet-polars",
    database="raw",
    schema={"order_id": "int64", "customer_id": "int64", "return_fee": "float64", "is_returned": "boolean"},
    logical_name="raw.returns",
)
RAW_PRODUCTS = DatasetRef(
    name="products",
    engine="mysql",
    database="raw",
    schema={"product_id": "int64", "category": "string", "unit_cost": "float64"},
    logical_name="raw.products",
)
RAW_INVENTORY = DatasetRef(
    name="inventory",
    engine="duckdb",
    database="raw",
    schema={"product_id": "int64", "warehouse_region": "string", "on_hand": "int64", "reorder_point": "int64"},
    logical_name="raw.inventory",
)
RAW_SUPPLIERS = DatasetRef(
    name="suppliers",
    engine="postgres",
    database="raw",
    schema={"product_id": "int64", "supplier_id": "int64", "risk_score": "float64"},
    logical_name="raw.suppliers",
)
