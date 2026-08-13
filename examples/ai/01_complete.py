"""Offline complete-call result handling example."""

from __future__ import annotations

import json
from collections.abc import Iterable

from loushang.ai import AssistantMessage, CallOptions, TextPart, get_model

PROVIDER_ID = "moonshot"
ENDPOINT_ID = "openai-completions"
MODEL_ID = "kimi-k2.6"
SYSTEM_PROMPT = "You are an example assistant."
USER_PROMPT = "请用两句话介绍你自己，并说明 1 + 1 等于几。"
MAX_TOKENS = 256


def _build_context() -> dict[str, object]:
    return {
        "system_prompt": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
    }


def _build_options() -> CallOptions:
    return CallOptions(max_output_tokens=MAX_TOKENS)


def _offline_message() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="mock hello from offline fixture")],
        api=ENDPOINT_ID,
        provider=PROVIDER_ID,
        endpoint=ENDPOINT_ID,
        model=MODEL_ID,
        response_id="offline-complete-demo",
        usage=None,
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _iter_text(parts: Iterable[object]) -> str:
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


def inspect_complete() -> dict[str, object]:
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)
    message = _offline_message()
    context = _build_context()
    messages = context["messages"]
    return {
        "model": f"{model.provider_id}:{model.endpoint_id}:{model.id}",
        "maxOutputTokens": _build_options().max_output_tokens,
        "messageCount": len(messages) if isinstance(messages, list) else 0,
        "responseId": message.response_id,
        "stopReason": message.stop_reason,
        "text": _iter_text(message.content),
    }


def main() -> None:
    print(json.dumps(inspect_complete(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
