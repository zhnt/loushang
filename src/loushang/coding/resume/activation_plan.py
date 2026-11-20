"""Coding-owned, data-only Resume activation Plan envelope.

The envelope records observed identity and owner selection references. It is
discardable and never constitutes Writer, Plugin, Approval, or Worker authority.
"""

from __future__ import annotations

import hashlib as hashlib
import os
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
from loushang.coding.harness.session import activation_plan as _programs
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
from loushang.foundation.json import dump_json_value as dump_json_value
from loushang.harness.resources.loader import ResourceLoader

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_OWNER = re.compile(r"[a-z][a-z0-9._-]{0,127}\Z")
_GENERATION = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_SOURCE_FINGERPRINT = re.compile(r"stat-v1:(?:[0-9]+:){4}[0-9]+\Z")


_ACTIVATION_PLAN_MAX_REFS = 64
_ACTIVATION_PLAN_MAX_BYTES = 32 * 1024
_POLICY_INPUT_OWNER = "coding.policy"
_SUBJECT_INPUT_OWNER = "coding.subject"


_RESUME_PLAN_PROGRAM_VALUES = {
    "value_001": "activation Plan owner inputs exceed their budget",
    "value_002": "activation Plan owner inputs are invalid",
    "value_003": "activation Plan owner inputs must be sorted and unique",
    "value_004": "activation Plan owner selections exceed their budget",
    "value_005": "activation Plan owner selections are invalid",
    "value_006": "activation Plan owner selections must be sorted and unique",
    "value_007": "activation Plan Session id is invalid",
    "value_008": "activation Plan selected leaf id is invalid",
    "value_009": "activation Plan source fingerprint is invalid",
    "value_010": "activation Plan source content digest is invalid",
    "value_011": "activation Plan ancestry digest is invalid",
    "value_012": "activation Plan exceeds its byte budget",
    "value_013": "activation Plan selected history facts differ",
    "value_014": "Coding activation Plan",
    "value_017": "invalid Coding activation Plan",
    "value_018": "Coding activation Plan source changed",
    "value_019": "Coding activation Plan owner inputs are invalid",
    "value_020": "Coding activation Plan owner inputs must be sorted and unique",
    "value_021": "Coding activation Plan owner inputs changed",
}

_RESUME_PLAN_PROGRAM_BYTES = {
    "value_001": b"loushang.coding.session-activation-plan/v1\x00"
}


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

    return _programs.build_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=owner_inputs,
        owner_selections=owner_selections,
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

    return _programs.plan_resume(
        history,
        current_composition,
        workspace_root=workspace_root,
        resource_loader=resource_loader,
        work_probe=work_probe,
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

    return await _programs.plan_resume_async(
        history,
        current_composition,
        workspace_root=workspace_root,
        resource_loader=resource_loader,
        subject_digest=subject_digest,
        policy_digest=policy_digest,
        max_work_units=max_work_units,
        time_budget_seconds=time_budget_seconds,
        priority=priority,
    )


def require_current_resume_plan_source(
    plan: SessionActivationPlanV1,
    history: CodingResumeHistoryPreview,
) -> None:
    """Reject stale read evidence; live Writer and owner checks are separate."""

    return _programs.require_current_plan_source(plan, history)


def require_current_resume_plan_inputs(
    plan: SessionActivationPlanV1,
    current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
) -> None:
    """Reject a Plan whose owner-observed input dependencies have changed.

    The caller must obtain fresh references from each original owner. Matching
    references are only a cache-validity check; they do not admit execution.
    """

    return _programs.require_current_plan_inputs(plan, current_owner_inputs)


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
