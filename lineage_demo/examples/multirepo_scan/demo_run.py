"""Generate lineage artifacts from several scanned Python repositories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ibis_unified_lineage import extract_pipeline_lineage, scan_ibis_project, transitive_dependency_pairs
from ibis_unified_lineage.scanner import PipelineScanResult
from ibis_unified_lineage.ui import write_lineage_ui

INCLUDE_GLOBS = ("**/stages/*.py",)


def repo_roots() -> list[Path]:
    """Return repository roots used by the multi-repo scanner example."""

    base = Path(__file__).resolve().parent / "repos"
    return [
        base / "catalog_repo",
        base / "mart_repo",
        base / "analytics_repo",
        base / "ops_repo",
    ]


def run_multirepo_scan(artifacts: str | Path) -> dict[str, Any]:
    """Scan multiple repos, extract lineage, and write JSON/HTML artifacts.

    Args:
        artifacts: Output directory for scan, lineage, transitive, and UI
            artifacts.

    Raises:
        RuntimeError: If scanner diagnostics, duplicate targets, or unresolved
            inputs indicate that extraction would be unsafe.

    Returns:
        Summary metadata for tests, demos, and handoff validation.
    """

    output_dir = Path(artifacts)
    output_dir.mkdir(parents=True, exist_ok=True)

    scan = scan_ibis_project(repo_roots(), include_globs=INCLUDE_GLOBS)
    _raise_for_scan_errors(scan)
    graph = extract_pipeline_lineage(scan.stages, metadata={"job_name": "multi_repo_scan"})
    transitive_pairs = sorted(transitive_dependency_pairs(graph))

    scan_json = output_dir / "scan_result.json"
    lineage_json = output_dir / "lineage.json"
    transitive_json = output_dir / "transitive_pairs.json"
    html_path = write_lineage_ui(graph, output_dir / "lineage.html", title="Multi-Repo Ibis Lineage")

    scan_json.write_text(json.dumps(scan.to_dict(), indent=2), encoding="utf-8")
    lineage_json.write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
    transitive_json.write_text(json.dumps(transitive_pairs, indent=2), encoding="utf-8")

    return {
        "stage_ids": [stage.stage_id for stage in scan.stages],
        "topological_stage_order": graph.metadata["stages"],
        "dataset_count": len(graph.datasets),
        "edge_count": len(graph.edges),
        "transitive_pair_count": len(transitive_pairs),
        "scan_json": str(scan_json),
        "lineage_json": str(lineage_json),
        "transitive_json": str(transitive_json),
        "html": str(html_path),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the multi-repo scanner example."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("artifacts/multirepo-scan"),
        help="Directory for generated lineage artifacts.",
    )
    args = parser.parse_args(argv)
    print(json.dumps(run_multirepo_scan(args.artifacts), indent=2))
    return 0


def _raise_for_scan_errors(scan: PipelineScanResult) -> None:
    errors = {
        "diagnostics": [diagnostic.to_dict() for diagnostic in scan.diagnostics],
        "duplicate_target_conflicts": list(scan.duplicate_target_conflicts),
        "unresolved_input_datasets": list(scan.unresolved_input_datasets),
    }
    if any(errors.values()):
        raise RuntimeError(json.dumps(errors, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
