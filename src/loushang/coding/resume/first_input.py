"""Bind the resume intent and its effect checks before Writer acquisition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from loushang.coding.composition.product_capability_plugins import (
    coding_session_plugin_state_relative_path,
    prepare_coding_product_approval_state_root,
)
from loushang.coding.resume.activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume.activation_attempt_v2 import CodingActivationAttemptV2
from loushang.coding.resume.plugin_effects import (
    require_no_capability_plugin_effects,
    resume_capability_plugins_required,
)

if TYPE_CHECKING:
    from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
    from loushang.coding.resume.activation_attempt_v2 import CodingResumeEffectOwnerV1
    from loushang.coding.resume.activation_plan import SessionActivationPlanV1
    from loushang.coding.resume.history import CodingResumeHistoryPreview
    from loushang.harness.session.bootstrap_utils import NoToolsMode


class _VerifyPluginEffects(Protocol):
    def __call__(
        self,
        attempt: CodingActivationAttemptV2,
        receipt: Mapping[str, object],
        *,
        state_root: Path,
        clock: Callable[[], int],
        allowed_external_owner_ids: frozenset[str] = ...,
    ) -> None: ...


def require_first_input_plan(plan: SessionActivationPlanV1) -> None:
    if plan.status != "needs_final_validation" or plan.ancestry_digest is None:
        raise CodingResumeRecoveryRequired("input.plan_unavailable")


def require_first_input_attempt(
    observed: CodingActivationAttemptV1,
) -> CodingActivationAttemptV2:
    if type(observed) is not CodingActivationAttemptV2:
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    return observed


@dataclass(frozen=True, slots=True)
class FirstInputEffects:
    """The original Plugin journal obligations for one Coding Resume plan."""

    plan: SessionActivationPlanV1
    plugin_state_root: Path
    plugin_owners: tuple[CodingResumeEffectOwnerV1, ...]

    def bind(
        self,
        *,
        attempt_id: str,
        request_id: str,
        epoch_fingerprint: str,
        subject_digest: str,
        clock: Callable[[], int],
        verify_plugin_effects: _VerifyPluginEffects,
        worker_owner: CodingResumeEffectOwnerV1 | None = None,
        allowed_external_owner_ids: frozenset[str] | None = None,
    ) -> tuple[
        CodingActivationAttemptV2,
        Callable[[CodingActivationAttemptV1, Mapping[str, object]], None],
    ]:
        owners = self.plugin_owners + (() if worker_owner is None else (worker_owner,))
        plan = self.plan
        attempt = CodingActivationAttemptV2(
            attempt_id=attempt_id,
            request_id=request_id,
            session_id=plan.session_id,
            original_leaf_id=plan.selected_leaf_id,
            ancestry_digest=cast(str, plan.ancestry_digest),
            plan_fingerprint=plan.plan_id,
            epoch_fingerprint=epoch_fingerprint,
            subject_digest=subject_digest,
            effect_owners=tuple(sorted(owners, key=lambda owner: owner.identity)),
        )

        def settle(
            observed: CodingActivationAttemptV1, receipt: Mapping[str, object]
        ) -> None:
            observed_attempt = require_first_input_attempt(observed)
            if not self.plugin_owners:
                verify_no_effects = require_no_capability_plugin_effects
                if allowed_external_owner_ids is not None:
                    verify_no_effects = partial(
                        verify_no_effects, allowed_owner_ids=allowed_external_owner_ids
                    )
                verify_no_effects(
                    observed_attempt,
                    receipt,
                    expected_set_id=self.plan.composition_comparison.candidate_set_id,
                )
                return
            plugin_check: _VerifyPluginEffects = verify_plugin_effects
            if allowed_external_owner_ids is not None:
                plugin_check = partial(
                    verify_plugin_effects,
                    allowed_external_owner_ids=allowed_external_owner_ids,
                )
            plugin_check(
                observed_attempt,
                receipt,
                state_root=prepare_coding_product_approval_state_root(self.plugin_state_root),
                clock=clock,
            )

        return attempt, settle


def prepare_first_input_effects(
    plan: SessionActivationPlanV1,
    *,
    history: CodingResumeHistoryPreview,
    session_dir: Path,
    settings_manager: object | None,
    no_tools: NoToolsMode | bool | None = None,
) -> FirstInputEffects:
    """Select the effect owners and identity before reserving an input ID."""
    from loushang.coding.composition.capability_plugins import (
        prepare_coding_resume_plugin_effect_owners,
    )

    plugins_enabled = resume_capability_plugins_required(
        plan_set_id=plan.composition_comparison.candidate_set_id,
        settings_manager=settings_manager,
        no_tools=no_tools,
        history=history,
    )
    state_root = session_dir / coding_session_plugin_state_relative_path(plan.session_id)
    owners = (
        prepare_coding_resume_plugin_effect_owners(
            session_id=plan.session_id, state_root=state_root
        )
        if plugins_enabled
        else ()
    )
    return FirstInputEffects(plan, state_root, owners)
