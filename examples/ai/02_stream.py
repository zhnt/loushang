"""Offline streaming event handling example."""

from __future__ import annotations

import json
from collections.abc import Iterable

from loushang.ai import AssistantMessage, TextPart, get_model

PROVIDER_ID = "moonshot"
ENDPOINT_ID = "openai-completions"
MODEL_ID = "kimi-k2.6"


def _offline_events() -> list[dict[str, object]]:
    return [
        {"type": "start"},
        {"type": "text_delta", "delta": "mock hello "},
        {"type": "text_delta", "delta": "from offline fixture"},
        {"type": "done"},
    ]


def _offline_message() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="mock hello from offline fixture")],
        api=ENDPOINT_ID,
        provider=PROVIDER_ID,
        endpoint=ENDPOINT_ID,
        model=MODEL_ID,
        response_id="offline-stream-demo",
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


def inspect_stream() -> dict[str, object]:
    model = get_model(PROVIDER_ID, ENDPOINT_ID, MODEL_ID)
    message = _offline_message()
    return {
        "model": f"{model.provider_id}:{model.endpoint_id}:{model.id}",
        "events": _offline_events(),
        "responseId": message.response_id,
        "stopReason": message.stop_reason,
        "text": _iter_text(message.content),
    }


def main() -> None:
    print(json.dumps(inspect_stream(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
