"""Kimi Anthropic Messages 完整返回示例。

用途：
- 对比 `anthropic-messages` 与 `openai-completions` 的最短调用路径
- 作为正式、最小的 Anthropic 风格接入参考
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterable

import pytest

from loushang.ai import (
    CallOptions,
    complete,
    get_model,
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
    # Anthropic endpoint 的正式示例也统一走显式 api_key 入口。
    value = API_KEY or os.getenv("MOONSHOT_API_KEY")
    if value:
        return value
    raise RuntimeError(
        "Set API_KEY at the top of this file, or export MOONSHOT_API_KEY."
    )


def _build_context() -> dict:
    # Anthropic 路径下仍然使用统一的 public context 结构。
    return {
        "system_prompt": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
    }


def _build_options(api_key: str) -> CallOptions:
    # 把 Anthropic 特有参数收束到 options 中，保持调用点干净。
    return CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=MAX_TOKENS)


def _iter_text(parts: Iterable[object]) -> str:
    # Anthropic 路径返回的 content 同样是结构化片段，这里只提取 text 部分。
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


async def _main() -> None:
    api_key = _resolve_api_key()
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)

    # 这里演示最短 complete 路径，不手动暴露 registry / provider 细节。
    message = await complete(
        model,
        _build_context(),
        _build_options(api_key),
    )

    # 运行后先看 FINAL text，再看 stop_reason / response_id。
    print(f"MODEL {model.provider_id}:{model.endpoint_id}:{model.id}")
    print(f"FINAL stop_reason={message.stop_reason!r}")
    print(f"FINAL response_id={message.response_id!r}")
    print(f"FINAL text={_iter_text(message.content)!r}")


def test_kimi_anthropic_complete_live() -> None:
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
