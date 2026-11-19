"""Legacy module identities for relocated Coding components.

Only frozen module inventories are redirected. Implementations are
loaded once from their canonical location; old names retain pickle lookup.
"""

from __future__ import annotations

import sys
from contextlib import suppress
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any

from ._compat.root_names import ALIASES as _SOURCE_ALIASES
from ._compat.root_names import NAMES as _ROOT_NAMES
from ._compat.root_names import OWNERS as _CURRENT_OWNERS
from .package._legacy_names import NAMES as _PACKAGE_NAMES
from .plugin_manager._legacy_names import NAMES as _MANAGER_NAMES

_ROUTES = {
    **_ROOT_NAMES,
    **{
        f"loushang.coding.package_{name}": f"loushang.coding.package.{name}"
        for name in _PACKAGE_NAMES
    },
    **{
        f"loushang.coding.{old}": f"loushang.coding.plugin_manager.{new}"
        for old, new in _MANAGER_NAMES.items()
    },
}
_ROUTES.update(_CURRENT_OWNERS)
_LEGACY = {canonical: legacy for legacy, canonical in _ROUTES.items()}
_ROUTES.update(_SOURCE_ALIASES)


def _restore_identity(value: Any, canonical: str, legacy: str, seen: set[int]) -> None:
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, (classmethod, staticmethod)):
        _restore_identity(value.__func__, canonical, legacy, seen)
        return
    if isinstance(value, property):
        for accessor in (value.fget, value.fset, value.fdel):
            if accessor is not None:
                _restore_identity(accessor, canonical, legacy, seen)
        return
    if getattr(value, "__module__", None) != canonical:
        return
    if not isinstance(value, type) and type(value).__module__ == canonical:
        _restore_identity(type(value), canonical, legacy, seen)
        return
    wrapped = getattr(value, "__wrapped__", None)
    if wrapped is not None:
        _restore_identity(wrapped, canonical, legacy, seen)
    if isinstance(value, type):
        value.__module__ = legacy
        for member in tuple(vars(value).values()):
            _restore_identity(member, canonical, legacy, seen)
        for field in getattr(value, "__dataclass_fields__", {}).values():
            _restore_identity(field.default, canonical, legacy, seen)
            _restore_identity(field.default_factory, canonical, legacy, seen)
        return
    for default in getattr(value, "__defaults__", None) or ():
        _restore_identity(default, canonical, legacy, seen)
    for default in (getattr(value, "__kwdefaults__", None) or {}).values():
        _restore_identity(default, canonical, legacy, seen)
    # Read-only typing views derive their module from their original type.
    with suppress(AttributeError, TypeError):
        value.__module__ = legacy


class _ComponentLoader(Loader):
    def __init__(self, delegate: Any, canonical: str, legacy: str) -> None:
        self._delegate = delegate
        self._canonical = canonical
        self._legacy = legacy

    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        create = getattr(self._delegate, "create_module", None)
        return None if create is None else create(spec)

    def _source_name(self, fullname: str) -> str:
        if fullname != self._canonical and _ROUTES.get(fullname) != self._canonical:
            raise ImportError(f"Loader cannot handle {fullname}")
        return self._canonical

    def get_code(self, fullname: str) -> Any:
        return self._delegate.get_code(self._source_name(fullname))

    def get_source(self, fullname: str) -> str | None:
        return self._delegate.get_source(self._source_name(fullname))

    def get_filename(self, fullname: str) -> str:
        return self._delegate.get_filename(self._source_name(fullname))

    def exec_module(self, module: ModuleType) -> None:
        # Definitions initially use the canonical name so dataclass decoration
        # observes the module protected by Python's ordinary import lock.
        module.__name__ = self._canonical
        self._delegate.exec_module(module)
        seen: set[int] = set()
        for value in tuple(vars(module).values()):
            _restore_identity(value, self._canonical, self._legacy, seen)
        module.__name__ = self._legacy
        sys.modules[self._legacy] = module
        setattr(sys.modules["loushang.coding"], self._legacy.rsplit(".", 1)[1], module)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


class _LegacyLoader(_ComponentLoader):
    def __init__(self, delegate: Any, canonical: str, legacy: str) -> None:
        super().__init__(delegate, canonical, legacy)
        self._spec: ModuleSpec | None = None

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        module = import_module(self._canonical)
        self._spec = module.__spec__
        return module

    def exec_module(self, module: ModuleType) -> None:
        # module_from_spec installs the requested legacy spec. Keep the actual
        # implementation spec for reload and source/resource inspection.
        module.__spec__ = self._spec


class _ComponentImports(MetaPathFinder):
    def _implementation_spec(
        self, fullname: str, path: Any, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        # Respect the registered implementation owner, including frozen builds
        # and custom finders, rather than bypassing them with a filesystem lookup.
        for finder in sys.meta_path:
            if finder is self or getattr(finder, "_coding_import_bootstrap", False):
                continue
            find = getattr(finder, "find_spec", None)
            if find is not None:
                spec = find(fullname, path, target)
                if spec is not None:
                    return spec
        return None

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if fullname in _ROUTES:
            canonical = _ROUTES[fullname]
            package = import_module(canonical.rpartition(".")[0])
            original = self._implementation_spec(canonical, package.__path__)
            if original is None or original.loader is None:
                return None
            legacy_spec = ModuleSpec(
                fullname,
                _LegacyLoader(original.loader, canonical, fullname),
                origin=original.origin,
            )
            legacy_spec.has_location = original.has_location
            return legacy_spec
        if fullname in _LEGACY:
            spec = self._implementation_spec(fullname, path, target)
            if spec is not None and spec.loader is not None:
                spec.loader = _ComponentLoader(spec.loader, fullname, _LEGACY[fullname])
            return spec
        return None


def install() -> _ComponentImports:
    for finder in sys.meta_path:
        if isinstance(finder, _ComponentImports):
            return finder
    finder = _ComponentImports()
    sys.meta_path.insert(0, finder)
    return finder
