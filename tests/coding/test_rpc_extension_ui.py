from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path

from loushang.ai.model.domain import (
    Capabilities,
    Model,
)
from loushang.harness.host.rpc import play_rpc_lines
from tests.coding.rpc_support import (
    FakeRuntime,
    FakeSession,
    _parse_jsonl,
)


def test_rpc_mode_supports_bash_command() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "bash", "type": "bash", "command": "printf hi"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.bash_calls == [
        {
            "command": "printf hi",
            "cwd": None,
            "env": None,
            "timeout_seconds": None,
            "stdin": None,
        }
    ]
    assert _parse_jsonl(stdout) == [
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
        }
    ]


def test_rpc_mode_allows_aborting_active_bash_command() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session._bash_started = asyncio.Event()
    session._bash_release = asyncio.Event()
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "bash", "type": "bash", "command": "sleep 1"}),
                json.dumps({"id": "abort-bash", "type": "abort_bash"}),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await asyncio.wait_for(mode.run(), timeout=0.5)
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.abort_bash_calls == 1
    lines = _parse_jsonl(stdout)
    assert lines[0] == {
        "id": "abort-bash",
        "type": "response",
        "command": "abort_bash",
        "success": True,
    }
    assert lines[1] == {
        "id": "bash",
        "type": "response",
        "command": "bash",
        "success": True,
        "data": {
            "output": "partial\n",
            "exitCode": None,
            "cancelled": True,
            "truncated": False,
            "fullOutputPath": None,
        },
    }


def test_rpc_mode_supports_clone_and_get_fork_messages() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    current = FakeSession(session_id="session-a", cwd="/tmp/project-a")
    current.user_messages_for_forking = [
        {"entry_id": "u1", "text": "first"},
        {"entry_id": "u2", "text": "second"},
    ]
    next_session = FakeSession(session_id="session-b", cwd="/tmp/project-b")
    runtime = FakeRuntime(current)
    runtime.queue_next_session(next_session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "fork-messages", "type": "get_fork_messages"}),
                json.dumps({"id": "clone", "type": "clone"}),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.fork_session_calls == ["leaf-1"]
    lines = _parse_jsonl(stdout)
    assert lines[0] == {
        "id": "fork-messages",
        "type": "response",
        "command": "get_fork_messages",
        "success": True,
        "data": {
            "messages": [
                {"entryId": "u1", "text": "first"},
                {"entryId": "u2", "text": "second"},
            ]
        },
    }
    assert lines[1] == {
        "id": "clone",
        "type": "response",
        "command": "clone",
        "success": True,
        "data": {"cancelled": False},
    }


def test_rpc_mode_get_fork_messages_uses_standard_session_method() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class StandardForkSession(FakeSession):
        def get_user_messages_for_forking(self):
            return [{"entry_id": "u1", "text": "first"}]

    session = StandardForkSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "fork-messages", "type": "get_fork_messages"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout)[0]["data"] == {
        "messages": [{"entryId": "u1", "text": "first"}]
    }


def test_rpc_mode_reports_invalid_json_and_unsupported_commands() -> None:
    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    result = play_rpc_lines(
        runtime=runtime,
        lines=(
            "{invalid json}\n",
            json.dumps({"id": "oops", "type": "unknown"}) + "\n",
        ),
    )

    assert result.exit_codes == (0,)
    invalid, unsupported = result.records
    assert invalid["type"] == "response"
    assert invalid["command"] == "parse"
    assert invalid["success"] is False
    assert "Failed to parse command" in invalid["error"]

    assert unsupported["type"] == "response"
    assert unsupported["command"] == "unknown"
    assert unsupported["success"] is False
    assert "unsupported command" in unsupported["error"]
    assert unsupported["errorCode"] == "unsupported_command"
    assert unsupported["errorInfo"]["message"] == unsupported["error"]
    assert unsupported["errorInfo"]["command"] == "unknown"


def test_rpc_mode_rejects_non_finite_input_numbers() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    result = play_rpc_lines(
        runtime=runtime,
        lines=tuple(
            line + "\n"
            for line in (
                '{"type":"get_state","value":NaN}',
                '{"type":"get_state","value":Infinity}',
                '{"type":"get_state","value":-Infinity}',
                '{"id":"bash","type":"bash","command":"printf hi","timeoutSeconds":1e400}',
                '{"id":"prompt","type":"prompt","message":"\\ud800"}',
            )
        ),
    )

    assert result.exit_codes == (0,)
    responses = result.records
    assert session.bash_calls == []
    assert session.prompt_calls == []
    assert [response["command"] for response in responses[:3]] == [
        "parse",
        "parse",
        "parse",
    ]
    assert [response["error"] for response in responses[:3]] == [
        "Failed to parse command: invalid JSON numeric constant: NaN",
        "Failed to parse command: invalid JSON numeric constant: Infinity",
        "Failed to parse command: invalid JSON numeric constant: -Infinity",
    ]
    assert responses[3] == {
        "id": "bash",
        "type": "response",
        "command": "invalid",
        "success": False,
        "error": (
            "RPC command contains a value outside strict JSON: "
            "rpc_command.timeoutSeconds must be JSON-safe: non-finite float"
        ),
    }
    assert responses[4] == {
        "id": "prompt",
        "type": "response",
        "command": "invalid",
        "success": False,
        "error": (
            "RPC command contains a value outside strict JSON: "
            "rpc_command.message must be JSON-safe: string is not valid UTF-8"
        ),
    }


def test_rpc_mode_jsonl_framing_preserves_unicode_line_separators() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    name = "alpha\u2028beta\u2029gamma"
    result = play_rpc_lines(
        runtime=runtime,
        lines=(
            json.dumps(
                {"id": "rename", "type": "set_session_name", "name": name},
                ensure_ascii=False,
            )
            + "\n",
        ),
    )

    assert session.set_session_name_calls == [name]
    assert list(result.records) == [
        {
            "id": "rename",
            "type": "response",
            "command": "set_session_name",
            "success": True,
        }
    ]


def test_rpc_mode_jsonl_framing_accepts_crlf_and_final_line_without_lf() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    result = play_rpc_lines(
        runtime=runtime,
        lines=(
            json.dumps({"id": "first", "type": "set_session_name", "name": "one"})
            + "\r\n",
            json.dumps({"id": "second", "type": "set_session_name", "name": "two"}),
        ),
    )

    assert session.set_session_name_calls == ["one", "two"]
    assert list(result.records) == [
        {
            "id": "first",
            "type": "response",
            "command": "set_session_name",
            "success": True,
        },
        {
            "id": "second",
            "type": "response",
            "command": "set_session_name",
            "success": True,
        },
    ]


def test_rpc_mode_ignores_unmatched_extension_ui_responses() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {"id": "ui-1", "type": "extension_ui_response", "value": "ignored"}
                ),
                json.dumps({"id": "state", "type": "get_state"}),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    lines = _parse_jsonl(stdout)
    assert len(lines) == 1
    assert lines[0]["id"] == "state"
    assert lines[0]["command"] == "get_state"


def test_rpc_mode_extension_ui_context_emits_side_effect_requests() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()
    mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)

    mode.extension_ui_context.notify("Build finished", "info")
    mode.extension_ui_context.set_status("deploy", "running")
    mode.extension_ui_context.set_title("Deploying")
    mode.extension_ui_context.set_editor_text("next prompt")
    mode.extension_ui_context.set_widget(
        "summary", ["line 1", "line 2"], placement="belowEditor"
    )

    lines = _parse_jsonl(stdout)
    assert [line["method"] for line in lines] == [
        "notify",
        "setStatus",
        "setTitle",
        "set_editor_text",
        "setWidget",
    ]
    assert lines[0]["message"] == "Build finished"
    assert lines[0]["notifyType"] == "info"
    assert lines[1]["statusKey"] == "deploy"
    assert lines[1]["statusText"] == "running"
    assert lines[2]["title"] == "Deploying"
    assert lines[3]["text"] == "next prompt"
    assert lines[4]["widgetKey"] == "summary"
    assert lines[4]["widgetLines"] == ["line 1", "line 2"]
    assert lines[4]["widgetPlacement"] == "belowEditor"


def test_rpc_mode_exposes_extension_ui_state_snapshot() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()
    mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)

    mode.extension_ui_context.notify("Build finished", "info")
    mode.extension_ui_context.set_status("deploy", "running")
    mode.extension_ui_context.set_title("Deploying")
    mode.extension_ui_context.set_editor_text("next prompt")
    mode.extension_ui_context.set_widget("summary", ["line 1"], placement="belowEditor")
    mode._handle_get_extension_ui_state_command("ui-state", {})

    response = _parse_jsonl(stdout)[-1]
    assert response == {
        "id": "ui-state",
        "type": "response",
        "command": "get_extension_ui_state",
        "success": True,
        "data": {
            "notifications": [{"message": "Build finished", "notifyType": "info"}],
            "statuses": {"deploy": "running"},
            "widgets": {"summary": {"lines": ["line 1"], "placement": "belowEditor"}},
            "title": "Deploying",
            "editorText": "next prompt",
        },
    }


def test_rpc_mode_extension_ui_context_resolves_dialog_responses() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
        task = asyncio.create_task(
            mode.extension_ui_context.select("Choose target", ["dev", "prod"])
        )
        await asyncio.sleep(0)
        request = _parse_jsonl(stdout)[0]
        assert request["type"] == "extension_ui_request"
        assert request["method"] == "select"
        assert request["title"] == "Choose target"
        assert request["options"] == ["dev", "prod"]
        assert await mode.submit_input(
            json.dumps(
                {"type": "extension_ui_response", "id": request["id"], "value": "prod"}
            )
        ) == 0
        assert await asyncio.wait_for(task, timeout=0.5) == "prod"

    asyncio.run(scenario())


def test_rpc_mode_extension_ui_context_resolves_confirm_input_and_editor_responses() -> (
    None
):
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
        confirm_task = asyncio.create_task(
            mode.extension_ui_context.confirm("Deploy?", "Ship to prod?")
        )
        input_task = asyncio.create_task(
            mode.extension_ui_context.input("Branch", "main")
        )
        editor_task = asyncio.create_task(
            mode.extension_ui_context.editor("Edit prompt", "draft")
        )
        await asyncio.sleep(0)
        requests = _parse_jsonl(stdout)
        assert [request["method"] for request in requests] == [
            "confirm",
            "input",
            "editor",
        ]
        assert requests[0]["message"] == "Ship to prod?"
        assert requests[1]["placeholder"] == "main"
        assert requests[2]["prefill"] == "draft"
        assert await mode.submit_input(
            json.dumps(
                {
                    "type": "extension_ui_response",
                    "id": requests[0]["id"],
                    "confirmed": True,
                }
            )
        ) == 0
        assert await mode.submit_input(
            json.dumps(
                {
                    "type": "extension_ui_response",
                    "id": requests[1]["id"],
                    "value": "feature",
                }
            )
        ) == 0
        assert await mode.submit_input(
            json.dumps(
                {
                    "type": "extension_ui_response",
                    "id": requests[2]["id"],
                    "value": "edited",
                }
            )
        ) == 0
        assert await asyncio.wait_for(confirm_task, timeout=0.5) is True
        assert await asyncio.wait_for(input_task, timeout=0.5) == "feature"
        assert await asyncio.wait_for(editor_task, timeout=0.5) == "edited"

    asyncio.run(scenario())


def test_rpc_mode_binds_extension_context_ui_methods_to_rpc_requests(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.host.rpc import RpcHost as RpcMode

    extension_runner = ExtensionRunner(
        [
            LoadedExtension(
                name="rpc-ui",
                source_path=Path("/tmp/rpc_ui.py"),
            )
        ]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny",
                    provider="faux",
                    endpoint="test",
                    capabilities=Capabilities(
                        input=("text",), context_window=10_000, max_tokens=1024
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=extension_runner,
    )
    runtime = FakeRuntime(session)
    stdout = StringIO()

    RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
    context = extension_runner.create_command_context(fallback_cwd="/tmp/project")
    context.notify("Starting", "info")
    context.set_title("Working")
    context.set_status("phase", "prompt")

    requests = _parse_jsonl(stdout)
    assert [request["method"] for request in requests] == [
        "notify",
        "setTitle",
        "setStatus",
    ]


def test_rpc_mode_extension_context_excludes_pi_style_camel_case_ui_methods(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.host.rpc import RpcHost as RpcMode

    extension_runner = ExtensionRunner(
        [LoadedExtension(name="rpc-ui", source_path=Path("/tmp/rpc_ui.py"))]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny",
                    provider="faux",
                    endpoint="test",
                    capabilities=Capabilities(
                        input=("text",), context_window=10_000, max_tokens=1024
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=extension_runner,
    )
    runtime = FakeRuntime(session)
    stdout = StringIO()

    RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
    context = extension_runner.create_command_context(fallback_cwd="/tmp/project")
    for method_name in ("setStatus", "setTitle", "setEditorText", "setWidget"):
        assert not hasattr(context, method_name)
    assert _parse_jsonl(stdout) == []


def test_rpc_mode_extension_context_ui_namespace_is_snake_case_only(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.host.rpc import RpcHost as RpcMode

    extension_runner = ExtensionRunner(
        [LoadedExtension(name="rpc-ui", source_path=Path("/tmp/rpc_ui.py"))]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny",
                    provider="faux",
                    endpoint="test",
                    capabilities=Capabilities(
                        input=("text",), context_window=10_000, max_tokens=1024
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=extension_runner,
    )
    runtime = FakeRuntime(session)
    stdout = StringIO()

    RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
    context = extension_runner.create_command_context(fallback_cwd="/tmp/project")
    assert context.has_ui is True
    for method_name in ("setStatus", "setTitle", "setEditorText"):
        assert not hasattr(context.ui, method_name)
    context.ui.set_status("deploy", "running")
    context.ui.set_title("Deploying")
    context.ui.set_editor_text("next prompt")

    requests = _parse_jsonl(stdout)
    assert [request["method"] for request in requests] == [
        "setStatus",
        "setTitle",
        "set_editor_text",
    ]


def test_rpc_mode_extension_context_excludes_pi_style_headless_ui_methods(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.host.rpc import RpcHost as RpcMode

    extension_runner = ExtensionRunner(
        [LoadedExtension(name="rpc-ui", source_path=Path("/tmp/rpc_ui.py"))]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny",
                    provider="faux",
                    endpoint="test",
                    capabilities=Capabilities(
                        input=("text",), context_window=10_000, max_tokens=1024
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=extension_runner,
    )
    runtime = FakeRuntime(session)
    stdout = StringIO()

    RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
    ui = extension_runner.create_command_context(fallback_cwd="/tmp/project").ui
    for method_name in (
        "onTerminalInput",
        "setWorkingMessage",
        "setWorkingVisible",
        "setWorkingIndicator",
        "setHiddenThinkingLabel",
        "setFooter",
        "setHeader",
        "addAutocompleteProvider",
        "setEditorComponent",
        "getAllThemes",
        "getTheme",
        "setTheme",
        "getToolsExpanded",
        "setToolsExpanded",
    ):
        assert not hasattr(ui, method_name)
    assert _parse_jsonl(stdout) == []


def test_rpc_mode_extension_ui_dialog_timeout_returns_default_values() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
        assert (
            await mode.extension_ui_context.select("Target", ["dev"], timeout=0.01)
            is None
        )
        assert (
            await mode.extension_ui_context.confirm("Confirm", "Proceed?", timeout=0.01)
            is False
        )
        assert await mode.extension_ui_context.input("Input", timeout=0.01) is None
        assert await mode.extension_ui_context.editor("Edit", timeout=0.01) is None

    asyncio.run(scenario())

    requests = _parse_jsonl(stdout)
    assert [request["method"] for request in requests] == [
        "select",
        "confirm",
        "input",
        "editor",
    ]
    assert all(request["timeout"] == 0.01 for request in requests)


def test_rpc_mode_extension_ui_late_response_after_timeout_is_ignored() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
        assert (
            await mode.extension_ui_context.select("Target", ["dev"], timeout=0.01)
            is None
        )
        expired_request = _parse_jsonl(stdout)[0]
        assert await mode.submit_input(
            json.dumps(
                {
                    "type": "extension_ui_response",
                    "id": expired_request["id"],
                    "value": "dev",
                }
            )
        ) == 0
        task = asyncio.create_task(mode.extension_ui_context.select("Target", ["prod"]))
        await asyncio.sleep(0)
        active_request = _parse_jsonl(stdout)[1]
        assert await mode.submit_input(
            json.dumps(
                {
                    "type": "extension_ui_response",
                    "id": active_request["id"],
                    "value": "prod",
                }
            )
        ) == 0
        assert await asyncio.wait_for(task, timeout=0.5) == "prod"

    asyncio.run(scenario())


def test_rpc_mode_extension_ui_dialog_cancelled_responses_return_defaults() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
        select_task = asyncio.create_task(
            mode.extension_ui_context.select("Target", ["dev"])
        )
        confirm_task = asyncio.create_task(
            mode.extension_ui_context.confirm("Confirm", "Proceed?")
        )
        await asyncio.sleep(0)
        requests = _parse_jsonl(stdout)
        for request in requests:
            assert await mode.submit_input(
                json.dumps(
                    {
                        "type": "extension_ui_response",
                        "id": request["id"],
                        "cancelled": True,
                    }
                )
            ) == 0
        assert await asyncio.wait_for(select_task, timeout=0.5) is None
        assert await asyncio.wait_for(confirm_task, timeout=0.5) is False

    asyncio.run(scenario())


def test_rpc_mode_write_json_line_rejects_circular_payloads() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()
    mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)

    payload: dict[str, object] = {
        "type": "response",
        "command": "probe",
        "success": True,
    }
    payload["data"] = payload

    mode._write_json_line(payload)
    assert _parse_jsonl(stdout) == [
        {
            "type": "response",
            "command": "probe",
            "success": False,
            "error": "Failed to serialize RPC output.",
        }
    ]


def test_rpc_mode_write_json_line_preserves_command_on_fallback() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BadSlots:
        __slots__ = ()

        def __repr__(self) -> str:  # pragma: no cover
            raise RuntimeError("unprintable")

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()
    mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)

    mode._write_json_line(
        {"type": "response", "id": "id-1", "command": "probe", "data": BadSlots()}
    )
    assert _parse_jsonl(stdout) == [
        {
            "type": "response",
            "command": "probe",
            "success": False,
            "error": "Failed to serialize RPC output.",
            "id": "id-1",
        },
    ]


def test_rpc_mode_write_json_line_drops_invalid_fallback_fields() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class Unsupported:
        pass

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = StringIO()
    mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)

    mode._write_json_line(
        {
            "type": "response",
            "id": "\ud800",
            "command": "\ud800",
            "data": Unsupported(),
        }
    )

    rendered = stdout.getvalue()
    rendered.encode("utf-8")
    assert _parse_jsonl(stdout) == [
        {
            "type": "response",
            "command": "response",
            "success": False,
            "error": "Failed to serialize RPC output.",
        }
    ]


def test_rpc_mode_write_json_line_flushes_output() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class FlushingStringIO(StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.flush_calls = 0

        def flush(self) -> None:
            self.flush_calls += 1
            super().flush()

    runtime = FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project"))
    stdout = FlushingStringIO()
    mode = RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)

    mode._write_json_line({"type": "response", "command": "probe", "success": True})

    assert stdout.flush_calls == 1
    assert _parse_jsonl(stdout) == [
        {"type": "response", "command": "probe", "success": True}
    ]


def test_rpc_mode_rebinds_extension_ui_context_after_session_switch(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.host.rpc import RpcHost as RpcMode

    def _session(session_id: str, extension_runner: ExtensionRunner) -> AgentSession:
        return AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "",
                    "model": Model(
                        id="tiny",
                        provider="faux",
                        endpoint="test",
                        capabilities=Capabilities(
                            input=("text",), context_window=10_000, max_tokens=1024
                        ),
                    ),
                    "thinking_level": "off",
                }
            ),
            session_manager=asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path / session_id, cwd="/tmp/project", persist=False
                )
            ),
            extension_runner=extension_runner,
        )

    first_runner = ExtensionRunner(
        [LoadedExtension(name="first", source_path=Path("/tmp/first.py"))]
    )
    second_runner = ExtensionRunner(
        [LoadedExtension(name="second", source_path=Path("/tmp/second.py"))]
    )
    current = _session("a", first_runner)
    next_session = _session("b", second_runner)
    runtime = FakeRuntime(current)
    runtime.queue_next_session(next_session)
    stdout = StringIO()
    stdin = StringIO(
        json.dumps({"id": "switch", "type": "switch_session", "sessionId": "session-b"})
        + "\n"
    )

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    second_runner.create_command_context(fallback_cwd="/tmp/project").notify(
        "Rebound", "info"
    )
    requests = [
        line for line in _parse_jsonl(stdout) if line["type"] == "extension_ui_request"
    ]
    assert len(requests) == 1
    assert requests[0]["message"] == "Rebound"


def test_rpc_mode_emits_extension_error_for_hook_failures(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.host.rpc import RpcHost as RpcMode

    def _broken_hook(session, ctx):
        del session, ctx
        raise RuntimeError("hook exploded")

    extension_runner = ExtensionRunner(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/broken.py"),
                hooks={"session_start": [_broken_hook]},
            )
        ]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny",
                    provider="faux",
                    endpoint="test",
                    capabilities=Capabilities(
                        input=("text",), context_window=10_000, max_tokens=1024
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=extension_runner,
    )
    runtime = FakeRuntime(session)
    stdout = StringIO()

    RpcMode(runtime=runtime, stdin=StringIO(""), stdout=stdout)
    asyncio.run(extension_runner.emit_session_start(session))

    lines = _parse_jsonl(stdout)
    assert lines == [
        {
            "type": "extension_error",
            "extensionPath": "/tmp/broken.py",
            "event": "session_start",
            "error": "hook exploded",
        }
    ]


def test_rpc_mode_is_exported_from_shared_host_package() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode
    from loushang.harness.host.rpc import run_rpc_host

    assert RpcMode is not None
    assert run_rpc_host is not None
