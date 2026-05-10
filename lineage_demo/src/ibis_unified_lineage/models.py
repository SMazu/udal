from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_schema(schema: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> tuple[tuple[str, str], ...]:
    items = schema.items() if isinstance(schema, Mapping) else schema
    return tuple((str(name), str(dtype)) for name, dtype in items)


@dataclass(frozen=True)
class DatasetRef:
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
        parts = [self.catalog, self.database, self.name]
        return ".".join(part for part in parts if part)

    @property
    def key(self) -> str:
        return self.logical_name or self.qualified_name

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["key"] = self.key
        result["qualified_name"] = self.qualified_name
        result["schema"] = [{"name": name, "dtype": dtype} for name, dtype in self.schema]
        return result


@dataclass(frozen=True)
class ColumnRef:
    dataset: str
    column: str

    @property
    def key(self) -> str:
        return f"{self.dataset}.{self.column}"

    def to_dict(self) -> dict[str, str]:
        return {"dataset": self.dataset, "column": self.column, "key": self.key}


@dataclass(frozen=True)
class ColumnDependency:
    source: ColumnRef
    role: str = "value"
    transform: str = "identity"
    confidence: str = "exact"

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.source.dataset, self.source.column, self.role, self.transform)

    def with_role(self, role: str, transform: str | None = None) -> ColumnDependency:
        return ColumnDependency(
            source=self.source,
            role=role,
            transform=transform or self.transform,
            confidence=self.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "role": self.role,
            "transform": self.transform,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ColumnDerivation:
    dependencies: tuple[ColumnDependency, ...] = field(default_factory=tuple)
    expression: str = ""
    transform: str = "identity"
    confidence: str = "exact"

    def with_context(self, dependencies: Iterable[ColumnDependency]) -> ColumnDerivation:
        return ColumnDerivation(
            dependencies=dedupe_dependencies((*self.dependencies, *dependencies)),
            expression=self.expression,
            transform=self.transform,
            confidence=combine_confidence(self.confidence, *(d.confidence for d in dependencies)),
        )


@dataclass(frozen=True)
class LineageEdge:
    source: ColumnRef
    target: ColumnRef
    role: str
    transform: str
    expression: str
    confidence: str = "exact"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "role": self.role,
            "transform": self.transform,
            "expression": self.expression,
            "confidence": self.confidence,
        }


@dataclass
class LineageGraph:
    datasets: dict[str, DatasetRef] = field(default_factory=dict)
    outputs: list[ColumnRef] = field(default_factory=list)
    edges: list[LineageEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_dataset(self, dataset: DatasetRef) -> DatasetRef:
        self.datasets[dataset.key] = dataset
        return dataset

    def add_output(self, output: ColumnRef) -> None:
        if output not in self.outputs:
            self.outputs.append(output)

    def add_edge(self, edge: LineageEdge) -> None:
        key = (
            edge.source.dataset,
            edge.source.column,
            edge.target.dataset,
            edge.target.column,
            edge.role,
            edge.transform,
        )
        existing = {
            (
                item.source.dataset,
                item.source.column,
                item.target.dataset,
                item.target.column,
                item.role,
                item.transform,
            )
            for item in self.edges
        }
        if key not in existing:
            self.edges.append(edge)

    def dependency_pairs(self, include_roles: bool = True) -> set[tuple[str, ...]]:
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
        return {
            "datasets": {key: dataset.to_dict() for key, dataset in sorted(self.datasets.items())},
            "outputs": [output.to_dict() for output in self.outputs],
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": self.metadata,
        }


def dedupe_dependencies(dependencies: Iterable[ColumnDependency]) -> tuple[ColumnDependency, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[ColumnDependency] = []
    for dep in dependencies:
        if dep.key not in seen:
            result.append(dep)
            seen.add(dep.key)
    return tuple(result)


def combine_confidence(*values: str) -> str:
    order = {"exact": 0, "partial": 1, "opaque": 2, "unknown": 3}
    if not values:
        return "exact"
    return max(values, key=lambda value: order.get(value, 3))
