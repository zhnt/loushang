"""Shared response verification reads original Transcript facts without Goal APIs."""
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.session.response_proof import ResponseProofError, verify_response
from loushang.harness.transcript.codecs import create_agent_transcript_payload_registry
from loushang.harness.transcript.model_input import rebuild_model_input


def test_shared_reader_accepts_immutable_proof_and_rejects_changed_input():
    # Reuse the independently frozen pre-refactor wire sample. No new writer,
    # Product class or proposal parser participates in this reader check.
    fixture = Path(__file__).parents[2] / "coding/fixtures/goal_refactor_v1/planning-response.json"
    value = json.loads(fixture.read_text())
    codec = ConversationJsonlRecordCodec(create_agent_transcript_payload_registry())
    records = tuple(codec.decode_record(row) for row in value["records"])

    class Reader:
        def get_branch(self, leaf):
            return list(records[:next(i for i, record in enumerate(records) if record.record_id == leaf) + 1])

        def rebuild_model_input(self, snapshot_id):
            return rebuild_model_input(SimpleNamespace(
                records=records, records_to=self.get_branch,
                header=SimpleNamespace(conversation_id=value["session_id"]),
            ), snapshot_id)

    proof = MappingProxyType({**value["proof"], "snapshot_ids": tuple(value["proof"]["snapshot_ids"])})
    arguments = dict(session_id=value["session_id"], prompt=value["prompt"], raw=value["response"].encode())
    verify_response(Reader(), proof, **arguments, max_attempts=1)
    with pytest.raises(ResponseProofError, match="response prompt differs from trusted input"):
        verify_response(Reader(), proof, **{**arguments, "prompt": "a different request"})

