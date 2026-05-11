from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import ibis

from ibis_unified_lineage.extractor import extract_lineage
from ibis_unified_lineage.models import ColumnRef, DatasetRef, LineageGraph, merge_lineage_graphs

PipelineBuilder = Callable[[Mapping[str, ibis.Table]], ibis.Expr]


@dataclass(frozen=True)
class PipelineStage:
    """One materialized Ibis transformation stage.

    Attributes:
        stage_id: Stable identifier for the materialization boundary.
        inputs: Mapping of builder table aliases to input dataset metadata.
        target: Dataset metadata for the materialized output.
        builder: Callable that receives lazy Ibis tables and returns a lazy
            Ibis expression. The callable must not execute the expression.
        metadata: Optional user metadata copied into graph artifacts.
    """

    stage_id: str
    inputs: Mapping[str, DatasetRef]
    target: DatasetRef
    builder: PipelineBuilder
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Normalize mappings and validate required stage fields."""

        stage_id = str(self.stage_id).strip()
        if not stage_id:
            raise ValueError("PipelineStage.stage_id must be a non-empty string")
        if not self.inputs:
            raise ValueError(f"PipelineStage {stage_id!r} must declare at least one input dataset")
        if not callable(self.builder):
            raise TypeError(f"PipelineStage {stage_id!r} builder must be callable")

        object.__setattr__(self, "stage_id", stage_id)
        object.__setattr__(self, "inputs", dict(self.inputs))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        """Serialize stage metadata for graph artifacts and UI filtering."""

        return {
            "stage_id": self.stage_id,
            "inputs": {
                alias: dataset.to_dict()
                for alias, dataset in sorted(self.inputs.items(), key=lambda item: item[0])
            },
            "target": self.target.to_dict(),
            "metadata": dict(self.metadata or {}),
        }


def extract_pipeline_lineage(
    stages: Iterable[PipelineStage],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> LineageGraph:
    """Extract static lineage for an ordered or dependency-sortable pipeline.

    Args:
        stages: Materialized stages. They may be supplied in topological order
            or any order that can be sorted by declared input and target
            dataset keys.
        metadata: Optional pipeline-level metadata attached to the merged
            graph.

    Raises:
        ValueError: If stage targets are duplicated, inputs lack schemas,
            stages form a cycle, or a builder does not return an Ibis
            expression.

    Returns:
        A merged direct/materialized lineage graph. Transitive lineage is
        derived separately with :func:`transitive_dependency_pairs`.
    """

    stage_list = list(stages)
    if not stage_list:
        return LineageGraph(metadata=dict(metadata or {}))

    ordered_stages = _topological_stages(stage_list)
    produced: dict[str, DatasetRef] = {}
    stage_graphs: list[LineageGraph] = []
    stage_records: list[dict[str, Any]] = []

    for stage in ordered_stages:
        resolved_inputs = {
            alias: produced.get(dataset.key, dataset)
            for alias, dataset in stage.inputs.items()
        }
        tables = {
            alias: _lazy_table(alias, dataset, stage_id=stage.stage_id)
            for alias, dataset in resolved_inputs.items()
        }
        expr = stage.builder(tables)
        if not isinstance(expr, ibis.Expr):
            raise ValueError(f"PipelineStage {stage.stage_id!r} builder must return an Ibis expression")

        target = _target_with_schema(stage.target, expr)
        registry = _registry_for_inputs(resolved_inputs)
        graph = extract_lineage(expr, registry=registry, target=target, job_name=stage.stage_id)
        graph.metadata.update(
            {
                "stage_id": stage.stage_id,
                "inputs": {
                    alias: dataset.to_dict()
                    for alias, dataset in sorted(resolved_inputs.items(), key=lambda item: item[0])
                },
                "target": target.to_dict(),
                "stage_metadata": dict(stage.metadata or {}),
            }
        )
        stage_graphs.append(graph)
        produced[target.key] = target
        stage_records.append(
            {
                "stage_id": stage.stage_id,
                "inputs": {
                    alias: dataset.to_dict()
                    for alias, dataset in sorted(resolved_inputs.items(), key=lambda item: item[0])
                },
                "target": target.to_dict(),
                "metadata": dict(stage.metadata or {}),
            }
        )

    merged = merge_lineage_graphs(stage_graphs, metadata=dict(metadata or {}))
    merged.metadata["stages"] = [stage.stage_id for stage in ordered_stages]
    merged.metadata["pipeline"] = {
        "stages": stage_records,
        "stage_order": [stage.stage_id for stage in ordered_stages],
        "canonical": "direct/materialized",
        "extraction": "static-ibis-expression",
    }
    return merged


def transitive_dependency_pairs(
    graph: LineageGraph,
    targets: Iterable[str | ColumnRef] | str | ColumnRef | None = None,
) -> set[tuple[str, str]]:
    """Return transitive raw-column-to-output dependency pairs.

    Args:
        graph: Direct/materialized lineage graph.
        targets: Optional output columns to analyze. Strings must use the
            logical `dataset.column` key. When omitted, final materialized
            output columns are used.

    Returns:
        Set of `(raw_source_column, selected_target_column)` logical pairs.
    """

    reverse_edges: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        reverse_edges[_logical_column_key(graph, edge.target)].add(_logical_column_key(graph, edge.source))

    target_keys = _target_column_keys(graph, targets)
    result: set[tuple[str, str]] = set()
    for target in target_keys:
        for source in _leaf_ancestors(target, reverse_edges, visiting=set()):
            if source != target:
                result.add((source, target))
    return result


def _topological_stages(stages: list[PipelineStage]) -> list[PipelineStage]:
    target_to_stage: dict[str, PipelineStage] = {}
    for stage in stages:
        if stage.target.key in target_to_stage:
            previous = target_to_stage[stage.target.key]
            raise ValueError(
                f"Duplicate pipeline target {stage.target.key!r} produced by "
                f"{previous.stage_id!r} and {stage.stage_id!r}"
            )
        target_to_stage[stage.target.key] = stage

    stage_by_id = {stage.stage_id: stage for stage in stages}
    dependencies: dict[str, set[str]] = {stage.stage_id: set() for stage in stages}
    dependents: dict[str, set[str]] = {stage.stage_id: set() for stage in stages}
    original_order = {stage.stage_id: index for index, stage in enumerate(stages)}

    for stage in stages:
        for dataset in stage.inputs.values():
            upstream = target_to_stage.get(dataset.key)
            if upstream is not None and upstream.stage_id != stage.stage_id:
                dependencies[stage.stage_id].add(upstream.stage_id)
                dependents[upstream.stage_id].add(stage.stage_id)

    ready = deque(
        sorted(
            (stage_id for stage_id, deps in dependencies.items() if not deps),
            key=lambda stage_id: original_order[stage_id],
        )
    )
    ordered: list[PipelineStage] = []
    while ready:
        stage_id = ready.popleft()
        ordered.append(stage_by_id[stage_id])
        for dependent in sorted(dependents[stage_id], key=lambda item: original_order[item]):
            dependencies[dependent].discard(stage_id)
            if not dependencies[dependent]:
                ready.append(dependent)

    if len(ordered) != len(stages):
        cycle = sorted(stage_id for stage_id, deps in dependencies.items() if deps)
        raise ValueError(f"Pipeline stages contain a cycle or unresolved materialization order: {cycle}")
    return ordered


def _lazy_table(alias: str, dataset: DatasetRef, *, stage_id: str) -> ibis.Table:
    if not dataset.schema:
        raise ValueError(
            f"Input dataset {dataset.key!r} for stage {stage_id!r} must declare a schema "
            "so a lazy Ibis table can be constructed without executing a backend query"
        )
    return ibis.table(dict(dataset.schema), name=alias)


def _target_with_schema(target: DatasetRef, expr: ibis.Expr) -> DatasetRef:
    if target.schema:
        return target
    return replace(target, schema=expr.as_table().schema().items())


def _registry_for_inputs(inputs: Mapping[str, DatasetRef]) -> dict[str, DatasetRef]:
    registry: dict[str, DatasetRef] = {}
    for alias, dataset in inputs.items():
        for key in (alias, dataset.name, dataset.qualified_name, dataset.key):
            if key:
                registry.setdefault(key, dataset)
    return registry


def _target_column_keys(
    graph: LineageGraph,
    targets: Iterable[str | ColumnRef] | str | ColumnRef | None,
) -> set[str]:
    if targets is not None:
        if isinstance(targets, (str, ColumnRef)):
            target_items: Iterable[str | ColumnRef] = (targets,)
        else:
            target_items = targets
        return {
            item if isinstance(item, str) else _logical_column_key(graph, item)
            for item in target_items
        }

    consumed_datasets = {
        edge.source.dataset
        for edge in graph.edges
        if edge.source.dataset != edge.target.dataset
    }
    final_outputs = [
        output
        for output in graph.outputs
        if output.dataset not in consumed_datasets
    ]
    if not final_outputs:
        final_outputs = list(graph.outputs)
    return {_logical_column_key(graph, output) for output in final_outputs}


def _leaf_ancestors(
    column_key: str,
    reverse_edges: Mapping[str, set[str]],
    *,
    visiting: set[str],
) -> set[str]:
    parents = reverse_edges.get(column_key, set())
    if not parents:
        return {column_key}
    if column_key in visiting:
        return set()

    visiting.add(column_key)
    ancestors: set[str] = set()
    for parent in parents:
        ancestors.update(_leaf_ancestors(parent, reverse_edges, visiting=visiting))
    visiting.remove(column_key)
    return ancestors


def _logical_column_key(graph: LineageGraph, column: ColumnRef) -> str:
    dataset = graph.datasets.get(column.dataset)
    dataset_name = dataset.logical_name if dataset and dataset.logical_name else column.dataset
    return f"{dataset_name}.{column.column}"
