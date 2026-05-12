from __future__ import annotations

from catalog.refs import RAW_CUSTOMERS, RAW_FX_RATES, RAW_ORDERS, RAW_RETURNS
from ibis_unified_lineage import PipelineStage
from mart_jobs.targets import MART_CUSTOMER_FEATURES, MART_ORDER_USD


def build_order_usd(tables):
    """Build customer/product revenue in USD from raw orders and FX rates."""

    orders = tables["orders"]
    fx_rates = tables["fx_rates"]
    paid_orders = orders.filter(orders.order_status == "paid")
    joined = paid_orders.join(fx_rates, paid_orders.currency == fx_rates.currency)
    enriched = joined.mutate(
        net_usd=joined.gross_amount * (1.0 - joined.discount_pct) * joined.rate_to_usd,
    )
    return enriched.group_by(enriched.customer_id, enriched.product_id, enriched.region).agg(
        total_net_usd=enriched.net_usd.sum(),
        gross_usd=enriched.gross_amount.sum(),
    )


def build_customer_features(tables):
    """Build reusable customer return and tenure features."""

    customers = tables["customers"]
    returns = tables["returns"]
    joined = customers.left_join(returns, customers.customer_id == returns.customer_id)
    enriched = joined.mutate(return_fee_filled=joined.return_fee.fill_null(0.0))
    return enriched.group_by(enriched.customer_id, enriched.segment, enriched.region).agg(
        total_return_fee=enriched.return_fee_filled.sum(),
        tenure_days=enriched.signup_days.max(),
    )


LINEAGE_STAGES = [
    PipelineStage(
        "stage_order_usd",
        {"orders": RAW_ORDERS, "fx_rates": RAW_FX_RATES},
        MART_ORDER_USD,
        build_order_usd,
        metadata={"repo": "mart_repo", "layer": "mart"},
    ),
    PipelineStage(
        "stage_customer_features",
        {"customers": RAW_CUSTOMERS, "returns": RAW_RETURNS},
        MART_CUSTOMER_FEATURES,
        build_customer_features,
        metadata={"repo": "mart_repo", "layer": "mart"},
    ),
]
