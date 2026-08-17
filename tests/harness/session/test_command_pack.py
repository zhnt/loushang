from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.session.command_pack import (
    STANDARD_SESSION_COMMAND_PROFILE,
    StandardSessionCommandId,
    StandardSessionCommandPorts,
    StandardSessionExport,
    execute_standard_session_command_async,
    is_standard_session_command,
    list_standard_session_command_descriptors,
    project_standard_session_command_result,
)


def test_standard_session_command_profile_selects_and_removes_commands() -> None:
    profile = STANDARD_SESSION_COMMAND_PROFILE.select(
        {StandardSessionCommandId.SESSION, "compact"}
    )

    assert is_standard_session_command("/session", profile=profile)
    assert is_standard_session_command("compact", profile=profile)
    assert not is_standard_session_command("reload", profile=profile)
    assert not is_standard_session_command(
        "session", profile=profile.without({"session"})
    )

    with pytest.raises(ValueError, match="unknown standard session command"):
        profile.select({"not-a-command"})


def test_standard_session_commands_expose_rename_without_name_alias() -> None:
    descriptors = {
        descriptor.name: descriptor
        for descriptor in list_standard_session_command_descriptors()
    }

    assert "name" not in descriptors
    assert descriptors["rename"].argument_hint == "<name>"
    assert is_standard_session_command("/rename")
    assert not is_standard_session_command("/name")


def test_standard_session_command_pack_delegates_common_operations() -> None:
    calls: list[tuple[str, object]] = []

    async def _compact(instructions: str | None) -> dict[str, object]:
        calls.append(("compact", instructions))
        return {"compacted": True}

    async def _reload() -> None:
        calls.append(("reload", None))

    ports = StandardSessionCommandPorts(
        get_session_info=lambda: {"session_id": "session-1"},
        compact=_compact,
        reload=_reload,
    )

    session = asyncio.run(
        execute_standard_session_command_async("/session", "ignored", ports)
    )
    compact = asyncio.run(
        execute_standard_session_command_async("compact", "keep decisions", ports)
    )
    reload = asyncio.run(
        execute_standard_session_command_async("reload", "ignored", ports)
    )
    unavailable = asyncio.run(
        execute_standard_session_command_async("clone", "", ports)
    )

    assert session is not None
    assert session.disposition == "completed"
    assert session.value == {"session_id": "session-1"}
    assert compact is not None
    assert compact.disposition == "completed"
    assert compact.value == {"compacted": True}
    assert reload is not None
    assert reload.disposition == "completed"
    assert unavailable is not None
    assert unavailable.disposition == "unavailable"
    assert calls == [("compact", "keep decisions"), ("reload", None)]


def test_standard_session_command_pack_delegates_identity_and_transcript_operations() -> (
    None
):
    calls: list[tuple[str, object]] = []

    async def _set_name(name: str | None) -> None:
        calls.append(("rename", name))

    def _export_jsonl(path: str | None) -> str:
        calls.append(("export", ("jsonl", path)))
        return "/tmp/session.jsonl"

    async def _import(path: str, cwd: str | None) -> dict[str, object]:
        calls.append(("import", (path, cwd)))
        return {"session_id": "session-2"}

    ports = StandardSessionCommandPorts(
        set_session_name=_set_name,
        export_jsonl=_export_jsonl,
        import_session=_import,
    )

    renamed = asyncio.run(
        execute_standard_session_command_async("rename", "Alpha", ports)
    )
    export = asyncio.run(
        execute_standard_session_command_async("export", "saved.jsonl", ports)
    )
    imported = asyncio.run(
        execute_standard_session_command_async(
            "import", 'saved.jsonl "/tmp/project"', ports
        )
    )
    invalid_import = asyncio.run(
        execute_standard_session_command_async("import", "", ports)
    )

    assert renamed is not None
    assert renamed.value == "Alpha"
    assert export is not None
    assert export.value == StandardSessionExport(
        format="jsonl", path="/tmp/session.jsonl"
    )
    assert imported is not None
    assert imported.value == {"session_id": "session-2"}
    assert invalid_import is not None
    assert invalid_import.error_code == "missing_import_path"
    assert calls == [
        ("rename", "Alpha"),
        ("export", ("jsonl", "saved.jsonl")),
        ("import", ("saved.jsonl", "/tmp/project")),
    ]


def test_standard_session_command_pack_requires_the_selected_export_port() -> None:
    calls: list[str | None] = []
    ports = StandardSessionCommandPorts(
        export_html=lambda path: calls.append(path) or "/tmp/session.html"
    )

    jsonl = asyncio.run(
        execute_standard_session_command_async("export", "session.jsonl", ports)
    )
    html = asyncio.run(execute_standard_session_command_async("export", "", ports))

    assert jsonl is not None
    assert jsonl.disposition == "unavailable"
    assert html is not None
    assert html.value == StandardSessionExport(format="html", path="/tmp/session.html")
    assert calls == [None]


def test_standard_session_command_pack_parses_lifecycle_and_tree_arguments() -> None:
    calls: list[tuple[str, object]] = []

    async def _new(options: object | None = None) -> dict[str, object]:
        calls.append(("new", options))
        return {"cancelled": False}

    async def _resume(reference: str, options: object) -> dict[str, object]:
        calls.append(("resume", (reference, options)))
        return {"cancelled": False}

    async def _fork(record_id: str, options: object) -> dict[str, object]:
        calls.append(("fork", (record_id, options)))
        return {"cancelled": False}

    async def _clone() -> dict[str, object]:
        calls.append(("clone", None))
        return {"cancelled": False}

    async def _tree(record_id: str, options: object) -> dict[str, object]:
        calls.append(("tree", (record_id, options)))
        return {"cancelled": False}

    ports = StandardSessionCommandPorts(
        new_session=_new,
        resume_session=_resume,
        fork_session=_fork,
        clone_session=_clone,
        navigate_tree=_tree,
    )

    results = [
        asyncio.run(execute_standard_session_command_async("new", "", ports)),
        asyncio.run(
            execute_standard_session_command_async("resume", "session-2", ports)
        ),
        asyncio.run(
            execute_standard_session_command_async("fork", "entry-1 before", ports)
        ),
        asyncio.run(execute_standard_session_command_async("clone", "", ports)),
        asyncio.run(
            execute_standard_session_command_async(
                "tree",
                "entry-2 --summarize --label chosen --instructions focused",
                ports,
            )
        ),
    ]
    missing_resume = asyncio.run(
        execute_standard_session_command_async("resume", "", ports)
    )
    invalid_new = asyncio.run(
        execute_standard_session_command_async("new", "/next", ports)
    )
    invalid_fork = asyncio.run(
        execute_standard_session_command_async("fork", "entry-1 elsewhere", ports)
    )

    assert all(
        result is not None and result.disposition == "completed" for result in results
    )
    assert missing_resume is not None
    assert missing_resume.disposition == "invalid_arguments"
    assert missing_resume.error_code == "missing_reference"
    assert invalid_new is not None
    assert invalid_new.disposition == "invalid_arguments"
    assert invalid_new.error_code == "unexpected_arguments"
    assert invalid_fork is not None
    assert invalid_fork.disposition == "invalid_arguments"
    assert invalid_fork.error_code == "invalid_fork_position"
    assert invalid_fork.value == "elsewhere"
    assert calls == [
        ("new", None),
        ("resume", ("session-2", None)),
        ("fork", ("entry-1", {"position": "before"})),
        ("clone", None),
        (
            "tree",
            (
                "entry-2",
                {
                    "summarize": True,
                    "label": "chosen",
                    "custom_instructions": "focused",
                },
            ),
        ),
    ]


def test_standard_new_command_projects_cancelled_operation_explicitly() -> None:
    result = asyncio.run(
        execute_standard_session_command_async(
            "new",
            "",
            StandardSessionCommandPorts(
                new_session=lambda: {"cancelled": True},
            ),
        )
    )

    assert result is not None
    assert project_standard_session_command_result(result) == {
        "source": "builtin",
        "command": "new",
        "status": "ok",
        "result": {"cancelled": True},
        "message": "New session creation cancelled.",
    }


def test_standard_session_command_projects_compaction_observability() -> None:
    result = asyncio.run(
        execute_standard_session_command_async(
            "session",
            "",
            StandardSessionCommandPorts(
                get_session_info=lambda: {
                    "session_id": "session-1",
                    "cwd": "/tmp/project",
                    "compaction": {
                        "is_compacting": False,
                        "last_reason": "threshold",
                        "last_stage": "committed",
                        "last_summary_mode": "stream",
                        "last_tokens_before": 90_000,
                        "last_tokens_after": 12_000,
                    },
                    "context": {
                        "tokens": 12_000,
                        "context_window": 131_072,
                        "reserve_tokens": 8_192,
                    },
                },
            ),
        )
    )

    assert result is not None
    projected = project_standard_session_command_result(result)
    assert projected["message"] == (
        "Session: session-1 | CWD: /tmp/project | "
        "Compact: threshold/committed, stream, 90000→12000 tokens | "
        "Context: 12000/131072 tokens, reserve 8192"
    )


def test_standard_session_command_pack_manages_tools_without_coding() -> None:
    active = ["read"]
    tools = [
        {"name": "read", "description": "Read files"},
        {"name": "bash", "description": "Run commands"},
    ]
    ports = StandardSessionCommandPorts(
        get_active_tool_names=lambda: active,
        get_all_tools=lambda: tools,
        set_active_tools=lambda names: active.__setitem__(slice(None), names),
        get_default_active_tool_names=lambda: ["read"],
    )

    result = asyncio.run(
        execute_standard_session_command_async("tools", "on bash", ports)
    )

    assert result is not None and result.disposition == "completed"
    assert result.value == {
        "active_tools": ["read", "bash"],
        "available_tools": [
            {"name": "read", "active": True, "description": "Read files"},
            {"name": "bash", "active": True, "description": "Run commands"},
        ],
        "action": "on",
    }
    assert active == ["read", "bash"]


def test_standard_session_command_pack_queries_extensions_without_coding() -> None:
    ports = StandardSessionCommandPorts(
        get_extensions=lambda: [
            {"id": "acme.review", "name": "Acme Review"},
        ]
    )

    result = asyncio.run(
        execute_standard_session_command_async("extensions", "acme.review", ports)
    )

    assert result is not None and result.disposition == "completed"
    assert result.value == {
        "extensions": [{"id": "acme.review", "name": "Acme Review"}],
        "query": "acme.review",
        "selected": {"id": "acme.review", "name": "Acme Review"},
    }


def test_standard_session_command_pack_copies_selected_assistant_text() -> None:
    copied: list[str] = []

    class _CopyResult:
        ok = True
        command = "clipboard"
        message = "copied"

    ports = StandardSessionCommandPorts(
        get_recent_assistant_texts=lambda: ("first", "second"),
        copy_text=lambda text: copied.append(text) or _CopyResult(),
    )

    result = asyncio.run(
        execute_standard_session_command_async("copy", "2", ports)
    )

    assert result is not None and result.disposition == "completed"
    assert result.value == {
        "copied": True,
        "characters": 6,
        "index": 2,
        "available": True,
        "command": "clipboard",
        "message": "copied",
    }
    assert copied == ["second"]


def test_standard_session_command_pack_forwards_changelog_request() -> None:
    ports = StandardSessionCommandPorts(
        get_changelog=lambda args: {"query": args, "entries": []}
    )

    result = asyncio.run(
        execute_standard_session_command_async("changelog", "recent", ports)
    )

    assert result is not None and result.disposition == "completed"
    assert result.value == {"query": "recent", "entries": []}


def test_standard_session_command_pack_has_no_coding_import() -> None:
    session_root = (
        Path(__file__).parents[3] / "src/loushang/harness/session/command_pack.py"
    ).parent
    module_paths = [session_root / "command_pack.py"]
    module_paths.extend(sorted((session_root / "commands").glob("*.py")))

    assert all(
        "loushang.coding" not in path.read_text(encoding="utf-8")
        for path in module_paths
    )
