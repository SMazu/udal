from __future__ import annotations

from analytics_jobs.targets import ANALYTICS_CUSTOMER_LTV, ANALYTICS_REGION_MARGIN, EXEC_SCORECARD
from mart_jobs.targets import MART_CUSTOMER_FEATURES, MART_ORDER_USD, MART_PRODUCT_INVENTORY
from ops_jobs.targets import OPS_INVENTORY_ALERTS


def build_customer_ltv(tables):
    """Build customer lifetime value from revenue and customer features."""

    order_usd = tables["order_usd"]
    customer_features = tables["customer_features"]
    joined = order_usd.join(customer_features, order_usd.customer_id == customer_features.customer_id)
    enriched = joined.mutate(net_after_returns=joined.total_net_usd - joined.total_return_fee)
    return enriched.group_by(enriched.customer_id, enriched.segment, enriched.region).agg(
        lifetime_value=enriched.net_after_returns.sum(),
        tenure_days=enriched.tenure_days.max(),
    )


def build_region_margin(tables):
    """Build regional margin from revenue and inventory pressure."""

    order_usd = tables["order_usd"]
    product_inventory = tables["product_inventory"]
    joined = order_usd.join(product_inventory, order_usd.product_id == product_inventory.product_id)
    enriched = joined.mutate(margin_usd=joined.total_net_usd - joined.stock_gap * joined.unit_cost)
    return enriched.group_by(enriched.region, enriched.category).agg(
        margin_usd=enriched.margin_usd.sum(),
        stock_gap=enriched.stock_gap.sum(),
    )


def build_exec_scorecard(tables):
    """Build executive region scorecard from analytics and ops outputs."""

    customer_ltv = tables["customer_ltv"]
    region_margin = tables["region_margin"]
    inventory_alerts = tables["inventory_alerts"]
    first_join = customer_ltv.join(region_margin, customer_ltv.region == region_margin.region)
    joined = first_join.join(inventory_alerts, customer_ltv.region == inventory_alerts.warehouse_region)
    enriched = joined.mutate(score=joined.lifetime_value + joined.margin_usd - joined.alert_score)
    return enriched.group_by(enriched.region).agg(score=enriched.score.sum())


LINEAGE_JOBS = [
    {
        "stage_id": "stage_customer_ltv",
        "inputs": {"order_usd": MART_ORDER_USD, "customer_features": MART_CUSTOMER_FEATURES},
        "target": ANALYTICS_CUSTOMER_LTV,
        "builder": build_customer_ltv,
        "metadata": {"repo": "analytics_repo", "layer": "analytics"},
    },
    {
        "stage_id": "stage_region_margin",
        "inputs": {"order_usd": MART_ORDER_USD, "product_inventory": MART_PRODUCT_INVENTORY},
        "target": ANALYTICS_REGION_MARGIN,
        "builder": build_region_margin,
        "metadata": {"repo": "analytics_repo", "layer": "analytics"},
    },
    {
        "stage_id": "stage_exec_scorecard",
        "inputs": {
            "customer_ltv": ANALYTICS_CUSTOMER_LTV,
            "region_margin": ANALYTICS_REGION_MARGIN,
            "inventory_alerts": OPS_INVENTORY_ALERTS,
        },
        "target": EXEC_SCORECARD,
        "builder": build_exec_scorecard,
        "metadata": {"repo": "analytics_repo", "layer": "executive"},
    },
]
