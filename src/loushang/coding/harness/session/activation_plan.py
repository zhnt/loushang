"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeVar

from loushang.coding.resume import activation_plan as _binding

_RefT = TypeVar(
    "_RefT", bound="_binding.ActivationOwnerInputRefV1 | _binding.ActivationOwnerSelectionRefV1"
)


def _checked_owner_refs(
    refs: Sequence[_RefT],
    ref_type: type[_RefT],
    *,
    type_error: str,
    order_error: str,
    budget_error: str | None = None,
) -> tuple[_RefT, ...]:
    items = tuple(refs)
    if budget_error is not None and len(items) > _binding._ACTIVATION_PLAN_MAX_REFS:
        raise ValueError(budget_error)
    if any(not isinstance(item, ref_type) for item in items):
        raise TypeError(type_error)
    if items != tuple(sorted(items, key=lambda item: item.owner_id)) or len(
        {item.owner_id for item in items}
    ) != len(items):
        raise ValueError(order_error)
    return items


def build_activation_plan(
    history: _binding.CodingResumeHistoryPreview,
    current_composition: _binding.CodingCompositionSetPlan,
    *,
    workspace_root: _binding.Path,
    owner_inputs: Sequence[_binding.ActivationOwnerInputRefV1] = (),
    owner_selections: Sequence[_binding.ActivationOwnerSelectionRefV1] = (),
) -> _binding.SessionActivationPlanV1:
    """Aggregate historical facts and existing owner choices without effects."""

    _binding._require_plan_workspace_root(workspace_root)
    errors = _binding._RESUME_PLAN_PROGRAM_VALUES
    inputs = _checked_owner_refs(
        owner_inputs,
        _binding.ActivationOwnerInputRefV1,
        type_error=errors["value_002"],
        order_error=errors["value_003"],
        budget_error=errors["value_001"],
    )
    selections = _checked_owner_refs(
        owner_selections,
        _binding.ActivationOwnerSelectionRefV1,
        type_error=errors["value_005"],
        order_error=errors["value_006"],
        budget_error=errors["value_004"],
    )
    comparison = _binding.compare_coding_resume_composition(
        history, current_composition
    )
    session_id = history.header_preview.header.conversation_id
    if (
        type(session_id) is not str
        or _binding._IDENTIFIER.fullmatch(session_id) is None
    ):
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_007"])
    if history.selected_leaf_id is not None and (
        type(history.selected_leaf_id) is not str
        or _binding._IDENTIFIER.fullmatch(history.selected_leaf_id) is None
    ):
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_008"])
    if (
        type(history.source_fingerprint) is not str
        or _binding._SOURCE_FINGERPRINT.fullmatch(history.source_fingerprint) is None
    ):
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_009"])
    if (
        type(history.source_content_digest) is not str
        or _binding._DIGEST.fullmatch(history.source_content_digest) is None
    ):
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_010"])
    if history.selected_ancestry_digest is not None and (
        type(history.selected_ancestry_digest) is not str
        or _binding._DIGEST.fullmatch(history.selected_ancestry_digest) is None
    ):
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_011"])
    status: Literal["needs_final_validation", "unavailable"] = (
        "unavailable"
        if comparison.status == "unavailable"
        else "needs_final_validation"
    )
    if status == "needs_final_validation":
        projection = _binding.project_coding_activation_attempt_path_v2(
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
            raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_013"])
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
    encoded = _binding.dump_json_value(
        identity,
        name=_binding._RESUME_PLAN_PROGRAM_VALUES["value_014"],
        ensure_ascii=True,
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _binding._ACTIVATION_PLAN_MAX_BYTES:
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_012"])
    plan_id = _binding.hashlib.sha256(
        _binding._RESUME_PLAN_PROGRAM_BYTES["value_001"] + encoded
    ).hexdigest()
    return _binding.SessionActivationPlanV1(
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


def plan_resume(
    history: _binding.CodingResumeHistoryPreview,
    current_composition: _binding.CodingCompositionSetPlan,
    *,
    workspace_root: _binding.Path,
    resource_loader: _binding.ResourceLoader,
    work_probe: _binding.Callable[[], None] | None,
) -> _binding.SessionActivationPlanV1:
    """Plan from already displayed history through the original Resource owner.

    This synchronous entry is shared by foreground and future background
    callers. It retains a redacted input fingerprint, never a borrowed Package
    handle, Resource receipt, selected Runtime, or execution authority.
    """

    _binding._require_plan_workspace_root(workspace_root)
    inputs: tuple[_binding.ActivationOwnerInputRefV1, ...] = ()
    if (
        _binding.compare_coding_resume_composition(history, current_composition).status
        != "unavailable"
    ):
        receipt = resource_loader.preview_catalog_input_receipt(
            workspace_root, work_probe=work_probe
        )
        inputs = (
            _binding.ActivationOwnerInputRefV1(
                owner_id="resources.catalog", fingerprint=receipt.input_fingerprint
            ),
        )
    return build_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=inputs,
    )


async def plan_resume_async(
    history: _binding.CodingResumeHistoryPreview,
    current_composition: _binding.CodingCompositionSetPlan,
    *,
    workspace_root: _binding.Path,
    resource_loader: _binding.ResourceLoader,
    subject_digest: str,
    policy_digest: str,
    max_work_units: int,
    time_budget_seconds: float,
    priority: Literal["foreground", "background"],
) -> _binding.SessionActivationPlanV1:
    """Build the same Plan envelope using bounded Resource-owned native work.

    Subject and policy digests are caller-observed input dependencies, not
    permission evidence. The awaiting Product owns its reference and cancels
    that Task when it no longer needs the result. Resource owns native work
    settlement; no Runtime, Writer, or selected Package escapes this entry.
    """

    _binding._require_plan_workspace_root(workspace_root)
    inputs = _binding._resume_domain_input_refs(
        policy_digest=policy_digest, subject_digest=subject_digest
    )
    if (
        _binding.compare_coding_resume_composition(history, current_composition).status
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
        inputs += (_binding.ActivationOwnerInputRefV1("resources.catalog", fingerprint),)
    return build_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=inputs,
    )


def require_current_plan_source(
    plan: _binding.SessionActivationPlanV1, history: _binding.CodingResumeHistoryPreview
) -> None:
    """Reject stale read evidence; live Writer and owner checks are separate."""

    if not isinstance(plan, _binding.SessionActivationPlanV1):
        raise TypeError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_017"])
    current = _binding.resolve_coding_composition_set(
        plan.composition_comparison.candidate_set_id,
    )
    if (
        plan.session_id != history.header_preview.header.conversation_id
        or plan.selected_leaf_id != history.selected_leaf_id
        or plan.source_fingerprint != history.source_fingerprint
        or plan.source_content_digest != history.source_content_digest
        or plan.ancestry_digest != history.selected_ancestry_digest
        or plan.composition_comparison
        != _binding.compare_coding_resume_composition(history, current)
    ):
        raise _binding.ResumePlanStaleError(
            _binding._RESUME_PLAN_PROGRAM_VALUES["value_018"]
        )


def require_current_plan_inputs(
    plan: _binding.SessionActivationPlanV1,
    current_owner_inputs: _binding.Sequence[_binding.ActivationOwnerInputRefV1],
) -> None:
    """Reject a Plan whose owner-observed input dependencies have changed.

    The caller must obtain fresh references from each original owner. Matching
    references are only a cache-validity check; they do not admit execution.
    """

    if not isinstance(plan, _binding.SessionActivationPlanV1):
        raise TypeError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_017"])
    inputs = _checked_owner_refs(
        current_owner_inputs,
        _binding.ActivationOwnerInputRefV1,
        type_error=_binding._RESUME_PLAN_PROGRAM_VALUES["value_019"],
        order_error=_binding._RESUME_PLAN_PROGRAM_VALUES["value_020"],
    )
    if inputs != plan.owner_inputs:
        raise _binding.ResumePlanStaleError(
            _binding._RESUME_PLAN_PROGRAM_VALUES["value_021"]
        )
