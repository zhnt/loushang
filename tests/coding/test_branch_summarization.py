from __future__ import annotations

import asyncio

from loushang.ai.types import TextPart, UserMessage
from loushang.coding.session_manager import SessionManager


def test_collect_entries_for_branch_summary_returns_entries_from_old_leaf(
    tmp_path,
) -> None:
    from loushang.harness.transcript import collect_branch_summary_delta

    session = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
    )
    root_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="root")],
                timestamp=1.0,
            )
        )
    )
    branch_a_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="branch-a")],
                timestamp=2.0,
            )
        )
    )

    session.branch(root_id)
    branch_b_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="branch-b")],
                timestamp=3.0,
            )
        )
    )

    result = collect_branch_summary_delta(
        session, old_leaf_id=branch_a_id, target_id=branch_b_id
    )

    assert [entry.record_id for entry in result.records] == [branch_a_id]
    assert result.common_ancestor_id == root_id


def test_prepare_branch_entries_keeps_recent_messages_within_token_budget(
    tmp_path,
) -> None:
    from loushang.harness.transcript import prepare_branch_summary

    session = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
    )
    asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[
                    TextPart(
                        type="text",
                        text="older branch message that should be dropped first",
                    )
                ],
                timestamp=1.0,
            )
        )
    )
    latest_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="latest branch message")],
                timestamp=2.0,
            )
        )
    )

    preparation = prepare_branch_summary(session.get_branch(), token_budget=8)

    assert len(preparation.messages) == 1
    assert preparation.messages[0].role == "user"
    assert "latest branch message" in preparation.messages[0].content[0].text
    assert preparation.record_ids == (latest_id,)
    assert preparation.total_tokens > 0
