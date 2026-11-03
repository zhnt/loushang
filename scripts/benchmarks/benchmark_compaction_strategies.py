"""Measure paired live Coding compaction calls on one synthetic split-turn case.

Run explicitly with --live. The output contains synthetic prompts and summaries,
but never credentials. Each repetition alternates strategy order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from loushang.agent import AgentMessage, ModelCallPreparation, PrepareModelCallFn
from loushang.ai import CallOptions, Context, Model, get_model, stream
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding.compaction.adapter import execute_coding_compaction
from loushang.harness.transcript import CompactionPreparation
from loushang.harness.transcript.summarization import CompactionStrategy

_ANCHORS = (
    "CTX-409",
    "checkpoint-v2",
    "single writer",
    "resume after crash",
    "ERR_RETRY_GAP",
    "qa-17",
)
_UPDATE_ANCHOR = "LEGACY-KEEP-42"


@dataclass(frozen=True)
class CallRecord:
    purpose: str
    seconds: float
    prompt_utf8_bytes: int
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    cost: dict[str, float] | None


def _assistant(text: str, index: int, model: Model) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api=model.api or "openai-completions",
        provider=model.provider_id,
        endpoint=model.endpoint_id,
        model=model.id,
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=float(index) + 0.5,
    )


def _case(case_name: str, model: Model) -> CompactionPreparation:
    history: list[AgentMessage] = [
        UserMessage(
            role="user",
            content=(
                "Goal: make transcript checkpoints recoverable after a process crash. "
                "The release marker is checkpoint-v2. Keep the append-only journal "
                "and a single writer. Never rewrite historical entries."
            ),
            timestamp=1.0,
        ),
        _assistant(
            "Decision: checkpoint-v2 stores a durable offset and validates the "
            "journal tail before use. The single writer owns offset publication.",
            1,
            model,
        ),
    ]
    for index in range(2, 18):
        history.extend(
            [
                UserMessage(
                    role="user",
                    content=(
                        f"Review cycle {index}: inspect the checkpoint path and "
                        "verify branches still reference the original journal. "
                        "Do not replace source history with a rendered summary. "
                        "Confirm the loader checks an offset against journal size "
                        "and falls back to the full scan on corruption. "
                        "The next review must preserve the same constraints. "
                    )
                    * 3,
                    timestamp=float(index),
                ),
                _assistant(
                    f"Review cycle {index} complete. The full scan remains the "
                    "recovery path, and the checkpoint offset is only a cache. "
                    "No journal entry was edited.",
                    index,
                    model,
                ),
            ]
        )
    history.extend(
        [
            UserMessage(
                role="user",
                content=(
                    "The compatibility error is CTX-409. Preserve this exact code "
                    "when a checkpoint belongs to another model route. The smoke "
                    "run identifier is qa-17. Continue with resume after crash "
                    "before measuring latency."
                ),
                timestamp=18.0,
            ),
            _assistant(
                "Implemented CTX-409 in the model-route guard. qa-17 passed "
                "journal replay; resume after crash is the remaining scenario.",
                18,
                model,
            ),
        ]
    )
    prefix: list[AgentMessage] = [
        UserMessage(
            role="user",
            content=(
                "Current unfinished task: investigate ERR_RETRY_GAP during resume "
                "after crash. Keep the single writer invariant and do not release "
                "checkpoint-v2 until qa-17 validates the retry path."
            ),
            timestamp=19.0,
        ),
        _assistant(
            "Found ERR_RETRY_GAP between tail validation and retry; the next "
            "step is a focused regression before changing the loader.",
            19,
            model,
        ),
    ]
    return CompactionPreparation(
        first_kept_entry_id="synthetic-kept-entry",
        messages_to_summarize=history,
        turn_prefix_messages=prefix,
        is_split_turn=True,
        tokens_before=12_000,
        previous_summary=(
            "## Goal\nRecover transcript checkpoints safely.\n\n"
            "## Constraints & Preferences\n- Preserve LEGACY-KEEP-42 across "
            "updates.\n\n"
            "## Progress\n### Done\n- [x] Selected append-only storage.\n"
            "### In Progress\n- [ ] Validate crash recovery.\n"
            "### Blocked\n- (none)\n\n"
            "## Key Decisions\n- **Legacy marker**: Keep LEGACY-KEEP-42 for "
            "checkpoint compatibility.\n\n"
            "## Next Steps\n1. Validate crash recovery.\n\n"
            "## Critical Context\n- LEGACY-KEEP-42 is a durable compatibility "
            "marker."
            if case_name == "split-turn-update"
            else None
        ),
    )


def _prompt_bytes(context: Context) -> int:
    parts = [context.system_prompt or ""]
    for message in context.messages:
        content = message.content
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(part.text for part in content if isinstance(part, TextPart))
    return len("\n".join(parts).encode("utf-8"))


async def _measure(
    *,
    model: Model,
    api_key: str,
    strategy: CompactionStrategy,
    repetition: int,
    case_name: str,
) -> dict[str, Any]:
    calls: list[CallRecord] = []
    purposes: list[str] = []

    def prepare_call(call: ModelCallPreparation) -> CallOptions:
        purposes.append(call.purpose)
        return replace(call.options, timeout_seconds=180)

    async def complete_text(
        selected_model: object, context: Context, options: CallOptions | None
    ) -> str:
        started = perf_counter()
        event_stream = await stream(cast(Model, selected_model), context, options)
        message = await event_stream.result()
        elapsed = perf_counter() - started
        usage = message.usage
        usage_reported = any(
            (usage.input, usage.output, usage.cache_read, usage.cache_write)
        )
        calls.append(
            CallRecord(
                purpose=purposes.pop(0),
                seconds=round(elapsed, 3),
                prompt_utf8_bytes=_prompt_bytes(context),
                input_tokens=usage.input if usage_reported else None,
                output_tokens=usage.output if usage_reported else None,
                cache_read_tokens=usage.cache_read if usage_reported else None,
                cache_write_tokens=usage.cache_write if usage_reported else None,
                cost=dict(usage.cost) if usage.cost is not None else None,
            )
        )
        return "".join(
            part.text for part in message.content if isinstance(part, TextPart)
        )

    started = perf_counter()
    result = await execute_coding_compaction(
        preparation=_case(case_name, model),
        model=model,
        api_key=api_key,
        strategy=strategy,
        completer=complete_text,
        prepare_model_call=cast(PrepareModelCallFn, prepare_call),
    )
    elapsed = perf_counter() - started
    summary = result.summary
    anchors = (
        (*_ANCHORS, _UPDATE_ANCHOR) if case_name == "split-turn-update" else _ANCHORS
    )
    retained = [anchor for anchor in anchors if anchor.casefold() in summary.casefold()]
    return {
        "strategy": strategy,
        "repetition": repetition,
        "elapsed_seconds": round(elapsed, 3),
        "call_count": len(calls),
        "calls": [asdict(call) for call in calls],
        "retained_anchors": retained,
        "missing_anchors": [anchor for anchor in anchors if anchor not in retained],
        "quality_score": f"{len(retained)}/{len(anchors)}",
        "has_turn_context": "Turn Context" in summary,
        "summary": summary,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    model = get_model(args.provider, args.endpoint, args.model)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing API key environment variable: {args.api_key_env}")
    rows: list[dict[str, Any]] = []
    for repetition in range(
        args.start_repetition, args.start_repetition + args.repetitions
    ):
        order: tuple[CompactionStrategy, CompactionStrategy] = (
            ("local_separate", "local_combined")
            if repetition % 2
            else ("local_combined", "local_separate")
        )
        for strategy in order:
            row = await _measure(
                model=model,
                api_key=api_key,
                strategy=strategy,
                repetition=repetition,
                case_name=args.case,
            )
            rows.append(row)
            print(
                f"{strategy} rep={repetition}: {row['elapsed_seconds']}s, "
                f"{row['call_count']} calls, {row['quality_score']} anchors",
                flush=True,
            )
    return {
        "schema": "loushang.compaction.paired.v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "model_route": f"{args.provider}/{args.endpoint}/{args.model}",
        "case": (
            "synthetic-split-turn-v1"
            if args.case == "split-turn-initial"
            else "synthetic-split-turn-update-v1"
        ),
        "anchor_count": len(_ANCHORS) + (args.case == "split-turn-update"),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Permit API requests")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--endpoint", default="openai-completions")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument(
        "--case",
        choices=("split-turn-initial", "split-turn-update"),
        default="split-turn-initial",
    )
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--start-repetition", type=int, default=1)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".artifacts/compaction/paired-deepseek.json"),
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to allow billed provider requests")
    if args.repetitions < 1 or args.start_repetition < 1:
        parser.error("--repetitions and --start-repetition must be positive")
    report = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
