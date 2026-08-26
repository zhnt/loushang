"""Private first-party Provider adapter for ``coding.lsp.default``.

This module is exact-version locked by the checked-in first-party Plugin.  It is
not a public Plugin SDK or an ambient service-locator boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Never, Protocol, TypeGuard, cast

from loushang.coding.capabilities import CODING_LSP_CAPABILITY
from loushang.coding.lsp.definition_codec import (
    decode_lsp_server_definition,
    encode_lsp_server_definition,
)
from loushang.coding.lsp.diagnostics import DiagnosticInboxSnapshot
from loushang.coding.lsp.model import (
    CodeDiagnostic,
    CodeQueryResult,
    DocumentOutlineResult,
    LspServerDefinition,
)
from loushang.coding.lsp.runtime import (
    CodingLspRuntime,
    CodingLspSessionAccess,
    _bind_coding_lsp_runtime_from_launcher,
)
from loushang.coding.lsp.status import LspSessionStatus
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
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
)
from loushang.harness.workspace.operations import OperationResult, resolve_operation
from loushang.harness.workspace.process import AuthorizedProcessLauncher

CODING_LSP_PLUGIN_CONFIG_VERSION = 1
CODING_LSP_SEMANTIC_FACET = "semantic"
CODING_LSP_TOOL_RUNTIME_FACET = "tool-runtime"
CODING_LSP_DIAGNOSTICS_FACET = "diagnostics"

_MAX_SERVER_DEFINITIONS = 64
_CONFIG_FIELDS = frozenset(
    {"baselineEnvironment", "configVersion", "servers", "workspaceRoot"}
)
CODING_LSP_WORKSPACE_REQUIREMENT = CapabilityRequirement(
    capability="harness.workspace",
    facets=(WORKSPACE_READ_FACET, WORKSPACE_PROCESS_LAUNCH_FACET),
    compatible_contract=CapabilityContractRange.exact(1),
)

CODING_LSP_CAPABILITY_DEFINITION = CapabilityDefinition(
    capability_id=CODING_LSP_CAPABILITY,
    owner_id="coding",
    contract_version=1,
    facets=(
        CODING_LSP_SEMANTIC_FACET,
        CODING_LSP_TOOL_RUNTIME_FACET,
        CODING_LSP_DIAGNOSTICS_FACET,
    ),
    scope="session",
    refresh_boundary="sealed",
    phase="final",
    authority_ceiling=frozenset({"filesystem", "process"}),
)
CODING_LSP_TOOL_RUNTIME_REQUIREMENT = CapabilityRequirement(
    capability=CODING_LSP_CAPABILITY_DEFINITION.capability_id,
    facets=(CODING_LSP_TOOL_RUNTIME_FACET,),
    compatible_contract=CapabilityContractRange.exact(
        CODING_LSP_CAPABILITY_DEFINITION.contract_version
    ),
)
CODING_LSP_SESSION_REQUIREMENT = CapabilityRequirement(
    capability=CODING_LSP_CAPABILITY_DEFINITION.capability_id,
    facets=(CODING_LSP_SEMANTIC_FACET,),
    compatible_contract=CapabilityContractRange.exact(
        CODING_LSP_CAPABILITY_DEFINITION.contract_version
    ),
)


@dataclass(frozen=True, slots=True)
class CodingLspSessionCapabilityConsumer:
    """Exact-generation non-owning Product view of the semantic facet."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != CODING_LSP_SESSION_REQUIREMENT:
            raise ValueError(
                "Coding LSP Session Consumer received the wrong facet view"
            )

    @property
    def access(self) -> CodingLspSessionAccess:
        value = self.facets.require(CODING_LSP_SEMANTIC_FACET)
        _require_callable_member(value, "status", name="semantic facet")
        _require_callable_member(value, "stop", name="semantic facet")
        return cast(CodingLspSessionAccess, value)


class CodingLspToolRuntimePort(Protocol):
    """Provider-neutral operations exposed to admitted LSP Tool consumers."""

    async def inspect_symbol(
        self,
        *,
        path: str,
        line: int,
        character: int,
        query: str = "definition",
        include_declaration: bool = True,
        limit: int = 50,
        correlation_id: str,
        signal: object | None = None,
    ) -> CodeQueryResult: ...

    async def document_outline(
        self,
        *,
        path: str,
        depth: int = 4,
        limit: int = 200,
        correlation_id: str,
        signal: object | None = None,
    ) -> DocumentOutlineResult: ...


@dataclass(frozen=True, slots=True)
class CodingLspToolRuntimeCapabilityConsumer:
    """Exact-generation view limited to the LSP Tool-runtime facet."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != CODING_LSP_TOOL_RUNTIME_REQUIREMENT:
            raise ValueError("Coding LSP Consumer received the wrong facet view")

    @property
    def runtime(self) -> CodingLspToolRuntimePort:
        return cast(
            CodingLspToolRuntimePort,
            self.facets.require(CODING_LSP_TOOL_RUNTIME_FACET),
        )


class CodingLspPluginConfigError(ValueError):
    """Stable rejection for malformed private Provider binding inputs."""

    code = "invalid_coding_lsp_plugin_configuration"


@dataclass(frozen=True, slots=True)
class CodingLspPluginConfigV1:
    """Canonical Product-owned inputs retained by one Plugin reservation."""

    workspace_root: Path
    definitions: tuple[LspServerDefinition, ...]
    baseline_environment: Mapping[str, str]
    config_version: int = CODING_LSP_PLUGIN_CONFIG_VERSION

    def __post_init__(self) -> None:
        if self.config_version != CODING_LSP_PLUGIN_CONFIG_VERSION:
            _reject("Coding LSP Plugin configuration version is unsupported")
        if not isinstance(self.workspace_root, Path):
            _reject("Coding LSP Plugin workspace root must be a path")
        if not self.workspace_root.is_absolute():
            _reject("Coding LSP Plugin workspace root must be absolute")
        definitions = tuple(self.definitions)
        if any(not isinstance(item, LspServerDefinition) for item in definitions):
            _reject("Coding LSP Plugin servers contain an invalid definition")
        if len(definitions) > _MAX_SERVER_DEFINITIONS:
            _reject("Coding LSP Plugin servers exceed the 64-entry limit")
        ids = tuple(item.id for item in definitions)
        if len(ids) != len(set(ids)):
            _reject("Coding LSP Plugin servers contain a duplicate id")
        environment = self.baseline_environment
        if not isinstance(environment, Mapping) or any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in environment.items()
        ):
            _reject(
                "Coding LSP Plugin baseline environment must map strings to strings"
            )
        object.__setattr__(self, "workspace_root", self.workspace_root.resolve())
        object.__setattr__(
            self,
            "definitions",
            tuple(sorted(definitions, key=lambda item: item.id)),
        )
        object.__setattr__(
            self,
            "baseline_environment",
            MappingProxyType(dict(sorted(environment.items()))),
        )

    @classmethod
    def from_runtime_inputs(
        cls,
        *,
        workspace_root: str | Path,
        definitions: Iterable[LspServerDefinition],
        baseline_environment: Mapping[str, str],
    ) -> CodingLspPluginConfigV1:
        root = Path(workspace_root)
        return cls(
            workspace_root=root,
            definitions=tuple(definitions),
            baseline_environment=baseline_environment,
        )

    @classmethod
    def from_mapping(cls, value: object) -> CodingLspPluginConfigV1:
        document = _exact_mapping(
            value,
            fields=_CONFIG_FIELDS,
            name="Coding LSP Plugin configuration",
        )
        version = document["configVersion"]
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != CODING_LSP_PLUGIN_CONFIG_VERSION
        ):
            _reject("Coding LSP Plugin configuration version is unsupported")
        workspace_root = document["workspaceRoot"]
        if not isinstance(workspace_root, str) or not workspace_root:
            _reject("Coding LSP Plugin workspace root must be a non-empty string")
        servers = document["servers"]
        if not _is_sequence(servers):
            _reject("Coding LSP Plugin servers must be an array")
        environment = _string_mapping(
            document["baselineEnvironment"],
            name="Coding LSP Plugin baseline environment",
        )
        try:
            definitions = tuple(
                decode_lsp_server_definition(
                    item,
                    require_exact_fields=True,
                )
                for item in servers
            )
            return cls(
                workspace_root=Path(workspace_root),
                definitions=definitions,
                baseline_environment=environment,
                config_version=version,
            )
        except CodingLspPluginConfigError:
            raise
        except (OverflowError, TypeError, ValueError) as exc:
            raise CodingLspPluginConfigError(
                f"Coding LSP Plugin configuration is invalid: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "baselineEnvironment": dict(self.baseline_environment),
            "configVersion": self.config_version,
            "servers": [
                encode_lsp_server_definition(item) for item in self.definitions
            ],
            "workspaceRoot": str(self.workspace_root),
        }


class _WorkspaceReadFacet(Protocol):
    def exists(self, path: Path) -> OperationResult[bool]: ...

    def read_bytes(self, path: Path) -> OperationResult[bytes]: ...


@dataclass(slots=True)
class _CodingLspProviderRuntimeOwner:
    runtime: CodingLspRuntime = field(repr=False)

    async def dispose(self) -> None:
        await self.runtime.close()


@dataclass(frozen=True, slots=True)
class _CodingLspSessionView:
    _owner: _CodingLspProviderRuntimeOwner = field(repr=False)

    def status(self) -> LspSessionStatus:
        return self._owner.runtime.status()

    async def stop(
        self,
        *,
        definition_id: str,
        workspace_root: str | Path,
    ) -> bool:
        return await self._owner.runtime.stop(
            definition_id=definition_id,
            workspace_root=workspace_root,
        )


@dataclass(frozen=True, slots=True)
class _CodingLspToolRuntimeView:
    _owner: _CodingLspProviderRuntimeOwner = field(repr=False)

    async def inspect_symbol(
        self,
        *,
        path: str,
        line: int,
        character: int,
        query: str = "definition",
        include_declaration: bool = True,
        limit: int = 50,
        correlation_id: str,
        signal: object | None = None,
    ) -> CodeQueryResult:
        return await self._owner.runtime.inspect_symbol(
            path=path,
            line=line,
            character=character,
            query=query,
            include_declaration=include_declaration,
            limit=limit,
            correlation_id=correlation_id,
            signal=signal,
        )

    async def document_outline(
        self,
        *,
        path: str,
        depth: int = 4,
        limit: int = 200,
        correlation_id: str,
        signal: object | None = None,
    ) -> DocumentOutlineResult:
        return await self._owner.runtime.document_outline(
            path=path,
            depth=depth,
            limit=limit,
            correlation_id=correlation_id,
            signal=signal,
        )


@dataclass(frozen=True, slots=True)
class _CodingLspDiagnosticsView:
    _owner: _CodingLspProviderRuntimeOwner = field(repr=False)

    def current(self) -> tuple[CodeDiagnostic, ...]:
        return self._owner.runtime.current_diagnostics()

    def snapshot(self) -> DiagnosticInboxSnapshot:
        return self._owner.runtime.diagnostics_snapshot()


def coding_lsp_capability_provider() -> CapabilityBundleProvider:
    """Describe the fixed private Provider without constructing live state."""

    return CapabilityBundleProvider(
        capability_id=CODING_LSP_CAPABILITY_DEFINITION.capability_id,
        provider_id="coding.lsp.default",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(
            CODING_LSP_CAPABILITY_DEFINITION.contract_version
        ),
        facets=CODING_LSP_CAPABILITY_DEFINITION.facets,
        requirements=(CODING_LSP_WORKSPACE_REQUIREMENT,),
        required_authorities=frozenset({"filesystem", "process"}),
        source_id="plugin:coding.lsp.default",
        selection_rule=PLUGIN_PROVIDER_SELECTION_RULE,
    )


def create_coding_lsp_provider(
    context: CapabilityProviderContext,
) -> CapabilityBundleValue:
    """Construct one lazy complete Bundle from declared dependency facets."""

    if not isinstance(context, CapabilityProviderContext):
        raise TypeError("Coding LSP Provider requires a Provider context")
    if context.product_id != CODING_PRODUCT_ID:
        raise ValueError("Coding LSP Provider is restricted to the Coding Product")
    config = CodingLspPluginConfigV1.from_mapping(context.binding_inputs)
    workspace = context.dependency(CODING_LSP_WORKSPACE_REQUIREMENT.capability)
    read = cast(_WorkspaceReadFacet, workspace.require(WORKSPACE_READ_FACET))
    launcher = cast(
        AuthorizedProcessLauncher,
        workspace.require(WORKSPACE_PROCESS_LAUNCH_FACET),
    )
    _require_callable_member(read, "exists", name="workspace read facet")
    _require_callable_member(read, "read_bytes", name="workspace read facet")
    _require_callable_member(launcher, "start", name="workspace process facet")

    async def read_text(path: Path) -> str:
        value = await resolve_operation(read.read_bytes(path))
        if not isinstance(value, bytes):
            raise TypeError("workspace read facet must return bytes")
        return value.decode("utf-8")

    async def path_exists(path: Path) -> bool:
        value = await resolve_operation(read.exists(path))
        if not isinstance(value, bool):
            raise TypeError("workspace read facet must return bool for exists")
        return value

    owner = _CodingLspProviderRuntimeOwner(
        _bind_coding_lsp_runtime_from_launcher(
            workspace_root=config.workspace_root,
            definitions=config.definitions,
            process_launcher=launcher,
            read_text=read_text,
            baseline_environment=config.baseline_environment,
            path_exists=path_exists,
        )
    )
    return CapabilityBundleValue(
        (
            CapabilityFacetBinding(
                CODING_LSP_SEMANTIC_FACET,
                _CodingLspSessionView(owner),
            ),
            CapabilityFacetBinding(
                CODING_LSP_TOOL_RUNTIME_FACET,
                _CodingLspToolRuntimeView(owner),
            ),
            CapabilityFacetBinding(
                CODING_LSP_DIAGNOSTICS_FACET,
                _CodingLspDiagnosticsView(owner),
            ),
        )
    )


async def dispose_coding_lsp_provider(value: CapabilityBundleValue) -> None:
    """Dispose only the runtime returned by this complete-Bundle factory."""

    if not isinstance(value, CapabilityBundleValue):
        raise TypeError("Coding LSP Provider disposer requires a Bundle value")
    session = value.require(CODING_LSP_SEMANTIC_FACET)
    tools = value.require(CODING_LSP_TOOL_RUNTIME_FACET)
    diagnostics = value.require(CODING_LSP_DIAGNOSTICS_FACET)
    if (
        not isinstance(session, _CodingLspSessionView)
        or not isinstance(tools, _CodingLspToolRuntimeView)
        or not isinstance(diagnostics, _CodingLspDiagnosticsView)
    ):
        raise TypeError("Coding LSP Provider Bundle contains a foreign access view")
    if session._owner is not tools._owner or session._owner is not diagnostics._owner:
        raise ValueError("Coding LSP Provider Bundle facets do not share one runtime")
    await session._owner.dispose()


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


def _string_mapping(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        _reject(f"{name} must map strings to strings")
    return dict(cast(Mapping[str, str], value))


def _is_sequence(
    value: object,
) -> TypeGuard[list[object] | tuple[object, ...]]:
    return isinstance(value, list | tuple)


def _require_callable_member(value: object, member: str, *, name: str) -> None:
    if not callable(getattr(value, member, None)):
        raise TypeError(f"Coding LSP Provider {name} is invalid")


def _reject(message: str) -> Never:
    raise CodingLspPluginConfigError(message)


__all__ = [
    "CODING_LSP_CAPABILITY_DEFINITION",
    "CODING_LSP_DIAGNOSTICS_FACET",
    "CODING_LSP_PLUGIN_CONFIG_VERSION",
    "CODING_LSP_SEMANTIC_FACET",
    "CODING_LSP_SESSION_REQUIREMENT",
    "CODING_LSP_TOOL_RUNTIME_FACET",
    "CODING_LSP_TOOL_RUNTIME_REQUIREMENT",
    "CODING_LSP_WORKSPACE_REQUIREMENT",
    "CodingLspPluginConfigError",
    "CodingLspPluginConfigV1",
    "CodingLspSessionCapabilityConsumer",
    "CodingLspToolRuntimeCapabilityConsumer",
    "CodingLspToolRuntimePort",
    "coding_lsp_capability_provider",
    "create_coding_lsp_provider",
    "dispose_coding_lsp_provider",
]
