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

EXAMPLE_REQUEST = "请生成一个手机登录的页面，放在 demo/index.html"


def _write_only_prompt(user_request: str) -> str:
    return (
        "你是一个可以写文件的编程助手。\n"
        "你只有 write 工具可用，没有 bash 工具。\n"
        "用户要求创建页面或代码时，必须直接调用 write 工具写入文件。\n"
        "write 工具参数必须包含：\n"
        "- path: 要写入的相对路径，例如 demo/index.html\n"
        "- content: 完整文件内容\n"
        "不要只描述方案；必须实际调用 write 工具。\n"
        "当前 demo 目录已经存在，可以直接写 demo/index.html。\n"
        "最后用一句话说明写入的文件路径。\n\n"
        f"用户请求：{user_request}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a minimal coding example that writes files with the write tool only.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Example:\n"
            "  uv run python examples/coding/15_simple_write_tool.py "
            f'"{EXAMPLE_REQUEST}"'
        ),
    )
    parser.add_argument(
        "request",
        nargs="*",
        help="Natural-language coding request. Defaults to writing demo/index.html.",
    )
    return parser


async def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    user_request = " ".join(args.request).strip() or EXAMPLE_REQUEST
    (Path.cwd() / "demo").mkdir(exist_ok=True)

    model = build_kimi_model()
    model_info = describe_model(model)
    runtime, session = await create_kimi_runtime_session(
        cwd=Path.cwd(),
        model=model,
        active_tool_names=["write"],
        persist=False,
    )

    print("=== Simple Write Tool ===")
    print(f"Provider: {model_info['provider']}")
    print(f"Model: {model_info['model']}")
    print(f"Endpoint: {model_info['endpoint']}")
    print(f"API: {model_info['api']}")
    print(f"Base URL: {model_info['base_url']}")
    print(f"CWD: {session.session_manager.get_cwd()}")
    print("Prepared: demo/")
    print("Output mode: text")
    print("Tools: write")
    print(f"Request: {user_request}")
    print()

    try:
        exit_code = await run_print_mode(
            runtime=runtime,
            session=session,
            user_input=_write_only_prompt(user_request),
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
