"""Debug mapped raw parts from Kimi OpenAI-compatible chat completions."""

from __future__ import annotations

import asyncio
import os
import sys

from loushang.ai import ApiKeyAuth, CallOptions, Model
from loushang.ai.context import normalize_context
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.provider import ProviderRequest

BASE_URL = "https://api.moonshot.cn/v1"


def _resolve_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("KIMI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set OPENAI_API_KEY or KIMI_API_KEY before running this script."
        )
    return api_key


async def _main() -> None:
    api_key = _resolve_api_key()
    provider = OpenAIChatCompletionsAdapter()
    model = Model(
        id="kimi-k2.5",
        provider="moonshot",
        endpoint="openai-completions",
        api="openai-completions",
    )
    context = {
        "messages": [
            {
                "role": "system",
                "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手。",
            },
            {"role": "user", "content": "你好，我叫李雷，1+1等于多少？"},
        ]
    }
    options = CallOptions(auth=ApiKeyAuth(api_key), max_output_tokens=128)
    request = ProviderRequest(
        provider="moonshot",
        endpoint="openai-completions",
        api="openai-completions",
        base_url=BASE_URL,
        model=model,
        context=normalize_context(context, model=model),
        options=options,
        headers={"Authorization": f"Bearer {api_key}"},
        upstream_model_id=model.id,
    )

    async for part in provider.invoke_raw(request):
        print(part)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
