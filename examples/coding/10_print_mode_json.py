from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import build_kimi_model, create_kimi_runtime_session

from loushang.coding import (
    register_coding_builtin_tools as register_builtin_tools,
)
from loushang.coding import (
    run_print_mode,
)
from loushang.harness.events import select_events
from loushang.harness.tools.workspace.registry import (
    WorkspaceToolRegistry as ToolRegistry,
)

EXAMPLE_REQUEST = (
    "当前目录有哪些文件？"
    "如果有 docs 目录，列出 docs 目录中的文件；"
    "如果有 README.md，请摘要 README.md。"
)


def _tool_enforced_prompt(user_request: str) -> str:
    return (
        "你有一个可用的 bash 工具。\n"
        "如果用户的问题涉及当前目录、文件列表、路径、文件是否存在、文件内容、"
        "或任何可以通过 shell 验证的本地事实，你必须先调用 bash 工具，再回答。"
        "不要猜测，也不要凭记忆回答。\n"
        "例如：\n"
        "- “当前是什么目录” 应先调用 `pwd`\n"
        "- “当前目录有哪些文件” 应先调用 `ls -1`\n"
        "- “README.md 里写了什么” 应先调用 `cat README.md`\n"
        "在调用工具后，基于真实输出给出简短回答。\n\n"
        f"用户请求：{user_request}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the coding print mode in JSON event-stream mode.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python examples/coding/10_print_mode_json.py '
            f'"{EXAMPLE_REQUEST}"\n'
            '  python examples/coding/10_print_mode_json.py '
            f'--event-view compact "{EXAMPLE_REQUEST}"\n'
            '  python examples/coding/10_print_mode_json.py '
            f'--event-view tools --render-tool-events "{EXAMPLE_REQUEST}"\n'
            '  python examples/coding/10_print_mode_json.py '
            f'--event-view compact --select assistant.delta --select assistant.final "{EXAMPLE_REQUEST}"\n'
            '  python examples/coding/10_print_mode_json.py '
            f'"{EXAMPLE_REQUEST}" | jq .'
        ),
    )
    parser.add_argument(
        "--event-view",
        choices=("full", "compact", "assistant_stream", "tools", "final"),
        default="full",
        help="Projected JSON event view to stream. Defaults to full.",
    )
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Optional event selector pattern. Repeat to keep multiple event types, "
            'for example: --select assistant.delta --select assistant.final'
        ),
    )
    parser.add_argument(
        "--render-tool-events",
        action="store_true",
        help="Attach renderedToolCall/renderedToolResult payloads to JSON tool events.",
    )
    parser.add_argument(
        "request",
        nargs="+",
        help="Natural-language request to send to the coding session.",
    )
    return parser


async def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    user_request = " ".join(args.request).strip()
    if not user_request:
        raise SystemExit(2)

    registry = ToolRegistry()
    register_builtin_tools(registry)
    runtime, session = await create_kimi_runtime_session(
        cwd=Path.cwd(),
        model=build_kimi_model(),
        tools=registry.list_enabled_tools(),
        persist=False,
    )

    try:
        exit_code = await run_print_mode(
            runtime=runtime,
            session=session,
            user_input=_tool_enforced_prompt(user_request),
            stdout=sys.stdout,
            stderr=sys.stderr,
            output_mode="json",
            event_view=args.event_view,
            event_select=select_events(*args.select) if args.select else None,
            render_tool_events=args.render_tool_events,
        )
    finally:
        await runtime.dispose()

    raise SystemExit(exit_code)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
