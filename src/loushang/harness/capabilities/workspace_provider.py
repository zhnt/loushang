"""Standard Provider for the typed, authorized workspace Capability Bundle."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.workspace.operations import OperationResult, ToolOperations
from loushang.harness.workspace.process import (
    AuthorizedProcessLauncher,
    ProcessHandle,
    ProcessLaunchRequest,
)

WorkspaceProviderCleanup = Callable[[], None | Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _ReadFacet:
    _operations: ToolOperations = field(repr=False)

    def exists(self, path: Path) -> OperationResult[bool]:
        return self._operations.exists(path)

    def is_file(self, path: Path) -> OperationResult[bool]:
        return self._operations.is_file(path)

    def read_bytes(self, path: Path) -> OperationResult[bytes]:
        return self._operations.read_bytes(path)


@dataclass(frozen=True, slots=True)
class _ListFacet:
    _operations: ToolOperations = field(repr=False)

    def exists(self, path: Path) -> OperationResult[bool]:
        return self._operations.exists(path)

    def is_dir(self, path: Path) -> OperationResult[bool]:
        return self._operations.is_dir(path)

    def iterdir(self, path: Path) -> OperationResult[Iterable[Path]]:
        return self._operations.iterdir(path)


@dataclass(frozen=True, slots=True)
class _SearchFacet:
    _operations: ToolOperations = field(repr=False)

    def exists(self, path: Path) -> OperationResult[bool]:
        return self._operations.exists(path)

    def is_file(self, path: Path) -> OperationResult[bool]:
        return self._operations.is_file(path)

    def is_dir(self, path: Path) -> OperationResult[bool]:
        return self._operations.is_dir(path)

    def read_text(
        self,
        path: Path,
        *,
        newline: str | None = None,
    ) -> OperationResult[str]:
        return self._operations.read_text(path, newline=newline)

    def walk_files(self, path: Path) -> OperationResult[Iterable[Path]]:
        return self._operations.walk_files(path)


@dataclass(frozen=True, slots=True)
class _WriteFacet:
    _operations: ToolOperations = field(repr=False)

    def exists(self, path: Path) -> OperationResult[bool]:
        return self._operations.exists(path)

    def is_file(self, path: Path) -> OperationResult[bool]:
        return self._operations.is_file(path)

    def mkdir(
        self,
        path: Path,
        *,
        parents: bool,
        exist_ok: bool,
    ) -> OperationResult[None]:
        return self._operations.mkdir(path, parents=parents, exist_ok=exist_ok)

    def write_text(
        self,
        path: Path,
        content: str,
        *,
        newline: str | None = None,
    ) -> OperationResult[None]:
        return self._operations.write_text(path, content, newline=newline)


@dataclass(frozen=True, slots=True)
class _EditFacet:
    _operations: ToolOperations = field(repr=False)

    def exists(self, path: Path) -> OperationResult[bool]:
        return self._operations.exists(path)

    def is_file(self, path: Path) -> OperationResult[bool]:
        return self._operations.is_file(path)

    def read_text(
        self,
        path: Path,
        *,
        newline: str | None = None,
    ) -> OperationResult[str]:
        return self._operations.read_text(path, newline=newline)

    def write_text(
        self,
        path: Path,
        content: str,
        *,
        newline: str | None = None,
    ) -> OperationResult[None]:
        return self._operations.write_text(path, content, newline=newline)


@dataclass(frozen=True, slots=True)
class _AuthorizedProcessLaunchFacet:
    _launcher: AuthorizedProcessLauncher = field(repr=False)

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ProcessHandle:
        return await self._launcher.start(
            request,
            correlation_id=correlation_id,
            signal=signal,
        )


def workspace_capability_provider_binding(
    *,
    operations: ToolOperations,
    process_launcher: AuthorizedProcessLauncher,
    scope_instance_id: str,
    binding_input_fingerprint: str,
    cleanup: WorkspaceProviderCleanup | None = None,
    provider_id: str = "harness.workspace.standard",
    source_id: str = "builtin",
) -> CapabilityBundleProviderBinding:
    """Pair admitted workspace services with data-only Provider metadata.

    The process facet is already authorized. Raw process hosts, policy engines,
    approval gateways, sandbox backends, and credentials never enter the Bundle.
    """

    provider = CapabilityBundleProvider(
        capability_id=WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        provider_id=provider_id,
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(
            WORKSPACE_CAPABILITY_DEFINITION.contract_version
        ),
        facets=WORKSPACE_CAPABILITY_DEFINITION.facets,
        required_authorities=frozenset({"filesystem", "process"}),
        source_id=source_id,
        selection_rule="Product workspace selection",
    )

    def create(_context: CapabilityProviderContext) -> CapabilityBundleValue:
        return CapabilityBundleValue(
            facets=(
                CapabilityFacetBinding(WORKSPACE_READ_FACET, _ReadFacet(operations)),
                CapabilityFacetBinding(WORKSPACE_LIST_FACET, _ListFacet(operations)),
                CapabilityFacetBinding(
                    WORKSPACE_SEARCH_FACET,
                    _SearchFacet(operations),
                ),
                CapabilityFacetBinding(
                    WORKSPACE_WRITE_FACET,
                    _WriteFacet(operations),
                ),
                CapabilityFacetBinding(WORKSPACE_EDIT_FACET, _EditFacet(operations)),
                CapabilityFacetBinding(
                    WORKSPACE_PROCESS_LAUNCH_FACET,
                    _AuthorizedProcessLaunchFacet(process_launcher),
                ),
            )
        )

    async def dispose(_value: CapabilityBundleValue) -> None:
        if cleanup is None:
            return
        result = cleanup()
        if inspect.isawaitable(result):
            await result

    return CapabilityBundleProviderBinding(
        provider=provider,
        scope_instance_id=scope_instance_id,
        binding_input_fingerprint=binding_input_fingerprint,
        create=create,
        dispose=dispose if cleanup is not None else None,
    )


__all__ = ["WorkspaceProviderCleanup", "workspace_capability_provider_binding"]
