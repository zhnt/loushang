"""Kimi Anthropic Messages 流式示例。

用途：
- 演示 Anthropic 风格 endpoint 的流式事件消费
- 对比 complete 与 stream 的外部使用方式
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterable

import pytest

from loushang.ai import (
    CallOptions,
    get_model,
    stream,
)
from loushang.ai.auth import ApiKeyAuth

# 用户可直接修改的配置。
# `API_KEY` 是显式认证入口；环境变量只是可选读取来源。
API_KEY = ""
MODEL_ID = "kimi-k2.5"
SYSTEM_PROMPT = "你是 Kimi，由 Moonshot AI 提供。回答要简洁、准确，优先使用中文。"
USER_PROMPT = "请用两句话介绍你自己，并说明 1 + 1 等于几。"
MAX_TOKENS = 256

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
    # 先读显式配置，再读标准环境变量，避免把认证隐藏在示例逻辑里。
    value = API_KEY or os.getenv("MOONSHOT_API_KEY")
    if value:
        return value
    raise RuntimeError(
        "Set API_KEY at the top of this file, or export MOONSHOT_API_KEY."
    )


def _build_context() -> dict:
    # 这是主示例使用的标准 context 形状。
    return {
        "system_prompt": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
    }


def _build_options(api_key: str) -> CallOptions:
    # 这里保留最小必要选项，方便观察 stream 本身而不是 options 细节。
    return CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=MAX_TOKENS)


def _iter_text(parts: Iterable[object]) -> str:
    # 流式结束后，最终消息仍然需要把 text 片段重新拼接成完整文本。
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


async def _main() -> None:
    api_key = _resolve_api_key()
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)

    # 先拿事件流，再逐个消费事件，最后通过 result() 拼装最终消息。
    event_stream = await stream(
        model,
        _build_context(),
        _build_options(api_key),
    )

    print(f"MODEL {model.provider_id}:{model.endpoint_id}:{model.id}")
    async for event in event_stream:
        # 运行时优先看 `text_delta`，其他事件有助于理解协议节奏。
        event_type = event["type"]
        if event_type == "text_delta":
            print(f"EVENT {event_type} delta={event['delta']!r}")
        else:
            print(f"EVENT {event_type}")

    message = await event_stream.result()
    # 流式结束后再查看最终聚合文本。
    print(f"FINAL stop_reason={message.stop_reason!r}")
    print(f"FINAL response_id={message.response_id!r}")
    print(f"FINAL text={_iter_text(message.content)!r}")


def test_kimi_anthropic_stream_live() -> None:
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
