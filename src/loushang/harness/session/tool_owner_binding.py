"""Connect admitted Tool packs to existing Session and registration owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationOwner,
    RegistrationScope,
    registration_scope_retirement_receipt,
)
from loushang.harness.tools.core import ToolDefinition

from .capability_composition_inputs import (
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
)


class SessionToolRegistrationPort(Protocol):
    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease: ...


@dataclass(slots=True)
class DeferredToolRegistrationSlot:
    """Bind the original controller once after Session construction."""

    label: ClassVar[str] = "Session Tool"
    _port: SessionToolRegistrationPort | None = field(
        default=None, init=False, repr=False
    )

    def bind(self, port: SessionToolRegistrationPort) -> None:
        if self._port is not None:
            raise RuntimeError(f"{self.label} registration is already bound")
        if not callable(getattr(port, "stage_runtime_tool", None)):
            raise TypeError(f"{self.label} registration port is invalid")
        self._port = port

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease:
        port = self._port
        if port is None:
            raise RuntimeError(f"{self.label} registration is not yet bound")
        return port.stage_runtime_tool(
            tool, owner=owner, enabled=enabled, source_info=source_info
        )


@dataclass(frozen=True, slots=True)
class _ToolPackSourceInfo:
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str


@dataclass(frozen=True, slots=True)
class _ToolPackGeneration:
    scope: RegistrationScope = field(repr=False)
    family: object = field(repr=False)


class ToolPackBindingInputs(Protocol):
    """Read the original mutable fields at their original lifecycle points."""

    @property
    def admission(self) -> OwnerContributionAdmissionRecord: ...

    @property
    def scope_id(self) -> str: ...

    @property
    def mode(self) -> CapabilityMountMode: ...


def bind_admitted_tool_pack(
    inputs: ToolPackBindingInputs,
    authority_gate: SessionCapabilityOwnerAuthorityGate,
    *,
    registration: SessionToolRegistrationPort,
    definitions_from_captures: Callable[
        [tuple[SessionCapabilityConsumerCapture, ...]], tuple[ToolDefinition, ...]
    ],
    generation_family: object,
    label: str,
    disposal_error: Callable[[], Exception],
) -> SessionCapabilityOwnerGenerationBinding:
    """Wire one already-admitted pack; the Graph still drives its lifecycle."""
    bound_admission = inputs.admission

    def require_generation(value: object) -> _ToolPackGeneration:
        if (
            not isinstance(value, _ToolPackGeneration)
            or value.family is not generation_family
        ):
            raise TypeError(f"{label} owner received a foreign generation")
        return value

    def stage(
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> _ToolPackGeneration:
        definitions = tuple(definitions_from_captures(captures))
        admission = inputs.admission
        owner = RegistrationOwner(
            owner_kind="product",
            owner_id=admission.owner_id,
            runtime_id=f"{inputs.scope_id}:{admission.plugin_id}:{admission.contribution_id}",
            generation=admission.candidate.instance_revision_ref.revision,
        )
        scope = RegistrationScope(owner)
        source_info = _ToolPackSourceInfo(
            admission.plugin_id, admission.contribution_id, admission.fingerprint
        )
        try:
            for definition in definitions:
                scope.add(
                    registration.stage_runtime_tool(
                        definition,
                        owner=owner,
                        enabled=inputs.mode == "always",
                        source_info=source_info,
                    )
                )
        except BaseException as error:
            if scope.state == "committed":
                scope.rollback_commit()
            if scope.state == "open":
                rollback = scope.rollback_admission()
                if rollback.has_failures:
                    error.add_note(f"{label} staging rollback remains incomplete")
            raise
        return _ToolPackGeneration(scope, generation_family)

    async def dispose(value: object) -> None:
        report = await require_generation(value).scope.dispose()
        if report.has_failures:
            raise disposal_error()

    return SessionCapabilityOwnerGenerationBinding(
        owner_id=bound_admission.owner_id,
        contribution_kind=bound_admission.contribution_kind,
        plugin_id=bound_admission.plugin_id,
        contribution_id=bound_admission.contribution_id,
        admission_fingerprint=bound_admission.fingerprint,
        authority_gate=authority_gate,
        stage=stage,
        dispose=dispose,
        retirement_receipt=lambda value: registration_scope_retirement_receipt(
            require_generation(value).scope,
            contribution_ids=(inputs.admission.contribution_id,),
            allow_open=True,
        ),
        commit=lambda value: require_generation(value).scope.commit(),
        rollback_commit=lambda value: require_generation(value).scope.rollback_commit(),
    )
