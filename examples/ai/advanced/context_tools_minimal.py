"""高级示例：形式化 Context 与 Tool 类型的最小演示。

这个示例主要用于说明：
- `Context` / `Tool` / `UserMessage` 这些显式类型如何组合
- 自定义 faux provider 时，如何在本地构造可运行示例

它不是第一次接入 `loushang.ai` 的推荐入口。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from loushang.ai import Context, Model, Tool, UserMessage, stream
from loushang.ai.advanced.registry import clear_api_adapters, register_api_adapter
from loushang.ai.model import Auth, Capabilities
from loushang.ai.protocols.faux import FauxAdapter


def _build_model() -> Model:
    # 这个 faux 模型只用于演示正式类型对象如何参与调用，不代表真实线上模型。
    return Model(
        id="faux-model",
        provider="faux",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        base_url="https://example.invalid/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(stream=True, tool_use=True),
    )


def _build_context() -> Context:
    # 这里刻意使用显式 Context / Tool / UserMessage 类型，
    # 用来演示正式类型对象如何构造，而不是走最短 dict 形式。
    return Context(
        system_prompt="You are a tool-using assistant.",
        messages=[
            UserMessage(role="user", content="Please solve this.", timestamp=0.0)
        ],
        tools=[
            Tool(
                name="calc",
                description="Calculate numeric expressions",
                parameters={
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                    },
                    "required": ["expression"],
                },
            )
        ],
    )


def _iter_text(parts: Iterable[object]) -> str:
    # 把最终消息中的 text 片段拼接起来，便于终端输出。
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


async def _main() -> None:
    # 这是高级场景：本地构造 faux 模型并手动注入 faux provider。
    clear_api_adapters()
    register_api_adapter(FauxAdapter())

    event_stream = await stream(
        _build_model(),
        _build_context(),
    )

    # 运行时主要观察 event 类型，确认 context 和 tools 已被正确消费。
    print("MODE context-tools-minimal")
    async for event in event_stream:
        print(f"EVENT {event['type']}")

    message = await event_stream.result()
    print(f"FINAL stop_reason={message.stop_reason!r}")
    print(f"FINAL text={_iter_text(message.content)!r}")


if __name__ == "__main__":
    asyncio.run(_main())
