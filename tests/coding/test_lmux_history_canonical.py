"""Real typed file/replay checks; fixtures are not the public seed workflow."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from loushang.ai.types import UserMessage
from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1
from loushang.harness.conversation import ConversationHeader
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    AgentTranscriptRecord,
    write_agent_transcript_export,
)

from . import _lmux_history_canonical as reader
from ._lmux_history_recipe import history_turn
from ._lmux_synthetic_product import components


@pytest.mark.parametrize("fault", [None, "wrong-session", "wrong-scope", "wrong-cwd", "early-edit",
                                  "broken-parent", "old-parent", "duplicate-id"])
def test_canonical_read_uses_typed_codec_and_never_changes_files(tmp_path, monkeypatch, fault):
    identity = SessionIdentityV1("coding", "continuity", "session", SessionScopeV1.USER_HOME, "a" * 64)
    metadata = {"cwd": str(tmp_path), "coding.hosted": {
        "version": 1, "compatibilityId": reader.CODING_HOSTED_COMPATIBILITY_ID,
        "continuityId": identity.continuity_id, "sessionId": identity.session_id,
        "scope": identity.scope.value, "scopeFingerprint": identity.scope_fingerprint,
        "operationId": "create-history",
    }}
    header = ConversationHeader(identity.session_id, 1, "2026-09-15T00:00:00Z", metadata=metadata)

    async def records():
        result = []
        model, stream, _ = components(lambda *_: None)
        for index in range(128):
            text, _ = history_turn(index)
            user = UserMessage(role="user", content=text, timestamp=0.0)
            response = await stream(model, SimpleNamespace(messages=[user]))
            try:
                assistant = await response.result()
            finally:
                await response.aclose()
            if index == 0 and fault == "early-edit":
                user = replace(user, content="corrupted early history")
            for message in (user, assistant):
                result.append(AgentTranscriptRecord(
                    record_id=f"r{len(result)}", parent_id=f"r{len(result)-1}" if result else None,
                    kind=AGENT_MESSAGE_KIND, payload_version=1, created_at="2026-09-15T00:00:00Z", payload=message,
                ))
        if fault == "broken-parent":
            result[20] = replace(result[20], parent_id=None)
        elif fault == "old-parent":
            result[20] = replace(result[20], parent_id="r0")
        elif fault == "duplicate-id":
            result[20] = replace(result[20], record_id="r0")
        return result

    path = tmp_path / "hosted-session.jsonl"
    write_agent_transcript_export(path, header, asyncio.run(records()))

    def snapshot():
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino, p.stat().st_mode)
                for p in tmp_path.iterdir() if p.is_file()}

    before = snapshot()
    original_read, calls = reader.load_agent_transcript_file, []
    def read(selected_path, **kwargs):
        assert selected_path == path
        assert kwargs == {"read_only": True, "max_bytes": 2_097_152}
        calls.append(selected_path)
        return original_read(selected_path, **kwargs)
    monkeypatch.setattr(reader, "load_agent_transcript_file", read)
    selected = replace(identity, continuity_id="other") if fault == "wrong-session" else identity
    if fault == "wrong-scope":
        selected = replace(identity, scope_fingerprint="b" * 64)
    workspace = tmp_path / "other" if fault == "wrong-cwd" else tmp_path
    evidence = {}
    if fault:
        with pytest.raises(ValueError):
            reader.read_history(tmp_path, selected, workspace, receipt=evidence)
        assert evidence == {}
    else:
        receipt = reader.read_history(tmp_path, selected, workspace, receipt=evidence)
        assert receipt["sha256"] == "00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41"
        assert receipt["text_bytes"] == 263680
        assert evidence["canonical"] == receipt
        assert evidence["root"] == str(tmp_path) and evidence["path"] == str(path)
        assert evidence["identity"]["session_id"] == identity.session_id
        assert evidence["started_at"] <= evidence["completed_at"]
    assert snapshot() == before
    assert calls == [path]
