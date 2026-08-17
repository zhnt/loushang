from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
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

TARGET_ENDPOINTS = [
    "kimi-code-anthropic",
]


def print_event(name: str, payload: dict[str, object]) -> None:
    print(f"{name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


@dataclass(frozen=True)
class RouteResult:
    endpoint: str
    provider: str
    model_id: str
    api: str | None
    base_url: str | None
    ok: bool
    error: str | None = None


def _resolve_catalog_info() -> Path | None:
    return _resolve_model_catalog()


def _render_usage_preview(message_text: str, max_chars: int = 120) -> str:
    cleaned = " ".join(message_text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3] + "..."


async def _probe_endpoint(endpoint_id: str, prompt: str) -> RouteResult:
    try:
        model = build_kimi_model(endpoint_id=endpoint_id)
    except Exception as error:
        raise RuntimeError(f"failed to build model for endpoint={endpoint_id}: {error}")

    info = describe_model(model)
    print_event(
        "model.start",
        {
            "endpoint": endpoint_id,
            "provider": info["provider"],
            "model": info["model"],
            "api": info["api"],
            "base_url": info["base_url"],
        },
    )

    print_event("tool.start", {"endpoint": endpoint_id, "tool": "completion"})
    response_status = "ok"
    error_text = None
    text = ""
    try:
        context = Context(
            system_prompt="Please respond with one concise sentence.",
            messages=[UserMessage(role="user", content=prompt, timestamp=0.0)],
        )
        response = await complete(model, context)
        if getattr(response, "content", None):
            text = "".join(
                part.text
                for part in response.content
                if getattr(part, "type", None) == "text" and hasattr(part, "text")
            )
    except Exception as error:
        response_status = "fail"
        error_text = str(error)
    finally:
        print_event(
            "tool.end",
            {
                "endpoint": endpoint_id,
                "text": _render_usage_preview(text),
                "status": response_status,
                "error": error_text,
            },
        )

    print(f"{endpoint_id}: model={info['model']} api={info['api']} base_url={info['base_url']}")
    if response_status == "ok":
        print(f"reply: {text}")
        return RouteResult(
            endpoint=endpoint_id,
            provider=str(info["provider"]),
            model_id=str(info["model"]),
            api=str(info["api"]),
            base_url=str(info["base_url"]),
            ok=True,
        )

    print(f"reply: {error_text}")
    return RouteResult(
        endpoint=endpoint_id,
        provider=str(info["provider"]),
        model_id=str(info["model"]),
        api=str(info["api"]),
        base_url=str(info["base_url"]),
        ok=False,
        error=error_text,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe multiple model route endpoints")
    parser.add_argument(
        "--endpoint",
        action="append",
        default=TARGET_ENDPOINTS.copy(),
        help="Endpoint id to probe. Can specify multiple times.",
    )
    parser.add_argument(
        "--prompt",
        default="请给我一句关于可观测性的中文总结。",
    )
    parser.add_argument("--offline", action="store_true", help="Only print routing matrix, skip live requests.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    print("=== Switch Model Route ===")
    print_event("message.start", {"step": "bootstrap"})

    catalog = _resolve_catalog_info()
    if catalog is None:
        print(f"resolved catalog: <unset>; default from {ENV_EXAMPLES_ARTIFACT_ROOT}")
    else:
        print(f"resolved catalog: {catalog}")

    results: list[RouteResult] = []
    for endpoint_id in args.endpoint:
        if args.offline:
            try:
                model = build_kimi_model(endpoint_id=endpoint_id)
                info = describe_model(model)
                results.append(
                    RouteResult(
                        endpoint=endpoint_id,
                        provider=str(info["provider"]),
                        model_id=str(info["model"]),
                        api=str(info["api"]),
                        base_url=str(info["base_url"]),
                        ok=True,
                    )
                )
                print(f"{endpoint_id}: offline resolved only")
            except Exception as error:
                results.append(
                    RouteResult(
                        endpoint=endpoint_id,
                        provider="kimi-code",
                        model_id="unknown",
                        api=None,
                        base_url=None,
                        ok=False,
                        error=str(error),
                    )
                )
                print_event("model.error", {"endpoint": endpoint_id, "error": str(error)})
            continue

        result = await _probe_endpoint(endpoint_id, args.prompt)
        results.append(result)

    success_count = sum(1 for item in results if item.ok)
    fail_count = len(results) - success_count
    print("=== Route Check Summary ===")
    print(f"total_checked={len(results)} ok={success_count} failed={fail_count}")
    for item in results:
        status = "ok" if item.ok else "failed"
        print(
            f"- {item.endpoint}: {status} provider={item.provider} model={item.model_id} "
            f"api={item.api} base_url={item.base_url}"
            + (f" error={item.error}" if item.error else "")
        )

    print_event("message.end", {"result": "pass" if fail_count == 0 else "partial", "ok": success_count, "total": len(results)})

    print("=== offline expected sample ===")
    print("resolved catalog: <unset>; using built-in catalog")
    print("message.start")
    print(f"total_checked={len(results)} ok={success_count} failed={fail_count}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
