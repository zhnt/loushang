"""Production Embedded first-input coordination for Coding Resume."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from loushang.agent import ThinkingLevel
from loushang.ai.model import Model, ModelSelection
from loushang.coding._capability_plugin_composition import (
    prepare_coding_resume_plugin_effect_owners,
    require_coding_resume_plugin_effect_settlement,
)
from loushang.coding._capability_plugin_specs import CODING_CAPABILITY_PLUGIN_IDS
from loushang.coding._product_capability_plugin_composition import (
    prepare_coding_product_approval_state_root,
)
from loushang.coding.bootstrap import BootstrapServices, NoToolsMode
from loushang.coding.capabilities import (
    CODING_ARCH_CAPABILITY,
    CODING_LSP_CAPABILITY,
    coding_capability_mount_mode,
)
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
)
from loushang.coding.resume_activation_attempt_v2 import CodingActivationAttemptV2
from loushang.coding.resume_history import (
    CodingResumeHistoryPreview,
    CodingResumeRecentPage,
)
from loushang.coding.resume_input_lookup import CodingResumeInputLookupQueryV1
from loushang.coding.resume_permission_confirmation import NativeResumePolicy
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
from loushang.harness.permissions import (
    PermissionProfileScope,
    PermissionProfileSnapshot,
    permission_profile,
)
from loushang.harness.session.bootstrap_utils import normalize_no_tools
from loushang.harnesstui.conversation.agent_binding import (
    agent_image_parts_from_prompt_attachments,
)
from loushang.harnesstui.conversation.control import ConversationTextAction


@dataclass(slots=True)
class EmbeddedResumeStartup:
    """History-first CLI state retained before an executable Session exists."""

    target: str | Path
    history: CodingResumeHistoryPreview | CodingResumeRecentPage
    model: Model | ModelSelection | None = None


@dataclass(slots=True)
class _EmbeddedApprovalPresentationLease:
    interaction: EmbeddedResumeApprovalInteraction
    generation: int
    closed: bool = False

    def close(
        self,
        reason: str = "Approval presenter closed before approval was resolved",
    ) -> None:
        if self.closed:
            return
        self.closed = True
        self.interaction._close_presenter(self.generation)


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
    ) -> _EmbeddedApprovalPresentationLease:
        self._presenter_generation += 1
        generation = self._presenter_generation
        self.resolver.set_request_presenter(presenter, dismisser=dismisser)
        self.resolver.open_session()
        self.resolver.represent_pending_requests()
        return _EmbeddedApprovalPresentationLease(self, generation)

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
        kind, separator, value = action.partition(":")
        if not separator or not value:
            return False
        if kind == "set-profile":
            scope, scope_separator, profile_id = value.partition(":")
            if not scope_separator or scope not in {"session", "project", "user"}:
                return False
            requested = permission_profile(profile_id).profile_id
            self.settings_manager.set_permission_profile(
                requested,
                scope=cast(PermissionProfileScope, scope),
            )
            if scope != "session":
                self.settings_manager.set_permission_profile(requested, scope="session")
            return True
        if kind == "revoke":
            return self.resolver.revoke_grant(value)
        if kind == "revoke-policy":
            return self.resolver.revoke_policy_rule(value)
        if kind == "reopen":
            return await self.resolver.represent_request(value)
        return False

    def _close_presenter(self, generation: int) -> None:
        if generation != self._presenter_generation:
            return
        self.resolver.set_request_presenter(None)


def _resume_plugin_state_root(
    runtime: AgentSessionRuntime, *, session_id: str
) -> Path:
    state_id = hashlib.sha256(
        b"loushang.coding-capability-plugin-state/v1\0"
        + session_id.encode("utf-8")
    ).hexdigest()
    return (
        Path(runtime.session_dir)
        / "plugin-state"
        / "coding-capability-plugins"
        / state_id
    )


def _capability_plugins_enabled(
    *,
    plan_set_id: str,
    settings_manager: object | None,
    no_tools: NoToolsMode | bool | None,
) -> bool:
    mode = normalize_no_tools(no_tools)
    if mode == "all":
        return False
    if plan_set_id == "coding-minimal":
        return False
    lsp = coding_capability_mount_mode(settings_manager, CODING_LSP_CAPABILITY)
    if plan_set_id == "coding-standard":
        return lsp != "disabled"
    if plan_set_id == "coding-architecture":
        arch = coding_capability_mount_mode(
            settings_manager, CODING_ARCH_CAPABILITY
        )
        return lsp != "disabled" or arch != "disabled"
    raise ValueError("Coding Resume composition set is unsupported")


def _require_no_capability_plugin_effects(
    attempt: CodingActivationAttemptV2,
    receipt: Mapping[str, object],
    *,
    expected_set_id: str,
    allowed_owner_ids: frozenset[str] = frozenset(),
) -> None:
    if (
        {owner.owner_id for owner in attempt.effect_owners} != allowed_owner_ids
        or attempt.effect_classes
        or any(owner.effect_classes for owner in attempt.effect_owners)
    ):
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    revisions = receipt.get("selectedRevisions")
    if receipt.get("setId") != expected_set_id or not isinstance(revisions, list):
        raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")
    for raw in revisions:
        if not isinstance(raw, Mapping):
            raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")
        if raw.get("pluginId") in CODING_CAPABILITY_PLUGIN_IDS:
            raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")


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
        if plan.status != "needs_final_validation" or plan.ancestry_digest is None:
            raise CodingResumeRecoveryRequired("input.plan_unavailable")
        workspace = Path(plan.workspace_root)
        subject_digest = self.runtime.embedded_resume_subject_digest()
        approval_owner = self.runtime.embedded_resume_approval_owner()
        epoch_fingerprint = self.runtime.prepare_embedded_resume_epoch(
            workspace,
            settings_manager=self.services.settings_manager,
        )
        plugins_enabled = _capability_plugins_enabled(
            plan_set_id=plan.composition_comparison.candidate_set_id,
            settings_manager=self.services.settings_manager,
            no_tools=self.no_tools,
        )
        plugin_state_root = _resume_plugin_state_root(
            self.runtime, session_id=plan.session_id
        )
        plugin_owners = (
            prepare_coding_resume_plugin_effect_owners(
                session_id=plan.session_id,
                state_root=plugin_state_root,
            )
            if plugins_enabled
            else ()
        )
        worker_owner = (
            self.runtime.embedded_resume_worker_effect_owner(workspace)
            if self.worker_candidate_plugin_id is not None
            else None
        )
        owners = tuple(
            sorted(
                (*plugin_owners, *((worker_owner,) if worker_owner is not None else ())),
                key=lambda owner: owner.identity,
            )
        )
        attempt = CodingActivationAttemptV2(
            attempt_id=f"resume-attempt:{self.id_factory()}",
            request_id=f"resume-input:{self.id_factory()}",
            session_id=plan.session_id,
            original_leaf_id=plan.selected_leaf_id,
            ancestry_digest=plan.ancestry_digest,
            plan_fingerprint=plan.plan_id,
            epoch_fingerprint=epoch_fingerprint,
            subject_digest=subject_digest,
            effect_owners=owners,
        )
        def admit(observed: CodingActivationAttemptV1) -> None:
            if type(observed) is not CodingActivationAttemptV2:
                raise CodingResumeRecoveryRequired(
                    "input.effect_owner_set_unsupported"
                )
            self.runtime.require_current_embedded_resume_subject(
                observed,
                approval_owner=approval_owner,
            )

        def settle(
            observed: CodingActivationAttemptV1,
            receipt: Mapping[str, object],
        ) -> None:
            if type(observed) is not CodingActivationAttemptV2:
                raise CodingResumeRecoveryRequired(
                    "input.effect_owner_set_unsupported"
                )
            if plugin_owners:
                require_coding_resume_plugin_effect_settlement(
                    observed,
                    receipt,
                    state_root=prepare_coding_product_approval_state_root(
                        plugin_state_root
                    ),
                    clock=self.clock_ms,
                    allowed_external_owner_ids=(
                        frozenset({"harness.worker-activation"})
                        if worker_owner is not None
                        else frozenset()
                    ),
                )
            else:
                _require_no_capability_plugin_effects(
                    observed,
                    receipt,
                    expected_set_id=plan.composition_comparison.candidate_set_id,
                    allowed_owner_ids=(
                        frozenset({"harness.worker-activation"})
                        if worker_owner is not None
                        else frozenset()
                    ),
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
