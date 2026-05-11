from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import ibis
import ibis.expr.operations as ops
from ibis.expr.schema import Schema

from ibis_unified_lineage.models import (
    ColumnDependency,
    ColumnDerivation,
    ColumnRef,
    DatasetRef,
    LineageEdge,
    LineageGraph,
    combine_confidence,
    dedupe_dependencies,
)


@dataclass
class RelationDerivation:
    """Column derivations and source datasets for an Ibis relation node.

    Attributes:
        columns: Mapping of relation output column name to derivation metadata.
        datasets: Source datasets reachable from this relation.
    """

    columns: dict[str, ColumnDerivation]
    datasets: dict[str, DatasetRef] = field(default_factory=dict)


class IbisLineageExtractor:
    """Extract backend-agnostic column lineage from Ibis expression graphs."""

    def __init__(self, registry: Mapping[str, DatasetRef] | None = None) -> None:
        """Initialize the extractor.

        Args:
            registry: Optional mapping from Ibis table aliases to logical and
                physical dataset metadata.
        """

        self.registry = dict(registry or {})
        self._relation_cache: dict[ops.Relation, RelationDerivation] = {}

    def extract(
        self,
        expr: ibis.Expr,
        *,
        target: DatasetRef | None = None,
        job_name: str | None = None,
    ) -> LineageGraph:
        """Extract a column-level lineage graph for an Ibis expression.

        Args:
            expr: Ibis expression to analyze.
            target: Optional dataset metadata for the materialized output.
            job_name: Optional job name to attach to graph metadata.

        Returns:
            A lineage graph with source datasets, output columns, and
            source-to-output column edges.
        """

        table_expr = expr.as_table()
        rel = table_expr.op()
        derivation = self.trace_relation(rel)

        if target is None:
            target = DatasetRef(
                name=job_name or "result",
                engine="ibis",
                kind="derived",
                schema=_schema_items(rel.schema),
                logical_name=job_name or "result",
            )

        stage_id = job_name or target.name
        graph = LineageGraph(metadata={"job_name": stage_id})
        for dataset in derivation.datasets.values():
            graph.add_dataset(dataset)
        graph.add_dataset(target)

        for column_name in rel.schema.names:
            output = ColumnRef(target.key, column_name)
            graph.add_output(output)
            column = derivation.columns.get(column_name, ColumnDerivation(confidence="unknown"))
            for dependency in column.dependencies:
                graph.add_edge(
                    LineageEdge(
                        source=dependency.source,
                        target=output,
                        role=dependency.role,
                        transform=column.transform if dependency.transform == "identity" else dependency.transform,
                        expression=column.expression,
                        confidence=combine_confidence(column.confidence, dependency.confidence),
                        stage_id=stage_id,
                    )
                )
        return graph

    def trace_relation(self, rel: ops.Relation) -> RelationDerivation:
        """Trace column derivations for an Ibis relation operation.

        Args:
            rel: Relation operation from an Ibis expression tree.

        Raises:
            TypeError: If a value operation is passed instead of a relation.

        Returns:
            Relation-level derivation metadata.
        """

        cached = self._relation_cache.get(rel)
        if cached is not None:
            return cached

        if isinstance(rel, ops.Field):
            raise TypeError("Field is a value operation, not a relation operation")

        result = self._trace_relation_uncached(rel)
        self._relation_cache[rel] = result
        return result

    def _trace_relation_uncached(self, rel: ops.Relation) -> RelationDerivation:
        if isinstance(rel, (ops.DatabaseTable, ops.UnboundTable, ops.InMemoryTable)):
            return self._trace_physical_table(rel)

        if isinstance(rel, ops.JoinReference):
            return self.trace_relation(rel.parent)

        if isinstance(rel, ops.AliasedRelation):
            return self.trace_relation(rel.parent)

        if isinstance(rel, ops.Project):
            return self._trace_project(rel)

        if isinstance(rel, ops.Aggregate):
            return self._trace_aggregate(rel)

        if isinstance(rel, ops.JoinChain):
            return self._trace_join_chain(rel)

        if isinstance(rel, ops.Filter):
            return self._trace_simple_with_context(rel, rel.predicates, "filter")

        if isinstance(rel, ops.Sort):
            return self._trace_simple_with_context(rel, rel.keys, "order")

        if isinstance(rel, (ops.Limit, ops.Distinct, ops.DropColumns, ops.FillNull, ops.DropNull, ops.Sample)):
            return self._trace_passthrough(rel)

        if isinstance(rel, (ops.Union, ops.Intersection, ops.Difference)):
            return self._trace_set(rel)

        if isinstance(rel, (ops.SQLStringView, ops.SQLQueryResult)):
            return self._trace_opaque_sql(rel)

        if hasattr(rel, "parent") and isinstance(rel.parent, ops.Relation):
            return self._trace_passthrough(rel)

        return self._trace_unknown_relation(rel)

    def _trace_physical_table(self, rel: ops.PhysicalTable) -> RelationDerivation:
        dataset = self._dataset_for_relation(rel)
        columns: dict[str, ColumnDerivation] = {}
        for name in rel.schema.names:
            source = ColumnRef(dataset.key, name)
            columns[name] = ColumnDerivation(
                dependencies=(ColumnDependency(source=source),),
                expression=f"{dataset.key}.{name}",
                transform="identity",
                confidence="exact",
            )
        return RelationDerivation(columns=columns, datasets={dataset.key: dataset})

    def _trace_project(self, rel: ops.Project) -> RelationDerivation:
        parent = self.trace_relation(rel.parent)
        columns = {
            name: self.trace_value(value, transform=self._classify_value(value))
            for name, value in rel.values.items()
        }
        return RelationDerivation(columns=columns, datasets=parent.datasets)

    def _trace_aggregate(self, rel: ops.Aggregate) -> RelationDerivation:
        parent = self.trace_relation(rel.parent)
        group_context = self.trace_values(rel.groups.values(), role="group")
        columns: dict[str, ColumnDerivation] = {}

        for name, value in rel.groups.items():
            columns[name] = self.trace_value(value, transform="group")

        for name, value in rel.metrics.items():
            metric = self.trace_value(value, transform=self._classify_value(value))
            columns[name] = metric.with_context(group_context)

        return RelationDerivation(columns=columns, datasets=parent.datasets)

    def _trace_join_chain(self, rel: ops.JoinChain) -> RelationDerivation:
        datasets: dict[str, DatasetRef] = {}
        for table in rel.tables:
            datasets.update(self.trace_relation(table).datasets)

        join_context = self.trace_values(
            (predicate for link in rel.rest for predicate in link.predicates),
            role="join",
        )
        columns = {
            name: self.trace_value(value, transform=self._classify_value(value)).with_context(join_context)
            for name, value in rel.values.items()
        }
        return RelationDerivation(columns=columns, datasets=datasets)

    def _trace_simple_with_context(
        self,
        rel: ops.Relation,
        context_values: Iterable[ops.Value],
        role: str,
    ) -> RelationDerivation:
        parent = self.trace_relation(rel.parent)
        context = self.trace_values(context_values, role=role)
        columns = {
            name: derivation.with_context(context)
            for name, derivation in parent.columns.items()
            if name in rel.schema
        }
        return RelationDerivation(columns=columns, datasets=parent.datasets)

    def _trace_passthrough(self, rel: ops.Relation) -> RelationDerivation:
        parent = self.trace_relation(rel.parent)
        columns = {name: parent.columns[name] for name in rel.schema.names if name in parent.columns}
        return RelationDerivation(columns=columns, datasets=parent.datasets)

    def _trace_set(self, rel: ops.Set) -> RelationDerivation:
        left = self.trace_relation(rel.left)
        right = self.trace_relation(rel.right)
        transform = type(rel).__name__.lower()
        columns: dict[str, ColumnDerivation] = {}
        for name in rel.schema.names:
            dependencies = []
            if name in left.columns:
                dependencies.extend(left.columns[name].dependencies)
            if name in right.columns:
                dependencies.extend(right.columns[name].dependencies)
            columns[name] = ColumnDerivation(
                dependencies=dedupe_dependencies(dependencies),
                expression=f"{transform}({name})",
                transform=transform,
                confidence=combine_confidence(
                    left.columns.get(name, ColumnDerivation()).confidence,
                    right.columns.get(name, ColumnDerivation()).confidence,
                ),
            )
        return RelationDerivation(columns=columns, datasets={**left.datasets, **right.datasets})

    def _trace_opaque_sql(self, rel: ops.Relation) -> RelationDerivation:
        parent = self.trace_relation(rel.parent) if hasattr(rel, "parent") else RelationDerivation({})
        dependencies = [
            dep.with_role("opaque", "sql")
            for derivation in parent.columns.values()
            for dep in derivation.dependencies
        ]
        columns = {
            name: ColumnDerivation(
                dependencies=dedupe_dependencies(dependencies),
                expression=getattr(rel, "query", ""),
                transform="sql",
                confidence="opaque",
            )
            for name in rel.schema.names
        }
        return RelationDerivation(columns=columns, datasets=parent.datasets)

    def _trace_unknown_relation(self, rel: ops.Relation) -> RelationDerivation:
        dependencies = self.trace_values(rel.find_topmost(ops.Field), role="unknown")
        columns = {
            name: ColumnDerivation(
                dependencies=dependencies,
                expression=type(rel).__name__,
                transform=type(rel).__name__.lower(),
                confidence="partial" if dependencies else "unknown",
            )
            for name in rel.schema.names
        }
        datasets = {
            dataset.key: dataset
            for dep in dependencies
            if (dataset := self._dataset_from_key(dep.source.dataset)) is not None
        }
        return RelationDerivation(columns=columns, datasets=datasets)

    def trace_values(
        self,
        values: Iterable[ops.Value],
        *,
        role: str = "value",
        transform: str | None = None,
    ) -> tuple[ColumnDependency, ...]:
        """Trace dependencies for multiple Ibis value operations.

        Args:
            values: Value operations to inspect.
            role: Dependency role to assign to discovered source columns.
            transform: Optional transform override.

        Returns:
            De-duplicated source column dependencies.
        """

        dependencies = []
        for value in values:
            dependencies.extend(self.trace_value(value, role=role, transform=transform).dependencies)
        return dedupe_dependencies(dependencies)

    def trace_value(
        self,
        value: ops.Value,
        *,
        role: str = "value",
        transform: str | None = None,
    ) -> ColumnDerivation:
        """Trace dependencies for one Ibis value operation.

        Args:
            value: Value operation to inspect.
            role: Dependency role to assign to discovered source columns.
            transform: Optional transform override.

        Returns:
            Column derivation metadata.
        """

        fields = value.find_topmost(ops.Field)
        dependencies: list[ColumnDependency] = []
        for field in fields:
            column = self.trace_column(field.rel, field.name)
            for dependency in column.dependencies:
                dep = dependency
                if role != "value":
                    dep = dep.with_role(role=role, transform=transform or role)
                dependencies.append(dep)

        transform_name = transform or self._classify_value(value)
        confidence = "exact"
        if self._is_opaque_value(value):
            confidence = "partial" if dependencies else "opaque"

        return ColumnDerivation(
            dependencies=dedupe_dependencies(dependencies),
            expression=_safe_expr(value),
            transform=transform_name,
            confidence=confidence,
        )

    def trace_column(self, rel: ops.Relation, name: str) -> ColumnDerivation:
        """Trace the derivation for one relation column.

        Args:
            rel: Relation operation that exposes the column.
            name: Column name.

        Returns:
            Column derivation metadata, or an unknown derivation if unresolved.
        """

        derivation = self.trace_relation(rel)
        return derivation.columns.get(
            name,
            ColumnDerivation(expression=f"{type(rel).__name__}.{name}", confidence="unknown"),
        )

    def _dataset_for_relation(self, rel: ops.PhysicalTable) -> DatasetRef:
        namespace = getattr(rel, "namespace", None)
        catalog = getattr(namespace, "catalog", None)
        database = getattr(namespace, "database", None)
        key_candidates = [
            getattr(rel, "name", None),
            ".".join(part for part in (catalog, database, getattr(rel, "name", None)) if part),
        ]
        for key in key_candidates:
            if key and key in self.registry:
                return self.registry[key]

        source = getattr(rel, "source", None)
        engine = _backend_name(source)
        dataset = DatasetRef(
            name=rel.name,
            engine=engine,
            catalog=catalog,
            database=database,
            schema=_schema_items(rel.schema),
            logical_name=rel.name,
        )
        return self.registry.get(dataset.key, dataset)

    def _dataset_from_key(self, key: str) -> DatasetRef | None:
        return self.registry.get(key)

    def _classify_value(self, value: ops.Value) -> str:
        if isinstance(value, ops.Field):
            return "identity"
        name = type(value).__name__.lower()
        if name == "literal":
            return "literal"
        if name in {"sum", "mean", "max", "min", "count", "countdistinct", "countstar"}:
            return "aggregate"
        if "window" in name:
            return "window"
        if "udf" in name:
            return "udf"
        return "expression"

    def _is_opaque_value(self, value: ops.Value) -> bool:
        name = type(value).__name__.lower()
        return "udf" in name or "sql" in name


def extract_lineage(
    expr: ibis.Expr,
    *,
    target: DatasetRef | None = None,
    registry: Mapping[str, DatasetRef] | None = None,
    job_name: str | None = None,
) -> LineageGraph:
    """Extract lineage for an Ibis expression using a one-shot extractor.

    Args:
        expr: Ibis expression to analyze.
        target: Optional dataset metadata for the materialized output.
        registry: Optional mapping from Ibis table aliases to dataset metadata.
        job_name: Optional job name to attach to graph metadata.

    Returns:
        Extracted column-level lineage graph.
    """

    return IbisLineageExtractor(registry=registry).extract(expr, target=target, job_name=job_name)


def _schema_items(schema: Schema) -> tuple[tuple[str, str], ...]:
    return tuple((name, str(dtype)) for name, dtype in schema.items())


def _backend_name(source: Any) -> str:
    if source is None:
        return "ibis"
    module = type(source).__module__.split(".")
    if "duckdb" in module:
        return "duckdb"
    if "sqlite" in module:
        return "sqlite"
    if "postgres" in module or "psycopg" in module:
        return "postgres"
    if "mysql" in module:
        return "mysql"
    if "polars" in module:
        return "polars"
    if "pyspark" in module or "spark" in module:
        return "spark"
    return type(source).__module__.split(".")[0]


def _safe_expr(value: ops.Value) -> str:
    try:
        return str(value.to_expr())
    except Exception:
        return type(value).__name__
