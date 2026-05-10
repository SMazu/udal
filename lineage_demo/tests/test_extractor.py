from __future__ import annotations

import ibis

from ibis_unified_lineage import DatasetRef, build_monthly_revenue_job, extract_lineage, logical_registry, mart_dataset, unbound_tables
from ibis_unified_lineage.sqlglot_bridge import extract_sqlglot_lineage


def test_projection_filter_and_aggregate_lineage() -> None:
    orders = ibis.table(
        {
            "customer_id": "int64",
            "amount": "float64",
            "discount": "float64",
            "status": "string",
        },
        name="orders",
    )
    expr = (
        orders.filter(orders.status == "paid")
        .mutate(net=orders.amount * (1.0 - orders.discount))
        .group_by(orders.customer_id)
        .agg(total_net=lambda t: t.net.sum())
    )

    registry = {
        "orders": DatasetRef(
            name="orders",
            engine="duckdb",
            schema=orders.schema().items(),
            logical_name="sales.orders",
        )
    }
    target = DatasetRef(name="customer_revenue", engine="duckdb", logical_name="mart.customer_revenue")
    graph = extract_lineage(expr, registry=registry, target=target)

    pairs = graph.dependency_pairs()
    assert ("sales.orders.amount", "mart.customer_revenue.total_net", "value") in pairs
    assert ("sales.orders.discount", "mart.customer_revenue.total_net", "value") in pairs
    assert ("sales.orders.status", "mart.customer_revenue.total_net", "filter") in pairs
    assert ("sales.orders.customer_id", "mart.customer_revenue.total_net", "group") in pairs


def test_cross_engine_job_lineage_is_stable_when_orders_backend_moves() -> None:
    expr = build_monthly_revenue_job(unbound_tables())
    spark_graph = extract_lineage(
        expr,
        registry=logical_registry(order_engine="spark-delta"),
        target=mart_dataset(),
        job_name="monthly_revenue",
    )
    sqlite_graph = extract_lineage(
        expr,
        registry=logical_registry(order_engine="sqlite"),
        target=mart_dataset(),
        job_name="monthly_revenue",
    )

    assert spark_graph.dependency_pairs() == sqlite_graph.dependency_pairs()
    assert ("sales.orders.quantity", "mart.monthly_revenue.total_net_usd", "value") in spark_graph.dependency_pairs()
    assert ("finance.fx_rates.rate_to_usd", "mart.monthly_revenue.total_net_usd", "value") in spark_graph.dependency_pairs()
    assert ("marketing.promotions.promo_discount_pct", "mart.monthly_revenue.total_net_usd", "value") in spark_graph.dependency_pairs()
    assert ("ops.returns.return_fee", "mart.monthly_revenue.total_net_usd", "value") in spark_graph.dependency_pairs()
    assert ("sales.orders.status", "mart.monthly_revenue.total_net_usd", "filter") in spark_graph.dependency_pairs()


def test_sqlglot_bridge_extracts_column_lineage() -> None:
    registry = {
        "orders": DatasetRef(
            name="orders",
            engine="duckdb",
            schema={"amount": "double", "discount": "double"},
            logical_name="sales.orders",
        )
    }
    target = DatasetRef(name="result", engine="duckdb", logical_name="mart.result")
    graph = extract_sqlglot_lineage(
        'SELECT amount * (1 - discount) AS net FROM orders',
        target=target,
        registry=registry,
        schema={"orders": {"amount": "double", "discount": "double"}},
        dialect="duckdb",
    )

    pairs = graph.dependency_pairs()
    assert ("sales.orders.amount", "mart.result.net", "value") in pairs
    assert ("sales.orders.discount", "mart.result.net", "value") in pairs
