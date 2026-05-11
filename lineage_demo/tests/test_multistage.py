from __future__ import annotations

import ibis

from ibis_unified_lineage import DatasetRef, extract_lineage, merge_lineage_graphs
from ibis_unified_lineage.ui import write_lineage_ui


def test_materialized_multistage_lineage_is_merged_and_rendered(tmp_path) -> None:
    """Verify lineage for `A+B -> C`, `D+E+F -> G`, and `C+G -> H`.

    This test models a realistic production pipeline where intermediate tables
    are materialized and then reused by downstream jobs. The merged graph should
    preserve both base-table lineage and intermediate-to-final lineage.
    """

    sources = _source_tables()
    source_registry = _source_registry(sources)

    c_expr = _build_c_stage(sources)
    g_expr = _build_g_stage(sources)
    c_target = DatasetRef(
        name="c",
        engine="duckdb",
        database="mart",
        schema=c_expr.schema().items(),
        logical_name="mart.c",
    )
    g_target = DatasetRef(
        name="g",
        engine="duckdb",
        database="mart",
        schema=g_expr.schema().items(),
        logical_name="mart.g",
    )

    c_graph = extract_lineage(c_expr, registry=source_registry, target=c_target, job_name="stage_c")
    g_graph = extract_lineage(g_expr, registry=source_registry, target=g_target, job_name="stage_g")

    h_tables = {
        "c": ibis.table(dict(c_expr.schema().items()), name="c"),
        "g": ibis.table(dict(g_expr.schema().items()), name="g"),
    }
    h_expr = _build_h_stage(h_tables)
    h_target = DatasetRef(
        name="h",
        engine="duckdb",
        database="mart",
        schema=h_expr.schema().items(),
        logical_name="mart.h",
    )
    h_graph = extract_lineage(
        h_expr,
        registry={"c": c_target, "g": g_target},
        target=h_target,
        job_name="stage_h",
    )

    merged = merge_lineage_graphs([c_graph, g_graph, h_graph], metadata={"job_name": "multi_stage"})
    pairs = merged.dependency_pairs()

    assert ("raw.a.amount", "mart.c.c_total", "value") in pairs
    assert ("raw.b.multiplier", "mart.c.c_total", "value") in pairs
    assert ("raw.b.flag", "mart.c.c_total", "filter") in pairs
    assert ("raw.d.region", "mart.g.region", "value") in pairs
    assert ("raw.e.score", "mart.g.g_score", "value") in pairs
    assert ("raw.f.fx", "mart.g.g_score", "value") in pairs
    assert ("mart.c.c_total", "mart.h.h_metric", "value") in pairs
    assert ("mart.g.g_score", "mart.h.h_metric", "value") in pairs
    assert ("mart.c.k1", "mart.h.h_metric", "join") in pairs
    assert ("mart.g.k1", "mart.h.h_metric", "join") in pairs

    html_path = write_lineage_ui(merged, tmp_path / "multistage_lineage.html")
    html = html_path.read_text(encoding="utf-8")
    assert "Intermediate Datasets" in html
    assert "Final Outputs" in html
    assert "mart.c" in html
    assert "mart.g" in html
    assert "mart.h" in html


def test_backend_swaps_do_not_change_multistage_logical_dependencies() -> None:
    """Verify that engine metadata changes do not alter logical dependencies."""

    first = _extract_multistage_with_engines({"a": "spark-delta", "c": "duckdb", "g": "duckdb"})
    second = _extract_multistage_with_engines({"a": "sqlite", "c": "postgres", "g": "mysql"})

    assert first.dependency_pairs() == second.dependency_pairs()


def _extract_multistage_with_engines(overrides: dict[str, str]):
    sources = _source_tables()
    source_registry = _source_registry(sources, overrides)
    c_expr = _build_c_stage(sources)
    g_expr = _build_g_stage(sources)
    c_target = DatasetRef(
        name="c",
        engine=overrides.get("c", "duckdb"),
        database="mart",
        schema=c_expr.schema().items(),
        logical_name="mart.c",
    )
    g_target = DatasetRef(
        name="g",
        engine=overrides.get("g", "duckdb"),
        database="mart",
        schema=g_expr.schema().items(),
        logical_name="mart.g",
    )
    h_target = DatasetRef(name="h", engine="duckdb", database="mart", logical_name="mart.h")
    c_graph = extract_lineage(c_expr, registry=source_registry, target=c_target, job_name="stage_c")
    g_graph = extract_lineage(g_expr, registry=source_registry, target=g_target, job_name="stage_g")
    h_expr = _build_h_stage(
        {
            "c": ibis.table(dict(c_expr.schema().items()), name="c"),
            "g": ibis.table(dict(g_expr.schema().items()), name="g"),
        }
    )
    h_graph = extract_lineage(h_expr, registry={"c": c_target, "g": g_target}, target=h_target, job_name="stage_h")
    return merge_lineage_graphs([c_graph, g_graph, h_graph], metadata={"job_name": "multi_stage"})


def _source_tables() -> dict[str, ibis.Table]:
    """Build unbound tables for the synthetic multi-stage pipeline."""

    schemas = {
        "a": {"a_id": "int64", "k1": "string", "amount": "float64", "category": "string"},
        "b": {"a_id": "int64", "multiplier": "float64", "flag": "boolean"},
        "d": {"d_id": "int64", "k1": "string", "region": "string"},
        "e": {"d_id": "int64", "score": "float64"},
        "f": {"region": "string", "fx": "float64"},
    }
    return {name: ibis.table(schema, name=name) for name, schema in schemas.items()}


def _source_registry(tables: dict[str, ibis.Table], overrides: dict[str, str] | None = None) -> dict[str, DatasetRef]:
    """Build source dataset metadata for synthetic tables."""

    overrides = overrides or {}
    return {
        name: DatasetRef(
            name=name,
            engine=overrides.get(name, "sqlite"),
            database="raw",
            schema=table.schema().items(),
            logical_name=f"raw.{name}",
        )
        for name, table in tables.items()
    }


def _build_c_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build the first materialized stage from source tables A and B."""

    a = tables["a"]
    b = tables["b"].select(
        b_a_id=tables["b"].a_id,
        multiplier=tables["b"].multiplier,
        flag=tables["b"].flag,
    )
    joined = a.join(b, a.a_id == b.b_a_id)
    enriched = joined.filter(joined.flag).mutate(adjusted=joined.amount * joined.multiplier)
    return enriched.group_by(enriched.k1, enriched.category).agg(c_total=enriched.adjusted.sum())


def _build_g_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build the second materialized stage from source tables D, E, and F."""

    d = tables["d"]
    e = tables["e"].select(e_d_id=tables["e"].d_id, score=tables["e"].score)
    f = tables["f"].select(f_region=tables["f"].region, fx=tables["f"].fx)
    joined = d.join(e, d.d_id == e.e_d_id).join(f, d.region == f.f_region)
    enriched = joined.mutate(weighted=joined.score * joined.fx)
    return enriched.group_by(enriched.k1, enriched.region).agg(g_score=enriched.weighted.mean())


def _build_h_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build the final stage by joining materialized C and G."""

    c = tables["c"]
    g = tables["g"]
    joined = c.join(g, c.k1 == g.k1)
    enriched = joined.mutate(blended=c.c_total * g.g_score)
    return enriched.group_by(c.category, g.region).agg(h_metric=enriched.blended.sum())
