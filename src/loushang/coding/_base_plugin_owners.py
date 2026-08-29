"""Exact Tool and Command owner adapters for the data-only ``coding.base``."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol, cast

from loushang.coding.tool_pack import create_coding_builtin_tool_definitions
from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationOwner,
    RegistrationScope,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
)
from loushang.harness.session.command_controller import (
    SessionCommandGenerationRegistry,
)
from loushang.harness.session.commands.catalog import (
    list_standard_session_command_descriptors,
)
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.workspace.operations import (
    EditOperations,
    FindOperations,
    GrepOperations,
    LsOperations,
    ReadOperations,
    WriteOperations,
)

_PLUGIN_ID = "coding.base"
_TOOL_CONTRIBUTION_ID = "coding.builtin"
_TOOL_OWNER_ID = "tools.workspace"
_TOOL_CATALOG_ID = "harness.workspace.core"
_COMMAND_CONTRIBUTION_ID = "coding.standard"
_COMMAND_OWNER_ID = "commands.session"
_COMMAND_CATALOG_ID = "harness.session.standard"
_TOOL_NAMES = ("bash", "edit", "find", "grep", "ls", "read", "write")
_COMMAND_NAMES = (
    "branch",
    "changelog",
    "clone",
    "compact",
    "copy",
    "delete",
    "export",
    "extensions",
    "fork",
    "import",
    "new",
    "reload",
    "rename",
    "resume",
    "session",
    "tools",
    "tree",
)
_WORKSPACE_REQUIREMENT = CapabilityRequirement(
    capability="harness.workspace",
    facets=(
        WORKSPACE_EDIT_FACET,
        WORKSPACE_LIST_FACET,
        WORKSPACE_PROCESS_LAUNCH_FACET,
        WORKSPACE_READ_FACET,
        WORKSPACE_SEARCH_FACET,
        WORKSPACE_WRITE_FACET,
    ),
    compatible_contract=CapabilityContractRange.exact(1),
)


class CodingBaseToolRegistrationPort(Protocol):
    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease: ...


@dataclass(slots=True)
class CodingBaseToolRegistrationSlot:
    _port: CodingBaseToolRegistrationPort | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def bind(self, port: CodingBaseToolRegistrationPort) -> None:
        if self._port is not None:
            raise RuntimeError("Coding base Tool registration is already bound")
        if not callable(getattr(port, "stage_runtime_tool", None)):
            raise TypeError("Coding base Tool registration port is invalid")
        self._port = port

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease:
        if self._port is None:
            raise RuntimeError("Coding base Tool registration is not yet bound")
        return self._port.stage_runtime_tool(
            tool,
            owner=owner,
            enabled=enabled,
            source_info=source_info,
        )


class CodingBaseOwnerError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _CodingBaseSourceInfo:
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str


@dataclass(slots=True)
class _CodingBaseGeneration:
    scope: RegistrationScope = field(repr=False)
    kind: str

    async def dispose(self) -> None:
        report = await self.scope.dispose()
        if report.has_failures:
            raise CodingBaseOwnerError(
                f"Coding base {self.kind} generation disposal remains incomplete",
                code=f"coding_base_{self.kind}_generation_disposal_failed",
            )


@dataclass(slots=True)
class CodingBaseToolOwner:
    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    options: ToolsOptions = field(default_factory=ToolsOptions, repr=False)
    scope_id: str = ""
    _bound: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_admission(
            self.admission,
            owner_id=_TOOL_OWNER_ID,
            contribution_kind="tool_pack",
            contribution_id=_TOOL_CONTRIBUTION_ID,
            catalog_id=_TOOL_CATALOG_ID,
            identities=_TOOL_NAMES,
            requirements=(_WORKSPACE_REQUIREMENT,),
        )
        if not isinstance(self.options, ToolsOptions):
            raise TypeError("Coding base Tool owner options are invalid")
        _validate_owner_common(self.admission, self.authority_gate, self.scope_id)

    def bind(
        self,
        registration: CodingBaseToolRegistrationPort,
    ) -> SessionCapabilityOwnerGenerationBinding:
        if self._bound:
            raise RuntimeError("Coding base Tool owner was already bound")
        if not callable(getattr(registration, "stage_runtime_tool", None)):
            raise TypeError("Coding base Tool owner registration port is invalid")
        self._bound = True
        return _owner_binding(
            self.admission,
            self.authority_gate,
            stage=lambda captures: self._stage(captures, registration=registration),
            dispose=self._dispose,
        )

    def _stage(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
        *,
        registration: CodingBaseToolRegistrationPort,
    ) -> _CodingBaseGeneration:
        options = self._options_from_capture(captures)
        by_name = {
            item.name: item
            for item in create_coding_builtin_tool_definitions(options=options)
        }
        if set(by_name) != set(_TOOL_NAMES):
            raise RuntimeError("Coding base Tool catalog changed admitted identities")
        owner = _registration_owner(self.admission, self.scope_id)
        scope = RegistrationScope(owner)
        source_info = _CodingBaseSourceInfo(
            plugin_id=self.admission.plugin_id,
            contribution_id=self.admission.contribution_id,
            admission_fingerprint=self.admission.fingerprint,
        )
        try:
            for name in _TOOL_NAMES:
                scope.add(
                    registration.stage_runtime_tool(
                        by_name[name],
                        owner=owner,
                        source_info=source_info,
                    )
                )
            scope.commit()
        except BaseException as error:
            _rollback_scope(scope, error, kind="Tool")
            raise
        return _CodingBaseGeneration(scope=scope, kind="tool")

    def _options_from_capture(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> ToolsOptions:
        if len(captures) != 1:
            raise ValueError("Coding base Tool owner requires one Consumer capture")
        [capture] = captures
        if (
            not isinstance(capture, SessionCapabilityConsumerCapture)
            or capture.entry.admission_fingerprint != self.admission.fingerprint
            or capture.entry.requirement != _WORKSPACE_REQUIREMENT
        ):
            raise ValueError("Coding base Tool owner received another Consumer")
        facets = capture.facets
        launcher = facets.require(WORKSPACE_PROCESS_LAUNCH_FACET)
        if not callable(getattr(launcher, "start", None)):
            raise TypeError("Coding base Tool process facet is invalid")
        return replace(
            self.options,
            read_operations=cast(
                ReadOperations,
                facets.require(WORKSPACE_READ_FACET),
            ),
            ls_operations=cast(
                LsOperations,
                facets.require(WORKSPACE_LIST_FACET),
            ),
            find_operations=cast(
                FindOperations,
                facets.require(WORKSPACE_SEARCH_FACET),
            ),
            grep_operations=cast(
                GrepOperations,
                facets.require(WORKSPACE_SEARCH_FACET),
            ),
            write_operations=cast(
                WriteOperations,
                facets.require(WORKSPACE_WRITE_FACET),
            ),
            edit_operations=cast(
                EditOperations,
                facets.require(WORKSPACE_EDIT_FACET),
            ),
        )

    async def _dispose(self, value: object) -> None:
        if not isinstance(value, _CodingBaseGeneration) or value.kind != "tool":
            raise TypeError("Coding base Tool owner received a foreign generation")
        await value.dispose()


@dataclass(slots=True)
class CodingBaseCommandOwner:
    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    scope_id: str
    _bound: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_admission(
            self.admission,
            owner_id=_COMMAND_OWNER_ID,
            contribution_kind="command_pack",
            contribution_id=_COMMAND_CONTRIBUTION_ID,
            catalog_id=_COMMAND_CATALOG_ID,
            identities=_COMMAND_NAMES,
            requirements=(),
        )
        _validate_owner_common(self.admission, self.authority_gate, self.scope_id)

    def bind(
        self,
        registry: SessionCommandGenerationRegistry,
    ) -> SessionCapabilityOwnerGenerationBinding:
        if self._bound:
            raise RuntimeError("Coding base Command owner was already bound")
        if not isinstance(registry, SessionCommandGenerationRegistry):
            raise TypeError("Coding base Command registration port is invalid")
        self._bound = True
        return _owner_binding(
            self.admission,
            self.authority_gate,
            stage=lambda captures: self._stage(captures, registry=registry),
            dispose=self._dispose,
        )

    def _stage(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
        *,
        registry: SessionCommandGenerationRegistry,
    ) -> _CodingBaseGeneration:
        if captures:
            raise ValueError("Coding base Command owner declares no Consumers")
        descriptors = tuple(list_standard_session_command_descriptors())
        if tuple(sorted(item.name for item in descriptors)) != _COMMAND_NAMES:
            raise RuntimeError(
                "Coding base Command catalog changed admitted identities"
            )
        owner = _registration_owner(self.admission, self.scope_id)
        scope = RegistrationScope(owner)
        try:
            scope.add(
                registry.stage_pack(
                    descriptors,
                    owner=owner,
                    pack_id=_COMMAND_CATALOG_ID,
                )
            )
            scope.commit()
        except BaseException as error:
            _rollback_scope(scope, error, kind="Command")
            raise
        return _CodingBaseGeneration(scope=scope, kind="command")

    async def _dispose(self, value: object) -> None:
        if not isinstance(value, _CodingBaseGeneration) or value.kind != "command":
            raise TypeError("Coding base Command owner received a foreign generation")
        await value.dispose()


def _owner_binding(
    admission: OwnerContributionAdmissionRecord,
    authority_gate: SessionCapabilityOwnerAuthorityGate,
    *,
    stage,
    dispose,
) -> SessionCapabilityOwnerGenerationBinding:
    return SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=authority_gate,
        stage=stage,
        dispose=dispose,
    )


def _registration_owner(
    admission: OwnerContributionAdmissionRecord,
    scope_id: str,
) -> RegistrationOwner:
    return RegistrationOwner(
        owner_kind="product",
        owner_id=admission.owner_id,
        runtime_id=(f"{scope_id}:{admission.plugin_id}:{admission.contribution_id}"),
        generation=admission.candidate.instance_revision_ref.revision,
    )


def _rollback_scope(
    scope: RegistrationScope,
    error: BaseException,
    *,
    kind: str,
) -> None:
    if scope.state == "committed":
        scope.rollback_commit()
    if scope.state == "open":
        rollback = scope.rollback_admission()
        if rollback.has_failures:
            error.add_note(f"Coding base {kind} rollback remains incomplete")


def _validate_admission(
    admission: OwnerContributionAdmissionRecord,
    *,
    owner_id: str,
    contribution_kind: str,
    contribution_id: str,
    catalog_id: str,
    identities: tuple[str, ...],
    requirements: tuple[CapabilityRequirement, ...],
) -> None:
    if not isinstance(admission, OwnerContributionAdmissionRecord):
        raise TypeError("Coding base owner requires an exact admission")
    if (
        admission.owner_id != owner_id
        or admission.contribution_kind != contribution_kind
        or admission.plugin_id != _PLUGIN_ID
        or admission.contribution_id != contribution_id
        or admission.candidate.contribution.collection_id != catalog_id
        or admission.admitted_identities != identities
        or admission.requirements != requirements
    ):
        raise ValueError("Coding base owner admission is not the reserved pack")


def _validate_owner_common(
    admission: OwnerContributionAdmissionRecord,
    authority_gate: SessionCapabilityOwnerAuthorityGate,
    scope_id: str,
) -> None:
    if not isinstance(authority_gate, SessionCapabilityOwnerAuthorityGate):
        raise TypeError("Coding base owner requires an authority gate")
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise ValueError("Coding base owner scope id must not be empty")
    if admission.candidate.scope_id != scope_id:
        raise ValueError("Coding base owner scope does not match admission")


__all__ = [
    "CodingBaseCommandOwner",
    "CodingBaseOwnerError",
    "CodingBaseToolOwner",
    "CodingBaseToolRegistrationPort",
    "CodingBaseToolRegistrationSlot",
]
