import asyncio
import sys

import pytest

from loushang.harness.host.rpc import RpcWirePlayback, play_rpc_wire
from tests.coding.rpc_support import (
    FakeRuntime,
    FakeSession,
    _assistant_message,
)


def _play_rpc_wire(
    runtime: FakeRuntime,
    *commands: dict[str, object],
) -> list[dict[str, object]]:
    result = play_rpc_wire(runtime=runtime, commands=commands)
    assert result.exit_codes == (0,) * len(commands)
    return list(result.records)


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="macOS env-sensitive golden/smoke; may hide a real macOS product bug — tracked separately as issue #455",
)
def test_rpc_wire_playback_preserves_cross_group_success_golden() -> None:
    session = FakeSession(
        session_id="session-a",
        cwd="/tmp/project",
        messages=[_assistant_message("ready")],
    )
    session.command_entries = [
        {
            "name": "deploy",
            "description": "Deploy project",
            "source": "extension",
            "source_info": {"path": "/tmp/project/extensions/deploy.py"},
        }
    ]
    session.packages = [{"name": "core", "source": "builtin"}]

    assert _play_rpc_wire(
        FakeRuntime(session),
        {"id": "commands", "type": "get_commands"},
        {"id": "last", "type": "get_last_assistant_text"},
        {"id": "models", "type": "get_available_models"},
        {"id": "packages", "type": "get_packages"},
        {"id": "compact", "type": "compact"},
        {
            "id": "export",
            "type": "export_html",
            "outputPath": "/tmp/exported.html",
        },
    ) == [
        {
            "id": "commands",
            "type": "response",
            "command": "get_commands",
            "success": True,
            "data": {
                "commands": [
                    {
                        "name": "deploy",
                        "description": "Deploy project",
                        "source": "extension",
                        "sourceInfo": {
                            "path": "/tmp/project/extensions/deploy.py",
                            "source": "filesystem",
                            "scope": "project",
                            "origin": "top-level",
                            "baseDir": "/tmp/project/extensions",
                        },
                    }
                ]
            },
        },
        {
            "id": "last",
            "type": "response",
            "command": "get_last_assistant_text",
            "success": True,
            "data": {"text": "ready"},
        },
        {
            "id": "models",
            "type": "response",
            "command": "get_available_models",
            "success": True,
            "data": {"models": []},
        },
        {
            "id": "packages",
            "type": "response",
            "command": "get_packages",
            "success": True,
            "data": {"packages": [{"name": "core", "source": "builtin"}]},
        },
        {
            "id": "compact",
            "type": "response",
            "command": "compact",
            "success": True,
            "data": {
                "summary": "compacted",
                "firstKeptEntryId": "entry-1",
                "tokensBefore": 42,
                "details": {"preserved": 3},
            },
        },
        {
            "id": "export",
            "type": "response",
            "command": "export_html",
            "success": True,
            "data": {"path": "/tmp/exported.html"},
        },
    ]


def test_rpc_wire_playback_resolves_groups_against_rebound_session() -> None:
    initial = FakeSession(
        session_id="initial",
        cwd="/tmp/project",
        messages=[_assistant_message("old")],
    )
    replacement = FakeSession(
        session_id="replacement",
        cwd="/tmp/project",
        messages=[_assistant_message("new")],
    )
    replacement.command_entries = [
        {
            "name": "replacement-command",
            "source": "prompt",
            "source_info": {"path": "/tmp/project/prompts/replacement.md"},
        }
    ]
    runtime = FakeRuntime(initial)
    runtime.queue_next_session(replacement)

    assert _play_rpc_wire(
        runtime,
        {"id": "new", "type": "new_session"},
        {"id": "last", "type": "get_last_assistant_text"},
        {"id": "commands", "type": "get_commands"},
    ) == [
        {
            "id": "new",
            "type": "response",
            "command": "new_session",
            "success": True,
            "data": {"cancelled": False},
        },
        {
            "id": "last",
            "type": "response",
            "command": "get_last_assistant_text",
            "success": True,
            "data": {"text": "new"},
        },
        {
            "id": "commands",
            "type": "response",
            "command": "get_commands",
            "success": True,
            "data": {
                "commands": [
                    {
                        "name": "replacement-command",
                        "description": None,
                        "source": "prompt",
                        "sourceInfo": {
                            "path": "/tmp/project/prompts/replacement.md",
                            "source": "filesystem",
                            "scope": "project",
                            "origin": "top-level",
                            "baseDir": "/tmp/project/prompts",
                        },
                    }
                ]
            },
        },
    ]


def test_rpc_wire_playback_preserves_async_prompt_and_bash_golden() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")

    assert _play_rpc_wire(
        FakeRuntime(session),
        {"id": "prompt", "type": "prompt", "message": "hello"},
        {"id": "bash", "type": "bash", "command": "printf ok"},
    ) == [
        {
            "id": "prompt",
            "type": "response",
            "command": "prompt",
            "success": True,
        },
        {
            "id": "bash",
            "type": "response",
            "command": "bash",
            "success": True,
            "data": {
                "output": "ok\n",
                "exitCode": 0,
                "cancelled": False,
                "truncated": False,
                "fullOutputPath": None,
            },
        },
    ]
    assert session.prompt_calls == [("hello", None)]
    assert session.wait_calls == 1
    assert session.bash_calls == [
        {
            "command": "printf ok",
            "cwd": None,
            "env": None,
            "timeout_seconds": None,
            "stdin": None,
        }
    ]


def test_rpc_wire_playback_preserves_validation_error_golden() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")

    assert _play_rpc_wire(
        FakeRuntime(session),
        {
            "id": "prefix",
            "type": "get_command_completions",
            "prefix": 3,
        },
        {
            "id": "command",
            "type": "get_command_completions",
            "command": "",
        },
    ) == [
        {
            "id": "prefix",
            "type": "response",
            "command": "get_command_completions",
            "success": False,
            "error": "Command completion prefix must be a string.",
            "errorCode": "invalid_request",
            "errorInfo": {
                "code": "invalid_request",
                "message": "Command completion prefix must be a string.",
                "command": "get_command_completions",
            },
        },
        {
            "id": "command",
            "type": "response",
            "command": "get_command_completions",
            "success": False,
            "error": "Command completion command must be a non-empty string.",
            "errorCode": "invalid_request",
            "errorInfo": {
                "code": "invalid_request",
                "message": (
                    "Command completion command must be a non-empty string."
                ),
                "command": "get_command_completions",
            },
        },
    ]


def test_rpc_wire_playback_aborts_immediately_then_settles_prompt_once() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)

    async def scenario() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        session._prompt_started = asyncio.Event()
        session._prompt_release = asyncio.Event()
        playback = RpcWirePlayback(runtime=runtime)

        assert (
            await playback.dispatch(
                {"id": "prompt", "type": "prompt", "message": "keep working"}
            )
            == 0
        )
        await session._prompt_started.wait()
        assert list(playback.snapshot().records) == [
            {
                "id": "prompt",
                "type": "response",
                "command": "prompt",
                "success": True,
            }
        ]

        assert await playback.dispatch({"id": "abort", "type": "abort"}) == 0
        immediate = list(playback.snapshot().records)
        finish_task = asyncio.create_task(playback.finish())
        await asyncio.sleep(0)
        assert finish_task.done() is False

        session._prompt_release.set()
        settled = await finish_task
        return immediate, list(settled.records)

    immediate, settled = asyncio.run(scenario())

    abort_response = {
        "id": "abort",
        "type": "response",
        "command": "abort",
        "success": True,
    }
    assert abort_response in immediate
    assert settled == immediate
    assert session.abort_calls == 1
    assert session.wait_calls == 1


def test_rpc_wire_playback_dispose_waits_for_outstanding_prompt() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)

    async def scenario() -> None:
        session._prompt_started = asyncio.Event()
        session._prompt_release = asyncio.Event()
        playback = RpcWirePlayback(runtime=runtime)
        await playback.dispatch(
            {"id": "prompt", "type": "prompt", "message": "finish before close"}
        )
        await session._prompt_started.wait()

        dispose_task = asyncio.create_task(playback.dispose())
        await asyncio.sleep(0)
        assert dispose_task.done() is False

        session._prompt_release.set()
        await dispose_task

    asyncio.run(scenario())

    assert session.wait_calls == 1
    assert session.listeners == []
