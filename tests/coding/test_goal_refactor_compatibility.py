"""Frozen pre-refactor records; never regenerate them in the reader under test."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.adapters._goal_planning_response import verify_response
from loushang.coding.adapters._goal_proposal import ProposalRejected
from loushang.coding.adapters._goal_store import GoalJournal, goal_journal_path
from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.transcript.codecs import create_agent_transcript_payload_registry
from loushang.harness.transcript.model_input import rebuild_model_input
from loushang.harnesswork.goal.contracts import (
    GOAL_LOCK_DIRECTORY,
    GOAL_WRITER_HASH_DOMAIN,
)
from loushang.harnesswork.goal.records import (
    decode_header,
    decode_record,
    encode_record,
    replay,
)

FIXTURES = Path(__file__).parent / "fixtures" / "goal_refactor_v1"


def frozen(name):
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    raw = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["fixtures"][name]
    return json.loads(raw)


@pytest.mark.parametrize("name", ["planning-response.json", "calculator-planning.json", "repository-planning.json"])
@pytest.mark.parametrize("changed", [False, True])
def test_pre_refactor_response_proof_is_read_without_new_prompt_or_records(changed, name):
    value = frozen(name)
    codec = ConversationJsonlRecordCodec(create_agent_transcript_payload_registry())
    records = tuple(codec.decode_record(record) for record in value["records"])

    class Manager:
        def get_branch(self, leaf):
            return list(records[: next(i for i, r in enumerate(records) if r.record_id == leaf) + 1])

        def rebuild_model_input(self, snapshot_id):
            return rebuild_model_input(
                SimpleNamespace(records=records, records_to=self.get_branch,
                                header=SimpleNamespace(conversation_id=value["session_id"])),
                snapshot_id,
            )

    kwargs = dict(session_id=value["session_id"], prompt=value["prompt"], raw=value["response"].encode())
    if changed:
        kwargs["prompt"] += " altered after migration"
        with pytest.raises(ProposalRejected):
            verify_response(Manager(), value["proof"], **kwargs)
    else:
        verify_response(Manager(), value["proof"], **kwargs)


def test_pre_refactor_goal_records_physical_path_lock_and_read_only_roundtrip(tmp_path):
    value = frozen("goal-records.json")
    header = decode_header(value["header"])
    records = tuple(decode_record(record) for record in value["records"])
    history = replay(header, records)
    assert history.goal("baseline-goal").status == "paused"
    root = tmp_path / "sessions"
    root.mkdir(mode=0o700)
    path = goal_journal_path(root, header.session_id)
    assert path.name == hashlib.sha256(header.session_id.encode()).hexdigest() + ".goal.jsonl"
    assert GOAL_LOCK_DIRECTORY == ".goal-writers"
    assert GOAL_WRITER_HASH_DOMAIN == "harnesswork-goal-writer/v1"
    # Materialize exact old envelopes, not records encoded by today's writer.
    path.write_text("\n".join(json.dumps(item) for item in (value["header"], *value["records"])) + "\n")
    path.chmod(0o600)
    initial_bytes = path.read_bytes()
    # A real old store also has its persistent writer lock. Establish that
    # physical admission artifact without re-encoding any frozen log bytes.
    admission = GoalJournal(root, header)
    try:
        admission.open()
    finally:
        admission.close()
    reader = GoalJournal(root, header, read_only=True)
    try:
        reader.open()
        actual_header, actual_records = reader.load()
        assert actual_header == header
        assert [dict(encode_record(record)) for record in actual_records] == value["records"]
        assert replay(actual_header, actual_records).goal("baseline-goal") == history.goal("baseline-goal")
    finally:
        reader.close()
    assert path.read_bytes() == initial_bytes


@pytest.mark.parametrize("kind", ["calculator", "repository"])
def test_real_pre_refactor_profile_prompt_parser_and_work_link(kind, tmp_path):
    from loushang.coding.adapters._goal_planning_shared import planning_prompt
    from loushang.coding.adapters._goal_proposal import parse_proposal
    from loushang.coding.adapters._goal_repository import (
        parse_repository_proposal,
        prompt,
    )
    from loushang.coding.adapters._work_evidence import project_work_evidence
    from loushang.harnesswork.event_log import JsonlEventLogBackend
    from loushang.harnesswork.goal.records import canonical

    value = frozen(kind + "-planning.json")
    material = value["input"].encode()
    builder = prompt if kind == "repository" else planning_prompt
    parser = parse_repository_proposal if kind == "repository" else parse_proposal
    assert builder(value["operation_id"], material) == value["prompt"]
    inputs = json.loads(material)
    proposal = parser(value["response"].encode(), known_evidence=[item["id"] for item in inputs["evidence"]])
    assert proposal.data() == value["report"]["proposal"]
    assert hashlib.sha256(material).hexdigest() == value["report"]["input_ref"]["sha256"]
    assert hashlib.sha256(value["response"].encode()).hexdigest() == value["report"]["response_ref"]["sha256"]
    path = tmp_path / "old-work.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in value["work_entries"]) + "\n")
    records = project_work_evidence(JsonlEventLogBackend(path).query())
    report = next(item for item in records if item.role == "goal_planning_report")
    assert report.operation_id == value["operation_id"]
    assert report.run_id == value["report"]["run_id"]
    assert report.session_id == value["session_id"]
    assert hashlib.sha256(canonical(value["report"]).encode()).hexdigest() == report.blob.sha256


def test_legacy_public_symbols_and_signatures_remain_stable():
    import importlib
    import inspect

    for path, expected in frozen("public-api.json").items():
        module, name = path.split(":")
        obj = getattr(importlib.import_module(module), name)
        assert (obj.__module__, obj.__qualname__) == (expected["module"], expected["qualname"])
        if expected["bases"] is not None:
            assert [base.__module__ + ":" + base.__qualname__ for base in obj.__bases__] == expected["bases"]
        for method, signature in expected["methods"].items():
            assert str(inspect.signature(getattr(obj, method))) == signature
