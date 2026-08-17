"""高级示例：本地 faux provider 的 tool-result roundtrip。

这个示例只关注协议往返：
1. 构造上一轮 assistant `toolCall`
2. 当前轮回传 `ToolResultMessage`

它适合调试工具协议，不适合作为第一次接入参考。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from loushang.ai import (
    AssistantMessage,
    Model,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    complete,
)
from loushang.ai.advanced.registry import clear_api_adapters, register_api_adapter
from loushang.ai.model import Auth
from loushang.ai.protocols.faux import FauxAdapter


def _build_model() -> Model:
    # faux 模型用于本地验证 tool-result roundtrip，不依赖真实厂商网络。
    return Model(
        id="faux-model",
        provider="faux",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        base_url="https://example.invalid/v1",
        auth=Auth(kind="none"),
    )


def _iter_text(parts: Iterable[object]) -> str:
    # 把最终消息中的文本片段拼接起来，便于直接检查 roundtrip 结果。
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


def _previous_tool_call_message() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="anthropic-messages",
        provider="faux",
        endpoint="anthropic-messages",
        model="faux-model",
        response_id="faux-tool-call",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


async def _main() -> None:
    # 高级路径：显式注册 faux provider，避免依赖真实厂商网络。
    clear_api_adapters()
    register_api_adapter(FauxAdapter())

    model = _build_model()

    first = _previous_tool_call_message()
    tool_call = next(
        part for part in first.content if getattr(part, "type", None) == "toolCall"
    )

    print("ROUND 1")
    print(
        f"TOOL_CALL id={tool_call.id!r} name={tool_call.name!r} arguments={tool_call.arguments!r}"
    )

    second = await complete(
        model,
        {
            "messages": [
                first,
                # 第二轮显式回传工具结果，验证消息协议能否完整闭环。
                ToolResultMessage(
                    role="toolResult",
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    content=[TextPart(type="text", text="42")],
                    is_error=False,
                    timestamp=0.0,
                ),
            ]
        },
    )

    print("ROUND 2")
    print(f"FINAL stop_reason={second.stop_reason!r}")
    print(f"FINAL text={_iter_text(second.content)!r}")


if __name__ == "__main__":
    asyncio.run(_main())
