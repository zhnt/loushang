from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    build_kimi_model,
    create_kimi_runtime_session,
    describe_model,
)

from loushang.harnesstui.conversation.agent_binding import (
    run_agent_plain_mode as run_print_mode,
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
        description="Run the coding print mode in text output mode.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Example:\n"
            '  python examples/coding/09_print_mode_text.py '
            f'"{EXAMPLE_REQUEST}"'
        ),
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

    model = build_kimi_model()
    model_info = describe_model(model)
    runtime, session = await create_kimi_runtime_session(
        cwd=Path.cwd(),
        model=model,
        persist=False,
    )

    print("=== Print Mode (text) ===")
    print(f"Provider: {model_info['provider']}")
    print(f"Model: {model_info['model']}")
    print(f"Endpoint: {model_info['endpoint']}")
    print(f"API: {model_info['api']}")
    print(f"Base URL: {model_info['base_url']}")
    print(f"CWD: {session.session_manager.get_cwd()}")
    print("Output mode: text")
    print("Tools: bash")
    print(f"Request: {user_request}")
    print()

    try:
        exit_code = await run_print_mode(
            runtime=runtime,
            session=session,
            user_input=_tool_enforced_prompt(user_request),
            stdout=sys.stdout,
            stderr=sys.stderr,
            output_mode="text",
        )
    finally:
        await runtime.dispose()

    raise SystemExit(exit_code)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
