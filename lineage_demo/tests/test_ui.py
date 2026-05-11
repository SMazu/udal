from __future__ import annotations

from examples.monthly_revenue.jobs import build_monthly_revenue_job, logical_registry, mart_dataset, unbound_tables
from ibis_unified_lineage import extract_lineage
from ibis_unified_lineage.ui import write_lineage_ui


def test_lineage_ui_is_generated(tmp_path) -> None:
    """Verify the standalone HTML UI includes lineage data and labels."""

    expr = build_monthly_revenue_job(unbound_tables())
    graph = extract_lineage(expr, registry=logical_registry(), target=mart_dataset(), job_name="monthly_revenue")
    path = write_lineage_ui(graph, tmp_path / "lineage.html")

    html = path.read_text(encoding="utf-8")
    assert "Ibis Unified Column Lineage" in html
    assert "sales.orders" in html
    assert "mart.monthly_revenue" in html
    assert "total_net_usd" in html
