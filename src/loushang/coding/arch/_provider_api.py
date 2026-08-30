"""Private first-party Provider adapter for ``coding.arch.default``.

This exact-version Product seam is consumed only by the checked-in Plugin.  It
does not expose the future public Plugin author SDK.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Never, Protocol, cast

from loushang.coding.arch.cache import ImportFactCache
from loushang.coding.arch.import_graph import project_import_provider_scan
from loushang.coding.arch.model import (
    ArchitectureDiagnostic,
    ImportGranularity,
    ImportGraph,
    ImportSelection,
)
from loushang.coding.arch.providers.python import (
    WorkspacePythonReadPort,
    WorkspacePythonSearchPort,
    scan_python_workspace,
)
from loushang.coding.arch.tool import (
    BoundaryRuleInput,
    project_import_graph_inspection_result,
    validate_import_graph_inspection_request,
)
from loushang.coding.capabilities import CODING_ARCH_CAPABILITY
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_LIST_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
)

CODING_ARCH_PLUGIN_CONFIG_VERSION = 1
CODING_ARCH_PRIVATE_STATE_SCHEMA_VERSION = 1
CODING_ARCH_DEFAULT_PRIVATE_STATE_QUOTA_BYTES = 64 * 1024 * 1024
CODING_ARCH_MAX_PRIVATE_STATE_QUOTA_BYTES = 1024 * 1024 * 1024

CODING_ARCH_ANALYSIS_FACET = "analysis"
CODING_ARCH_TOOL_RUNTIME_FACET = "tool-runtime"
CODING_ARCH_DIAGNOSTICS_FACET = "diagnostics"

_CONFIG_FIELDS = frozenset(
    {
        "configVersion",
        "privateDataRoot",
        "privateStateQuotaBytes",
        "privateStateSchemaVersion",
        "workspaceRoot",
    }
)

CODING_ARCH_WORKSPACE_REQUIREMENT = CapabilityRequirement(
    capability="harness.workspace",
    facets=(WORKSPACE_READ_FACET, WORKSPACE_LIST_FACET, WORKSPACE_SEARCH_FACET),
    compatible_contract=CapabilityContractRange.exact(1),
)
CODING_ARCH_CAPABILITY_DEFINITION = CapabilityDefinition(
    capability_id=CODING_ARCH_CAPABILITY,
    owner_id="coding",
    contract_version=1,
    facets=(
        CODING_ARCH_ANALYSIS_FACET,
        CODING_ARCH_TOOL_RUNTIME_FACET,
        CODING_ARCH_DIAGNOSTICS_FACET,
    ),
    scope="session",
    refresh_boundary="sealed",
    phase="final",
    authority_ceiling=frozenset({"filesystem"}),
)
CODING_ARCH_TOOL_RUNTIME_REQUIREMENT = CapabilityRequirement(
    capability=CODING_ARCH_CAPABILITY,
    facets=(CODING_ARCH_TOOL_RUNTIME_FACET,),
    compatible_contract=CapabilityContractRange.exact(1),
)
CODING_ARCH_ANALYSIS_REQUIREMENT = CapabilityRequirement(
    capability=CODING_ARCH_CAPABILITY,
    facets=(CODING_ARCH_ANALYSIS_FACET, CODING_ARCH_DIAGNOSTICS_FACET),
    compatible_contract=CapabilityContractRange.exact(1),
)


class CodingArchPluginConfigError(ValueError):
    """Stable rejection for malformed private Provider binding inputs."""

    code = "invalid_coding_arch_plugin_configuration"


@dataclass(frozen=True, slots=True)
class CodingArchPluginConfigV1:
    """Canonical Product-owned inputs retained by one Arch reservation."""

    workspace_root: Path
    private_data_root: Path
    private_state_quota_bytes: int = CODING_ARCH_DEFAULT_PRIVATE_STATE_QUOTA_BYTES
    private_state_schema_version: int = CODING_ARCH_PRIVATE_STATE_SCHEMA_VERSION
    config_version: int = CODING_ARCH_PLUGIN_CONFIG_VERSION

    def __post_init__(self) -> None:
        if self.config_version != CODING_ARCH_PLUGIN_CONFIG_VERSION:
            _reject("Coding Arch Plugin configuration version is unsupported")
        if self.private_state_schema_version != CODING_ARCH_PRIVATE_STATE_SCHEMA_VERSION:
            _reject("Coding Arch private-state schema version is unsupported")
        workspace_root = _absolute_path(
            self.workspace_root,
            name="Coding Arch Plugin workspace root",
        )
        private_data_root = _absolute_path(
            self.private_data_root,
            name="Coding Arch Plugin private-data root",
        )
        quota = self.private_state_quota_bytes
        if isinstance(quota, bool) or not isinstance(quota, int):
            _reject("Coding Arch private-state quota must be an integer")
        if not 1 <= quota <= CODING_ARCH_MAX_PRIVATE_STATE_QUOTA_BYTES:
            _reject("Coding Arch private-state quota is out of range")
        object.__setattr__(self, "workspace_root", workspace_root)
        object.__setattr__(self, "private_data_root", private_data_root)

    @classmethod
    def from_runtime_inputs(
        cls,
        *,
        workspace_root: str | Path,
        private_data_root: str | Path,
        private_state_quota_bytes: int = (
            CODING_ARCH_DEFAULT_PRIVATE_STATE_QUOTA_BYTES
        ),
    ) -> CodingArchPluginConfigV1:
        return cls(
            workspace_root=Path(workspace_root),
            private_data_root=Path(private_data_root),
            private_state_quota_bytes=private_state_quota_bytes,
        )

    @classmethod
    def from_mapping(cls, value: object) -> CodingArchPluginConfigV1:
        document = _exact_mapping(
            value,
            fields=_CONFIG_FIELDS,
            name="Coding Arch Plugin configuration",
        )
        for field_name in ("configVersion", "privateStateSchemaVersion"):
            field_value = document[field_name]
            if isinstance(field_value, bool) or not isinstance(field_value, int):
                _reject(f"Coding Arch Plugin {field_name} must be an integer")
        workspace_root = document["workspaceRoot"]
        private_data_root = document["privateDataRoot"]
        if not isinstance(workspace_root, str) or not workspace_root:
            _reject("Coding Arch Plugin workspace root must be a non-empty string")
        if not isinstance(private_data_root, str) or not private_data_root:
            _reject("Coding Arch Plugin private-data root must be a non-empty string")
        try:
            return cls(
                workspace_root=Path(workspace_root),
                private_data_root=Path(private_data_root),
                private_state_quota_bytes=cast(
                    int,
                    document["privateStateQuotaBytes"],
                ),
                private_state_schema_version=cast(
                    int,
                    document["privateStateSchemaVersion"],
                ),
                config_version=cast(int, document["configVersion"]),
            )
        except CodingArchPluginConfigError:
            raise
        except (OSError, OverflowError, TypeError, ValueError) as exc:
            raise CodingArchPluginConfigError(
                f"Coding Arch Plugin configuration is invalid: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "configVersion": self.config_version,
            "privateDataRoot": str(self.private_data_root),
            "privateStateQuotaBytes": self.private_state_quota_bytes,
            "privateStateSchemaVersion": self.private_state_schema_version,
            "workspaceRoot": str(self.workspace_root),
        }


class CodingArchToolRuntimePort(Protocol):
    """Narrow synchronous Tool view retained by the exact generation."""

    def inspect(
        self,
        *,
        workspace: str | Path,
        root: str = ".",
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: str = "module",
        imports: str = "eager",
        query: str = "summary",
        source: str | None = None,
        target: str | None = None,
        limit: int = 100,
        excludes: list[str] | None = None,
        boundary_rules: list[BoundaryRuleInput] | None = None,
        refresh_cache: bool = False,
        signal: object | None = None,
    ) -> dict[str, object] | Awaitable[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class CodingArchToolRuntimeCapabilityConsumer:
    """Exact-generation view limited to the Arch Tool-runtime facet."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != CODING_ARCH_TOOL_RUNTIME_REQUIREMENT:
            raise ValueError("Coding Arch Consumer received the wrong facet view")

    @property
    def runtime(self) -> CodingArchToolRuntimePort:
        return cast(
            CodingArchToolRuntimePort,
            self.facets.require(CODING_ARCH_TOOL_RUNTIME_FACET),
        )


@dataclass(frozen=True, slots=True)
class CodingArchAnalysisCapabilityConsumer:
    """Exact-generation view limited to analysis and diagnostics facets."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != CODING_ARCH_ANALYSIS_REQUIREMENT:
            raise ValueError("Coding Arch Consumer received the wrong facet view")

    @property
    def analysis(self) -> object:
        return self.facets.require(CODING_ARCH_ANALYSIS_FACET)

    @property
    def diagnostics(self) -> object:
        return self.facets.require(CODING_ARCH_DIAGNOSTICS_FACET)


@dataclass(slots=True)
class _CodingArchProviderRuntimeOwner:
    config: CodingArchPluginConfigV1
    workspace_read: WorkspacePythonReadPort = field(repr=False)
    workspace_search: WorkspacePythonSearchPort = field(repr=False)
    cache: ImportFactCache = field(repr=False)
    _diagnostics: tuple[ArchitectureDiagnostic, ...] = field(
        default=(),
        init=False,
        repr=False,
    )
    _disposed: bool = field(default=False, init=False, repr=False)

    async def analyze(
        self,
        *,
        root: str = ".",
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: ImportGranularity = "module",
        imports: ImportSelection = "eager",
        excludes: tuple[str, ...] = (),
        refresh_cache: bool = False,
        signal: object | None = None,
    ) -> ImportGraph:
        self._require_open()
        resolved_root = _contained_root(self.config.workspace_root, root)
        if language not in {"auto", "python"}:
            raise ValueError(
                f"unsupported import graph language {language!r}; "
                "available providers: python"
            )
        scan = await scan_python_workspace(
            resolved_root,
            package_prefix=package_prefix,
            excludes=excludes,
            read=self.workspace_read,
            search=self.workspace_search,
            cache=self.cache,
            refresh_cache=refresh_cache,
            signal=signal,
        )
        graph = project_import_provider_scan(
            scan,
            root=resolved_root,
            package_prefix=package_prefix,
            granularity=granularity,
            imports=imports,
        )
        self._diagnostics = graph.diagnostics
        return graph

    async def inspect(
        self,
        *,
        workspace: str | Path,
        root: str = ".",
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: str = "module",
        imports: str = "eager",
        query: str = "summary",
        source: str | None = None,
        target: str | None = None,
        limit: int = 100,
        excludes: list[str] | None = None,
        boundary_rules: list[BoundaryRuleInput] | None = None,
        refresh_cache: bool = False,
        signal: object | None = None,
    ) -> dict[str, object]:
        self._require_open()
        if Path(workspace).expanduser().resolve() != self.config.workspace_root:
            raise PermissionError(
                "Coding Arch Tool workspace does not match its Provider scope"
            )
        validate_import_graph_inspection_request(
            granularity=granularity,
            imports=imports,
            query=query,
            limit=limit,
            excludes=excludes,
            boundary_rules=boundary_rules,
        )
        graph = await self.analyze(
            root=root,
            package_prefix=package_prefix,
            language=language,
            granularity=cast(ImportGranularity, granularity),
            imports=cast(ImportSelection, imports),
            excludes=tuple(excludes or ()),
            refresh_cache=refresh_cache,
            signal=signal,
        )
        return project_import_graph_inspection_result(
            graph,
            query=query,
            source=source,
            target=target,
            limit=limit,
            boundary_rules=boundary_rules,
        )

    def diagnostics(self) -> tuple[ArchitectureDiagnostic, ...]:
        self._require_open()
        return self._diagnostics

    def dispose(self) -> None:
        self._disposed = True

    def _require_open(self) -> None:
        if self._disposed:
            raise RuntimeError("Coding Arch Provider generation is disposed")


@dataclass(frozen=True, slots=True)
class _CodingArchAnalysisView:
    _owner: _CodingArchProviderRuntimeOwner = field(repr=False)

    async def analyze(
        self,
        *,
        root: str = ".",
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: ImportGranularity = "module",
        imports: ImportSelection = "eager",
        excludes: tuple[str, ...] = (),
        refresh_cache: bool = False,
        signal: object | None = None,
    ) -> ImportGraph:
        return await self._owner.analyze(
            root=root,
            package_prefix=package_prefix,
            language=language,
            granularity=granularity,
            imports=imports,
            excludes=excludes,
            refresh_cache=refresh_cache,
            signal=signal,
        )


@dataclass(frozen=True, slots=True)
class _CodingArchToolRuntimeView:
    _owner: _CodingArchProviderRuntimeOwner = field(repr=False)

    async def inspect(
        self,
        *,
        workspace: str | Path,
        root: str = ".",
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: str = "module",
        imports: str = "eager",
        query: str = "summary",
        source: str | None = None,
        target: str | None = None,
        limit: int = 100,
        excludes: list[str] | None = None,
        boundary_rules: list[BoundaryRuleInput] | None = None,
        refresh_cache: bool = False,
        signal: object | None = None,
    ) -> dict[str, object]:
        return await self._owner.inspect(
            workspace=workspace,
            root=root,
            package_prefix=package_prefix,
            language=language,
            granularity=granularity,
            imports=imports,
            query=query,
            source=source,
            target=target,
            limit=limit,
            excludes=excludes,
            boundary_rules=boundary_rules,
            refresh_cache=refresh_cache,
            signal=signal,
        )


@dataclass(frozen=True, slots=True)
class _CodingArchDiagnosticsView:
    _owner: _CodingArchProviderRuntimeOwner = field(repr=False)

    def current(self) -> tuple[ArchitectureDiagnostic, ...]:
        return self._owner.diagnostics()


def coding_arch_capability_provider() -> CapabilityBundleProvider:
    """Describe the fixed private Provider without constructing live state."""

    return CapabilityBundleProvider(
        capability_id=CODING_ARCH_CAPABILITY,
        provider_id="coding.arch.default",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=CODING_ARCH_CAPABILITY_DEFINITION.facets,
        requirements=(
            CODING_ARCH_WORKSPACE_REQUIREMENT,
        ),
        required_authorities=frozenset({"filesystem"}),
        source_id="plugin:coding.arch.default",
        selection_rule=PLUGIN_PROVIDER_SELECTION_RULE,
    )


def create_coding_arch_provider(
    context: CapabilityProviderContext,
) -> CapabilityBundleValue:
    """Construct one lazy Arch Bundle from exact Product inputs."""

    if not isinstance(context, CapabilityProviderContext):
        raise TypeError("Coding Arch Provider requires a Provider context")
    if context.product_id != CODING_PRODUCT_ID:
        raise ValueError("Coding Arch Provider is restricted to the Coding Product")
    config = CodingArchPluginConfigV1.from_mapping(context.binding_inputs)
    workspace = context.dependency(CODING_ARCH_WORKSPACE_REQUIREMENT.capability)
    read = cast(
        WorkspacePythonReadPort,
        workspace.require(WORKSPACE_READ_FACET),
    )
    listing = workspace.require(WORKSPACE_LIST_FACET)
    search = cast(
        WorkspacePythonSearchPort,
        workspace.require(WORKSPACE_SEARCH_FACET),
    )
    for value, members, name in (
        (read, ("exists", "is_file", "read_bytes"), "read facet"),
        (listing, ("exists", "is_dir", "iterdir"), "list facet"),
        (search, ("exists", "is_file", "is_dir", "read_text", "walk_files"), "search facet"),
    ):
        for member in members:
            _require_callable_member(value, member, name=name)
    cache = ImportFactCache(
        config.private_data_root
        / f"import-facts-v{config.private_state_schema_version}.json",
        max_bytes=config.private_state_quota_bytes,
    )
    owner = _CodingArchProviderRuntimeOwner(
        config=config,
        workspace_read=read,
        workspace_search=search,
        cache=cache,
    )
    return CapabilityBundleValue(
        (
            CapabilityFacetBinding(
                CODING_ARCH_ANALYSIS_FACET,
                _CodingArchAnalysisView(owner),
            ),
            CapabilityFacetBinding(
                CODING_ARCH_TOOL_RUNTIME_FACET,
                _CodingArchToolRuntimeView(owner),
            ),
            CapabilityFacetBinding(
                CODING_ARCH_DIAGNOSTICS_FACET,
                _CodingArchDiagnosticsView(owner),
            ),
        )
    )


def dispose_coding_arch_provider(value: CapabilityBundleValue) -> None:
    """Dispose only the owner shared by the exact Arch Bundle facets."""

    if not isinstance(value, CapabilityBundleValue):
        raise TypeError("Coding Arch Provider disposer requires a Bundle value")
    analysis = value.require(CODING_ARCH_ANALYSIS_FACET)
    tools = value.require(CODING_ARCH_TOOL_RUNTIME_FACET)
    diagnostics = value.require(CODING_ARCH_DIAGNOSTICS_FACET)
    if (
        not isinstance(analysis, _CodingArchAnalysisView)
        or not isinstance(tools, _CodingArchToolRuntimeView)
        or not isinstance(diagnostics, _CodingArchDiagnosticsView)
    ):
        raise TypeError("Coding Arch Provider Bundle contains a foreign access view")
    if analysis._owner is not tools._owner or analysis._owner is not diagnostics._owner:
        raise ValueError("Coding Arch Provider Bundle facets do not share one runtime")
    analysis._owner.dispose()


def _absolute_path(value: object, *, name: str) -> Path:
    if not isinstance(value, Path):
        _reject(f"{name} must be a path")
    if not value.is_absolute():
        _reject(f"{name} must be absolute")
    return value.resolve()


def _contained_root(workspace: Path, root: str) -> Path:
    candidate = Path(root).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(workspace):
        raise PermissionError("Coding Arch analysis root must stay in the workspace")
    return resolved


def _exact_mapping(
    value: object,
    *,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _reject(f"{name} must be an object with exact fields")
    actual = frozenset(value)
    if actual != fields:
        _reject(f"{name} fields do not match the v1 contract")
    return cast(Mapping[str, object], value)


def _require_callable_member(value: object, member: str, *, name: str) -> None:
    if not callable(getattr(value, member, None)):
        raise TypeError(f"Coding Arch Provider {name} is invalid")


def _reject(message: str) -> Never:
    raise CodingArchPluginConfigError(message)


__all__ = [
    "CODING_ARCH_ANALYSIS_FACET",
    "CODING_ARCH_ANALYSIS_REQUIREMENT",
    "CODING_ARCH_CAPABILITY_DEFINITION",
    "CODING_ARCH_DEFAULT_PRIVATE_STATE_QUOTA_BYTES",
    "CODING_ARCH_DIAGNOSTICS_FACET",
    "CODING_ARCH_MAX_PRIVATE_STATE_QUOTA_BYTES",
    "CODING_ARCH_PLUGIN_CONFIG_VERSION",
    "CODING_ARCH_PRIVATE_STATE_SCHEMA_VERSION",
    "CODING_ARCH_TOOL_RUNTIME_FACET",
    "CODING_ARCH_TOOL_RUNTIME_REQUIREMENT",
    "CODING_ARCH_WORKSPACE_REQUIREMENT",
    "CodingArchPluginConfigError",
    "CodingArchPluginConfigV1",
    "CodingArchAnalysisCapabilityConsumer",
    "CodingArchToolRuntimeCapabilityConsumer",
    "CodingArchToolRuntimePort",
    "coding_arch_capability_provider",
    "create_coding_arch_provider",
    "dispose_coding_arch_provider",
]
