from __future__ import annotations

from collections.abc import Mapping

from sqlglot import exp
from sqlglot.lineage import Node, lineage

from ibis_unified_lineage.models import ColumnDependency, ColumnRef, DatasetRef, LineageEdge, LineageGraph


def extract_sqlglot_lineage(
    sql: str | exp.Expression,
    *,
    target: DatasetRef,
    registry: Mapping[str, DatasetRef],
    schema: Mapping | None = None,
    dialect: str | None = None,
) -> LineageGraph:
    """Extract SQLGlot AST/scope lineage into the common graph model.

    Args:
        sql: SQL text or parsed SQLGlot expression.
        target: Dataset metadata for the SQL output.
        registry: Mapping from SQL table aliases/names to dataset metadata.
        schema: Optional SQLGlot schema mapping used to qualify columns.
        dialect: Optional SQL dialect for parsing and expression rendering.

    Returns:
        Column-level lineage graph in the same model as the Ibis extractor.
    """

    graph = LineageGraph(metadata={"source": "sqlglot"})
    graph.add_dataset(target)
    for dataset in registry.values():
        graph.add_dataset(dataset)

    nodes = lineage(None, sql, schema=schema, dialect=dialect)
    for output_name, node in nodes.items():
        output = ColumnRef(target.key, output_name)
        graph.add_output(output)
        for dependency in _leaf_dependencies(node, registry):
            graph.add_edge(
                LineageEdge(
                    source=dependency.source,
                    target=output,
                    role=dependency.role,
                    transform=dependency.transform,
                    expression=node.expression.sql(dialect=dialect) if hasattr(node.expression, "sql") else str(node.expression),
                    confidence=dependency.confidence,
                )
            )
    return graph


def _leaf_dependencies(node: Node, registry: Mapping[str, DatasetRef]) -> tuple[ColumnDependency, ...]:
    dependencies: list[ColumnDependency] = []
    for item in node.walk():
        if item.downstream:
            continue
        column = _column_from_node(item, registry)
        if column is not None:
            dependencies.append(ColumnDependency(source=column))
    return tuple(dict.fromkeys(dependencies))


def _column_from_node(node: Node, registry: Mapping[str, DatasetRef]) -> ColumnRef | None:
    if "." in node.name:
        table_name, column_name = node.name.rsplit(".", 1)
    else:
        column_name = node.name
        table_name = _single_dataset_key(registry)
        if table_name is None:
            return None

    dataset = registry.get(table_name)
    if dataset is None:
        dataset = next((candidate for candidate in registry.values() if candidate.name == table_name), None)
    if dataset is None:
        return None
    return ColumnRef(dataset.key, column_name.strip('"`[]'))


def _single_dataset_key(registry: Mapping[str, DatasetRef]) -> str | None:
    if len(registry) == 1:
        return next(iter(registry))
    return None
