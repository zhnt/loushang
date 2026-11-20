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
from pathlib import Path
from typing import cast as cast

from loushang.agent import ThinkingLevel
from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.ai.types import ImagePart
from loushang.ai.types import UserMessage as UserMessage
from loushang.coding.composition.bootstrap import BootstrapServices, NoToolsMode
from loushang.coding.composition.bootstrap import (
    coding_capability_plugin_state_root as _coding_capability_plugin_state_root,  # noqa: F401
)
from loushang.coding.composition.bootstrap import (
    create_resume_agent_session as _create_resume_agent_session,  # noqa: F401
)
from loushang.coding.composition.capability_plugins import CodingResumePluginParents
from loushang.coding.composition.product_capability_plugins import (
    prepare_coding_product_approval_state_root as prepare_coding_product_approval_state_root,
)
from loushang.coding.composition.sets import (
    resolve_coding_composition_set as resolve_coding_composition_set,
)
from loushang.coding.harness.session import continuation_transaction as _programs
from loushang.coding.package.product_runtime import (
    CodingFencedProductApplicationSelection,
)
from loushang.coding.resume._cleanup import (
    CodingResumeContinuationCleanupFailure as CodingResumeContinuationCleanupFailure,
)
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
from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal as PluginActivationDecisionJournal,
)
from loushang.harness.approval.plugin_activation import (
    PluginActivationJournalError as PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionDecisionJournal as PluginExecutionDecisionJournal,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionJournalError as PluginExecutionJournalError,
)
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
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


_RESUME_OPERATION_VALUES = {
    "value_001": "input.effect_owner_set_unsupported",
    "value_002": "coding.resume-continuation/v2",
    "value_003": "definition-decisions.jsonl",
    "value_004": "activation-decisions.jsonl",
    "value_005": "worker-activation-state.jsonl",
    "value_006": "writer.resume_protocol_unsupported",
    "value_007": "Coding Resume continuation failed during ",
    "value_008": "Original Coding Resume owner cleanup also failed: ",
    "value_009": "Coding Resume requires its original SessionManager type",
    "value_010": "Coding Resume Product application owner is invalid",
    "value_011": "Coding Resume Worker requires its application Product owner",
    "value_012": "Coding Resume attempt differs from its activation Plan",
    "value_013": "Coding Resume input record identity is invalid",
    "value_014": "Coding Resume intent and input require distinct record identities",
    "value_015": "Coding Resume requires nonempty user input",
    "value_016": "Coding Resume timestamp must be timezone-aware",
    "value_017": "Coding Resume requires synchronous current owner checks",
    "value_018": "Coding Resume owner check must return None",
    "value_019": "input.record_identity_conflict",
    "value_020": "input.recovery_required",
    "value_021": "Coding Resume candidate was not delivered",
    "definition_owner": "harness.plugin-execution",
    "activation_owner": "harness.plugin-activation",
    "worker_owner": "harness.worker-activation",
    "definition_writer_capability": "harness.plugin-execution.resume-context/v1",
    "activation_writer_capability": "harness.plugin-activation.resume-context/v1",
    "worker_writer_capability": "harness.worker-activation.resume-context/v1",
    "probe_scope": "session:protocol-probe",
    "probe_directory": ".resume-protocol-probe",
}


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
    return _programs.prepare_effect_parents(
        attempt, worker_candidate_plugin_id=worker_candidate_plugin_id
    )


def _require_v2_native_writer_protocols(
    manager_type: type[SessionManager],
) -> None:
    """Negotiate all accepted v2 writers without opening any durable source."""

    return _programs.require_writer_protocols(manager_type)


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

    return await _programs.prepare_continuation(
        manager_type=manager_type,
        session_file=session_file,
        plan=plan,
        current_owner_inputs=current_owner_inputs,
        attempt=attempt,
        input_record_id=input_record_id,
        text=text,
        created_at=created_at,
        require_current_admission=require_current_admission,
        require_current_epoch_settlement=require_current_epoch_settlement,
        images=images,
        services=services,
        model=model,
        thinking_level=thinking_level,
        stream_fn=stream_fn,
        tools=tools,
        output_capture_factory=output_capture_factory,
        no_tools=no_tools,
        approval_resolver=approval_resolver,
        tool_policy_evaluator=tool_policy_evaluator,
        observe_input_identity=observe_input_identity,
        product_owner_selection=product_owner_selection,
        resume_writer_factory=resume_writer_factory,
        worker_candidates=worker_candidates,
        worker_candidate_plugin_id=worker_candidate_plugin_id,
    )
