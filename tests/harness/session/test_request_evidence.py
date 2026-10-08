from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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
    RESOURCE_EVIDENCE_COMPONENT,
    RESOURCE_EVIDENCE_METADATA_KEY,
    RESOURCE_EVIDENCE_SCHEMA_ID,
    PreparedResourceEvidence,
    RequestEvidenceIntegrityError,
    SessionRequestEvidenceRuntime,
)
from loushang.harness.transcript.model_input_types import (
    ModelInputComponent,
    ModelInputComponentReference,
    ModelInputSnapshot,
    hash_model_input_json,
)


def _snapshot(
    *,
    snapshot_id: str,
    additional_components: tuple[ModelInputComponentReference, ...] = (),
) -> ModelInputSnapshot:
    fingerprint = "a" * 64
    logical = tuple(
        ModelInputComponentReference(name, "component", fingerprint)
        for name in ("system_prompt", "messages", "tools", "request_options")
    )
    return ModelInputSnapshot(
        snapshot_id=snapshot_id,
        invocation_id="invocation",
        attempt=1,
        purpose="continuation",
        product_id="coding",
        runtime_id="session",
        mount_generation=0,
        profile_fingerprint=fingerprint,
        registration_revision=fingerprint,
        conversation_id="conversation",
        source_leaf_id="message",
        source_revision=1,
        commit_revision=2,
        provider_id="provider",
        model_id="model",
        api_id="api",
        endpoint_id="endpoint",
        logical_components=logical + additional_components,
        prepared_payload_components=(),
        model_visible_headers_component=ModelInputComponentReference(
            "model_visible_headers", "component", fingerprint
        ),
        logical_input_hash=fingerprint,
        prepared_payload_hash=fingerprint,
    )


def test_evidence_free_resume_does_not_rebuild_historical_requests() -> None:
    snapshot = _snapshot(snapshot_id="snapshot-0")
    records = [
        ConversationRecord(
            record_id=f"snapshot-record-{index}",
            parent_id=(f"snapshot-record-{index - 1}" if index else None),
            kind="model.input.prepared",
            payload_version=1,
            created_at="2026-09-28T00:00:00Z",
            payload=replace(snapshot, snapshot_id=f"snapshot-{index}"),
            metadata={},
        )
        for index in range(700)
    ]

    def unexpected_rebuild(snapshot_id: str) -> None:
        pytest.fail(f"unrelated historical request was rebuilt: {snapshot_id}")

    runtime = SessionRequestEvidenceRuntime(
        get_context_message_bindings=lambda records=None: (),
        get_active_records=lambda: records,
        rebuild_model_input=unexpected_rebuild,
    )
    assert runtime.project_model_input(_preparation([])) is None
    assert runtime.project_model_input(_preparation([])) is None


def test_snapshot_only_evidence_follows_its_source_branch() -> None:
    message = _user_message("branch message")
    message_record = _message_record("message", message)
    evidence = _runtime([], []).prepare(
        PromptPreflightResult(
            text="branch message", loaded_skills=(_loaded_skill(),)
        )
    )
    assert evidence is not None
    payload = {
        "contextComplete": True,
        "schemaId": RESOURCE_EVIDENCE_SCHEMA_ID,
        "schemaVersion": 1,
        "messages": [
            evidence.to_message_payload(message_record_id="message", message_index=0)
        ],
    }
    component_hash = hash_model_input_json(payload, name="branch Resource evidence")
    component_record = ConversationRecord(
        record_id="component",
        parent_id="message",
        kind="model.input.component",
        payload_version=1,
        created_at="2026-09-28T00:00:00Z",
        payload=ModelInputComponent(content_hash=component_hash, content=payload),
        metadata={},
    )
    snapshot_record = ConversationRecord(
        record_id="snapshot-record",
        parent_id="component",
        kind="model.input.prepared",
        payload_version=1,
        created_at="2026-09-28T00:00:00Z",
        payload=_snapshot(
            snapshot_id="snapshot",
            additional_components=(
                ModelInputComponentReference(
                    RESOURCE_EVIDENCE_COMPONENT, "component", component_hash
                ),
            ),
        ),
        metadata={},
    )
    other_branch = ConversationRecord(
        record_id="other-branch",
        parent_id="message",
        kind="test.branch",
        payload_version=1,
        created_at="2026-09-28T00:00:00Z",
        payload=None,
        metadata={},
    )
    active = [message_record, component_record, snapshot_record]
    rebuilds: list[str] = []

    def rebuild(snapshot_id: str) -> SimpleNamespace:
        rebuilds.append(snapshot_id)
        return SimpleNamespace(
            logical_input={
                RESOURCE_EVIDENCE_COMPONENT: payload,
                "messages": [message],
            }
        )

    runtime = SessionRequestEvidenceRuntime(
        get_context_message_bindings=lambda records=None: tuple(
            (record.record_id, record.payload)
            for record in (active if records is None else records)
            if record.kind == "agent.message"
        ),
        get_active_records=lambda: active,
        rebuild_model_input=rebuild,
    )
    preparation = _preparation([message])
    assert runtime.project_model_input(preparation) == payload
    active[:] = [message_record]
    assert runtime.project_model_input(preparation) is None
    active[:] = [message_record, other_branch]
    assert runtime.project_model_input(preparation) is None
    active[:] = [message_record, component_record, snapshot_record]
    assert runtime.project_model_input(preparation) == payload
    assert rebuilds == ["snapshot", "snapshot"]


def test_anchor_hydration_is_atomic_after_invalid_metadata() -> None:
    first = _user_message("first")
    second = _user_message("second")
    evidence = _runtime([], []).prepare(
        PromptPreflightResult(text="first", loaded_skills=(_loaded_skill(),))
    )
    assert evidence is not None
    records = [
        _message_record(
            "first",
            first,
            metadata={RESOURCE_EVIDENCE_METADATA_KEY: evidence.to_message_metadata()},
        ),
        _message_record(
            "second",
            second,
            parent_id="first",
            metadata={RESOURCE_EVIDENCE_METADATA_KEY: {"schemaId": "invalid"}},
        ),
    ]
    runtime = SessionRequestEvidenceRuntime(
        get_context_message_bindings=lambda records=None: tuple(
            (record.record_id, record.payload)
            for record in (records if records is not None else active)
            if record.kind == "agent.message"
        ),
        get_active_records=lambda: active,
        rebuild_model_input=lambda _snapshot_id: pytest.fail("no snapshot exists"),
    )
    active = records
    with pytest.raises((RequestEvidenceIntegrityError, ValueError, TypeError)):
        runtime.project_model_input(_preparation([first, second]))
    assert runtime._recovered == {}
    assert runtime._hydrated_record_ids is None
    active = [records[0], replace(records[1], metadata={})]
    projected = runtime.project_model_input(_preparation([first, second]))
    assert projected is not None
    assert projected["messages"] == [
        evidence.to_message_payload(message_record_id="first", message_index=0)
    ]


def test_mixed_anchor_and_legacy_conflict_does_not_poison_retry() -> None:
    first = _user_message("first")
    second = _user_message("second")
    anchor = _runtime([], []).prepare(
        PromptPreflightResult(text="first", loaded_skills=(_loaded_skill(),))
    )
    legacy = _runtime([], []).prepare(
        PromptPreflightResult(text="second", loaded_skills=(_loaded_skill(),))
    )
    assert anchor is not None and legacy is not None
    conflicting_skill = dict(anchor.skills[0])
    conflicting_skill["catalogGeneration"] = 8
    conflicting = PreparedResourceEvidence(
        model_visible_text="first", skills=(conflicting_skill,)
    )
    payload = {
        "contextComplete": True,
        "schemaId": RESOURCE_EVIDENCE_SCHEMA_ID,
        "schemaVersion": 1,
        "messages": [
            conflicting.to_message_payload(message_record_id="first", message_index=0),
            legacy.to_message_payload(message_record_id="second", message_index=1),
        ],
    }
    component_hash = hash_model_input_json(payload, name="mixed Resource evidence")
    first_record = _message_record(
        "first",
        first,
        metadata={RESOURCE_EVIDENCE_METADATA_KEY: anchor.to_message_metadata()},
    )
    second_record = _message_record("second", second, parent_id="first")
    component_record = ConversationRecord(
        record_id="component",
        parent_id="second",
        kind="model.input.component",
        payload_version=1,
        created_at="2026-09-28T00:00:00Z",
        payload=ModelInputComponent(content_hash=component_hash, content=payload),
        metadata={},
    )
    snapshot_record = ConversationRecord(
        record_id="snapshot-record",
        parent_id="component",
        kind="model.input.prepared",
        payload_version=1,
        created_at="2026-09-28T00:00:00Z",
        payload=_snapshot(
            snapshot_id="snapshot",
            additional_components=(
                ModelInputComponentReference(
                    RESOURCE_EVIDENCE_COMPONENT, "component", component_hash
                ),
            ),
        ),
        metadata={},
    )
    active = [first_record, second_record, component_record, snapshot_record]
    runtime = SessionRequestEvidenceRuntime(
        get_context_message_bindings=lambda records=None: tuple(
            (record.record_id, record.payload)
            for record in (active if records is None else records)
            if record.kind == "agent.message"
        ),
        get_active_records=lambda: active,
        rebuild_model_input=lambda _snapshot_id: SimpleNamespace(
            logical_input={
                RESOURCE_EVIDENCE_COMPONENT: payload,
                "messages": [first, second],
            }
        ),
    )
    with pytest.raises(RequestEvidenceIntegrityError, match="disagrees"):
        runtime.project_model_input(_preparation([first, second]))
    assert runtime._recovered == {}
    assert runtime._hydrated_record_ids is None
    active[:] = [first_record, second_record]
    projected = runtime.project_model_input(_preparation([first, second]))
    assert projected is not None
    assert projected["messages"] == [
        anchor.to_message_payload(message_record_id="first", message_index=0)
    ]


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
