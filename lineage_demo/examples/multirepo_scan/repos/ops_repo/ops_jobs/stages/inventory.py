from __future__ import annotations

from catalog.refs import RAW_SUPPLIERS
from mart_jobs.targets import MART_PRODUCT_INVENTORY
from ops_jobs.targets import OPS_INVENTORY_ALERTS

LINEAGE_STAGE_ID = "stage_inventory_alerts"
LINEAGE_INPUTS = {"product_inventory": MART_PRODUCT_INVENTORY, "suppliers": RAW_SUPPLIERS}
LINEAGE_TARGET = OPS_INVENTORY_ALERTS


def LINEAGE_BUILDER(tables):
    """Build supplier risk-weighted inventory alerts."""

    product_inventory = tables["product_inventory"]
    suppliers = tables["suppliers"]
    joined = product_inventory.join(suppliers, product_inventory.product_id == suppliers.product_id)
    enriched = joined.mutate(alert_score=joined.stock_gap * joined.risk_score)
    return enriched.group_by(enriched.warehouse_region).agg(alert_score=enriched.alert_score.sum())
