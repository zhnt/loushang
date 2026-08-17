from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from loushang.coding.policy import HeadlessApprovalResolver, PolicyEngine
from loushang.coding.store import SessionManager
from loushang.coding.tools import ToolRegistry, register_builtin_tools
from loushang.coding.types import ModelSelection

from loushang.ai.api import stream_simple
from loushang.ai.model.registry import get_default_model_registry
from loushang.ai.options import SimpleStreamOptions
from loushang.ai.types import AssistantMessage, TextPart
from loushang.coding.bootstrap import create_agent_session_runtime, create_services
from loushang.coding.control import SettingsManager
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.foundation.observability import log_context
from loushang.foundation.observability._router import (
    capture_observability,
    configure_observability,
    restore_observability,
)
from loushang.foundation.observability.trace_sink import TraceJSONLSink

DEFAULT_MODEL = ModelSelection(provider="moonshot", model_id="kimi-for-coding")
DEFAULT_ENDPOINT = "kimi-code-anthropic"

FULL_BMI_RECOVERY_PROMPTS = (
    "你好",
    "你是谁",
    "你能干什么",
    "请生成一个计算BMI的python程序，必须写入当前工作目录下的相对路径 tmp/bmi.py，不要写到 /tmp/bmi.py",
    "请生成一个计算BMI的html程序，必须写入当前工作目录下的相对路径 tmp/bmi.html，不要写到 /tmp/bmi.html",
    "你好",
    "你是谁",
)

HTML_BMI_PROMPTS = (
    "请生成计算bmi的html程序，必须写入当前工作目录下的相对路径 tmp/bmi.html，不要写到 /tmp/bmi.html",
    "你好",
)

HTML_BMI_WRITE_ONLY_PROMPTS = (
    "请只使用 write 工具创建当前工作目录下的相对路径 tmp/bmi.html，不要使用 /tmp/bmi.html，内容是一个可直接打开使用的 BMI 计算 HTML 程序。",
)

SCENARIOS = {
    "full-bmi-recovery": {
        "prompts": FULL_BMI_RECOVERY_PROMPTS,
        "expect_python": True,
        "expect_html": True,
        "description": "generate tmp/bmi.py and tmp/bmi.html, then continue chatting",
    },
    "html-bmi": {
        "prompts": HTML_BMI_PROMPTS,
        "expect_python": False,
        "expect_html": True,
        "description": "generate only tmp/bmi.html, then confirm the session still responds",
    },
    "html-bmi-write-only": {
        "prompts": HTML_BMI_WRITE_ONLY_PROMPTS,
        "expect_python": False,
        "expect_html": True,
        "allowed_tool_names": ["write"],
        "active_tool_names": ["write"],
        "description": "single real-model prompt with only the write tool enabled",
    },
}

RECOVERY_VALIDATION_ERROR = 'Validation failed for tool "write"'


@dataclass
class TurnSummary:
    prompt: str
    assistant_texts: list[str] = field(default_factory=list)
    assistant_errors: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)

    @property
    def assistant_text(self) -> str:
        return "\n".join(text for text in self.assistant_texts if text).strip()


class TranscriptCollector:
    def __init__(self) -> None:
        self.turns: list[TurnSummary] = []
        self._current: TurnSummary | None = None

    def start_turn(self, prompt: str) -> TurnSummary:
        turn = TurnSummary(prompt=prompt)
        self.turns.append(turn)
        self._current = turn
        return turn

    def end_turn(self) -> None:
        self._current = None

    def __call__(self, event: object) -> None:
        if self._current is None or not isinstance(event, dict):
            return

        event_type = event.get("type")
        if event_type == "tool_execution_start":
            self._record_tool_start(event)
        elif event_type == "tool_execution_end":
            self._record_tool_end(event)
        elif event_type == "message_end":
            self._record_message_end(event)
        elif event_type == "agent_end":
            self._record_agent_end(event)

    def _record_tool_start(self, event: dict[str, object]) -> None:
        tool_name = event.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            self._current_turn().tool_calls.append(
                _tool_call_summary(tool_name, event.get("args"))
            )

    def _record_tool_end(self, event: dict[str, object]) -> None:
        if not event.get("is_error"):
            return
        tool_name = event.get("tool_name")
        message = _tool_result_text(event.get("result"))
        if isinstance(tool_name, str) and tool_name:
            message = f"{tool_name}: {message}" if message else tool_name
        if message:
            self._current_turn().tool_errors.append(message)

    def _record_message_end(self, event: dict[str, object]) -> None:
        message = event.get("message")
        if not isinstance(message, AssistantMessage):
            return
        text = _assistant_text(message)
        if text:
            self._current_turn().assistant_texts.append(text)
        error = _assistant_error(message)
        if error:
            self._current_turn().assistant_errors.append(error)

    def _record_agent_end(self, event: dict[str, object]) -> None:
        messages = event.get("messages")
        if not isinstance(messages, list):
            return
        for message in messages:
            if isinstance(message, AssistantMessage):
                error = _assistant_error(message)
                if error and error not in self._current_turn().assistant_errors:
                    self._current_turn().assistant_errors.append(error)

    def _current_turn(self) -> TurnSummary:
        if self._current is None:
            raise RuntimeError("collector has no active turn")
        return self._current


async def run_scenario(args: argparse.Namespace) -> int:
    workspace, is_temporary = _resolve_workspace(args.cwd)
    session_dir = Path(args.session_dir).expanduser() if args.session_dir else workspace / ".loushang" / "scenario-sessions"
    cleanup = is_temporary and bool(args.cleanup)
    scenario = SCENARIOS[args.case]
    prompts = scenario["prompts"]
    trace_scopes = _trace_scopes(args)
    trace_path = _trace_file_path(args, workspace) if trace_scopes and args.trace_file else None

    print(f"workspace: {workspace}")
    print(f"session_dir: {session_dir}")
    if trace_path is not None:
        print(f"trace_file: {trace_path}")
    runtime = None
    observability_snapshot = capture_observability() if trace_path is not None else None
    try:
        if trace_path is not None:
            configure_observability(
                trace_sink=TraceJSONLSink(trace_path),
                trace_scopes=trace_scopes,
            )
        services = _create_services(workspace)
        model = _resolve_scenario_model(services, args)
        tool_registry = _create_tool_registry(services)
        print(f"model: {model.provider_id}/{model.endpoint_id}/{model.id}")
        print(f"case: {args.case}")
        print(f"description: {scenario['description']}")
        if scenario.get("allowed_tool_names") is not None:
            print(f"allowed_tools: {', '.join(scenario['allowed_tool_names'])}")
        runtime = create_agent_session_runtime(
            session_dir=session_dir,
            model=model,
            stream_fn=_create_stream_fn(trace_provider=_stdout_trace_scope_enabled(args, "provider")),
            tool_registry=tool_registry,
            services=services,
            allowed_tool_names=scenario.get("allowed_tool_names"),
            active_tool_names=scenario.get("active_tool_names"),
            persist=True,
        )
        session = await runtime.new_session(cwd=workspace)
        collector = TranscriptCollector()
        unsubscribe = session.subscribe(collector)

        try:
            with log_context(session_id=getattr(session, "session_id", None), cwd=str(workspace), mode=f"scenario:{args.case}"):
                for index, prompt in enumerate(prompts, start=1):
                    turn = collector.start_turn(prompt)
                    print(f"\n[{index}/{len(prompts)}] user: {prompt}", flush=True)
                    try:
                        await _run_turn(session, prompt, timeout_seconds=args.turn_timeout)
                    except TimeoutError:
                        turn.assistant_errors.append(
                            f"turn timed out after {args.turn_timeout:.1f}s"
                        )
                        await _abort_session(session)
                        _print_turn_summary(turn)
                        break
                    finally:
                        collector.end_turn()
                    _print_turn_summary(turn)
        finally:
            unsubscribe()

        failures = _validate_scenario(
            workspace,
            collector.turns,
            expect_python=bool(scenario["expect_python"]),
            expect_html=bool(scenario["expect_html"]),
        )
        if failures:
            print("\nFAIL")
            for failure in failures:
                print(f"- {failure}")
            if cleanup:
                print("\ntemporary workspace will be removed")
            else:
                print(f"\nworkspace kept for inspection: {workspace}")
            return 1

        print("\nPASS")
        if scenario["expect_python"]:
            print(f"- generated: {workspace / 'tmp' / 'bmi.py'}")
        if scenario["expect_html"]:
            print(f"- generated: {workspace / 'tmp' / 'bmi.html'}")
        print(f"- session: {_session_file(session)}")
        if cleanup:
            print("- temporary workspace will be removed")
        else:
            print(f"- workspace kept for inspection: {workspace}")
        return 0
    finally:
        if observability_snapshot is not None:
            restore_observability(observability_snapshot)
        if runtime is not None:
            await runtime.dispose()
        if cleanup:
            shutil.rmtree(workspace, ignore_errors=True)


def _resolve_workspace(raw_cwd: str | None) -> tuple[Path, bool]:
    if raw_cwd:
        workspace = Path(raw_cwd).expanduser().resolve(strict=False)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace, False
    return Path(tempfile.mkdtemp(prefix="loushang-kimi-bmi-")).resolve(), True


async def _run_turn(session: Any, prompt: str, *, timeout_seconds: float) -> None:
    if timeout_seconds <= 0:
        await session.prompt(prompt)
        await session.wait_for_idle()
        return
    await asyncio.wait_for(session.prompt(prompt), timeout=timeout_seconds)
    await asyncio.wait_for(session.wait_for_idle(), timeout=timeout_seconds)


async def _abort_session(session: Any) -> None:
    for method_name in ("abort", "abort_bash"):
        method = getattr(session, method_name, None)
        if callable(method):
            result = method()
            if asyncio.iscoroutine(result):
                await result
    wait_for_idle = getattr(session, "wait_for_idle", None)
    if callable(wait_for_idle):
        try:
            result = wait_for_idle()
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=5)
        except TimeoutError:
            pass


def _create_services(workspace: Path):
    settings_manager = SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
    )
    return create_services(
        ai_model_registry=get_default_model_registry(),
        settings_manager=settings_manager,
        default_model=DEFAULT_MODEL,
    )


def _resolve_scenario_model(services: Any, args: argparse.Namespace):
    registry = services.model_registry.ai_registry
    endpoint = getattr(args, "endpoint", DEFAULT_ENDPOINT)
    return registry.get_model(args.provider, endpoint, args.model)


def _create_stream_fn(*, trace_provider: bool):
    if not trace_provider:
        return None

    async def _stream(model: object, context: object, options: object | None = None):
        traced_options = (
            replace(options, trace=_print_provider_trace)
            if options is not None
            else SimpleStreamOptions(trace=_print_provider_trace)
        )
        return await stream_simple(model, context, traced_options)

    return _stream


def _print_provider_trace(event: object) -> None:
    if not isinstance(event, dict):
        return
    event_type = event.get("type")
    if event_type == "sdk:payload":
        params = event.get("params")
        if isinstance(params, dict):
            print(
                f"  trace: {json.dumps(_compact_trace_payload(params), ensure_ascii=False, default=str)}",
                flush=True,
            )
        return
    if isinstance(event_type, str) and event_type.startswith("sdk:tool_"):
        print(
            f"  trace: {json.dumps(event, ensure_ascii=False, default=str)}",
            flush=True,
        )


def _compact_trace_payload(params: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {
        "type": "sdk:payload",
        "model": params.get("model"),
        "max_tokens": params.get("max_tokens"),
    }
    tools = params.get("tools")
    if isinstance(tools, list):
        compact["tools"] = [_compact_trace_tool(tool) for tool in tools]
    tool_choice = params.get("tool_choice")
    if tool_choice is not None:
        compact["tool_choice"] = tool_choice
    return compact


def _compact_trace_tool(tool: object) -> object:
    if not isinstance(tool, dict):
        return tool
    return {
        "name": tool.get("name"),
        "input_schema": tool.get("input_schema"),
    }


def _create_tool_registry(services: Any) -> ToolRegistry:
    registry = ToolRegistry()
    tool_settings = _tool_settings(services.settings_manager)
    get_external_tool_policy = getattr(services.settings_manager, "get_external_tool_policy", None)
    register_builtin_tools(
        registry,
        diagnostics_service=services.diagnostics_service,
        exec_service=services.exec_service,
        policy_engine=_policy_engine_from_tool_settings(tool_settings),
        approval_resolver=_approval_resolver_from_tool_settings(tool_settings),
        external_tool_policy=get_external_tool_policy()
        if callable(get_external_tool_policy)
        else None,
    )
    return registry


def _tool_settings(settings_manager: object) -> object | None:
    getter = getattr(settings_manager, "get_tool_settings", None)
    if callable(getter):
        return getter()
    return None


def _policy_engine_from_tool_settings(tool_settings: object | None) -> PolicyEngine | None:
    if tool_settings is None:
        return None
    kwargs = {
        "blocked_tools": _tool_setting_tuple(tool_settings, "blocked_tools"),
        "ask_tools": _tool_setting_tuple(tool_settings, "ask_tools"),
        "blocked_substrings": _tool_setting_tuple(tool_settings, "blocked_substrings"),
        "ask_substrings": _tool_setting_tuple(tool_settings, "ask_substrings"),
        "blocked_path_substrings": _tool_setting_tuple(tool_settings, "blocked_path_substrings"),
        "ask_path_substrings": _tool_setting_tuple(tool_settings, "ask_path_substrings"),
    }
    if not any(kwargs.values()):
        return None
    return PolicyEngine(**kwargs)


def _approval_resolver_from_tool_settings(
    tool_settings: object | None,
) -> HeadlessApprovalResolver | None:
    if tool_settings is None:
        return None
    approval_mode = getattr(tool_settings, "approval_mode", None)
    if approval_mode is None:
        return None
    return HeadlessApprovalResolver(
        mode=approval_mode,
        reason=getattr(tool_settings, "approval_reason", None),
    )


def _tool_setting_tuple(tool_settings: object, name: str) -> tuple[str, ...]:
    value = getattr(tool_settings, name, ())
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _print_turn_summary(turn: TurnSummary) -> None:
    tools = ", ".join(turn.tool_calls) if turn.tool_calls else "none"
    assistant = _first_line(turn.assistant_text) or "no assistant text"
    print(f"  tools: {tools}")
    print(f"  assistant: {assistant}")
    for error in [*turn.tool_errors, *turn.assistant_errors]:
        print(f"  error: {_first_line(error)}")


def _validate_scenario(
    workspace: Path,
    turns: list[TurnSummary],
    *,
    expect_python: bool,
    expect_html: bool,
) -> list[str]:
    failures: list[str] = []
    python_file = workspace / "tmp" / "bmi.py"
    html_file = workspace / "tmp" / "bmi.html"
    if expect_python and not python_file.is_file():
        failures.append(f"missing generated file: {python_file}")
    if expect_html and not html_file.is_file():
        failures.append(f"missing generated file: {html_file}")
    if expect_python and expect_html and python_file == html_file:
        failures.append("python and html outputs resolved to the same path")
    if (
        expect_python
        and python_file.is_file()
        and "bmi" not in python_file.read_text(encoding="utf-8", errors="ignore").lower()
    ):
        failures.append(f"generated python file does not look like a BMI program: {python_file}")
    if (
        expect_html
        and html_file.is_file()
        and "<html" not in html_file.read_text(encoding="utf-8", errors="ignore").lower()
    ):
        failures.append(f"generated html file does not look like HTML: {html_file}")

    tail_turns = turns[-2:]
    for turn in tail_turns:
        if not turn.assistant_text:
            failures.append(f"final prompt did not receive an assistant response: {turn.prompt}")
        if turn.assistant_errors:
            failures.append(f"final prompt ended with assistant error: {turn.prompt}")

    all_errors = [
        error
        for turn in turns
        for error in [*turn.tool_errors, *turn.assistant_errors]
    ]
    unexpected_errors = [
        error
        for error in all_errors
        if RECOVERY_VALIDATION_ERROR not in error
    ]
    if unexpected_errors:
        failures.append(f"unexpected error surfaced: {_first_line(unexpected_errors[0])}")

    repeated_write_validation_errors = [
        error
        for error in all_errors
        if RECOVERY_VALIDATION_ERROR in error
    ]
    if len(repeated_write_validation_errors) > 1:
        failures.append(
            f"write validation error repeated {len(repeated_write_validation_errors)} times"
        )

    return failures


def _assistant_text(message: AssistantMessage) -> str:
    return "\n".join(
        part.text
        for part in message.content
        if isinstance(part, TextPart) and part.text
    ).strip()


def _assistant_error(message: AssistantMessage) -> str | None:
    if message.stop_reason not in {"error", "aborted"}:
        return None
    return message.error_message or f"request {message.stop_reason}"


def _tool_result_text(result: object) -> str:
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        return ""
    return "\n".join(
        part.text
        for part in content
        if isinstance(part, TextPart) and part.text
    ).strip()


def _tool_call_summary(tool_name: str, args: object) -> str:
    if not isinstance(args, dict):
        return tool_name
    if not args:
        return f"{tool_name} {{}}"

    parts: list[str] = []
    for key in ("path", "file_path", "command", "pattern", "query"):
        value = args.get(key)
        if isinstance(value, str) and value:
            parts.append(f"{key}={_short_inline(value)}")
            break

    content = args.get("content")
    if isinstance(content, str):
        parts.append(f"content={len(content)} chars")
    elif "content" in args:
        parts.append(f"content=<{type(content).__name__}>")

    if not parts:
        return tool_name
    return f"{tool_name} {' '.join(parts)}"


def _short_inline(value: str, *, limit: int = 80) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    if len(line) <= 140:
        return line
    return line[:137] + "..."


def _session_file(session: object) -> str:
    manager = getattr(session, "session_manager", None)
    if isinstance(manager, SessionManager):
        return str(manager.get_session_file())
    return "unknown"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a real Kimi coding session that should generate separate "
            "tmp/bmi.py and tmp/bmi.html files, then continue chatting."
        )
    )
    parser.add_argument(
        "--cwd",
        help="Workspace to run in. Defaults to a kept temporary directory.",
    )
    parser.add_argument(
        "--session-dir",
        help="Session directory. Defaults to <workspace>/.loushang/scenario-sessions.",
    )
    parser.add_argument("--provider", default=DEFAULT_MODEL.provider)
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help="Model endpoint used to disambiguate provider/model pairs.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL.model_id)
    parser.add_argument(
        "--case",
        choices=tuple(SCENARIOS),
        default="full-bmi-recovery",
        help="Scenario to run.",
    )
    parser.add_argument(
        "--turn-timeout",
        type=float,
        default=360.0,
        help="Seconds to wait for each prompt turn. Use 0 to disable.",
    )
    parser.add_argument(
        "--trace",
        nargs="?",
        const="all",
        default="",
        help="Comma-separated scenario trace scopes. Currently supports: provider. Without --trace-file, provider traces are printed to stdout.",
    )
    parser.add_argument(
        "--trace-file",
        help="Write structured trace JSONL to PATH. If --trace is omitted, this implies provider trace scope.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove the temporary workspace after a successful or failed run.",
    )
    return parser.parse_args(argv)


def _stdout_trace_scope_enabled(args: argparse.Namespace, scope: str) -> bool:
    scopes = _explicit_trace_scopes(args)
    return scope in scopes or "all" in scopes


def _trace_scopes(args: argparse.Namespace) -> frozenset[str]:
    scopes = _explicit_trace_scopes(args)
    if not scopes and getattr(args, "trace_file", None):
        return frozenset({"provider"})
    return scopes


def _explicit_trace_scopes(args: argparse.Namespace) -> frozenset[str]:
    raw = str(getattr(args, "trace", "") or "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def _trace_file_path(args: argparse.Namespace, workspace: Path) -> Path:
    raw = Path(args.trace_file).expanduser()
    if raw.is_absolute():
        return raw.resolve(strict=False)
    return (workspace / raw).resolve(strict=False)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(run_scenario(args))


if __name__ == "__main__":
    raise SystemExit(main())
