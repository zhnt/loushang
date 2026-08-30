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

EXAMPLE_REQUEST = "请生成一个手机登录的页面，放在 demo 下"


def _coding_prompt(user_request: str) -> str:
    return (
        "你是一个可以修改当前工作目录文件的编程助手。\n"
        "你有 bash 和 write 工具可用。\n"
        "需要写文件时，优先调用 write 工具，参数必须包含 path 和 content。\n"
        "需要创建目录时，先调用 bash，例如 `mkdir -p demo`。\n"
        "如果 write 工具失败，必须改用 bash 和 shell 重定向重试，例如 `cat > path <<'EOF' ... EOF`。\n"
        "完成后必须再调用 bash 验证结果，例如 `ls -la demo`，必要时用 `sed -n` 查看文件开头。\n"
        "不要只描述方案；必须实际创建用户要求的文件。\n"
        "最后用一句话说明创建了哪些文件。\n\n"
        f"用户请求：{user_request}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a simple coding example that writes files through bash.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Example:\n"
            "  uv run python examples/coding/14_simple_code_writer.py "
            f'"{EXAMPLE_REQUEST}"'
        ),
    )
    parser.add_argument(
        "request",
        nargs="*",
        help=(
            "Natural-language coding request. Defaults to creating a mobile login page "
            "under demo/."
        ),
    )
    return parser


async def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    user_request = " ".join(args.request).strip() or EXAMPLE_REQUEST

    model = build_kimi_model()
    model_info = describe_model(model)
    runtime, session = await create_kimi_runtime_session(
        cwd=Path.cwd(),
        model=model,
        active_tool_names=["bash", "write"],
        persist=False,
    )

    print("=== Simple Code Writer ===")
    print(f"Provider: {model_info['provider']}")
    print(f"Model: {model_info['model']}")
    print(f"Endpoint: {model_info['endpoint']}")
    print(f"API: {model_info['api']}")
    print(f"Base URL: {model_info['base_url']}")
    print(f"CWD: {session.session_manager.get_cwd()}")
    print("Output mode: text")
    print("Tools: bash, write")
    print(f"Request: {user_request}")
    print()

    try:
        exit_code = await run_print_mode(
            runtime=runtime,
            session=session,
            user_input=_coding_prompt(user_request),
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
