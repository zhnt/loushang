from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from loushang.ai.model import ModelSelection
from loushang.ai.model.domain import (
    Capabilities,
    Endpoint,
    Model,
)
from loushang.harness.commands import CommandSourceInfo, SessionCommandDescriptor
from loushang.harness.diagnostics import (
    DiagnosticRecord,
    DiagnosticsQuery,
    ErrorReport,
)
from tests.coding.rpc_support import (
    FakeModelRegistry,
    FakeRuntime,
    FakeSession,
    _parse_jsonl,
)


def test_rpc_mode_get_diagnostics_and_last_error_report() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    warning = DiagnosticRecord(
        type="warning",
        code="model_auth_unresolved",
        message="Provider demo has no configured API key.",
        phase="startup",
        source="model",
        timestamp="2026-05-01T00:00:00Z",
        session_id="session-a",
        source_path=Path("/tmp/project/.loushang/settings.json"),
        details={"provider": "demo"},
        fingerprint="fp-warning",
        occurrence_count=2,
    )
    error = DiagnosticRecord(
        type="error",
        code="assistant_response_error",
        message="provider failed",
        phase="runtime",
        source="provider",
        timestamp="2026-05-01T00:01:00Z",
        session_id="session-a",
        entry_id="entry-1",
        details={"retry": True},
        fingerprint="fp-error",
    )
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.diagnostics = [warning, error]
    session.error_report = ErrorReport(primary=error, related=(warning,))
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {"id": "diagnostics", "type": "get_diagnostics", "limit": 1}
                ),
                json.dumps({"id": "report", "type": "get_last_error_report"}),
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

    lines = _parse_jsonl(stdout)
    assert lines[0] == {
        "id": "diagnostics",
        "type": "response",
        "command": "get_diagnostics",
        "success": True,
        "data": {
            "diagnostics": [
                {
                    "type": "error",
                    "code": "assistant_response_error",
                    "message": "provider failed",
                    "phase": "runtime",
                    "source": "provider",
                    "timestamp": "2026-05-01T00:01:00Z",
                    "details": {"retry": True},
                    "occurrenceCount": 1,
                    "sessionId": "session-a",
                    "entryId": "entry-1",
                    "fingerprint": "fp-error",
                }
            ]
        },
    }
    assert lines[1]["id"] == "report"
    assert lines[1]["success"] is True
    report = lines[1]["data"]["report"]
    assert report["primary"]["code"] == "assistant_response_error"
    assert report["related"][0]["code"] == "model_auth_unresolved"
    assert report["related"][0]["occurrenceCount"] == 2


def test_rpc_mode_get_packages_projects_remote_lifecycle_state() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.packages = [
        {
            "name": "review-pack",
            "kind": "remote_plugin",
            "scope": "project",
            "version": "",
            "source": "https://packages.example.invalid/review-pack.git",
            "path": "",
            "enabled": False,
            "prompts": 0,
            "skills": 0,
            "extensions": 0,
            "themes": 0,
            "diagnostics": 0,
            "lifecycle": "remote_registered",
            "security": "allowed",
            "description": "",
        }
    ]
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "packages", "type": "get_packages"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.get_packages_calls == [None]
    assert response == {
        "id": "packages",
        "type": "response",
        "command": "get_packages",
        "success": True,
        "data": {"packages": session.packages},
    }


def test_rpc_mode_materialize_package_uses_runtime_facade() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps(
            {"id": "materialize", "type": "materialize_package", "source": source}
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.materialize_package_calls == [source]
    assert response == {
        "id": "materialize",
        "type": "response",
        "command": "materialize_package",
        "success": True,
        "data": {
            "record": {
                "source": source,
                "name": "review-pack",
                "lifecycle": "materialization_pending",
                "targetPath": "/tmp/packages/review-pack",
                "errorMessage": None,
            }
        },
    }


def test_rpc_mode_update_package_uses_runtime_facade() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "update", "type": "update_package", "source": source}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.update_package_calls == [source]
    assert response == {
        "id": "update",
        "type": "response",
        "command": "update_package",
        "success": True,
        "data": {
            "record": {
                "source": source,
                "name": "review-pack",
                "lifecycle": "installed",
                "targetPath": "/tmp/packages/review-pack",
                "errorMessage": None,
            }
        },
    }


def test_rpc_mode_remove_package_uses_runtime_facade() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "remove", "type": "remove_package", "source": source}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.remove_package_calls == [source]
    assert response == {
        "id": "remove",
        "type": "response",
        "command": "remove_package",
        "success": True,
        "data": {
            "record": {
                "source": source,
                "name": "review-pack",
                "lifecycle": "remote_registered",
                "targetPath": "/tmp/packages/review-pack",
                "errorMessage": None,
            }
        },
    }


def test_rpc_mode_package_lifecycle_failed_record_returns_error() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)

    async def failed_materialize(source_arg: str) -> dict[str, object]:
        runtime.materialize_package_calls.append(source_arg)
        return {
            "source": source_arg,
            "name": "review-pack",
            "lifecycle": "failed",
            "targetPath": "/tmp/packages/review-pack",
            "errorMessage": "clone failed",
        }

    runtime.materialize_package = failed_materialize  # type: ignore[method-assign]
    stdin = StringIO(
        json.dumps(
            {"id": "materialize", "type": "materialize_package", "source": source}
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.materialize_package_calls == [source]
    assert response == {
        "id": "materialize",
        "type": "response",
        "command": "materialize_package",
        "success": False,
        "error": "Failed to materialize package: clone failed",
        "errorCode": "package_materialization_failed",
        "errorInfo": {
            "command": "materialize_package",
            "code": "package_materialization_failed",
            "message": "Failed to materialize package: clone failed",
        },
    }


def test_rpc_mode_high_level_package_manager_commands_use_runtime_facade() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {"id": "install", "type": "install_package", "source": source}
                ),
                json.dumps({"id": "check", "type": "check_package_updates"}),
                json.dumps({"id": "update-all", "type": "update_packages"}),
                json.dumps(
                    {"id": "uninstall", "type": "uninstall_package", "source": source}
                ),
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

    responses = _parse_jsonl(stdout)
    assert runtime.install_package_calls == [source]
    assert runtime.check_package_updates_calls == 1
    assert runtime.update_packages_calls == 1
    assert runtime.uninstall_package_calls == [source]
    assert [response["command"] for response in responses] == [
        "install_package",
        "check_package_updates",
        "update_packages",
        "uninstall_package",
    ]
    assert responses[1]["data"]["updates"][0]["availableCommit"] == "b"
    assert responses[2]["data"]["records"][0]["lifecycle"] == "installed"


def test_rpc_mode_get_diagnostics_supports_query_filters() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    provider_error = DiagnosticRecord(
        type="error",
        code="assistant_response_error",
        message="provider failed",
        phase="runtime",
        source="provider",
        timestamp="2026-05-01T00:01:00Z",
        session_id="session-a",
        entry_id="entry-a",
        details={},
    )
    session_warning = DiagnosticRecord(
        type="warning",
        code="startup_warning",
        message="heads up",
        phase="startup",
        source="bootstrap",
        timestamp="2026-05-01T00:00:00Z",
        session_id="session-b",
        entry_id="entry-b",
        details={},
    )
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    runtime.diagnostics = [session_warning, provider_error]
    stdin = StringIO(
        json.dumps(
            {
                "id": "diagnostics",
                "type": "get_diagnostics",
                "limit": 5,
                "phase": "runtime",
                "source": "provider",
                "level": "error",
                "sessionId": "session-a",
                "entryId": "entry-a",
                "code": "assistant_response_error",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.get_diagnostics_calls == [
        DiagnosticsQuery(
            phase="runtime",
            source="provider",
            level="error",
            session_id="session-a",
            entry_id="entry-a",
            code="assistant_response_error",
            limit=5,
        )
    ]
    response = _parse_jsonl(stdout)[0]
    assert [record["code"] for record in response["data"]["diagnostics"]] == [
        "assistant_response_error"
    ]


def test_rpc_mode_get_session_diagnostics_uses_session_scoped_runtime_query() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    current_session_error = DiagnosticRecord(
        type="error",
        code="current_session_error",
        message="current failed",
        phase="runtime",
        source="session",
        timestamp="2026-05-01T00:01:00Z",
        session_id="session-a",
        entry_id="entry-a",
        details={},
    )
    other_session_error = DiagnosticRecord(
        type="error",
        code="other_session_error",
        message="other failed",
        phase="runtime",
        source="session",
        timestamp="2026-05-01T00:02:00Z",
        session_id="session-b",
        entry_id="entry-b",
        details={},
    )
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    runtime.diagnostics = [other_session_error, current_session_error]
    stdin = StringIO(
        json.dumps(
            {
                "id": "session-diagnostics",
                "type": "get_session_diagnostics",
                "limit": 5,
                "phase": "runtime",
                "source": "session",
                "level": "error",
                "code": "current_session_error",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.get_session_diagnostics_calls == [
        DiagnosticsQuery(
            phase="runtime",
            source="session",
            level="error",
            code="current_session_error",
            limit=5,
        )
    ]
    assert runtime.get_diagnostics_calls == []
    response = _parse_jsonl(stdout)[0]
    assert response["command"] == "get_session_diagnostics"
    assert [record["code"] for record in response["data"]["diagnostics"]] == [
        "current_session_error"
    ]


def test_rpc_mode_get_diagnostics_summary_projects_counts() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    provider_error = DiagnosticRecord(
        type="error",
        code="assistant_response_error",
        message="provider failed",
        phase="runtime",
        source="provider",
        timestamp="2026-05-01T00:01:00Z",
        session_id="session-a",
        entry_id="entry-a",
        details={},
        occurrence_count=3,
    )
    startup_warning = DiagnosticRecord(
        type="warning",
        code="startup_warning",
        message="heads up",
        phase="startup",
        source="bootstrap",
        timestamp="2026-05-01T00:00:00Z",
        session_id="session-a",
        details={},
    )
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    runtime.diagnostics = [startup_warning, provider_error]
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "summary",
                        "type": "get_diagnostics_summary",
                        "sessionId": "session-a",
                    }
                ),
                json.dumps(
                    {"id": "session-summary", "type": "get_session_diagnostics_summary"}
                ),
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

    lines = _parse_jsonl(stdout)
    assert runtime.get_diagnostics_summary_calls == [
        DiagnosticsQuery(session_id="session-a")
    ]
    assert runtime.get_session_diagnostics_summary_calls == [DiagnosticsQuery()]
    assert lines[0]["command"] == "get_diagnostics_summary"
    summary = lines[0]["data"]["summary"]
    assert summary["totalCount"] == 4
    assert summary["errorCount"] == 3
    assert summary["warningCount"] == 1
    assert summary["byCode"] == {"startup_warning": 1, "assistant_response_error": 3}
    assert summary["latestError"]["code"] == "assistant_response_error"
    assert lines[1]["command"] == "get_session_diagnostics_summary"
    assert lines[1]["data"]["summary"]["totalCount"] == 4


def test_rpc_mode_get_diagnostics_rejects_invalid_limit() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "diagnostics", "type": "get_diagnostics", "limit": 0}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "diagnostics",
            "type": "response",
            "command": "get_diagnostics",
            "success": False,
            "error": "Diagnostic limit must be a positive integer.",
        }
    ]


def test_rpc_mode_get_commands_prefers_session_command_descriptors() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class DescriptorSession(FakeSession):
        def list_commands(self):
            return [
                SessionCommandDescriptor(
                    name="deploy",
                    description="Deploy the project",
                    source="extension",
                    source_info=CommandSourceInfo(
                        path="/tmp/project/extensions/deploy.py",
                        base_dir="/tmp/project/extensions",
                    ),
                )
            ]

    session = DescriptorSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "commands", "type": "get_commands"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "commands",
            "type": "response",
            "command": "get_commands",
            "success": True,
            "data": {
                "commands": [
                    {
                        "name": "deploy",
                        "description": "Deploy the project",
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
        }
    ]


def test_rpc_mode_discovers_coding_lsp_session_command() -> None:
    from loushang.coding.lsp.commands import lsp_session_command_descriptor
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class LspCommandSession(FakeSession):
        def list_commands(self):
            return [lsp_session_command_descriptor()]

    session = LspCommandSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "commands", "type": "get_commands"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert await mode.run() == 0

    asyncio.run(scenario())

    command = _parse_jsonl(stdout)[0]["data"]["commands"][0]
    assert command["name"] == "lsp"
    assert command["source"] == "builtin"
    assert command["argumentHint"] == "[status | stop <server-id> <root>]"


def test_rpc_mode_executes_coding_lsp_session_command() -> None:
    from loushang.coding.lsp.commands import (
        execute_lsp_session_command,
        lsp_session_command_descriptor,
    )
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class LspCommandSession(FakeSession):
        def list_commands(self):
            return [lsp_session_command_descriptor()]

        async def execute_command_async(self, invocation_name: str, args: str):
            assert invocation_name == "lsp"
            return await execute_lsp_session_command(None, args)

    session = LspCommandSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps(
            {
                "id": "lsp-status",
                "type": "execute_command",
                "command": "lsp",
                "args": "status",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert await mode.run() == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "lsp-status",
            "type": "response",
            "command": "execute_command",
            "success": True,
            "data": {
                "invocationName": "lsp",
                "args": "status",
                "result": {
                    "source": "builtin",
                    "command": "lsp",
                    "status": "ok",
                    "scope": "session",
                    "enabled": False,
                    "disposed": False,
                    "servers": [],
                    "starting_count": 0,
                    "ready_count": 0,
                    "failed_count": 0,
                    "display": "LSP session capability: disabled",
                },
            },
        }
    ]


def test_rpc_mode_get_commands_projects_session_command_descriptors() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.command_entries = [
        SessionCommandDescriptor(
            name="deploy",
            description="Deploy the project",
            source="extension",
            source_info=CommandSourceInfo(
                path="/tmp/project/extensions/deploy-ext.py",
                base_dir="/tmp/project/extensions",
            ),
        ),
        SessionCommandDescriptor(
            name="plan",
            description="Plan the work.",
            source="prompt",
            source_info=CommandSourceInfo(
                path="/tmp/project/prompts/plan.md", base_dir="/tmp/project/prompts"
            ),
            argument_hint="[topic]",
        ),
        SessionCommandDescriptor(
            name="legacy",
            description=None,
            source="skill",
            source_info=CommandSourceInfo(
                path="/tmp/project/skills/legacy.md", base_dir="/tmp/project/skills"
            ),
        ),
        SessionCommandDescriptor(
            name="metadata",
            description="Uses descriptor metadata.",
            source="extension",
            source_info=CommandSourceInfo(
                path="/tmp/project/extensions/alias-cased.md",
                source="project-metadata",
                scope="user",
                origin="package",
                base_dir="/tmp/explicit-base",
            ),
        ),
    ]
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "commands", "type": "get_commands"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    commands = _parse_jsonl(stdout)[0]["data"]["commands"]
    assert commands == [
        {
            "name": "deploy",
            "description": "Deploy the project",
            "source": "extension",
            "sourceInfo": {
                "path": "/tmp/project/extensions/deploy-ext.py",
                "source": "filesystem",
                "scope": "project",
                "origin": "top-level",
                "baseDir": "/tmp/project/extensions",
            },
        },
        {
            "name": "plan",
            "description": "Plan the work.",
            "source": "prompt",
            "argumentHint": "[topic]",
            "sourceInfo": {
                "path": "/tmp/project/prompts/plan.md",
                "source": "filesystem",
                "scope": "project",
                "origin": "top-level",
                "baseDir": "/tmp/project/prompts",
            },
        },
        {
            "name": "legacy",
            "description": None,
            "source": "skill",
            "sourceInfo": {
                "path": "/tmp/project/skills/legacy.md",
                "source": "filesystem",
                "scope": "project",
                "origin": "top-level",
                "baseDir": "/tmp/project/skills",
            },
        },
        {
            "name": "metadata",
            "description": "Uses descriptor metadata.",
            "source": "extension",
            "sourceInfo": {
                "path": "/tmp/project/extensions/alias-cased.md",
                "source": "project-metadata",
                "scope": "user",
                "origin": "package",
                "baseDir": "/tmp/explicit-base",
            },
        },
    ]


def test_rpc_mode_get_command_completions_returns_command_and_argument_suggestions() -> (
    None
):
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class CompletionSession(FakeSession):
        async def get_command_argument_completions(
            self, invocation_name: str, prefix: str
        ) -> list[object]:
            assert (invocation_name, prefix) == ("deploy", "pr")
            return [{"value": "prod", "label": "Production"}]

    session = CompletionSession(session_id="session-a", cwd="/tmp/project")
    session.command_entries = [
        {
            "name": "deploy",
            "description": "Deploy the project",
            "source": "extension",
            "source_info": {"path": "/tmp/project/extensions/deploy-ext.py"},
        },
        {
            "name": "debug",
            "description": "Debug",
            "source": "skill",
            "source_info": {"path": "/tmp/project/skills/debug/SKILL.md"},
        },
    ]
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {"id": "names", "type": "get_command_completions", "prefix": "/dep"}
                ),
                json.dumps(
                    {
                        "id": "args",
                        "type": "get_command_completions",
                        "command": "deploy",
                        "prefix": "pr",
                    }
                ),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert await mode.run() == 0

    asyncio.run(scenario())

    names, args = _parse_jsonl(stdout)
    assert names["data"]["completions"] == [
        {
            "value": "/deploy",
            "label": "/deploy",
            "description": "Deploy the project",
            "source": "extension",
            "kind": "command",
        }
    ]
    assert args["data"]["completions"] == [{"value": "prod", "label": "Production"}]


def test_rpc_mode_query_command_errors_stay_in_response_envelopes() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenQuerySession(FakeSession):
        def get_available_models(self) -> list[ModelSelection]:
            raise RuntimeError("model registry failed")

        def list_commands(self) -> list[object]:
            raise RuntimeError("command registry failed")

    session = BrokenQuerySession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "models", "type": "get_available_models"}),
                json.dumps({"id": "commands", "type": "get_commands"}),
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

    assert _parse_jsonl(stdout) == [
        {
            "id": "models",
            "type": "response",
            "command": "get_available_models",
            "success": False,
            "error": "Failed to query model registry: model registry failed",
        },
        {
            "id": "commands",
            "type": "response",
            "command": "get_commands",
            "success": False,
            "error": "Failed to query commands: command registry failed",
        },
    ]


def test_rpc_mode_get_available_models_returns_error_on_invalid_payload() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class InvalidModelSession(FakeSession):
        def get_available_models(self) -> object:
            return {"providers": []}

    session = InvalidModelSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "models", "type": "get_available_models"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "models",
            "type": "response",
            "command": "get_available_models",
            "success": False,
            "error": "Model registry returned an invalid response.",
        },
    ]


def test_rpc_mode_get_available_models_skips_invalid_model_entries() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenModelSession(FakeSession):
            def get_available_models(self):
                return [
                    SimpleNamespace(
                        provider="faux", endpoint_id="coding", model_id="alpha"
                    ),
                    object(),
                ]

    session = BrokenModelSession(session_id="session-a", cwd="/tmp/project")
    session.model_registry = FakeModelRegistry(
        resolved_models={
            ("faux", "coding", "alpha"): Model(
                id="alpha",
                provider="faux",
                endpoint="coding",
                name="Alpha",
                capabilities=Capabilities(
                    input=("text",),
                    context_window=128_000,
                    max_tokens=8_192,
                    reasoning=True,
                ),
            )
        },
        endpoints={
            ("faux", "coding"): Endpoint(
                id="coding",
                api="openai-completions",
                provider="faux",
                base_url="https://api.faux.test/v1",
            )
        },
    )
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        mode = RpcMode(
            runtime=runtime,
            stdin=StringIO(
                json.dumps({"id": "models", "type": "get_available_models"}) + "\n"
            ),
            stdout=stdout,
            stderr=stderr,
        )
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    lines = _parse_jsonl(stdout)
    assert lines == [
        {
            "id": "models",
            "type": "response",
            "command": "get_available_models",
            "success": True,
            "data": {
                "models": [
                        {
                            "provider": "faux",
                            "endpointId": "coding",
                            "id": "alpha",
                        "name": "Alpha",
                        "api": "openai-completions",
                        "baseUrl": "https://api.faux.test/v1",
                        "input": ["text"],
                        "contextWindow": 128000,
                        "maxTokens": 8192,
                        "reasoning": True,
                    },
                ],
            },
        }
    ]


def test_rpc_mode_get_commands_returns_error_on_invalid_payload() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class InvalidCommandSession(FakeSession):
        def list_commands(self) -> object:
            return {"commands": ["/bad"]}

    session = InvalidCommandSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "commands", "type": "get_commands"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "commands",
            "type": "response",
            "command": "get_commands",
            "success": False,
            "error": "Command registry returned an invalid response.",
        },
    ]


def test_rpc_mode_get_commands_skips_entries_without_valid_names() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.command_entries = [
        {
            "name": "deploy",
            "description": "Good command",
            "source": "extension",
            "source_info": {"path": "/tmp/project/extensions/deploy.py"},
        },
        {"name": "", "description": "Missing name"},
        {"description": "No name"},
        {"name": 123, "description": "Invalid name"},
        {
            "name": "plan",
            "description": "Another good command",
            "source": "prompt",
            "source_info": {"path": "/tmp/project/prompts/plan.md"},
        },
    ]
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "commands", "type": "get_commands"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    commands = _parse_jsonl(stdout)[0]["data"]["commands"]
    assert commands == [
        {
            "name": "deploy",
            "description": "Good command",
            "source": "extension",
            "sourceInfo": {
                "path": "/tmp/project/extensions/deploy.py",
                "source": "filesystem",
                "scope": "project",
                "origin": "top-level",
                "baseDir": "/tmp/project/extensions",
            },
        },
        {
            "name": "plan",
            "description": "Another good command",
            "source": "prompt",
            "sourceInfo": {
                "path": "/tmp/project/prompts/plan.md",
                "source": "filesystem",
                "scope": "project",
                "origin": "top-level",
                "baseDir": "/tmp/project/prompts",
            },
        },
    ]
