from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from loushang.harness.conversation import ConversationRecord
from loushang.harness.transcript import (
    MODEL_CALL_ATTEMPT_USAGE_KIND,
    MODEL_INPUT_PREPARED_KIND,
    AgentTranscriptRecord,
    ModelCallAttemptUsage,
    ModelInputComponentReference,
    ModelInputIntegrityError,
    ModelInputSnapshot,
    project_model_call_usage,
)


def test_attempt_usage_replay_replaces_partial_components_and_sums_attempts() -> None:
    records = (
        _record("snapshot-1", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-1", 1)),
        _record(
            "usage-1",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _usage(attempt=1, input=10, cache_read=2, total_tokens=12),
        ),
        _record(
            "usage-2",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _usage(attempt=1, output=5),
        ),
        _record(
            "usage-2-duplicate",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _usage(attempt=1, output=5),
        ),
        _record(
            "usage-3",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _usage(attempt=1, input=20, total_tokens=15, terminal=True),
        ),
        _record("snapshot-2", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-2", 2)),
        _record(
            "usage-4",
            MODEL_CALL_ATTEMPT_USAGE_KIND,
            _usage(
                attempt=2,
                snapshot_id="snapshot-2",
                input=7,
                terminal=True,
            ),
        ),
    )

    ledger = project_model_call_usage(records)

    assert len(ledger.attempts) == 2
    assert ledger.attempts[0].usage.input == 20
    assert ledger.attempts[0].usage.output == 5
    assert ledger.attempts[0].usage.cache_read == 2
    assert ledger.attempts[0].usage.total_tokens == 27
    assert ledger.usage.input == 27
    assert ledger.usage.output == 5
    assert ledger.usage.cache_read == 2
    assert ledger.usage.total_tokens == 34
    assert ledger.complete is True


def test_attempt_usage_replay_marks_empty_and_nonterminal_coverage_incomplete() -> None:
    assert project_model_call_usage(()).complete is False
    ledger = project_model_call_usage(
        (
            _record(
                "snapshot-1", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-1", 1)
            ),
            _record(
                "usage-1",
                MODEL_CALL_ATTEMPT_USAGE_KIND,
                _usage(attempt=1, input=1),
            ),
        )
    )

    assert ledger.complete is False
    assert ledger.usage.total_tokens == 1

    mixed = project_model_call_usage(
        (
            _record(
                "snapshot-1", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-1", 1)
            ),
            _record(
                "usage-1",
                MODEL_CALL_ATTEMPT_USAGE_KIND,
                _usage(attempt=1, input=1, terminal=True),
            ),
            _record(
                "snapshot-2", MODEL_INPUT_PREPARED_KIND, _snapshot("snapshot-2", 2)
            ),
        )
    )

    assert mixed.attempts[0].terminal is True
    assert mixed.complete is False


def test_attempt_usage_replay_rejects_missing_lineage_and_post_terminal_change() -> None:
    with pytest.raises(ModelInputIntegrityError, match="matching prior Model Input"):
        project_model_call_usage(
            (
                _record(
                    "usage-1",
                    MODEL_CALL_ATTEMPT_USAGE_KIND,
                    _usage(attempt=1, input=1),
                ),
            )
        )

    with pytest.raises(ModelInputIntegrityError, match="after its terminal"):
        project_model_call_usage(
            (
                _record(
                    "snapshot-1",
                    MODEL_INPUT_PREPARED_KIND,
                    _snapshot("snapshot-1", 1),
                ),
                _record(
                    "usage-1",
                    MODEL_CALL_ATTEMPT_USAGE_KIND,
                    _usage(attempt=1, input=1, terminal=True),
                ),
                _record(
                    "usage-2",
                    MODEL_CALL_ATTEMPT_USAGE_KIND,
                    _usage(attempt=1, output=1),
                ),
            )
        )


def test_attempt_usage_fact_rejects_empty_and_negative_observations() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        _usage(attempt=1)
    with pytest.raises(ValueError, match="must be non-negative"):
        _usage(attempt=1, input=-1)


def _usage(
    *,
    attempt: int,
    snapshot_id: str = "snapshot-1",
    input: int | None = None,
    output: int | None = None,
    cache_read: int | None = None,
    total_tokens: int | None = None,
    terminal: bool = False,
) -> ModelCallAttemptUsage:
    return ModelCallAttemptUsage(
        invocation_id="invocation-1",
        attempt=attempt,
        model_input_snapshot_id=snapshot_id,
        input=input,
        output=output,
        cache_read=cache_read,
        total_tokens=total_tokens,
        terminal=terminal,
    )


def _snapshot(snapshot_id: str, attempt: int) -> ModelInputSnapshot:
    reference = ModelInputComponentReference(
        name="messages",
        record_id="component-record",
        content_hash="a" * 64,
    )
    return ModelInputSnapshot(
        snapshot_id=snapshot_id,
        invocation_id="invocation-1",
        attempt=attempt,
        purpose="main_turn",
        product_id="coding",
        runtime_id="runtime-1",
        mount_generation=1,
        profile_fingerprint="b" * 64,
        registration_revision="c" * 64,
        conversation_id="conversation-1",
        source_leaf_id="source-record",
        source_revision=1,
        commit_revision=2,
        provider_id="provider-1",
        model_id="model-1",
        api_id="api-1",
        endpoint_id="endpoint-1",
        logical_components=tuple(
            replace(reference, name=name)
            for name in ("system_prompt", "messages", "tools", "request_options")
        ),
        prepared_payload_components=(reference,),
        model_visible_headers_component=replace(
            reference, name="model_visible_headers"
        ),
        logical_input_hash="d" * 64,
        prepared_payload_hash="e" * 64,
    )


def _record(record_id: str, kind: str, payload: object) -> AgentTranscriptRecord:
    return cast(
        AgentTranscriptRecord,
        ConversationRecord(
            record_id=record_id,
            parent_id=None,
            kind=kind,
            payload_version=1,
            created_at="2026-08-26T00:00:00Z",
            payload=payload,
        ),
    )
