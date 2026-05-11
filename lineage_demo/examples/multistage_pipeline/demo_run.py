"""Command-line artifact generator for the deep multi-stage lineage example."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.multistage_pipeline.jobs import pipeline_stages
from ibis_unified_lineage import extract_pipeline_lineage, transitive_dependency_pairs
from ibis_unified_lineage.ui import write_lineage_ui


def main(argv: list[str] | None = None) -> int:
    """Generate JSON and HTML artifacts for the deep multi-stage lineage DAG.

    Args:
        argv: Optional command-line arguments. Defaults to `sys.argv`.

    Returns:
        Process exit code.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("artifacts/multistage-lineage"),
        help="Directory for lineage JSON and HTML artifacts.",
    )
    parser.add_argument(
        "--table-engine",
        action="append",
        default=[],
        metavar="DATASET=ENGINE",
        help="Override a logical dataset engine, for example raw.a=spark-delta.",
    )
    args = parser.parse_args(argv)

    artifacts = args.artifacts
    artifacts.mkdir(parents=True, exist_ok=True)
    graph = extract_pipeline_lineage(
        pipeline_stages(_parse_engine_overrides(args.table_engine)),
        metadata={"job_name": "deep_multistage_pipeline"},
    )

    lineage_json = artifacts / "deep_lineage.json"
    transitive_json = artifacts / "deep_transitive_pairs.json"
    html_path = write_lineage_ui(graph, artifacts / "deep_lineage.html", title="Deep Multi-Stage Ibis Lineage")

    lineage_json.write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
    transitive_pairs = sorted(transitive_dependency_pairs(graph))
    transitive_json.write_text(json.dumps(transitive_pairs, indent=2), encoding="utf-8")

    print(json.dumps({"lineage": str(lineage_json), "transitive": str(transitive_json), "html": str(html_path)}, indent=2))
    return 0


def _parse_engine_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --table-engine value {value!r}; expected DATASET=ENGINE")
        dataset, engine = value.split("=", 1)
        dataset = dataset.strip()
        engine = engine.strip()
        if not dataset or not engine:
            raise SystemExit(f"Invalid --table-engine value {value!r}; expected DATASET=ENGINE")
        overrides[dataset] = engine
    return overrides


if __name__ == "__main__":
    raise SystemExit(main())
