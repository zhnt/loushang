from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest

from loushang.agent import ModelCallPreparation
from loushang.ai import Context
from loushang.ai.model import Capabilities, Model
from loushang.ai.options import CallOptions
from loushang.ai.types import TextPart, UserMessage
from loushang.foundation.json import JSONValue, require_json_value
from loushang.harness.capabilities.prompt_preflight import PromptPreflightResult
from loushang.harness.conversation.types import ConversationRecord
from loushang.harness.resources._catalog_records import (
    ResourceComponentProducer,
    ResourceIdentity,
    ResourceLoadReceipt,
    ResourceSourceGenerationRef,
)
from loushang.harness.resources._skill_catalog_consumer import (
    LoadedSkillBody,
    SkillCatalogSummary,
)
from loushang.harness.session.request_evidence import (
    RESOURCE_EVIDENCE_METADATA_KEY,
    RESOURCE_EVIDENCE_SCHEMA_ID,
    PreparedResourceEvidence,
    RequestEvidenceIntegrityError,
    SessionRequestEvidenceRuntime,
)


def test_loaded_skill_projects_only_json_safe_exact_receipt_evidence() -> None:
    loaded = _loaded_skill()
    result = PromptPreflightResult(
        text="<skill>Review carefully.</skill>",
        loaded_skills=(loaded,),
    )
    runtime = _runtime([], [])

    prepared = runtime.prepare(result)

    assert prepared is not None
    payload = prepared.to_message_payload(
        message_record_id="message-1",
        message_index=0,
    )
    require_json_value(payload)
    skill = payload["skills"][0]
    assert skill["catalogGeneration"] == 7
    assert skill["catalogSnapshotFingerprint"] == "b" * 64
    assert skill["activationPolicyFingerprint"] == "a" * 64
    assert skill["candidateFingerprint"] == "c" * 64
    assert skill["sourceGeneration"]["generation"] == "source-generation-7"
    assert skill["expectedContentDigest"] == skill["observedContentDigest"]
    assert skill["expectedContentLength"] == skill["observedContentLength"]
    assert "opaqueLocator" not in skill
    assert "sourcePath" not in skill


def test_message_binding_is_ordered_per_message_and_abandonment_is_ephemeral() -> None:
    first = _user_message("same")
    second = _user_message("same")
    records = [
        _message_record("message-1", first),
        _message_record("message-2", second, parent_id="message-1"),
    ]
    bindings = [("message-1", first), ("message-2", second)]
    runtime = _runtime(records, bindings)
    prepared = runtime.prepare(
        PromptPreflightResult(text="same", loaded_skills=(_loaded_skill(),))
    )
    assert prepared is not None
    first_owner = object()
    second_owner = object()
    first_delivered = _user_message("same")
    second_delivered = _user_message("same")
    runtime.bind(first_delivered, prepared, owner=first_owner)
    runtime.bind(second_delivered, prepared, owner=second_owner)

    assert runtime.commit_message(first_delivered, "message-1") is True
    assert runtime.commit_message(second_delivered, "message-2") is True

    projection = runtime.project_model_input(
        _preparation([_user_message("same"), _user_message("same")])
    )
    assert projection is not None
    assert projection["schemaId"] == RESOURCE_EVIDENCE_SCHEMA_ID
    assert projection["contextComplete"] is True
    assert [message["messageRecordId"] for message in projection["messages"]] == [
        "message-1",
        "message-2",
    ]
    assert [message["messageIndex"] for message in projection["messages"]] == [
        0,
        1,
    ]

    abandoned_owner = object()
    runtime.bind(_user_message("same"), prepared, owner=abandoned_owner)
    runtime.discard_owner(abandoned_owner)
    assert runtime.commit_message(_user_message("same"), "message-3") is False


def test_unidentified_duplicate_pending_messages_fail_closed() -> None:
    runtime = _runtime([], [])
    prepared = runtime.prepare(
        PromptPreflightResult(text="same", loaded_skills=(_loaded_skill(),))
    )
    assert prepared is not None
    runtime.bind(
        _user_message("same"),
        prepared,
        owner=object(),
        allow_signature_fallback=True,
    )
    runtime.bind(
        _user_message("same"),
        prepared,
        owner=object(),
        allow_signature_fallback=True,
    )

    with pytest.raises(RequestEvidenceIntegrityError, match="multiple uncommitted"):
        runtime.commit_message(_user_message("same"), "message-1")


def test_message_metadata_closes_pre_model_input_crash_window() -> None:
    message = _user_message("durable")
    first_runtime = _runtime([], [])
    prepared = first_runtime.prepare(
        PromptPreflightResult(text="durable", loaded_skills=(_loaded_skill(),))
    )
    assert prepared is not None
    first_runtime.bind(message, prepared, owner=object())

    metadata = first_runtime.prepare_message_commit(message)

    assert metadata is not None
    assert RESOURCE_EVIDENCE_METADATA_KEY in metadata
    record = _message_record("message-1", message, metadata=metadata)
    resumed = _runtime([record], [("message-1", message)])
    projection = resumed.project_model_input(_preparation([message]))
    assert projection is not None
    assert projection["messages"][0]["messageRecordId"] == "message-1"
    assert projection["messages"][0]["skills"] == list(prepared.skills)


def test_retry_is_idempotent_and_does_not_consume_same_text_pending() -> None:
    runtime = _runtime([], [])
    prepared = runtime.prepare(
        PromptPreflightResult(text="same", loaded_skills=(_loaded_skill(),))
    )
    assert prepared is not None
    first = _user_message("same")
    second = _user_message("same")
    runtime.bind(
        first,
        prepared,
        owner=object(),
        allow_signature_fallback=True,
    )
    assert runtime.prepare_message_commit(first) is not None
    assert runtime.commit_message(first, "message-1") is True
    runtime.bind(
        second,
        prepared,
        owner=object(),
        allow_signature_fallback=True,
    )

    assert runtime.commit_message(first, "message-1") is True
    assert runtime.prepare_message_commit(second) is not None
    assert runtime.commit_message(second, "message-2") is True


def test_queued_binding_is_identity_only_and_evidence_is_deeply_immutable() -> None:
    runtime = _runtime([], [])
    prepared = runtime.prepare(
        PromptPreflightResult(text="same", loaded_skills=(_loaded_skill(),))
    )
    assert prepared is not None
    delivered = _user_message("same")
    runtime.bind(delivered, prepared, owner=object())

    assert runtime.prepare_message_commit(_user_message("same")) is None
    assert runtime.prepare_message_commit(delivered) is not None

    exposed_skill = prepared.skills[0]
    exposed_identity = exposed_skill["resourceIdentity"]
    assert isinstance(exposed_identity, dict)
    exposed_identity["publicId"] = "forged"
    payload = prepared.to_message_payload(
        message_record_id="message-1",
        message_index=0,
    )
    assert payload["skills"][0]["resourceIdentity"]["publicId"] == "review"

    skill_with_locator = dict(exposed_skill)
    skill_with_locator["opaqueLocator"] = "forbidden"
    with pytest.raises(RequestEvidenceIntegrityError, match="fields are invalid"):
        PreparedResourceEvidence(
            model_visible_text="same",
            skills=(skill_with_locator,),
        )


def test_close_is_idempotent_and_rejects_further_evidence_use() -> None:
    runtime = _runtime([], [])
    prepared = runtime.prepare(
        PromptPreflightResult(text="closed", loaded_skills=(_loaded_skill(),))
    )
    assert prepared is not None
    runtime.bind(_user_message("closed"), prepared, owner=object())

    runtime.close()
    runtime.close()
    runtime.discard_owner(object())

    with pytest.raises(RuntimeError, match="closed"):
        runtime.prepare(
            PromptPreflightResult(text="closed", loaded_skills=(_loaded_skill(),))
        )
    with pytest.raises(RuntimeError, match="closed"):
        runtime.bind(_user_message("closed"), prepared, owner=object())
    with pytest.raises(RuntimeError, match="closed"):
        runtime.commit_message(_user_message("closed"), "message-1")
    with pytest.raises(RuntimeError, match="closed"):
        runtime.project_model_input(_preparation([]))


def test_request_evidence_omits_absent_context_and_fails_on_duplicate_subset() -> None:
    message = _user_message("exact")
    records = [_message_record("message-1", message)]
    bindings = [("message-1", message)]
    runtime = _runtime(records, bindings)
    prepared = runtime.prepare(
        PromptPreflightResult(text="exact", loaded_skills=(_loaded_skill(),))
    )
    assert prepared is not None
    runtime.bind(message, prepared, owner=object())
    assert runtime.commit_message(message, "message-1") is True

    assert runtime.project_model_input(_preparation([_user_message("changed")])) is None

    duplicate = _user_message("exact")
    records.append(_message_record("message-2", duplicate, parent_id="message-1"))
    bindings.append(("message-2", duplicate))
    with pytest.raises(RequestEvidenceIntegrityError, match="ambiguous subset"):
        runtime.project_model_input(_preparation([_user_message("exact")]))


def _runtime(
    records: list[ConversationRecord[object]],
    bindings: list[tuple[str, object]],
) -> SessionRequestEvidenceRuntime:
    return SessionRequestEvidenceRuntime(
        get_context_message_bindings=lambda: tuple(bindings),
        get_active_records=lambda: tuple(records),  # type: ignore[arg-type]
        rebuild_model_input=lambda _snapshot_id: (_ for _ in ()).throw(
            AssertionError("a source-free unit projection has no snapshot")
        ),
    )


def _preparation(messages: list[UserMessage]) -> ModelCallPreparation:
    return ModelCallPreparation(
        purpose="main",
        sequence=1,
        model=Model(
            id="evidence-model",
            name="Evidence Model",
            provider="test",
            endpoint="test",
            capabilities=Capabilities(input=("text",), context_window=8_192),
        ),
        context=Context(system_prompt="test", messages=messages),
        options=CallOptions(),
    )


def _message_record(
    record_id: str,
    message: UserMessage,
    *,
    parent_id: str | None = None,
    metadata: Mapping[str, JSONValue] | None = None,
) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind="agent.message",
        payload_version=1,
        created_at="2026-08-29T00:00:00Z",
        payload=message,
        metadata={} if metadata is None else metadata,
    )


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=[TextPart(type="text", text=text)],
        timestamp=0.0,
    )


def _loaded_skill() -> LoadedSkillBody:
    body = b"---\nname: review\n---\nReview carefully.\n"
    digest = hashlib.sha256(body).hexdigest()
    identity = ResourceIdentity(
        resource_kind="skill",
        schema_id="loushang.skill",
        schema_version=1,
        public_id="review",
    )
    source_generation = ResourceSourceGenerationRef(
        source_id="project-skills",
        product_id="coding",
        generation="source-generation-7",
        source_policy_fingerprint="d" * 64,
        producer=ResourceComponentProducer(
            component_contribution_id="project-skill-component",
            component_candidate_fingerprint="e" * 64,
            component_admission_fingerprint="f" * 64,
            binding_fingerprint="1" * 64,
            plugin_instance_revision_ref="project-revision-7",
            package_content_digest="2" * 64,
        ),
    )
    summary = SkillCatalogSummary(
        catalog_generation=7,
        catalog_snapshot_fingerprint="b" * 64,
        activation_policy_fingerprint="a" * 64,
        candidate_fingerprint="c" * 64,
        identity=identity,
        name="review",
        canonical_name="review",
        description="Review changes",
        enabled=True,
        model_invocable=True,
        media_type="text/markdown",
        expected_content_digest=digest,
        expected_content_length=len(body),
        source_path=Path("/project/.agents/skills/review/SKILL.md"),
        source_root=Path("/project/.agents"),
        source_kind="project_local",
        source_scope="project",
        source_root_order=0,
        source="filesystem",
        diagnostics=(),
        declared_id=None,
        revision_ref=None,
    )
    receipt = ResourceLoadReceipt(
        catalog_generation=7,
        snapshot_fingerprint="b" * 64,
        candidate_fingerprint="c" * 64,
        source_generation_ref=source_generation,
        schema_id=identity.schema_id,
        schema_version=identity.schema_version,
        media_type="text/markdown",
        content_digest=digest,
        content_length=len(body),
    )
    return LoadedSkillBody(
        summary=summary,
        receipt=receipt,
        body=body,
        content=body.decode("utf-8"),
    )
