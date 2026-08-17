from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from loushang.ai.types import TextPart, UserMessage
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    TranscriptExportRequest,
    TranscriptHtmlExportProfile,
    export_agent_transcript_to_html,
    export_agent_transcript_to_jsonl,
    load_agent_transcript_file,
)


def _header() -> ConversationHeader:
    return ConversationHeader(
        conversation_id="conversation-1",
        version=1,
        created_at="2026-07-20T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )


def _record(
    record_id: str,
    parent_id: str | None,
    text: str,
) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-20T00:00:01Z",
        payload=UserMessage(
            role="user",
            content=[TextPart(type="text", text=text)],
            timestamp=1.0,
        ),
    )


def test_html_export_is_product_neutral_and_embeds_conversation_jsonl_records(
    tmp_path: Path,
) -> None:
    record = _record("record-1", None, "hello export")
    request = TranscriptExportRequest(
        header=_header(),
        conversation_name="Export example",
        entries=[record],
        branch_entries=[record],
        leaf_id=record.record_id,
        messages=[record.payload],
        stats={"entry_count": 1, "source": "test"},
        entry_count=1,
        message_count=1,
        active_tool_count=0,
        estimated_context_tokens=4,
        system_prompt="Be useful.",
    )

    path = tmp_path / "transcript.html"
    output = export_agent_transcript_to_html(
        request,
        path,
        profile=TranscriptHtmlExportProfile(
            title="Portable Transcript",
            theme={"accent-color": "#123456"},
        ),
    )
    rendered = path.read_text(encoding="utf-8")

    assert output == str(path)
    assert "Portable Transcript" in rendered
    assert "hello export" in rendered
    assert "--accent-color: #123456;" in rendered
    encoded = re.search(
        r'<script id="session-data" type="application/json">([^<]+)</script>',
        rendered,
    )
    assert encoded is not None
    data = json.loads(base64.b64decode(encoded.group(1)).decode("utf-8"))
    assert data["header"]["conversationId"] == "conversation-1"
    assert data["entries"][0]["recordId"] == "record-1"
    assert data["stats"] == {"entry_count": 1, "source": "test"}


def test_jsonl_export_linearizes_selected_branch_without_a_product_store(
    tmp_path: Path,
) -> None:
    first = _record("record-1", None, "first")
    second = _record("record-2", "other-branch-parent", "selected")

    path = tmp_path / "branch.jsonl"
    output = export_agent_transcript_to_jsonl(_header(), [first, second], path)
    header, records = load_agent_transcript_file(path)

    assert output == str(path)
    assert header == _header()
    assert [record.record_id for record in records] == ["record-1", "record-2"]
    assert [record.parent_id for record in records] == [None, "record-1"]
