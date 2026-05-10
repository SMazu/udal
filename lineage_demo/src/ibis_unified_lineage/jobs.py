from __future__ import annotations

from collections.abc import Mapping

import ibis

from ibis_unified_lineage.models import DatasetRef


ORDERS_SCHEMA = {
    "order_id": "int64",
    "customer_id": "int64",
    "order_month": "string",
    "quantity": "int64",
    "unit_price": "float64",
    "discount_pct": "float64",
    "currency": "string",
    "status": "string",
    "promo_id": "int64",
}

CUSTOMERS_SCHEMA = {
    "customer_id": "int64",
    "region": "string",
    "segment": "string",
}

FX_RATES_SCHEMA = {
    "currency": "string",
    "rate_month": "string",
    "rate_to_usd": "float64",
}

PROMOTIONS_SCHEMA = {
    "promo_id": "int64",
    "channel": "string",
    "promo_discount_pct": "float64",
}

RETURNS_SCHEMA = {
    "order_id": "int64",
    "is_returned": "boolean",
    "return_fee": "float64",
}

MART_SCHEMA = {
    "region": "string",
    "segment": "string",
    "channel": "string",
    "order_month": "string",
    "total_net_usd": "float64",
    "gross_local": "float64",
    "active_customers": "int64",
    "returned_orders": "int64",
}


def logical_registry(order_engine: str = "spark-delta") -> dict[str, DatasetRef]:
    return {
        "orders": DatasetRef(
            name="orders",
            engine=order_engine,
            database="sales",
            kind="delta" if order_engine == "spark-delta" else "table",
            schema=ORDERS_SCHEMA.items(),
            logical_name="sales.orders",
        ),
        "customers": DatasetRef(
            name="customers",
            engine="sqlite",
            database="crm",
            schema=CUSTOMERS_SCHEMA.items(),
            logical_name="crm.customers",
        ),
        "fx_rates": DatasetRef(
            name="fx_rates",
            engine="postgres",
            database="finance",
            schema=FX_RATES_SCHEMA.items(),
            logical_name="finance.fx_rates",
        ),
        "promotions": DatasetRef(
            name="promotions",
            engine="mysql",
            database="marketing",
            schema=PROMOTIONS_SCHEMA.items(),
            logical_name="marketing.promotions",
        ),
        "returns": DatasetRef(
            name="returns",
            engine="parquet-polars",
            database="ops",
            kind="parquet",
            schema=RETURNS_SCHEMA.items(),
            logical_name="ops.returns",
        ),
    }


def mart_dataset() -> DatasetRef:
    return DatasetRef(
        name="monthly_revenue",
        engine="duckdb",
        database="mart",
        kind="table",
        schema=MART_SCHEMA.items(),
        logical_name="mart.monthly_revenue",
    )


def unbound_tables() -> dict[str, ibis.Table]:
    return {
        "orders": ibis.table(ORDERS_SCHEMA, name="orders"),
        "customers": ibis.table(CUSTOMERS_SCHEMA, name="customers"),
        "fx_rates": ibis.table(FX_RATES_SCHEMA, name="fx_rates"),
        "promotions": ibis.table(PROMOTIONS_SCHEMA, name="promotions"),
        "returns": ibis.table(RETURNS_SCHEMA, name="returns"),
    }


def build_monthly_revenue_job(tables: Mapping[str, ibis.Table]) -> ibis.Table:
    orders = tables["orders"]
    customers = tables["customers"]
    fx_rates = tables["fx_rates"]
    promotions = tables["promotions"].select(
        promo_key=tables["promotions"].promo_id,
        channel=tables["promotions"].channel,
        promo_discount_pct=tables["promotions"].promo_discount_pct,
    )
    returns = tables["returns"].select(
        return_order_id=tables["returns"].order_id,
        is_returned=tables["returns"].is_returned,
        return_fee=tables["returns"].return_fee,
    )

    paid_orders = orders.filter(orders.status == "paid")
    joined = paid_orders.join(customers, paid_orders.customer_id == customers.customer_id)
    joined = joined.left_join(
        fx_rates,
        [
            joined.currency == fx_rates.currency,
            joined.order_month == fx_rates.rate_month,
        ],
    )
    joined = joined.left_join(promotions, joined.promo_id == promotions.promo_key)
    joined = joined.left_join(returns, joined.order_id == returns.return_order_id)

    enriched = joined.mutate(
        channel=joined.channel.fill_null("direct"),
        promo_discount_pct=joined.promo_discount_pct.fill_null(0.0),
        return_fee=joined.return_fee.fill_null(0.0),
        is_returned=joined.is_returned.fill_null(False),
    ).mutate(
        gross_line=joined.quantity * joined.unit_price,
        net_local=joined.quantity
        * joined.unit_price
        * (1.0 - joined.discount_pct)
        * (1.0 - joined.promo_discount_pct.fill_null(0.0)),
        net_usd=(
            joined.quantity
            * joined.unit_price
            * (1.0 - joined.discount_pct)
            * (1.0 - joined.promo_discount_pct.fill_null(0.0))
            * joined.rate_to_usd
        )
        - joined.return_fee.fill_null(0.0),
    )

    return (
        enriched.group_by(
            enriched.region,
            enriched.segment,
            enriched.channel,
            enriched.order_month,
        )
        .agg(
            total_net_usd=enriched.net_usd.sum(),
            gross_local=enriched.gross_line.sum(),
            active_customers=enriched.customer_id.nunique(),
            returned_orders=enriched.is_returned.cast("int64").sum(),
        )
        .select(
            "region",
            "segment",
            "channel",
            "order_month",
            "total_net_usd",
            "gross_local",
            "active_customers",
            "returned_orders",
        )
    )
