from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.monthly_revenue.config import JobConfig, default_config_path
from examples.monthly_revenue.engine_io import collect_configured_frames
from examples.monthly_revenue.execution import assert_frame_equalish, execute_monthly_revenue_with_duckdb
from examples.monthly_revenue.jobs import build_monthly_revenue_job
from ibis_unified_lineage.extractor import extract_lineage
from ibis_unified_lineage.models import LineageGraph
from ibis_unified_lineage.ui import write_lineage_ui


def main(argv: list[str] | None = None) -> int:
    """Run the configured end-to-end lineage demo.

    Args:
        argv: Optional CLI arguments for tests.

    Returns:
        Process exit code.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(default_config_path()), help="Path to a JSON job config.")
    parser.add_argument("--artifacts", default="artifacts/lineage-demo", help="Directory for outputs.")
    parser.add_argument("--service-mode", action="store_true", help="Round-trip fixtures through configured engines.")
    parser.add_argument(
        "--table-engine",
        action="append",
        default=[],
        metavar="TABLE=ENGINE",
        help="Override an input table engine. Can be provided more than once.",
    )
    parser.add_argument("--target-engine", help="Override the output dataset engine.")
    parser.add_argument(
        "--variant",
        action="append",
        help="Named lineage variant to compare. Defaults to every variant in the config.",
    )
    args = parser.parse_args(argv)

    artifacts = Path(args.artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)

    config = JobConfig.from_path(args.config).with_engine_overrides(
        _parse_table_engine_overrides(args.table_engine),
        target_engine=args.target_engine,
    )
    frames, service_summary = collect_configured_frames(config, artifacts, service_mode=args.service_mode)

    actual = execute_monthly_revenue_with_duckdb(frames)
    expected = config.load_expected_frame()
    if expected is not None:
        assert_frame_equalish(actual, expected)

    base_graph = _extract_monthly_revenue_graph(config)
    graph_paths = _write_graph_artifacts(base_graph, artifacts, "base")

    variant_names = args.variant if args.variant is not None else sorted(config.lineage_variants or {})
    variant_summaries: dict[str, dict[str, object]] = {}
    for variant_name in variant_names:
        variant_config = config.variant(variant_name)
        variant_graph = _extract_monthly_revenue_graph(variant_config)
        if base_graph.dependency_pairs() != variant_graph.dependency_pairs():
            raise AssertionError(f"Lineage dependency shape changed for variant {variant_name!r}")
        graph_paths.update(_write_graph_artifacts(variant_graph, artifacts, variant_name))
        variant_summaries[variant_name] = {
            "table_engines": {name: table.engine for name, table in variant_config.tables.items()},
            "dependency_pairs": len(variant_graph.dependency_pairs()),
            "edge_count": len(variant_graph.edges),
        }

    actual.to_csv(artifacts / "monthly_revenue.csv", index=False)
    html_path = write_lineage_ui(base_graph, artifacts / "lineage.html")
    graph_paths["html"] = html_path

    summary = {
        "status": "ok",
        "job_name": config.job_name,
        "config": str(Path(args.config)),
        "artifacts": {
            "monthly_revenue_csv": str(artifacts / "monthly_revenue.csv"),
            **{name: str(path) for name, path in graph_paths.items()},
        },
        "table_engines": {name: table.engine for name, table in config.tables.items()},
        "target_engine": config.target.engine,
        "service_summary": service_summary,
        "variants": variant_summaries,
        "output_rows": len(actual),
        "dataset_count": len(base_graph.datasets),
        "output_column_count": len(base_graph.outputs),
        "edge_count": len(base_graph.edges),
        "backend_invariant_dependency_pairs": len(base_graph.dependency_pairs()),
    }
    (artifacts / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def _extract_monthly_revenue_graph(config: JobConfig) -> LineageGraph:
    expr = build_monthly_revenue_job(config.unbound_tables())
    return extract_lineage(
        expr,
        registry=config.registry(),
        target=config.target,
        job_name=config.job_name,
    )


def _write_graph_artifacts(graph: LineageGraph, artifacts: Path, label: str) -> dict[str, Path]:
    safe_label = label.replace("/", "_").replace(" ", "_")
    paths = {
        f"lineage_{safe_label}_json": artifacts / f"lineage_{safe_label}.json",
    }
    if label == "base":
        paths["lineage_json"] = artifacts / "lineage.json"
        paths["lineage_spark_orders_json"] = artifacts / "lineage_spark_orders.json"
    elif label == "orders_sqlite":
        paths["lineage_sqlite_orders_json"] = artifacts / "lineage_sqlite_orders.json"

    payload = json.dumps(graph.to_dict(), indent=2)
    for path in paths.values():
        path.write_text(payload, encoding="utf-8")
    return paths


def _parse_table_engine_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Expected TABLE=ENGINE override, got {value!r}")
        table, engine = value.split("=", 1)
        table = table.strip()
        engine = engine.strip()
        if not table or not engine:
            raise ValueError(f"Expected TABLE=ENGINE override, got {value!r}")
        overrides[table] = engine
    return overrides


if __name__ == "__main__":
    raise SystemExit(main())
