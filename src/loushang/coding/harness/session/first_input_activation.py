"""Bind the resume intent and its effect checks before Writer acquisition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from loushang.coding.composition.product_capability_plugins import (
    prepare_coding_product_approval_state_root,
)
from loushang.coding.resume.activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume.activation_attempt_v2 import CodingActivationAttemptV2
from loushang.coding.resume.plugin_effects import require_no_capability_plugin_effects

if TYPE_CHECKING:
    from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
    from loushang.coding.resume.activation_attempt_v2 import CodingResumeEffectOwnerV1
    from loushang.coding.resume.activation_plan import SessionActivationPlanV1


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


def build_first_input_attempt(
    plan: SessionActivationPlanV1,
    *,
    attempt_id: str,
    request_id: str,
    epoch_fingerprint: str,
    subject_digest: str,
    effect_owners: tuple[CodingResumeEffectOwnerV1, ...],
) -> CodingActivationAttemptV2:
    """Bind the admitted plan and exact effect-owner set to a durable intent."""
    return CodingActivationAttemptV2(
        attempt_id=attempt_id,
        request_id=request_id,
        session_id=plan.session_id,
        original_leaf_id=plan.selected_leaf_id,
        ancestry_digest=cast(str, plan.ancestry_digest),
        plan_fingerprint=plan.plan_id,
        epoch_fingerprint=epoch_fingerprint,
        subject_digest=subject_digest,
        effect_owners=effect_owners,
    )


def require_first_input_attempt(
    observed: CodingActivationAttemptV1,
) -> CodingActivationAttemptV2:
    if type(observed) is not CodingActivationAttemptV2:
        raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
    return observed


def bind_first_input_settlement(
    plan: SessionActivationPlanV1,
    *,
    plugin_owners: tuple[CodingResumeEffectOwnerV1, ...],
    plugin_state_root: Path,
    clock: Callable[[], int],
    allowed_external_owner_ids: frozenset[str] | None = None,
    verify_plugin_effects: _VerifyPluginEffects,
) -> Callable[[CodingActivationAttemptV1, Mapping[str, object]], None]:
    """Reconcile a receipt with the Plugin journals or prove no Plugin effects."""

    def settle(
        observed: CodingActivationAttemptV1, receipt: Mapping[str, object]
    ) -> None:
        attempt = require_first_input_attempt(observed)
        if not plugin_owners:
            verify_no_effects = require_no_capability_plugin_effects
            if allowed_external_owner_ids is not None:
                verify_no_effects = partial(
                    verify_no_effects, allowed_owner_ids=allowed_external_owner_ids
                )
            verify_no_effects(
                attempt,
                receipt,
                expected_set_id=plan.composition_comparison.candidate_set_id,
            )
            return

        plugin_check: _VerifyPluginEffects = verify_plugin_effects
        if allowed_external_owner_ids is not None:
            plugin_check = partial(
                verify_plugin_effects,
                allowed_external_owner_ids=allowed_external_owner_ids,
            )
        plugin_check(
            attempt,
            receipt,
            state_root=prepare_coding_product_approval_state_root(plugin_state_root),
            clock=clock,
        )

    return settle
