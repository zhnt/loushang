"""Pinned text recipe and synthetic model contract, not installed acceptance."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ._lmux_history_recipe import (
    history_digest,
    history_records,
    history_turn,
    validate_history,
    validate_history_window,
)
from ._lmux_synthetic_product import components


def test_exact_recipe_bytes_and_digest():
    records = history_records()
    assert validate_history(records) == {
        "recipe": "lmux-history-128x2048/v1", "rounds": 128, "records": 256,
        "text_bytes": 263680,
        "sha256": "00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41",
    }
    assert history_digest([]) == "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    for index in range(128):
        user, assistant = history_turn(index)
        assert user == f"history {index:04d}"
        assert len(user.encode("ascii")) == 12
        assert len(assistant.encode("ascii")) == 2048
        assert assistant.endswith(f"LMUX_HISTORY_{index:04d}_END")
        assert f"## History {index:04d}\n" in assistant
        assert f"- completed round {index:04d}\n" in assistant
        assert f"```text\ncode-{index:04d}\n```" in assistant
        assert "\r" not in assistant


@pytest.mark.parametrize("index", [-1, 128, True, 0.0, "0000", None])
def test_history_round_is_bounded(index):
    with pytest.raises(ValueError):
        history_turn(index)


@pytest.mark.parametrize("fault", ["early-edit", "missing", "duplicate", "reorder", "wrong-kind", "extra"])
def test_correct_tail_cannot_hide_corrupted_early_history(fault):
    records = history_records()
    tail = copy.deepcopy(records[-2:])
    if fault == "early-edit":
        records[1][1] = "x" + records[1][1][1:]
    elif fault == "missing":
        records.pop(0)
    elif fault == "duplicate":
        records[1] = records[0]
    elif fault == "reorder":
        records[0], records[1] = records[1], records[0]
    elif fault == "wrong-kind":
        records[0][0] = "assistant"
    else:
        records.insert(0, ["user", "extra"])
    assert records[-2:] == tail
    with pytest.raises(ValueError):
        validate_history(records)


def test_synthetic_product_emits_exact_recipe_without_tools():
    async def check():
        def witness(*args):
            pytest.fail("history does not execute tools or park producers")
        model, stream, _ = components(witness)
        for index in (0, 127):
            user, expected = history_turn(index)
            response = await stream(model, SimpleNamespace(messages=[SimpleNamespace(role="user", content=user)]))
            try:
                message = await response.result()
                assert message.content[0].text == expected
                assert message.stop_reason == "stop"
            finally:
                await response.aclose()
    asyncio.run(check())


@pytest.mark.parametrize("last", [0, 6, 7, 127])
def test_real_product_projection_matches_recipe_window(last):
    from loushang.ai.types import UserMessage
    from loushang.coding.hosted_session import CodingRealHostedSessionV1

    async def check():
        messages = []
        model, stream, _ = components(lambda *_: None)
        for index in range(last + 1):
            user, _ = history_turn(index)
            messages.append(UserMessage(role="user", content=user, timestamp=0.0))
            response = await stream(model, SimpleNamespace(messages=messages))
            try:
                messages.append(await response.result())
            finally:
                await response.aclose()
        # Exercise the real pure projection without opening a Session/store.
        owner = SimpleNamespace(_session=SimpleNamespace(messages=messages, session_name="History",
                                                        is_streaming=False), _revision=last + 1)
        snapshot = CodingRealHostedSessionV1.project_snapshot(owner)
        records = [[record.kind.value, record.text] for record in snapshot.records]
        validate_history_window(records, last)
        assert snapshot.truncated is (last >= 7)
        assert len(records) == (2 * (last + 1) if last < 7 else 15)
    asyncio.run(check())


@pytest.mark.parametrize("fault", ["old-round", "missing-latest", "duplicate", "changed-text", "missing-status"])
def test_tail_rejects_stale_or_wrong_latest_round(fault):
    from ._lmux_history_recipe import OMITTED
    records = [["status", OMITTED], *history_records()[-14:]]
    if fault == "old-round":
        records = [["status", OMITTED], *history_records()[-16:-2]]
    elif fault == "missing-latest":
        records.pop()
    elif fault == "duplicate":
        records.append(records[-1])
    elif fault == "changed-text":
        records[-1][1] = "wrong" + records[-1][1]
    else:
        records.pop(0)
    with pytest.raises(ValueError):
        validate_history_window(records, 127)
