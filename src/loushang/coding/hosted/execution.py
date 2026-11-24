"""Explicitly selected Coding execution port; default Hosted composition is unchanged."""

from __future__ import annotations

from dataclasses import replace
from secrets import token_hex
from typing import TYPE_CHECKING, cast

from loushang.ai.model import normalize_model_selection
from loushang.ai.model.selection import is_usable_model_selection
from loushang.apphost import SessionBindingKeyV1
from loushang.apphost.integrations._canonical_transcript_catalog import (
    session_identity_matches_open,
)
from loushang.apphost.integrations.resource_access import (
    SUBMISSION_DIGEST,
    SUBMISSION_ID,
    HostedResourceAccess,
)
from loushang.apphost.integrations.session_control import (
    _ExecutionSessionServiceAdapter,
)
from loushang.appserver.execution.model import ExecutionInputV1, ResourceRefV1
from loushang.appserver.execution.resources import (
    SessionResourceQueryV1,
    SessionResourceResultV1,
)
from loushang.appserver.execution.session_commands import (
    SessionCommandCatalogV1,
    SessionCommandInvocationV1,
    SessionCommandResultV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionModelsV1,
    SessionOpenSpecV1,
)
from loushang.appservice.execution_contract import ExecutionRequestV1
from loushang.appservice.execution_registry import ExecutionLimitsV1
from loushang.appservice.execution_service import HostedExecutionServiceBindingV1

from ._execution_work import (
    HostedResumeSubjectControl as HostedResumeSubjectControl,
)
from ._execution_work import (
    HostedResumeSubjectScope as HostedResumeSubjectScope,
)
from ._execution_work import (
    _require_current_coding_hosted_resume_subject as _require_current_coding_hosted_resume_subject,
)
from ._execution_work import (
    current_coding_hosted_resume_subject as current_coding_hosted_resume_subject,
)
from ._execution_work import (
    current_coding_hosted_resume_submission_id as current_coding_hosted_resume_submission_id,
)
from ._session_commands import CodingHostedSessionCommands
from .execution_goal import _HostedExecutionGoal
from .resume import CodingDeferredHostedSessionV1
from .service_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSessionBindingV1,
    CodingHostedSessionV1,
    CodingHostedSnapshotProjectionV1,
)
from .session import CodingHostedHistoryBindingV1, CodingRealHostedSessionV1

if TYPE_CHECKING:
    from .application import (
        CodingAppHostHostedSessionResolverV1,
        _LeasedCodingHostedBinding,
    )


def _admit_execution_projection(
    owner: _LeasedCodingHostedBinding, resolver: CodingAppHostHostedSessionResolverV1, request: SessionOpenSpecV1,
) -> None:
    """Seal only the managed resolver's admitted lease and selection view.

    This is Product-internal authority, never a caller-supplied identity
    override. Retain the original objects as well as their identity values
    so adapter construction cannot substitute a same-ID owner or control.
    """
    from .application import (
        CodingAppHostHostedSessionResolverV1,
        _LeasedCodingHostedBinding,
    )

    if type(owner) is not _LeasedCodingHostedBinding:
        raise ValueError("invalid managed execution owner")
    original = owner._binding.identity
    if (type(resolver) is not CodingAppHostHostedSessionResolverV1
            or not resolver._managed_selection or not resolver._execution
            or owner._runtime is not resolver._runtime
            or owner._lease.profile_id != resolver._profile_id
            or owner._lease.profile_binding is not owner._binding
            or owner._lease.binding_key != SessionBindingKeyV1(
                original.product_id, original.continuity_id, original.session_id)
            or not resolver.admits(request)
            or owner.identity != replace(original, scope=request.scope,
                                        scope_fingerprint=request.scope_fingerprint)
            or not session_identity_matches_open(request, owner.identity)
            or owner._execution_projection is not None or owner._close_task is not None):
        raise ValueError("invalid managed execution projection")
    owner._execution_projection = (
        owner._binding, owner._lease, owner._runtime, original, owner.identity, owner.control,
        owner._lease.profile_id, owner,
    )

def _owns_execution_projection(owner: _LeasedCodingHostedBinding, binding: object) -> bool:
    proof = owner._execution_projection
    return bool(
        proof is not None and proof[7] is owner and binding is owner._binding is proof[0]
        and owner._lease is proof[1] and owner._runtime is proof[2]
        and owner._binding.identity == proof[3] and owner.identity == proof[4]
        and owner.control is proof[5]
        and owner._lease.profile_binding is binding
        and owner._lease.profile_id == proof[6]
        and owner._lease.binding_key == SessionBindingKeyV1(
            owner.identity.product_id, owner.identity.continuity_id, owner.identity.session_id)
        and owner._close_task is None
    )


class CodingHostedExecutionSessionV1(
    _ExecutionSessionServiceAdapter[CodingHostedSnapshotProjectionV1, CodingHostedEventProjectionV1],
    CodingHostedSessionV1,
    _HostedExecutionGoal,
):
    """Own the optional capability and the legacy surface on one real binding.

    The caller transfers exclusive binding ownership. No second Hosted adapter
    or direct input driver may run against that same AgentSession concurrently.
    """

    def __init__(
        self,
        binding: CodingRealHostedSessionV1 | CodingDeferredHostedSessionV1,
        *,
        owner: CodingHostedSessionBindingV1 | None = None,
    ) -> None:
        if type(binding) not in {CodingRealHostedSessionV1, CodingDeferredHostedSessionV1}:
            raise TypeError("execution requires a Coding Product binding")
        if owner is not None:
            from .application import _LeasedCodingHostedBinding

            projected = (type(owner) is _LeasedCodingHostedBinding
                         and _owns_execution_projection(owner, binding))
            if (owner.control is not binding.control
                    or (type(owner) is _LeasedCodingHostedBinding
                        and owner._identity is not None and not projected)
                    or owner.identity != binding.identity and not projected):
                raise ValueError("execution close owner must own the exact Product binding")
        self._product_binding = binding
        self._resource_access: HostedResourceAccess | None = None
        if type(binding) is CodingRealHostedSessionV1:
            binding.claim_execution(self._idle_for_interactive_goal)
        try:
            super().__init__(binding if owner is None else owner, execution_submission=type(binding) is CodingDeferredHostedSessionV1)
        except BaseException:
            if type(binding) is CodingRealHostedSessionV1:
                binding.release_failed_execution_claim()
            raise
        self._start_execution_observation(binding)

    def _allows_interactive_goal(self) -> bool:
        return type(self) is CodingHostedExecutionSessionV1

    def require_submission_ready(self) -> None:
        self._require_open()
        if not self._product_binding.execution_available:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        if self._model_lock.locked() or not is_usable_model_selection(
            normalize_model_selection(self._product_binding.current_model)
        ):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def _resources(self) -> HostedResourceAccess:
        if self._resource_access is None:
            self._resource_access = self._product_binding.create_resource_access()
        return self._resource_access

    def resource_submission_digest(self, submission_id: str) -> str | None:
        try:
            return self._resources().submission_digest(submission_id)
        except (ValueError, OSError):
            raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE) from None

    def require_resource_input(self, refs: tuple[ResourceRefV1, ...]) -> None:
        model = self._product_binding.current_model
        if self._resources().images(refs) and (not model or not model.supports_image_input):
            raise AppServiceError(AppErrorCodeV1.IMAGE_INPUT_UNSUPPORTED)

    def session_resource(self, query: SessionResourceQueryV1) -> SessionResourceResultV1:
        self._require_open()
        return self._resources().exchange(query)

    def _session_commands(self) -> CodingHostedSessionCommands | None:
        binding = self._product_binding
        active = binding._active if isinstance(binding, CodingDeferredHostedSessionV1) else binding
        return CodingHostedSessionCommands(active._session) if active is not None else None

    async def session_command_catalog(self, prefix: str) -> SessionCommandCatalogV1:
        self._require_open()
        commands = self._session_commands()
        if commands is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await commands.catalog(prefix)

    async def read_session_command(self, invocation: SessionCommandInvocationV1) -> SessionCommandResultV1:
        self._require_open()
        commands = self._session_commands()
        if commands is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await commands.read(invocation)

    def require_command_ready(self, invocation: SessionCommandInvocationV1) -> None:
        self._require_open()
        commands = self._session_commands()
        if commands is None or not self._product_binding.execution_available or self._model_lock.locked():
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        commands.require_ready(invocation)

    def start_execution(self, request: ExecutionRequestV1) -> None:
        if request.command is not None:
            self.require_command_ready(request.command)
            commands = self._session_commands()
            assert commands is not None
            self._guard.start(request, commands.create_work(request.command, self._product_binding.wait_for_title))
            return
        self.require_submission_ready()
        metadata = {
            SUBMISSION_ID: request.submission_id,
            SUBMISSION_DIGEST: ExecutionInputV1(request.text, request.resource_refs).digest(),
            **self._resources().input_metadata(request.resource_refs),
        } if request.resource_refs and request.submission_id is not None else None
        images = self._resources().images(request.resource_refs) if request.resource_refs else None
        text = request.text if request.text or images else "Use the attached Session resources."
        self._guard.start(
            request,
            self._product_binding.create_execution_work(
                text, lambda: self._guard.interrupt_requested, images,
                metadata
            ),
        )

    async def _select_model(
        self, model_id: str, thinking_level: str | None = None,
    ) -> SessionModelsV1:
        binding = self._product_binding
        if isinstance(binding, CodingRealHostedSessionV1) and binding.goal_command_running:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        await binding.wait_for_title()
        state = self._guard.state
        if state is not None and not state.status.terminal:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await super()._select_model(model_id, thinking_level)

    def _release_execution_resources(self) -> None:
        if self._resource_access is not None:
            self._resource_access.close()


def _select_coding_execution_port(port: object) -> CodingHostedExecutionSessionV1 | None:
    return port if isinstance(port, CodingHostedExecutionSessionV1) else None


def create_coding_execution_service_binding(
    application_id: str, *, service_instance_id: str | None = None,
    limits: ExecutionLimitsV1 = ExecutionLimitsV1(),
) -> HostedExecutionServiceBindingV1:
    """Explicit composition selection; create a fresh value per application instance."""
    return HostedExecutionServiceBindingV1(
        application_id, service_instance_id or token_hex(16),
        _select_coding_execution_port,
        limits,
    )


def create_leased_coding_execution_session(
    binding: object, owner: CodingHostedSessionBindingV1,
) -> CodingHostedSessionV1:
    if type(binding) is CodingHostedHistoryBindingV1:
        return CodingHostedSessionV1(owner, execution_submission=True)
    if type(binding) not in {
        CodingRealHostedSessionV1,
        CodingDeferredHostedSessionV1,
    }:
        raise TypeError("execution requires a Coding Product Session")
    return CodingHostedExecutionSessionV1(
        cast(CodingRealHostedSessionV1 | CodingDeferredHostedSessionV1, binding),
        owner=owner,
    )


__all__ = ["CodingHostedExecutionSessionV1"]
