"""高级示例：本地 faux provider 的流式协议演示。

适用场景：
- 调试统一事件流协议
- 不依赖真实厂商网络，直接观察 assembler 输出

不适合：
- 作为真实 provider 接入示例
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from loushang.ai import CallOptions, Model, ReasoningOptions, stream
from loushang.ai.advanced.registry import clear_api_adapters, register_api_adapter
from loushang.ai.model import Auth, Capabilities
from loushang.ai.protocols.faux import FauxAdapter


def _build_model() -> Model:
    # faux 模型用于稳定产出多种事件，方便观察统一事件流协议。
    return Model(
        id="faux-model",
        provider="faux",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        base_url="https://example.invalid/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(stream=True, reasoning=True),
    )


def _build_context() -> dict:
    return {"messages": []}


def _build_options() -> CallOptions:
    # reasoning 等调用行为走 CallOptions，context 只保留 system_prompt/messages/tools。
    return CallOptions(reasoning=ReasoningOptions(enabled=True))


def _iter_text(parts: Iterable[object]) -> str:
    # 最终消息依然按公共 content 协议返回，这里只提取 text 片段。
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


async def _main() -> None:
    # 高级路径：手动注入 faux provider，而不是走 builtin provider。
    clear_api_adapters()
    register_api_adapter(FauxAdapter())

    event_stream = await stream(
        _build_model(),
        _build_context(),
        _build_options(),
    )

    # 运行时可观察不同事件类型如何被统一协议表达。
    print("MODE faux-stream")
    async for event in event_stream:
        event_type = event["type"]
        if event_type == "text_delta":
            print(f"EVENT {event_type} delta={event['delta']!r}")
        elif event_type == "thinking_delta":
            part = event["partial"].content[event["content_index"]]
            print(f"EVENT {event_type} thinking={part.thinking!r}")
        else:
            print(f"EVENT {event_type}")

    message = await event_stream.result()
    print(f"FINAL stop_reason={message.stop_reason!r}")
    print(f"FINAL text={_iter_text(message.content)!r}")


if __name__ == "__main__":
    asyncio.run(_main())
