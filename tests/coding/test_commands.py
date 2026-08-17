from __future__ import annotations


def test_parse_slash_command_splits_name_args_and_mcp_marker() -> None:
    from loushang.harness.commands import parse_slash_command

    parsed = parse_slash_command("/deploy prod now")
    assert parsed is not None
    assert (parsed.name, parsed.args, parsed.is_mcp) == ("deploy", "prod now", False)

    mcp = parse_slash_command("/mcp__ide__diagnostics (MCP) current file")
    assert mcp is not None
    assert (mcp.name, mcp.args, mcp.is_mcp) == (
        "mcp__ide__diagnostics (MCP)",
        "current file",
        True,
    )


def test_parse_slash_command_rejects_non_commands_and_empty_names() -> None:
    from loushang.harness.commands import parse_slash_command

    assert parse_slash_command("deploy prod") is None
    assert parse_slash_command(" /deploy prod") is None
    assert parse_slash_command("/") is None
    assert parse_slash_command("/   ") is None


def test_standard_session_commands_have_shared_metadata() -> None:
    from loushang.harness.session import STANDARD_SESSION_COMMANDS

    commands = {command.name: command.description for command in STANDARD_SESSION_COMMANDS}

    assert commands == {
        "export": "Export session (HTML default, or specify path: .html/.jsonl)",
        "import": "Import and resume a session from a JSONL file",
        "copy": "Copy an assistant message to clipboard",
        "rename": "Rename the current session",
        "session": "Show session info and stats",
        "changelog": "Show changelog entries",
        "fork": "Create a new fork from a previous user message",
        "clone": "Duplicate the current session at the current position",
        "tree": "Navigate session tree (switch branches)",
        "tools": "Show or update active tools for this session",
        "extensions": "Show loaded extensions and diagnostics",
        "new": "Start a new session in the current context",
        "compact": "Manually compact the session context",
        "resume": "Resume a different session",
        "delete": "Delete a previous session",
        "reload": "Reload keybindings, extensions, skills, prompts, and themes",
    }


def test_complete_slash_commands_filters_by_prefix_and_marks_conflicts() -> None:
    from loushang.harness.commands import (
        CommandSourceInfo,
        SessionCommandDescriptor,
        complete_slash_commands,
    )

    completions = complete_slash_commands(
        "/de",
        [
            SessionCommandDescriptor(
                name="deploy",
                description="Deploy from extension A",
                source="extension",
                source_info=CommandSourceInfo(path="/tmp/a.py"),
            ),
            SessionCommandDescriptor(
                name="deploy:1",
                description="Deploy from extension B",
                source="extension",
                source_info=CommandSourceInfo(path="/tmp/b.py"),
                conflict_group="deploy",
            ),
            SessionCommandDescriptor(
                name="debug",
                description="Debug skill",
                source="skill",
                source_info=CommandSourceInfo(path="/tmp/debug/SKILL.md"),
            ),
        ],
    )

    assert completions == [
        {
            "value": "/deploy",
            "label": "/deploy",
            "description": "Deploy from extension A",
            "source": "extension",
            "kind": "command",
        },
        {
            "value": "/deploy:1",
            "label": "/deploy:1",
            "description": "Deploy from extension B",
            "source": "extension",
            "kind": "command",
            "conflictGroup": "deploy",
        },
        {
            "value": "/debug",
            "label": "/debug",
            "description": "Debug skill",
            "source": "skill",
            "kind": "command",
        },
    ]


def test_session_command_descriptor_remains_a_runtime_class() -> None:
    from loushang.harness.commands import (
        CommandDescriptor,
        CommandSourceInfo,
        SessionCommandDescriptor,
    )

    command = SessionCommandDescriptor(
        name="review",
        description="Review a change",
        source="prompt",
        source_info=CommandSourceInfo(path="/tmp/prompts/review.md"),
    )

    assert isinstance(command, SessionCommandDescriptor)
    assert isinstance(command, CommandDescriptor)


def test_session_command_descriptor_preserves_legacy_positional_fields() -> None:
    from loushang.harness.commands import (
        CommandSourceInfo,
        SessionCommandDescriptor,
    )

    command = SessionCommandDescriptor(
        "review",
        "Review a change",
        "prompt",
        CommandSourceInfo(path="/tmp/prompts/review.md"),
        "review:project",
        "review",
        "<target>",
    )

    assert command.invocation_name == "review:project"
    assert command.conflict_group == "review"
    assert command.argument_hint == "<target>"
    assert command.aliases == ()
