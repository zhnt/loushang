"""高级示例：DashScope tool roundtrip。

这个示例展示两轮调用：
1. 第一轮让模型发出 `toolCall`
2. 第二轮把本地工具结果包装成 `ToolResultMessage` 再回传给模型

适合：
- 理解工具调用协议
- 调试 tool roundtrip

不适合：
- 作为第一次接入 `loushang.ai` 的参考
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from loushang.ai import (
    CallOptions,
    TextPart,
    ToolResultMessage,
    complete,
    get_model,
)
from loushang.ai.auth import ApiKeyAuth

# 用户可直接修改的配置。
# 这是高级示例；重点在 tool 协议，不在最短接入路径。
API_KEY = ""
MODEL_ID = "qwen3.7-plus"
USER_PROMPT = "只调用工具，不要心算：使用 add 计算 78 + 35，并返回结果。"
MAX_TOKENS = 1024

PROVIDER_ID = "dashscope"
ENDPOINT_ID = "openai-responses"

pytestmark = [
    pytest.mark.live,
    pytest.mark.vendor_verification,
    pytest.mark.skipif(
        not (API_KEY or os.getenv("DASHSCOPE_API_KEY")),
        reason="DASHSCOPE_API_KEY not set; live DashScope verification skipped",
    ),
]


def _resolve_api_key() -> str:
    # 高级示例也保持同一认证入口，避免协议示例引入额外认证心智。
    value = API_KEY or os.getenv("DASHSCOPE_API_KEY")
    if value:
        return value
    raise RuntimeError(
        "Set API_KEY at the top of this file, or export DASHSCOPE_API_KEY."
    )


def _build_tools() -> list[dict]:
    # 示例工具保持最小可读形态：一个 add 函数，便于观察 tool 参数往返。
    return [
        {
            "name": "add",
            "description": "Return the sum of two numbers a and b.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "first number"},
                    "b": {"type": "number", "description": "second number"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        }
    ]


def _build_options(api_key: str) -> CallOptions:
    # tool roundtrip 与普通调用共用同一套认证和 token 控制方式。
    return CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=MAX_TOKENS)


async def _main() -> None:
    api_key = _resolve_api_key()
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)
    tools = _build_tools()

    # 第一轮：要求模型先决定是否调用工具。
    first = await complete(
        model,
        {
            "system_prompt": (
                "当需要外部计算时，请优先调用工具；"
                "收到工具结果后请用中文一句话给出最终答案。"
            ),
            "messages": [{"role": "user", "content": USER_PROMPT}],
            "tools": tools,
        },
        _build_options(api_key),
    )

    tool_call = next(
        (part for part in first.content if getattr(part, "type", None) == "toolCall"),
        None,
    )
    if tool_call is None:
        raise RuntimeError("Model did not emit a tool call.")

    # 这里模拟本地工具执行：读取模型给出的参数并在本地完成加法。
    args = getattr(tool_call, "arguments", {}) or {}
    a = args.get("a", 0)
    b = args.get("b", 0)
    result_text = str(
        (a if isinstance(a, (int, float)) else 0)
        + (b if isinstance(b, (int, float)) else 0)
    )

    print(
        f"TOOL_CALL id={tool_call.id!r} "
        f"name={tool_call.name!r} arguments={tool_call.arguments!r}"
    )

    # 第二轮：把本地执行结果显式包装成 ToolResultMessage 再回传给模型。
    # 这是协议 roundtrip 的关键步骤，也是这个高级示例要表达的核心。
    second = await complete(
        model,
        {
            "system_prompt": "你已经拿到工具结果，请用中文一句话给出最终答案。",
            "messages": [
                {"role": "user", "content": USER_PROMPT},
                first,
                ToolResultMessage(
                    role="toolResult",
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    content=[TextPart(type="text", text=result_text)],
                    is_error=False,
                    timestamp=0.0,
                ),
            ],
            "tools": tools,
        },
        _build_options(api_key),
    )

    # 运行后重点关注两处输出：
    # 1. TOOL_CALL：模型请求了哪个工具、带了什么参数
    # 2. 最终文本：模型消费工具结果后的自然语言答案
    for part in second.content:
        if getattr(part, "type", None) == "text":
            print(part.text, end="")
    print()


def test_openai_responses_tools_live() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:  # pragma: no cover - example path
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
