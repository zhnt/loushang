from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.coding.session_manager import SessionManager
from loushang.harness.diagnostics import DiagnosticsService
from loushang.harness.extensions.agent import (
    ExtensionRunner,
    LoadedExtension,
    RegisteredCommand,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)
from loushang.harness.session import (
    StandardSessionCommandController as CommandController,
)
from loushang.harness.session import StandardSessionCommandPorts
from loushang.tui.clipboard import ClipboardCopyResult


def test_command_controller_lists_extension_prompt_and_enabled_skill_commands(
    tmp_path,
) -> None:
    async def _handler(args: str, ctx) -> None:
        del args, ctx

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="deploy-ext",
                source_path=Path("/tmp/project/extensions/deploy.py"),
                commands={
                    "deploy": RegisteredCommand(
                        name="deploy",
                        handler=_handler,
                        description="Deploy the project",
                    )
                },
            )
        ]
    )
    bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="plan",
                source_path=Path("/tmp/project/prompts/plan.md"),
                text="---\ndescription: Plan\n---\nPlan the change.",
                source_root=Path("/tmp/project/prompts"),
            )
        ],
        skills=[
            SkillDescriptor(
                name="debugging",
                source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                description="Debug failures.",
                source_root=Path("/tmp/project/skills"),
            ),
            SkillDescriptor(
                name="hidden",
                source_path=Path("/tmp/project/skills/hidden/SKILL.md"),
                enabled=False,
            ),
        ],
    )
    controller = CommandController(
        session_manager=manager,
        get_extension_runner=lambda: runner,
        get_resource_bundle=lambda: bundle,
        get_diagnostics_service=lambda: None,
    )

    commands = controller.list_commands()

    assert [command.name for command in commands] == [
        "deploy",
        "plan",
        "skill:debugging",
    ]
    assert [command.description for command in commands] == [
        "Deploy the project",
        "Plan the change.",
        "Debug failures.",
    ]
    assert [command.source for command in commands] == ["extension", "prompt", "skill"]
    assert [command.source_info.path for command in commands] == [
        "/tmp/project/extensions/deploy.py",
        "/tmp/project/prompts/plan.md",
        "/tmp/project/skills/debugging/SKILL.md",
    ]


def test_command_controller_lists_builtin_commands_before_extension_and_resource_commands(
    tmp_path,
) -> None:
    async def _handler(args: str, ctx) -> None:
        del args, ctx

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="deploy-ext",
                source_path=Path("/tmp/project/extensions/deploy.py"),
                commands={"deploy": RegisteredCommand(name="deploy", handler=_handler)},
            )
        ]
    )
    bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="plan",
                source_path=Path("/tmp/project/prompts/plan.md"),
                text="Plan",
            )
        ],
    )
    controller = CommandController(
        session_manager=manager,
        get_extension_runner=lambda: runner,
        get_resource_bundle=lambda: bundle,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(),
    )

    commands = controller.list_commands()

    assert [command.name for command in commands[:4]] == [
        "export",
        "import",
        "copy",
        "rename",
    ]
    assert {command.name for command in commands} >= {
        "copy",
        "rename",
        "session",
        "changelog",
        "tools",
        "deploy",
        "plan",
    }
    assert all(command.source == "builtin" for command in commands[:15])
    assert commands[0].source_info.source == "builtin"


def test_command_controller_exposes_prompt_argument_hint_from_frontmatter(
    tmp_path,
) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="review",
                source_path=Path("/tmp/project/prompts/review.md"),
                text="---\n"
                "description: Review pull requests\n"
                'argument-hint: "<PR-URL>"\n'
                "---\n\n"
                "Review $1.",
                description="Review pull requests",
                argument_hint="<PR-URL>",
                source_root=Path("/tmp/project/prompts"),
            )
        ],
    )
    controller = CommandController(
        session_manager=manager,
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: bundle,
        get_diagnostics_service=lambda: None,
    )

    commands = controller.list_commands()

    assert [
        (command.name, command.description, command.argument_hint)
        for command in commands
    ] == [("review", "Review pull requests", "<PR-URL>")]


def test_command_controller_executes_extension_command_before_resource_command(
    tmp_path,
) -> None:
    calls: list[tuple[str, str]] = []

    async def _handler(args: str, ctx) -> None:
        calls.append((args, ctx.cwd))

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="deploy-ext",
                source_path=Path("/tmp/project/extensions/deploy.py"),
                commands={"deploy": RegisteredCommand(name="deploy", handler=_handler)},
            )
        ]
    )
    bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="deploy",
                source_path=Path("/tmp/project/prompts/deploy.md"),
                text="Prompt deploy",
            )
        ],
    )
    controller = CommandController(
        session_manager=manager,
        get_extension_runner=lambda: runner,
        get_resource_bundle=lambda: bundle,
        get_diagnostics_service=lambda: None,
    )

    result = asyncio.run(controller.execute_command_async("/deploy", "now"))

    assert result is not None
    assert result.invocation_name == "deploy"
    assert result.result is None
    assert calls == [("now", "/tmp/project")]


def test_command_controller_dispatches_extension_before_builtin_and_resource(
    tmp_path,
) -> None:
    calls: list[tuple[str, str]] = []
    builtin_names: list[str | None] = []

    async def _handler(args: str, ctx) -> None:
        calls.append((args, ctx.cwd))

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="rename-ext",
                source_path=Path("/tmp/project/extensions/rename.py"),
                commands={
                    "rename": RegisteredCommand(name="rename", handler=_handler)
                },
            )
        ]
    )
    bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="rename",
                source_path=Path("/tmp/project/prompts/rename.md"),
                text="Resource rename $ARGUMENTS",
            )
        ],
    )
    controller = CommandController(
        session_manager=manager,
        get_extension_runner=lambda: runner,
        get_resource_bundle=lambda: bundle,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(set_session_name=builtin_names.append),
    )

    result = asyncio.run(
        controller.execute_command_async("/rename", "Project Alpha")
    )

    assert result is not None
    assert result.invocation_name == "rename"
    assert result.result is None
    assert calls == [("Project Alpha", "/tmp/project")]
    assert builtin_names == []


def test_command_controller_executes_builtin_rename_session_and_unsupported_commands(
    tmp_path,
) -> None:
    names: list[str | None] = []
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
                session_id="session-1",
            )
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            set_session_name=names.append,
            get_session_info=lambda: {"session_id": "session-1", "cwd": "/tmp/project"},
        ),
    )

    rename_result = asyncio.run(
        controller.execute_command_async("/rename", "Project Alpha")
    )
    session_result = asyncio.run(controller.execute_command_async("/session", ""))

    assert rename_result is not None
    assert rename_result.result == {
        "source": "builtin",
        "command": "rename",
        "status": "ok",
        "name": "Project Alpha",
        "message": "Session renamed to Project Alpha",
    }
    assert names == ["Project Alpha"]
    assert session_result is not None
    assert session_result.result == {
        "source": "builtin",
        "command": "session",
        "status": "ok",
        "session": {"session_id": "session-1", "cwd": "/tmp/project"},
        "message": "Session: session-1 | CWD: /tmp/project",
    }
    assert controller.extract_builtin_command_invocation("/model") is None


def test_command_controller_executes_builtin_tools_list_and_mutations(tmp_path) -> None:
    active_tools = ["read", "grep"]
    all_tools = [
        {"name": "read", "description": "Read files"},
        {"name": "grep", "description": "Search files"},
        {"name": "bash", "description": "Run shell commands"},
    ]
    set_calls: list[list[str]] = []

    async def _set_active_tools(tool_names: list[str]) -> None:
        set_calls.append(list(tool_names))
        active_tools[:] = list(tool_names)

    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
                session_id="session-1",
            )
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            get_active_tool_names=lambda: list(active_tools),
            get_all_tools=lambda: list(all_tools),
            set_active_tools=_set_active_tools,
            get_default_active_tool_names=lambda: ["read", "grep", "bash"],
        ),
    )

    list_result = asyncio.run(controller.execute_command_async("/tools", ""))
    off_result = asyncio.run(controller.execute_command_async("/tools", "off grep"))
    on_result = asyncio.run(controller.execute_command_async("/tools", "on bash"))
    only_result = asyncio.run(controller.execute_command_async("/tools", "only read"))
    reset_result = asyncio.run(controller.execute_command_async("/tools", "reset"))

    assert list_result is not None
    assert list_result.result == {
        "source": "builtin",
        "command": "tools",
        "status": "ok",
        "active_tools": ["read", "grep"],
        "available_tools": [
            {"name": "read", "active": True, "description": "Read files"},
            {"name": "grep", "active": True, "description": "Search files"},
            {"name": "bash", "active": False, "description": "Run shell commands"},
        ],
        "message": "Active tools: read, grep",
    }
    assert off_result is not None
    assert off_result.result["active_tools"] == ["read"]
    assert on_result is not None
    assert on_result.result["active_tools"] == ["read", "bash"]
    assert only_result is not None
    assert only_result.result["active_tools"] == ["read"]
    assert reset_result is not None
    assert reset_result.result["active_tools"] == ["read", "grep", "bash"]
    assert set_calls == [["read"], ["read", "bash"], ["read"], ["read", "grep", "bash"]]


def test_command_controller_builtin_tools_preserves_tool_source_info(tmp_path) -> None:
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
                session_id="session-1",
            )
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            get_active_tool_names=lambda: ["review_lookup"],
            get_all_tools=lambda: [
                {
                    "name": "review_lookup",
                    "description": "Look up review metadata",
                    "sourceInfo": {
                        "path": "/tmp/project/extensions/review/extension.py",
                        "source": "filesystem",
                        "scope": "project",
                        "origin": "package",
                        "baseDir": "/tmp/project/extensions/review",
                    },
                }
            ],
        ),
    )

    result = asyncio.run(controller.execute_command_async("/tools", ""))

    assert result is not None
    assert result.result["available_tools"] == [
        {
            "name": "review_lookup",
            "active": True,
            "description": "Look up review metadata",
            "sourceInfo": {
                "path": "/tmp/project/extensions/review/extension.py",
                "source": "filesystem",
                "scope": "project",
                "origin": "package",
                "baseDir": "/tmp/project/extensions/review",
            },
        }
    ]


def test_command_controller_executes_builtin_extensions_list_and_detail(
    tmp_path,
) -> None:
    extensions = [
        {
            "id": "acme.review",
            "name": "Acme Review",
            "version": "0.1.0",
            "description": "Review helpers",
            "sourcePath": "/tmp/project/extensions/review/extension.py",
            "permissionLevel": "standard",
            "capabilities": ["filesystem"],
            "surfaces": [
                {
                    "type": "command",
                    "name": "acme-review",
                    "active": True,
                    "source": "manifest",
                },
                {
                    "type": "tool",
                    "name": "review_lookup",
                    "active": True,
                    "source": "runtime",
                },
            ],
            "diagnostics": [
                {
                    "code": "missing_extension_hook_event",
                    "message": "Extension manifest hook declaration requires an event.",
                    "sourcePath": "/tmp/project/extensions/review/loushang-extension.toml",
                }
            ],
        }
    ]
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
                session_id="session-1",
            )
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(get_extensions=lambda: extensions),
    )

    list_result = asyncio.run(controller.execute_command_async("/extensions", ""))
    detail_result = asyncio.run(
        controller.execute_command_async("/extensions", "acme.review")
    )

    assert list_result is not None
    assert list_result.result == {
        "source": "builtin",
        "command": "extensions",
        "status": "ok",
        "extensions": extensions,
        "message": "Extensions: acme.review (standard, 2 surfaces, 1 diagnostic)",
        "display": (
            "Extensions:\n"
            "- acme.review - Acme Review [standard]\n"
            "  Source: /tmp/project/extensions/review/extension.py\n"
            "  Surfaces: command acme-review, tool review_lookup\n"
            "  Diagnostics: 1"
        ),
    }
    assert detail_result is not None
    assert detail_result.result == {
        "source": "builtin",
        "command": "extensions",
        "status": "ok",
        "extension": extensions[0],
        "message": "Extension acme.review: Acme Review",
        "display": (
            "Extension acme.review\n"
            "Name: Acme Review\n"
            "Version: 0.1.0\n"
            "Description: Review helpers\n"
            "Permission: standard\n"
            "Capabilities: filesystem\n"
            "Source: /tmp/project/extensions/review/extension.py\n"
            "Surfaces:\n"
            "- command acme-review (manifest)\n"
            "- tool review_lookup (runtime)\n"
            "Diagnostics:\n"
            "- missing_extension_hook_event: Extension manifest hook declaration requires an event."
        ),
    }


def test_command_controller_builtin_extensions_reports_unknown_extension(
    tmp_path,
) -> None:
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
                session_id="session-1",
            )
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            get_extensions=lambda: [{"id": "acme.review", "name": "Acme Review"}]
        ),
    )

    result = asyncio.run(controller.execute_command_async("/extensions", "missing.ext"))

    assert result is not None
    assert result.result == {
        "source": "builtin",
        "command": "extensions",
        "status": "error",
        "message": "Unknown extension: missing.ext. Loaded extensions: acme.review",
    }


def test_command_controller_builtin_tools_rejects_unknown_tool(tmp_path) -> None:
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
                session_id="session-1",
            )
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            get_active_tool_names=lambda: ["read"],
            get_all_tools=lambda: [{"name": "read", "description": "Read files"}],
            set_active_tools=lambda tool_names: None,
            get_default_active_tool_names=lambda: ["read"],
        ),
    )

    result = asyncio.run(controller.execute_command_async("/tools", "on bash"))

    assert result is not None
    assert result.result == {
        "source": "builtin",
        "command": "tools",
        "status": "error",
        "message": "Unknown tool: bash. Available tools: read",
    }


def test_command_controller_executes_builtin_copy_by_recent_index(tmp_path) -> None:
    copied: list[str] = []

    def _copy_text(text: str) -> ClipboardCopyResult:
        copied.append(text)
        return ClipboardCopyResult(ok=True, command="fake-copy", message="copied")

    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            get_recent_assistant_texts=lambda: ("latest answer", "previous answer"),
            copy_text=_copy_text,
        ),
    )

    latest_result = asyncio.run(controller.execute_command_async("/copy", ""))
    previous_result = asyncio.run(controller.execute_command_async("/copy", "2"))

    assert copied == ["latest answer", "previous answer"]
    assert latest_result is not None
    assert latest_result.result == {
        "source": "builtin",
        "command": "copy",
        "status": "ok",
        "copied": True,
        "characters": len("latest answer"),
        "command_backend": "fake-copy",
        "message": "copied",
        "index": 1,
    }
    assert previous_result is not None
    assert previous_result.result == {
        "source": "builtin",
        "command": "copy",
        "status": "ok",
        "copied": True,
        "characters": len("previous answer"),
        "command_backend": "fake-copy",
        "message": "copied",
        "index": 2,
    }


def test_command_controller_rejects_invalid_builtin_copy_index(tmp_path) -> None:
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            get_recent_assistant_texts=lambda: ("latest answer",)
        ),
    )

    zero_result = asyncio.run(controller.execute_command_async("/copy", "0"))
    bad_result = asyncio.run(controller.execute_command_async("/copy", "latest"))
    missing_result = asyncio.run(controller.execute_command_async("/copy", "2"))

    assert zero_result is not None
    assert zero_result.result == {
        "source": "builtin",
        "command": "copy",
        "status": "error",
        "message": "Usage: /copy [N], where N is a positive integer.",
    }
    assert bad_result is not None
    assert bad_result.result == zero_result.result
    assert missing_result is not None
    assert missing_result.result == {
        "source": "builtin",
        "command": "copy",
        "status": "ok",
        "copied": False,
        "characters": 0,
        "message": "No assistant text is available for /copy 2.",
        "index": 2,
    }


def test_command_controller_keeps_legacy_builtin_copy_backend(tmp_path) -> None:
    copied: list[str] = []
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            get_last_assistant_text=lambda: "legacy latest",
            copy_text=lambda text: (
                copied.append(text) or ClipboardCopyResult(ok=True, command="fake-copy")
            ),
        ),
    )

    result = asyncio.run(controller.execute_command_async("/copy", ""))

    assert copied == ["legacy latest"]
    assert result is not None
    assert result.result == {
        "source": "builtin",
        "command": "copy",
        "status": "ok",
        "copied": True,
        "characters": len("legacy latest"),
        "command_backend": "fake-copy",
        "message": None,
        "index": 1,
    }


def test_command_controller_executes_builtin_runtime_session_commands(tmp_path) -> None:
    calls: list[tuple[str, object]] = []

    async def _new_session(options: object | None = None) -> dict[str, object]:
        calls.append(("new", options))
        return {"cancelled": False}

    async def _resume_session(
        session_path: str, options: object | None = None
    ) -> dict[str, object]:
        calls.append(("resume", (session_path, options)))
        return {"cancelled": False}

    async def _fork(entry_id: str, options: object | None = None) -> dict[str, object]:
        calls.append(("fork", (entry_id, options)))
        return {"cancelled": False, "selected_text": "selected"}

    async def _clone() -> dict[str, object]:
        calls.append(("clone", None))
        return {"cancelled": False}

    async def _navigate_tree(
        target_id: str, options: object | None = None
    ) -> dict[str, object]:
        calls.append(("tree", (target_id, options)))
        return {"cancelled": False}

    async def _import_session(
        input_path: str, cwd_override: str | None = None
    ) -> dict[str, object]:
        calls.append(("import", (input_path, cwd_override)))
        return {"cancelled": False}

    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            new_session=_new_session,
            resume_session=_resume_session,
            fork_session=_fork,
            clone_session=_clone,
            navigate_tree=_navigate_tree,
            import_session=_import_session,
        ),
    )

    results = [
        asyncio.run(controller.execute_command_async("/new", "")),
        asyncio.run(controller.execute_command_async("/resume", "/tmp/session.jsonl")),
        asyncio.run(controller.execute_command_async("/fork", "entry-1 before")),
        asyncio.run(controller.execute_command_async("/clone", "")),
        asyncio.run(
            controller.execute_command_async(
                "/tree", "entry-2 --summarize --label chosen"
            )
        ),
        asyncio.run(
            controller.execute_command_async(
                "/import", "/tmp/import.jsonl /tmp/project"
            )
        ),
    ]

    assert [result.result for result in results if result is not None] == [
        {
            "source": "builtin",
            "command": "new",
            "status": "ok",
            "result": {"cancelled": False},
            "message": "Started a new session.",
        },
        {
            "source": "builtin",
            "command": "resume",
            "status": "ok",
            "result": {"cancelled": False},
        },
        {
            "source": "builtin",
            "command": "fork",
            "status": "ok",
            "result": {"cancelled": False, "selected_text": "selected"},
        },
        {
            "source": "builtin",
            "command": "clone",
            "status": "ok",
            "result": {"cancelled": False},
        },
        {
            "source": "builtin",
            "command": "tree",
            "status": "ok",
            "result": {"cancelled": False},
        },
        {
            "source": "builtin",
            "command": "import",
            "status": "ok",
            "result": {"cancelled": False},
        },
    ]
    assert calls == [
        ("new", None),
        ("resume", ("/tmp/session.jsonl", None)),
        ("fork", ("entry-1", {"position": "before"})),
        ("clone", None),
        ("tree", ("entry-2", {"summarize": True, "label": "chosen"})),
        ("import", ("/tmp/import.jsonl", "/tmp/project")),
    ]


def test_command_controller_projects_standard_session_argument_errors(tmp_path) -> None:
    async def _resume(
        session_path: str, options: object | None = None
    ) -> dict[str, object]:
        del session_path, options
        return {"cancelled": False}

    async def _fork(entry_id: str, options: object | None = None) -> dict[str, object]:
        del entry_id, options
        return {"cancelled": False}

    async def _navigate_tree(
        target_id: str, options: object | None = None
    ) -> dict[str, object]:
        del target_id, options
        return {"cancelled": False}

    async def _new_session(options: object | None = None) -> dict[str, object]:
        del options
        return {"cancelled": False}

    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(
            new_session=_new_session,
            resume_session=_resume,
            fork_session=_fork,
            navigate_tree=_navigate_tree,
        ),
    )

    resume = asyncio.run(controller.execute_command_async("/resume", ""))
    new = asyncio.run(controller.execute_command_async("/new", "/tmp/project"))
    fork = asyncio.run(controller.execute_command_async("/fork", "entry elsewhere"))
    tree = asyncio.run(controller.execute_command_async("/tree", ""))

    assert resume is not None
    assert resume.result == {
        "source": "builtin",
        "command": "resume",
        "status": "error",
        "message": "Usage: /resume <session-id-or-path>",
    }
    assert new is not None
    assert new.result == {
        "source": "builtin",
        "command": "new",
        "status": "error",
        "message": "Usage: /new",
    }
    assert fork is not None
    assert fork.result == {
        "source": "builtin",
        "command": "fork",
        "status": "error",
        "message": "Unsupported fork position: elsewhere",
    }
    assert tree is not None
    assert tree.result == {
        "source": "builtin",
        "command": "tree",
        "status": "error",
        "message": "Usage: /tree <entry-id> [--summarize] [--label <label>]",
    }


def test_command_controller_records_missing_command_without_resource_bundle(
    tmp_path,
) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    diagnostics_service = DiagnosticsService()
    controller = CommandController(
        session_manager=manager,
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: diagnostics_service,
    )

    assert asyncio.run(controller.execute_command_async("missing", "args")) is None

    records = diagnostics_service.get_diagnostics(code="command_not_found")
    assert len(records) == 1
    assert records[0].details == {"invocation_name": "missing", "args": "args"}


def test_command_controller_extracts_and_rejects_queued_extension_commands(
    tmp_path,
) -> None:
    async def _handler(args: str, ctx) -> None:
        del args, ctx

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="deploy-ext",
                source_path=Path("/tmp/project/extensions/deploy.py"),
                commands={"deploy": RegisteredCommand(name="deploy", handler=_handler)},
            )
        ]
    )
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: runner,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )

    assert controller.extract_extension_command_invocation("/deploy now") == (
        "deploy",
        "now",
    )
    assert controller.extract_extension_command_invocation("deploy now") is None
    assert controller.extract_extension_command_invocation("/missing now") is None

    with pytest.raises(
        RuntimeError, match='Extension command "/deploy" cannot be queued'
    ):
        controller.raise_if_queued_extension_command("/deploy now")


def test_command_controller_preflight_async_consumes_extension_command(
    tmp_path,
) -> None:
    calls: list[str] = []

    async def _handler(args: str, ctx) -> None:
        del ctx
        calls.append(args)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="deploy-ext",
                source_path=Path("/tmp/project/extensions/deploy.py"),
                commands={"deploy": RegisteredCommand(name="deploy", handler=_handler)},
            )
        ]
    )
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: runner,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )

    result = asyncio.run(controller.preflight_user_input_async("/deploy now"))

    assert result.consumed is True
    assert result.text == "/deploy now"
    assert calls == ["now"]


def test_command_controller_preflight_async_consumes_builtin_command(tmp_path) -> None:
    names: list[str | None] = []
    controller = CommandController(
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        get_extension_runner=lambda: None,
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
        standard_ports=StandardSessionCommandPorts(set_session_name=names.append),
    )

    result = asyncio.run(
        controller.preflight_user_input_async("/rename Project Alpha")
    )

    assert result.consumed is True
    assert result.text == "/rename Project Alpha"
    assert names == ["Project Alpha"]
