"""Strict selected-path correspondence for explicit v1 and v2 Coding facts.

No projection result establishes present admission or native effect settlement.
"""

from __future__ import annotations

import asyncio
import re as re
import time
from collections.abc import Iterable
from collections.abc import Mapping as Mapping
from dataclasses import dataclass
from typing import Literal

from loushang.ai.types import UserMessage as UserMessage
from loushang.coding.harness.session import activation_history as _programs
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
    decode_coding_runtime_binding_v2 as decode_coding_runtime_binding_v2,
)
from loushang.coding.resume.binding_v2 import (
    validate_coding_resume_v2_user_record as validate_coding_resume_v2_user_record,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND as AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harness.transcript.types import ExtensionData as ExtensionData

_RESUME_OPERATION_VALUES = {
    "value_001": "Coding activation projection Session id is invalid",
    "value_002": "Coding activation projection requires a complete selected path",
    "value_003": "coding.activation-attempt/",
    "value_004": "coding.runtimeBinding",
    "value_005": "Coding RuntimeBinding requires a UserMessage record",
    "value_006": "Coding activation intent ancestry differs",
    "value_007": "Coding activation intent precedes unresolved intent",
    "value_008": "Coding Binding v2 lacks its exact persisted v2 intent",
    "value_009": "Coding Binding v1 cannot close a v2 intent",
    "value_010": "Coding Binding v1 does not match its intent",
}

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
    steps = _programs.project_activation_history_steps(
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

    steps = _programs.project_activation_history_steps(
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
