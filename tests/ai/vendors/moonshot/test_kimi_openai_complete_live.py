"""Kimi OpenAI Chat Completions 完整返回示例。

适用场景：
- 第一次接入 `loushang.ai`
- 想看最短 public path：`get_model(...)` + `complete(model, ...)`

运行前提：
- 在文件顶部填写 `API_KEY`，或导出 `MOONSHOT_API_KEY`

运行后重点关注：
- `FINAL text`：模型最终文本
- `FINAL stop_reason`：模型停止原因
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
from loushang.ai.errors import AIAuthenticationError

# 用户可直接修改的配置。
# `API_KEY` 是显式认证入口；环境变量只是可选读取来源，不会在示例中被回写。
API_KEY = ""
# `MODEL_ID` / `PROVIDER_ID` / `ENDPOINT_ID` 必须是内置 catalog 里可匹配的一组模型句柄。
MODEL_ID = "kimi-k2.6"
SYSTEM_PROMPT = "你是 Kimi，由 Moonshot AI 提供。回答要简洁、准确，优先使用中文。"
USER_PROMPT = "请用两句话介绍你自己，并说明 1 + 1 等于几。"
# `MAX_TOKENS` 控制本次返回上限；调大通常会得到更长输出。
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
    # 这里使用最常见的 system + user 结构，便于外部调用方直接照抄。
    return {
        "system_prompt": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
    }


def _build_options(api_key: str) -> CallOptions:
    # options 只放本次调用直接相关的参数，避免把认证散落到别处。
    return CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=MAX_TOKENS)


def _iter_text(parts: Iterable[object]) -> str:
    # complete 返回的是结构化 content 列表；这里把文本片段拼成便于阅读的单字符串。
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


async def _main() -> None:
    # 第 1 步：解析显式认证信息。
    api_key = _resolve_api_key()
    # 第 2 步：从内置模型目录中取出正式模型句柄。
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)

    # 第 3 步：走完整返回接口。这个示例故意不手动传 registry，
    # 用来展示根包默认 registry 的最短调用路径。
    message = await complete(
        model,
        _build_context(),
        _build_options(api_key),
    )

    # 运行后优先看 FINAL text，其次再看 stop_reason / response_id。
    print(f"MODEL {model.provider_id}:{model.endpoint_id}:{model.id}")
    print(f"FINAL stop_reason={message.stop_reason!r}")
    print(f"FINAL response_id={message.response_id!r}")
    print(f"FINAL text={_iter_text(message.content)!r}")


def test_kimi_openai_complete_live() -> None:
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
