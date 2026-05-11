from __future__ import annotations

import ibis

from ibis_unified_lineage import (
    DatasetRef,
    PipelineStage,
    extract_pipeline_lineage,
    transitive_dependency_pairs,
)
from ibis_unified_lineage.ui import write_lineage_ui


def test_explicit_pipeline_extracts_deep_materialized_dag_and_transitive_lineage(tmp_path) -> None:
    """Verify direct and transitive lineage across a five-layer pipeline."""

    graph = extract_pipeline_lineage(_deep_pipeline_stages(), metadata={"job_name": "deep_pipeline"})
    direct = graph.dependency_pairs()
    transitive = transitive_dependency_pairs(graph)

    assert graph.metadata["stages"] == ["stage_c", "stage_g", "stage_h", "stage_i", "stage_k"]
    assert graph.metadata["pipeline"]["canonical"] == "direct/materialized"
    assert ("raw.a.amount", "mart.c.c_total", "value") in direct
    assert ("raw.b.multiplier", "mart.c.c_total", "value") in direct
    assert ("raw.b.flag", "mart.c.c_total", "filter") in direct
    assert ("raw.d.region", "mart.g.region", "value") in direct
    assert ("raw.e.score", "mart.g.g_score", "value") in direct
    assert ("raw.f.fx", "mart.g.g_score", "value") in direct
    assert ("mart.c.c_total", "mart.h.h_metric", "value") in direct
    assert ("mart.g.g_score", "mart.h.h_metric", "value") in direct
    assert ("raw.a.amount", "mart.h.h_metric", "value") in direct
    assert ("mart.h.h_metric", "mart.i.i_metric", "value") in direct
    assert ("mart.c.c_total", "mart.i.i_metric", "value") in direct
    assert ("mart.i.i_metric", "mart.k.k_metric", "value") in direct
    assert ("raw.f.fx", "mart.k.k_metric", "value") in direct

    final = "mart.k.k_metric"
    assert ("raw.a.amount", final) in transitive
    assert ("raw.b.multiplier", final) in transitive
    assert ("raw.b.flag", final) in transitive
    assert ("raw.d.region", final) in transitive
    assert ("raw.e.score", final) in transitive
    assert ("raw.f.fx", final) in transitive

    html_path = write_lineage_ui(graph, tmp_path / "deep_lineage.html")
    html = html_path.read_text(encoding="utf-8")
    assert "arbitrary-depth-materialized-dag" in html
    assert "Direct materialized lineage" in html
    assert "Transitive raw-to-output lineage" in html
    assert '"transitive_edges"' in html
    assert '"stage_order"' in html
    assert "mart.k" in html


def test_pipeline_lineage_is_backend_invariant_when_engines_change() -> None:
    """Verify logical lineage is stable when physical engines change."""

    first = extract_pipeline_lineage(
        _deep_pipeline_stages(
            {
                "raw.a": "spark-delta",
                "raw.b": "sqlite",
                "mart.c": "duckdb",
                "mart.g": "postgres",
                "mart.k": "mysql",
            }
        )
    )
    second = extract_pipeline_lineage(
        _deep_pipeline_stages(
            {
                "raw.a": "sqlite",
                "raw.b": "mysql",
                "mart.c": "spark-delta",
                "mart.g": "duckdb",
                "mart.k": "polars",
            }
        )
    )

    assert first.dependency_pairs() == second.dependency_pairs()
    assert transitive_dependency_pairs(first) == transitive_dependency_pairs(second)


def _deep_pipeline_stages(engine_overrides: dict[str, str] | None = None) -> list[PipelineStage]:
    """Build a deep materialized pipeline with raw and intermediate reuse."""

    engines = engine_overrides or {}
    raw = _raw_datasets(engines)
    c = _target("c", engines.get("mart.c", "duckdb"))
    g = _target("g", engines.get("mart.g", "duckdb"))
    h = _target("h", engines.get("mart.h", "duckdb"))
    i = _target("i", engines.get("mart.i", "duckdb"))
    k = _target("k", engines.get("mart.k", "duckdb"))
    return [
        PipelineStage("stage_c", {"a": raw["a"], "b": raw["b"]}, c, _build_c_stage),
        PipelineStage("stage_g", {"d": raw["d"], "e": raw["e"], "f": raw["f"]}, g, _build_g_stage),
        PipelineStage("stage_h", {"c": c, "g": g, "a": raw["a"]}, h, _build_h_stage),
        PipelineStage("stage_i", {"h": h, "c": c}, i, _build_i_stage),
        PipelineStage("stage_k", {"i": i, "f": raw["f"]}, k, _build_k_stage),
    ]


def _raw_datasets(engine_overrides: dict[str, str]) -> dict[str, DatasetRef]:
    schemas = {
        "a": {"a_id": "int64", "k1": "string", "amount": "float64", "category": "string"},
        "b": {"a_id": "int64", "multiplier": "float64", "flag": "boolean"},
        "d": {"d_id": "int64", "k1": "string", "region": "string"},
        "e": {"d_id": "int64", "score": "float64"},
        "f": {"region": "string", "fx": "float64"},
    }
    return {
        name: DatasetRef(
            name=name,
            engine=engine_overrides.get(f"raw.{name}", "sqlite"),
            database="raw",
            schema=schema.items(),
            logical_name=f"raw.{name}",
        )
        for name, schema in schemas.items()
    }


def _target(name: str, engine: str) -> DatasetRef:
    return DatasetRef(name=name, engine=engine, database="mart", kind="table", logical_name=f"mart.{name}")


def _build_c_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build `raw.a + raw.b -> mart.c`."""

    a = tables["a"]
    b = tables["b"].select(b_a_id=tables["b"].a_id, multiplier=tables["b"].multiplier, flag=tables["b"].flag)
    joined = a.join(b, a.a_id == b.b_a_id)
    enriched = joined.filter(joined.flag).mutate(adjusted=joined.amount * joined.multiplier)
    return enriched.group_by(enriched.k1, enriched.category).agg(c_total=enriched.adjusted.sum())


def _build_g_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build `raw.d + raw.e + raw.f -> mart.g`."""

    d = tables["d"]
    e = tables["e"].select(e_d_id=tables["e"].d_id, score=tables["e"].score)
    f = tables["f"].select(f_region=tables["f"].region, fx=tables["f"].fx)
    joined = d.join(e, d.d_id == e.e_d_id).join(f, d.region == f.f_region)
    enriched = joined.mutate(weighted=joined.score * joined.fx)
    return enriched.group_by(enriched.k1, enriched.region).agg(g_score=enriched.weighted.mean())


def _build_h_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build `mart.c + mart.g + raw.a -> mart.h`."""

    c = tables["c"]
    g = tables["g"]
    a = tables["a"].select(a_k1=tables["a"].k1, amount_seed=tables["a"].amount)
    joined = c.join(g, c.k1 == g.k1).join(a, c.k1 == a.a_k1)
    enriched = joined.mutate(h_base=c.c_total * g.g_score + a.amount_seed)
    return enriched.group_by(c.category, g.region).agg(h_metric=enriched.h_base.sum())


def _build_i_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build `mart.h + mart.c -> mart.i`."""

    h = tables["h"]
    c = tables["c"].select(c_category=tables["c"].category, c_total=tables["c"].c_total)
    joined = h.join(c, h.category == c.c_category)
    enriched = joined.mutate(i_base=h.h_metric + c.c_total)
    return enriched.group_by(h.region).agg(i_metric=enriched.i_base.sum())


def _build_k_stage(tables: dict[str, ibis.Table]) -> ibis.Table:
    """Build `mart.i + raw.f -> mart.k`."""

    i = tables["i"]
    f = tables["f"].select(f_region=tables["f"].region, fx=tables["f"].fx)
    joined = i.join(f, i.region == f.f_region)
    enriched = joined.mutate(k_base=i.i_metric * f.fx)
    return enriched.group_by(i.region).agg(k_metric=enriched.k_base.sum())
