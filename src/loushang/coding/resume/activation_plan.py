"""Coding-owned, data-only Resume activation Plan envelope.

The envelope records observed identity and owner selection references. It is
discardable and never constitutes Writer, Plugin, Approval, or Worker authority.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding.composition.sets import (
    CodingCompositionSetPlan,
)
from loushang.coding.composition.sets import (
    resolve_coding_composition_set as resolve_coding_composition_set,
)
from loushang.coding.resume.activation_projection_v2 import (
    project_coding_activation_attempt_path_v2 as project_coding_activation_attempt_path_v2,
)
from loushang.coding.resume.composition_comparison import (
    CodingResumeCompositionComparisonV1,
)
from loushang.coding.resume.composition_comparison import (
    compare_coding_resume_composition as compare_coding_resume_composition,
)
from loushang.coding.resume.history import CodingResumeHistoryPreview
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.session._resume_continuation import (
    checked_activation_plan_owner_refs,
    project_activation_plan_identity,
    require_activation_plan_workspace_root,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_OWNER = re.compile(r"[a-z][a-z0-9._-]{0,127}\Z")
_GENERATION = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


_ACTIVATION_PLAN_MAX_REFS = 64
_ACTIVATION_PLAN_MAX_BYTES = 32 * 1024
_POLICY_INPUT_OWNER = "coding.policy"
_SUBJECT_INPUT_OWNER = "coding.subject"


_PLAN_LABEL = "Coding activation Plan"
_PLAN_DIGEST_DOMAIN = b"loushang.coding.session-activation-plan/v1\0"


class ResumePlanStaleError(ValueError):
    """The selected source or current composition changed after planning."""


@dataclass(frozen=True, slots=True)
class ActivationOwnerSelectionRefV1:
    """Redacted reference to a selection computed by its original owner."""

    owner_id: str
    fingerprint: str
    generation: str

    def __post_init__(self) -> None:
        if type(self.owner_id) is not str or _OWNER.fullmatch(self.owner_id) is None:
            raise ValueError("activation owner id is invalid")
        if (
            type(self.fingerprint) is not str
            or _DIGEST.fullmatch(self.fingerprint) is None
        ):
            raise ValueError("activation owner fingerprint is invalid")
        if (
            type(self.generation) is not str
            or _GENERATION.fullmatch(self.generation) is None
        ):
            raise ValueError("activation owner generation is invalid")


@dataclass(frozen=True, slots=True)
class ActivationOwnerInputRefV1:
    """Redacted input dependency only; it cannot prove a selected Resource."""

    owner_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        if type(self.owner_id) is not str or _OWNER.fullmatch(self.owner_id) is None:
            raise ValueError("activation input owner id is invalid")
        if (
            type(self.fingerprint) is not str
            or _DIGEST.fullmatch(self.fingerprint) is None
        ):
            raise ValueError("activation input fingerprint is invalid")


def _resume_domain_input_refs(
    *, policy_digest: str, subject_digest: str
) -> tuple[ActivationOwnerInputRefV1, ...]:
    return (
        ActivationOwnerInputRefV1(_POLICY_INPUT_OWNER, policy_digest),
        ActivationOwnerInputRefV1(_SUBJECT_INPUT_OWNER, subject_digest),
    )


@dataclass(frozen=True, slots=True)
class SessionActivationPlanV1:
    """Immutable Plan evidence awaiting live owner validation and admission."""

    plan_id: str
    session_id: str
    selected_leaf_id: str | None
    source_fingerprint: str
    source_content_digest: str
    ancestry_digest: str | None
    workspace_root: str
    composition_comparison: CodingResumeCompositionComparisonV1
    owner_inputs: tuple[ActivationOwnerInputRefV1, ...]
    owner_selections: tuple[ActivationOwnerSelectionRefV1, ...]
    status: Literal["needs_final_validation", "unavailable"]
    schema_version: int = 1


def build_session_activation_plan(
    history: CodingResumeHistoryPreview,
    current_composition: CodingCompositionSetPlan,
    *,
    workspace_root: Path,
    owner_inputs: Sequence[ActivationOwnerInputRefV1] = (),
    owner_selections: Sequence[ActivationOwnerSelectionRefV1] = (),
) -> SessionActivationPlanV1:
    """Aggregate historical facts and existing owner choices without effects."""

    require_activation_plan_workspace_root(workspace_root)
    inputs = checked_activation_plan_owner_refs(
        owner_inputs,
        ActivationOwnerInputRefV1,
        type_error="activation Plan owner inputs are invalid",
        order_error="activation Plan owner inputs must be sorted and unique",
        budget=(_ACTIVATION_PLAN_MAX_REFS, "activation Plan owner inputs exceed their budget"),
    )
    selections = checked_activation_plan_owner_refs(
        owner_selections,
        ActivationOwnerSelectionRefV1,
        type_error="activation Plan owner selections are invalid",
        order_error="activation Plan owner selections must be sorted and unique",
        budget=(_ACTIVATION_PLAN_MAX_REFS, "activation Plan owner selections exceed their budget"),
    )
    comparison = compare_coding_resume_composition(
        history, current_composition
    )
    identity = project_activation_plan_identity(
        history,
        session_id=history.header_preview.header.conversation_id,
        workspace_root=workspace_root,
        comparison={
            "originSetId": comparison.origin.set_id if comparison.origin else None,
            "originFingerprint": (
                comparison.origin.plan_fingerprint if comparison.origin else None
            ),
            "candidateSetId": comparison.candidate_set_id,
            "candidateFingerprint": comparison.candidate_fingerprint,
            "status": comparison.status,
            "differenceCodes": list(comparison.difference_codes),
            "reasonCodes": list(comparison.reason_codes),
        },
        inputs=inputs,
        selections=selections,
        project_path=project_coding_activation_attempt_path_v2,
        digest_domain=_PLAN_DIGEST_DOMAIN,
        label=_PLAN_LABEL,
        max_bytes=_ACTIVATION_PLAN_MAX_BYTES,
    )
    return SessionActivationPlanV1(
        **identity,
        composition_comparison=comparison,
        owner_inputs=inputs,
        owner_selections=selections,
    )


def plan_coding_resume(
    history: CodingResumeHistoryPreview,
    current_composition: CodingCompositionSetPlan,
    *,
    workspace_root: Path,
    resource_loader: ResourceLoader,
    work_probe: Callable[[], None] | None = None,
) -> SessionActivationPlanV1:
    """Plan from already displayed history through the original Resource owner.

    This synchronous entry is shared by foreground and future background
    callers. It retains a redacted input fingerprint, never a borrowed Package
    handle, Resource receipt, selected Runtime, or execution authority.
    """

    require_activation_plan_workspace_root(workspace_root)
    inputs: tuple[ActivationOwnerInputRefV1, ...] = ()
    if (
        compare_coding_resume_composition(history, current_composition).status
        != "unavailable"
    ):
        receipt = resource_loader.preview_catalog_input_receipt(
            workspace_root, work_probe=work_probe
        )
        inputs = (
            ActivationOwnerInputRefV1(
                owner_id="resources.catalog", fingerprint=receipt.input_fingerprint
            ),
        )
    return build_session_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=inputs,
    )


async def plan_coding_resume_async(
    history: CodingResumeHistoryPreview,
    current_composition: CodingCompositionSetPlan,
    *,
    workspace_root: Path,
    resource_loader: ResourceLoader,
    subject_digest: str,
    policy_digest: str,
    max_work_units: int,
    time_budget_seconds: float,
    priority: Literal["foreground", "background"] = "background",
) -> SessionActivationPlanV1:
    """Build the same Plan envelope using bounded Resource-owned native work.

    Subject and policy digests are caller-observed input dependencies, not
    permission evidence. The awaiting Product owns its reference and cancels
    that Task when it no longer needs the result. Resource owns native work
    settlement; no Runtime, Writer, or selected Package escapes this entry.
    """

    require_activation_plan_workspace_root(workspace_root)
    inputs = _resume_domain_input_refs(
        policy_digest=policy_digest, subject_digest=subject_digest
    )
    if (
        compare_coding_resume_composition(history, current_composition).status
        != "unavailable"
    ):
        fingerprint = await resource_loader.preview_catalog_input_fingerprint(
            workspace_root,
            subject_digest=subject_digest,
            policy_digest=policy_digest,
            max_work_units=max_work_units,
            time_budget_seconds=time_budget_seconds,
            priority=priority,
        )
        inputs += (ActivationOwnerInputRefV1("resources.catalog", fingerprint),)
    return build_session_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=inputs,
    )


def require_current_resume_plan_source(
    plan: SessionActivationPlanV1,
    history: CodingResumeHistoryPreview,
) -> None:
    """Reject stale read evidence; live Writer and owner checks are separate."""

    if not isinstance(plan, SessionActivationPlanV1):
        raise TypeError(f"invalid {_PLAN_LABEL}")
    current = resolve_coding_composition_set(
        plan.composition_comparison.candidate_set_id,
    )
    if (
        plan.session_id != history.header_preview.header.conversation_id
        or plan.selected_leaf_id != history.selected_leaf_id
        or plan.source_fingerprint != history.source_fingerprint
        or plan.source_content_digest != history.source_content_digest
        or plan.ancestry_digest != history.selected_ancestry_digest
        or plan.composition_comparison
        != compare_coding_resume_composition(history, current)
    ):
        raise ResumePlanStaleError(
            f"{_PLAN_LABEL} source changed"
        )


def require_current_resume_plan_inputs(
    plan: SessionActivationPlanV1,
    current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
) -> None:
    """Reject a Plan whose owner-observed input dependencies have changed.

    The caller must obtain fresh references from each original owner. Matching
    references are only a cache-validity check; they do not admit execution.
    """

    if not isinstance(plan, SessionActivationPlanV1):
        raise TypeError(f"invalid {_PLAN_LABEL}")
    inputs = checked_activation_plan_owner_refs(
        current_owner_inputs,
        ActivationOwnerInputRefV1,
        type_error=f"{_PLAN_LABEL} owner inputs are invalid",
        order_error=f"{_PLAN_LABEL} owner inputs must be sorted and unique",
    )
    if inputs != plan.owner_inputs:
        raise ResumePlanStaleError(
            f"{_PLAN_LABEL} owner inputs changed"
        )


__all__ = [
    "ActivationOwnerInputRefV1",
    "ActivationOwnerSelectionRefV1",
    "ResumePlanStaleError",
    "SessionActivationPlanV1",
    "build_session_activation_plan",
    "plan_coding_resume",
    "plan_coding_resume_async",
    "require_current_resume_plan_inputs",
    "require_current_resume_plan_source",
]
