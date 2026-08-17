"""高级示例：Kimi Anthropic tool roundtrip。

这个示例专门演示 `ToolResultMessage` 的往返流程。
如果你只是第一次接入，请先看 complete / stream 主示例。
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
# 这是高级示例，重点是工具协议，不是最短接入路径。
API_KEY = ""
MODEL_ID = "kimi-k2.5"
USER_PROMPT = "只调用工具，不要解释：使用 add 计算 7 + 35，并返回结果。"
MAX_TOKENS = 512

PROVIDER_ID = "moonshot"
ENDPOINT_ID = "anthropic-messages"

pytestmark = [
    pytest.mark.live,
    pytest.mark.vendor_verification,
    pytest.mark.skip(
        reason="Moonshot Anthropic route is archived from the built-in curated catalog"
    ),
    pytest.mark.skipif(
        not (API_KEY or os.getenv("MOONSHOT_API_KEY")),
        reason="MOONSHOT_API_KEY not set; live Moonshot verification skipped",
    ),
]


def _resolve_api_key() -> str:
    # 即使是高级协议示例，认证入口也应与主示例保持一致。
    value = API_KEY or os.getenv("MOONSHOT_API_KEY")
    if value:
        return value
    raise RuntimeError(
        "Set API_KEY at the top of this file, or export MOONSHOT_API_KEY."
    )


def _build_tools() -> list[dict]:
    # 用一个最小工具定义来降低阅读成本。
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
    # 把调用参数集中到 options，便于聚焦 tool 协议本身。
    return CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=MAX_TOKENS)


async def _main() -> None:
    api_key = _resolve_api_key()
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)
    tools = _build_tools()

    # 第一轮：让模型先决定工具调用参数。
    first = await complete(
        model,
        {
            "system_prompt": (
                "当需要外部计算时，你必须且仅能通过调用工具完成任务；"
                "收到工具结果后请用中文直接给出最终答案。"
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

    # 这里模拟本地工具执行。
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

    # 第二轮：把工具执行结果回传给模型，让模型生成最终自然语言答案。
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

    # 运行后先看 TOOL_CALL，再看最终文本输出。
    for part in second.content:
        if getattr(part, "type", None) == "text":
            print(part.text, end="")
    print()


def test_kimi_anthropic_tools_live() -> None:
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
