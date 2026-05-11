from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_schema(schema: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> tuple[tuple[str, str], ...]:
    """Normalize schema-like input into a stable tuple representation.

    Args:
        schema: Mapping or iterable of `(column, dtype)` pairs.

    Returns:
        Tuple of stringified column and dtype pairs.
    """

    items = schema.items() if isinstance(schema, Mapping) else schema
    return tuple((str(name), str(dtype)) for name, dtype in items)


@dataclass(frozen=True)
class DatasetRef:
    """Logical and physical identity for a dataset used in lineage.

    Attributes:
        name: Physical object name or local table name.
        engine: Backend or storage engine that owns the dataset.
        catalog: Optional catalog namespace.
        database: Optional database/schema namespace.
        uri: Optional physical path or URI.
        kind: Physical object kind, such as `table`, `delta`, or `parquet`.
        schema: Ordered column schema.
        logical_name: Stable governance name used for backend-invariant lineage.
    """

    name: str
    engine: str = "ibis"
    catalog: str | None = None
    database: str | None = None
    uri: str | None = None
    kind: str = "table"
    schema: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    logical_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "catalog", _clean(self.catalog))
        object.__setattr__(self, "database", _clean(self.database))
        object.__setattr__(self, "uri", _clean(self.uri))
        object.__setattr__(self, "logical_name", _clean(self.logical_name))
        object.__setattr__(self, "schema", normalize_schema(self.schema))

    @property
    def qualified_name(self) -> str:
        """Return a physical name including catalog/database when available."""

        parts = [self.catalog, self.database, self.name]
        return ".".join(part for part in parts if part)

    @property
    def key(self) -> str:
        """Return the stable dataset key used by graph nodes and edges."""

        return self.logical_name or self.qualified_name

    def to_dict(self) -> dict[str, Any]:
        """Serialize the dataset for JSON artifacts and UI rendering."""

        result = asdict(self)
        result["key"] = self.key
        result["qualified_name"] = self.qualified_name
        result["schema"] = [{"name": name, "dtype": dtype} for name, dtype in self.schema]
        return result


@dataclass(frozen=True)
class ColumnRef:
    """Reference to one column in one lineage dataset."""

    dataset: str
    column: str

    @property
    def key(self) -> str:
        """Return `dataset.column` for display and comparisons."""

        return f"{self.dataset}.{self.column}"

    def to_dict(self) -> dict[str, str]:
        """Serialize the column reference for JSON artifacts and UI rendering."""

        return {"dataset": self.dataset, "column": self.column, "key": self.key}


@dataclass(frozen=True)
class ColumnDependency:
    """Source column dependency for a derived column.

    Attributes:
        source: Upstream source column.
        role: Dependency role, such as `value`, `filter`, `join`, or `group`.
        transform: Transform classification associated with the dependency.
        confidence: Confidence level assigned by the extractor.
    """

    source: ColumnRef
    role: str = "value"
    transform: str = "identity"
    confidence: str = "exact"

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.source.dataset, self.source.column, self.role, self.transform)

    def with_role(self, role: str, transform: str | None = None) -> ColumnDependency:
        """Return a dependency copy with a different context role."""

        return ColumnDependency(
            source=self.source,
            role=role,
            transform=transform or self.transform,
            confidence=self.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the dependency for JSON artifacts and UI rendering."""

        return {
            "source": self.source.to_dict(),
            "role": self.role,
            "transform": self.transform,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ColumnDerivation:
    """Lineage derivation for one relation column inside the extractor."""

    dependencies: tuple[ColumnDependency, ...] = field(default_factory=tuple)
    expression: str = ""
    transform: str = "identity"
    confidence: str = "exact"

    def with_context(self, dependencies: Iterable[ColumnDependency]) -> ColumnDerivation:
        """Return a derivation with filter, join, group, or sort context added."""

        return ColumnDerivation(
            dependencies=dedupe_dependencies((*self.dependencies, *dependencies)),
            expression=self.expression,
            transform=self.transform,
            confidence=combine_confidence(self.confidence, *(d.confidence for d in dependencies)),
        )


@dataclass(frozen=True)
class LineageEdge:
    """Directed column-level dependency edge in a lineage graph."""

    source: ColumnRef
    target: ColumnRef
    role: str
    transform: str
    expression: str
    confidence: str = "exact"
    stage_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the edge for JSON artifacts and UI rendering."""

        return {
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "role": self.role,
            "transform": self.transform,
            "expression": self.expression,
            "confidence": self.confidence,
            "stage_id": self.stage_id,
        }


@dataclass
class LineageGraph:
    """Column-level lineage graph for one or more materialized stages."""

    datasets: dict[str, DatasetRef] = field(default_factory=dict)
    outputs: list[ColumnRef] = field(default_factory=list)
    edges: list[LineageEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    _edge_keys: set[tuple[str, str, str, str, str, str]] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize the internal edge index for pre-populated graphs."""

        self._edge_keys = {_edge_key(edge) for edge in self.edges}

    def add_dataset(self, dataset: DatasetRef) -> DatasetRef:
        """Add or replace a dataset by stable key."""

        self.datasets[dataset.key] = dataset
        return dataset

    def add_output(self, output: ColumnRef) -> None:
        """Register a materialized output column."""

        if output not in self.outputs:
            self.outputs.append(output)

    def add_edge(self, edge: LineageEdge) -> None:
        """Add a lineage edge if an equivalent edge is not already present."""

        key = _edge_key(edge)
        if key not in self._edge_keys:
            self.edges.append(edge)
            self._edge_keys.add(key)

    def dependency_pairs(self, include_roles: bool = True) -> set[tuple[str, ...]]:
        """Return backend-invariant source-target dependency tuples.

        Args:
            include_roles: Include dependency roles in the tuple when true.

        Returns:
            Set of logical dependency pairs, optionally role-qualified.
        """

        pairs: set[tuple[str, ...]] = set()
        for edge in self.edges:
            source = self._logical_column_key(edge.source)
            target = self._logical_column_key(edge.target)
            if include_roles:
                pairs.add((source, target, edge.role))
            else:
                pairs.add((source, target))
        return pairs

    def _logical_column_key(self, column: ColumnRef) -> str:
        dataset = self.datasets.get(column.dataset)
        dataset_name = dataset.logical_name if dataset and dataset.logical_name else column.dataset
        return f"{dataset_name}.{column.column}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph for JSON artifacts and UI rendering."""

        return {
            "datasets": {key: dataset.to_dict() for key, dataset in sorted(self.datasets.items())},
            "outputs": [output.to_dict() for output in self.outputs],
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": self.metadata,
        }


def merge_lineage_graphs(graphs: Iterable[LineageGraph], metadata: Mapping[str, Any] | None = None) -> LineageGraph:
    """Merge independently extracted stage graphs into one lineage graph.

    Args:
        graphs: Stage-level lineage graphs, usually ordered by pipeline stage.
        metadata: Optional metadata to attach to the merged graph.

    Returns:
        A graph containing all datasets, outputs, and de-duplicated edges.
    """

    merged = LineageGraph(metadata=dict(metadata or {}))
    stage_names: list[str] = []
    for graph in graphs:
        if name := graph.metadata.get("job_name"):
            stage_names.append(str(name))
        for dataset in graph.datasets.values():
            merged.add_dataset(dataset)
        for output in graph.outputs:
            merged.add_output(output)
        for edge in graph.edges:
            merged.add_edge(edge)
    if stage_names:
        merged.metadata.setdefault("stages", stage_names)
    return merged


def dedupe_dependencies(dependencies: Iterable[ColumnDependency]) -> tuple[ColumnDependency, ...]:
    """Return dependencies with duplicates removed while preserving order."""

    seen: set[tuple[str, str, str, str]] = set()
    result: list[ColumnDependency] = []
    for dep in dependencies:
        if dep.key not in seen:
            result.append(dep)
            seen.add(dep.key)
    return tuple(result)


def combine_confidence(*values: str) -> str:
    """Return the least confident value from a set of confidence labels."""

    order = {"exact": 0, "partial": 1, "opaque": 2, "unknown": 3}
    if not values:
        return "exact"
    return max(values, key=lambda value: order.get(value, 3))


def _edge_key(edge: LineageEdge) -> tuple[str, str, str, str, str, str]:
    return (
        edge.source.dataset,
        edge.source.column,
        edge.target.dataset,
        edge.target.column,
        edge.role,
        edge.transform,
    )
