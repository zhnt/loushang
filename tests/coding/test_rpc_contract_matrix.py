from __future__ import annotations

import asyncio
import json

import pytest

from loushang.harness.host.rpc import RpcWirePlayback, play_rpc_lines
from tests.coding.rpc_support import FakeRuntime, FakeSession


def test_rpc_contract_prompt_abort_and_extension_interaction_settle_once() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)

    async def scenario() -> tuple[dict[str, object], ...]:
        session._prompt_started = asyncio.Event()
        session._prompt_release = asyncio.Event()
        playback = RpcWirePlayback(runtime=runtime)

        await playback.dispatch(
            {"id": "prompt", "type": "prompt", "message": "keep working"}
        )
        await session._prompt_started.wait()

        interaction = asyncio.create_task(
            playback.host.extension_ui_context.confirm("Deploy?", "Continue?")
        )
        await asyncio.sleep(0)
        request = next(
            record
            for record in playback.snapshot().records
            if record.get("type") == "extension_ui_request"
        )
        await playback.dispatch(
            {
                "type": "extension_ui_response",
                "id": request["id"],
                "confirmed": True,
            }
        )
        assert await interaction is True

        await playback.dispatch({"id": "abort", "type": "abort"})
        finish_task = asyncio.create_task(playback.finish())
        await asyncio.sleep(0)
        assert finish_task.done() is False
        session._prompt_release.set()
        return (await finish_task).records

    records = asyncio.run(scenario())

    responses = [
        record
        for record in records
        if record.get("type") == "response"
    ]
    assert [record.get("id") for record in responses] == ["prompt", "abort"]
    assert session.abort_calls == 1
    assert session.wait_calls == 1


@pytest.mark.parametrize(
    ("command", "payload"),
    (
        ("new_session", {"cwd": "/tmp/project-b"}),
        ("switch_session", {"sessionId": "session-b"}),
        ("fork", {"entryId": "leaf-1"}),
        ("clone", {}),
    ),
)
def test_rpc_contract_lifecycle_rebinds_follow_up_to_current_session(
    command: str,
    payload: dict[str, object],
) -> None:
    previous = FakeSession(session_id="session-a", cwd="/tmp/project-a")
    current = FakeSession(session_id="session-b", cwd="/tmp/project-b")
    runtime = FakeRuntime(previous)
    runtime.queue_next_session(current)

    async def scenario() -> tuple[dict[str, object], ...]:
        playback = RpcWirePlayback(runtime=runtime)
        await playback.dispatch(
            {"id": "lifecycle", "type": command, **payload}
        )
        await playback.dispatch(
            {
                "id": "follow-up",
                "type": "follow_up",
                "message": "second round",
            }
        )
        return (await playback.finish()).records

    records = asyncio.run(scenario())

    assert previous.follow_up_calls == []
    assert current.follow_up_calls == [("second round", None)]
    assert [
        record.get("id")
        for record in records
        if record.get("type") == "response"
    ] == ["lifecycle", "follow-up"]


def test_rpc_contract_bash_abort_settles_cancelled_result_once() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)

    async def scenario() -> tuple[dict[str, object], ...]:
        session._bash_started = asyncio.Event()
        session._bash_release = asyncio.Event()
        playback = RpcWirePlayback(runtime=runtime)
        await playback.dispatch(
            {"id": "bash", "type": "bash", "command": "sleep 1"}
        )
        await session._bash_started.wait()
        await playback.dispatch({"id": "abort-bash", "type": "abort_bash"})
        return (await playback.finish()).records

    records = asyncio.run(scenario())

    responses = [
        record
        for record in records
        if record.get("type") == "response"
    ]
    assert [record.get("id") for record in responses] == ["abort-bash", "bash"]
    assert responses[1]["data"] == {
        "output": "partial\n",
        "exitCode": None,
        "cancelled": True,
        "truncated": False,
        "fullOutputPath": None,
    }
    assert session.abort_bash_calls == 1


@pytest.mark.parametrize(
    ("lines", "expected_commands"),
    (
        (
            (
                '{"id":"one","type":"set_session_name","name":"one"}\r\n',
                '{"id":"two","type":"set_session_name","name":"two"}',
            ),
            ("set_session_name", "set_session_name"),
        ),
        (
            (
                "{invalid json}\n",
                json.dumps({"id": "state", "type": "get_state"}) + "\n",
            ),
            ("parse", "get_state"),
        ),
    ),
)
def test_rpc_contract_raw_lines_preserve_framing_and_recovery(
    lines: tuple[str, ...],
    expected_commands: tuple[str, ...],
) -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")

    result = play_rpc_lines(
        runtime=FakeRuntime(session),
        lines=lines,
    )

    assert result.exit_codes == (0,)
    assert tuple(record.get("command") for record in result.records) == (
        expected_commands
    )
