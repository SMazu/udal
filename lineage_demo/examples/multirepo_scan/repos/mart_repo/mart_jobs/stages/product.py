from __future__ import annotations

from catalog.refs import RAW_INVENTORY, RAW_PRODUCTS
from ibis_unified_lineage import PipelineStage
from mart_jobs.targets import MART_PRODUCT_INVENTORY


def build_product_inventory(tables):
    """Build product/category inventory pressure by warehouse region."""

    products = tables["products"]
    inventory = tables["inventory"]
    joined = products.join(inventory, products.product_id == inventory.product_id)
    enriched = joined.mutate(stock_gap=joined.reorder_point - joined.on_hand)
    return enriched.group_by(enriched.product_id, enriched.category, enriched.warehouse_region).agg(
        stock_gap=enriched.stock_gap.sum(),
        unit_cost=enriched.unit_cost.max(),
    )


STAGE_PRODUCT_INVENTORY = PipelineStage(
    "stage_product_inventory",
    {"products": RAW_PRODUCTS, "inventory": RAW_INVENTORY},
    MART_PRODUCT_INVENTORY,
    build_product_inventory,
    metadata={"repo": "mart_repo", "layer": "mart"},
)
