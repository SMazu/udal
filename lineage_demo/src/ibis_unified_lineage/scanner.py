from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from ibis_unified_lineage.models import DatasetRef
from ibis_unified_lineage.pipeline import PipelineStage

DEFAULT_INCLUDE_GLOBS = ("**/*.py",)
DEFAULT_EXCLUDE_GLOBS = (
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/.venv/**",
    "**/venv/**",
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
)
DEFAULT_CONVENTIONS = {
    "stage_collection_names": ("LINEAGE_STAGES", "PIPELINE_STAGES", "STAGES"),
    "job_collection_names": ("LINEAGE_JOBS",),
    "stage_id_names": ("LINEAGE_STAGE_ID", "STAGE_ID"),
    "input_names": ("LINEAGE_INPUTS", "INPUTS"),
    "target_names": ("LINEAGE_TARGET", "TARGET"),
    "builder_names": ("LINEAGE_BUILDER", "build_lineage", "build_job", "build"),
}


@dataclass(frozen=True)
class PipelineScanDiagnostic:
    """Structured diagnostic emitted while scanning Python projects.

    Attributes:
        path: File that produced the diagnostic.
        code: Stable machine-readable diagnostic code.
        message: Human-readable description.
        severity: `info`, `warning`, or `error`.
    """

    path: str
    code: str
    message: str
    severity: str = "warning"

    def to_dict(self) -> dict[str, str]:
        """Serialize the diagnostic for reports and JSON artifacts."""

        return {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class PipelineScanSkippedFile:
    """Record describing a Python file ignored by the scanner."""

    path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        """Serialize the skipped-file record."""

        return {"path": self.path, "reason": self.reason}


@dataclass(frozen=True)
class PipelineScanResult:
    """Result of scanning one or more Python roots for lineage stages."""

    stages: tuple[PipelineStage, ...] = field(default_factory=tuple)
    skipped_files: tuple[PipelineScanSkippedFile, ...] = field(default_factory=tuple)
    diagnostics: tuple[PipelineScanDiagnostic, ...] = field(default_factory=tuple)
    duplicate_target_conflicts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    unresolved_input_datasets: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the scan result for logs or governance artifacts."""

        return {
            "stages": [stage.to_dict() for stage in self.stages],
            "skipped_files": [skipped.to_dict() for skipped in self.skipped_files],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "duplicate_target_conflicts": list(self.duplicate_target_conflicts),
            "unresolved_input_datasets": list(self.unresolved_input_datasets),
        }


def scan_ibis_project(
    root_paths: str | Path | Iterable[str | Path],
    *,
    include_globs: Iterable[str] | None = None,
    exclude_globs: Iterable[str] | None = None,
    conventions: Mapping[str, Iterable[str]] | None = None,
) -> PipelineScanResult:
    """Discover pipeline stages from Python modules in one or more roots.

    Args:
        root_paths: File or directory paths to scan.
        include_globs: Glob patterns relative to each directory root. Defaults
            to every Python file.
        exclude_globs: Glob patterns to ignore. Defaults to common generated
            and virtualenv directories.
        conventions: Optional names for module-level stage declarations,
            builder metadata, and job collections.

    Returns:
        A scan result containing discovered stages and structured diagnostics.
    """

    roots = _normalize_roots(root_paths)
    includes = tuple(include_globs or DEFAULT_INCLUDE_GLOBS)
    excludes = tuple(exclude_globs or DEFAULT_EXCLUDE_GLOBS)
    resolved_conventions = _merge_conventions(conventions)

    stages: list[PipelineStage] = []
    skipped_files: list[PipelineScanSkippedFile] = []
    diagnostics: list[PipelineScanDiagnostic] = []
    import_roots = _import_roots(roots)

    for root, path in _iter_python_files(roots, includes, excludes):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except OSError as exc:
            diagnostics.append(_diagnostic(path, "read_error", str(exc), "error"))
            continue
        except SyntaxError as exc:
            diagnostics.append(_diagnostic(path, "syntax_error", str(exc), "error"))
            continue

        if not _looks_like_lineage_module(tree, source, resolved_conventions):
            skipped_files.append(PipelineScanSkippedFile(str(path), "no_supported_lineage_convention"))
            continue

        module = _import_module(path, import_roots, diagnostics)
        if module is None:
            continue
        stages.extend(_stages_from_module(module, path, resolved_conventions, diagnostics))

    duplicate_target_conflicts = _duplicate_target_conflicts(stages)
    unresolved_input_datasets = _unresolved_input_datasets(stages)
    return PipelineScanResult(
        stages=tuple(stages),
        skipped_files=tuple(skipped_files),
        diagnostics=tuple(diagnostics),
        duplicate_target_conflicts=tuple(duplicate_target_conflicts),
        unresolved_input_datasets=tuple(unresolved_input_datasets),
    )


def _normalize_roots(root_paths: str | Path | Iterable[str | Path]) -> tuple[Path, ...]:
    if isinstance(root_paths, (str, Path)):
        items: Iterable[str | Path] = (root_paths,)
    else:
        items = root_paths
    return tuple(Path(item).resolve() for item in items)


def _import_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        import_root = root.parent if root.is_file() else root
        if import_root not in seen:
            result.append(import_root)
            seen.add(import_root)
    return tuple(result)


def _merge_conventions(conventions: Mapping[str, Iterable[str]] | None) -> dict[str, tuple[str, ...]]:
    result = {key: tuple(value) for key, value in DEFAULT_CONVENTIONS.items()}
    for key, value in (conventions or {}).items():
        result[key] = tuple(value)
    return result


def _iter_python_files(
    roots: Iterable[Path],
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
) -> Iterable[tuple[Path, Path]]:
    for root in roots:
        if root.is_file():
            if root.suffix == ".py":
                yield root.parent, root
            continue
        for include in include_globs:
            for path in sorted(root.glob(include)):
                if path.is_file() and not _excluded(path, root, exclude_globs):
                    yield root, path


def _excluded(path: Path, root: Path, exclude_globs: tuple[str, ...]) -> bool:
    relative = path.relative_to(root)
    return any(relative.match(pattern) for pattern in exclude_globs)


def _looks_like_lineage_module(
    tree: ast.AST,
    source: str,
    conventions: Mapping[str, tuple[str, ...]],
) -> bool:
    known_names = {
        name
        for values in conventions.values()
        for name in values
    }
    if "PipelineStage" in source or "ibis_unified_lineage" in source:
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in known_names:
            return True
        if isinstance(node, ast.Attribute) and node.attr in known_names:
            return True
    return False


def _import_module(path: Path, import_roots: tuple[Path, ...], diagnostics: list[PipelineScanDiagnostic]) -> ModuleType | None:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
    module_name = f"_ibis_unified_lineage_scan_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        diagnostics.append(_diagnostic(path, "import_spec_error", "Could not create import spec", "error"))
        return None

    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    sys.path[:0] = [str(root) for root in import_roots]
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - exact exception type is user-code dependent.
        diagnostics.append(_diagnostic(path, "import_error", f"{type(exc).__name__}: {exc}", "error"))
        return None
    finally:
        sys.path[:] = old_path
        sys.modules.pop(module_name, None)
    return module


def _stages_from_module(
    module: ModuleType,
    path: Path,
    conventions: Mapping[str, tuple[str, ...]],
    diagnostics: list[PipelineScanDiagnostic],
) -> list[PipelineStage]:
    stages: list[PipelineStage] = []
    seen_objects: set[int] = set()

    for value in vars(module).values():
        if isinstance(value, PipelineStage):
            _append_stage(value, stages, seen_objects)
        elif isinstance(value, (list, tuple)) and value and all(isinstance(item, PipelineStage) for item in value):
            for item in value:
                _append_stage(item, stages, seen_objects)

    for name in conventions["stage_collection_names"]:
        value = getattr(module, name, None)
        if isinstance(value, (list, tuple)):
            invalid = [type(item).__name__ for item in value if not isinstance(item, PipelineStage)]
            if invalid:
                diagnostics.append(
                    _diagnostic(path, "ambiguous_stage_collection", f"{name} contains non-PipelineStage values: {invalid}")
                )

    for name in conventions["job_collection_names"]:
        value = getattr(module, name, None)
        if isinstance(value, (list, tuple)):
            for index, spec in enumerate(value):
                stage = _stage_from_spec(spec, path, diagnostics, default_stage_id=f"{path.stem}_{index}")
                if stage is not None:
                    _append_stage(stage, stages, seen_objects)
        elif value is not None:
            diagnostics.append(_diagnostic(path, "invalid_job_collection", f"{name} must be a list or tuple"))

    convention_stage = _stage_from_module_convention(module, path, conventions, diagnostics)
    if convention_stage is not None:
        _append_stage(convention_stage, stages, seen_objects)

    if not stages:
        diagnostics.append(
            _diagnostic(path, "no_stage_discovered", "File matched lineage markers but no supported stage declaration was found")
        )
    return stages


def _append_stage(stage: PipelineStage, stages: list[PipelineStage], seen_objects: set[int]) -> None:
    if id(stage) in seen_objects:
        return
    stages.append(stage)
    seen_objects.add(id(stage))


def _stage_from_module_convention(
    module: ModuleType,
    path: Path,
    conventions: Mapping[str, tuple[str, ...]],
    diagnostics: list[PipelineScanDiagnostic],
) -> PipelineStage | None:
    inputs = _first_attr(module, conventions["input_names"])
    target = _first_attr(module, conventions["target_names"])
    builder = _first_attr(module, conventions["builder_names"])
    if inputs is None and target is None and builder is None:
        return None
    stage_id = _first_attr(module, conventions["stage_id_names"]) or path.stem
    return _build_stage(
        {"stage_id": stage_id, "inputs": inputs, "target": target, "builder": builder},
        path,
        diagnostics,
        default_stage_id=str(stage_id),
    )


def _stage_from_spec(
    spec: Any,
    path: Path,
    diagnostics: list[PipelineScanDiagnostic],
    *,
    default_stage_id: str,
) -> PipelineStage | None:
    if isinstance(spec, PipelineStage):
        return spec
    if not isinstance(spec, Mapping):
        diagnostics.append(_diagnostic(path, "invalid_job_spec", f"Job spec must be a mapping, got {type(spec).__name__}"))
        return None
    return _build_stage(spec, path, diagnostics, default_stage_id=default_stage_id)


def _build_stage(
    spec: Mapping[str, Any],
    path: Path,
    diagnostics: list[PipelineScanDiagnostic],
    *,
    default_stage_id: str,
) -> PipelineStage | None:
    stage_id = spec.get("stage_id") or spec.get("name") or default_stage_id
    inputs = spec.get("inputs")
    target = spec.get("target")
    builder = spec.get("builder")
    metadata = spec.get("metadata")

    if not isinstance(inputs, Mapping) or not all(isinstance(item, DatasetRef) for item in inputs.values()):
        diagnostics.append(_diagnostic(path, "invalid_stage_inputs", f"Stage {stage_id!r} inputs must map aliases to DatasetRef"))
        return None
    if not isinstance(target, DatasetRef):
        diagnostics.append(_diagnostic(path, "invalid_stage_target", f"Stage {stage_id!r} target must be a DatasetRef"))
        return None
    if not callable(builder):
        diagnostics.append(_diagnostic(path, "invalid_stage_builder", f"Stage {stage_id!r} builder must be callable"))
        return None
    try:
        return PipelineStage(
            stage_id=str(stage_id),
            inputs=inputs,
            target=target,
            builder=builder,
            metadata=metadata if isinstance(metadata, Mapping) else None,
        )
    except (TypeError, ValueError) as exc:
        diagnostics.append(_diagnostic(path, "invalid_pipeline_stage", str(exc)))
        return None


def _first_attr(module: ModuleType, names: Iterable[str]) -> Any:
    for name in names:
        if hasattr(module, name):
            return getattr(module, name)
    return None


def _duplicate_target_conflicts(stages: Iterable[PipelineStage]) -> list[dict[str, Any]]:
    target_to_stages: dict[str, list[str]] = defaultdict(list)
    for stage in stages:
        target_to_stages[stage.target.key].append(stage.stage_id)
    return [
        {"target": target, "stage_ids": stage_ids}
        for target, stage_ids in sorted(target_to_stages.items())
        if len(stage_ids) > 1
    ]


def _unresolved_input_datasets(stages: Iterable[PipelineStage]) -> list[dict[str, Any]]:
    stage_list = list(stages)
    produced_targets = {stage.target.key for stage in stage_list}
    unresolved: list[dict[str, Any]] = []
    for stage in stage_list:
        for alias, dataset in sorted(stage.inputs.items()):
            if dataset.schema or dataset.key in produced_targets:
                continue
            unresolved.append(
                {
                    "stage_id": stage.stage_id,
                    "input_alias": alias,
                    "dataset": dataset.to_dict(),
                    "reason": "input is neither produced by a discovered stage nor schema-bearing raw metadata",
                }
            )
    return unresolved


def _diagnostic(
    path: Path,
    code: str,
    message: str,
    severity: str = "warning",
) -> PipelineScanDiagnostic:
    return PipelineScanDiagnostic(path=str(path), code=code, message=message, severity=severity)
