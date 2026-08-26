"""Verified installed Python distribution identity and import-origin evidence."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Literal

from loushang.harness.resources.plugins.dependencies import (
    PluginPythonDistributionLock,
    canonical_python_distribution_name,
)

InstalledPythonDistributionMode = Literal["record", "editable"]
DistributionsReader = Callable[[str], tuple[object, ...]]
PackagesDistributionsReader = Callable[[], Mapping[str, list[str]]]
ModuleSpecReader = Callable[[str], ModuleSpec | None]


def _installed_distributions(name: str) -> tuple[object, ...]:
    return tuple(importlib.metadata.distributions(name=name))


class InstalledPythonDistributionEvidenceError(ImportError):
    """Fail-closed installed-distribution evidence rejection."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _EditablePackageOrigin:
    package: str
    exact_paths: tuple[Path, ...]
    directory_roots: tuple[Path, ...]

    def allows(self, paths: tuple[Path, ...]) -> bool:
        return bool(paths) and all(
            path in self.exact_paths
            or any(
                path == root or path.is_relative_to(root)
                for root in self.directory_roots
            )
            for path in paths
        )


@dataclass(frozen=True, slots=True)
class InstalledPythonDistributionEvidence:
    """One exact installed distribution plus its current import-origin proof."""

    distribution: PluginPythonDistributionLock
    install_mode: InstalledPythonDistributionMode
    top_level_packages: tuple[str, ...]
    editable_project_root: Path | None = None
    _recorded_paths: tuple[Path, ...] = field(default=(), repr=False)
    _editable_origins: tuple[_EditablePackageOrigin, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.distribution, PluginPythonDistributionLock):
            raise TypeError("Installed distribution evidence requires an exact lock")
        packages = tuple(sorted(set(self.top_level_packages)))
        if any(not _valid_top_level_package(item) for item in packages):
            raise ValueError("Installed distribution top-level package is invalid")
        object.__setattr__(self, "top_level_packages", packages)
        if self.install_mode == "record":
            if self.editable_project_root is not None or self._editable_origins:
                raise ValueError("RECORD evidence cannot carry editable origins")
        elif self.install_mode == "editable":
            if self.editable_project_root is None or self._recorded_paths:
                raise ValueError("Editable evidence requires one project root")
            if tuple(item.package for item in self._editable_origins) != packages:
                raise ValueError("Editable package origins do not match distribution")
        else:
            raise ValueError("Unsupported installed distribution evidence mode")

    def contains_distribution_path(self, path: str | Path) -> bool:
        """Return whether a current file/directory belongs to this evidence."""

        candidate = _resolve_existing_path(path)
        if candidate is None:
            return False
        if self.install_mode == "editable":
            root = self.editable_project_root
            return root is not None and (
                candidate == root or candidate.is_relative_to(root)
            )
        return candidate in self._recorded_paths

    def allows_import_origin(
        self,
        module_name: str,
        paths: tuple[Path, ...],
    ) -> bool:
        """Return whether every resolved module path is proven by this distribution."""

        top_level = module_name.partition(".")[0]
        if top_level not in self.top_level_packages:
            return False
        resolved = tuple(_resolve_existing_path(item) for item in paths)
        if not resolved or any(item is None for item in resolved):
            return False
        concrete = tuple(item for item in resolved if item is not None)
        if self.install_mode == "editable":
            return next(
                item for item in self._editable_origins if item.package == top_level
            ).allows(concrete)
        return all(
            path in self._recorded_paths
            or (
                path.is_dir()
                and path.name == module_name.rpartition(".")[2]
                and any(item.is_relative_to(path) for item in self._recorded_paths)
            )
            for path in concrete
        )

    def require_import_origin(
        self,
        module_name: str,
        paths: tuple[Path, ...],
    ) -> None:
        """Reject a module origin not proven by this exact distribution."""

        if not self.allows_import_origin(module_name, paths):
            raise InstalledPythonDistributionEvidenceError(
                "Plugin dependency import origin is outside its lock",
                code="plugin_dependency_import_origin_outside_evidence",
            )


class InstalledPythonDistributionEvidenceResolver:
    """Resolve wheel/RECORD or explicitly allowed PEP 610 editable evidence."""

    def __init__(
        self,
        *,
        allow_editable: bool = False,
        distributions_reader: DistributionsReader = _installed_distributions,
        packages_distributions_reader: PackagesDistributionsReader = (
            importlib.metadata.packages_distributions
        ),
        module_spec_reader: ModuleSpecReader = importlib.util.find_spec,
    ) -> None:
        if not isinstance(allow_editable, bool):
            raise TypeError("Editable distribution policy must be a boolean")
        if not all(
            callable(item)
            for item in (
                distributions_reader,
                packages_distributions_reader,
                module_spec_reader,
            )
        ):
            raise TypeError("Installed distribution evidence readers must be callable")
        self._allow_editable = allow_editable
        self._distributions_reader = distributions_reader
        self._packages_distributions_reader = packages_distributions_reader
        self._module_spec_reader = module_spec_reader

    def resolve(
        self,
        distribution: str | PluginPythonDistributionLock,
        *,
        expected_version: str | None = None,
        required_paths: tuple[Path, ...] = (),
    ) -> InstalledPythonDistributionEvidence:
        """Resolve one unambiguous candidate, optionally selected by source paths."""

        evidence = self.resolve_all(
            distribution,
            expected_version=expected_version,
        )
        if required_paths:
            evidence = tuple(
                item
                for item in evidence
                if all(item.contains_distribution_path(path) for path in required_paths)
            )
            if not evidence:
                raise _evidence_error(
                    "A locked Plugin dependency source is outside its installation",
                    code="plugin_dependency_distribution_source_mismatch",
                )
        if len(evidence) != 1:
            raise _evidence_error(
                "A locked Plugin dependency installation is ambiguous",
                code="plugin_dependency_distribution_ambiguous",
            )
        return evidence[0]

    def resolve_all(
        self,
        distribution: str | PluginPythonDistributionLock,
        *,
        expected_version: str | None = None,
    ) -> tuple[InstalledPythonDistributionEvidence, ...]:
        """Resolve every exact installed candidate for import-origin selection."""

        requested_name, required_version = _requested_distribution(
            distribution,
            expected_version=expected_version,
        )
        try:
            installed_candidates = tuple(self._distributions_reader(requested_name))
        except Exception as exc:
            raise _evidence_error(
                "A locked Plugin dependency is unavailable",
                code="plugin_dependency_distribution_unavailable",
            ) from exc
        if not installed_candidates:
            raise _evidence_error(
                "A locked Plugin dependency is unavailable",
                code="plugin_dependency_distribution_unavailable",
            )
        packages = _top_level_packages(
            requested_name,
            self._packages_distributions_reader,
        )
        matching: list[InstalledPythonDistributionEvidence] = []
        saw_requested_name = False
        for installed in installed_candidates:
            installed_name = _installed_distribution_name(installed)
            if installed_name != requested_name:
                raise _evidence_error(
                    "A locked Plugin dependency identity changed",
                    code="plugin_dependency_distribution_name_mismatch",
                )
            saw_requested_name = True
            installed_version = _installed_distribution_version(installed)
            if required_version is not None and installed_version != required_version:
                continue
            item = self._resolve_installed_candidate(
                installed,
                distribution=PluginPythonDistributionLock(
                    name=installed_name,
                    version=installed_version,
                ),
                packages=packages,
            )
            if item not in matching:
                matching.append(item)
        if required_version is not None and saw_requested_name and not matching:
            raise _evidence_error(
                "A locked Plugin dependency version drifted",
                code="plugin_dependency_distribution_version_drift",
            )
        if not matching:
            raise _evidence_error(
                "A locked Plugin dependency is unavailable",
                code="plugin_dependency_distribution_unavailable",
            )
        return tuple(matching)

    def _resolve_installed_candidate(
        self,
        installed: object,
        *,
        distribution: PluginPythonDistributionLock,
        packages: tuple[str, ...],
    ) -> InstalledPythonDistributionEvidence:
        editable_root = _editable_project_root(installed)
        if editable_root is not None:
            if not self._allow_editable:
                raise _evidence_error(
                    "A locked Plugin dependency editable install is not permitted",
                    code="plugin_dependency_editable_disallowed",
                )
            origins = tuple(
                _editable_package_origin(
                    package,
                    project_root=editable_root,
                    module_spec_reader=self._module_spec_reader,
                )
                for package in packages
            )
            return InstalledPythonDistributionEvidence(
                distribution=distribution,
                install_mode="editable",
                top_level_packages=packages,
                editable_project_root=editable_root,
                _editable_origins=origins,
            )

        files = getattr(installed, "files", None)
        if files is None:
            raise _evidence_error(
                "A locked Plugin dependency origin is unverifiable",
                code="plugin_dependency_distribution_origin_unverifiable",
            )
        locate_file = getattr(installed, "locate_file", None)
        if not callable(locate_file):
            raise _evidence_error(
                "A locked Plugin dependency origin is unverifiable",
                code="plugin_dependency_distribution_origin_unverifiable",
            )
        try:
            recorded_paths = tuple(
                sorted(
                    {Path(str(locate_file(item))).resolve() for item in tuple(files)},
                    key=str,
                )
            )
        except Exception as exc:
            raise _evidence_error(
                "A locked Plugin dependency origin is unverifiable",
                code="plugin_dependency_distribution_origin_unverifiable",
            ) from exc
        return InstalledPythonDistributionEvidence(
            distribution=distribution,
            install_mode="record",
            top_level_packages=packages,
            _recorded_paths=recorded_paths,
        )


def _requested_distribution(
    distribution: str | PluginPythonDistributionLock,
    *,
    expected_version: str | None,
) -> tuple[str, str | None]:
    if isinstance(distribution, PluginPythonDistributionLock):
        if expected_version is not None:
            raise TypeError("Expected version must not accompany an exact lock")
        return distribution.name, distribution.version
    name = canonical_python_distribution_name(distribution)
    if expected_version is None:
        return name, None
    if (
        not isinstance(expected_version, str)
        or not expected_version
        or expected_version != expected_version.strip()
    ):
        raise ValueError("Expected Python distribution version must be non-empty")
    return name, expected_version


def _installed_distribution_name(installed: object) -> str:
    metadata = getattr(installed, "metadata", None)
    get_metadata = getattr(metadata, "get", None)
    name = get_metadata("Name") if callable(get_metadata) else None
    if not isinstance(name, str) or not name.strip():
        name = getattr(installed, "name", None)
    if not isinstance(name, str) or not name.strip():
        raise _evidence_error(
            "A locked Plugin dependency identity is unverifiable",
            code="plugin_dependency_distribution_name_unverifiable",
        )
    try:
        return canonical_python_distribution_name(name)
    except (TypeError, ValueError) as exc:
        raise _evidence_error(
            "A locked Plugin dependency identity is unverifiable",
            code="plugin_dependency_distribution_name_unverifiable",
        ) from exc


def _installed_distribution_version(installed: object) -> str:
    version = getattr(installed, "version", None)
    if not isinstance(version, str) or not version or version != version.strip():
        raise _evidence_error(
            "A locked Plugin dependency version is unverifiable",
            code="plugin_dependency_distribution_version_unverifiable",
        )
    return version


def _top_level_packages(
    distribution_name: str,
    reader: PackagesDistributionsReader,
) -> tuple[str, ...]:
    try:
        package_distributions = reader()
    except Exception as exc:
        raise _evidence_error(
            "A locked Plugin dependency origin is unverifiable",
            code="plugin_dependency_distribution_origin_unverifiable",
        ) from exc
    packages: set[str] = set()
    for package, distributions in package_distributions.items():
        if not _valid_top_level_package(package):
            continue
        try:
            matches = any(
                canonical_python_distribution_name(item) == distribution_name
                for item in distributions
            )
        except (TypeError, ValueError):
            continue
        if matches:
            packages.add(package)
    return tuple(sorted(packages))


def _editable_project_root(installed: object) -> Path | None:
    read_text = getattr(installed, "read_text", None)
    if not callable(read_text):
        return None
    try:
        encoded = read_text("direct_url.json")
    except Exception as exc:
        raise _invalid_editable_metadata() from exc
    if encoded is None:
        return None
    if not isinstance(encoded, str):
        raise _invalid_editable_metadata()
    try:
        document = json.loads(encoded, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise _invalid_editable_metadata() from exc
    if not isinstance(document, dict):
        raise _invalid_editable_metadata()
    directory_info = document.get("dir_info")
    if (
        not isinstance(directory_info, dict)
        or directory_info.get("editable") is not True
    ):
        return None
    url = document.get("url")
    if not isinstance(url, str):
        raise _invalid_editable_metadata()
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme.lower() != "file"
        or parsed.hostname not in {None, "", "localhost"}
        or parsed.query
        or parsed.fragment
        or not parsed.path
    ):
        raise _invalid_editable_metadata()
    try:
        root = Path(urllib.request.url2pathname(parsed.path)).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise _invalid_editable_metadata() from exc
    if not root.is_dir():
        raise _invalid_editable_metadata()
    return root


def _editable_package_origin(
    package: str,
    *,
    project_root: Path,
    module_spec_reader: ModuleSpecReader,
) -> _EditablePackageOrigin:
    try:
        spec = module_spec_reader(package)
    except Exception as exc:
        raise _unverifiable_editable_origin() from exc
    if spec is None:
        raise _unverifiable_editable_origin()
    exact_paths: set[Path] = set()
    directory_roots: set[Path] = set()
    locations = getattr(spec, "submodule_search_locations", None)
    if locations is not None:
        try:
            directory_roots.update(
                Path(str(item)).resolve(strict=True) for item in locations
            )
        except (OSError, ValueError) as exc:
            raise _unverifiable_editable_origin() from exc
    if not directory_roots:
        origin = getattr(spec, "origin", None)
        if not isinstance(origin, str) or origin in {"built-in", "frozen"}:
            raise _unverifiable_editable_origin()
        try:
            exact_paths.add(Path(origin).resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise _unverifiable_editable_origin() from exc
    if any(
        not (path == project_root or path.is_relative_to(project_root))
        for path in (*exact_paths, *directory_roots)
    ):
        raise _unverifiable_editable_origin()
    return _EditablePackageOrigin(
        package=package,
        exact_paths=tuple(sorted(exact_paths, key=str)),
        directory_roots=tuple(sorted(directory_roots, key=str)),
    )


def _resolve_existing_path(path: str | Path) -> Path | None:
    try:
        return Path(path).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        return None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Duplicate installed-distribution metadata field")
        document[key] = value
    return document


def _valid_top_level_package(value: object) -> bool:
    return isinstance(value, str) and value.isidentifier()


def _invalid_editable_metadata() -> InstalledPythonDistributionEvidenceError:
    return _evidence_error(
        "A locked Plugin dependency editable metadata is invalid",
        code="plugin_dependency_editable_metadata_invalid",
    )


def _unverifiable_editable_origin() -> InstalledPythonDistributionEvidenceError:
    return _evidence_error(
        "A locked Plugin dependency editable origin is unverifiable",
        code="plugin_dependency_distribution_origin_unverifiable",
    )


def _evidence_error(
    message: str,
    *,
    code: str,
) -> InstalledPythonDistributionEvidenceError:
    return InstalledPythonDistributionEvidenceError(message, code=code)


__all__ = [
    "InstalledPythonDistributionEvidence",
    "InstalledPythonDistributionEvidenceError",
    "InstalledPythonDistributionEvidenceResolver",
    "InstalledPythonDistributionMode",
]
