"""DashScope Responses 流式示例。

用途：
- 演示 DashScope 在 `openai-responses` 路径下的最短 public 调用方式
- 观察 `text_delta` / `thinking_delta` 这类流式事件
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from loushang.ai import CallOptions, get_model, stream
from loushang.ai.auth import ApiKeyAuth

# 用户可直接修改的配置。
# `API_KEY` 是显式认证入口；环境变量只是可选读取来源。
API_KEY = ""
MODEL_ID = "qwen3.7-plus"
SYSTEM_PROMPT = "你是通义千问模型，请用中文简洁回答。"
USER_PROMPT = "请用两句话介绍你自己，并说明 1 + 1 等于几。"
MAX_TOKENS = 256

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
    # DashScope 示例也统一使用显式 api_key，环境变量只是一个方便的读取来源。
    value = API_KEY or os.getenv("DASHSCOPE_API_KEY")
    if value:
        return value
    raise RuntimeError(
        "Set API_KEY at the top of this file, or export DASHSCOPE_API_KEY."
    )


def _build_context() -> dict:
    # Responses 路径下主示例仍然使用统一 context 结构，方便与其他 provider 对比。
    return {
        "system_prompt": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
    }


def _build_options(api_key: str) -> CallOptions:
    # Responses path 的关键参数仍然集中放在 options 中，调用点保持最短。
    return CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=MAX_TOKENS)


async def _main() -> None:
    api_key = _resolve_api_key()
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)

    # 这个示例展示最短流式路径：get_model -> stream -> 遍历事件。
    events = await stream(
        model,
        _build_context(),
        _build_options(api_key),
    )

    print(f"MODEL {model.provider_id}:{model.endpoint_id}:{model.id}")

    async for event in events:
        # 运行时重点看 `text_delta`；如果模型支持思考，也可能看到 `thinking_delta`。
        line = f"EVENT {event['type']}"
        if event["type"] == "thinking_delta":
            line += f" thinking={event['delta']!r}"
        if event["type"] == "text_delta":
            line += f" text={event['delta']!r}"
        print(line)

    final = await events.result()
    # 最终结果对象主要用于拿 stop_reason / response_id 等聚合信息。
    print(f"FINAL stop_reason={final.stop_reason!r}")
    print(f"FINAL response_id={final.response_id!r}")


def test_openai_responses_stream_live() -> None:
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
