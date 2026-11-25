"""Production Embedded first-input coordination for Coding Resume."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from loushang.agent import ThinkingLevel
from loushang.ai.model import Model, ModelSelection
from loushang.coding.composition.bootstrap import BootstrapServices, NoToolsMode
from loushang.coding.composition.capability_plugins import (
    require_coding_resume_plugin_effect_settlement,
)
from loushang.coding.resume.activation_attempt import (
    CodingActivationAttemptV1,
)
from loushang.coding.resume.first_input import (
    prepare_first_input_effects,
    require_first_input_attempt,
    require_first_input_plan,
)
from loushang.coding.resume.history import (
    CodingResumeHistoryPreview,
    CodingResumeRecentPage,
)
from loushang.coding.resume.input_lookup import CodingResumeInputLookupQueryV1
from loushang.coding.resume.permission_confirmation import NativeResumePolicy
from loushang.coding.runtime.agent_session_runtime import (
    AgentSessionRuntime,
    CodingRuntimePreparedResume,
)
from loushang.harness.approval import (
    ApprovalOutcome,
    ApprovalPermissionsSnapshot,
    InteractiveApprovalResolver,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.permissions import PermissionProfileSnapshot
from loushang.harness.session.approval_interaction import (
    _apply_permission_action,
    _open_approval_presentation,
)
from loushang.harness.session.facade import ApprovalPresentationLease
from loushang.harnesstui.conversation.agent_binding import (
    agent_image_parts_from_prompt_attachments,
)
from loushang.harnesstui.conversation.control import ConversationTextAction

from .plugin_effects import (
    require_no_capability_plugin_effects as _require_no_capability_plugin_effects,  # noqa: F401
)
from .plugin_effects import (
    resume_capability_plugins_required as _resume_capability_plugins_required,  # noqa: F401
)


@dataclass(slots=True)
class EmbeddedResumeStartup:
    """History-first CLI state retained before an executable Session exists."""

    target: str | Path
    history: CodingResumeHistoryPreview | CodingResumeRecentPage
    model: Model | ModelSelection | None = None


@dataclass(slots=True)
class EmbeddedResumeApprovalInteraction:
    """Screen interaction over the retained Root resolver before Session birth."""

    resolver: InteractiveApprovalResolver
    settings_manager: SettingsManager
    _presenter_generation: int = 0

    def bind_presenter(
        self,
        presenter: Callable[[dict[str, object]], Awaitable[None] | None],
        *,
        dismisser: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> ApprovalPresentationLease:
        self._presenter_generation += 1
        generation = self._presenter_generation
        return _open_approval_presentation(
            self.resolver,
            presenter,
            dismisser=dismisser,
            close_callback=lambda _reason: self._close_presenter(generation),
        )

    async def respond(
        self,
        action_id: str,
        *,
        outcome: ApprovalOutcome,
        reason: str | None = None,
    ) -> bool:
        return await self.resolver.handle_result(
            action_id, outcome=outcome, reason=reason
        )

    def permissions_snapshot(self) -> ApprovalPermissionsSnapshot:
        return self.resolver.permissions_snapshot()

    def permission_profile_snapshot(self) -> PermissionProfileSnapshot:
        return self.settings_manager.get_permission_profile_snapshot()

    async def apply_permission_action(self, action: str) -> bool:
        return await _apply_permission_action(
            action,
            resolver=self.resolver,
            set_permission_profile=self.settings_manager.set_permission_profile,
            require_profile_id=False,
        )

    def _close_presenter(self, generation: int) -> None:
        if generation != self._presenter_generation:
            return
        self.resolver.set_request_presenter(None)


@dataclass(frozen=True, slots=True)
class EmbeddedResumeInputCoordinator:
    """Join current Embedded owners for exactly one history-screen input."""

    runtime: AgentSessionRuntime
    services: BootstrapServices
    policy_evaluator: NativeResumePolicy
    model: Model | ModelSelection | None = None
    thinking_level: ThinkingLevel | None = None
    no_tools: NoToolsMode | bool | None = None
    worker_candidate_plugin_id: str | None = None
    workspace_writable: bool = True
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000
    id_factory: Callable[[], str] = lambda: uuid4().hex

    def __post_init__(self) -> None:
        if type(self.runtime) is not AgentSessionRuntime:
            raise TypeError("Embedded Resume requires the native Coding Root")
        if not isinstance(self.services, BootstrapServices):
            raise TypeError("Embedded Resume services are invalid")
        if type(self.workspace_writable) is not bool:
            raise TypeError("Embedded Resume workspace mode is invalid")

    async def prepare_input(
        self,
        *,
        session_file: str | Path,
        history: CodingResumeHistoryPreview,
        action: ConversationTextAction,
        observe_input_identity: Callable[[CodingResumeInputLookupQueryV1], None],
    ) -> CodingRuntimePreparedResume:
        plan = await self.runtime.prepare_configured_resume_plan(history)
        require_first_input_plan(plan)
        workspace = Path(plan.workspace_root)
        subject_digest = self.runtime.embedded_resume_subject_digest()
        approval_owner = self.runtime.embedded_resume_approval_owner()
        epoch_fingerprint = self.runtime.prepare_embedded_resume_epoch(
            workspace,
            settings_manager=self.services.settings_manager,
        )
        effects = prepare_first_input_effects(
            plan,
            history=history,
            session_dir=Path(self.runtime.session_dir),
            settings_manager=self.services.settings_manager,
            no_tools=self.no_tools,
        )
        worker_owner = (
            self.runtime.embedded_resume_worker_effect_owner(workspace)
            if self.worker_candidate_plugin_id is not None
            else None
        )
        attempt, settle = effects.bind(
            attempt_id=f"resume-attempt:{self.id_factory()}",
            request_id=f"resume-input:{self.id_factory()}",
            epoch_fingerprint=epoch_fingerprint,
            subject_digest=subject_digest,
            clock=self.clock_ms,
            worker_owner=worker_owner,
            allowed_external_owner_ids=(
                frozenset({"harness.worker-activation"})
                if worker_owner is not None
                else frozenset()
            ),
            verify_plugin_effects=lambda *args, **kwargs: (
                require_coding_resume_plugin_effect_settlement(*args, **kwargs)
            ),
        )

        def admit(observed: CodingActivationAttemptV1) -> None:
            self.runtime.require_current_embedded_resume_subject(
                require_first_input_attempt(observed),
                approval_owner=approval_owner,
            )

        created_at = self.now()
        if not isinstance(created_at, datetime) or created_at.tzinfo is None:
            raise TypeError("Embedded Resume clock must be timezone-aware")
        return await self.runtime.prepare_resume_continuation(
            session_file=session_file,
            plan=plan,
            current_owner_inputs=plan.owner_inputs,
            attempt=attempt,
            input_record_id=f"resume-record:{self.id_factory()}",
            text=action.text,
            images=(
                list(
                    agent_image_parts_from_prompt_attachments(
                        action.attachments
                    )
                    or ()
                )
                or None
            ),
            created_at=created_at,
            require_current_admission=admit,
            require_current_epoch_settlement=settle,
            services=self.services,
            model=self.model,
            thinking_level=self.thinking_level,
            no_tools=self.no_tools,
            approval_resolver=approval_owner,
            tool_policy_evaluator=self.policy_evaluator,
            observe_input_identity=observe_input_identity,
            worker_candidates=self.worker_candidate_plugin_id is not None,
            worker_candidate_plugin_id=self.worker_candidate_plugin_id,
        )


__all__ = [
    "EmbeddedResumeApprovalInteraction",
    "EmbeddedResumeInputCoordinator",
    "EmbeddedResumeStartup",
]
