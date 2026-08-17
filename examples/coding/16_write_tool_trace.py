from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    build_kimi_model,
    create_kimi_runtime_session,
    describe_model,
)

from loushang.coding import ToolRegistry, register_builtin_tools

EXAMPLE_REQUEST = "请生成一个手机登录的页面，放在 demo/index.html"
HEARTBEAT_SECONDS = 5.0


def _coding_prompt(user_request: str) -> str:
    return (
        "你是一个可以修改当前工作目录文件的编程助手。\n"
        "你有 bash 和 write 工具可用。\n"
        "当前 demo 目录已经存在；除非用户要求其他目录，否则直接写 demo/index.html。\n"
        "需要写文件时，优先调用 write 工具，参数必须包含 path 和 content。\n"
        "如果 write 工具失败，必须改用 bash 和 shell 重定向重试。\n"
        "完成后用 bash 验证结果，例如 `ls -la demo`，必要时用 `sed -n` 查看文件开头。\n"
        "不要只描述方案；必须实际创建用户要求的文件。\n"
        "最后用一句话说明创建了哪些文件。\n\n"
        f"用户请求：{user_request}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a coding example with readable assistant/tool trace output.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Example:\n"
            "  uv run python examples/coding/16_write_tool_trace.py "
            f'"{EXAMPLE_REQUEST}"'
        ),
    )
    parser.add_argument(
        "request",
        nargs="*",
        help="Natural-language coding request. Defaults to writing demo/index.html.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Maximum seconds to wait for the coding turn. Use 0 to disable. Defaults to 120.",
    )
    return parser


class TracePrinter:
    def __init__(self) -> None:
        self._start = time.monotonic()

    def __call__(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "message_update":
            self._print_assistant_update(event)
            return
        if event_type == "tool_execution_start":
            self._print_tool_start(event)
            return
        if event_type == "tool_execution_update":
            self._print_tool_update(event)
            return
        if event_type == "tool_execution_end":
            self._print_tool_end(event)
            return
        if event_type == "message_end":
            self._print_message_end(event)

    def _prefix(self) -> str:
        return f"[+{time.monotonic() - self._start:07.3f}s]"

    def _print_assistant_update(self, event: dict[str, Any]) -> None:
        assistant_event = event.get("assistant_message_event")
        if not isinstance(assistant_event, dict):
            return
        event_type = assistant_event.get("type")
        if event_type == "text_delta":
            delta = assistant_event.get("delta")
            if isinstance(delta, str) and delta:
                print(f"{self._prefix()} [assistant:delta] {delta}", flush=True)
            return
        if event_type == "toolcall_start":
            message = event.get("message")
            tool_call = _tool_call_from_message(message)
            name = getattr(tool_call, "name", None) if tool_call is not None else None
            print(f"{self._prefix()} [assistant:toolcall_start] {name or '<pending>'}", flush=True)
            return
        if event_type == "toolcall_delta":
            delta = assistant_event.get("delta")
            if isinstance(delta, str) and delta:
                print(f"{self._prefix()} [assistant:toolcall_delta] {delta}", flush=True)
            return
        if event_type == "toolcall_end":
            tool_call = assistant_event.get("tool_call")
            if tool_call is None:
                message = event.get("message")
                tool_call = _tool_call_from_message(message)
            name = getattr(tool_call, "name", None)
            args = getattr(tool_call, "arguments", None)
            print(f"{self._prefix()} [assistant:toolcall_end] {name} {_json(args)}", flush=True)

    def _print_tool_start(self, event: dict[str, Any]) -> None:
        print(
            f"{self._prefix()} [tool:start] {event.get('tool_name')} {_json(event.get('args'))}",
            flush=True,
        )

    def _print_tool_update(self, event: dict[str, Any]) -> None:
        result = event.get("partial_result")
        text = _tool_result_text(result)
        if text:
            print(f"{self._prefix()} [tool:update] {_one_line(text)}", flush=True)

    def _print_tool_end(self, event: dict[str, Any]) -> None:
        result = event.get("result")
        status = "error" if event.get("is_error") else "ok"
        text = _tool_result_text(result)
        print(
            f"{self._prefix()} [tool:end] {event.get('tool_name')} {status} {_one_line(text)}",
            flush=True,
        )

    def _print_message_end(self, event: dict[str, Any]) -> None:
        message = event.get("message")
        if getattr(message, "role", None) != "assistant":
            return
        text = _message_text(message)
        if text:
            print(f"{self._prefix()} [assistant:final] {_one_line(text)}", flush=True)


def _tool_call_from_message(message: object) -> object | None:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return None
    for part in reversed(content):
        if getattr(part, "type", None) == "toolCall":
            return part
    return None


def _message_text(message: object) -> str:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return ""
    return "".join(
        part.text
        for part in content
        if getattr(part, "type", None) == "text" and isinstance(getattr(part, "text", None), str)
    )


def _tool_result_text(result: object) -> str:
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        return ""
    return "".join(
        part.text
        for part in content
        if getattr(part, "type", None) == "text" and isinstance(getattr(part, "text", None), str)
    )


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(value)


def _one_line(text: str, *, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


async def _prompt_with_heartbeat(session: object, user_input: str, *, timeout_seconds: float) -> int:
    trace_start = time.monotonic()
    deadline = None if timeout_seconds <= 0 else trace_start + timeout_seconds
    prompt = getattr(session, "prompt")
    wait_for_idle = getattr(session, "wait_for_idle")
    task = asyncio.create_task(prompt(user_input))
    print("[trace] request sent to model; waiting for first assistant/tool event...", flush=True)

    while not task.done():
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            print(f"[trace] timeout after {timeout_seconds:.1f}s before the turn completed", file=sys.stderr)
            return 124

        wait_seconds = HEARTBEAT_SECONDS
        if deadline is not None:
            wait_seconds = min(wait_seconds, max(0.1, deadline - now))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
        except TimeoutError:
            elapsed = time.monotonic() - trace_start
            print(f"[trace] still waiting for model... {elapsed:.1f}s", flush=True)

    await task
    await wait_for_idle()
    return 0


async def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    user_request = " ".join(args.request).strip() or EXAMPLE_REQUEST
    (Path.cwd() / "demo").mkdir(exist_ok=True)

    model = build_kimi_model()
    model_info = describe_model(model)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    runtime, session = await create_kimi_runtime_session(
        cwd=Path.cwd(),
        model=model,
        tools=[registry.get_tool("bash"), registry.get_tool("write")],
        persist=False,
    )

    print("=== Write Tool Trace ===")
    print(f"Provider: {model_info['provider']}")
    print(f"Model: {model_info['model']}")
    print(f"Endpoint: {model_info['endpoint']}")
    print(f"API: {model_info['api']}")
    print(f"Base URL: {model_info['base_url']}")
    print(f"CWD: {session.session_manager.get_cwd()}")
    print("Prepared: demo/")
    print("Tools: bash, write")
    print(f"Timeout: {args.timeout:g}s" if args.timeout > 0 else "Timeout: disabled")
    print(f"Request: {user_request}")
    print()

    unsubscribe = session.subscribe(TracePrinter())
    try:
        exit_code = await _prompt_with_heartbeat(
            session,
            _coding_prompt(user_request),
            timeout_seconds=args.timeout,
        )
    finally:
        unsubscribe()
        await runtime.dispose()

    raise SystemExit(exit_code)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
