"""Kimi OpenAI Chat Completions 流式示例。

适用场景：
- 想看最短 public path 下如何消费流式事件
- 想区分 `text_delta` 与最终 `result()`

运行前提：
- 在文件顶部填写 `API_KEY`，或导出 `MOONSHOT_API_KEY`
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from loushang.ai import (
    CallOptions,
    get_model,
    stream,
)
from loushang.ai.auth import ApiKeyAuth
from loushang.ai.errors import AIAuthenticationError

# 用户可直接修改的配置。
# `API_KEY` 是显式认证入口；环境变量只是可选读取来源。
API_KEY = ""
MODEL_ID = "kimi-k2.6"
SYSTEM_PROMPT = "你是 Kimi，由 Moonshot AI 提供。回答要简洁、准确，优先使用中文。"
USER_PROMPT = "请用两句话介绍你自己，并说明 1 + 1 等于几。"
MAX_TOKENS = 256

PROVIDER_ID = "moonshot"
ENDPOINT_ID = "openai-completions"

pytestmark = [
    pytest.mark.live,
    pytest.mark.vendor_verification,
    pytest.mark.skipif(
        not (API_KEY or os.getenv("MOONSHOT_API_KEY")),
        reason="MOONSHOT_API_KEY not set; live Moonshot verification skipped",
    ),
]


def _resolve_api_key() -> str:
    # 显式认证优先来自文件顶部配置，其次才回退到标准环境变量。
    value = API_KEY or os.getenv("MOONSHOT_API_KEY")
    if value:
        return value
    raise RuntimeError(
        "Set API_KEY at the top of this file, or export MOONSHOT_API_KEY."
    )


def _build_context() -> dict:
    # 主示例保持最常见消息结构，便于直接迁移到业务代码。
    return {
        "system_prompt": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
    }


def _build_options(api_key: str) -> CallOptions:
    # 流式与完整返回共用同一组核心 options；这里只保留最关键的 api_key/max_tokens。
    return CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=MAX_TOKENS)


async def _main() -> None:
    api_key = _resolve_api_key()
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)

    # 这个示例演示流式接口：先消费事件，再通过 result() 取最终消息。
    events = await stream(
        model,
        _build_context(),
        _build_options(api_key),
    )

    print(f"MODEL {model.provider_id}:{model.endpoint_id}:{model.id}")

    async for event in events:
        # 运行时重点关注 `text_delta`；其他事件用于理解协议节奏。
        line = f"EVENT {event['type']}"
        if event["type"] == "thinking_delta":
            line += f" thinking={event['delta']!r}"
        if event["type"] == "text_delta":
            line += f" text={event['delta']!r}"
        if event["type"] == "image_end":
            line += f" mime_type={event['content'].mime_type!r}"
        print(line)

    final = await events.result()
    # 流式结束后再读取最终结果对象。
    print(f"FINAL stop_reason={final.stop_reason!r}")
    print(f"FINAL response_id={final.response_id!r}")


def test_kimi_openai_stream_live() -> None:
    try:
        asyncio.run(_main())
    except AIAuthenticationError as exc:
        pytest.skip(f"Moonshot credentials rejected: {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:  # pragma: no cover - example path
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
