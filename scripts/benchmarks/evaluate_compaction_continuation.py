"""Ask the same model to recover facts from saved synthetic compaction outputs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from loushang.ai import ApiKeyAuth, CallOptions, Context, get_model, stream
from loushang.ai.types import TextPart, UserMessage

_EXPECTED = (
    "ERR_RETRY_GAP",
    "qa-17",
    "checkpoint-v2",
    "single writer",
    "CTX-409",
)
_QUESTION = (
    "From this checkpoint, explain the unfinished resume error, the release "
    "condition, the writer invariant, and the compatibility error code. "
    "Include the exact identifiers. Answer in one concise paragraph."
)


def recalled_facts(answer: str) -> list[str]:
    """Accept the ordinary hyphenated spelling of the writer invariant."""

    normalized = answer.casefold().replace("single-writer", "single writer")
    return [fact for fact in _EXPECTED if fact.casefold() in normalized]


async def _evaluate(paths: list[Path], api_key: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        report = json.loads(path.read_text())
        provider, endpoint, model_id = report["model_route"].split("/", 2)
        model = get_model(provider, endpoint, model_id)
        for item in report["rows"]:
            context = Context(
                system_prompt=(
                    "Continue a coding session using only the checkpoint below. "
                    "If a fact is missing, say unknown."
                ),
                messages=[
                    UserMessage(
                        role="user",
                        content=f"Checkpoint:\n{item['summary']}\n\n{_QUESTION}",
                        timestamp=0.0,
                    )
                ],
            )
            started = perf_counter()
            event_stream = await stream(
                model,
                context,
                CallOptions(auth=ApiKeyAuth(api_key), timeout_seconds=180),
            )
            response = await event_stream.result()
            answer = "".join(
                part.text for part in response.content if isinstance(part, TextPart)
            )
            recalled = recalled_facts(answer)
            rows.append(
                {
                    "source": path.name,
                    "model_route": report["model_route"],
                    "case": report["case"],
                    "strategy": item["strategy"],
                    "repetition": item["repetition"],
                    "elapsed_seconds": round(perf_counter() - started, 3),
                    "recalled": recalled,
                    "missing": [fact for fact in _EXPECTED if fact not in recalled],
                    "answer": answer,
                }
            )
            print(
                f"{path.name} {item['strategy']} rep={item['repetition']}: "
                f"{len(recalled)}/{len(_EXPECTED)} recalled",
                flush=True,
            )
    return {
        "schema": "loushang.compaction.continuation.v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "expected_count": len(_EXPECTED),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Permit API requests")
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to allow billed provider requests")
    key = os.environ.get(args.api_key_env)
    if not key:
        parser.error(f"Missing API key environment variable: {args.api_key_env}")
    report = asyncio.run(_evaluate(args.input, key))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
