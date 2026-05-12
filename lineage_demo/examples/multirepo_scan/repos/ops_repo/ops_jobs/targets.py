from __future__ import annotations

from ibis_unified_lineage import DatasetRef

OPS_INVENTORY_ALERTS = DatasetRef(
    name="inventory_alerts",
    engine="mysql",
    database="ops",
    logical_name="ops.inventory_alerts",
)
