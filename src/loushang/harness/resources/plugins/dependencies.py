from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

PLUGIN_DEPENDENCY_LOCK_FORMAT = "loushang.plugin-dependency-lock/v1"


@dataclass(frozen=True, slots=True)
class PluginPythonDistributionLock:
    """Exact Python distribution identity present in one published revision."""

    name: str
    version: str

    def __post_init__(self) -> None:
        if self.name != _normalize_distribution_name(self.name):
            raise ValueError("Python distribution lock name must be canonical")
        if not self.version or self.version != self.version.strip():
            raise ValueError("Python distribution lock version must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "version": self.version}

    @classmethod
    def from_dict(cls, value: object) -> PluginPythonDistributionLock:
        document = _exact_document(
            value,
            name="Plugin Python distribution lock",
            keys={"name", "version"},
        )
        name = document["name"]
        version = document["version"]
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("Plugin Python distribution lock fields must be strings")
        return cls(name=name, version=version)


@dataclass(frozen=True, slots=True)
class PluginDependencyClosureLock:
    """Digest-bound inventory of the complete materialized distribution tree."""

    package_content_digest: str
    python_distributions: tuple[PluginPythonDistributionLock, ...]
    format: str = PLUGIN_DEPENDENCY_LOCK_FORMAT

    def __post_init__(self) -> None:
        _require_sha256(self.package_content_digest, name="package content digest")
        distributions = tuple(self.python_distributions)
        if any(
            not isinstance(item, PluginPythonDistributionLock) for item in distributions
        ):
            raise TypeError(
                "python_distributions must contain PluginPythonDistributionLock values"
            )
        distributions = tuple(
            sorted(distributions, key=lambda item: (item.name, item.version))
        )
        names = [item.name for item in distributions]
        if len(names) != len(set(names)):
            raise ValueError(
                "Plugin dependency closure contains duplicate Python distributions"
            )
        object.__setattr__(self, "python_distributions", distributions)
        if self.format != PLUGIN_DEPENDENCY_LOCK_FORMAT:
            raise ValueError("Unsupported Plugin dependency lock format")

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "packageContentDigest": self.package_content_digest,
            "pythonDistributions": [
                item.to_dict() for item in self.python_distributions
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDependencyClosureLock:
        document = _exact_document(
            value,
            name="Plugin dependency closure lock",
            keys={"format", "packageContentDigest", "pythonDistributions"},
        )
        lock_format = document["format"]
        content_digest = document["packageContentDigest"]
        distributions = document["pythonDistributions"]
        if lock_format != PLUGIN_DEPENDENCY_LOCK_FORMAT:
            raise ValueError("Unsupported Plugin dependency lock format")
        if not isinstance(content_digest, str):
            raise ValueError("Plugin dependency lock content digest must be a string")
        if not isinstance(distributions, list):
            raise ValueError(
                "Plugin dependency lock pythonDistributions must be a list"
            )
        return cls(
            package_content_digest=content_digest,
            python_distributions=tuple(
                PluginPythonDistributionLock.from_dict(item) for item in distributions
            ),
            format=lock_format,
        )


def lock_plugin_dependency_closure(
    *,
    package_content_digest: str,
    installed_distributions: tuple[str, ...],
) -> PluginDependencyClosureLock:
    """Normalize installed ``name==version`` facts into one immutable lock."""

    return PluginDependencyClosureLock(
        package_content_digest=package_content_digest,
        python_distributions=tuple(
            _parse_installed_distribution(value) for value in installed_distributions
        ),
    )


def _parse_installed_distribution(value: str) -> PluginPythonDistributionLock:
    if not isinstance(value, str):
        raise ValueError("Installed Python distribution identity must be a string")
    name, separator, version = value.partition("==")
    if separator != "==" or not name.strip() or not version.strip():
        raise ValueError(
            "Installed Python distribution identity must use exact name==version"
        )
    if "==" in version:
        raise ValueError(
            "Installed Python distribution identity must contain one exact version"
        )
    return PluginPythonDistributionLock(
        name=_normalize_distribution_name(name),
        version=version.strip(),
    )


def _normalize_distribution_name(value: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", value.strip()).lower()
    if not normalized or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
        raise ValueError("Invalid Python distribution name in dependency lock")
    return normalized


def _exact_document(
    value: object,
    *,
    name: str,
    keys: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} fields do not match the supported format")
    return value


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


__all__ = [
    "PLUGIN_DEPENDENCY_LOCK_FORMAT",
    "PluginDependencyClosureLock",
    "PluginPythonDistributionLock",
    "lock_plugin_dependency_closure",
]
