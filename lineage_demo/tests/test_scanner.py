from __future__ import annotations

from pathlib import Path

from ibis_unified_lineage import extract_pipeline_lineage, scan_ibis_project, transitive_dependency_pairs


def test_scanner_discovers_stage_modules_across_project_roots(tmp_path) -> None:
    """Verify scan mode produces PipelineStage objects used by extraction."""

    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    _write(repo_a / "stage_c.py", _stage_c_module())
    _write(repo_a / "stage_g.py", _stage_g_module())
    _write(repo_b / "stage_h.py", _stage_h_module())
    _write(repo_b / "ignored.py", "VALUE = 1\n")

    result = scan_ibis_project([repo_a, repo_b])

    assert sorted(stage.stage_id for stage in result.stages) == ["stage_c", "stage_g", "stage_h"]
    assert not result.duplicate_target_conflicts
    assert not result.unresolved_input_datasets
    assert any(Path(item.path).name == "ignored.py" for item in result.skipped_files)

    graph = extract_pipeline_lineage(result.stages, metadata={"job_name": "scanned_pipeline"})
    assert graph.metadata["stages"] == ["stage_c", "stage_g", "stage_h"]
    assert ("raw.a.amount", "mart.h.h_metric") in transitive_dependency_pairs(graph)
    assert ("raw.e.score", "mart.h.h_metric") in transitive_dependency_pairs(graph)


def test_scanner_reports_diagnostics_without_inventing_lineage(tmp_path) -> None:
    """Verify unsupported and ambiguous scan files return structured errors."""

    root = tmp_path / "project"
    root.mkdir()
    _write(
        root / "ambiguous.py",
        """
from ibis_unified_lineage import DatasetRef

LINEAGE_STAGES = ["not a stage"]
""",
    )
    _write(
        root / "broken.py",
        """
from ibis_unified_lineage import PipelineStage

raise RuntimeError("do not import me")
""",
    )
    _write(
        root / "conflict_a.py",
        _minimal_stage_module("stage_a", "target"),
    )
    _write(
        root / "conflict_b.py",
        _minimal_stage_module("stage_b", "target"),
    )

    result = scan_ibis_project(root)
    codes = {diagnostic.code for diagnostic in result.diagnostics}

    assert "ambiguous_stage_collection" in codes
    assert "no_stage_discovered" in codes
    assert "import_error" in codes
    assert result.duplicate_target_conflicts == (
        {"target": "mart.target", "stage_ids": ["stage_a", "stage_b"]},
    )
    assert [stage.stage_id for stage in result.stages] == ["stage_a", "stage_b"]


def _write(path: Path, content: str) -> None:
    path.write_text(content.lstrip(), encoding="utf-8")


def _stage_c_module() -> str:
    return """
from ibis_unified_lineage import DatasetRef, PipelineStage

raw_a = DatasetRef(
    name="a",
    engine="sqlite",
    database="raw",
    schema={"a_id": "int64", "k1": "string", "amount": "float64", "category": "string"},
    logical_name="raw.a",
)
raw_b = DatasetRef(
    name="b",
    engine="duckdb",
    database="raw",
    schema={"a_id": "int64", "multiplier": "float64", "flag": "boolean"},
    logical_name="raw.b",
)
mart_c = DatasetRef(name="c", engine="duckdb", database="mart", logical_name="mart.c")

def build_c(tables):
    a = tables["a"]
    b = tables["b"].select(b_a_id=tables["b"].a_id, multiplier=tables["b"].multiplier, flag=tables["b"].flag)
    joined = a.join(b, a.a_id == b.b_a_id)
    enriched = joined.filter(joined.flag).mutate(adjusted=joined.amount * joined.multiplier)
    return enriched.group_by(enriched.k1, enriched.category).agg(c_total=enriched.adjusted.sum())

STAGE_C = PipelineStage("stage_c", {"a": raw_a, "b": raw_b}, mart_c, build_c)
"""


def _stage_g_module() -> str:
    return """
from ibis_unified_lineage import DatasetRef, PipelineStage

raw_d = DatasetRef(
    name="d",
    engine="postgres",
    database="raw",
    schema={"d_id": "int64", "k1": "string", "region": "string"},
    logical_name="raw.d",
)
raw_e = DatasetRef(
    name="e",
    engine="mysql",
    database="raw",
    schema={"d_id": "int64", "score": "float64"},
    logical_name="raw.e",
)
raw_f = DatasetRef(
    name="f",
    engine="polars",
    database="raw",
    schema={"region": "string", "fx": "float64"},
    logical_name="raw.f",
)
mart_g = DatasetRef(name="g", engine="duckdb", database="mart", logical_name="mart.g")

def build_g(tables):
    d = tables["d"]
    e = tables["e"].select(e_d_id=tables["e"].d_id, score=tables["e"].score)
    f = tables["f"].select(f_region=tables["f"].region, fx=tables["f"].fx)
    joined = d.join(e, d.d_id == e.e_d_id).join(f, d.region == f.f_region)
    enriched = joined.mutate(weighted=joined.score * joined.fx)
    return enriched.group_by(enriched.k1, enriched.region).agg(g_score=enriched.weighted.mean())

LINEAGE_STAGES = [PipelineStage("stage_g", {"d": raw_d, "e": raw_e, "f": raw_f}, mart_g, build_g)]
"""


def _stage_h_module() -> str:
    return """
from ibis_unified_lineage import DatasetRef

LINEAGE_STAGE_ID = "stage_h"
LINEAGE_INPUTS = {
    "c": DatasetRef(name="c", engine="duckdb", database="mart", logical_name="mart.c"),
    "g": DatasetRef(name="g", engine="duckdb", database="mart", logical_name="mart.g"),
}
LINEAGE_TARGET = DatasetRef(name="h", engine="duckdb", database="mart", logical_name="mart.h")

def LINEAGE_BUILDER(tables):
    c = tables["c"]
    g = tables["g"]
    joined = c.join(g, c.k1 == g.k1)
    enriched = joined.mutate(blended=c.c_total * g.g_score)
    return enriched.group_by(c.category, g.region).agg(h_metric=enriched.blended.sum())
"""


def _minimal_stage_module(stage_id: str, target_name: str) -> str:
    return f'''
from ibis_unified_lineage import DatasetRef, PipelineStage

source = DatasetRef(
    name="source",
    engine="sqlite",
    schema={{"id": "int64", "amount": "float64"}},
    logical_name="raw.source",
)
target = DatasetRef(name="{target_name}", engine="duckdb", database="mart", logical_name="mart.{target_name}")

def build(tables):
    return tables["source"].select(amount=tables["source"].amount)

STAGE = PipelineStage("{stage_id}", {{"source": source}}, target, build)
'''
