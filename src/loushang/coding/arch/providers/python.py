"""Python AST provider for the language-neutral import graph contract."""

from __future__ import annotations

import ast
import fnmatch
import io
import os
import tokenize
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.arch.cache import (
    CachedImportFile,
    ImportFactCache,
    ImportFactCacheNamespace,
    ImportFactCacheSnapshot,
    ImportFileFingerprint,
    fingerprint_source,
    import_cache_root_id,
)
from loushang.coding.arch.model import (
    ArchitectureDiagnostic,
    ImportCacheStats,
    ImportCategory,
    ImportDependencyFact,
    ImportKind,
    ImportModuleFact,
    ImportProviderScan,
    SourceEvidence,
)

PYTHON_IMPORT_PROVIDER_VERSION = 1

_DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)


@dataclass(frozen=True)
class _PythonSourceFile:
    path: Path
    relative_path: str
    module: str
    is_package: bool


class PythonImportGraphProvider:
    """Extract Python import dependencies without importing project code."""

    language = "python"

    def supports(self, root: Path) -> bool:
        if not root.is_dir():
            return False
        return any(_iter_python_files(root, ()))

    def scan(
        self,
        root: Path,
        *,
        package_prefix: str | None = None,
        excludes: tuple[str, ...] = (),
        cache: ImportFactCache | None = None,
        refresh_cache: bool = False,
    ) -> ImportProviderScan:
        resolved_root = root.resolve()
        if not resolved_root.is_dir():
            raise ValueError(f"import graph root is not a directory: {root}")
        prefix = _normalize_package_prefix(resolved_root, package_prefix)
        discovery_diagnostics: list[ArchitectureDiagnostic] = []
        module_index: list[tuple[str, str | None]] = []
        sources_by_module: dict[str, _PythonSourceFile] = {}

        for path in _iter_python_files(resolved_root, excludes):
            relative_path = path.relative_to(resolved_root).as_posix()
            module = _module_name(relative_path, prefix)
            module_index.append((relative_path, module))
            if module is None:
                discovery_diagnostics.append(
                    ArchitectureDiagnostic(
                        code="invalid_python_module_path",
                        message="Python source path cannot be represented as a module name.",
                        path=relative_path,
                    )
                )
                continue
            candidate = _PythonSourceFile(
                path=path,
                relative_path=relative_path,
                module=module,
                is_package=path.name == "__init__.py",
            )
            existing = sources_by_module.get(module)
            if existing is not None:
                discovery_diagnostics.append(
                    _duplicate_module_diagnostic(existing, candidate)
                )
                continue
            sources_by_module[module] = candidate

        normalized_module_index = tuple(sorted(module_index))
        namespace = ImportFactCacheNamespace(
            root_id=import_cache_root_id(resolved_root),
            language=self.language,
            provider_version=PYTHON_IMPORT_PROVIDER_VERSION,
            package_prefix=prefix,
        )
        cached_snapshot = cache.load(namespace) if cache is not None else None
        cache_error = cache.last_error if cache is not None else None
        cached_entries = (
            {}
            if refresh_cache
            or cached_snapshot is None
            or cached_snapshot.module_index != normalized_module_index
            else cached_snapshot.entry_map()
        )
        invalidated = (
            len(cached_snapshot.entries)
            if cached_snapshot is not None and not cached_entries
            else 0
        )

        module_names = frozenset(sources_by_module)
        current_entries: dict[str, CachedImportFile] = {}
        hits = 0
        misses = 0
        for module in sorted(sources_by_module):
            source_file = sources_by_module[module]
            try:
                content = source_file.path.read_bytes()
            except OSError as exc:
                misses += 1
                discovery_diagnostics.append(
                    ArchitectureDiagnostic(
                        code="unreadable_python_source",
                        message=str(exc),
                        severity="error",
                        path=source_file.relative_path,
                    )
                )
                continue
            fingerprint = fingerprint_source(content)
            cached = cached_entries.get(source_file.relative_path)
            if cached is not None and _cached_entry_matches(
                cached,
                source_file=source_file,
                fingerprint=fingerprint,
            ):
                entry = cached
                hits += 1
            else:
                if cached is not None:
                    invalidated += 1
                entry = _analyze_python_file(
                    source_file,
                    content=content,
                    fingerprint=fingerprint,
                    module_names=module_names,
                )
                misses += 1
            current_entries[source_file.relative_path] = entry

        if cache is not None:
            cache.replace(
                ImportFactCacheSnapshot(
                    namespace=namespace,
                    module_index=normalized_module_index,
                    entries=tuple(sorted(current_entries.items())),
                )
            )
            cache_error = cache.last_error or cache_error

        modules: list[ImportModuleFact] = []
        dependencies: list[ImportDependencyFact] = []
        diagnostics = discovery_diagnostics
        for entry in current_entries.values():
            if entry.module is not None:
                modules.append(entry.module)
            dependencies.extend(entry.dependencies)
            diagnostics.extend(entry.diagnostics)

        return ImportProviderScan(
            language=self.language,
            modules=tuple(sorted(modules, key=lambda item: item.module)),
            dependencies=tuple(sorted(dependencies, key=_dependency_sort_key)),
            package_prefix=prefix,
            diagnostics=tuple(sorted(diagnostics, key=_diagnostic_sort_key)),
            cache_stats=ImportCacheStats(
                enabled=cache is not None,
                hits=hits,
                misses=misses,
                invalidated=invalidated,
                entries=len(current_entries) if cache is not None else 0,
                error=cache_error,
            ),
        )


def _analyze_python_file(
    source_file: _PythonSourceFile,
    *,
    content: bytes,
    fingerprint: ImportFileFingerprint,
    module_names: frozenset[str],
) -> CachedImportFile:
    fact = ImportModuleFact(
        module=source_file.module,
        path=source_file.relative_path,
        language="python",
        is_package=source_file.is_package,
    )
    try:
        buffer = io.BytesIO(content)
        encoding, _ = tokenize.detect_encoding(buffer.readline)
        source = content.decode(encoding)
    except (LookupError, SyntaxError, UnicodeError) as exc:
        return CachedImportFile(
            fingerprint=fingerprint,
            module=None,
            diagnostics=(
                ArchitectureDiagnostic(
                    code="unreadable_python_source",
                    message=str(exc),
                    severity="error",
                    path=source_file.relative_path,
                ),
            ),
        )

    try:
        tree = ast.parse(source, filename=source_file.relative_path)
    except SyntaxError as exc:
        return CachedImportFile(
            fingerprint=fingerprint,
            module=fact,
            diagnostics=(
                ArchitectureDiagnostic(
                    code="python_syntax_error",
                    message=exc.msg,
                    severity="error",
                    path=source_file.relative_path,
                    line=exc.lineno,
                ),
            ),
        )

    visitor = _PythonImportVisitor(
        module=fact,
        module_names=module_names,
        source=source,
    )
    visitor.visit(tree)
    return CachedImportFile(
        fingerprint=fingerprint,
        module=fact,
        dependencies=tuple(sorted(visitor.dependencies, key=_dependency_sort_key)),
        diagnostics=tuple(sorted(visitor.diagnostics, key=_diagnostic_sort_key)),
    )


def _cached_entry_matches(
    entry: CachedImportFile,
    *,
    source_file: _PythonSourceFile,
    fingerprint: ImportFileFingerprint,
) -> bool:
    if entry.fingerprint != fingerprint:
        return False
    if entry.module is None:
        return (
            not entry.dependencies
            and bool(entry.diagnostics)
            and all(
                diagnostic.code == "unreadable_python_source"
                and diagnostic.severity == "error"
                and diagnostic.path == source_file.relative_path
                for diagnostic in entry.diagnostics
            )
        )
    expected_module = ImportModuleFact(
        module=source_file.module,
        path=source_file.relative_path,
        language="python",
        is_package=source_file.is_package,
    )
    return (
        entry.module == expected_module
        and all(
            dependency.source == source_file.module
            and dependency.evidence.path == source_file.relative_path
            for dependency in entry.dependencies
        )
        and all(
            diagnostic.path in {None, source_file.relative_path}
            for diagnostic in entry.diagnostics
        )
    )


class _PythonImportVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        module: ImportModuleFact,
        module_names: frozenset[str],
        source: str,
    ) -> None:
        self.module = module
        self.module_names = module_names
        self.source = source
        self._source_lines = source.splitlines(keepends=True)
        self.dependencies: list[ImportDependencyFact] = []
        self.diagnostics: list[ArchitectureDiagnostic] = []
        self._function_depth = 0
        self._typing_depth = 0
        self._lazy_export_depth = 0

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name, node=node, kind="import")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = self._resolve_from_base(node)
        if base is None:
            return
        for alias in node.names:
            target = base
            if alias.name != "*":
                candidate = f"{base}.{alias.name}" if base else alias.name
                if candidate in self.module_names:
                    target = candidate
            if target:
                self._record(target, node=node, kind="from_import")

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        if _is_type_checking_test(node.test):
            self._typing_depth += 1
            for statement in node.body:
                self.visit(statement)
            self._typing_depth -= 1
            for statement in node.orelse:
                self.visit(statement)
            return
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        target = _dynamic_import_target(node)
        if target:
            resolved = self._resolve_dynamic_target(target)
            if resolved:
                self._record(resolved, node=node, kind="dynamic_import")
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        for type_parameter in getattr(node, "type_params", ()):
            self.visit(type_parameter)

        is_lazy_export = self._function_depth == 0 and node.name == "__getattr__"
        self._function_depth += 1
        if is_lazy_export:
            self._lazy_export_depth += 1
        for statement in node.body:
            self.visit(statement)
        if is_lazy_export:
            self._lazy_export_depth -= 1
        self._function_depth -= 1

    def _resolve_from_base(self, node: ast.ImportFrom) -> str | None:
        if node.level == 0:
            return node.module or ""
        package = (
            self.module.module
            if self.module.is_package
            else self.module.module.rpartition(".")[0]
        )
        parts = package.split(".") if package else []
        parents_to_remove = node.level - 1
        if parents_to_remove and parents_to_remove >= len(parts):
            self.diagnostics.append(
                ArchitectureDiagnostic(
                    code="invalid_relative_import",
                    message="Relative import escapes the discovered package root.",
                    path=self.module.path,
                    line=node.lineno,
                )
            )
            return None
        base_parts = parts[: len(parts) - parents_to_remove]
        if node.module:
            base_parts.extend(node.module.split("."))
        return ".".join(base_parts)

    def _resolve_dynamic_target(self, target: str) -> str | None:
        if not target.startswith("."):
            return target
        level = len(target) - len(target.lstrip("."))
        remainder = target[level:]
        package = (
            self.module.module
            if self.module.is_package
            else self.module.module.rpartition(".")[0]
        )
        parts = package.split(".") if package else []
        parents_to_remove = level - 1
        if parents_to_remove and parents_to_remove >= len(parts):
            return None
        resolved = parts[: len(parts) - parents_to_remove]
        if remainder:
            resolved.extend(remainder.split("."))
        return ".".join(resolved)

    def _record(
        self,
        target: str,
        *,
        node: ast.AST,
        kind: ImportKind,
    ) -> None:
        category = self._category()
        is_reexport = category == "lazy_export" or (
            self.module.is_package and target.startswith(f"{self.module.module}.")
        )
        statement = self._source_segment(node)
        self.dependencies.append(
            ImportDependencyFact(
                source=self.module.module,
                target=target,
                category=category,
                kind=kind,
                evidence=SourceEvidence(
                    path=self.module.path,
                    line=getattr(node, "lineno", 1),
                    column=getattr(node, "col_offset", 0) + 1,
                    statement=" ".join(statement.split()),
                ),
                is_reexport=is_reexport,
            )
        )

    def _source_segment(self, node: ast.AST) -> str:
        start_line = getattr(node, "lineno", 0)
        end_line = getattr(node, "end_lineno", start_line)
        if start_line < 1 or end_line < start_line:
            return ""
        if end_line > len(self._source_lines):
            return ""
        start_column = getattr(node, "col_offset", 0)
        end_column = getattr(node, "end_col_offset", None)
        selected = self._source_lines[start_line - 1 : end_line]
        if not selected:
            return ""
        selected[0] = _slice_utf8(selected[0], start_column, None)
        if end_column is not None:
            selected[-1] = _slice_utf8(selected[-1], 0, end_column)
        return "".join(selected)

    def _category(self) -> ImportCategory:
        if self._typing_depth:
            return "typing"
        if self._lazy_export_depth:
            return "lazy_export"
        if self._function_depth:
            return "deferred"
        return "eager"


def _duplicate_module_diagnostic(
    existing: _PythonSourceFile,
    candidate: _PythonSourceFile,
) -> ArchitectureDiagnostic:
    return ArchitectureDiagnostic(
        code="duplicate_python_module",
        message=(
            f"Module {candidate.module!r} is provided by both "
            f"{existing.relative_path!r} and {candidate.relative_path!r}; "
            "the first path was retained."
        ),
        severity="error",
        path=candidate.relative_path,
    )


def _iter_python_files(root: Path, excludes: tuple[str, ...]):
    for directory, names, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        relative_directory = current.relative_to(root)
        names[:] = sorted(
            name
            for name in names
            if not (current / name).is_symlink()
            and not _is_excluded((relative_directory / name).as_posix(), name, excludes)
        )
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            candidate = current / filename
            if candidate.is_symlink():
                continue
            relative = (relative_directory / filename).as_posix()
            if _matches_exclude(relative, excludes):
                continue
            yield candidate


def _is_excluded(relative: str, name: str, excludes: tuple[str, ...]) -> bool:
    return name in _DEFAULT_EXCLUDED_DIRECTORIES or _matches_exclude(relative, excludes)


def _matches_exclude(relative: str, excludes: tuple[str, ...]) -> bool:
    normalized = relative.removeprefix("./")
    return any(
        fnmatch.fnmatchcase(normalized, pattern.removeprefix("./"))
        or fnmatch.fnmatchcase(f"{normalized}/", pattern.removeprefix("./"))
        for pattern in excludes
        if pattern
    )


def _normalize_package_prefix(root: Path, value: str | None) -> str | None:
    if value is None:
        value = root.name if (root / "__init__.py").is_file() else None
    if value is None:
        return None
    normalized = value.strip().strip(".")
    if not normalized:
        return None
    if any(not part.isidentifier() for part in normalized.split(".")):
        raise ValueError(f"invalid Python package prefix: {value!r}")
    return normalized


def _module_name(relative_path: str, prefix: str | None) -> str | None:
    parts = list(Path(relative_path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if any(not part.isidentifier() for part in parts):
        return None
    if prefix:
        parts = [*prefix.split("."), *parts]
    if not parts:
        return prefix
    return ".".join(parts)


def _is_type_checking_test(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "TYPE_CHECKING"
        and isinstance(node.value, ast.Name)
        and node.value.id in {"typing", "typing_extensions"}
    )


def _dynamic_import_target(node: ast.Call) -> str | None:
    is_builtin_import = isinstance(node.func, ast.Name) and node.func.id == "__import__"
    is_importlib_call = (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "importlib"
    )
    if not (is_builtin_import or is_importlib_call) or not node.args:
        return None
    value = node.args[0]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _slice_utf8(value: str, start: int, end: int | None) -> str:
    return value.encode("utf-8")[start:end].decode("utf-8", errors="replace")


def _dependency_sort_key(
    dependency: ImportDependencyFact,
) -> tuple[object, ...]:
    evidence = dependency.evidence
    return (
        dependency.source,
        dependency.target,
        dependency.category,
        dependency.kind,
        evidence.path,
        evidence.line,
        evidence.column,
    )


def _diagnostic_sort_key(
    diagnostic: ArchitectureDiagnostic,
) -> tuple[object, ...]:
    return (
        diagnostic.path or "",
        diagnostic.line or 0,
        diagnostic.code,
        diagnostic.message,
    )


__all__ = ["PYTHON_IMPORT_PROVIDER_VERSION", "PythonImportGraphProvider"]
