"""Verified source loading with direct-import checks for host-equivalent Plugins."""

from __future__ import annotations

import builtins
import dis
import importlib.util
import inspect
import sys
import sysconfig
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidence,
    InstalledPythonDistributionEvidenceResolver,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_python_path,
    canonical_plugin_symbol,
)
from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle


@dataclass(frozen=True, slots=True)
class VerifiedPluginPythonModule:
    """One module evaluated from a verified revision under a locked import policy."""

    module_name: str
    _module: ModuleType = field(repr=False, compare=False)

    def resolve(self, symbol: str) -> object:
        value: object = self._module
        for part in canonical_plugin_symbol(symbol).split("."):
            value = getattr(value, part)
        return value


def load_verified_plugin_python_module(
    *,
    revision_handle: VerifiedRevisionHandle,
    dependency_lock: PluginDependencyClosureLock,
    relative_path: str,
    module_name: str,
    host_api_prefixes: tuple[str, ...],
    host_api_exports: Mapping[str, tuple[str, ...]] | None = None,
    distribution_evidence_resolver: InstalledPythonDistributionEvidenceResolver
    | None = None,
) -> VerifiedPluginPythonModule:
    """Compile one verified source file with non-sandbox direct-import checks."""

    if not isinstance(revision_handle, VerifiedRevisionHandle):
        raise TypeError("Plugin Python loader requires a verified revision handle")
    if not isinstance(dependency_lock, PluginDependencyClosureLock):
        raise TypeError("Plugin Python loader requires a dependency closure lock")
    if revision_handle.content_digest != dependency_lock.package_content_digest:
        raise ValueError("Plugin Python loader package and dependency lock differ")
    normalized_module_name = _require_nonempty(module_name, name="module name")
    prefixes = tuple(
        _require_nonempty(item, name="Host API prefix") for item in host_api_prefixes
    )
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("Host API prefixes must be unique")
    exports: dict[str, frozenset[str]] = {}
    for raw_module, raw_names in (host_api_exports or {}).items():
        host_module = _require_nonempty(raw_module, name="Host API module")
        names = tuple(
            _require_nonempty(item, name="Host API export") for item in raw_names
        )
        if not names or len(names) != len(set(names)):
            raise ValueError("Host API exports must be nonempty and unique")
        if "*" in names:
            raise ValueError("Host API wildcard exports are unavailable")
        exports[host_module] = frozenset(names)

    path = canonical_plugin_python_path(relative_path)
    revision_handle.verify()
    with revision_handle.open_file(path) as stream:
        source = stream.read()
    import_policy = _DirectImportPolicy(
        dependency_lock,
        host_api_prefixes=prefixes,
        host_api_exports=exports,
        distribution_evidence_resolver=(
            distribution_evidence_resolver
            or InstalledPythonDistributionEvidenceResolver()
        ),
    )
    module = ModuleType(normalized_module_name)
    virtual_filename = f"<plugin:{normalized_module_name}>"
    module.__dict__.update(
        {
            "__builtins__": import_policy.builtins,
            "__file__": virtual_filename,
            "__package__": "",
        }
    )
    code = compile(source, virtual_filename, "exec", dont_inherit=True)
    exec(code, module.__dict__)
    return VerifiedPluginPythonModule(
        module_name=normalized_module_name,
        _module=module,
    )


class _DirectImportPolicy:
    def __init__(
        self,
        dependency_lock: PluginDependencyClosureLock,
        *,
        host_api_prefixes: tuple[str, ...],
        host_api_exports: Mapping[str, frozenset[str]],
        distribution_evidence_resolver: InstalledPythonDistributionEvidenceResolver,
    ) -> None:
        evidence_by_package: dict[
            str,
            list[InstalledPythonDistributionEvidence],
        ] = {}
        for distribution in dependency_lock.python_distributions:
            for evidence in distribution_evidence_resolver.resolve_all(distribution):
                for package in evidence.top_level_packages:
                    evidence_by_package.setdefault(package, []).append(evidence)
        self._distribution_evidence = {
            package: tuple(items) for package, items in evidence_by_package.items()
        }
        self._host_api_prefixes = host_api_prefixes
        self._host_api_exports = dict(host_api_exports)
        self._stdlib_roots = tuple(
            {
                Path(value).resolve()
                for key in ("stdlib", "platstdlib")
                if (value := sysconfig.get_path(key)) is not None
            }
        )
        self._site_roots = tuple(
            {
                Path(value).resolve()
                for key in ("purelib", "platlib")
                if (value := sysconfig.get_path(key)) is not None
            }
        )
        values = dict(vars(builtins))
        values["__import__"] = self._import
        self.builtins: Mapping[str, object] = values

    def _import(
        self,
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        caller = inspect.currentframe()
        caller = caller.f_back if caller is not None else None
        opcode = (
            dis.opname[caller.f_code.co_code[caller.f_lasti]]
            if caller is not None and caller.f_lasti >= 0
            else None
        )
        if opcode != "IMPORT_NAME":
            raise ImportError("Direct calls to Plugin import authority are unavailable")
        if level:
            raise ImportError("Relative imports are not available to Plugin modules")
        root = name.partition(".")[0]
        if root in {"builtins", "importlib", "pkgutil", "runpy", "sys", "zipimport"}:
            raise ImportError(
                "Dynamic import facilities are unavailable to Plugin modules"
            )
        exact_exports = self._host_api_exports.get(name)
        if exact_exports is not None and (
            not fromlist or any(item not in exact_exports for item in fromlist)
        ):
            raise ImportError(
                "Exact Plugin Host API imports require explicit allowed exports"
            )
        is_host_api = exact_exports is not None or any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in self._host_api_prefixes
        )
        if root in sys.stdlib_module_names:
            self._require_stdlib_origin(name)
        elif root in self._distribution_evidence:
            self._require_distribution_origin(name, root=root)
        elif not is_host_api:
            raise ImportError(
                "Plugin import is outside its declared direct-import boundary"
            )
        return builtins.__import__(name, globals, locals, fromlist, level)

    def _require_stdlib_origin(self, name: str) -> None:
        spec = importlib.util.find_spec(name)
        if spec is None:
            raise ImportError("Plugin standard-library import cannot be resolved")
        if spec.origin in {"built-in", "frozen"}:
            return
        paths = _spec_paths(spec)
        if not paths or any(
            not _is_within(path, self._stdlib_roots)
            or _is_within(path, self._site_roots)
            for path in paths
        ):
            raise ImportError("Plugin standard-library import origin is mutable")

    def _require_distribution_origin(self, name: str, *, root: str) -> None:
        spec = importlib.util.find_spec(name)
        if spec is None:
            raise ImportError("Plugin dependency import cannot be resolved")
        paths = _spec_paths(spec)
        if not any(
            evidence.allows_import_origin(name, paths)
            for evidence in self._distribution_evidence[root]
        ):
            raise ImportError("Plugin dependency import origin is outside its lock")


def _spec_paths(spec: object) -> tuple[Path, ...]:
    origin = getattr(spec, "origin", None)
    if isinstance(origin, str) and origin not in {"built-in", "frozen"}:
        return (Path(origin).resolve(),)
    locations = getattr(spec, "submodule_search_locations", None)
    if locations is None:
        return ()
    return tuple(Path(item).resolve() for item in locations)


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


__all__ = [
    "VerifiedPluginPythonModule",
    "load_verified_plugin_python_module",
]
