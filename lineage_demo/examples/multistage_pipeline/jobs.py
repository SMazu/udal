"""Reusable Ibis builders for the deep multi-stage lineage example."""

from __future__ import annotations

from collections.abc import Mapping

import ibis

from ibis_unified_lineage import DatasetRef, PipelineStage


def raw_datasets(engine_overrides: Mapping[str, str] | None = None) -> dict[str, DatasetRef]:
    """Return schema-bearing raw dataset metadata for the deep DAG example.

    Args:
        engine_overrides: Optional mapping from logical dataset name, such as
            `raw.a`, to physical engine label.

    Returns:
        Raw dataset references keyed by builder alias.
    """

    engines = dict(engine_overrides or {})
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
            engine=engines.get(f"raw.{name}", "sqlite"),
            database="raw",
            schema=schema.items(),
            logical_name=f"raw.{name}",
        )
        for name, schema in schemas.items()
    }


def pipeline_stages(engine_overrides: Mapping[str, str] | None = None) -> list[PipelineStage]:
    """Build the five-stage materialized pipeline used for handoff demos.

    The returned stages intentionally reuse intermediate and raw datasets across
    layers so the generated lineage includes both direct materialization
    boundaries and derived raw-to-final dependencies.

    Args:
        engine_overrides: Optional mapping from logical dataset name to physical
            engine label.

    Returns:
        Ordered `PipelineStage` objects for `C`, `G`, `H`, `I`, and `K`.
    """

    engines = dict(engine_overrides or {})
    raw = raw_datasets(engines)
    c = _target("c", engines.get("mart.c", "duckdb"))
    g = _target("g", engines.get("mart.g", "duckdb"))
    h = _target("h", engines.get("mart.h", "duckdb"))
    i = _target("i", engines.get("mart.i", "duckdb"))
    k = _target("k", engines.get("mart.k", "duckdb"))
    return [
        PipelineStage("stage_c", {"a": raw["a"], "b": raw["b"]}, c, build_c_stage),
        PipelineStage("stage_g", {"d": raw["d"], "e": raw["e"], "f": raw["f"]}, g, build_g_stage),
        PipelineStage("stage_h", {"c": c, "g": g, "a": raw["a"]}, h, build_h_stage),
        PipelineStage("stage_i", {"h": h, "c": c}, i, build_i_stage),
        PipelineStage("stage_k", {"i": i, "f": raw["f"]}, k, build_k_stage),
    ]


def build_c_stage(tables: Mapping[str, ibis.Table]) -> ibis.Table:
    """Build the `raw.a + raw.b -> mart.c` materialization expression."""

    a = tables["a"]
    b = tables["b"].select(b_a_id=tables["b"].a_id, multiplier=tables["b"].multiplier, flag=tables["b"].flag)
    joined = a.join(b, a.a_id == b.b_a_id)
    enriched = joined.filter(joined.flag).mutate(adjusted=joined.amount * joined.multiplier)
    return enriched.group_by(enriched.k1, enriched.category).agg(c_total=enriched.adjusted.sum())


def build_g_stage(tables: Mapping[str, ibis.Table]) -> ibis.Table:
    """Build the `raw.d + raw.e + raw.f -> mart.g` materialization expression."""

    d = tables["d"]
    e = tables["e"].select(e_d_id=tables["e"].d_id, score=tables["e"].score)
    f = tables["f"].select(f_region=tables["f"].region, fx=tables["f"].fx)
    joined = d.join(e, d.d_id == e.e_d_id).join(f, d.region == f.f_region)
    enriched = joined.mutate(weighted=joined.score * joined.fx)
    return enriched.group_by(enriched.k1, enriched.region).agg(g_score=enriched.weighted.mean())


def build_h_stage(tables: Mapping[str, ibis.Table]) -> ibis.Table:
    """Build the `mart.c + mart.g + raw.a -> mart.h` expression."""

    c = tables["c"]
    g = tables["g"]
    a = tables["a"].select(a_k1=tables["a"].k1, amount_seed=tables["a"].amount)
    joined = c.join(g, c.k1 == g.k1).join(a, c.k1 == a.a_k1)
    enriched = joined.mutate(h_base=c.c_total * g.g_score + a.amount_seed)
    return enriched.group_by(c.category, g.region).agg(h_metric=enriched.h_base.sum())


def build_i_stage(tables: Mapping[str, ibis.Table]) -> ibis.Table:
    """Build the `mart.h + mart.c -> mart.i` materialization expression."""

    h = tables["h"]
    c = tables["c"].select(c_category=tables["c"].category, c_total=tables["c"].c_total)
    joined = h.join(c, h.category == c.c_category)
    enriched = joined.mutate(i_base=h.h_metric + c.c_total)
    return enriched.group_by(h.region).agg(i_metric=enriched.i_base.sum())


def build_k_stage(tables: Mapping[str, ibis.Table]) -> ibis.Table:
    """Build the `mart.i + raw.f -> mart.k` final materialization expression."""

    i = tables["i"]
    f = tables["f"].select(f_region=tables["f"].region, fx=tables["f"].fx)
    joined = i.join(f, i.region == f.f_region)
    enriched = joined.mutate(k_base=i.i_metric * f.fx)
    return enriched.group_by(i.region).agg(k_metric=enriched.k_base.sum())


def _target(name: str, engine: str) -> DatasetRef:
    return DatasetRef(name=name, engine=engine, database="mart", kind="table", logical_name=f"mart.{name}")
