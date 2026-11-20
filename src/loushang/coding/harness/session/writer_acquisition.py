"""Acquire one leased transcript writer from verified selected history."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from loushang.coding.composition.sets import resolve_coding_composition_set
from loushang.coding.resume.activation_plan import (
    ActivationOwnerInputRefV1,
    ResumePlanStaleError,
    SessionActivationPlanV1,
    build_session_activation_plan,
    require_current_resume_plan_inputs,
    require_current_resume_plan_source,
)
from loushang.coding.resume.history import (
    MAX_CODING_RESUME_HISTORY_BYTES,
    read_coding_resume_snapshot,
)
from loushang.coding.session import manager as _binding
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
from loushang.harness.transcript import (
    AgentTranscriptLifecycleSession,
    AgentTranscriptSessionFactory,
)

_ManagerT = TypeVar("_ManagerT", bound="_binding.SessionManager")


async def acquire_writer(
    manager_type: type[_ManagerT],
    session_file: str | Path,
    *,
    plan: SessionActivationPlanV1,
    current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
    factory: AgentTranscriptSessionFactory[
        ResolvedRuntimeProfile, RuntimeProfileBinding
    ]
    | None,
) -> _ManagerT:
    """Complete writer custody before exposing the restored manager."""

    if factory is None:
        factory = manager_type._factory_for_persistence(True)
    label = _binding._RESUME_WRITER_LABEL
    if not isinstance(factory, AgentTranscriptSessionFactory):
        raise TypeError(f"{label} factory is invalid")
    if not factory.owns_persistent_sessions:
        raise ValueError(f"{label} requires its application-owned factory")
    if (
        not isinstance(plan, SessionActivationPlanV1)
        or plan.status != "needs_final_validation"
    ):
        raise ValueError(f"{label} requires an available activation Plan")
    require_current_resume_plan_inputs(plan, current_owner_inputs)
    context = factory._discover_owned_context(session_file)
    history = await settled_io(
        read_coding_resume_snapshot,
        context.session_file,
        max_bytes=MAX_CODING_RESUME_HISTORY_BYTES,
        selected_leaf_id=plan.selected_leaf_id,
        expected_source_fingerprint=plan.source_fingerprint,
    )
    require_current_resume_plan_source(plan, history)
    if (
        context.header != history.header_preview.header
        or context.cwd != plan.workspace_root
        or build_session_activation_plan(
            history,
            resolve_coding_composition_set(
                plan.composition_comparison.candidate_set_id
            ),
            workspace_root=Path(plan.workspace_root),
            owner_inputs=plan.owner_inputs,
            owner_selections=plan.owner_selections,
        )
        != plan
    ):
        raise ResumePlanStaleError(f"{label} Plan differs from current history")
    binding = factory._resolve_binding_input(True)
    # Historical identity must still match. Epoch equality belongs to the new binding.
    _binding._validate_coding_restored_header(context.header, binding, False)
    result: list[_ManagerT] = []

    def project(
        session: AgentTranscriptLifecycleSession[RuntimeProfileBinding],
    ) -> None:
        manager = manager_type(lifecycle_session=session)
        manager._resume_runtime_publication_pending = True
        stale = f"{label} history changed during acquisition"
        if tuple(manager.get_entries()) != history.records:
            raise ResumePlanStaleError(stale)
        if history.selected_leaf_id is not None:
            # Restore initially selects the last record rather than the verified leaf.
            manager.branch(history.selected_leaf_id)
        if (
            manager.leaf_id != history.selected_leaf_id
            or tuple(manager.get_active_entries()) != history.selected_records
        ):
            raise ResumePlanStaleError(stale)
        manager._resume_writer_plan = plan
        manager._creation_factory = factory
        result.append(manager)

    await factory._construct_owned(context, binding, restore=True, _projection=project)
    return result[0]
