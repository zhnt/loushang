"""Create a small synthetic embedded-resume seed outside startup measurement."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


async def prepare(root: Path, workspace: Path) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.coding.session_manager import SessionManager

    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    manager = await SessionManager.new(
        session_dir=root, cwd=str(workspace), persist=True
    )
    try:
        for index in range(16):
            await manager.append_message(
                UserMessage(
                    role="user",
                    content=f"G18 history request {index}",
                    timestamp=float(index),
                )
            )
            await manager.append_message(
                AssistantMessage(
                    role="assistant",
                    content=[
                        TextPart(type="text", text=f"G18 history sentinel {index}")
                    ],
                    api="openai-completions",
                    endpoint="openai-completions-cn",
                    provider="baidu-qianfan",
                    model="ernie-5.1",
                    response_id=None,
                    usage=Usage(
                        input=0,
                        output=0,
                        cache_read=0,
                        cache_write=0,
                        total_tokens=0,
                        cost={},
                    ),
                    stop_reason="stop",
                    error_message=None,
                    timestamp=float(index),
                )
            )
    finally:
        await manager.dispose_runtime_profile()
    print(
        json.dumps(
            dict(
                session_file=str(manager.get_session_file()),
                session_id=manager.get_header().conversation_id,
            )
        )
    )


if __name__ == "__main__":
    asyncio.run(prepare(Path(sys.argv[1]), Path(sys.argv[2])))
