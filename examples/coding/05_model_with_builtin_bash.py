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


async def main() -> None:
    model = build_kimi_model()
    model_info = describe_model(model)

    session = create_kimi_session(
        model=model,
    )
    attach_stream_printer(session)

    print("=== Coding Session With Built-In Bash Tool ===")
    print(f"Provider: {model_info['provider']}")
    print(f"Model: {model_info['model']}")
    print(f"Endpoint: {model_info['endpoint']}")
    print(f"API: {model_info['api']}")
    print(f"Base URL: {model_info['base_url']}")
    print(f"CWD: {session.session_manager.get_cwd()}")
    print("Tools: bash")
    print()

    await session.prompt(
        "必须调用 bash 工具执行 `pwd`。"
        "不要猜测结果，也不要直接回答。"
        "先调用工具，再原样返回工具输出，并用一句话说明这是当前工作目录。"
    )
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
