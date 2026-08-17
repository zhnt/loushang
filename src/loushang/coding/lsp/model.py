"""Transport-independent values for Coding's LSP capability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Literal

LspQuery = Literal["definition", "references", "hover", "implementation"]


class LspError(RuntimeError):
    """Base class for stable Coding LSP failures."""


class LspUnavailableError(LspError):
    """The requested language service is unavailable."""


class LspProtocolError(LspError):
    """The language server violated the supported protocol contract."""


class LspInvalidInputError(LspError, ValueError):
    """A semantic query is outside the admitted workspace or input contract."""


@dataclass(frozen=True, slots=True)
class LspServerDefinition:
    """One admitted, declarative stdio language-server definition."""

    id: str
    command: tuple[str, ...]
    language_extensions: Mapping[str, tuple[str, ...]]
    root_markers: tuple[str, ...] = ()
    priority: int = 0
    environment: Mapping[str, str] = field(default_factory=dict)
    initialization_options: Mapping[str, object] = field(default_factory=dict)
    settings: Mapping[str, object] = field(default_factory=dict)
    startup_timeout_seconds: float = 20.0
    request_timeout_seconds: float = 15.0
    shutdown_timeout_seconds: float = 3.0
    source: str = "product"

    def __post_init__(self) -> None:
        definition_id = self.id.strip()
        if not definition_id:
            raise ValueError("LSP server id must be non-empty")
        command = tuple(self.command)
        if not command or any(
            not isinstance(part, str) or not part for part in command
        ):
            raise ValueError("LSP server command must be a non-empty argv tuple")

        language_extensions = _normalize_language_extensions(self.language_extensions)
        root_markers = tuple(self.root_markers)
        for marker in root_markers:
            if not isinstance(marker, str):
                raise TypeError("LSP root markers must be strings")
            marker_path = PurePath(marker)
            if (
                not marker
                or marker_path.is_absolute()
                or ".." in marker_path.parts
                or any(character in marker for character in "*?[")
            ):
                raise ValueError(
                    "LSP root markers must be literal relative workspace paths"
                )
        for name, value in self.environment.items():
            if not isinstance(name, str) or not name or not isinstance(value, str):
                raise TypeError("LSP environment overrides must map strings to strings")
        for timeout in (
            self.startup_timeout_seconds,
            self.request_timeout_seconds,
            self.shutdown_timeout_seconds,
        ):
            if (
                not isinstance(timeout, int | float)
                or isinstance(timeout, bool)
                or not isfinite(timeout)
                or timeout <= 0
            ):
                raise ValueError("LSP timeouts must be positive")

        object.__setattr__(self, "id", definition_id)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "language_extensions", language_extensions)
        object.__setattr__(self, "root_markers", root_markers)
        object.__setattr__(
            self, "environment", MappingProxyType(dict(self.environment))
        )
        object.__setattr__(
            self,
            "initialization_options",
            _freeze_json_mapping(self.initialization_options),
        )
        object.__setattr__(self, "settings", _freeze_json_mapping(self.settings))

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(self.language_extensions)

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(
            extension
            for extensions in self.language_extensions.values()
            for extension in extensions
        )

    def language_for_filename(self, filename: str) -> str | None:
        normalized = filename.lower()
        matches = [
            (len(extension), language)
            for language, extensions in self.language_extensions.items()
            for extension in extensions
            if normalized.endswith(extension)
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: (-item[0], item[1]))
        return matches[0][1]


@dataclass(frozen=True, slots=True)
class LspServerSelection:
    definition_id: str
    language_id: str
    workspace_root: Path
    file_path: Path
    reason_code: str


@dataclass(frozen=True, slots=True)
class LspServerKey:
    definition_id: str
    workspace_root: Path


@dataclass(frozen=True, slots=True)
class CodePosition:
    """A public, one-based code-point position."""

    line: int
    character: int


@dataclass(frozen=True, slots=True)
class CodeRange:
    start: CodePosition
    end: CodePosition


@dataclass(frozen=True, slots=True)
class CodeLocation:
    path: str | None
    uri: str
    range: CodeRange
    external: bool = False
    readable: bool = True


@dataclass(frozen=True, slots=True)
class CodeHover:
    """One bounded hover payload normalized away from LSP wire variants."""

    contents: str
    kind: Literal["markdown", "plaintext"]
    range: CodeRange | None = None


@dataclass(frozen=True, slots=True)
class CodeDiagnostic:
    """One normalized code diagnostic, distinct from Harness operations."""

    server_id: str
    uri: str
    path: str | None
    version: int | None
    severity: str
    message: str
    range: CodeRange
    code: str | None = None
    source: str | None = None
    tags: tuple[str, ...] = ()
    received_at: float = 0.0
    stale: bool = False


@dataclass(frozen=True, slots=True)
class CodeQueryResult:
    items: tuple[CodeLocation | CodeHover, ...]
    count: int
    truncated: bool
    server_id: str
    document_version: int | None
    readiness: str = "ready"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CodeSymbol:
    """One normalized document symbol with bounded nested children."""

    name: str
    kind: int
    kind_name: str
    range: CodeRange
    selection_range: CodeRange
    detail: str | None = None
    container_name: str | None = None
    children: tuple[CodeSymbol, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentOutlineResult:
    items: tuple[CodeSymbol, ...]
    count: int
    truncated: bool
    server_id: str
    document_version: int | None
    readiness: str = "ready"
    warnings: tuple[str, ...] = ()


def _normalize_extension(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("LSP server extensions must be strings")
    extension = value.strip().lower()
    if not extension:
        raise ValueError("LSP server extensions must be non-empty")
    return extension if extension.startswith(".") else f".{extension}"


def _normalize_language_extensions(
    value: Mapping[str, tuple[str, ...]],
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("LSP language_extensions must be a non-empty mapping")
    normalized: dict[str, tuple[str, ...]] = {}
    owner_by_extension: dict[str, str] = {}
    for raw_language, raw_extensions in value.items():
        if not isinstance(raw_language, str) or not raw_language.strip():
            raise TypeError("LSP language ids must be non-empty strings")
        language = raw_language.strip().lower()
        if language in normalized:
            raise ValueError(f"duplicate LSP language id: {language!r}")
        if isinstance(raw_extensions, str):
            raise TypeError("LSP language extensions must be string sequences")
        extensions = tuple(_normalize_extension(item) for item in raw_extensions)
        if not extensions:
            raise ValueError(f"LSP language {language!r} has no extensions")
        if len(set(extensions)) != len(extensions):
            raise ValueError(f"LSP language {language!r} has duplicate extensions")
        for extension in extensions:
            owner = owner_by_extension.get(extension)
            if owner is not None:
                raise ValueError(
                    f"LSP extension {extension!r} belongs to both {owner!r} "
                    f"and {language!r}"
                )
            owner_by_extension[extension] = language
        normalized[language] = extensions
    return MappingProxyType(normalized)


def _freeze_json_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("LSP JSON configuration must be an object")
    frozen: dict[str, object] = {}
    for name, item in value.items():
        if not isinstance(name, str):
            raise TypeError("LSP JSON configuration keys must be strings")
        frozen[name] = _freeze_json_value(item)
    return MappingProxyType(frozen)


def _freeze_json_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("LSP JSON configuration numbers must be finite")
        return value
    if isinstance(value, Mapping):
        return _freeze_json_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise TypeError(f"unsupported LSP JSON configuration value: {type(value).__name__}")


__all__ = [
    "CodeDiagnostic",
    "CodeHover",
    "CodeLocation",
    "CodePosition",
    "CodeQueryResult",
    "CodeRange",
    "CodeSymbol",
    "DocumentOutlineResult",
    "LspError",
    "LspInvalidInputError",
    "LspProtocolError",
    "LspQuery",
    "LspServerDefinition",
    "LspServerKey",
    "LspServerSelection",
    "LspUnavailableError",
]
