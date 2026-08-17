"""在线调用模型并检查最终 AssistantMessage.usage。

用途：
- 验证 provider 在线返回是否能被 `loushang.ai` 归一化为 Usage
- 对比 complete 与 stream 两种 public path 的最终 usage

运行前提：
- Moonshot public API: export MOONSHOT_API_KEY=...
- DashScope: export DASHSCOPE_API_KEY=...
- DeepSeek: export DEEPSEEK_API_KEY=...

示例：
- uv --cache-dir .uv-cache run python examples/ai/advanced/usage_online.py
- uv --cache-dir .uv-cache run python examples/ai/advanced/usage_online.py --route dashscope-responses --strict
- uv --cache-dir .uv-cache run python examples/ai/advanced/usage_online.py --route deepseek-completions --stream --strict
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from loushang.ai import (
    CallOptions,
    Model,
    complete,
    get_model,
    stream,
)
from loushang.ai.auth import ApiKeyAuth
from loushang.ai.pricing import calculate_cost
from loushang.ai.types import AssistantMessage, Usage


@dataclass(frozen=True)
class Route:
    provider: str
    endpoint: str
    model: str
    api_key_envs: tuple[str, ...]


ROUTES: dict[str, Route] = {
    "moonshot-openai": Route(
        provider="moonshot",
        endpoint="openai-completions",
        model="kimi-k2.6",
        api_key_envs=("MOONSHOT_API_KEY",),
    ),
    "dashscope-responses": Route(
        provider="dashscope",
        endpoint="openai-responses",
        model="qwen3.7-plus",
        api_key_envs=("DASHSCOPE_API_KEY",),
    ),
    "deepseek-completions": Route(
        provider="deepseek",
        endpoint="openai-completions",
        model="deepseek-v4-flash",
        api_key_envs=("DEEPSEEK_API_KEY",),
    ),
}

SYSTEM_PROMPT = "你是一个用于检查 usage 字段的在线模型。请简洁回答。"
USER_PROMPT = "请用一句中文回答：你是否可以返回 usage？"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call an online model and print normalized usage."
    )
    parser.add_argument("--route", choices=sorted(ROUTES), default="moonshot-openai")
    parser.add_argument(
        "--provider", help="Override provider id from the selected route."
    )
    parser.add_argument(
        "--endpoint", help="Override endpoint id from the selected route."
    )
    parser.add_argument("--model", help="Override model id from the selected route.")
    parser.add_argument("--api-key-env", help="Override API key environment variable.")
    parser.add_argument(
        "--api-key", help="Explicit API key. Prefer env vars for normal use."
    )
    parser.add_argument("--prompt", default=USER_PROMPT)
    parser.add_argument("--system-prompt", default=SYSTEM_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Provider request timeout in seconds.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Use the streaming root API instead of the complete root API.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if usage is missing or total_tokens is not positive.",
    )
    return parser.parse_args()


def _resolve_route(args: argparse.Namespace) -> Route:
    base = ROUTES[args.route]
    api_key_envs = (args.api_key_env,) if args.api_key_env else base.api_key_envs
    return Route(
        provider=args.provider or base.provider,
        endpoint=args.endpoint or base.endpoint,
        model=args.model or base.model,
        api_key_envs=api_key_envs,
    )


def _resolve_api_key(
    *, explicit_api_key: str | None, env_names: tuple[str, ...]
) -> tuple[str, str]:
    if explicit_api_key:
        return explicit_api_key, "<explicit>"
    for env_name in env_names:
        value = os.getenv(env_name)
        if value:
            return value, env_name
    joined = " or ".join(env_names)
    raise RuntimeError(f"Set --api-key, or export {joined}.")


def _build_options(
    route: Route, *, api_key: str, max_tokens: int, timeout: float
) -> CallOptions:
    del route
    return CallOptions(auth=ApiKeyAuth(api_key),
        max_output_tokens=max_tokens,
        timeout_seconds=timeout,
    )


def _build_context(*, system_prompt: str, user_prompt: str) -> dict[str, object]:
    return {
        "system_prompt": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }


def _usage_payload(usage: Usage | None) -> dict[str, object]:
    if usage is None:
        return {
            "present": False,
            "input": None,
            "output": None,
            "cache_read": None,
            "cache_write": None,
            "component_total": None,
            "total_tokens": None,
            "total_positive": False,
            "total_matches_components": False,
        }
    component_total = usage.input + usage.output + usage.cache_read + usage.cache_write
    return {
        "present": True,
        "input": usage.input,
        "output": usage.output,
        "cache_read": usage.cache_read,
        "cache_write": usage.cache_write,
        "component_total": component_total,
        "total_tokens": usage.total_tokens,
        "total_positive": usage.total_tokens > 0,
        "total_matches_components": usage.total_tokens == component_total,
    }


def _cost_payload(cost: dict[str, float] | None) -> dict[str, object]:
    if cost is None:
        return {"known": False}
    return {"known": True, **cost}


def _iter_text(parts: Iterable[object]) -> str:
    texts: list[str] = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            texts.append(part.text)
    return "".join(texts)


def _print_json(label: str, payload: dict[str, object]) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


async def _complete(
    model: Model, context: dict[str, object], options: CallOptions
) -> AssistantMessage:
    return await complete(model, context, options)


async def _stream(
    model: Model, context: dict[str, object], options: CallOptions
) -> AssistantMessage:
    events = await stream(model, context, options)
    async for event in events:
        if event["type"] == "text_delta":
            print(f"EVENT text_delta {event['delta']!r}")
        elif event["type"] in {"done", "error"}:
            print(f"EVENT {event['type']}")
    return await events.result()


async def main() -> int:
    args = parse_args()
    route = _resolve_route(args)
    api_key, api_key_source = _resolve_api_key(
        explicit_api_key=args.api_key, env_names=route.api_key_envs
    )
    model = get_model(route.provider, route.endpoint, route.model)
    options = _build_options(
        route, api_key=api_key, max_tokens=args.max_tokens, timeout=args.timeout
    )
    context = _build_context(system_prompt=args.system_prompt, user_prompt=args.prompt)

    _print_json(
        "route",
        {
            "provider": route.provider,
            "endpoint": route.endpoint,
            "model": route.model,
            "api_key_source": api_key_source,
            "api_key_envs": list(route.api_key_envs),
            "mode": "stream" if args.stream else "complete",
            "timeout": args.timeout,
        },
    )

    message = await (
        _stream(model, context, options)
        if args.stream
        else _complete(model, context, options)
    )
    usage = getattr(message, "usage", None)
    usage_payload = _usage_payload(usage)
    cost_payload = _cost_payload(
        calculate_cost(model, usage) if usage is not None else None
    )

    _print_json(
        "message",
        {
            "stop_reason": message.stop_reason,
            "error_message": message.error_message,
            "response_id": message.response_id,
            "content_types": [
                getattr(part, "type", "unknown") for part in message.content
            ],
        },
    )
    _print_json("usage", usage_payload)
    _print_json("cost", cost_payload)
    print("text:", " ".join(_iter_text(message.content).split())[:240])

    if args.strict and not usage_payload["total_positive"]:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:  # pragma: no cover - online example path
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
