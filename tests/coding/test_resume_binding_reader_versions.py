from dataclasses import replace

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.resume_activation_attempt import (
    CodingResumeRecoveryRequired,
    require_no_unsettled_coding_activation,
)
from loushang.coding.resume_binding import (
    coding_user_payload_digest,
    inspect_coding_runtime_binding,
    project_coding_runtime_binding_path,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory
from tests.coding.test_resume_binding import _binding


@pytest.mark.parametrize("key", ["coding.runtimeBindingV2", "coding.runtimeBindingV3"])
def test_unsupported_binding_key_remains_inert_and_blocks_ordinary_mutation(key):
    metadata = {key: {"version": int(key[-1]), "approval": True}}
    observation = inspect_coding_runtime_binding(metadata)
    assert observation.status == "unknown_version" and observation.binding is None
    record = AgentTranscriptRecordFactory().create(
        AGENT_MESSAGE_KIND,
        UserMessage(role="user", content="historical input", timestamp=1.0),
        parent_id=None,
        metadata=metadata,
    )
    with pytest.raises(CodingResumeRecoveryRequired) as caught:
        require_no_unsettled_coding_activation(
            (record,), current_session_id="session-1"
        )
    assert caught.value.reason_code == "history.activation_unknown_version"
    assert record.metadata == metadata


def test_future_binding_key_cannot_be_hidden_by_a_legacy_key():
    metadata = {
        "coding.runtimeBindingV1": {"version": 1},
        "coding.runtimeBindingV2": {"version": 2},
    }
    assert inspect_coding_runtime_binding(metadata).status == "unknown_version"


def test_later_known_binding_does_not_erase_unknown_version_in_selected_history():
    message = UserMessage(role="user", content="historical input", timestamp=1.0)
    factory = AgentTranscriptRecordFactory()
    future = factory.create(
        AGENT_MESSAGE_KIND,
        message,
        parent_id=None,
        metadata={"coding.runtimeBindingV2": {"version": 2}},
    )
    binding = replace(_binding(), payload_digest=coding_user_payload_digest(message))
    known = factory.create(
        AGENT_MESSAGE_KIND,
        message,
        parent_id=future.record_id,
        metadata=binding.to_message_metadata(),
    )
    known = replace(known, record_id=binding.record_id)
    projection = project_coding_runtime_binding_path(
        (future, known),
        current_session_id=binding.session_id,
    )
    assert projection.status == "unknown_version"
    assert projection.binding is None
