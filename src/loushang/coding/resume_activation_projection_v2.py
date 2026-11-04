"""Strict selected-path correspondence for explicit v1 and v2 Coding facts.

No projection result establishes present admission or native effect settlement.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Generator, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from loushang.ai.types import UserMessage
from loushang.coding.resume_activation_attempt import (
    CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE,
    CodingActivationAttemptV1,
    _encoded,
    validate_coding_activation_attempt_record,
)
from loushang.coding.resume_activation_attempt_v2 import (
    CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE,
    CodingActivationAttemptV2,
    validate_coding_activation_attempt_v2_record,
)
from loushang.coding.resume_binding import (
    CODING_RUNTIME_BINDING_METADATA_KEY,
    CodingRuntimeBindingV1,
    inspect_coding_runtime_binding,
    validate_coding_runtime_binding_record,
)
from loushang.coding.resume_binding_v2 import (
    CODING_RUNTIME_BINDING_V2_METADATA_KEY,
    CodingRuntimeBindingV2,
    decode_coding_runtime_binding_v2,
    validate_coding_resume_v2_user_record,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord, ExtensionData


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
    steps = _project_coding_activation_attempt_path_v2_steps(
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

    steps = _project_coding_activation_attempt_path_v2_steps(
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


def _project_coding_activation_attempt_path_v2_steps(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
) -> Generator[None, None, CodingActivationAttemptProjectionV2]:
    if (
        type(current_session_id) is not str
        or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", current_session_id) is None
    ):
        raise ValueError("Coding activation projection Session id is invalid")
    ancestry = hashlib.sha256(b"loushang.coding.resume-ancestry/v1\0")
    previous_id = None
    seen = set()
    pending: dict[str, CodingActivationAttemptV1] = {}
    unknown = False
    selected_binding: CodingRuntimeBindingV1 | CodingRuntimeBindingV2 | None = None
    selected_binding_record_id: str | None = None
    for record in records:
        if record.parent_id != previous_id or record.record_id in seen:
            raise ValueError(
                "Coding activation projection requires a complete selected path"
            )
        seen.add(record.record_id)
        payload = record.payload
        if isinstance(payload, ExtensionData) and payload.extension_type.startswith(
            "coding.activation-attempt/"
        ):
            attempt: CodingActivationAttemptV1 | None
            if payload.extension_type == CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE:
                attempt = validate_coding_activation_attempt_record(record)
            elif payload.extension_type == CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE:
                attempt = validate_coding_activation_attempt_v2_record(record)
            else:
                unknown = True
                attempt = None
            if attempt is not None:
                if attempt.ancestry_digest != ancestry.hexdigest():
                    raise ValueError("Coding activation intent ancestry differs")
                if attempt.session_id in pending:
                    raise ValueError(
                        "Coding activation intent precedes unresolved intent"
                    )
                pending[attempt.session_id] = attempt
        reserved = {
            key for key in record.metadata if key.startswith("coding.runtimeBinding")
        }
        if reserved:
            if record.kind != AGENT_MESSAGE_KIND or not isinstance(
                payload, UserMessage
            ):
                raise ValueError("Coding RuntimeBinding requires a UserMessage record")
            if reserved == {CODING_RUNTIME_BINDING_V2_METADATA_KEY}:
                raw = record.metadata[CODING_RUNTIME_BINDING_V2_METADATA_KEY]
                version = raw.get("version") if isinstance(raw, Mapping) else None
                if type(version) is int and version > 2:
                    unknown = True
                else:
                    binding_v2 = decode_coding_runtime_binding_v2(record.metadata)
                    matched = pending.get(binding_v2.session_id)
                    if type(matched) is not CodingActivationAttemptV2:
                        raise ValueError(
                            "Coding Binding v2 lacks its exact persisted v2 intent"
                        )
                    validate_coding_resume_v2_user_record(record, intent=matched)
                    if binding_v2.session_id == current_session_id and not unknown:
                        selected_binding = binding_v2
                        selected_binding_record_id = record.record_id
                    del pending[binding_v2.session_id]
            elif reserved == {CODING_RUNTIME_BINDING_METADATA_KEY}:
                observation = inspect_coding_runtime_binding(record.metadata)
                if observation.status == "unknown_version":
                    unknown = True
                elif observation.binding is not None:
                    binding = validate_coding_runtime_binding_record(
                        record,
                        expected_session_id=observation.binding.session_id,
                    )
                    matched = pending.get(binding.session_id)
                    if matched is not None:
                        if type(matched) is not CodingActivationAttemptV1:
                            raise ValueError(
                                "Coding Binding v1 cannot close a v2 intent"
                            )
                        if (
                            record.parent_id != matched.attempt_id
                            or binding.attempt_id != matched.attempt_id
                            or binding.input_id != matched.request_id
                            or binding.original_leaf_id != matched.original_leaf_id
                            or binding.ancestry_digest != matched.ancestry_digest
                            or binding.planned_fingerprint != matched.plan_fingerprint
                            or binding.actual_fingerprint != matched.epoch_fingerprint
                            or binding.subject_digest != matched.subject_digest
                        ):
                            raise ValueError(
                                "Coding Binding v1 does not match its intent"
                            )
                        del pending[binding.session_id]
                    if binding.session_id == current_session_id and not unknown:
                        selected_binding = binding
                        selected_binding_record_id = record.record_id
            else:
                unknown = True
        identity = _encoded(
            {"recordId": record.record_id, "parentId": record.parent_id}
        )
        ancestry.update(len(identity).to_bytes(4, "big"))
        ancestry.update(identity)
        previous_id = record.record_id
        yield
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
