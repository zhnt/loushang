from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest


def _command_descriptor(item: dict[str, object]) -> SimpleNamespace:
    source_info = item.get("source_info")
    if isinstance(source_info, dict):
        path = source_info.get("path", "")
    else:
        path = item.get("path", "")
    return SimpleNamespace(
        name=item.get("name"),
        description=item.get("description"),
        source=item.get("source"),
        argument_hint=item.get("argument_hint"),
        source_info=SimpleNamespace(path=path),
    )


class FakeSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.session_name = session_id
        self.session_file = Path(f"/tmp/{session_id}.jsonl")
        self.set_model_calls = []
        self.set_thinking_calls = []
        self.set_session_name_calls: list[str | None] = []
        self.set_export_calls: list[str | None] = []
        self.set_jsonl_export_calls: list[str | None] = []
        self.get_available_models_calls = 0
        self.list_commands_calls = 0
        self.commands_payload = []
        self.diagnostics_payload = []
        self.execute_command_calls: list[tuple[str, str]] = []
        self.execute_command_result: object | None = None
        self.materialize_package_calls: list[str] = []
        self.install_package_calls: list[tuple[str, str]] = []
        self.update_package_calls: list[str] = []
        self.update_packages_calls = 0
        self.check_package_updates_calls = 0
        self.remove_package_calls: list[str] = []
        self.uninstall_package_calls: list[tuple[str, str]] = []
        self.packages_payload: list[dict[str, object]] = []
        self.resource_bundle = SimpleNamespace(skills=[])

    async def set_model(self, selection) -> None:
        self.set_model_calls.append(selection)

    def set_thinking_level(self, level) -> None:
        self.set_thinking_calls.append(level)

    def set_session_name(self, name: str | None) -> None:
        self.set_session_name_calls.append(name)
        self.session_name = name

    def export_to_html(self, output_path: str | None = None) -> str:
        self.set_export_calls.append(output_path)
        return output_path if output_path is not None else str(self.session_file.with_suffix(".html"))

    def export_to_jsonl(self, output_path: str | None = None) -> str:
        self.set_jsonl_export_calls.append(output_path)
        return output_path if output_path is not None else str(self.session_file.with_name(f"{self.session_id}-export.jsonl"))

    def get_available_models(self):
        self.get_available_models_calls += 1
        return []

    def list_commands(self):
        self.list_commands_calls += 1
        return self.commands_payload

    def get_last_diagnostics(self, limit: int = 50):
        return self.diagnostics_payload[-limit:]

    async def execute_command_async(self, invocation_name: str, args: str):
        self.execute_command_calls.append((invocation_name, args))
        return self.execute_command_result

    def set_commands(self, payload: list[dict[str, object]]) -> None:
        self.commands_payload = [_command_descriptor(item) for item in payload]

    def set_diagnostics(self, payload: list[object]) -> None:
        self.diagnostics_payload = list(payload)

    def set_execute_command_result(self, result: object | None) -> None:
        self.execute_command_result = result

    async def materialize_package(self, source: str) -> dict[str, object]:
        self.materialize_package_calls.append(source)
        return {"source": source, "name": "review-pack", "lifecycle": "installed", "targetPath": "/tmp/packages/review-pack"}

    def get_packages(self, *, catalog_path: str | None = None):
        del catalog_path
        return list(self.packages_payload)

    async def install_package(self, source: str, *, scope: str = "project") -> dict[str, object]:
        self.install_package_calls.append((source, scope))
        return {"source": source, "name": "review-pack", "lifecycle": "installed", "targetPath": "/tmp/packages/review-pack"}

    async def update_package(self, source: str) -> dict[str, object]:
        self.update_package_calls.append(source)
        return {"source": source, "name": "review-pack", "lifecycle": "installed", "targetPath": "/tmp/packages/review-pack"}

    async def update_packages(self) -> list[dict[str, object]]:
        self.update_packages_calls += 1
        return [{"source": "all", "name": "all", "lifecycle": "installed", "targetPath": "/tmp/packages"}]

    async def check_package_updates(self) -> list[dict[str, object]]:
        self.check_package_updates_calls += 1
        return [{"source": "all", "name": "review-pack", "currentCommit": "a", "availableCommit": "b", "pinned": False}]

    def remove_package(self, source: str) -> dict[str, object]:
        self.remove_package_calls.append(source)
        return {"source": source, "name": "review-pack", "lifecycle": "remote_registered", "targetPath": "/tmp/packages/review-pack"}

    def uninstall_package(self, source: str, *, scope: str = "project") -> dict[str, object]:
        self.uninstall_package_calls.append((source, scope))
        return {"source": source, "name": "review-pack", "lifecycle": "remote_registered", "targetPath": "/tmp/packages/review-pack"}


class FakeRuntime:
    def __init__(self, session: FakeSession, records: list[object] | None = None) -> None:
        self._current_session = session
        self.new_session_calls: list[str] = []
        self.restore_session_calls: list[str] = []
        self.fork_session_calls: list[str] = []
        self.list_sessions_calls: int = 0
        self.list_all_session_summaries_calls: int = 0
        self.find_session_summaries_calls: list[object] = []
        self.find_all_session_summaries_calls: list[object] = []
        self.refresh_session_index_calls = 0
        self.refresh_all_session_indexes_calls = 0
        self.list_indexed_session_summaries_calls = 0
        self.list_all_indexed_session_summaries_calls = 0
        self.find_indexed_session_summaries_calls: list[object] = []
        self.find_all_indexed_session_summaries_calls: list[object] = []
        self.session_records = list(records or [])

    def get_current_session(self) -> FakeSession:
        return self._current_session

    async def new_session(self, *, cwd: str) -> FakeSession:
        self.new_session_calls.append(cwd)
        return self._current_session

    async def restore_session(self, session_id: str) -> FakeSession:
        self.restore_session_calls.append(session_id)
        return self._current_session

    async def fork_session(self, entry_id: str) -> FakeSession:
        self.fork_session_calls.append(entry_id)
        return self._current_session

    def list_sessions(self) -> list[object]:
        self.list_sessions_calls += 1
        return self.session_records

    def list_all_session_summaries(self) -> list[object]:
        self.list_all_session_summaries_calls += 1
        return self.session_records

    def find_session_summaries(self, query) -> list[object]:
        self.find_session_summaries_calls.append(query)
        return self.session_records

    def find_all_session_summaries(self, query) -> list[object]:
        self.find_all_session_summaries_calls.append(query)
        return self.session_records

    def refresh_session_index(self) -> list[object]:
        self.refresh_session_index_calls += 1
        return self.session_records

    def refresh_all_session_indexes(self) -> list[object]:
        self.refresh_all_session_indexes_calls += 1
        return self.session_records

    def list_indexed_session_summaries(self) -> list[object]:
        self.list_indexed_session_summaries_calls += 1
        return self.session_records

    def list_all_indexed_session_summaries(self) -> list[object]:
        self.list_all_indexed_session_summaries_calls += 1
        return self.session_records

    def find_indexed_session_summaries(self, query) -> list[object]:
        self.find_indexed_session_summaries_calls.append(query)
        return self.session_records

    def find_all_indexed_session_summaries(self, query) -> list[object]:
        self.find_all_indexed_session_summaries_calls.append(query)
        return self.session_records


class FakeRunner:
    def __init__(self, *, exit_code: int = 0) -> None:
        self.calls: list[dict[str, object]] = []
        self.exit_code = exit_code

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.exit_code


class TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _append_work_log_marker(event_log: object) -> Path:
    from loushang.work import EventLogEntry

    path = getattr(event_log, "_path")
    event_log.append(
        EventLogEntry(
            entry_id="entry-1",
            entry_type="event",
            operation_id="op-1",
            event_id="event-1",
            run_id="run-1",
            session_id="session-1",
            sequence=1,
            payload={"kind": "WorkRunStarted"},
            created_at=datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )
    )
    return path


def _append_work_log_inspect_entry(
    event_log: object,
    *,
    sequence: int,
    kind: str,
    run_id: str = "run-1",
    session_id: str = "session-1",
    entry_type: str = "event",
    delivery_hint: str | None = None,
    method_id: str | None = None,
) -> None:
    from loushang.work import EventLogEntry

    payload: dict[str, object] = {"kind": kind}
    if delivery_hint is not None:
        payload["delivery_hint"] = delivery_hint
    if method_id is not None:
        payload["payload"] = {"method_id": method_id}
    event_log.append(
        EventLogEntry(
            entry_id=f"entry-{sequence}",
            entry_type=entry_type,
            operation_id=f"operation-{run_id}",
            event_id=f"event-{sequence}" if entry_type == "event" else None,
            run_id=run_id,
            session_id=session_id,
            sequence=sequence,
            payload=payload,
            created_at=datetime(2026, 6, 1, 10, 30, sequence, tzinfo=UTC),
        )
    )


def _fake_services(
    session_dir: str | None = None,
    package_roots: tuple[str, ...] = (),
    plugin_sources: tuple[str, ...] = (),
    disabled_plugins: tuple[str, ...] = (),
    method_settings: object | None = None,
):
    settings = SimpleNamespace(
        session_dir=session_dir,
        package_roots=package_roots,
        plugin_sources=plugin_sources,
        disabled_plugins=disabled_plugins,
        method=method_settings,
    )
    settings_manager = SimpleNamespace(get_settings=lambda: settings)
    return SimpleNamespace(settings_manager=settings_manager, diagnostics_service=object())


def _write_review_method(project_root: Path) -> None:
    method_dir = project_root / "methods" / "task" / "review"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\n"
        "name: review\n"
        "description: Review changes.\n"
        "type: task\n"
        "meta_role: VALIDATOR\n"
        "---\n\n"
        "Use concise review guidance.",
        encoding="utf-8",
    )


def _write_debug_method(project_root: Path) -> None:
    method_dir = project_root / "methods" / "task" / "debug"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\n"
        "name: debug\n"
        "description: Debug failures.\n"
        "type: task\n"
        "meta_role: VALIDATOR\n"
        "---\n\n"
        "Use focused debugging guidance.",
        encoding="utf-8",
    )


def _write_fixed_review_method(project_root: Path) -> None:
    method_dir = project_root / "methods" / "task" / "review"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\n"
        "name: review\n"
        "description: Review changes.\n"
        "type: task\n"
        "meta_role: VALIDATOR\n"
        "plan_mode: fixed\n"
        "steps:\n"
        "  - inspect\n"
        "  - verify\n"
        "step_titles:\n"
        "  inspect: Inspect current changes\n"
        "  verify: Run focused checks\n"
        "step_guidance:\n"
        "  inspect: Read changed files and summarize intent.\n"
        "  verify: Run focused tests or explain why they cannot run.\n"
        "---\n\n"
        "Use concise review guidance.",
        encoding="utf-8",
    )


def test_parse_args_supports_modes_sessions_and_overrides() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "--mode",
            "json",
            "--session",
            "session-1",
            "--list-sessions",
            "--list-sessions-format",
            "json",
            "--session-index",
            "--refresh-session-index",
            "--fork",
            "entry-42",
            "--session-dir",
            "/tmp/sessions",
            "--provider",
            "faux",
            "--model",
            "alpha",
            "--tool",
            "bash",
            "--tool",
            "read",
            "--render-tool-events",
            "hello",
            "world",
        ]
    )

    assert args.mode == "json"
    assert args.session == "session-1"
    assert args.list_sessions is True
    assert args.list_sessions_format == "json"
    assert args.session_index is True
    assert args.refresh_session_index is True
    assert args.session_has_diagnostics is None
    assert args.fork == "entry-42"
    assert args.session_dir == "/tmp/sessions"
    assert args.provider == "faux"
    assert args.model == "alpha"
    assert args.tools == ("bash", "read")
    assert args.render_tool_events is True
    assert args.messages == ("hello", "world")


def test_parse_args_accepts_tui_flag() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["--tui"])

    assert args.tui is True


def test_parse_args_accepts_no_tui_flag() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["--no-tui"])

    assert args.no_tui is True


def test_parse_args_accepts_work_log_flag() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["--work-log", ".loushang/work/events.jsonl", "hello"])

    assert args.work_log == ".loushang/work/events.jsonl"
    assert args.messages == ("hello",)


def test_parse_args_accepts_work_log_inspect_flags() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "--work-log-inspect",
            ".loushang/work/events.jsonl",
            "--work-log-run",
            "run-1",
            "--work-log-inspect-format",
            "json",
        ]
    )

    assert args.work_log_inspect == ".loushang/work/events.jsonl"
    assert args.work_log_run == "run-1"
    assert args.work_log_inspect_format == "json"


def test_parse_args_accepts_method_visibility_flags_and_subcommands() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["--list-methods", "--list-methods-format", "json"])

    assert args.list_methods is True
    assert args.list_methods_format == "json"

    show_args = parse_args(["method", "show", "method:task:review", "--show-method-format", "json"])

    assert show_args.show_method == "method:task:review"
    assert show_args.show_method_format == "json"

    list_args = parse_args(["method", "list"])

    assert list_args.list_methods is True

    cwd_first_args = parse_args(["--cwd", "/tmp/project", "method", "list"])

    assert cwd_first_args.cwd == "/tmp/project"
    assert cwd_first_args.list_methods is True

    message_args = parse_args(["fix", "method", "list"])

    assert message_args.list_methods is False
    assert message_args.messages == ("fix", "method", "list")


def test_parse_args_accepts_observability_flags() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "--debug=tui,agent",
            "--debug-file",
            "/tmp/debug.log",
            "--trace=provider",
            "--trace-file",
            "/tmp/trace.jsonl",
        ]
    )

    assert args.debug == "tui,agent"
    assert args.debug_file == "/tmp/debug.log"
    assert args.trace == "provider"
    assert args.trace_file == "/tmp/trace.jsonl"


def test_parse_args_keeps_prompt_after_bare_observability_flags() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["--debug", "--trace", "hello"])

    assert args.debug == ""
    assert args.trace == "all"
    assert args.messages == ("hello",)


def test_parse_args_splits_at_file_args_from_plain_messages() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["@README.md", "summarize", "@images/screenshot.png"])

    assert args.file_args == ("README.md", "images/screenshot.png")
    assert args.messages == ("summarize",)


def test_parse_args_supports_explicit_message_prompts() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["hello", "--message", "next", "--message", "final"])

    assert args.messages == ("hello",)
    assert args.message_prompts == ("next", "final")


def test_parse_args_supports_tooling_and_continuation_flags() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "--continue",
            "--list-models",
            "anthropic",
            "--list-models-format",
            "json",
            "--tools",
            "read,write, ls",
            "--tool",
            "grep",
            "--thinking",
            "high",
            "--no-tools",
            "--no-builtin-tools",
            "--no-context-files",
            "hello",
        ]
    )

    assert args.continue_ is True
    assert args.resume is False
    assert args.list_models == "anthropic"
    assert args.list_models_format == "json"
    assert args.tools == ("grep", "read", "write", "ls")
    assert args.thinking == "high"
    assert args.no_tools is True
    assert args.no_builtin_tools is True
    assert args.no_context_files is True
    assert args.messages == ("hello",)


def test_parse_args_supports_resume_session_reference() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(["--resume", "abcd1234"])

    assert args.resume == "abcd1234"
    assert args.messages == ()


def test_parse_args_supports_pi_style_aliases_and_noop_fields() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "--help",
            "-v",
            "--models",
            "claude-3.5,gpt-4o",
            "--extension",
            "plugins/demo.py",
            "--no-extensions",
            "--skill",
            "skill-a",
            "--no-skills",
            "--prompt-template",
            "templates/default.md",
            "--no-prompt-templates",
            "--theme",
            "themes/night",
            "--no-themes",
            "--verbose",
            "--offline",
            "--api-key",
            "top-secret",
            "--system-prompt",
            "sys",
            "--append-system-prompt",
            "A",
            "--append-system-prompt",
            "B",
            "--export",
            "/tmp/out.html",
            "--export-format",
            "jsonl",
            "--export-result-format",
            "json",
            "--tool",
            "bash",
            "--tools",
            "read",
            "-p",
            "hi",
            "--no-context-files",
            "-nc",
            "-t",
            "write",
            "--no-tools",
            "hello",
        ]
    )

    assert args.help is True
    assert args.version is True
    assert args.models == ("claude-3.5", "gpt-4o")
    assert args.extensions == ("plugins/demo.py",)
    assert args.no_extensions is True
    assert args.skills == ("skill-a",)
    assert args.no_skills is True
    assert args.prompt_templates == ("templates/default.md",)
    assert args.no_prompt_templates is True
    assert args.themes == ("themes/night",)
    assert args.no_themes is True
    assert args.verbose is True
    assert args.offline is True
    assert args.api_key == "top-secret"
    assert args.system_prompt == "sys"
    assert args.append_system_prompt == ("A", "B")
    assert args.export == "/tmp/out.html"
    assert args.export_format == "jsonl"
    assert args.export_result_format == "json"
    assert args.tools == ("bash", "read", "write")
    assert args.prompt == "hi"
    assert args.no_context_files is True
    assert args.messages == ("hello",)


def test_parse_args_supports_prompt_alias_and_print_mode() -> None:
    from loushang.coding.cli.args import parse_args

    short = parse_args(["-p", "hello"])
    long = parse_args(["--prompt", "hello"])
    method = parse_args(["--method", "review", "-p", "hello"])
    no_method = parse_args(["--no-method", "-p", "hello"])
    print_mode = parse_args(["--mode", "print", "hello"])
    workflow = parse_args(["-ps", "scenarios/coding/bmi.workflow.yaml"])

    assert short.prompt == "hello"
    assert short.messages == ()
    assert long.prompt == "hello"
    assert long.messages == ()
    assert method.method == "review"
    assert method.no_method is False
    assert method.prompt == "hello"
    assert no_method.no_method is True
    assert no_method.prompt == "hello"
    assert print_mode.mode == "print"
    assert print_mode.messages == ("hello",)
    assert workflow.prompt_steps == "scenarios/coding/bmi.workflow.yaml"


def test_parse_args_rewrites_diag_export_subcommand() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "diag",
            "export",
            "--output",
            "/tmp/loushang-diag.zip",
            "--session-dir",
            "/tmp/sessions",
        ]
    )

    assert args.diag_export is True
    assert args.diag_output == "/tmp/loushang-diag.zip"
    assert args.session_dir == "/tmp/sessions"
    assert args.messages == ()


def test_default_runtime_builder_maps_tools_to_allowed_and_active_tools(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import default_runtime_builder
    from loushang.coding.tools import ToolRegistry, register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)
    runtime = default_runtime_builder(
        args=SimpleNamespace(no_tools=False, tools=("read", "grep"), no_session=True),
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=create_services(),
        tool_registry=registry,
    )

    session = asyncio.run(runtime.create_session(cwd=str(tmp_path)))

    assert session.get_active_tool_names() == ["read", "grep"]
    assert [definition.name for definition in session.get_all_tools()] == ["read", "grep"]


def test_default_runtime_builder_maps_no_tools_to_empty_allowed_tools(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import default_runtime_builder
    from loushang.coding.tools import ToolRegistry, register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)
    runtime = default_runtime_builder(
        args=SimpleNamespace(no_tools=True, tools=(), no_session=True),
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=create_services(),
        tool_registry=registry,
    )

    session = asyncio.run(runtime.create_session(cwd=str(tmp_path)))

    assert session.get_active_tool_names() == []
    assert session.get_all_tools() == []


def test_default_runtime_builder_applies_resource_and_prompt_options(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import default_runtime_builder
    from loushang.coding.tools import ToolRegistry, register_builtin_tools

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "AGENTS.md").write_text("Project guidance", encoding="utf-8")
    system_file = tmp_path / "system.txt"
    system_file.write_text("System from file", encoding="utf-8")
    append_file = tmp_path / "append.txt"
    append_file.write_text("Append from file", encoding="utf-8")
    explicit_skill = tmp_path / "review-skill"
    explicit_skill.mkdir()
    (explicit_skill / "SKILL.md").write_text(
        "---\nname: review\n---\n\nReview skill",
        encoding="utf-8",
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)
    runtime = default_runtime_builder(
        args=SimpleNamespace(
            no_tools=False,
            tools=(),
            no_session=True,
            extensions=(),
            no_extensions=True,
            skills=(str(explicit_skill),),
            no_skills=True,
            prompt_templates=(),
            no_prompt_templates=True,
            themes=(),
            no_themes=True,
            no_context_files=True,
            system_prompt=str(system_file),
            append_system_prompt=(str(append_file), "Inline append"),
        ),
        cwd=project_root,
        session_dir=tmp_path / "sessions",
        services=create_services(),
        tool_registry=registry,
    )

    session = asyncio.run(runtime.create_session(cwd=str(project_root)))

    assert session.agent.system_prompt.startswith("System from file\n\nAppend from file\n\nInline append")
    assert "Project guidance" not in session.agent.system_prompt
    assert [skill.name for skill in session.resource_bundle.skills] == ["review"]


def test_default_runtime_builder_rebuilds_project_bound_services_for_session_cwd(tmp_path) -> None:
    from loushang.coding.cli.__main__ import (
        build_default_services,
        default_runtime_builder,
    )
    from loushang.coding.tools import ToolRegistry, register_builtin_tools

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    (project_b / "AGENTS.md").write_text("Project B guidance", encoding="utf-8")
    registry = ToolRegistry()
    register_builtin_tools(registry)
    services = build_default_services(project_a)

    runtime = default_runtime_builder(
        args=SimpleNamespace(no_tools=False, tools=(), no_session=True),
        cwd=project_a,
        session_dir=tmp_path / "sessions",
        services=services,
        tool_registry=registry,
    )

    first = asyncio.run(runtime.create_session(cwd=str(project_a)))
    second = asyncio.run(runtime.create_session(cwd=str(project_b)))

    assert first.settings_manager is not second.settings_manager
    assert first.resource_loader is not second.resource_loader
    assert second.cwd_bound_services_audit.ok is True
    assert "Project B guidance" in second.agent.system_prompt


def test_cwd_bound_services_factory_uses_sdk_services_creation(tmp_path, monkeypatch) -> None:
    import loushang.coding.cli.__main__ as cli_main
    from loushang.coding.bootstrap import create_services

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    base_services = cli_main.build_default_services(project_a)
    created_services = create_services()
    calls: list[dict[str, object]] = []
    resource_loader_options = {
        "no_context_files": True,
        "additional_skill_paths": [str(tmp_path / "skills")],
    }

    def fake_create_agent_session_services(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(services=created_services)

    monkeypatch.setattr(cli_main, "create_agent_session_services", fake_create_agent_session_services, raising=False)

    factory = cli_main._cwd_bound_services_factory(base_services, resource_loader_options)

    assert factory is not None
    assert factory(str(project_b)) is created_services
    assert calls == [
        {
            "cwd": str(project_b),
            "resource_loader_options": resource_loader_options,
        }
    ]


def test_run_cli_sets_offline_environment_before_building_runtime(tmp_path, monkeypatch) -> None:
    from loushang.coding.cli.__main__ import run_cli

    monkeypatch.delenv("LOUSHANG_OFFLINE", raising=False)
    captured_args = []
    runtime = FakeRuntime(FakeSession("unused"))

    def runtime_builder(**kwargs):
        captured_args.append(kwargs["args"])
        assert os.environ["LOUSHANG_OFFLINE"] == "1"
        return runtime

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--offline",
                "--extension",
                "extensions/demo.py",
                "--skill",
                "skills/review",
                "--no-skills",
                "--list-sessions",
            ],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0

    try:
        asyncio.run(scenario())
    finally:
        os.environ.pop("LOUSHANG_OFFLINE", None)

    assert captured_args
    assert captured_args[0].offline is True
    assert captured_args[0].extensions == ("extensions/demo.py",)
    assert captured_args[0].skills == ("skills/review",)
    assert captured_args[0].no_skills is True


def test_cli_builtin_tool_registry_uses_settings_external_tool_policy(monkeypatch) -> None:
    from loushang.coding.cli import __main__ as cli_main
    from loushang.coding.control import ControlConfig, SettingsManager, ToolSettings

    captured: dict[str, object] = {}

    def fake_register_builtin_tools(registry, **kwargs):
        captured.update(kwargs)
        return registry

    monkeypatch.setattr(cli_main, "register_builtin_tools", fake_register_builtin_tools)
    manager = SettingsManager(ControlConfig(tools=ToolSettings(external_tool_policy="required")))

    cli_main.build_builtin_tool_registry(settings_manager=manager)

    assert captured["external_tool_policy"] == "required"


def test_cli_builtin_tool_registry_binds_headless_policy_from_settings(tmp_path) -> None:
    from loushang.coding.cli import __main__ as cli_main
    from loushang.coding.control import ControlConfig, SettingsManager, ToolSettings
    from loushang.coding.tools import ToolContext

    def context_provider(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, cwd=str(tmp_path))

    allow_manager = SettingsManager(
        ControlConfig(
            tools=ToolSettings(
                ask_tools=("write",),
                approval_mode="allow",
            )
        )
    )
    allow_registry = cli_main.build_builtin_tool_registry(settings_manager=allow_manager)
    allow_tool = allow_registry.materialize_tool("write", context_provider=context_provider)

    asyncio.run(allow_tool.execute("call-allow", {"path": "allowed.txt", "content": "ok"}))

    deny_manager = SettingsManager(
        ControlConfig(
            tools=ToolSettings(
                ask_tools=("write",),
                approval_mode="deny",
                approval_reason="headless policy denied",
            )
        )
    )
    deny_registry = cli_main.build_builtin_tool_registry(settings_manager=deny_manager)
    deny_tool = deny_registry.materialize_tool("write", context_provider=context_provider)

    with pytest.raises(PermissionError, match="headless policy denied"):
        asyncio.run(deny_tool.execute("call-deny", {"path": "denied.txt", "content": "blocked"}))

    assert (tmp_path / "allowed.txt").read_text(encoding="utf-8") == "ok"
    assert not (tmp_path / "denied.txt").exists()


def test_parse_args_supports_command_dispatch_flags() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "--list-commands",
            "--list-commands-format",
            "json",
            "--list-diagnostics",
            "--list-diagnostics-format",
            "json",
            "--diagnostics-limit",
            "7",
            "--list-skills",
            "--list-skills-format",
            "json",
            "--enable-skill",
            "debug",
            "--disable-skill",
            "review",
            "--list-plugins",
            "--list-plugins-format",
            "json",
            "--list-packages",
            "--list-packages-format",
            "json",
            "--package-catalog",
            "catalog.json",
            "--add-plugin-source",
            "plugins/debug-pack",
            "--remove-plugin-source",
            "plugins/legacy-pack",
            "--enable-plugin",
            "debug-pack",
            "--disable-plugin",
            "legacy-pack",
            "--command",
            "deploy",
            "--command-args",
            "now",
            "--command-result-format",
            "json",
            "hello",
        ]
    )

    assert args.list_commands is True
    assert args.list_commands_format == "json"
    assert args.list_diagnostics is True
    assert args.list_diagnostics_format == "json"
    assert args.diagnostics_limit == 7
    assert args.list_skills is True
    assert args.list_skills_format == "json"
    assert args.enable_skills == ("debug",)
    assert args.disable_skills == ("review",)
    assert args.list_plugins is True
    assert args.list_plugins_format == "json"
    assert args.list_packages is True
    assert args.list_packages_format == "json"
    assert args.package_catalog == "catalog.json"
    assert args.add_plugin_sources == ("plugins/debug-pack",)
    assert args.remove_plugin_sources == ("plugins/legacy-pack",)
    assert args.enable_plugins == ("debug-pack",)
    assert args.disable_plugins == ("legacy-pack",)
    assert args.command == "deploy"
    assert args.command_args == "now"
    assert args.command_result_format == "json"
    assert args.messages == ("hello",)


def test_parse_args_maps_pi_style_package_subcommands_to_package_manager_commands() -> None:
    from loushang.coding.cli.args import parse_args

    install = parse_args(["install", "plugins/debug-pack"])
    local_install = parse_args(["install", "-l", "plugins/debug-pack"])
    remove = parse_args(["remove", "plugins/debug-pack"])
    local_remove = parse_args(["remove", "--local", "plugins/debug-pack"])
    uninstall = parse_args(["uninstall", "plugins/debug-pack"])

    assert install.install_packages == ("plugins/debug-pack",)
    assert install.package_scope == "global"
    assert install.messages == ()
    assert local_install.install_packages == ("plugins/debug-pack",)
    assert local_install.package_scope == "project"
    assert remove.uninstall_packages == ("plugins/debug-pack",)
    assert remove.package_scope == "global"
    assert local_remove.uninstall_packages == ("plugins/debug-pack",)
    assert local_remove.package_scope == "project"
    assert remove.messages == ()
    assert uninstall.uninstall_packages == ("plugins/debug-pack",)
    assert uninstall.messages == ()


def test_parse_args_supports_explicit_package_lifecycle_flags() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        [
            "--materialize-package",
            "https://packages.example.invalid/review-pack.git",
            "--update-package",
            "https://packages.example.invalid/review-pack.git",
            "--remove-package",
            "https://packages.example.invalid/review-pack.git",
        ]
    )

    assert args.materialize_packages == ("https://packages.example.invalid/review-pack.git",)
    assert args.update_packages == ("https://packages.example.invalid/review-pack.git",)
    assert args.remove_packages == ("https://packages.example.invalid/review-pack.git",)


def test_parse_args_maps_pi_style_package_list_when_list_is_standalone() -> None:
    from loushang.coding.cli.args import parse_args

    package_list = parse_args(["list"])
    prompt = parse_args(["list", "files"])

    assert package_list.list_packages is True
    assert package_list.messages == ()
    assert prompt.list_packages is False
    assert prompt.messages == ("list", "files")


def test_run_cli_prints_help_and_exits_before_runtime(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            ["--help"],
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
        )
        assert exit_code == 0
        assert "Usage:" in stdout.getvalue()
        assert "--list-models-format text|json" in stdout.getvalue()
        assert "--list-sessions-format tsv|json" in stdout.getvalue()
        assert "--list-commands-format tsv|json" in stdout.getvalue()
        assert "--command-result-format raw|json" in stdout.getvalue()
        assert "--export-format html|jsonl" in stdout.getvalue()
        assert "--export-result-format text|json" in stdout.getvalue()
        assert stderr.getvalue() == ""
        assert not (tmp_path / ".loushang" / "sessions").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("argv", (["--mode", "json", "--help"], ["--mode", "print", "--help"]))
def test_run_cli_routes_non_interactive_help_to_stderr(argv, tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            argv,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
        )
        assert exit_code == 0
        assert stdout.getvalue() == ""
        assert "Usage:" in stderr.getvalue()
        assert "--mode" in stderr.getvalue()
        assert not (tmp_path / ".loushang" / "sessions").exists()

    asyncio.run(scenario())


def test_run_cli_routes_non_interactive_help_startup_stdout_to_stderr(tmp_path, monkeypatch) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    leaked_stdout = StringIO()
    monkeypatch.setattr(sys, "stdout", leaked_stdout)

    def runtime_builder(**kwargs):
        print("startup chatter")
        return runtime

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            ["--mode", "json", "--help"],
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0
        assert stdout.getvalue() == ""
        assert leaked_stdout.getvalue() == ""
        assert "startup chatter" in stderr.getvalue()
        assert "Usage:" in stderr.getvalue()

    asyncio.run(scenario())


def test_run_cli_routes_machine_readable_command_startup_stdout_to_stderr(tmp_path, monkeypatch) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"), records=[])
    leaked_stdout = StringIO()
    monkeypatch.setattr(sys, "stdout", leaked_stdout)

    def runtime_builder(**kwargs):
        print("startup chatter")
        return runtime

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            ["--list-sessions", "--list-sessions-format", "json"],
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0
        assert json.loads(stdout.getvalue()) == []
        assert leaked_stdout.getvalue() == ""
        assert "startup chatter" in stderr.getvalue()

    asyncio.run(scenario())


def test_run_cli_routes_print_mode_runtime_stdout_chatter_to_stderr(tmp_path, monkeypatch) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    leaked_stdout = StringIO()
    monkeypatch.setattr(sys, "stdout", leaked_stdout)

    def runtime_builder(**kwargs):
        return runtime

    async def print_runner(**kwargs):
        print("mode chatter")
        kwargs["stdout"].write('{"type":"result"}\n')
        return 0

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            ["--mode", "json", "hello"],
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
            print_runner=print_runner,
        )
        assert exit_code == 0
        assert stdout.getvalue() == '{"type":"result"}\n'
        assert leaked_stdout.getvalue() == ""
        assert "mode chatter" in stderr.getvalue()

    asyncio.run(scenario())


def test_run_cli_routes_machine_readable_command_runtime_stdout_chatter_to_stderr(tmp_path, monkeypatch) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class ChatteringRuntime(FakeRuntime):
        def list_sessions(self) -> list[object]:
            print("list chatter")
            return super().list_sessions()

    runtime = ChatteringRuntime(FakeSession("session-1"), records=[])
    leaked_stdout = StringIO()
    monkeypatch.setattr(sys, "stdout", leaked_stdout)

    def runtime_builder(**kwargs):
        return runtime

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            ["--list-sessions", "--list-sessions-format", "json"],
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0
        assert json.loads(stdout.getvalue()) == []
        assert leaked_stdout.getvalue() == ""
        assert "list chatter" in stderr.getvalue()

    asyncio.run(scenario())


def test_run_cli_prints_version_and_exits_before_runtime(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    async def scenario() -> None:
        stdout = StringIO()
        exit_code = await run_cli(
            ["-v"],
            stdin=StringIO(),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
        )
        assert exit_code == 0
        assert stdout.getvalue().strip() != ""

    asyncio.run(scenario())


def test_run_cli_reports_parse_errors_to_provided_stderr(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "invalid"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "invalid choice" in stderr.getvalue()


def test_run_cli_rejects_conflicting_tui_flags(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    stderr = StringIO()

    exit_code = asyncio.run(
        run_cli(
            ["--tui", "--no-tui"],
            stdin=TtyStringIO(),
            stdout=TtyStringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: pytest.fail("runtime should not be built"),
        )
    )

    assert exit_code == 2
    assert "--tui and --no-tui cannot be used together" in stderr.getvalue()


def test_main_uses_process_argv_when_argv_is_omitted(monkeypatch) -> None:
    from loushang.coding.cli.__main__ import main

    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "argv", ["loushang-coding", "--help"])
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    assert main() == 0
    assert "Usage:" in stdout.getvalue()
    assert "prompt is required" not in stderr.getvalue()


def test_cli_package_lazily_exports_main_and_run_cli() -> None:
    from loushang.coding import cli

    assert cli.main
    assert cli.run_cli


def test_loushang_tui_entrypoint_forces_tui(monkeypatch) -> None:
    from loushang.coding.ui import cli as tui_cli

    calls = []

    async def fake_run_cli(argv):
        calls.append(tuple(argv))
        return 23

    monkeypatch.setattr(sys, "argv", ["loushang-tui", "--resume", "abcd1234"])
    monkeypatch.setattr(tui_cli, "run_cli", fake_run_cli)

    with pytest.raises(SystemExit) as error:
        tui_cli.main()

    assert error.value.code == 23
    assert calls == [("--tui", "--resume", "abcd1234")]


def test_cli_main_handles_keyboard_interrupt(monkeypatch, capsys) -> None:
    from loushang.coding.cli import __main__ as cli_main

    async def interrupted(argv):
        del argv
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "run_cli", interrupted)

    assert cli_main.main([]) == 130
    assert capsys.readouterr().err == "Interrupted.\n"


def test_python_module_help_has_no_runpy_warning(tmp_path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = subprocess.run(
        [sys.executable, "-m", "loushang.coding.cli", "--help"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert result.stderr == ""
    assert not (tmp_path / ".loushang" / "sessions").exists()


def test_run_cli_exports_session_and_exits_early(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    export_path = str(tmp_path / "export.html")

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            ["--export", export_path],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0
        assert runtime.get_current_session().set_export_calls == [export_path]
        assert f"Exported to: {export_path}" in stdout.getvalue()
        assert stderr.getvalue() == ""

    asyncio.run(scenario())


def test_run_cli_diag_export_exits_before_runtime_creation(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    (session_dir / "latest.jsonl").write_text('{"type":"user","text":"hello"}\n', encoding="utf-8")
    debug_file = tmp_path / "debug.log"
    debug_file.write_text("debug line\n", encoding="utf-8")
    output = tmp_path / "diag.zip"
    stdout = StringIO()
    stderr = StringIO()

    def runtime_builder(**kwargs):
        raise AssertionError("diag export should not create a runtime")

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "diag",
                "export",
                "--output",
                str(output),
                "--session-dir",
                str(session_dir),
                "--debug-file",
                str(debug_file),
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(session_dir=str(session_dir)),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert output.exists()
    assert f"Exported diagnostics to: {output}" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_exports_session_to_default_path_when_path_is_omitted(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--export"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.set_export_calls == [None]
    assert "session-1.html" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_exports_session_to_jsonl_with_json_result(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    export_path = str(tmp_path / "export.jsonl")
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--export",
                export_path,
                "--export-format",
                "jsonl",
                "--export-result-format",
                "json",
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.set_export_calls == []
    assert session.set_jsonl_export_calls == [export_path]
    assert json.loads(stdout.getvalue()) == {"path": export_path, "format": "jsonl"}
    assert stderr.getvalue() == ""


def test_run_cli_reports_export_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenExportSession(FakeSession):
        def export_to_html(self, output_path: str | None = None) -> str:
            raise RuntimeError("export failed")

    runtime = FakeRuntime(BrokenExportSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--export"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "export failed" in stderr.getvalue()


def test_run_cli_reports_export_unexpected_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenExportSession(FakeSession):
        def export_to_html(self, output_path: str | None = None) -> str:
            raise TypeError("export type error")

    runtime = FakeRuntime(BrokenExportSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--export"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "export type error" in stderr.getvalue()


def test_run_cli_reports_export_method_not_available(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenExportSession(FakeSession):
        export_to_jsonl = None  # type: ignore[assignment]

    runtime = FakeRuntime(BrokenExportSession("session-1"))

    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--export", "--export-format", "jsonl"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1
    asyncio.run(scenario())

    assert "jsonl export is not available." in stderr.getvalue()


def test_run_cli_lists_sessions_without_creating_new_session(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    records = [
        SimpleNamespace(
            session_id="session-2",
            cwd="/tmp/project-b",
            session_file=Path("/tmp/session-2.jsonl"),
            parent_session="/tmp/session-1.jsonl",
            leaf_id="leaf-2",
            metadata=SimpleNamespace(
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                name="Second",
            ),
        ),
        SimpleNamespace(
            session_id="session-1",
            cwd="/tmp/project-a",
            session_file=Path("/tmp/session-1.jsonl"),
            parent_session=None,
            leaf_id=None,
            metadata=SimpleNamespace(
                created_at="2026-05-20T10:00:00Z",
                updated_at="2026-05-21T10:00:00Z",
                name=None,
            ),
        ),
    ]
    runtime = FakeRuntime(FakeSession("unused"), records=records)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.list_sessions_calls == 1
    assert runtime.new_session_calls == []
    assert stdout.getvalue() == (
        "session-2\t/tmp/session-2.jsonl\t/tmp/project-b\t2026-05-22T10:00:00Z\tSecond\n"
        "session-1\t/tmp/session-1.jsonl\t/tmp/project-a\t2026-05-21T10:00:00Z\t\n"
    )
    assert stderr.getvalue() == ""


def test_run_cli_lists_sessions_as_json_without_creating_new_session(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    records = [
        SimpleNamespace(
            session_id="session-2",
            cwd="/tmp/project-b",
            session_file=Path("/tmp/session-2.jsonl"),
            parent_session="/tmp/session-1.jsonl",
            leaf_id="leaf-2",
            metadata=SimpleNamespace(
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                name="Second",
            ),
            first_message="first prompt",
            all_messages_text="first prompt assistant answer",
        )
    ]
    runtime = FakeRuntime(FakeSession("unused"), records=records)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--list-sessions-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.list_sessions_calls == 1
    assert runtime.new_session_calls == []
    assert json.loads(stdout.getvalue()) == [
        {
            "session_id": "session-2",
            "cwd": "/tmp/project-b",
            "session_file": "/tmp/session-2.jsonl",
            "parent_session": "/tmp/session-1.jsonl",
            "leaf_id": "leaf-2",
            "metadata": {
                "created_at": "2026-05-21T10:00:00Z",
                "updated_at": "2026-05-22T10:00:00Z",
                "name": "Second",
            },
            "first_message": "first prompt",
            "all_messages_text": "first prompt assistant answer",
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_all_sessions_when_requested(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    records = [
        SimpleNamespace(
            session_id="session-global",
            cwd="/tmp/project-global",
            session_file=Path("/tmp/session-global.jsonl"),
            parent_session=None,
            leaf_id=None,
            created_at="2026-05-21T10:00:00Z",
            updated_at="2026-05-22T10:00:00Z",
            name="Global",
        )
    ]
    runtime = FakeRuntime(FakeSession("unused"), records=records)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--all-sessions", "--list-sessions-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.list_all_session_summaries_calls == 1
    assert runtime.list_sessions_calls == 0
    assert json.loads(stdout.getvalue())[0]["session_id"] == "session-global"
    assert stderr.getvalue() == ""


def test_run_cli_list_sessions_supports_query_filters(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.store import SessionQuery

    records = [
        SimpleNamespace(
            session_id="session-filtered",
            cwd="/tmp/project-filtered",
            session_file=Path("/tmp/session-filtered.jsonl"),
            parent_session="/tmp/parent.jsonl",
            leaf_id=None,
            created_at="2026-05-21T10:00:00Z",
            updated_at="2026-05-22T10:00:00Z",
            name="Filtered",
        )
    ]
    runtime = FakeRuntime(FakeSession("unused"), records=records)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--list-sessions",
                "--session-cwd",
                "/tmp/project-filtered",
                "--session-name-filter",
                "filter",
                "--session-parent",
                "/tmp/parent.jsonl",
                "--session-query",
                "needle",
                "--session-has-diagnostics",
                "--session-limit",
                "1",
                "--list-sessions-format",
                "json",
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.find_session_summaries_calls == [
        SessionQuery(
            cwd="/tmp/project-filtered",
            name="filter",
            parent_session="/tmp/parent.jsonl",
            text="needle",
            has_diagnostics=True,
            limit=1,
        )
    ]
    assert runtime.list_sessions_calls == 0
    assert json.loads(stdout.getvalue())[0]["session_id"] == "session-filtered"
    assert stderr.getvalue() == ""


def test_run_cli_list_sessions_supports_no_diagnostics_filter(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.store import SessionQuery

    runtime = FakeRuntime(FakeSession("unused"), records=[])
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--session-no-diagnostics"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.find_session_summaries_calls == [SessionQuery(has_diagnostics=False)]
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_run_cli_list_sessions_supports_all_sessions_with_query_filters(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.store import SessionQuery

    runtime = FakeRuntime(
        FakeSession("unused"),
        records=[
            SimpleNamespace(
                session_id="session-global-filtered",
                cwd="/tmp/project-global",
                session_file=Path("/tmp/session-global-filtered.jsonl"),
                parent_session=None,
                leaf_id=None,
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                name="Global",
            )
        ],
    )
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--list-sessions",
                "--all-sessions",
                "--session-query",
                "global",
                "--list-sessions-format",
                "json",
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.find_all_session_summaries_calls == [SessionQuery(text="global")]
    assert runtime.list_all_session_summaries_calls == 0
    assert json.loads(stdout.getvalue())[0]["session_id"] == "session-global-filtered"
    assert stderr.getvalue() == ""


def test_run_cli_list_sessions_can_use_session_index(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.store import SessionQuery

    runtime = FakeRuntime(
        FakeSession("unused"),
        records=[
            SimpleNamespace(
                session_id="session-indexed",
                cwd="/tmp/project-indexed",
                session_file=Path("/tmp/session-indexed.jsonl"),
                parent_session=None,
                leaf_id=None,
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                name="Indexed",
            )
        ],
    )
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--session-index", "--session-query", "indexed", "--list-sessions-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.find_indexed_session_summaries_calls == [SessionQuery(text="indexed")]
    assert runtime.find_session_summaries_calls == []
    assert json.loads(stdout.getvalue())[0]["session_id"] == "session-indexed"
    assert stderr.getvalue() == ""


def test_run_cli_list_sessions_can_refresh_all_session_indexes(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.store import SessionQuery

    runtime = FakeRuntime(FakeSession("unused"), records=[])
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--all-sessions", "--refresh-session-index", "--session-query", "global"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.refresh_all_session_indexes_calls == 1
    assert runtime.find_all_indexed_session_summaries_calls == [SessionQuery(text="global")]
    assert runtime.find_all_session_summaries_calls == []
    assert stderr.getvalue() == ""


def test_run_cli_list_sessions_rejects_invalid_session_limit(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("unused"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--session-limit", "-1"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "Session query limit must be non-negative" in stderr.getvalue()
    assert stdout.getvalue() == ""


def test_run_cli_prefers_session_summaries_for_listing(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class SummaryRuntime(FakeRuntime):
        def __init__(self, session: FakeSession, summaries: list[object]) -> None:
            super().__init__(session)
            self.session_summaries = list(summaries)
            self.list_session_summaries_calls = 0

        def list_session_summaries(self) -> list[object]:
            self.list_session_summaries_calls += 1
            return self.session_summaries

    runtime = SummaryRuntime(
        FakeSession("unused"),
        summaries=[
            SimpleNamespace(
                session_id="session-2",
                cwd="/tmp/project-b",
                session_file=Path("/tmp/session-2.jsonl"),
                parent_session="/tmp/session-1.jsonl",
                leaf_id="leaf-2",
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                name="Second",
                message_count=3,
                entry_count=5,
                last_message_preview="latest assistant message",
                model={"provider": "faux", "model_id": "alpha"},
            )
        ],
    )
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--list-sessions-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.list_session_summaries_calls == 1
    assert runtime.list_sessions_calls == 0
    assert json.loads(stdout.getvalue()) == [
        {
            "session_id": "session-2",
            "cwd": "/tmp/project-b",
            "session_file": "/tmp/session-2.jsonl",
            "parent_session": "/tmp/session-1.jsonl",
            "leaf_id": "leaf-2",
            "metadata": {
                "created_at": "2026-05-21T10:00:00Z",
                "updated_at": "2026-05-22T10:00:00Z",
                "name": "Second",
            },
            "message_count": 3,
            "entry_count": 5,
            "last_message_preview": "latest assistant message",
            "model": {"provider": "faux", "model_id": "alpha"},
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_reports_list_sessions_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenListSessionsRuntime(FakeRuntime):
        def list_sessions(self) -> list[object]:
            raise RuntimeError("session listing failed")

    runtime = BrokenListSessionsRuntime(FakeSession("unused"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "session listing failed" in stderr.getvalue()


def test_run_cli_reports_list_sessions_unexpected_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenListSessionsRuntime(FakeRuntime):
        def list_sessions(self) -> list[object]:
            raise TypeError("session listing type error")

    runtime = BrokenListSessionsRuntime(FakeSession("unused"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "session listing type error" in stderr.getvalue()


def test_run_cli_reports_list_sessions_invalid_payload(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenListSessionsRuntime(FakeRuntime):
        def list_sessions(self):
            return {"sessions": []}

    runtime = BrokenListSessionsRuntime(FakeSession("unused"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "session listing returned an invalid response." in stderr.getvalue()


def test_run_cli_skips_session_records_that_fail_normalization(tmp_path, monkeypatch) -> None:
    from loushang.coding.cli import __main__ as cli_main
    from loushang.coding.cli.__main__ import run_cli

    valid_record = SimpleNamespace(
        session_id="session-1",
        cwd="/tmp/project-a",
        session_file=Path("/tmp/session-1.jsonl"),
        parent_session=None,
        leaf_id=None,
        metadata=SimpleNamespace(
            created_at="2026-05-20T10:00:00Z",
            updated_at="2026-05-21T10:00:00Z",
            name="First",
        ),
    )

    original = cli_main._normalize_session_record

    def _broken_normalize_session_record(record: object) -> dict[str, object]:
        if record == "broken":
            raise RuntimeError("broken record")
        return original(record)

    monkeypatch.setattr(cli_main, "_normalize_session_record", _broken_normalize_session_record)

    runtime = FakeRuntime(FakeSession("unused"), records=["broken", valid_record])
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--list-sessions-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "session_id": "session-1",
            "cwd": "/tmp/project-a",
            "session_file": "/tmp/session-1.jsonl",
            "parent_session": None,
            "leaf_id": None,
            "metadata": {
                "created_at": "2026-05-20T10:00:00Z",
                "updated_at": "2026-05-21T10:00:00Z",
                "name": "First",
            },
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_reports_list_sessions_with_unprintable_fields(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("unprintable")

        def __repr__(self) -> str:
            return "/tmp/unprintable.jsonl"

    records = [
        SimpleNamespace(
            session_id="session-a",
            cwd=Unprintable(),
            session_file=Path("/tmp/session-a.jsonl"),
            parent_session=Unprintable(),
            leaf_id="leaf-a",
            metadata=SimpleNamespace(
                created_at=Unprintable(),
                updated_at=Unprintable(),
                name=Unprintable(),
            ),
        )
    ]
    runtime = FakeRuntime(FakeSession("unused"), records=records)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-sessions", "--list-sessions-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "session_id": "session-a",
            "cwd": "/tmp/unprintable.jsonl",
            "session_file": "/tmp/session-a.jsonl",
            "parent_session": "/tmp/unprintable.jsonl",
            "leaf_id": "leaf-a",
            "metadata": {
                "created_at": "/tmp/unprintable.jsonl",
                "updated_at": "/tmp/unprintable.jsonl",
                "name": "/tmp/unprintable.jsonl",
            },
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_dispatches_print_mode_with_restored_session_and_model_override(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.types import ModelSelection

    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    def runtime_builder(**kwargs):
        assert kwargs["session_dir"] == tmp_path / "sessions"
        return runtime

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--mode",
                "json",
                "--session",
                "session-1",
                "--provider",
                "faux",
                "--model",
                "beta",
                "hello",
                "world",
            ],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(str(tmp_path / "sessions")),
            runtime_builder=runtime_builder,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.restore_session_calls == ["session-1"]
    assert runtime.get_current_session().set_model_calls == [ModelSelection(provider="faux", model_id="beta")]
    assert print_runner.calls[0]["user_input"] == "hello world"
    assert print_runner.calls[0]["follow_up_messages"] == ()
    assert print_runner.calls[0]["output_mode"] == "json"
    assert print_runner.calls[0]["session"] is runtime.get_current_session()


def test_run_cli_dash_p_dispatches_prompt_command(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()
    mode_runner = FakeRunner()
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-p", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
            mode_runner=mode_runner,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert len(prompt_runner.calls) == 1
    assert prompt_runner.calls[0]["prompt"] == "hello"
    assert prompt_runner.calls[0]["session"] is runtime.get_current_session()
    assert mode_runner.calls == []
    assert print_runner.calls == []


def test_run_cli_dash_p_with_method_prepares_prompt_and_method_id(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--method", "review", "-p", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = prompt_runner.calls[0]
    assert call["method_id"] == "method:task:review"
    assert "Use concise review guidance." in call["prompt"]
    assert call["prompt"].endswith("User request:\n\ncheck src/app.py")


def test_run_cli_dash_p_with_fixed_method_executes_each_step(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_fixed_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--method", "review", "-p", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert len(prompt_runner.calls) == 2
    first_call = prompt_runner.calls[0]
    second_call = prompt_runner.calls[1]
    assert first_call["method_id"] == "method:task:review"
    assert first_call["plan_id"] == "plan:method:task:review"
    assert first_call["step_id"] == "inspect"
    assert first_call["step_index"] == 0
    assert first_call["step_title"] == "Inspect current changes"
    assert "Read changed files and summarize intent." in first_call["prompt"]
    assert first_call["prompt"].endswith("User request:\n\ncheck src/app.py")
    assert second_call["method_id"] == "method:task:review"
    assert second_call["plan_id"] == "plan:method:task:review"
    assert second_call["step_id"] == "verify"
    assert second_call["step_index"] == 1
    assert second_call["step_title"] == "Run focused checks"
    assert "Run focused tests or explain why they cannot run." in second_call["prompt"]
    assert second_call["prompt"].endswith("User request:\n\ncheck src/app.py")


def test_run_cli_dash_p_with_no_method_suppresses_method(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--no-method", "-p", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = prompt_runner.calls[0]
    assert call["prompt"] == "check src/app.py"
    assert call["method_id"] is None


def test_run_cli_dash_p_uses_method_default_from_settings(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import MethodSettings

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-p", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(
                method_settings=MethodSettings(mode="explicit", selected_method="review"),
            ),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = prompt_runner.calls[0]
    assert call["method_id"] == "method:task:review"
    assert "Use concise review guidance." in call["prompt"]
    assert call["prompt"].endswith("User request:\n\ncheck src/app.py")


def test_run_cli_dash_p_method_flag_overrides_method_default_from_settings(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import MethodSettings

    _write_review_method(tmp_path)
    _write_debug_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--method", "debug", "-p", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(
                method_settings=MethodSettings(mode="explicit", selected_method="review"),
            ),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = prompt_runner.calls[0]
    assert call["method_id"] == "method:task:debug"
    assert "Use focused debugging guidance." in call["prompt"]
    assert "Use concise review guidance." not in call["prompt"]


def test_run_cli_dash_p_no_method_overrides_method_default_from_settings(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import MethodSettings

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--no-method", "-p", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(
                method_settings=MethodSettings(mode="explicit", selected_method="review"),
            ),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = prompt_runner.calls[0]
    assert call["prompt"] == "check src/app.py"
    assert call["method_id"] is None


def test_run_cli_dash_p_method_off_default_suppresses_method(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import MethodSettings

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-p", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(
                method_settings=MethodSettings(mode="off", selected_method="review"),
            ),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = prompt_runner.calls[0]
    assert call["prompt"] == "check src/app.py"
    assert call["method_id"] is None


def test_run_cli_rejects_method_and_no_method_conflict(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--method", "review", "--no-method", "-p", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert prompt_runner.calls == []
    assert "--method cannot be used with --no-method" in stderr.getvalue()


def test_run_cli_dash_p_with_missing_method_reports_error(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--method", "missing", "-p", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert prompt_runner.calls == []
    assert "method not found: missing" in stderr.getvalue()
    assert "Run 'loushang method list' to inspect available methods." in stderr.getvalue()


def test_run_cli_dash_p_with_missing_method_default_reports_error(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import MethodSettings

    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-p", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(
                method_settings=MethodSettings(mode="explicit", selected_method="missing"),
            ),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert prompt_runner.calls == []
    assert "method not found: missing" in stderr.getvalue()
    assert "Run 'loushang method list' to inspect available methods." in stderr.getvalue()


def test_run_cli_dash_p_with_unsupported_method_default_mode_reports_error(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import MethodSettings

    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()
    prompt_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-p", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(
                method_settings=MethodSettings(mode="auto", selected_method=None),
            ),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert prompt_runner.calls == []
    assert "unsupported method policy mode: auto" in stderr.getvalue()


def test_run_cli_dash_p_passes_work_log_backend_to_prompt_command(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    runtime = FakeRuntime(FakeSession("session-1"))
    prompt_runner = FakeRunner()
    work_log_path = tmp_path / "prompt-work.jsonl"

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--work-log", str(work_log_path), "-p", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            prompt_runner=prompt_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    event_log = prompt_runner.calls[0]["work_event_log"]
    assert isinstance(event_log, JsonlEventLogBackend)
    assert _append_work_log_marker(event_log) == work_log_path
    assert work_log_path.exists()


def test_run_cli_dash_ps_dispatches_prompt_steps_workflow(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text('{"steps": [{"prompt": "hello"}]}', encoding="utf-8")
    runtime = FakeRuntime(FakeSession("session-1"))
    workflow_runner = FakeRunner()
    prompt_runner = FakeRunner()
    mode_runner = FakeRunner()
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "print", "-ps", str(workflow_file)],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            workflow_runner=workflow_runner,
            prompt_runner=prompt_runner,
            mode_runner=mode_runner,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert len(workflow_runner.calls) == 1
    assert workflow_runner.calls[0]["workflow_path"] == workflow_file
    assert workflow_runner.calls[0]["session"] is runtime.get_current_session()
    assert workflow_runner.calls[0]["cwd"] == tmp_path
    assert prompt_runner.calls == []
    assert mode_runner.calls == []
    assert print_runner.calls == []


def test_run_cli_dash_ps_runs_fake_workflow_backend(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
name: fake cli
backend: fake
steps:
  - prompt: active task
    hold: true
  - abort: {}
  - prompt: 你好
  - expect:
      events:
        - event: assistant.message
          contains: 你好
""".lstrip(),
        encoding="utf-8",
    )
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-ps", str(workflow_file)],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert "workflow: fake cli\n" in stdout.getvalue()
    assert "PASS\n" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_fake_prompt_steps_skips_runtime_bootstrap(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
name: fake cli without runtime
backend: fake
steps:
  - prompt: 你好
  - expect:
      events:
        - event: assistant.message
          contains: 你好
""".lstrip(),
        encoding="utf-8",
    )
    stdout = StringIO()
    stderr = StringIO()

    def runtime_builder(**kwargs):
        raise AssertionError("fake workflow should not build a runtime")

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-ps", str(workflow_file)],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert "workflow: fake cli without runtime\n" in stdout.getvalue()
    assert "PASS\n" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_fake_prompt_steps_directory_skips_runtime_bootstrap(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "01-one.workflow.yaml").write_text(
        """
name: one
backend: fake
steps:
  - prompt: 你好
""".lstrip(),
        encoding="utf-8",
    )
    (workflows_dir / "02-two.workflow.yaml").write_text(
        """
name: two
backend: fake
steps:
  - prompt: 再见
""".lstrip(),
        encoding="utf-8",
    )
    stdout = StringIO()
    stderr = StringIO()

    def runtime_builder(**kwargs):
        raise AssertionError("fake workflow directory should not build a runtime")

    async def scenario() -> None:
        exit_code = await run_cli(
            ["-ps", str(workflows_dir)],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert "workflow: one\n" in stdout.getvalue()
    assert "workflow: two\n" in stdout.getvalue()
    assert "workflow summary: 2 passed, 0 failed\n" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_fake_prompt_steps_json_mode_outputs_json_without_runtime(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "01-one.workflow.yaml").write_text(
        """
name: one
backend: fake
steps:
  - prompt: 你好
""".lstrip(),
        encoding="utf-8",
    )
    stdout = StringIO()
    stderr = StringIO()

    def runtime_builder(**kwargs):
        raise AssertionError("fake workflow json mode should not build a runtime")

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "json", "-ps", str(workflows_dir)],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is True
    assert payload["workflows"][0]["name"] == "one"
    assert "workflow: one" not in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_mode_print_dispatches_print_adapter(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "print", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert len(print_runner.calls) == 1
    assert print_runner.calls[0]["user_input"] == "hello"
    assert print_runner.calls[0]["output_mode"] == "text"


def test_run_cli_mode_print_with_method_prepares_prompt_and_method_id(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--method", "review", "--mode", "print", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = print_runner.calls[0]
    assert call["method_id"] == "method:task:review"
    assert "Use concise review guidance." in call["user_input"]
    assert call["user_input"].endswith("User request:\n\ncheck src/app.py")
    assert call["output_mode"] == "text"


def test_run_cli_mode_print_with_fixed_method_executes_each_step(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_fixed_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--method", "review", "--mode", "print", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert len(print_runner.calls) == 2
    first_call = print_runner.calls[0]
    second_call = print_runner.calls[1]
    assert first_call["method_id"] == "method:task:review"
    assert first_call["plan_id"] == "plan:method:task:review"
    assert first_call["step_id"] == "inspect"
    assert first_call["step_index"] == 0
    assert first_call["step_title"] == "Inspect current changes"
    assert "Read changed files and summarize intent." in first_call["user_input"]
    assert first_call["user_input"].endswith("User request:\n\ncheck src/app.py")
    assert first_call["output_mode"] == "text"
    assert second_call["method_id"] == "method:task:review"
    assert second_call["plan_id"] == "plan:method:task:review"
    assert second_call["step_id"] == "verify"
    assert second_call["step_index"] == 1
    assert second_call["step_title"] == "Run focused checks"
    assert "Run focused tests or explain why they cannot run." in second_call["user_input"]
    assert second_call["user_input"].endswith("User request:\n\ncheck src/app.py")
    assert second_call["output_mode"] == "text"


def test_run_cli_mode_print_uses_method_default_from_settings(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import MethodSettings

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "print", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(
                method_settings=MethodSettings(mode="explicit", selected_method="review"),
            ),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = print_runner.calls[0]
    assert call["method_id"] == "method:task:review"
    assert "Use concise review guidance." in call["user_input"]
    assert call["user_input"].endswith("User request:\n\ncheck src/app.py")
    assert call["output_mode"] == "text"


def test_run_cli_mode_print_passes_work_log_backend_to_print_adapter(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()
    work_log_path = tmp_path / "logs" / "work-events.jsonl"

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "print", "--work-log", "logs/work-events.jsonl", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    event_log = print_runner.calls[0]["work_event_log"]
    assert isinstance(event_log, JsonlEventLogBackend)
    assert _append_work_log_marker(event_log) == work_log_path
    assert work_log_path.exists()


def test_run_cli_builds_initial_prompt_from_at_file_and_text(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    notes = tmp_path / "notes.txt"
    notes.write_text("important context", encoding="utf-8")
    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            [f"@{notes.name}", "summarize"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    user_input = print_runner.calls[0]["user_input"]
    assert isinstance(user_input, str)
    assert f'<file name="{notes.resolve()}">' in user_input
    assert "important context" in user_input
    assert user_input.endswith("summarize")
    assert print_runner.calls[0]["images"] is None


def test_run_cli_at_file_uses_read_path_normalization(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    real_name = "Screenshot 2026-05-09 at 1.23.45\u202fPM.txt"
    typed_name = "Screenshot 2026-05-09 at 1.23.45 PM.txt"
    notes = tmp_path / real_name
    notes.write_text("normalized path content", encoding="utf-8")
    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            [f"@{typed_name}", "summarize"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    user_input = print_runner.calls[0]["user_input"]
    assert isinstance(user_input, str)
    assert f'<file name="{notes.resolve()}">' in user_input
    assert "normalized path content" in user_input


def test_run_cli_passes_at_image_to_initial_prompt(tmp_path) -> None:
    import base64

    from loushang.coding.cli.__main__ import run_cli

    image_path = tmp_path / "pixel.png"
    image_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
    )
    image_path.write_bytes(image_bytes)
    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            [f"@{image_path.name}", "describe"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    images = print_runner.calls[0]["images"]
    assert len(images) == 1
    assert images[0].mime_type == "image/png"
    assert images[0].data == base64.b64encode(image_bytes).decode("ascii")
    assert f'<file name="{image_path.resolve()}"></file>' in print_runner.calls[0]["user_input"]


def test_run_cli_resizes_large_at_image_and_adds_dimension_note(tmp_path) -> None:
    import base64
    from io import BytesIO

    from PIL import Image

    from loushang.coding.cli.__main__ import run_cli

    image_path = tmp_path / "wide.png"
    image = Image.new("RGB", (2100, 10), color=(255, 0, 0))
    original_buffer = BytesIO()
    image.save(original_buffer, format="PNG")
    original_bytes = original_buffer.getvalue()
    image_path.write_bytes(original_bytes)
    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            [f"@{image_path.name}", "describe"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    images = print_runner.calls[0]["images"]
    assert len(images) == 1
    assert images[0].data != base64.b64encode(original_bytes).decode("ascii")
    user_input = print_runner.calls[0]["user_input"]
    assert isinstance(user_input, str)
    assert f'<file name="{image_path.resolve()}">[Image: original 2100x10, displayed at ' in user_input
    assert "Multiply coordinates" in user_input


def test_run_cli_passes_explicit_message_prompts_as_follow_ups(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["hello", "--message", "next", "--message", "final"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert print_runner.calls[0]["user_input"] == "hello"
    assert print_runner.calls[0]["follow_up_messages"] == ("next", "final")


def test_run_cli_applies_session_name_override(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--session-name", "Demo Session", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.set_session_name_calls == ["Demo Session"]
    assert session.session_name == "Demo Session"
    assert print_runner.calls[0]["session"] is session


def test_run_cli_reports_incomplete_model_selection(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--model", "alpha", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "Model selection requires" in stderr.getvalue()


def test_run_cli_reports_model_apply_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenModelSession(FakeSession):
        async def set_model(self, selection) -> None:
            raise RuntimeError("model not available")

    runtime = FakeRuntime(BrokenModelSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--provider", "faux", "--model", "missing", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "model not available" in stderr.getvalue()


def test_run_cli_reports_second_pass_parse_errors_to_provided_stderr(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands-format", "xml", "--list-commands"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "invalid choice" in stderr.getvalue()


def test_run_cli_dispatches_continue_by_restoring_latest_session(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    latest = Path(tmp_path / ".loushang" / "sessions" / "latest.jsonl")
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.touch()
    runtime = FakeRuntime(
        FakeSession("session-1"),
        records=[SimpleNamespace(session_file=latest)],
    )
    print_runner = FakeRunner()

    def runtime_builder(**kwargs):
        return runtime

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--continue", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.list_sessions_calls == 1
    assert runtime.restore_session_calls == [str(latest)]
    assert print_runner.calls[0]["user_input"] == "hello"


@pytest.mark.parametrize("resume_flag", ["--continue", "--resume"])
def test_run_cli_dispatches_restore_by_latest_session_for_resume_mode(tmp_path, resume_flag) -> None:
    from loushang.coding.cli.__main__ import run_cli

    latest = Path(tmp_path / ".loushang" / "sessions" / "latest.jsonl")
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.touch()
    runtime = FakeRuntime(
        FakeSession("session-1"),
        records=[SimpleNamespace(session_file=latest)],
    )
    print_runner = FakeRunner()

    def runtime_builder(**kwargs):
        return runtime

    async def scenario() -> None:
        exit_code = await run_cli(
            [resume_flag, "hello"] if resume_flag == "--continue" else [resume_flag, "--message", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.list_sessions_calls == 1
    assert runtime.restore_session_calls == [str(latest)]
    assert print_runner.calls[0]["user_input"] == "hello"


def test_run_cli_dispatches_restore_by_resume_session_reference(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    def runtime_builder(**kwargs):
        return runtime

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--resume", "abcd1234", "--message", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.list_sessions_calls == 0
    assert runtime.restore_session_calls == ["abcd1234"]
    assert print_runner.calls[0]["user_input"] == "hello"


def test_run_cli_reports_continue_without_existing_sessions(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"), records=[])
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--continue", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "No existing session found" in stderr.getvalue()


@pytest.mark.parametrize("resume_flag", ["--continue", "--resume"])
def test_run_cli_reports_restore_errors_when_list_sessions_fails(tmp_path, resume_flag) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenListSessionsRuntime(FakeRuntime):
        def list_sessions(self):
            raise RuntimeError("session listing failed")

    runtime = BrokenListSessionsRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [resume_flag, "hello"] if resume_flag == "--continue" else [resume_flag, "--message", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "session listing failed" in stderr.getvalue()


@pytest.mark.parametrize("resume_flag", ["--continue", "--resume"])
def test_run_cli_reports_restore_invalid_list_sessions_payload(tmp_path, resume_flag) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenListSessionsRuntime(FakeRuntime):
        def list_sessions(self):
            return {"sessions": []}

    runtime = BrokenListSessionsRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [resume_flag, "hello"] if resume_flag == "--continue" else [resume_flag, "--message", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "session listing returned an invalid response." in stderr.getvalue()


def test_run_cli_reports_continue_errors_when_list_sessions_fails(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenListSessionsRuntime(FakeRuntime):
        def list_sessions(self):
            raise RuntimeError("session listing failed")

    runtime = BrokenListSessionsRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--continue", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "session listing failed" in stderr.getvalue()


def test_run_cli_reports_continue_invalid_list_sessions_payload(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenListSessionsRuntime(FakeRuntime):
        def list_sessions(self):
            return {"sessions": []}

    runtime = BrokenListSessionsRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--continue", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "session listing returned an invalid response." in stderr.getvalue()


def test_run_cli_reports_missing_session_restore(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class MissingSessionRuntime(FakeRuntime):
        async def restore_session(self, session_id: str) -> FakeSession:
            self.restore_session_calls.append(session_id)
            raise FileNotFoundError(2, "No such file or directory", session_id)

    runtime = MissingSessionRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--session", "missing-session", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert runtime.restore_session_calls == ["missing-session"]
    assert "No such file or directory" in stderr.getvalue()


def test_run_cli_reports_missing_cwd_from_runtime(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class MissingCwdRuntime(FakeRuntime):
        async def new_session(self, *, cwd: str) -> FakeSession:
            self.new_session_calls.append(cwd)
            raise FileNotFoundError(2, "No such file or directory", cwd)

    runtime = MissingCwdRuntime(FakeSession("session-1"))
    missing_cwd = tmp_path / "missing"
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=missing_cwd,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "No such file or directory" in stderr.getvalue()
    assert str(missing_cwd.resolve()) in stderr.getvalue()


def test_run_cli_dispatches_rpc_mode_and_creates_new_session(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    rpc_runner = FakeRunner()

    def runtime_builder(**kwargs):
        assert kwargs["session_dir"] == tmp_path / ".loushang" / "sessions"
        return runtime

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "rpc"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
            rpc_runner=rpc_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.new_session_calls == [str(tmp_path.resolve())]
    assert rpc_runner.calls[0]["runtime"] is runtime


def test_run_cli_default_path_uses_unified_mode_runner(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    mode_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "json", "--render-tool-events", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            mode_runner=mode_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert mode_runner.calls[0]["config"].mode == "json"
    assert mode_runner.calls[0]["config"].render_tool_events is True
    assert mode_runner.calls[0]["runtime"] is runtime
    assert mode_runner.calls[0]["session"] is runtime.get_current_session()
    assert mode_runner.calls[0]["user_input"] == "hello"


def test_run_cli_default_path_with_method_prepares_prompt_and_method_id(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    mode_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "json", "--method", "review", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            mode_runner=mode_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    call = mode_runner.calls[0]
    assert call["method_id"] == "method:task:review"
    assert "Use concise review guidance." in call["user_input"]
    assert call["user_input"].endswith("User request:\n\ncheck src/app.py")


def test_run_cli_default_path_with_fixed_method_executes_each_step(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_fixed_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    mode_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "json", "--method", "review", "check src/app.py"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            mode_runner=mode_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert len(mode_runner.calls) == 2
    first_call = mode_runner.calls[0]
    second_call = mode_runner.calls[1]
    assert first_call["config"].mode == "json"
    assert first_call["method_id"] == "method:task:review"
    assert first_call["plan_id"] == "plan:method:task:review"
    assert first_call["step_id"] == "inspect"
    assert first_call["step_index"] == 0
    assert "Read changed files and summarize intent." in first_call["user_input"]
    assert first_call["user_input"].endswith("User request:\n\ncheck src/app.py")
    assert second_call["config"].mode == "json"
    assert second_call["method_id"] == "method:task:review"
    assert second_call["plan_id"] == "plan:method:task:review"
    assert second_call["step_id"] == "verify"
    assert second_call["step_index"] == 1
    assert "Run focused tests or explain why they cannot run." in second_call["user_input"]
    assert second_call["user_input"].endswith("User request:\n\ncheck src/app.py")


def test_run_cli_default_path_passes_work_log_backend_to_unified_mode_runner(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    runtime = FakeRuntime(FakeSession("session-1"))
    mode_runner = FakeRunner()
    work_log_path = tmp_path / "events.jsonl"

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "json", "--work-log", str(work_log_path), "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            mode_runner=mode_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    event_log = mode_runner.calls[0]["work_event_log"]
    assert isinstance(event_log, JsonlEventLogBackend)
    assert _append_work_log_marker(event_log) == work_log_path
    assert work_log_path.exists()


def test_run_cli_work_log_inspect_outputs_text_without_runtime(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "events.jsonl"
    event_log = JsonlEventLogBackend(log_path)
    _append_work_log_inspect_entry(
        event_log,
        sequence=1,
        kind="SubmitCodingTurn",
        entry_type="operation",
    )
    _append_work_log_inspect_entry(
        event_log,
        sequence=2,
        kind="ContentDelta",
        delivery_hint="coalesce",
    )
    stdout = StringIO()
    stderr = StringIO()

    def runtime_builder(**kwargs):
        raise AssertionError("work log inspect should not build a runtime")

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--work-log-inspect", str(log_path)],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue().splitlines() == [
        "sequence\tkind\trun_id\tsession_id\tdelivery_hint\tmethod_id",
        "1\tSubmitCodingTurn\trun-1\tsession-1\t\t",
        "2\tContentDelta\trun-1\tsession-1\tcoalesce\t",
    ]
    assert stderr.getvalue() == ""


def test_run_cli_work_log_inspect_text_includes_method_id(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "events.jsonl"
    event_log = JsonlEventLogBackend(log_path)
    _append_work_log_inspect_entry(
        event_log,
        sequence=1,
        kind="SubmitCodingTurn",
        entry_type="operation",
        method_id="method:task:review",
    )
    _append_work_log_inspect_entry(
        event_log,
        sequence=2,
        kind="WorkRunStarted",
        delivery_hint="immediate",
        method_id="method:task:review",
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--work-log-inspect", str(log_path)],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: (_ for _ in ()).throw(AssertionError("runtime should not start")),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue().splitlines() == [
        "sequence\tkind\trun_id\tsession_id\tdelivery_hint\tmethod_id",
        "1\tSubmitCodingTurn\trun-1\tsession-1\t\tmethod:task:review",
        "2\tWorkRunStarted\trun-1\tsession-1\timmediate\tmethod:task:review",
    ]


def test_run_cli_work_log_inspect_outputs_json_without_runtime(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "events.jsonl"
    event_log = JsonlEventLogBackend(log_path)
    _append_work_log_inspect_entry(
        event_log,
        sequence=3,
        kind="TurnCompleted",
        delivery_hint="immediate",
    )
    stdout = StringIO()

    def runtime_builder(**kwargs):
        raise AssertionError("work log inspect should not build a runtime")

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--work-log-inspect", str(log_path), "--work-log-inspect-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=runtime_builder,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "entry_id": "entry-3",
            "entry_type": "event",
            "sequence": 3,
            "kind": "TurnCompleted",
            "run_id": "run-1",
            "session_id": "session-1",
            "operation_id": "operation-run-1",
            "event_id": "event-3",
            "delivery_hint": "immediate",
        }
    ]


def test_run_cli_work_log_inspect_json_includes_method_id_when_present(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "events.jsonl"
    event_log = JsonlEventLogBackend(log_path)
    _append_work_log_inspect_entry(
        event_log,
        sequence=3,
        kind="WorkRunCompleted",
        delivery_hint="immediate",
        method_id="method:task:review",
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--work-log-inspect", str(log_path), "--work-log-inspect-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: (_ for _ in ()).throw(AssertionError("runtime should not start")),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue())[0]["method_id"] == "method:task:review"


def test_run_cli_work_log_inspect_filters_by_run(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "events.jsonl"
    event_log = JsonlEventLogBackend(log_path)
    _append_work_log_inspect_entry(event_log, sequence=1, kind="ContentDelta", run_id="run-1")
    _append_work_log_inspect_entry(event_log, sequence=2, kind="ApprovalRequested", run_id="run-2", delivery_hint="immediate")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--work-log-inspect", str(log_path), "--work-log-run", "run-2"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: (_ for _ in ()).throw(AssertionError("runtime should not start")),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue().splitlines() == [
        "sequence\tkind\trun_id\tsession_id\tdelivery_hint\tmethod_id",
        "2\tApprovalRequested\trun-2\tsession-1\timmediate\t",
    ]


def test_run_cli_default_rpc_path_uses_unified_mode_runner(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    mode_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "rpc"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            mode_runner=mode_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert mode_runner.calls[0]["config"].mode == "rpc"
    assert mode_runner.calls[0]["runtime"] is runtime
    assert mode_runner.calls[0]["session"] is runtime.get_current_session()
    assert mode_runner.calls[0]["user_input"] is None


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--tui", "--work-log", "events.jsonl"], "--work-log is not supported in TUI mode"),
        (["--mode", "rpc", "--work-log", "events.jsonl"], "--work-log is not supported in RPC mode"),
        (["--work-log", "events.jsonl", "--prompt-steps", "workflow.json"], "--work-log is not supported with --prompt-steps"),
    ],
)
def test_run_cli_rejects_work_log_on_unsupported_paths(tmp_path, argv, message) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            argv,
            stdin=TtyStringIO(""),
            stdout=TtyStringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            mode_runner=FakeRunner(),
            prompt_runner=FakeRunner(),
            rpc_runner=FakeRunner(),
            tui_runner=FakeRunner(),
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert message in stderr.getvalue()


@pytest.mark.parametrize(
    ("argv", "stdin", "stdout"),
    [
        (["--method", "review", "--mode", "rpc"], StringIO(""), StringIO()),
        (["--method", "review", "--tui"], TtyStringIO(""), TtyStringIO()),
    ],
)
def test_run_cli_rejects_method_on_unsupported_interactive_paths(tmp_path, argv, stdin, stdout) -> None:
    from loushang.coding.cli.__main__ import run_cli

    _write_review_method(tmp_path)
    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()
    prompt_runner = FakeRunner()
    mode_runner = FakeRunner()
    rpc_runner = FakeRunner()
    tui_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            argv,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            mode_runner=mode_runner,
            prompt_runner=prompt_runner,
            rpc_runner=rpc_runner,
            tui_runner=tui_runner,
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert "--method is not supported" in stderr.getvalue()
    assert prompt_runner.calls == []
    assert mode_runner.calls == []
    assert rpc_runner.calls == []
    assert tui_runner.calls == []


def test_run_cli_dispatches_tui_mode(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    tui_runner = FakeRunner()
    stdout = StringIO()
    stderr = StringIO()

    exit_code = asyncio.run(
        run_cli(
            ["--tui", "--verbose"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
        )
    )

    assert exit_code == 0
    assert len(tui_runner.calls) == 1
    assert tui_runner.calls[0]["runtime"] is runtime
    assert tui_runner.calls[0]["session"] is runtime.get_current_session()
    assert tui_runner.calls[0]["stdout"] is stdout
    assert tui_runner.calls[0]["stderr"] is stderr
    assert tui_runner.calls[0]["verbose"] is True


def test_run_cli_defaults_to_tui_for_interactive_bare_startup(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    tui_runner = FakeRunner()
    print_runner = FakeRunner()
    stdout = TtyStringIO()
    stderr = StringIO()

    exit_code = asyncio.run(
        run_cli(
            [],
            stdin=TtyStringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
            print_runner=print_runner,
        )
    )

    assert exit_code == 0
    assert len(tui_runner.calls) == 1
    assert tui_runner.calls[0]["runtime"] is runtime
    assert tui_runner.calls[0]["session"] is runtime.get_current_session()
    assert print_runner.calls == []
    assert "prompt is required" not in stderr.getvalue()


@pytest.mark.parametrize(
    ("argv", "expected_restore"),
    [
        (["--resume", "abcd1234"], "abcd1234"),
        (["--resume"], "/tmp/latest-session.jsonl"),
        (["--continue"], "/tmp/latest-session.jsonl"),
    ],
)
def test_run_cli_defaults_to_tui_for_interactive_resume_flows(tmp_path, argv, expected_restore) -> None:
    from loushang.coding.cli.__main__ import run_cli

    latest_session = SimpleNamespace(session_file=Path("/tmp/latest-session.jsonl"))
    runtime = FakeRuntime(FakeSession("session-1"), records=[latest_session])
    tui_runner = FakeRunner()
    print_runner = FakeRunner()

    exit_code = asyncio.run(
        run_cli(
            argv,
            stdin=TtyStringIO(),
            stdout=TtyStringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
            print_runner=print_runner,
        )
    )

    assert exit_code == 0
    assert runtime.restore_session_calls == [expected_restore]
    assert len(tui_runner.calls) == 1
    assert print_runner.calls == []


def test_run_cli_no_tui_keeps_interactive_bare_startup_in_text_mode(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    stderr = StringIO()

    exit_code = asyncio.run(
        run_cli(
            ["--no-tui"],
            stdin=TtyStringIO(),
            stdout=TtyStringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
            tui_runner=FakeRunner(),
        )
    )

    assert exit_code == 2
    assert "prompt is required" in stderr.getvalue()


def test_run_cli_keeps_interactive_positional_prompt_out_of_default_tui(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    tui_runner = FakeRunner()
    print_runner = FakeRunner()

    exit_code = asyncio.run(
        run_cli(
            ["hello", "world"],
            stdin=TtyStringIO(),
            stdout=TtyStringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
            print_runner=print_runner,
        )
    )

    assert exit_code == 0
    assert tui_runner.calls == []
    assert print_runner.calls[0]["user_input"] == "hello world"


def test_run_cli_keeps_piped_stdin_out_of_default_tui(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    tui_runner = FakeRunner()
    print_runner = FakeRunner()

    exit_code = asyncio.run(
        run_cli(
            [],
            stdin=StringIO("hello from pipe\n"),
            stdout=TtyStringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
            print_runner=print_runner,
        )
    )

    assert exit_code == 0
    assert tui_runner.calls == []
    assert print_runner.calls[0]["user_input"] == "hello from pipe"


def test_run_cli_keeps_machine_readable_mode_out_of_default_tui(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    tui_runner = FakeRunner()
    print_runner = FakeRunner()

    exit_code = asyncio.run(
        run_cli(
            ["--mode", "json", "hello"],
            stdin=TtyStringIO(),
            stdout=TtyStringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
            print_runner=print_runner,
        )
    )

    assert exit_code == 0
    assert tui_runner.calls == []
    assert print_runner.calls[0]["output_mode"] == "json"


def test_run_cli_keeps_list_commands_out_of_default_tui(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.set_commands([{"name": "review", "description": "Run review"}])
    runtime = FakeRuntime(session)
    tui_runner = FakeRunner()
    stdout = TtyStringIO()

    exit_code = asyncio.run(
        run_cli(
            ["--list-commands"],
            stdin=TtyStringIO(),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
        )
    )

    assert exit_code == 0
    assert tui_runner.calls == []
    assert "review" in stdout.getvalue()


def test_run_cli_configures_observability_for_tui_debug_trace(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.observability import get_log, reset_observability

    reset_observability()
    runtime = FakeRuntime(FakeSession("session-1"))
    debug_path = tmp_path / "debug.log"
    trace_path = tmp_path / "trace.jsonl"

    class EmittingRunner(FakeRunner):
        async def __call__(self, **kwargs):
            self.calls.append(kwargs)
            get_log("loushang.tests.cli").debug_event("tui", "cli.runner", ok=True)
            return self.exit_code

    tui_runner = EmittingRunner()

    exit_code = asyncio.run(
        run_cli(
            [
                "--tui",
                "--debug=tui",
                "--debug-file",
                str(debug_path),
                "--trace=tui",
                "--trace-file",
                str(trace_path),
            ],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            tui_runner=tui_runner,
        )
    )

    reset_observability()
    assert exit_code == 0
    assert "DEBUG_EVENT tui cli.runner" in debug_path.read_text(encoding="utf-8")

    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["kind"] == "debug_event"
    assert record["scope"] == "tui"
    assert record["name"] == "cli.runner"
    assert record["session_id"] == "session-1"
    assert record["cwd"] == str(tmp_path.resolve())
    assert record["mode"] == "tui"
    assert record["data"] == {"ok": True}


def test_run_cli_rejects_at_file_args_in_rpc_mode(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    (tmp_path / "notes.txt").write_text("context", encoding="utf-8")
    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "rpc", "@notes.txt"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            rpc_runner=FakeRunner(),
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert "@file arguments are not supported in RPC mode" in stderr.getvalue()


def test_run_cli_uses_piped_stdin_when_prompt_is_missing(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            [],
            stdin=StringIO("prompt from stdin"),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert print_runner.calls[0]["user_input"] == "prompt from stdin"
    assert print_runner.calls[0]["output_mode"] == "text"


def test_run_cli_lists_models_and_returns_early(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class ModelSession(FakeSession):
        def get_available_models(self):
            self.get_available_models_calls += 1
            return [
                type("ModelSelection", (), {"provider": "anthropic", "model_id": "claude-3-opus"}),
                type("ModelSelection", (), {"provider": "google", "model_id": "gemini-2.0"}),
                type("ModelSelection", (), {"provider": "anthropic", "model_id": "claude-3-haiku"}),
            ]

    runtime = FakeRuntime(ModelSession("session-1"))
    runtime_args = []
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
                ["--list-models", "anthropic"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime_args.append(kwargs["args"]) or runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime_args[0].no_session is True
    assert runtime.get_current_session().get_available_models_calls == 1
    assert stdout.getvalue() == "anthropic/claude-3-haiku\nanthropic/claude-3-opus\n"
    assert "prompt is required" not in stderr.getvalue()


def test_run_cli_lists_models_as_json(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class ModelSession(FakeSession):
        def get_available_models(self):
            self.get_available_models_calls += 1
            return [
                type("ModelSelection", (), {"provider": "anthropic", "model_id": "claude-3-opus"}),
                type("ModelSelection", (), {"provider": "google", "model_id": "gemini-2.0"}),
                type("ModelSelection", (), {"provider": "anthropic", "model_id": "claude-3-haiku"}),
            ]

    runtime = FakeRuntime(ModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models", "anthropic", "--list-models-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "provider": "anthropic",
            "model_id": "claude-3-haiku",
            "id": "anthropic/claude-3-haiku",
        },
        {
            "provider": "anthropic",
            "model_id": "claude-3-opus",
            "id": "anthropic/claude-3-opus",
        },
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_model_metadata_when_session_exposes_details(tmp_path) -> None:
    from loushang.ai.model import Capabilities, Model
    from loushang.coding.cli.__main__ import run_cli

    class ModelSession(FakeSession):
        def get_available_model_details(self):
            return [
                Model(
                    id="claude-3-opus",
                    provider="anthropic",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(reasoning=True, input=("text", "image"), context_window=200000, max_tokens=8192),
                ),
                Model(
                    id="gpt-5-mini",
                    provider="openai",
                    endpoint="responses",
                    capabilities=Capabilities(reasoning=False, input=("text",), context_window=128000, max_tokens=4096),
                ),
            ]

    runtime = FakeRuntime(ModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models", "opus"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == (
        "provider   model          context  max-out  thinking  images\n"
        "anthropic  claude-3-opus  200K     8192     yes       yes\n"
    )
    assert stderr.getvalue() == ""


def test_run_cli_lists_model_metadata_as_json(tmp_path) -> None:
    from loushang.ai.model import Capabilities, Model
    from loushang.coding.cli.__main__ import run_cli

    class ModelSession(FakeSession):
        def get_available_model_details(self):
            return [
                Model(
                    id="kimi-k2.5",
                    provider="moonshot",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(reasoning=True, input=("text",), context_window=256000, max_tokens=16384),
                )
            ]

    runtime = FakeRuntime(ModelSession("session-1"))
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models", "--list-models-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "provider": "moonshot",
            "model_id": "kimi-k2.5",
            "id": "moonshot/kimi-k2.5",
            "context_window": 256000,
            "max_tokens": 16384,
            "supports_thinking": True,
            "supports_images": False,
        }
    ]


def test_run_cli_lists_models_deduplicates_provider_model_pairs(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class ModelSession(FakeSession):
        def get_available_models(self):
            self.get_available_models_calls += 1
            return [
                type("ModelSelection", (), {"provider": "moonshot", "model_id": "kimi-k2.5"}),
                type("ModelSelection", (), {"provider": "moonshot", "model_id": "kimi-k2.5"}),
                type("ModelSelection", (), {"provider": "openai", "model_id": "gpt-5"}),
            ]

    runtime = FakeRuntime(ModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == "moonshot/kimi-k2.5\nopenai/gpt-5\n"
    assert stderr.getvalue() == ""


def test_run_cli_reports_list_models_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenModelSession(FakeSession):
        def get_available_models(self):
            raise RuntimeError("model listing failed")

    runtime = FakeRuntime(BrokenModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "model listing failed" in stderr.getvalue()


def test_run_cli_reports_list_models_unexpected_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenModelSession(FakeSession):
        def get_available_models(self):
            raise TypeError("model listing type error")

    runtime = FakeRuntime(BrokenModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "model listing type error" in stderr.getvalue()


def test_run_cli_reports_list_models_invalid_payload(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class InvalidModelSession(FakeSession):
        def get_available_models(self):
            return {"providers": []}

    runtime = FakeRuntime(InvalidModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=FakeRunner(),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "model listing returned an invalid response." in stderr.getvalue()


def test_run_cli_list_models_query_ignores_invalid_model_entries(tmp_path) -> None:
    from types import SimpleNamespace

    from loushang.coding.cli.__main__ import run_cli

    class WeirdModelSession(FakeSession):
        def get_available_models(self):
            return [
                SimpleNamespace(provider=123, model_id="legacy"),
                SimpleNamespace(provider="openai", model_id="gpt-5"),
                SimpleNamespace(provider="moonshot", model_id=None),
            ]

    runtime = FakeRuntime(WeirdModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models", "gpt"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == "openai/gpt-5\n"
    assert stderr.getvalue() == ""


def test_run_cli_list_models_query_ignores_raising_model_attributes(tmp_path) -> None:
    from types import SimpleNamespace

    from loushang.coding.cli.__main__ import run_cli

    class BadProvider:
        @property
        def provider(self):
            raise RuntimeError("provider unavailable")

        @property
        def model_id(self):
            return "alpha"

    class RaisingModelSession(FakeSession):
        def get_available_models(self):
            return [
                BadProvider(),
                SimpleNamespace(provider="openai", model_id="gpt-5"),
            ]

    runtime = FakeRuntime(RaisingModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models", "gpt"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0
    asyncio.run(scenario())

    assert stdout.getvalue() == "openai/gpt-5\n"
    assert stderr.getvalue() == ""


def test_run_cli_list_models_text_mode_uses_normalized_entries(tmp_path) -> None:
    from types import SimpleNamespace

    from loushang.coding.cli.__main__ import run_cli

    class FlakyModel:
        def __init__(self) -> None:
            self._provider_calls = 0

        @property
        def provider(self) -> str:
            self._provider_calls += 1
            if self._provider_calls >= 2:
                raise RuntimeError("provider unavailable on repeated access")
            return "openai"

        @property
        def model_id(self) -> str:
            return "gpt-5"

    class MixedModelSession(FakeSession):
        def get_available_models(self):
            return [
                FlakyModel(),
                SimpleNamespace(provider="anthropic", model_id="claude-3-haiku"),
            ]

    runtime = FakeRuntime(MixedModelSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-models"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == "anthropic/claude-3-haiku\n"
    assert stderr.getvalue() == ""


def test_run_cli_lists_commands_and_returns_early(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    runtime.get_current_session().set_commands(
        [
            {
                "name": "deploy",
                "description": "Deploy project",
                "source": "extension",
                "source_info": {"path": "/tmp/project/extensions/deploy.py"},
            },
            {
                "name": "plan",
                "description": "Run plan",
                "source": "prompt",
                "source_info": {"path": "/tmp/project/prompts/plan.md"},
            },
        ]
    )
    runtime_args = []
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime_args.append(kwargs["args"]) or runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime_args[0].no_session is True
    assert runtime.get_current_session().list_commands_calls == 1
    assert stdout.getvalue() == (
        "deploy\textension\t/tmp/project/extensions/deploy.py\tDeploy project\n"
        "plan\tprompt\t/tmp/project/prompts/plan.md\tRun plan\n"
    )
    assert "prompt is required" not in stderr.getvalue()


def test_run_cli_lists_command_descriptors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    runtime.get_current_session().set_commands(
        [
            {
                "name": "deploy",
                "description": "Deploy project",
                "source": "extension",
                "source_info": {"path": "/tmp/project/extensions/deploy.py"},
            },
            {
                "name": "plan",
                "description": "Run plan",
                "source": "prompt",
                "source_info": {"path": "/tmp/project/prompts/plan.md"},
            },
            {
                "name": "legacy",
                "description": None,
                "source": "skill",
                "source_info": {"path": "/tmp/project/skills/legacy.md"},
            },
        ]
    )
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == (
        "deploy\textension\t/tmp/project/extensions/deploy.py\tDeploy project\n"
        "plan\tprompt\t/tmp/project/prompts/plan.md\tRun plan\n"
        "legacy\tskill\t/tmp/project/skills/legacy.md\t\n"
    )
    assert "prompt is required" not in stderr.getvalue()


def test_run_cli_lists_commands_skips_items_raising_normalization(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BadCommand:
        @property
        def name(self):
            raise RuntimeError("bad command")

    runtime = FakeRuntime(FakeSession("session-1"))
    runtime.get_current_session().commands_payload = [
        SimpleNamespace(
            name="good",
            description="Keep",
            source="extension",
            source_info=SimpleNamespace(path="/tmp/project/extensions/good.py"),
        ),
        BadCommand(),
        123,
    ]
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands", "--list-commands-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "name": "good",
            "description": "Keep",
            "source": "extension",
            "source_info": {"path": "/tmp/project/extensions/good.py"},
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_commands_as_json(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    runtime.get_current_session().set_commands(
        [
            {
                "name": "deploy",
                "description": "Deploy project",
                "source": "extension",
                "source_info": {"path": "/tmp/project/extensions/deploy.py"},
            },
            {
                "name": "plan",
                "description": None,
                "source": "prompt",
                "argument_hint": "[topic]",
                "source_info": {"path": "/tmp/project/prompts/plan.md"},
            },
        ]
    )
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands", "--list-commands-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "name": "deploy",
            "description": "Deploy project",
            "source": "extension",
            "source_info": {"path": "/tmp/project/extensions/deploy.py"},
        },
        {
            "name": "plan",
            "description": "",
            "source": "prompt",
            "argument_hint": "[topic]",
            "source_info": {"path": "/tmp/project/prompts/plan.md"},
        },
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_diagnostics_as_json(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.diagnostics import DiagnosticRecord

    session = FakeSession("session-1")
    session.set_diagnostics(
        [
            DiagnosticRecord(
                type="warning",
                code="model_auth_unresolved",
                message="Provider demo has no configured API key.",
                phase="startup",
                source="model",
                timestamp="2026-05-01T00:00:00Z",
                session_id="session-1",
                source_path=Path("/tmp/project/.loushang/settings.json"),
                details={"provider": "demo"},
                fingerprint="fp-1",
                occurrence_count=2,
            )
        ]
    )
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-diagnostics", "--list-diagnostics-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "type": "warning",
            "code": "model_auth_unresolved",
            "message": "Provider demo has no configured API key.",
            "phase": "startup",
            "source": "model",
            "timestamp": "2026-05-01T00:00:00Z",
            "details": {"provider": "demo"},
            "occurrenceCount": 2,
            "sessionId": "session-1",
            "sourcePath": "/tmp/project/.loushang/settings.json",
            "fingerprint": "fp-1",
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_diagnostics_as_tsv_and_returns_early(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.diagnostics import DiagnosticRecord

    session = FakeSession("session-1")
    session.set_diagnostics(
        [
            DiagnosticRecord(
                type="error",
                code="assistant_response_error",
                message="provider failed",
                phase="runtime",
                source="provider",
                timestamp="2026-05-01T00:00:00Z",
                occurrence_count=3,
            )
        ]
    )
    runtime = FakeRuntime(session)
    runtime_args = []
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-diagnostics"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime_args.append(kwargs["args"]) or runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime_args[0].no_session is True
    assert stdout.getvalue() == "error\truntime\tprovider\tassistant_response_error\t3\tprovider failed\n"
    assert stderr.getvalue() == ""


def test_run_cli_lists_skills_as_json(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.loader import SkillDescriptor

    session = FakeSession("session-1")
    session.resource_bundle.skills = [
        SkillDescriptor(
            name="debug",
            source_path=Path("/tmp/project/skills/debug/SKILL.md"),
            content="Debug skill",
            source_kind="project_local",
        )
    ]
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-skills", "--list-skills-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "name": "debug",
            "id": "debug",
            "path": "/tmp/project/skills/debug/SKILL.md",
            "source_kind": "project_local",
            "enabled": True,
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_methods_as_json(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    method_dir = tmp_path / "methods" / "task" / "review"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\n"
        "name: review\n"
        "description: Review changes.\n"
        "type: task\n"
        "domain: coding\n"
        "domains:\n"
        "  - coding\n"
        "  - research\n"
        "task_types:\n"
        "  - reviewing\n"
        "contexts:\n"
        "  - oss-library\n"
        "artifact_types:\n"
        "  - code\n"
        "modalities:\n"
        "  - text\n"
        "toolchains:\n"
        "  - python\n"
        "lifecycle:\n"
        "  - maintenance\n"
        "capabilities:\n"
        "  - diff-review\n"
        "complexity: standard\n"
        "risk: medium\n"
        "tags:\n"
        "  method_family:\n"
        "    - review-first\n"
        "  domain_app: coding\n"
        "meta_role: VALIDATOR\n"
        "phase: VERIFY\n"
        "---\n\n"
        "Review the diff carefully.",
        encoding="utf-8",
    )
    (tmp_path / "methods" / "METHOD.md").write_text("Future method manifest.", encoding="utf-8")
    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["method", "list", "--list-methods-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "id": "method:task:review",
            "name": "review",
            "kind": "method_resource",
            "element_type": "task",
            "domain": "coding",
            "meta_role": "VALIDATOR",
            "phase": "VERIFY",
            "path": str(method_dir / "SKILL.md"),
            "applicability": {
                "domains": ["coding", "research"],
                "task_types": ["reviewing"],
                "contexts": ["oss-library"],
                "artifact_types": ["code"],
                "modalities": ["text"],
                "toolchains": ["python"],
                "lifecycle": ["maintenance"],
                "capabilities": ["diff-review"],
                "complexity": "standard",
                "risk": "medium",
                "tags": {
                    "method_family": ["review-first"],
                    "domain_app": ["coding"],
                },
            },
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_shows_method_json_with_applicability(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    method_dir = tmp_path / "methods" / "task" / "review"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\n"
        "name: review\n"
        "description: Review changes.\n"
        "type: task\n"
        "domains: [coding, research]\n"
        "task_types: [reviewing]\n"
        "tags:\n"
        "  method_family: review-first\n"
        "---\n\n"
        "Review the diff carefully.",
        encoding="utf-8",
    )
    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["method", "show", "review", "--show-method-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    payload = json.loads(stdout.getvalue())
    assert payload["applicability"] == {
        "domains": ["coding", "research"],
        "task_types": ["reviewing"],
        "contexts": [],
        "artifact_types": [],
        "modalities": [],
        "toolchains": [],
        "lifecycle": [],
        "capabilities": [],
        "complexity": None,
        "risk": None,
        "tags": {"method_family": ["review-first"]},
    }
    assert payload["content"] == (
        "---\n"
        "name: review\n"
        "description: Review changes.\n"
        "type: task\n"
        "domains: [coding, research]\n"
        "task_types: [reviewing]\n"
        "tags:\n"
        "  method_family: review-first\n"
        "---\n\n"
        "Review the diff carefully."
    )
    assert stderr.getvalue() == ""


def test_run_cli_shows_method_as_text(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    skill_dir = tmp_path / "skills" / "debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: debug\n"
        "description: Debug failures.\n"
        "type: task\n"
        "domain: coding\n"
        "task_types: [debugging]\n"
        "risk: medium\n"
        "tags:\n"
        "  method_family: debug-first\n"
        "---\n\n"
        "Debug failures carefully.",
        encoding="utf-8",
    )
    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["method", "show", "debug"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    output = stdout.getvalue()
    assert "id: skill:debug" in output
    assert "kind: skill_backed" in output
    assert "element_type: task" in output
    assert "applicability:" in output
    assert "  domains: coding" in output
    assert "  task_types: debugging" in output
    assert "  risk: medium" in output
    assert "  tags.method_family: debug-first" in output
    assert "Debug failures carefully." in output
    assert stderr.getvalue() == ""


def test_run_cli_show_method_reports_missing_method(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["method", "show", "missing"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "Error: method not found: missing" in stderr.getvalue()


def test_run_cli_lists_plugins_as_tsv(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    plugin_root = tmp_path / "plugins" / "debug-pack"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps({"name": "debug-pack", "version": "1.0.0"}),
        encoding="utf-8",
    )
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-plugins"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(plugin_sources=(str(plugin_root),)),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == f"debug-pack\t1.0.0\t{plugin_root.resolve()}\tTrue\n"
    assert stderr.getvalue() == ""


def test_run_cli_lists_disabled_plugins_as_tsv(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    plugin_root = tmp_path / "plugins" / "debug-pack"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "debug-pack"}), encoding="utf-8")
    settings_path = tmp_path / ".loushang" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "plugin_sources": [str(plugin_root)],
                "disabled_plugins": ["debug-pack"],
            }
        ),
        encoding="utf-8",
    )
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()
    services = create_services(settings_manager=SettingsManager(project_settings_path=settings_path))

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-plugins"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == f"debug-pack\t\t{plugin_root.resolve()}\tFalse\n"
    assert stderr.getvalue() == ""


def test_run_cli_lists_package_roots_and_plugin_packages_as_json(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    package_root = tmp_path / "packages" / "review-pack"
    (package_root / "prompts").mkdir(parents=True)
    (package_root / "skills" / "review").mkdir(parents=True)
    (package_root / "prompts" / "review.md").write_text("Package prompt", encoding="utf-8")
    (package_root / "skills" / "review" / "SKILL.md").write_text("Package skill", encoding="utf-8")
    plugin_root = tmp_path / "plugins" / "debug-pack"
    plugin_package_root = plugin_root / "resources"
    (plugin_package_root / "themes").mkdir(parents=True)
    (plugin_package_root / "themes" / "clean.json").write_text("{}", encoding="utf-8")
    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "debug-pack",
                "version": "1.0.0",
                "packageRoot": "resources",
            }
        ),
        encoding="utf-8",
    )
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages", "--list-packages-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(
                package_roots=(str(package_root),),
                plugin_sources=(str(plugin_root),),
            ),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == [
        {
            "name": "review-pack",
            "kind": "package_root",
            "packageKind": "local_package_root",
            "scope": "merged",
            "version": "",
            "source": str(package_root.resolve()),
            "path": str(package_root.resolve()),
            "enabled": True,
            "prompts": 1,
            "skills": 1,
            "extensions": 0,
            "themes": 0,
            "diagnostics": 0,
        },
        {
            "name": "debug-pack",
            "kind": "plugin",
            "packageKind": "plugin_package",
            "scope": "merged",
            "version": "1.0.0",
            "source": str(plugin_root.resolve()),
            "path": str(plugin_package_root.resolve()),
            "enabled": True,
            "prompts": 0,
            "skills": 0,
            "extensions": 0,
            "themes": 1,
            "diagnostics": 0,
        },
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_package_scopes_from_settings_layers(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    global_package_root = tmp_path / "global" / "package"
    project_package_root = tmp_path / "project-package"
    global_plugin_root = tmp_path / "global" / "plugin"
    project_plugin_root = tmp_path / "project-plugin"
    for root in (global_package_root, project_package_root, global_plugin_root, project_plugin_root):
        root.mkdir(parents=True)
    (global_plugin_root / "plugin.json").write_text(json.dumps({"name": "global-plugin"}), encoding="utf-8")
    (project_plugin_root / "plugin.json").write_text(json.dumps({"name": "project-plugin"}), encoding="utf-8")
    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / ".loushang" / "settings.json"
    project_settings_path.parent.mkdir()
    global_settings_path.write_text(
        json.dumps(
            {
                "package_roots": [str(global_package_root)],
                "plugin_sources": [str(global_plugin_root)],
            }
        ),
        encoding="utf-8",
    )
    project_settings_path.write_text(
        json.dumps(
            {
                "package_roots": [str(project_package_root)],
                "plugin_sources": [str(project_plugin_root)],
            }
        ),
        encoding="utf-8",
    )
    services = create_services(
        settings_manager=SettingsManager(
            global_settings_path=global_settings_path,
            project_settings_path=project_settings_path,
        )
    )
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages", "--list-packages-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    packages = json.loads(stdout.getvalue())
    assert [(package["name"], package["kind"], package["scope"]) for package in packages] == [
        ("package", "package_root", "user"),
        ("project-package", "package_root", "project"),
        ("global-plugin", "plugin", "user"),
        ("project-plugin", "plugin", "project"),
    ]
    assert stderr.getvalue() == ""


def test_run_cli_reports_settings_load_warnings_for_package_listing(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    project_settings_path = tmp_path / ".loushang" / "settings.json"
    project_settings_path.parent.mkdir()
    project_settings_path.write_text("{not-json", encoding="utf-8")
    services = create_services(settings_manager=SettingsManager(project_settings_path=project_settings_path))
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages", "--list-packages-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == []
    assert "Warning (package command, project settings):" in stderr.getvalue()
    assert "Expecting property name" in stderr.getvalue()


def test_run_cli_reports_settings_load_warnings_once_for_plugin_toggles(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    project_settings_path = tmp_path / ".loushang" / "settings.json"
    project_settings_path.parent.mkdir()
    project_settings_path.write_text("{not-json", encoding="utf-8")
    services = create_services(settings_manager=SettingsManager(project_settings_path=project_settings_path))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--add-plugin-source", "plugins/debug-pack", "--disable-plugin", "legacy"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == "added plugin source\tplugins/debug-pack\ndisabled plugin\tlegacy\n"
    assert stderr.getvalue().count("Warning (package command, project settings):") == 1


def test_run_cli_remove_missing_plugin_source_returns_stable_error(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    services = create_services(settings_manager=SettingsManager(project_settings_path=tmp_path / ".loushang" / "settings.json"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--remove-plugin-source", "plugins/missing-pack"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Error: no matching plugin source found: plugins/missing-pack\n"


def test_run_cli_add_duplicate_plugin_source_returns_stable_error(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    project_settings_path = tmp_path / ".loushang" / "settings.json"
    project_settings_path.parent.mkdir()
    project_settings_path.write_text(
        json.dumps({"plugin_sources": ["plugins/debug-pack"]}),
        encoding="utf-8",
    )
    services = create_services(settings_manager=SettingsManager(project_settings_path=project_settings_path))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--add-plugin-source", "plugins/debug-pack"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Error: plugin source already exists: plugins/debug-pack\n"


def test_run_cli_adds_https_remote_plugin_source_without_resolving_local_path(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    project_settings_path = tmp_path / ".loushang" / "settings.json"
    services = create_services(settings_manager=SettingsManager(project_settings_path=project_settings_path))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["install", "https://packages.example.invalid/review-pack.git"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == {
        "command": "install_package",
        "record": {
            "source": "https://packages.example.invalid/review-pack.git",
            "name": "review-pack",
            "lifecycle": "installed",
            "targetPath": "/tmp/packages/review-pack",
        },
    }
    assert stderr.getvalue() == ""


def test_run_cli_rejects_insecure_remote_plugin_source(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    services = create_services(settings_manager=SettingsManager(project_settings_path=tmp_path / ".loushang" / "settings.json"))
    diagnostics = services.diagnostics_service
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["install", "http://packages.example.invalid/review-pack.git"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "Error: insecure remote package source requires HTTPS: http://packages.example.invalid/review-pack.git\n"
    )
    records = diagnostics.get_diagnostics(code="package_source_policy_denied")
    assert len(records) == 1
    assert records[0].source == "policy"
    assert records[0].details == {
        "plugin_source": "http://packages.example.invalid/review-pack.git",
        "policy": "package_security",
        "disposition": "deny",
    }


def test_run_cli_runs_explicit_package_lifecycle_commands(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--materialize-package",
                source,
                "--update-package",
                source,
                "--remove-package",
                source,
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.materialize_package_calls == [source]
    assert session.update_package_calls == [source]
    assert session.remove_package_calls == [source]
    assert [json.loads(line) for line in stdout.getvalue().splitlines()] == [
        {"command": "materialize_package", "record": {"source": source, "name": "review-pack", "lifecycle": "installed", "targetPath": "/tmp/packages/review-pack"}},
        {"command": "update_package", "record": {"source": source, "name": "review-pack", "lifecycle": "installed", "targetPath": "/tmp/packages/review-pack"}},
        {"command": "remove_package", "record": {"source": source, "name": "review-pack", "lifecycle": "remote_registered", "targetPath": "/tmp/packages/review-pack"}},
    ]
    assert stderr.getvalue() == ""


def test_run_cli_package_lifecycle_failed_record_returns_error(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession("session-1")

    async def failed_materialize(source_arg: str) -> dict[str, object]:
        session.materialize_package_calls.append(source_arg)
        return {
            "source": source_arg,
            "name": "review-pack",
            "lifecycle": "failed",
            "targetPath": "/tmp/packages/review-pack",
            "errorMessage": "clone failed",
        }

    session.materialize_package = failed_materialize  # type: ignore[method-assign]
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--materialize-package", source],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert session.materialize_package_calls == [source]
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Error: clone failed\n"


def test_run_cli_runs_high_level_package_manager_commands(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--install-package",
                source,
                "--check-package-updates",
                "--update-packages",
                "--uninstall-package",
                source,
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.install_package_calls == [(source, "global")]
    assert session.check_package_updates_calls == 1
    assert session.update_packages_calls == 1
    assert session.uninstall_package_calls == [(source, "global")]
    assert [json.loads(line)["command"] for line in stdout.getvalue().splitlines()] == [
        "install_package",
        "check_package_updates",
        "update_packages",
        "uninstall_package",
    ]
    assert stderr.getvalue() == ""


def test_run_cli_pi_style_package_install_local_passes_project_scope(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    source = "https://packages.example.invalid/review-pack.git"
    session = FakeSession("session-1")
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["install", "--local", source],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.install_package_calls == [(source, "project")]
    assert json.loads(stdout.getvalue())["command"] == "install_package"
    assert stderr.getvalue() == ""


def test_run_cli_lists_disabled_plugin_package_as_text(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    plugin_root = tmp_path / "plugins" / "debug-pack"
    plugin_package_root = plugin_root / "resources"
    plugin_package_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps({"name": "debug-pack", "packageRoot": "resources"}),
        encoding="utf-8",
    )
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(
                plugin_sources=(str(plugin_root),),
                disabled_plugins=("debug-pack",),
            ),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == (
        "Merged packages:\n"
        f"  debug-pack [plugin] disabled\n"
        f"    source: {plugin_root.resolve()}\n"
        f"    path: {plugin_package_root.resolve()}\n"
    )
    assert stderr.getvalue() == ""


def test_run_cli_groups_package_text_output_by_scope(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.packages_payload = [
        {
            "name": "user-pack",
            "kind": "remote_plugin",
            "scope": "user",
            "version": "1.0.0",
            "source": "https://packages.example.invalid/user-pack.git",
            "path": "/tmp/packages/user-pack",
            "enabled": True,
            "prompts": 1,
            "skills": 2,
            "extensions": 0,
            "themes": 0,
            "diagnostics": 0,
        },
        {
            "name": "project-pack",
            "kind": "package_root",
            "scope": "project",
            "version": "",
            "source": "packages/project-pack",
            "path": "/tmp/project/.loushang/packages/project-pack",
            "enabled": True,
            "prompts": 0,
            "skills": 1,
            "extensions": 0,
            "themes": 0,
            "diagnostics": 1,
            "filtered": True,
        },
    ]
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == (
        "User packages:\n"
        "  user-pack 1.0.0 [remote_plugin]\n"
        "    source: https://packages.example.invalid/user-pack.git\n"
        "    path: /tmp/packages/user-pack\n"
        "    resources: prompts=1 skills=2\n"
        "\n"
        "Project packages:\n"
        "  project-pack [package_root] filtered\n"
        "    source: packages/project-pack\n"
        "    path: /tmp/project/.loushang/packages/project-pack\n"
        "    resources: skills=1 diagnostics=1\n"
    )
    assert stderr.getvalue() == ""


def test_run_cli_marks_package_version_conflicts_in_json(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    first_plugin = tmp_path / "plugins" / "debug-pack-a"
    second_plugin = tmp_path / "plugins" / "debug-pack-b"
    first_plugin.mkdir(parents=True)
    second_plugin.mkdir(parents=True)
    (first_plugin / "plugin.json").write_text(json.dumps({"name": "debug-pack", "version": "1.0.0"}), encoding="utf-8")
    (second_plugin / "plugin.json").write_text(json.dumps({"name": "debug-pack", "version": "2.0.0"}), encoding="utf-8")
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages", "--list-packages-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(plugin_sources=(str(first_plugin), str(second_plugin))),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    packages = json.loads(stdout.getvalue())
    assert [package["versionConflict"] for package in packages] == [True, True]
    assert packages[0]["conflictVersions"] == ["1.0.0", "2.0.0"]
    assert stderr.getvalue() == ""


def test_run_cli_lists_offline_package_catalog_entries(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "name": "review-pack",
                        "version": "3.0.0",
                        "source": "https://example.invalid/review-pack",
                        "description": "Catalog entry",
                        "skills": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages", "--list-packages-format", "json", "--package-catalog", str(catalog_path)],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    packages = json.loads(stdout.getvalue())
    assert packages == [
        {
            "name": "review-pack",
            "kind": "catalog",
            "packageKind": "catalog_package",
            "scope": "catalog",
            "version": "3.0.0",
            "source": "https://example.invalid/review-pack",
            "path": "",
            "enabled": False,
            "prompts": 0,
            "skills": 2,
            "extensions": 0,
            "themes": 0,
            "diagnostics": 0,
            "description": "Catalog entry",
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_lists_packages_from_session_projection(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.packages_payload = [
        {
            "name": "review-pack",
            "kind": "remote_plugin",
            "packageKind": "remote_package",
            "scope": "project",
            "version": "1.2.3",
            "source": "https://packages.example.invalid/review-pack.git",
            "path": str(tmp_path / "packages" / "review-pack"),
            "enabled": True,
            "prompts": 1,
            "skills": 1,
            "extensions": 0,
            "themes": 0,
            "diagnostics": 0,
            "lifecycle": "installed",
            "installedCommit": "abc",
        }
    ]
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages", "--list-packages-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == session.packages_payload
    assert stderr.getvalue() == ""


def test_run_cli_lists_remote_plugin_source_lifecycle_state(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    project_settings_path = tmp_path / ".loushang" / "settings.json"
    project_settings_path.parent.mkdir()
    project_settings_path.write_text(
        json.dumps({"plugin_sources": ["https://packages.example.invalid/review-pack.git"]}),
        encoding="utf-8",
    )
    services = create_services(settings_manager=SettingsManager(project_settings_path=project_settings_path))
    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-packages", "--list-packages-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    packages = json.loads(stdout.getvalue())
    assert packages == [
        {
            "name": "review-pack",
            "kind": "remote_plugin",
            "packageKind": "remote_package",
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
            "pinned": False,
            "requestedRef": "",
            "resolvedCommit": "",
            "installedCommit": "",
            "dirty": False,
            "lastUpdatedAt": "",
            "filtered": False,
            "description": "",
        }
    ]
    assert stderr.getvalue() == ""


def test_run_cli_persists_skill_and_plugin_toggles(tmp_path) -> None:
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.control import SettingsManager

    project_settings_path = tmp_path / ".loushang" / "settings.json"
    project_settings_path.parent.mkdir()
    project_settings_path.write_text(
        json.dumps({"plugin_sources": ["plugins/legacy-pack"]}),
        encoding="utf-8",
    )
    services = create_services(
        settings_manager=SettingsManager(project_settings_path=project_settings_path),
    )
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--disable-skill",
                "review",
                "--enable-skill",
                "debug",
                "--remove-plugin-source",
                "plugins/legacy-pack",
                "--add-plugin-source",
                "plugins/debug-pack",
                "--disable-plugin",
                "legacy-pack",
                "--enable-plugin",
                "debug-pack",
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == (
        "disabled skill\treview\n"
        "enabled skill\tdebug\n"
        "removed plugin source\tplugins/legacy-pack\n"
        "added plugin source\tplugins/debug-pack\n"
        "disabled plugin\tlegacy-pack\n"
        "enabled plugin\tdebug-pack\n"
    )
    assert stderr.getvalue() == ""
    reloaded = SettingsManager(project_settings_path=project_settings_path)
    assert reloaded.get_settings().plugin_sources == ("plugins/debug-pack",)
    assert reloaded.get_settings().disabled_skills == ("review",)
    assert reloaded.get_settings().disabled_plugins == ("legacy-pack",)


def test_run_cli_lists_commands_as_tsv(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    runtime.get_current_session().set_commands(
        [
            {
                "name": "deploy",
                "description": "Deploy project",
                "source": "extension",
                "source_info": {"path": "/tmp/project/extensions/deploy.py"},
            },
            {
                "name": "legacy",
                "description": None,
                "source": "prompt",
                "source_info": {"path": "/tmp/project/prompts/legacy.md"},
            },
        ]
    )
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands", "--list-commands-format", "tsv"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue() == (
        "deploy\textension\t/tmp/project/extensions/deploy.py\tDeploy project\n"
        "legacy\tprompt\t/tmp/project/prompts/legacy.md\t\n"
    )
    assert stderr.getvalue() == ""


def test_run_cli_reports_list_commands_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenCommandListSession(FakeSession):
        def list_commands(self):
            raise RuntimeError("command listing failed")

    runtime = FakeRuntime(BrokenCommandListSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "command listing failed" in stderr.getvalue()


def test_run_cli_reports_list_commands_unexpected_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenCommandListSession(FakeSession):
        def list_commands(self):
            raise TypeError("command listing type error")

    runtime = FakeRuntime(BrokenCommandListSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "command listing type error" in stderr.getvalue()


def test_run_cli_reports_list_commands_invalid_payload(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class InvalidCommandSession(FakeSession):
        def list_commands(self):
            return {"commands": ["/bad"]}

    runtime = FakeRuntime(InvalidCommandSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-commands"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "command registry returned an invalid response." in stderr.getvalue()


def test_run_cli_reports_list_diagnostics_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenDiagnosticsSession(FakeSession):
        def get_last_diagnostics(self, limit: int = 50):
            raise RuntimeError("diagnostics failed")

    runtime = FakeRuntime(BrokenDiagnosticsSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-diagnostics"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "diagnostics failed" in stderr.getvalue()


def test_run_cli_reports_list_diagnostics_invalid_limit(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--list-diagnostics", "--diagnostics-limit", "0"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert stdout.getvalue() == ""
    assert "diagnostics limit must be greater than zero." in stderr.getvalue()


def test_run_cli_bridges_startup_problem_to_diagnostics(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.coding.diagnostics import DiagnosticsService
    from loushang.observability import get_log, reset_observability

    class StartupProblemRuntime(FakeRuntime):
        async def new_session(self, *, cwd: str) -> FakeSession:
            del cwd
            get_log("loushang.tests.startup").problem(
                "model_selection_ambiguous",
                source="config",
                message="Ambiguous model selection: faux:alpha",
                recoverable=True,
                provider_id="faux",
                model_id="alpha",
            )
            raise ValueError("Ambiguous model selection: faux:alpha")

    services = _fake_services()
    services.diagnostics_service = DiagnosticsService()
    runtime = StartupProblemRuntime(FakeSession("session-1"))
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["hello"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=services,
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    reset_observability()
    try:
        asyncio.run(scenario())
    finally:
        reset_observability()

    records = services.diagnostics_service.get_last_diagnostics()
    assert len(records) == 1
    assert records[0].code == "model_selection_ambiguous"
    assert records[0].source == "model"
    assert records[0].phase == "startup"
    assert records[0].session_id is None
    assert records[0].details["problem_source"] == "config"
    assert "Ambiguous model selection" in stderr.getvalue()


def test_run_cli_executes_command_and_prints_output(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.set_execute_command_result(type("Execution", (), {"result": {"status": "ok"}})())
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "deploy", "--command-args", "now"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.execute_command_calls == [("deploy", "now")]
    assert stdout.getvalue() == "{\"status\": \"ok\"}\n"
    assert stderr.getvalue() == ""


def test_run_cli_executes_command_with_json_result_envelope(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.set_execute_command_result(type("Execution", (), {"result": {"status": "ok"}})())
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [
                "--command",
                "deploy",
                "--command-args",
                "now",
                "--command-result-format",
                "json",
            ],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == {
        "command": "deploy",
        "args": "now",
        "result": {"status": "ok"},
    }
    assert stderr.getvalue() == ""


def test_run_cli_executes_void_command_with_json_result_envelope(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.set_execute_command_result(type("Execution", (), {"result": None})())
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "deploy", "--command-result-format", "json"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert json.loads(stdout.getvalue()) == {
        "command": "deploy",
        "args": "",
        "result": None,
    }
    assert stderr.getvalue() == ""


def test_run_cli_executes_command_with_leading_slash_name(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.set_execute_command_result(type("Execution", (), {"result": "done"})())
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "/deploy", "--command-args", "now"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.execute_command_calls == [("deploy", "now")]
    assert stdout.getvalue() == "done\n"
    assert stderr.getvalue() == ""


def test_run_cli_prints_non_jsonifiable_command_result(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.set_execute_command_result(type("Execution", (), {"result": {1, 2, 3}})())
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "deploy"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert stdout.getvalue().strip().startswith("{")
    assert "1" in stdout.getvalue() and "2" in stdout.getvalue() and "3" in stdout.getvalue()
    assert "Error" not in stderr.getvalue()


def test_run_cli_executes_command_with_void_result_without_printing(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    session = FakeSession("session-1")
    session.set_execute_command_result(type("Execution", (), {"result": None})())
    runtime = FakeRuntime(session)
    stdout = StringIO()
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "deploy"],
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.execute_command_calls == [("deploy", "")]
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_run_cli_reports_command_not_available(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenCommandSession(FakeSession):
        execute_command_async = None  # type: ignore[assignment]

    runtime = FakeRuntime(BrokenCommandSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "deploy"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "command execution is not available." in stderr.getvalue()


def test_run_cli_reports_missing_command(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "missing"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "command not found: missing" in stderr.getvalue()


def test_run_cli_reports_command_execution_errors(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenCommandSession(FakeSession):
        async def execute_command_async(self, invocation_name: str, args: str):
            raise RuntimeError("command failed")

    runtime = FakeRuntime(BrokenCommandSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--command", "deploy"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "command failed" in stderr.getvalue()


def test_run_cli_rejects_missing_prompt_outside_rpc(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            [],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert "prompt is required" in stderr.getvalue()


def test_run_cli_rejects_fork_without_restoring_a_session(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    stderr = StringIO()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--fork", "entry-1", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: FakeRuntime(FakeSession("session-1")),
        )
        assert exit_code == 2

    asyncio.run(scenario())

    assert "--fork requires --session" in stderr.getvalue()


@pytest.mark.parametrize("resume_flag", ["--session", "--continue"])
def test_run_cli_reports_fork_errors(tmp_path, resume_flag) -> None:
    from loushang.coding.cli.__main__ import run_cli

    class BrokenForkRuntime(FakeRuntime):
        async def fork_session(self, entry_id: str):
            raise RuntimeError(f"fork failed for {entry_id}")

    runtime = BrokenForkRuntime(FakeSession("session-1"))
    stderr = StringIO()

    async def scenario() -> None:
        args = ["--fork", "entry-1", "hello"]
        if resume_flag == "--session":
            args = ["--session", "session-1", *args]
        else:
            runtime.session_records = [SimpleNamespace(session_file=Path(f"/tmp/{resume_flag}-session.jsonl"))]
            runtime.restore_session_calls = []
            args = [resume_flag, *args]

        exit_code = await run_cli(
            args,
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
        )
        assert exit_code == 1

    asyncio.run(scenario())

    assert "fork failed" in stderr.getvalue()


def test_run_cli_applies_thinking_level_override(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli

    runtime = FakeRuntime(FakeSession("session-1"))
    print_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--thinking", "low", "hello"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            print_runner=print_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.get_current_session().set_thinking_calls == ["low"]
