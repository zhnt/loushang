"""Coding-owned, data-only Resume activation Plan envelope.

The envelope records observed identity and owner selection references. It is
discardable and never constitutes Writer, Plugin, Approval, or Worker authority.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.foundation.json import dump_json_value
from loushang.harness.resources.loader import ResourceLoader

from .composition_sets import CodingCompositionSetPlan, resolve_coding_composition_set
from .resume_activation_projection_v2 import project_coding_activation_attempt_path_v2
from .resume_composition_comparison import (
    CodingResumeCompositionComparisonV1,
    compare_coding_resume_composition,
)
from .resume_history import CodingResumeHistoryPreview

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_OWNER = re.compile(r"[a-z][a-z0-9._-]{0,127}\Z")
_GENERATION = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_SOURCE_FINGERPRINT = re.compile(r"stat-v1:(?:[0-9]+:){4}[0-9]+\Z")


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

    _require_plan_workspace_root(workspace_root)
    inputs = tuple(owner_inputs)
    if len(inputs) > 64:
        raise ValueError("activation Plan owner inputs exceed their budget")
    if any(not isinstance(item, ActivationOwnerInputRefV1) for item in inputs):
        raise TypeError("activation Plan owner inputs are invalid")
    if inputs != tuple(sorted(inputs, key=lambda item: item.owner_id)) or len(
        {item.owner_id for item in inputs}
    ) != len(inputs):
        raise ValueError("activation Plan owner inputs must be sorted and unique")
    selections = tuple(owner_selections)
    if len(selections) > 64:
        raise ValueError("activation Plan owner selections exceed their budget")
    if any(not isinstance(item, ActivationOwnerSelectionRefV1) for item in selections):
        raise TypeError("activation Plan owner selections are invalid")
    if selections != tuple(sorted(selections, key=lambda item: item.owner_id)) or len(
        {item.owner_id for item in selections}
    ) != len(selections):
        raise ValueError("activation Plan owner selections must be sorted and unique")
    comparison = compare_coding_resume_composition(history, current_composition)
    session_id = history.header_preview.header.conversation_id
    if type(session_id) is not str or _IDENTIFIER.fullmatch(session_id) is None:
        raise ValueError("activation Plan Session id is invalid")
    if history.selected_leaf_id is not None and (
        type(history.selected_leaf_id) is not str
        or _IDENTIFIER.fullmatch(history.selected_leaf_id) is None
    ):
        raise ValueError("activation Plan selected leaf id is invalid")
    if (
        type(history.source_fingerprint) is not str
        or _SOURCE_FINGERPRINT.fullmatch(history.source_fingerprint) is None
    ):
        raise ValueError("activation Plan source fingerprint is invalid")
    if (
        type(history.source_content_digest) is not str
        or _DIGEST.fullmatch(history.source_content_digest) is None
    ):
        raise ValueError("activation Plan source content digest is invalid")
    if history.selected_ancestry_digest is not None and (
        type(history.selected_ancestry_digest) is not str
        or _DIGEST.fullmatch(history.selected_ancestry_digest) is None
    ):
        raise ValueError("activation Plan ancestry digest is invalid")
    status: Literal["needs_final_validation", "unavailable"] = (
        "unavailable"
        if comparison.status == "unavailable"
        else "needs_final_validation"
    )
    if status == "needs_final_validation":
        projection = project_coding_activation_attempt_path_v2(
            history.selected_records,
            current_session_id=session_id,
        )
        if (
            projection.ancestry_digest != history.selected_ancestry_digest
            or projection.binding_status != history.binding_status
            or projection.binding != history.binding
            or projection.status != history.activation_status
            or projection.attempt != history.pending_activation_attempt
            or projection.record_id != history.pending_activation_record_id
            or (
                history.selected_records[-1].record_id
                if history.selected_records
                else None
            )
            != history.selected_leaf_id
        ):
            raise ValueError("activation Plan selected history facts differ")
    identity = {
        "schemaVersion": 1,
        "sessionId": session_id,
        "selectedLeafId": history.selected_leaf_id,
        "sourceFingerprint": history.source_fingerprint,
        "sourceContentDigest": history.source_content_digest,
        "ancestryDigest": history.selected_ancestry_digest,
        "workspaceRoot": str(workspace_root),
        "composition": {
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
        "ownerSelections": [
            {
                "ownerId": item.owner_id,
                "fingerprint": item.fingerprint,
                "generation": item.generation,
            }
            for item in selections
        ],
        "ownerInputs": [
            {"ownerId": item.owner_id, "fingerprint": item.fingerprint}
            for item in inputs
        ],
        "status": status,
    }
    encoded = dump_json_value(
        identity,
        name="Coding activation Plan",
        ensure_ascii=True,
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 32 * 1024:
        raise ValueError("activation Plan exceeds its byte budget")
    plan_id = hashlib.sha256(
        b"loushang.coding.session-activation-plan/v1\0" + encoded
    ).hexdigest()
    return SessionActivationPlanV1(
        plan_id=plan_id,
        session_id=session_id,
        selected_leaf_id=history.selected_leaf_id,
        source_fingerprint=history.source_fingerprint,
        source_content_digest=history.source_content_digest,
        ancestry_digest=history.selected_ancestry_digest,
        workspace_root=str(workspace_root),
        composition_comparison=comparison,
        owner_inputs=inputs,
        owner_selections=selections,
        status=status,
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

    _require_plan_workspace_root(workspace_root)
    if (
        compare_coding_resume_composition(history, current_composition).status
        == "unavailable"
    ):
        return build_session_activation_plan(
            history,
            current_composition,
            workspace_root=workspace_root,
        )
    receipt = resource_loader.preview_catalog_input_receipt(
        workspace_root,
        work_probe=work_probe,
    )
    return build_session_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=(
            ActivationOwnerInputRefV1(
                owner_id="resources.catalog",
                fingerprint=receipt.input_fingerprint,
            ),
        ),
    )


def _require_plan_workspace_root(workspace_root: Path) -> None:
    if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
        raise ValueError("activation Plan requires a canonical absolute workspace root")
    if str(workspace_root) != os.path.normpath(str(workspace_root)):
        raise ValueError("activation Plan requires a canonical absolute workspace root")
    if len(str(workspace_root).encode("utf-8")) > 4096:
        raise ValueError("activation Plan workspace root exceeds its budget")


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

    _require_plan_workspace_root(workspace_root)
    domain_inputs = (
        ActivationOwnerInputRefV1("coding.policy", policy_digest),
        ActivationOwnerInputRefV1("coding.subject", subject_digest),
    )
    if (
        compare_coding_resume_composition(history, current_composition).status
        == "unavailable"
    ):
        return build_session_activation_plan(
            history,
            current_composition,
            workspace_root=workspace_root,
            owner_inputs=domain_inputs,
        )
    fingerprint = await resource_loader.preview_catalog_input_fingerprint(
        workspace_root,
        subject_digest=subject_digest,
        policy_digest=policy_digest,
        max_work_units=max_work_units,
        time_budget_seconds=time_budget_seconds,
        priority=priority,
    )
    return build_session_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=(
            *domain_inputs,
            ActivationOwnerInputRefV1(
                "resources.catalog",
                fingerprint,
            ),
        ),
    )


def require_current_resume_plan_source(
    plan: SessionActivationPlanV1,
    history: CodingResumeHistoryPreview,
) -> None:
    """Reject stale read evidence; live Writer and owner checks are separate."""

    if not isinstance(plan, SessionActivationPlanV1):
        raise TypeError("invalid Coding activation Plan")
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
        raise ResumePlanStaleError("Coding activation Plan source changed")


def require_current_resume_plan_inputs(
    plan: SessionActivationPlanV1,
    current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
) -> None:
    """Reject a Plan whose owner-observed input dependencies have changed.

    The caller must obtain fresh references from each original owner. Matching
    references are only a cache-validity check; they do not admit execution.
    """

    if not isinstance(plan, SessionActivationPlanV1):
        raise TypeError("invalid Coding activation Plan")
    inputs = tuple(current_owner_inputs)
    if any(not isinstance(item, ActivationOwnerInputRefV1) for item in inputs):
        raise TypeError("Coding activation Plan owner inputs are invalid")
    if inputs != tuple(sorted(inputs, key=lambda item: item.owner_id)) or len(
        {item.owner_id for item in inputs}
    ) != len(inputs):
        raise ValueError(
            "Coding activation Plan owner inputs must be sorted and unique"
        )
    if inputs != plan.owner_inputs:
        raise ResumePlanStaleError("Coding activation Plan owner inputs changed")


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
