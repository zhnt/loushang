from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    attach_stream_printer,
    build_kimi_model,
    create_kimi_session,
    describe_model,
)

EXAMPLE_REQUEST = (
    "当前目录有哪些文件？"
    "如果有 docs 目录，列出 docs 目录中的文件；"
    "如果有 README.md，请摘要 README.md。"
)


def _tool_enforced_prompt(user_request: str) -> str:
    return (
        "你有一个可用的 bash 工具。\n"
        "如果用户的问题涉及当前目录、文件列表、路径、文件是否存在、或任何可以通过 shell 验证的本地事实，"
        "你必须先调用 bash 工具，再回答。不要猜测，也不要凭记忆回答。\n"
        "例如：\n"
        "- “当前是什么目录” 应先调用 `pwd`\n"
        "- “当前目录有哪些文件” 应先调用 `ls -1`\n"
        "在调用工具后，基于真实输出给出简短回答。\n\n"
        f"用户请求：{user_request}"
    )


async def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "Usage:\n"
            '  python examples/coding/06_nl_with_builtin_bash.py "<natural-language request>"\n\n'
            "Example:\n"
            f'  python examples/coding/06_nl_with_builtin_bash.py "{EXAMPLE_REQUEST}"',
            file=sys.stderr,
        )
        raise SystemExit(2)

    user_request = " ".join(args).strip()
    if not user_request:
        print("Natural-language request must not be empty.", file=sys.stderr)
        raise SystemExit(2)

    model = build_kimi_model()
    model_info = describe_model(model)

    session = create_kimi_session(
        model=model,
    )
    attach_stream_printer(session)

    print("=== Coding Session With Natural-Language Bash Tool Routing ===")
    print(f"Provider: {model_info['provider']}")
    print(f"Model: {model_info['model']}")
    print(f"Endpoint: {model_info['endpoint']}")
    print(f"API: {model_info['api']}")
    print(f"Base URL: {model_info['base_url']}")
    print(f"CWD: {session.session_manager.get_cwd()}")
    print("Tools: bash")
    print(f"Request: {user_request}")
    print()

    await session.prompt(_tool_enforced_prompt(user_request))
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
