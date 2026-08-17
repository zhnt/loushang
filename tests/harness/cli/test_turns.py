from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from loushang.harness.cli import (
    CliPreparedTurn,
    project_domain_turns_to_cli,
    run_keyword_cli_turns,
)


@dataclass(frozen=True)
class _ResearchPreparedTurn:
    prepared_prompt: str
    method_id: str | None = "research"
    plan_id: str | None = "plan-1"
    step_id: str | None = "collect"
    step_index: int | None = 0
    step_title: str | None = "Collect sources"
    metadata: Mapping[str, object] = field(
        default_factory=lambda: {
            "planned_constraint": {"requires_sources": True},
        }
    )


def test_keyword_turn_runtime_applies_first_and_last_values_once() -> None:
    calls: list[dict[str, object]] = []

    async def runner(**kwargs) -> int:
        calls.append(kwargs)
        return 0

    async def run_turns(turns, *, run_turn, dispose_candidates) -> int:
        assert dispose_candidates == ("runtime", "session")
        for index, turn in enumerate(turns):
            result = await run_turn(turn, index == 0, index == len(turns) - 1)
            if result:
                return result
        return 0

    result = asyncio.run(
        run_keyword_cli_turns(
            (
                CliPreparedTurn("first", {"step_id": "step-1"}),
                CliPreparedTurn("second", {"step_id": "step-2"}),
            ),
            run_turns=run_turns,
            runner=runner,
            input_argument="prompt",
            fixed_arguments={"runtime": "runtime"},
            images=("image",),
            follow_up_messages=("follow up",),
            dispose_candidates=("runtime", "session"),
        )
    )

    assert result == 0
    assert calls == [
        {
            "runtime": "runtime",
            "prompt": "first",
            "step_id": "step-1",
            "images": ("image",),
            "follow_up_messages": (),
            "dispose": False,
        },
        {
            "runtime": "runtime",
            "prompt": "second",
            "step_id": "step-2",
            "images": None,
            "follow_up_messages": ("follow up",),
            "dispose": True,
        },
    ]


def test_prepared_turn_rejects_lifecycle_argument_override() -> None:
    with pytest.raises(ValueError, match="lifecycle values"):
        CliPreparedTurn("input", {"dispose": False})


def test_domain_turn_projection_is_product_neutral() -> None:
    projected = project_domain_turns_to_cli(
        (_ResearchPreparedTurn("Investigate the claim"),)
    )

    assert projected == (
        CliPreparedTurn(
            "Investigate the claim",
            {
                "method_id": "research",
                "plan_id": "plan-1",
                "step_id": "collect",
                "step_index": 0,
                "step_title": "Collect sources",
                "planned_constraint": {"requires_sources": True},
                "audit_policy": None,
                "plan_facts": None,
                "step_facts": None,
            },
        ),
    )
