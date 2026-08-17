from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from _support import build_kimi_model, describe_model

from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    Usage,
    UserMessage,
)
from loushang.coding.compaction import (
    SummaryEvaluationCase,
    evaluate_summary_case,
)
from loushang.coding.compaction.adapter import execute_coding_compaction
from loushang.harness.transcript import CompactionPreparation

SAMPLE_SUMMARY = """## Goal
Harden the session index lifecycle and runtime diagnostics.

## Constraints & Preferences
- Keep the changes mode-neutral and non-UI.

## Progress
### Done
- [x] Added runtime diagnostics for rename/delete failures.

### In Progress
- [ ] Continue pi gap evaluation.

### Blocked
- (none)

## Key Decisions
- **Session index lifecycle**: Rebuild stale indexed summaries when cached files disappear.

## Next Steps
1. Run coding regression tests.

## Critical Context
- Runtime diagnostics are recorded without swallowing the original exception.

<read-files>
docs/architecture/coding/component-interfaces/runtime.md
</read-files>

<modified-files>
src/loushang/coding/runtime/agent_session_runtime.py
</modified-files>"""


def _usage() -> Usage:
    return Usage(
        input=20, output=10, cache_read=0, cache_write=0, total_tokens=30, cost=None
    )


def _fixed_preparation() -> CompactionPreparation:
    return CompactionPreparation(
        first_kept_entry_id="keep-1",
        messages_to_summarize=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="Harden session index lifecycle.")],
                timestamp=1.0,
            ),
            AssistantMessage(
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="read-1",
                        name="read",
                        arguments={
                            "path": "docs/architecture/coding/component-interfaces/runtime.md"
                        },
                    ),
                    ToolCall(
                        type="toolCall",
                        id="edit-1",
                        name="edit",
                        arguments={
                            "path": "src/loushang/coding/runtime/agent_session_runtime.py"
                        },
                    ),
                ],
                api="responses",
                provider="faux",
                endpoint="responses",
                model="alpha",
                response_id="r1",
                usage=_usage(),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            ),
        ],
        turn_prefix_messages=[],
        is_split_turn=False,
        tokens_before=42,
    )


async def _real_summary() -> str:
    model = build_kimi_model()
    model_info = describe_model(model)
    print("=== Real Model Compaction Summary ===")
    print(f"Provider: {model_info['provider']}")
    print(f"Model: {model_info['model']}")
    print(f"Endpoint: {model_info['endpoint']}")
    print()
    result = await execute_coding_compaction(
        preparation=_fixed_preparation(), model=model, api_key=""
    )
    return result.summary


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate compaction summary quality for a fixed workload."
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Call the configured Kimi model for the fixed compaction workload instead of using the offline sample.",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    summary = await _real_summary() if args.real else SAMPLE_SUMMARY
    result = evaluate_summary_case(
        SummaryEvaluationCase(
            name="runtime-store-stress",
            summary=summary,
            summary_type="compaction",
            required_phrases=("session index lifecycle", "runtime diagnostics"),
            expected_read_files=(
                "docs/architecture/coding/component-interfaces/runtime.md",
            ),
            expected_modified_files=(
                "src/loushang/coding/runtime/agent_session_runtime.py",
            ),
        )
    )
    print("=== Compaction Summary Evaluation ===")
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
