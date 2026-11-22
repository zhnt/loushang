"""Strict selected-path correspondence for explicit v1 and v2 Coding facts.

No projection result establishes present admission or native effect settlement.
"""

from __future__ import annotations

import re as re
from collections.abc import Callable, Generator, Iterable
from collections.abc import Mapping as Mapping
from dataclasses import dataclass
from typing import Literal

from loushang.ai.types import UserMessage as UserMessage
from loushang.coding.resume.activation_attempt import (
    CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE as CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE,
)
from loushang.coding.resume.activation_attempt import (
    CodingActivationAttemptV1,
)
from loushang.coding.resume.activation_attempt import (
    _encoded as _encoded,
)
from loushang.coding.resume.activation_attempt import (
    validate_coding_activation_attempt_record as validate_coding_activation_attempt_record,
)
from loushang.coding.resume.activation_attempt_v2 import (
    CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE as CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE,
)
from loushang.coding.resume.activation_attempt_v2 import (
    CodingActivationAttemptV2 as CodingActivationAttemptV2,
)
from loushang.coding.resume.activation_attempt_v2 import (
    validate_coding_activation_attempt_v2_record as validate_coding_activation_attempt_v2_record,
)
from loushang.coding.resume.binding import (
    _ANCESTRY_DOMAIN as _ANCESTRY_DOMAIN,
)
from loushang.coding.resume.binding import (
    CODING_RUNTIME_BINDING_METADATA_KEY as CODING_RUNTIME_BINDING_METADATA_KEY,
)
from loushang.coding.resume.binding import (
    CodingRuntimeBindingV1,
    matches_intent,
)
from loushang.coding.resume.binding import (
    _require_decoded_v1_binding as _require_decoded_v1_binding,
)
from loushang.coding.resume.binding import (
    _require_v1_user_payload as _require_v1_user_payload,
)
from loushang.coding.resume.binding import (
    inspect_coding_runtime_binding as inspect_coding_runtime_binding,
)
from loushang.coding.resume.binding import (
    validate_coding_runtime_binding_record as validate_coding_runtime_binding_record,
)
from loushang.coding.resume.binding_v2 import (
    CODING_RUNTIME_BINDING_V2_METADATA_KEY as CODING_RUNTIME_BINDING_V2_METADATA_KEY,
)
from loushang.coding.resume.binding_v2 import (
    CodingRuntimeBindingV2,
)
from loushang.coding.resume.binding_v2 import (
    _require_decoded_v2_binding as _require_decoded_v2_binding,
)
from loushang.coding.resume.binding_v2 import (
    _require_v2_user_payload as _require_v2_user_payload,
)
from loushang.coding.resume.binding_v2 import (
    decode_coding_runtime_binding_v2 as decode_coding_runtime_binding_v2,
)
from loushang.coding.resume.binding_v2 import (
    validate_coding_resume_v2_user_record as validate_coding_resume_v2_user_record,
)
from loushang.harness.runtime._owned_tasks import _finish_cooperative_scan
from loushang.harness.transcript._resume_records import (
    SelectedAncestry,
    finish_history_scan,
    scan_activation_history,
    select_input_record,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND as AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harness.transcript.types import ExtensionData as ExtensionData


@dataclass(frozen=True, slots=True)
class CodingActivationAttemptProjectionV2:
    status: Literal["none", "pending", "unknown_version"]
    attempt: CodingActivationAttemptV1 | None = None
    record_id: str | None = None
    ancestry_digest: str = ""
    binding_status: Literal["none", "bound", "unknown_version"] = "none"
    binding: CodingRuntimeBindingV1 | CodingRuntimeBindingV2 | None = None
    binding_record_id: str | None = None


def project_coding_activation_attempt_path_v2(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
) -> CodingActivationAttemptProjectionV2:
    return finish_history_scan(
        _project_activation_history_steps(records, current_session_id=current_session_id)
    )

async def project_coding_activation_attempt_path_v2_async(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
) -> CodingActivationAttemptProjectionV2:
    """Perform the same complete historical check while allowing UI work."""

    return await _finish_cooperative_scan(
        _project_activation_history_steps(records, current_session_id=current_session_id)
    )


def _project_activation_history_steps(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str | None = None,
) -> Generator[
    AgentTranscriptRecord | None,
    None,
    CodingActivationAttemptProjectionV2,
]:
    if (
        type(current_session_id) is not str
        or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", current_session_id) is None
    ):
        raise ValueError('Coding activation projection Session id is invalid')
    history = yield from scan_activation_history(
        records,
        current_session_id=current_session_id,
        ancestry=SelectedAncestry(_ANCESTRY_DOMAIN),
        encode=_encoded,
        attempt_prefix="coding.activation-attempt/",
        attempt_readers={
            CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE: validate_coding_activation_attempt_record,
            CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE: validate_coding_activation_attempt_v2_record,
        },
        read_binding=_read_activation_path_binding,
        path_error="Coding activation projection requires a complete selected path",
        ancestry_error="Coding activation intent ancestry differs",
        duplicate_error="Coding activation intent precedes unresolved intent",
        input_id=input_id,
    )
    binding_status: Literal["none", "bound", "unknown_version"] = (
        "unknown_version" if history.status == "unknown_version"
        else "bound" if history.binding is not None
        else "none"
    )
    attempt = history.attempt
    return CodingActivationAttemptProjectionV2(
        history.status,
        attempt,
        None if attempt is None else attempt.attempt_id,
        history.ancestry_digest,
        binding_status,
        history.binding,
        history.binding_record_id,
    )


def _read_activation_path_binding(
    record: AgentTranscriptRecord, pending: Mapping[str, CodingActivationAttemptV1],
) -> CodingRuntimeBindingV1 | Literal["unknown_version"] | None:
    reserved = {key for key in record.metadata if key.startswith("coding.runtimeBinding")}
    if not reserved:
        return None
    payload = record.payload
    if record.kind != AGENT_MESSAGE_KIND or not isinstance(payload, UserMessage):
        raise ValueError("Coding RuntimeBinding requires a UserMessage record")
    if reserved == {CODING_RUNTIME_BINDING_V2_METADATA_KEY}:
        raw = record.metadata[CODING_RUNTIME_BINDING_V2_METADATA_KEY]
        version = raw.get("version") if isinstance(raw, Mapping) else None
        if type(version) is int and version > 2:
            return "unknown_version"
        binding_v2 = decode_coding_runtime_binding_v2(record.metadata)
        attempt = pending.get(binding_v2.session_id)
        if type(attempt) is not CodingActivationAttemptV2:
            raise ValueError("Coding Binding v2 lacks its exact persisted v2 intent")
        _require_decoded_v2_binding(
            record, binding_v2, payload=_require_v2_user_payload(record), intent=attempt,
        )
        return binding_v2
    if reserved != {CODING_RUNTIME_BINDING_METADATA_KEY}:
        return "unknown_version"
    observation = inspect_coding_runtime_binding(record.metadata)
    if observation.status == "unknown_version":
        return "unknown_version"
    binding = observation.binding
    if binding is None:
        return None
    _require_decoded_v1_binding(
        record, binding, payload=payload, expected_session_id=binding.session_id,
    )
    attempt = pending.get(binding.session_id)
    if attempt is not None:
        if type(attempt) is not CodingActivationAttemptV1:
            raise ValueError("Coding Binding v1 cannot close a v2 intent")
        if record.parent_id != attempt.attempt_id or not matches_intent(
            binding, attempt, check_session=False
        ):
            raise ValueError("Coding Binding v1 does not match its intent")
    return binding


def find_input_records(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str,
) -> list[AgentTranscriptRecord] | None:
    """Find exact-session inputs while verifying the whole selected path."""
    steps = _project_activation_history_steps(
        records, current_session_id=current_session_id, input_id=input_id
    )
    matches: list[AgentTranscriptRecord] = []
    history = finish_history_scan(steps, matches)
    # A later unknown version invalidates even an earlier known input.
    return None if history.status == "unknown_version" else matches


def find_legacy_model_input(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str,
    expected_digest: str,
    digest: Callable[[AgentTranscriptRecord], str],
) -> tuple[int, AgentTranscriptRecord] | Literal["unknown", "conflict"]:
    """Find the exact V1-bound input and its position for model observation."""
    matches: list[AgentTranscriptRecord] = []
    first_index = 0
    try:
        for index, record in enumerate(records):
            binding = inspect_coding_runtime_binding(record.metadata).binding
            if binding is None or binding.session_id != current_session_id or binding.input_id != input_id:
                continue
            _require_decoded_v1_binding(
                record, binding, payload=_require_v1_user_payload(record),
                expected_session_id=current_session_id,
            )
            if not matches:
                first_index = index
            matches.append(record)
    except ValueError:
        return "unknown"
    selected = select_input_record(matches, expected_digest=expected_digest, digest=digest)
    return selected if isinstance(selected, str) else (first_index, selected)
