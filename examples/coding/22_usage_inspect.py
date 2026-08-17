from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    ENV_EXAMPLES_ARTIFACT_ROOT,
    _resolve_model_catalog,
    build_kimi_model,
    describe_model,
)

from loushang.ai import Context, UserMessage, complete
from loushang.ai.pricing import calculate_cost


def print_event(name: str, payload: dict[str, object]) -> None:
    print(f"{name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _cost_payload(cost: dict[str, float] | None) -> dict[str, object]:
    if cost is None:
        return {"known": False}
    return {"known": True, **cost}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect assistant usage and estimated cost from a model call.")
    parser.add_argument(
        "--model",
        default="kimi-for-coding",
        help="Target model id. Defaults to kimi-for-coding.",
    )
    parser.add_argument(
        "--endpoint",
        default="kimi-code-anthropic",
        help="Target endpoint id. Defaults to kimi-code-anthropic.",
    )
    parser.add_argument(
        "--prompt",
        default="请输出一段 12 字以内的短句，说明你能看到 usage 字段。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：必须有非空回复且成功；usage 必须存在（允许值为 0），不满足则返回非 0。",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    print("=== Usage Inspect ===")
    print_event("message.start", {"step": "bootstrap"})

    catalog = _resolve_model_catalog()
    if catalog is None:
        print(f"resolved catalog: <unset>; default from {ENV_EXAMPLES_ARTIFACT_ROOT}")
    else:
        print(f"resolved catalog: {catalog}")

    model = build_kimi_model(endpoint_id=args.endpoint, model_id=args.model)
    model_info = describe_model(model)
    print("Model route:")
    print(
        f"  provider={model_info['provider']} endpoint={model_info['endpoint']} "
        f"api={model_info['api']} base_url={model_info['base_url']} model={model_info['model']}"
    )

    print_event(
        "model.start",
        {
            "provider": model_info["provider"],
            "endpoint": model_info["endpoint"],
            "api": model_info["api"],
            "base_url": model_info["base_url"],
            "model": model_info["model"],
        },
    )

    context = Context(
        system_prompt="请遵循用户约束，简短回复。",
        messages=[UserMessage(role="user", content=args.prompt, timestamp=0.0)],
    )
    response = await complete(model, context)
    text_parts = [
        part.text
        for part in response.content
        if getattr(part, "type", None) == "text" and hasattr(part, "text")
    ]
    text = "".join(text_parts)
    thinking_parts = [
        part.thinking
        for part in response.content
        if getattr(part, "type", None) == "thinking" and hasattr(part, "thinking")
    ]
    thinking = "".join(thinking_parts)
    usage = getattr(response, "usage", None)
    stop_reason = getattr(response, "stop_reason", None)
    error_message = getattr(response, "error_message", None)
    content_summary = [
        getattr(part, "type", "unknown") for part in response.content
    ]

    print_event(
        "model.message",
        {
            "stop_reason": stop_reason,
            "has_error": error_message is not None,
            "error_message": error_message,
            "content_types": content_summary,
        },
    )

    usage_payload: dict[str, object] = {
        "input": None,
        "output": None,
        "cache_read": None,
        "cache_write": None,
        "total_tokens": None,
    }
    cost_payload = _cost_payload(None)

    if usage is not None:
        usage_payload = {
            "input": usage.input,
            "output": usage.output,
            "cache_read": usage.cache_read,
            "cache_write": usage.cache_write,
            "total_tokens": usage.total_tokens,
        }
        try:
            cost_payload = _cost_payload(calculate_cost(model, usage))
        except Exception as error:
            cost_payload = {"known": False, "error": str(error)}
    else:
        print_event("model.error", {"reason": "missing usage in response"})

    status = "ok"
    if args.strict:
        if not text_parts or not text.strip():
            status = "fail"
        if error_message is not None:
            status = "fail"
        if usage is None:
            status = "fail"
    print_event("message.end", {"status": status, "usage": usage_payload, "cost": cost_payload})
    print("assistant preview:", " ".join(text.split())[:160])
    if thinking:
        print("assistant thinking:", " ".join(thinking.split())[:160])
    print("usage:", usage_payload)
    print("cost:", cost_payload)

    print("=== offline expected sample ===")
    print("resolved catalog: <unset>; using built-in catalog")
    print("Model route:")
    print("usage: {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'total_tokens': 0}")
    print("cost: {'known': False}")

    if args.strict and status != "ok":
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
