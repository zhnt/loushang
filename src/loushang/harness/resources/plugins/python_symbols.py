"""Single verified Python module/symbol loading path for in-process Plugins."""

from __future__ import annotations

import builtins
import importlib.metadata
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import ModuleType

from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
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
) -> VerifiedPluginPythonModule:
    """Compile and execute one verified package-local source file exactly once."""

    if not isinstance(revision_handle, VerifiedRevisionHandle):
        raise TypeError("Plugin Python loader requires a verified revision handle")
    if not isinstance(dependency_lock, PluginDependencyClosureLock):
        raise TypeError("Plugin Python loader requires a dependency closure lock")
    if revision_handle.content_digest != dependency_lock.package_content_digest:
        raise ValueError("Plugin Python loader package and dependency lock differ")
    normalized_module_name = _require_nonempty(module_name, name="module name")
    prefixes = tuple(
        _require_nonempty(item, name="Host API prefix")
        for item in host_api_prefixes
    )
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("Host API prefixes must be unique")

    path = canonical_plugin_python_path(relative_path)
    revision_handle.verify()
    with revision_handle.open_file(path) as stream:
        source = stream.read()
    import_policy = _LockedImportPolicy(
        dependency_lock,
        host_api_prefixes=prefixes,
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


class _LockedImportPolicy:
    def __init__(
        self,
        dependency_lock: PluginDependencyClosureLock,
        *,
        host_api_prefixes: tuple[str, ...],
    ) -> None:
        locked_names = {
            distribution.name for distribution in dependency_lock.python_distributions
        }
        package_distributions = importlib.metadata.packages_distributions()
        self._allowed_roots = frozenset(
            package
            for package, distributions in package_distributions.items()
            if any(
                _normalize_distribution_name(item) in locked_names
                for item in distributions
            )
        )
        self._host_api_prefixes = host_api_prefixes
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
        if level:
            raise ImportError("Relative imports are not available to Plugin modules")
        root = name.partition(".")[0]
        if not (
            root in sys.stdlib_module_names
            or root in self._allowed_roots
            or any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in self._host_api_prefixes
            )
        ):
            raise ImportError("Plugin import is outside its locked closure")
        return builtins.__import__(name, globals, locals, fromlist, level)


def _normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


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
