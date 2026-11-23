"""Strict selected-path correspondence for explicit v1 and v2 Coding facts.

No projection result establishes present admission or native effect settlement.
"""

from __future__ import annotations

import asyncio
import re as re
import time
from collections.abc import Callable, Generator, Iterable, Sequence
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
from loushang.harness.transcript._resume_records import (
    SelectedAncestry,
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
    steps = _project_activation_history_steps(
        records, current_session_id=current_session_id
    )
    while True:
        try:
            next(steps)
        except StopIteration as complete:
            return complete.value


async def project_coding_activation_attempt_path_v2_async(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
) -> CodingActivationAttemptProjectionV2:
    """Perform the same complete historical check while allowing UI work."""

    steps = _project_activation_history_steps(
        records, current_session_id=current_session_id
    )
    deadline = time.monotonic() + 0.008
    try:
        while True:
            try:
                next(steps)
            except StopIteration as complete:
                return complete.value
            if time.monotonic() >= deadline:
                await asyncio.sleep(0)
                deadline = time.monotonic() + 0.008
    finally:
        steps.close()


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
    ancestry = SelectedAncestry(_ANCESTRY_DOMAIN)
    pending: dict[str, CodingActivationAttemptV1] = {}
    unknown = False
    selected_binding: (
        CodingRuntimeBindingV1 | CodingRuntimeBindingV2 | None
    ) = None
    selected_binding_record_id: str | None = None
    for record in records:
        ancestry.require_next(
            record, error='Coding activation projection requires a complete selected path'
        )
        observed_binding: CodingRuntimeBindingV1 | None = None
        payload = record.payload
        if isinstance(
            payload, ExtensionData
        ) and payload.extension_type.startswith(
            'coding.activation-attempt/'
        ):
            attempt: CodingActivationAttemptV1 | None
            if (
                payload.extension_type
                == CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE
            ):
                attempt = validate_coding_activation_attempt_record(record)
            elif (
                payload.extension_type
                == CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE
            ):
                attempt = validate_coding_activation_attempt_v2_record(record)
            else:
                unknown = True
                attempt = None
            if attempt is not None:
                if attempt.ancestry_digest != ancestry.hexdigest():
                    raise ValueError('Coding activation intent ancestry differs')
                if attempt.session_id in pending:
                    raise ValueError('Coding activation intent precedes unresolved intent')
                pending[attempt.session_id] = attempt
        reserved = {
            key
            for key in record.metadata
            if key.startswith('coding.runtimeBinding')
        }
        if reserved:
            if record.kind != AGENT_MESSAGE_KIND or not isinstance(
                payload, UserMessage
            ):
                raise ValueError('Coding RuntimeBinding requires a UserMessage record')
            if reserved == {CODING_RUNTIME_BINDING_V2_METADATA_KEY}:
                raw = record.metadata[CODING_RUNTIME_BINDING_V2_METADATA_KEY]
                version = (
                    raw.get("version") if isinstance(raw, Mapping) else None
                )
                if type(version) is int and version > 2:
                    unknown = True
                else:
                    binding_v2 = decode_coding_runtime_binding_v2(
                        record.metadata
                    )
                    matched = pending.get(binding_v2.session_id)
                    if type(matched) is not CodingActivationAttemptV2:
                        raise ValueError('Coding Binding v2 lacks its exact persisted v2 intent')
                    _require_decoded_v2_binding(
                        record,
                        binding_v2,
                        payload=_require_v2_user_payload(record),
                        intent=matched,
                    )
                    observed_binding = binding_v2
                    del pending[binding_v2.session_id]
            elif reserved == {CODING_RUNTIME_BINDING_METADATA_KEY}:
                observation = inspect_coding_runtime_binding(record.metadata)
                if observation.status == "unknown_version":
                    unknown = True
                elif (binding := observation.binding) is not None:
                    _require_decoded_v1_binding(
                        record,
                        binding,
                        payload=payload,
                        expected_session_id=binding.session_id,
                    )
                    matched = pending.get(binding.session_id)
                    if matched is not None:
                        if type(matched) is not CodingActivationAttemptV1:
                            raise ValueError(
                                'Coding Binding v1 cannot close a v2 intent'
                            )
                        if record.parent_id != matched.attempt_id or not matches_intent(
                            binding, matched, check_session=False
                        ):
                            raise ValueError(
                                'Coding Binding v1 does not match its intent'
                            )
                        del pending[binding.session_id]
                    observed_binding = binding
            else:
                unknown = True
        match = None
        if (
            observed_binding is not None
            and observed_binding.session_id == current_session_id
            and not unknown
        ):
            selected_binding = observed_binding
            selected_binding_record_id = record.record_id
            if observed_binding.input_id == input_id:
                match = record
        ancestry.advance(record, _encoded)
        yield match
    ancestry_digest = ancestry.hexdigest()
    if unknown:
        return CodingActivationAttemptProjectionV2(
            "unknown_version",
            ancestry_digest=ancestry_digest,
            binding_status="unknown_version",
            binding_record_id=selected_binding_record_id,
        )
    current = pending.get(current_session_id)
    if current is not None:
        return CodingActivationAttemptProjectionV2(
            "pending",
            current,
            current.attempt_id,
            ancestry_digest,
            "bound" if selected_binding is not None else "none",
            selected_binding,
            selected_binding_record_id,
        )
    return CodingActivationAttemptProjectionV2(
        "none",
        ancestry_digest=ancestry_digest,
        binding_status="bound" if selected_binding is not None else "none",
        binding=selected_binding,
        binding_record_id=selected_binding_record_id,
    )


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
    while True:
        try:
            record = next(steps)
        except StopIteration as complete:
            # A later unknown version invalidates even an earlier known input.
            return None if complete.value.status == "unknown_version" else matches
        if record is not None:
            matches.append(record)


def observe_latest_bound_input(
    records: Sequence[AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str,
    expected_digest: str,
    digest: Callable[[AgentTranscriptRecord], str],
) -> AgentTranscriptRecord | Literal["unknown", "conflict"] | None:
    """Observe the latest bound input before a live owner is attached.

    None allows the caller to consult its retained request when the projected
    Binding does not identify this input.
    """
    projection = project_coding_activation_attempt_path_v2(
        records, current_session_id=current_session_id
    )
    binding = projection.binding
    if (
        projection.binding_status != "bound"
        or binding is None
        or binding.input_id != input_id
        or projection.binding_record_id is None
    ):
        return None
    return select_input_record(
        [record for record in records if record.record_id == projection.binding_record_id],
        expected_digest=expected_digest, digest=digest, duplicate="unknown",
    )


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
