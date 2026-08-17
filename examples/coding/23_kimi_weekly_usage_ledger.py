from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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

LEDGER_FILE_NAME = "usage-ledger.jsonl"
ENV_WEEKLY_QUOTA_TOKENS = "LOUSHANG_WEEKLY_QUOTA_TOKENS"


def print_event(name: str, payload: dict[str, object]) -> None:
    print(f"{name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _resolve_default_ledger_root() -> Path:
    raw = os.environ.get(ENV_EXAMPLES_ARTIFACT_ROOT, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent / ".loushang"


def _resolve_ledger_path(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    root = _resolve_default_ledger_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / LEDGER_FILE_NAME


@dataclass(frozen=True)
class UsagePayload:
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_write: int
    total_tokens: int
    cost_input: float | None
    cost_output: float | None
    cost_cache_read: float | None
    cost_cache_write: float | None
    cost_total: float | None


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _cost_value(cost: dict[str, float] | None, key: str) -> float | None:
    if cost is None or key not in cost:
        return None
    return _to_float(cost[key])


def _usage_from_response(
    response,
    model_obj,
) -> UsagePayload:
    usage = getattr(response, "usage", None)
    if usage is None:
        raise RuntimeError("provider response missing usage")
    input_tokens = _to_int(getattr(usage, "input", 0))
    output_tokens = _to_int(getattr(usage, "output", 0))
    cache_read = _to_int(getattr(usage, "cache_read", 0))
    cache_write = _to_int(getattr(usage, "cache_write", 0))
    total_tokens = _to_int(
        getattr(usage, "total_tokens", None),
        default=input_tokens + output_tokens + cache_read + cache_write,
    )
    cost = None
    try:
        computed = calculate_cost(model_obj, usage)
        if isinstance(computed, dict):
            cost = computed
    except Exception:
        pass
    return UsagePayload(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read=cache_read,
        cache_write=cache_write,
        total_tokens=total_tokens,
        cost_input=_cost_value(cost, "input"),
        cost_output=_cost_value(cost, "output"),
        cost_cache_read=_cost_value(cost, "cacheRead"),
        cost_cache_write=_cost_value(cost, "cacheWrite"),
        cost_total=_cost_value(cost, "total"),
    )


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _week_start(ts: datetime) -> datetime:
    # 星期一 00:00:00 本地时区
    day_offset = ts.weekday()
    base = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return base - timedelta(days=day_offset)


def _next_reset_hours(ts: datetime) -> int:
    current = _week_start(ts) + timedelta(days=7)
    return int((current - ts).total_seconds() // 3600)


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            lines.append(payload)
    return lines


def _safe_append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False))
        fp.write("\n")


def _week_bucket_total(
    records: list[dict[str, Any]],
    week_start: datetime,
) -> tuple[int, int]:
    total_input = 0
    total_output = 0
    for rec in records:
        ts_raw = rec.get("timestamp")
        if not isinstance(ts_raw, str):
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if _week_start(ts) != week_start:
            continue
        total_input += _to_int(rec.get("input_tokens", 0))
        total_output += _to_int(rec.get("output_tokens", 0))
    return total_input, total_output


def _print_offline_sample(ledger_path: Path) -> None:
    now = _now_local()
    week_start = _week_start(now)
    print("=== Weekly Usage Ledger (offline expected sample) ===")
    print(f"ledger: {ledger_path}")
    print(f"week_start: {week_start.isoformat()}")
    print("records_loaded: 0")
    print("weekly_input_tokens: 0")
    print("weekly_output_tokens: 0")
    print("weekly_total_tokens: 0")
    print(f"resets_in_hours: {_next_reset_hours(now)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track weekly usage locally from API usage payload."
    )
    parser.add_argument(
        "--endpoint",
        default="kimi-code-anthropic",
        help="Target endpoint id. Defaults to kimi-code-anthropic.",
    )
    parser.add_argument(
        "--model",
        default="kimi-for-coding",
        help="Target model id. Defaults to kimi-for-coding.",
    )
    parser.add_argument(
        "--prompt",
        default="请用一句话说明你看到了周用量统计。",
    )
    parser.add_argument(
        "--ledger-path",
        default="",
        help="Usage ledger path, default from LOUSHANG_EXAMPLES_ARTIFACT_ROOT/usage-ledger.jsonl",
    )
    parser.add_argument(
        "--weekly-quota-tokens",
        type=int,
        default=None,
        help="Optional weekly quota token cap for percentage estimation.",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Do not persist this request into ledger.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip live API call and only print ledger aggregate.",
    )
    return parser.parse_args()


async def _run_once(
    endpoint: str, model: str, prompt: str, ledger_path: Path
) -> tuple[str, dict[str, Any]]:
    model_obj = build_kimi_model(endpoint_id=endpoint, model_id=model)
    model_info = describe_model(model_obj)
    print_event(
        "model.start",
        {
            "provider": model_info["provider"],
            "endpoint": model_info["endpoint"],
            "api": model_info["api"],
            "base_url": model_info["base_url"],
            "model": model_info["model"],
            "ledger_path": str(ledger_path),
        },
    )

    context = Context(
        system_prompt="简短回复并保持稳定可复现格式。",
        messages=[UserMessage(role="user", content=prompt, timestamp=0.0)],
    )
    print_event(
        "tool.start", {"tool": "completion", "endpoint": endpoint, "model": model}
    )

    response = await complete(model_obj, context)
    text = "".join(
        part.text
        for part in response.content
        if getattr(part, "type", None) == "text" and hasattr(part, "text")
    )

    usage = _usage_from_response(response, model_obj)
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "provider": str(model_info["provider"]),
        "endpoint": str(model_info["endpoint"]),
        "api": str(model_info["api"]),
        "base_url": str(model_info["base_url"]),
        "model": str(model_info["model"]),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read": usage.cache_read,
        "cache_write": usage.cache_write,
        "total_tokens": usage.total_tokens,
        "cost_input": usage.cost_input,
        "cost_output": usage.cost_output,
        "cost_cache_read": usage.cost_cache_read,
        "cost_cache_write": usage.cost_cache_write,
        "cost_total": usage.cost_total,
        "stop_reason": getattr(response, "stop_reason", None),
        "reply": text[:200],
        "error_message": getattr(response, "error_message", None),
    }
    return text, payload


def _render_summary(
    now: datetime,
    records: list[dict[str, Any]],
    quota_tokens: int | None,
    current_input: int,
    current_output: int,
) -> None:
    week_start = _week_start(now)
    weekly_input, weekly_output = _week_bucket_total(records, week_start)
    weekly_total = weekly_input + weekly_output
    print(f"week_start: {week_start.isoformat()}")
    print(f"resets_in_hours: {_next_reset_hours(now)}")
    print(f"weekly_input_tokens: {weekly_input}")
    print(f"weekly_output_tokens: {weekly_output}")
    print(f"weekly_total_tokens: {weekly_total}")
    print(f"current_call_tokens: {current_input + current_output}")
    if quota_tokens is not None and quota_tokens > 0:
        used_ratio = (weekly_total / quota_tokens) * 100
        print(f"weekly_quota_tokens: {quota_tokens}")
        print(f"weekly_used_pct: {used_ratio:.2f}%")
        print(f"weekly_remaining_tokens: {max(0, quota_tokens - weekly_total)}")
        print(f"weekly_remaining_pct: {max(0.0, 100 - used_ratio):.2f}%")


async def main_async(args: argparse.Namespace) -> int:
    print("=== Weekly Usage Ledger ===")
    print_event("message.start", {"mode": "bootstrap", "offline": args.offline})

    catalog = _resolve_model_catalog()
    if catalog is None:
        print(f"resolved catalog: <unset>; default from {ENV_EXAMPLES_ARTIFACT_ROOT}")
    else:
        print(f"resolved catalog: {catalog}")

    quota_tokens = args.weekly_quota_tokens
    env_quota = os.environ.get(ENV_WEEKLY_QUOTA_TOKENS, "").strip()
    if quota_tokens is None and env_quota:
        try:
            quota_tokens = int(env_quota)
        except Exception:
            quota_tokens = None

    ledger_path = _resolve_ledger_path(args.ledger_path or None)
    print(f"ledger_path: {ledger_path}")
    records = _load_records(ledger_path)
    print_event(
        "model.end",
        {"loaded_records": len(records), "record_file_exists": ledger_path.exists()},
    )

    if args.offline:
        _print_offline_sample(ledger_path)
        return 0

    try:
        text, record = await _run_once(
            args.endpoint, args.model, args.prompt, ledger_path
        )
    except Exception as error:
        print_event(
            "tool.end", {"tool": "completion", "status": "fail", "error": str(error)}
        )
        print(f"reply_error: {error}")
        print_event("message.end", {"result": "fail"})
        _render_summary(_now_local(), records, quota_tokens, 0, 0)
        return 1

    if not args.no_record:
        _safe_append_record(ledger_path, record)
        records.append(record)

    print_event(
        "tool.end", {"tool": "completion", "status": "ok", "reply_preview": text[:160]}
    )
    print(f"reply: {text}")
    print(
        "usage_now:",
        {
            k: record[k]
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_read",
                "cache_write",
                "total_tokens",
            )
        },
    )
    print(
        "cost_now:",
        {
            "input": record["cost_input"],
            "output": record["cost_output"],
            "cacheRead": record["cost_cache_read"],
            "cacheWrite": record["cost_cache_write"],
            "total": record["cost_total"],
        },
    )
    _render_summary(
        datetime.fromisoformat(record["timestamp"]),
        records,
        quota_tokens,
        _to_int(record["input_tokens"]),
        _to_int(record["output_tokens"]),
    )
    print_event(
        "message.end",
        {
            "result": "pass",
            "recorded": not args.no_record,
            "records": len(records),
            "ledger_path": str(ledger_path),
        },
    )

    print("=== offline expected sample ===")
    _print_offline_sample(ledger_path)

    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
