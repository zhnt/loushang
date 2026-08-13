from __future__ import annotations

from loushang.ai.types import ImagePart, TextPart, UserMessage
from loushang.harness.conversation import (
    CommandExecutionRecord,
    ConversationRecord,
    OpaquePayload,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    STANDARD_AGENT_TRANSCRIPT_KINDS,
    THINKING_SELECTION_KIND,
    AgentTranscriptProfile,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    ConversationMetadataPatch,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
    ThinkingSelectionSnapshot,
    application_message_to_user_message,
    context_item_to_model_message,
    context_items_to_model_messages,
)


def _record(record_id: str, parent_id: str | None, kind: str, payload):
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=kind,
        payload_version=1,
        created_at="2026-07-16T00:00:00Z",
        payload=payload,
    )


def _text(message) -> str:
    return "".join(part.text for part in message.content if isinstance(part, TextPart))


def test_profile_replays_context_checkpoint_and_folds_runtime_state() -> None:
    profile = AgentTranscriptProfile.default()
    assert profile.semantic_kinds == STANDARD_AGENT_TRANSCRIPT_KINDS
    application = ApplicationMessage(
        application_message_id="application-1",
        custom_type="notice",
        content="Continue from here",
        timestamp=10.0,
    )
    records = (
        _record(
            "old",
            None,
            AGENT_MESSAGE_KIND,
            UserMessage(role="user", content="old question", timestamp=1.0),
        ),
        _record(
            "kept",
            "old",
            COMMAND_EXECUTION_KIND,
            CommandExecutionRecord(
                command="pwd",
                output="/workspace",
                exit_code=0,
            ),
        ),
        _record(
            "branch",
            "kept",
            CONTEXT_BRANCH_SUMMARY_KIND,
            BranchContextSummary(
                from_record_id="other-leaf",
                summary="A branch was explored",
            ),
        ),
        _record(
            "checkpoint",
            "branch",
            CONTEXT_COMPACTION_CHECKPOINT_KIND,
            ContextCompactionCheckpoint(
                summary="Old question summarized",
                first_kept_record_id="kept",
                tokens_before=100,
            ),
        ),
        _record(
            "thinking",
            "checkpoint",
            THINKING_SELECTION_KIND,
            ThinkingSelectionSnapshot(level="medium"),
        ),
        _record(
            "model",
            "thinking",
            MODEL_SELECTION_KIND,
            ModelSelectionSnapshot(
                endpoint_id="test-endpoint", provider="provider", model_id="model"
            ),
        ),
        _record(
            "metadata",
            "model",
            CONVERSATION_METADATA_PATCH_KIND,
            ConversationMetadataPatch(values={"title": "Run"}),
        ),
        _record(
            "annotation",
            "metadata",
            RECORD_ANNOTATION_PATCH_KIND,
            RecordAnnotationPatch(
                target_record_id="kept",
                namespace="display.label",
                operation="set",
                value="Workspace",
            ),
        ),
        _record(
            "application",
            "annotation",
            APPLICATION_MESSAGE_KIND,
            application,
        ),
    )

    context = profile.replay(records)

    assert len(context.messages) == 4
    assert "Old question summarized" in _text(context.messages[0])
    assert "Ran `pwd`" in _text(context.messages[1])
    assert "A branch was explored" in _text(context.messages[2])
    assert context.messages[3] is application
    assert context.thinking_level == "medium"
    assert context.model == {
        "provider": "provider",
        "endpoint_id": "test-endpoint",
        "model_id": "model",
    }
    assert context.state.conversation_metadata == {"title": "Run"}
    assert context.state.annotations == {"kept": {"display.label": "Workspace"}}


def test_branch_summary_is_visible_but_never_a_checkpoint() -> None:
    profile = AgentTranscriptProfile.default()
    branch = _record(
        "branch",
        None,
        CONTEXT_BRANCH_SUMMARY_KIND,
        BranchContextSummary(from_record_id="source", summary="Branch summary"),
    )

    assert profile.record_is_visible(branch)
    assert profile.record_role(branch) == "user"
    assert profile.resolve_checkpoint(branch) is None
    assert profile.previous_summary(branch) is None


def test_opaque_and_excluded_command_are_invisible_and_state_neutral() -> None:
    profile = AgentTranscriptProfile.default()
    opaque = ConversationRecord(
        record_id="opaque",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=2,
        created_at="2026-07-16T00:00:00Z",
        payload=OpaquePayload({"future": True}),
    )
    hidden_command = _record(
        "command",
        "opaque",
        COMMAND_EXECUTION_KIND,
        CommandExecutionRecord(
            command="secret",
            output="hidden",
            exit_code=0,
            exclude_from_context=True,
        ),
    )

    context = profile.replay((opaque, hidden_command))

    assert context.messages == ()
    assert context.thinking_level == "off"
    assert not profile.record_is_visible(opaque)
    assert not profile.record_is_visible(hidden_command)


def test_application_message_remains_context_carrier_and_projects_to_model_input() -> (
    None
):
    application = ApplicationMessage(
        application_message_id="application-1",
        custom_type="notice",
        content="Review this",
        timestamp=12.0,
        delivery_mode="steering",
    )

    user = application_message_to_user_message(application)

    assert context_item_to_model_message(application) == user
    assert user.role == "user"
    assert _text(user) == "Review this"


def test_context_projection_can_replace_adjacent_images() -> None:
    message = UserMessage(
        role="user",
        content=[
            ImagePart(type="image", data="one", mime_type="image/png"),
            ImagePart(type="image", data="two", mime_type="image/png"),
            TextPart(type="text", text="Review this"),
        ],
        timestamp=12.0,
    )

    projected = context_items_to_model_messages(
        [message],
        image_placeholder="Images are disabled.",
    )

    assert projected == [
        UserMessage(
            role="user",
            content=[
                TextPart(type="text", text="Images are disabled."),
                TextPart(type="text", text="Review this"),
            ],
            timestamp=12.0,
        )
    ]
    assert context_items_to_model_messages([message]) == [message]
