"""Coding-owned configuration, discovery, and admission for LSP servers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from loushang.coding.lsp.model import LspServerDefinition

LspAdmissionState = Literal["admitted", "disabled", "rejected", "unavailable"]
ExecutableResolver = Callable[[str, Mapping[str, str]], str | None]
ConfigPath = str | Path | Literal[False] | None

_MAX_CONFIG_BYTES = 256 * 1024
_MAX_SERVER_DECLARATIONS = 64
_ALLOWED_SERVER_FIELDS = frozenset(
    {
        "id",
        "enabled",
        "command",
        "language_extensions",
        "root_markers",
        "priority",
        "environment",
        "initialization_options",
        "settings",
        "startup_timeout_seconds",
        "request_timeout_seconds",
        "shutdown_timeout_seconds",
    }
)
_BASELINE_ENVIRONMENT_NAMES = frozenset(
    {
        "CONDA_PREFIX",
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "NODE_PATH",
        "NVM_BIN",
        "NVM_DIR",
        "PATH",
        "PATHEXT",
        "PYENV_ROOT",
        "SHELL",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USER",
        "VIRTUAL_ENV",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)


@dataclass(frozen=True, slots=True)
class LspAdmissionRecord:
    definition_id: str
    source: str
    state: LspAdmissionState
    detail: str
    executable: str | None = None


@dataclass(frozen=True, slots=True)
class LspCatalogSnapshot:
    """One immutable Product catalog snapshot plus bounded admission facts."""

    generation: str
    definitions: tuple[LspServerDefinition, ...]
    records: tuple[LspAdmissionRecord, ...]

    @property
    def admitted_count(self) -> int:
        return len(self.definitions)


@dataclass(frozen=True, slots=True)
class _Declaration:
    definition_id: str
    source: str
    definition: LspServerDefinition | None
    enabled: bool = True
    error: str | None = None


def default_global_lsp_config_path() -> Path:
    return Path.home() / ".loushang" / "coding" / "lsp.json"


def default_project_lsp_config_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().resolve() / ".loushang" / "lsp.json"


def coding_lsp_config_paths(
    settings_manager: object | None,
    *,
    workspace_root: str | Path,
) -> tuple[ConfigPath, ConfigPath]:
    """Resolve Product config beside the active generic settings layers."""

    global_base = getattr(settings_manager, "global_base_dir", None)
    project_base = getattr(settings_manager, "project_base_dir", None)
    global_path: ConfigPath = (
        Path(global_base) / "lsp.json" if global_base is not None else False
    )
    project_path: ConfigPath = (
        Path(project_base) / "lsp.json"
        if project_base is not None
        else default_project_lsp_config_path(workspace_root)
    )
    return global_path, project_path


def default_lsp_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Project a stable, secret-averse environment for language servers."""

    source = os.environ if environ is None else environ
    return {
        name: value
        for name, value in source.items()
        if name in _BASELINE_ENVIRONMENT_NAMES and isinstance(value, str)
    }


def product_default_lsp_definitions() -> tuple[LspServerDefinition, ...]:
    """Return inert Product defaults; discovery admits only installed binaries."""

    return (
        LspServerDefinition(
            id="pyright",
            command=("pyright-langserver", "--stdio"),
            language_extensions={"python": (".py", ".pyi")},
            root_markers=("pyrightconfig.json", "pyproject.toml", ".git"),
            source="product-default",
        ),
        LspServerDefinition(
            id="typescript-language-server",
            command=("typescript-language-server", "--stdio"),
            language_extensions={
                "javascript": (".js", ".mjs", ".cjs"),
                "javascriptreact": (".jsx",),
                "typescript": (".ts", ".mts", ".cts"),
                "typescriptreact": (".tsx",),
            },
            root_markers=("tsconfig.json", "jsconfig.json", "package.json", ".git"),
            source="product-default",
        ),
        LspServerDefinition(
            id="rust-analyzer",
            command=("rust-analyzer",),
            language_extensions={"rust": (".rs",)},
            root_markers=("rust-project.json", "Cargo.toml", ".git"),
            source="product-default",
        ),
        LspServerDefinition(
            id="gopls",
            command=("gopls", "serve"),
            language_extensions={"go": (".go",)},
            root_markers=("go.work", "go.mod", ".git"),
            source="product-default",
        ),
        LspServerDefinition(
            id="clangd",
            command=("clangd",),
            language_extensions={
                "c": (".c", ".h"),
                "cpp": (".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"),
            },
            root_markers=(
                ".clangd",
                "compile_commands.json",
                "compile_flags.txt",
                ".git",
            ),
            source="product-default",
        ),
    )


def discover_lsp_catalog(
    *,
    workspace_root: str | Path,
    baseline_environment: Mapping[str, str],
    explicit_definitions: Iterable[LspServerDefinition] = (),
    global_config_path: ConfigPath = None,
    project_config_path: ConfigPath = None,
    executable_resolver: ExecutableResolver | None = None,
    include_product_defaults: bool = True,
) -> LspCatalogSnapshot:
    """Build one catalog without launching or communicating with any server."""

    root = Path(workspace_root).expanduser().resolve()
    declarations: list[_Declaration] = []
    if include_product_defaults:
        declarations.extend(
            _Declaration(item.id, item.source, item)
            for item in product_default_lsp_definitions()
        )
    user_declarations = _load_optional_config(
        global_config_path,
        default=default_global_lsp_config_path(),
        source="user-config",
    )
    project_declarations = _load_optional_config(
        project_config_path,
        default=default_project_lsp_config_path(root),
        source="project-config",
    )
    declarations.extend(user_declarations)
    declarations.extend(
        _admit_project_declarations(
            project_declarations,
            user_declarations=user_declarations,
        )
    )
    declarations.extend(
        _Declaration(item.id, "session", item) for item in explicit_definitions
    )

    # Later sources have higher Product precedence. A disabled higher-precedence
    # declaration intentionally masks the same lower-precedence definition.
    selected: dict[str, _Declaration] = {}
    malformed: list[_Declaration] = []
    for declaration in declarations:
        if declaration.error is not None and declaration.definition_id.startswith("<"):
            malformed.append(declaration)
            continue
        selected[declaration.definition_id] = declaration

    resolve = executable_resolver or _resolve_executable
    admitted: list[LspServerDefinition] = []
    records: list[LspAdmissionRecord] = []
    for declaration in (*malformed, *(selected[key] for key in sorted(selected))):
        if declaration.error is not None:
            records.append(
                LspAdmissionRecord(
                    definition_id=declaration.definition_id,
                    source=declaration.source,
                    state="rejected",
                    detail=declaration.error,
                )
            )
            continue
        if not declaration.enabled:
            records.append(
                LspAdmissionRecord(
                    definition_id=declaration.definition_id,
                    source=declaration.source,
                    state="disabled",
                    detail="disabled by higher-precedence Coding configuration",
                )
            )
            continue
        definition = declaration.definition
        assert definition is not None
        # Public SDK definitions are already-admitted session declarations. The
        # production config/default paths are resolved here before publication.
        effective_environment = dict(baseline_environment)
        effective_environment.update(definition.environment)
        executable = (
            definition.command[0]
            if declaration.source == "session"
            else resolve(definition.command[0], effective_environment)
        )
        if executable is None:
            records.append(
                LspAdmissionRecord(
                    definition_id=definition.id,
                    source=declaration.source,
                    state="unavailable",
                    detail=f"executable not found: {definition.command[0]}",
                )
            )
            continue
        admitted_definition = (
            definition
            if declaration.source == "session"
            else replace(
                definition,
                command=(executable, *definition.command[1:]),
            )
        )
        admitted.append(admitted_definition)
        records.append(
            LspAdmissionRecord(
                definition_id=definition.id,
                source=declaration.source,
                state="admitted",
                detail="definition validated and executable is available",
                executable=executable,
            )
        )

    definitions = tuple(sorted(admitted, key=lambda item: item.id))
    generation_input = json.dumps(
        {
            "definitions": [
                _definition_generation_value(definition) for definition in definitions
            ],
            "records": [
                {
                    "id": item.definition_id,
                    "source": item.source,
                    "state": item.state,
                    "detail": item.detail,
                    "executable": item.executable,
                }
                for item in records
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    generation = hashlib.sha256(generation_input).hexdigest()[:12]
    return LspCatalogSnapshot(
        generation=generation,
        definitions=definitions,
        records=tuple(records),
    )


def _load_config(path: Path, *, source: str) -> tuple[_Declaration, ...]:
    if not path.is_file():
        return ()
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ValueError(f"config exceeds {_MAX_CONFIG_BYTES} bytes")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise TypeError("config root must be an object")
        unknown = set(raw) - {"servers"}
        if unknown:
            raise ValueError(f"unknown config fields: {', '.join(sorted(unknown))}")
        servers = raw.get("servers", ())
        if not isinstance(servers, list):
            raise TypeError("servers must be an array")
        if len(servers) > _MAX_SERVER_DECLARATIONS:
            raise ValueError(
                f"servers exceeds the {_MAX_SERVER_DECLARATIONS}-entry limit"
            )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (_Declaration("<config>", source, None, error=str(exc)),)

    declarations: list[_Declaration] = []
    for index, value in enumerate(servers):
        try:
            declarations.append(_parse_declaration(value, source=source))
        except (OverflowError, TypeError, ValueError) as exc:
            definition_id = (
                value.get("id")
                if isinstance(value, Mapping) and isinstance(value.get("id"), str)
                else f"<server:{index}>"
            )
            declarations.append(
                _Declaration(str(definition_id), source, None, error=str(exc))
            )
    return tuple(declarations)


def _load_optional_config(
    path: ConfigPath,
    *,
    default: Path,
    source: str,
) -> tuple[_Declaration, ...]:
    if path is False:
        return ()
    return _load_config(Path(path) if path is not None else default, source=source)


def _admit_project_declarations(
    declarations: tuple[_Declaration, ...],
    *,
    user_declarations: tuple[_Declaration, ...],
) -> tuple[_Declaration, ...]:
    """Keep repository config from introducing a new executable identity.

    A future workspace-trust runtime can replace this conservative P0 rule.
    User-level config may establish a trusted custom server id; project config
    can then tune that server but cannot replace its executable or environment.
    """

    trusted_definitions = {
        definition.id: definition for definition in product_default_lsp_definitions()
    }
    for declaration in user_declarations:
        if not declaration.enabled:
            trusted_definitions.pop(declaration.definition_id, None)
        elif declaration.definition is not None:
            trusted_definitions[declaration.definition_id] = declaration.definition

    admitted: list[_Declaration] = []
    for declaration in declarations:
        definition = declaration.definition
        if not declaration.enabled or definition is None:
            admitted.append(declaration)
            continue
        trusted_definition = trusted_definitions.get(declaration.definition_id)
        if (
            trusted_definition is None
            or definition.command != trusted_definition.command
        ):
            admitted.append(
                _Declaration(
                    declaration.definition_id,
                    declaration.source,
                    None,
                    error=(
                        "project config cannot introduce or alter a process command; "
                        "add the complete command to user-level Coding lsp.json first"
                    ),
                )
            )
            continue
        if definition.environment:
            admitted.append(
                _Declaration(
                    declaration.definition_id,
                    declaration.source,
                    None,
                    error=(
                        "project config cannot set process environment overrides; "
                        "configure them in user-level Coding lsp.json"
                    ),
                )
            )
            continue
        admitted.append(
            replace(
                declaration,
                definition=replace(
                    definition,
                    command=trusted_definition.command,
                    environment=trusted_definition.environment,
                ),
            )
        )
    return tuple(admitted)


def _parse_declaration(value: object, *, source: str) -> _Declaration:
    if not isinstance(value, Mapping):
        raise TypeError("server declarations must be objects")
    unknown = set(value) - _ALLOWED_SERVER_FIELDS
    if unknown:
        raise ValueError(f"unknown server fields: {', '.join(sorted(unknown))}")
    raw_id = value.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise TypeError("server id must be a non-empty string")
    definition_id = raw_id.strip()
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise TypeError("server enabled must be a boolean")
    if not enabled:
        return _Declaration(definition_id, source, None, enabled=False)

    command = value.get("command")
    if not isinstance(command, list) or not all(
        isinstance(item, str) for item in command
    ):
        raise TypeError("server command must be a string array")
    language_extensions = value.get("language_extensions")
    if not isinstance(language_extensions, Mapping):
        raise TypeError("server language_extensions must be an object")
    normalized_languages: dict[str, tuple[str, ...]] = {}
    for language, extensions in language_extensions.items():
        if not isinstance(language, str) or not isinstance(extensions, list):
            raise TypeError("language_extensions must map strings to string arrays")
        if not all(isinstance(extension, str) for extension in extensions):
            raise TypeError("language_extensions must map strings to string arrays")
        normalized_languages[language] = tuple(extensions)

    root_markers = value.get("root_markers", [])
    if not isinstance(root_markers, list) or not all(
        isinstance(marker, str) for marker in root_markers
    ):
        raise TypeError("server root_markers must be a string array")
    environment = value.get("environment", {})
    initialization_options = value.get("initialization_options", {})
    settings = value.get("settings", {})
    definition = LspServerDefinition(
        id=definition_id,
        command=tuple(command),
        language_extensions=normalized_languages,
        root_markers=tuple(root_markers),
        priority=_integer_field(value, "priority", 0),
        environment=_string_mapping(environment, "environment"),
        initialization_options=_object_mapping(
            initialization_options, "initialization_options"
        ),
        settings=_object_mapping(settings, "settings"),
        startup_timeout_seconds=_number_field(value, "startup_timeout_seconds", 20.0),
        request_timeout_seconds=_number_field(value, "request_timeout_seconds", 15.0),
        shutdown_timeout_seconds=_number_field(value, "shutdown_timeout_seconds", 3.0),
        source=source,
    )
    return _Declaration(definition_id, source, definition)


def _integer_field(value: Mapping[object, object], name: str, default: int) -> int:
    item = value.get(name, default)
    if not isinstance(item, int) or isinstance(item, bool):
        raise TypeError(f"server {name} must be an integer")
    return item


def _number_field(value: Mapping[object, object], name: str, default: float) -> float:
    item = value.get(name, default)
    if not isinstance(item, int | float) or isinstance(item, bool):
        raise TypeError(f"server {name} must be a number")
    return float(item)


def _string_mapping(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise TypeError(f"server {name} must map strings to strings")
    return dict(value)


def _object_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"server {name} must be an object")
    return dict(value)


def _resolve_executable(command: str, environment: Mapping[str, str]) -> str | None:
    path = Path(command)
    if path.is_absolute():
        return (
            str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
        )
    if len(path.parts) != 1:
        return None
    return shutil.which(command, path=environment.get("PATH"))


def _definition_generation_value(
    definition: LspServerDefinition,
) -> dict[str, object]:
    return {
        "id": definition.id,
        "command": definition.command,
        "language_extensions": _json_generation_value(definition.language_extensions),
        "root_markers": definition.root_markers,
        "priority": definition.priority,
        "environment": _json_generation_value(definition.environment),
        "initialization_options": _json_generation_value(
            definition.initialization_options
        ),
        "settings": _json_generation_value(definition.settings),
        "startup_timeout_seconds": definition.startup_timeout_seconds,
        "request_timeout_seconds": definition.request_timeout_seconds,
        "shutdown_timeout_seconds": definition.shutdown_timeout_seconds,
        "source": definition.source,
    }


def _json_generation_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(name): _json_generation_value(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_json_generation_value(item) for item in value]
    return value


__all__ = [
    "LspAdmissionRecord",
    "LspAdmissionState",
    "LspCatalogSnapshot",
    "coding_lsp_config_paths",
    "default_global_lsp_config_path",
    "default_lsp_environment",
    "default_project_lsp_config_path",
    "discover_lsp_catalog",
    "product_default_lsp_definitions",
]
