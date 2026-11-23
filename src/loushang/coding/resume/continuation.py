"""Coding's initial Resume continuation sequence over existing owner entries.

The Product caller obtains current admission/confirmation before invoking this
entry. Owner callbacks remain mandatory; this coordinator issues no authority,
settles no external effects and supplies no restart or automatic replay grant.
"""

from __future__ import annotations

import inspect as inspect
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast as cast

from loushang.agent import ThinkingLevel
from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.ai.types import ImagePart
from loushang.ai.types import UserMessage as UserMessage
from loushang.coding.composition.bootstrap import BootstrapServices, NoToolsMode
from loushang.coding.composition.bootstrap import (
    coding_capability_plugin_state_root as _coding_capability_plugin_state_root,
)
from loushang.coding.composition.bootstrap import (
    create_resume_agent_session as _create_resume_agent_session,
)
from loushang.coding.composition.capability_plugins import CodingResumePluginParents
from loushang.coding.composition.product_capability_plugins import (
    prepare_coding_product_approval_state_root as prepare_coding_product_approval_state_root,
)
from loushang.coding.composition.sets import (
    resolve_coding_composition_set as resolve_coding_composition_set,
)
from loushang.coding.package.product_runtime import (
    CodingFencedProductApplicationSelection,
)
from loushang.coding.resume._cleanup import (
    CodingResumeContinuationCleanupFailure as CodingResumeContinuationCleanupFailure,
)
from loushang.coding.resume._cleanup import discard_candidate as discard_candidate
from loushang.coding.resume._cleanup import (
    retain_resume_cleanup_failure as retain_resume_cleanup_failure,
)
from loushang.coding.resume.activation_attempt import (
    CodingActivationAttemptV1,
)
from loushang.coding.resume.activation_attempt import (
    CodingResumeRecoveryRequired as CodingResumeRecoveryRequired,
)
from loushang.coding.resume.activation_attempt import (
    prepare_coding_activation_attempt_record as prepare_coding_activation_attempt_record,
)
from loushang.coding.resume.activation_attempt_v2 import (
    CodingActivationAttemptV2,
)
from loushang.coding.resume.activation_attempt_v2 import (
    prepare_coding_activation_attempt_v2_record as prepare_coding_activation_attempt_v2_record,
)
from loushang.coding.resume.activation_plan import (
    ActivationOwnerInputRefV1,
    SessionActivationPlanV1,
)
from loushang.coding.resume.binding import (
    CodingRuntimeBindingV1 as CodingRuntimeBindingV1,
)
from loushang.coding.resume.binding import (
    coding_user_payload_digest as coding_user_payload_digest,
)
from loushang.coding.resume.binding import (
    inspect_coding_runtime_binding as inspect_coding_runtime_binding,
)
from loushang.coding.resume.binding_v2 import (
    CODING_RUNTIME_BINDING_V2_METADATA_KEY as CODING_RUNTIME_BINDING_V2_METADATA_KEY,
)
from loushang.coding.resume.binding_v2 import (
    CodingRuntimeBindingV2 as CodingRuntimeBindingV2,
)
from loushang.coding.resume.binding_v2 import (
    decode_coding_runtime_binding_v2 as decode_coding_runtime_binding_v2,
)
from loushang.coding.resume.input_lookup import (
    CodingResumeInputLookupQueryV1,
)
from loushang.coding.resume.input_lookup import (
    coding_resume_input_record_digest as coding_resume_input_record_digest,
)
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session.manager import SessionManager
from loushang.harness.approval import InteractiveApprovalResolver
from loushang.harness.approval._plugin_resume_parents import plugin_resume_journals
from loushang.harness.approval.plugin_activation import (
    PluginActivationJournalError as PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionJournalError as PluginExecutionJournalError,
)
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
from loushang.harness.session._resume_continuation import prepare_resume_continuation
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.transcript import AgentTranscriptSessionFactory
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournal as WorkerActivationStateJournal,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError as WorkerActivationStateJournalError,
)
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


@dataclass(frozen=True, slots=True)
class CodingResumePreparedContinuation:
    """Original published Session awaiting its Product slot and model dispatch.

    The caller assumes the original Session's disposal responsibility on return.
    Adopting a Product slot still uses its existing lifecycle/Hosted binding owner.
    Input has been committed; callers must not resubmit it through normal prompt.
    """

    session: AgentSession
    attempt_id: str
    input_record_id: str
    input_lookup_query: CodingResumeInputLookupQueryV1


def _prepare_v2_plugin_parents(
    attempt: CodingActivationAttemptV2,
    *,
    worker_candidate_plugin_id: str | None,
) -> tuple[CodingResumePluginParents | None, ResumeEffectParentContextV1 | None]:
    owners = {owner.owner_id: owner for owner in attempt.effect_owners}
    plugin_ids = {
        'harness.plugin-execution',
        'harness.plugin-activation',
    }
    selected_plugin_ids = plugin_ids & owners.keys()
    if selected_plugin_ids and selected_plugin_ids != plugin_ids:
        raise CodingResumeRecoveryRequired(
            'input.effect_owner_set_unsupported'
        )
    worker_owner_id = 'harness.worker-activation'
    supported = plugin_ids | (
        {worker_owner_id} if worker_candidate_plugin_id else set()
    )
    unsupported = set(owners) - supported
    if (
        unsupported
        or attempt.effect_classes
        or any(owner.effect_classes for owner in attempt.effect_owners)
    ):
        raise CodingResumeRecoveryRequired(
            'input.effect_owner_set_unsupported'
        )
    worker_owner = owners.get(worker_owner_id)
    if (worker_candidate_plugin_id is None) != (worker_owner is None):
        raise CodingResumeRecoveryRequired(
            'input.effect_owner_set_unsupported'
        )
    worker_parent = None
    if worker_owner is not None:
        if worker_owner.phases != ("reservation", "start"):
            raise CodingResumeRecoveryRequired(
                'input.effect_owner_set_unsupported'
            )
        worker_parent = attempt.parent_context(worker_owner)
    if not selected_plugin_ids:
        return None, worker_parent
    if owners['harness.plugin-execution'].phases != (
        "declaration",
    ) or owners['harness.plugin-activation'].phases != (
        "activation",
    ):
        raise CodingResumeRecoveryRequired(
            'input.effect_owner_set_unsupported'
        )
    return (
        CodingResumePluginParents(
            definition=attempt.parent_context(
                owners['harness.plugin-execution']
            ),
            activation=attempt.parent_context(
                owners['harness.plugin-activation']
            ),
        ),
        worker_parent,
    )


def _require_v2_native_writer_protocols(
    manager_type: type[SessionManager],
) -> None:
    """Negotiate all accepted v2 writers without opening any durable source."""

    manager_type._require_resume_writer_capabilities(
        frozenset({'coding.resume-continuation/v2'})
    )
    probe_root = (
        Path.cwd().resolve(strict=False)
        / '.resume-protocol-probe'
    )
    try:
        plugin_resume_journals(
            "protocol-probe",
            probe_root / "definition-decisions.jsonl",
            probe_root / "activation-decisions.jsonl",
            require_resume_context=True,
        )
        WorkerActivationStateJournal(
            probe_root / 'worker-activation-state.jsonl',
            required_writer_capabilities=frozenset(
                {'harness.worker-activation.resume-context/v1'}
            ),
        )
    except (
        PluginExecutionJournalError,
        PluginActivationJournalError,
        WorkerActivationStateJournalError,
    ) as error:
        raise CodingResumeRecoveryRequired(
            'writer.resume_protocol_unsupported'
        ) from error


async def prepare_coding_resume_continuation(
    *,
    manager_type: type[SessionManager],
    session_file: str | Path,
    plan: SessionActivationPlanV1,
    current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
    attempt: CodingActivationAttemptV1,
    input_record_id: str,
    text: str,
    created_at: datetime,
    require_current_admission: Callable[[CodingActivationAttemptV1], None],
    require_current_epoch_settlement: Callable[
        [CodingActivationAttemptV1, Mapping[str, object]], None
    ],
    images: list[ImagePart] | None = None,
    services: BootstrapServices | None = None,
    model: Model | ModelSelection | None = None,
    thinking_level: ThinkingLevel | None = None,
    stream_fn: StreamFn | None = None,
    tools: list[ToolDefinition] | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    no_tools: NoToolsMode | bool | None = None,
    approval_resolver: InteractiveApprovalResolver | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
    observe_input_identity: Callable[[CodingResumeInputLookupQueryV1], None]
    | None = None,
    product_owner_selection: CodingFencedProductApplicationSelection | None = None,
    resume_writer_factory: AgentTranscriptSessionFactory[
        ResolvedRuntimeProfile,
        RuntimeProfileBinding,
    ]
    | None = None,
    worker_candidates: bool = False,
    worker_candidate_plugin_id: str | None = None,
) -> CodingResumePreparedContinuation:
    """Prepare one initial input, commit it once, then publish original owners.

    There is no retry, model dispatch or Product slot replacement here. Failure
    releases the undelivered original candidate/Writer without erasing history.
    Commit uncertainty requires original logical-input lookup, not another input.
    """

    if not isinstance(manager_type, type) or not issubclass(
        manager_type, SessionManager
    ):
        raise TypeError('Coding Resume requires its original SessionManager type')
    if isinstance(attempt, CodingActivationAttemptV1) and type(
        attempt
    ) not in {
        CodingActivationAttemptV1,
        CodingActivationAttemptV2,
    }:
        raise CodingResumeRecoveryRequired(
            'writer.resume_protocol_unsupported'
        )
    if product_owner_selection is not None and not isinstance(
        product_owner_selection,
        CodingFencedProductApplicationSelection,
    ):
        raise TypeError('Coding Resume Product application owner is invalid')
    if (
        type(worker_candidates) is not bool
        or (
            worker_candidate_plugin_id is not None
            and (
                not isinstance(worker_candidate_plugin_id, str)
                or not worker_candidate_plugin_id
                or worker_candidate_plugin_id != worker_candidate_plugin_id.strip()
            )
        )
        or (
            (worker_candidates or worker_candidate_plugin_id is not None)
            and product_owner_selection is None
        )
    ):
        raise ValueError('Coding Resume Worker requires its application Product owner')
    resume_plugin_parents: CodingResumePluginParents | None = None
    resume_worker_parent: ResumeEffectParentContextV1 | None = None
    if type(attempt) is CodingActivationAttemptV2:
        if worker_candidates and worker_candidate_plugin_id is None:
            raise CodingResumeRecoveryRequired(
                'input.effect_owner_set_unsupported'
            )
        resume_plugin_parents, resume_worker_parent = (
            _prepare_v2_plugin_parents(
                attempt,
                worker_candidate_plugin_id=worker_candidate_plugin_id,
            )
        )
        _require_v2_native_writer_protocols(manager_type)
    elif worker_candidate_plugin_id is not None:
        raise CodingResumeRecoveryRequired(
            'input.effect_owner_set_unsupported'
        )
    if (
        not isinstance(plan, SessionActivationPlanV1)
        or not isinstance(attempt, CodingActivationAttemptV1)
        or plan.status != "needs_final_validation"
        or attempt.session_id != plan.session_id
        or attempt.original_leaf_id != plan.selected_leaf_id
        or attempt.ancestry_digest != plan.ancestry_digest
        or attempt.plan_fingerprint != plan.plan_id
    ):
        raise ValueError('Coding Resume attempt differs from its activation Plan')
    if (
        type(input_record_id) is not str
        or _IDENTIFIER.fullmatch(input_record_id) is None
    ):
        raise ValueError('Coding Resume input record identity is invalid')
    if input_record_id == attempt.attempt_id:
        raise ValueError('Coding Resume intent and input require distinct record identities')
    if not isinstance(text, str) or (not text.strip() and not images):
        raise ValueError('Coding Resume requires nonempty user input')
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError('Coding Resume timestamp must be timezone-aware')
    if any(
        not callable(check) or inspect.iscoroutinefunction(check)
        for check in (
            require_current_admission,
            require_current_epoch_settlement,
        )
    ):
        raise TypeError('Coding Resume requires synchronous current owner checks')

    async def open_writer() -> SessionManager:
        return await manager_type._load_resume_writer(
            session_file,
            plan=plan,
            current_owner_inputs=current_owner_inputs,
            required_writer_capabilities=(
                frozenset({"coding.resume-continuation/v2"})
                if type(attempt) is CodingActivationAttemptV2
                else frozenset()
            ),
            _factory=resume_writer_factory,
        )

    def enroll_native_owners(manager: SessionManager) -> Callable[[], None]:
        parents = resume_plugin_parents
        assert parents is not None
        state_root = prepare_coding_product_approval_state_root(
            _coding_capability_plugin_state_root(manager, session_id=attempt.session_id)
        )

        def clock() -> int:
            return int(created_at.timestamp() * 1000)

        parents.enroll(session_id=attempt.session_id, state_root=state_root, clock=clock)

        def seal() -> None:
            parents.seal(session_id=attempt.session_id, state_root=state_root, clock=clock)

        return seal

    async def build_session(manager: SessionManager) -> AgentSession:
        return await _create_resume_agent_session(
            session_manager=manager,
            attempt_id=attempt.attempt_id,
            composition_set=resolve_coding_composition_set(
                plan.composition_comparison.candidate_set_id
            ),
            require_current_admission=require_current_admission,
            services=services,
            model=model,
            thinking_level=thinking_level,
            stream_fn=stream_fn,
            tools=tools,
            output_capture_factory=output_capture_factory,
            no_tools=no_tools,
            approval_resolver=approval_resolver,
            tool_policy_evaluator=tool_policy_evaluator,
            product_owner_selection=product_owner_selection,
            worker_candidates=worker_candidates,
            worker_candidate_plugin_id=worker_candidate_plugin_id,
            resume_plugin_parents=resume_plugin_parents,
            resume_worker_parent=resume_worker_parent,
            resume_effect_owner_ids=(
                frozenset(owner.owner_id for owner in attempt.effect_owners)
                if type(attempt) is CodingActivationAttemptV2
                else None
            ),
        )

    def prepare_binding(
        persisted: UserMessage,
    ) -> CodingRuntimeBindingV1 | CodingRuntimeBindingV2:
        payload_digest = coding_user_payload_digest(persisted)
        constructor = (
            partial(CodingRuntimeBindingV2, intent_digest=attempt.digest)
            if type(attempt) is CodingActivationAttemptV2
            else CodingRuntimeBindingV1
        )
        return constructor(
            attempt_id=attempt.attempt_id,
            input_id=attempt.request_id,
            record_id=input_record_id,
            session_id=attempt.session_id,
            original_leaf_id=attempt.original_leaf_id,
            ancestry_digest=attempt.ancestry_digest,
            subject_digest=attempt.subject_digest,
            origin_composition=plan.composition_comparison.origin,
            planned_fingerprint=attempt.plan_fingerprint,
            actual_fingerprint=attempt.epoch_fingerprint,
            payload_digest=payload_digest,
            difference_codes=plan.composition_comparison.difference_codes,
        )

    return await prepare_resume_continuation(
        product_label="Coding Resume",
        attempt=attempt,
        input_record_id=input_record_id,
        text=text,
        images=images,
        created_at=created_at,
        require_current_admission=require_current_admission,
        require_current_epoch_settlement=require_current_epoch_settlement,
        open_writer=open_writer,
        build_session=build_session,
        enroll_native_owners=enroll_native_owners if resume_plugin_parents is not None else None,
        prepare_binding=prepare_binding,
        input_query=CodingResumeInputLookupQueryV1,
        observe_input_identity=observe_input_identity,
        retained_cleanup_error=CodingResumeContinuationCleanupFailure,
        deliver=CodingResumePreparedContinuation,
    )
