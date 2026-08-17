from __future__ import annotations

import json
from io import StringIO

import pytest

from loushang.harness.cli.multiagent import (
    MultiAgentCliUsageError,
    MultiAgentRunCommand,
    extract_multiagent_argv,
    parse_multiagent_command,
    resolve_multiagent_prompt,
    resolve_multiagent_replicas,
    write_multiagent_recipe_catalog,
    write_multiagent_recipe_result,
)
from loushang.harness.multiagent import (
    AgentCompletionNotice,
    AgentPath,
    AgentRef,
    AgentUsage,
    CollaborationRecipe,
    RecipeExecutionResult,
    RecipeRole,
    TerminalPayload,
)


def _recipe() -> CollaborationRecipe:
    return CollaborationRecipe(
        recipe_id="parallel-review",
        description="Review in parallel.",
        roles=(
            RecipeRole(
                name="reviewer",
                agent_type="reviewer",
                default_replicas=2,
                maximum_replicas=4,
                scalable=True,
            ),
            RecipeRole(name="synthesizer", agent_type="synthesizer"),
        ),
    )


def test_parses_product_neutral_recipe_command_and_common_cwd() -> None:
    assert extract_multiagent_argv(("--cwd=/repo", "ma", "recipes")) == (
        "recipes",
        "--cwd=/repo",
    )

    command = parse_multiagent_command(
        (
            "run",
            "parallel-review",
            "--prompt",
            "Review it.",
            "--count",
            "3",
            "--agent",
            "synthesizer=openai/gpt-5.4",
        )
    )

    assert isinstance(command, MultiAgentRunCommand)
    assert command.recipe_id == "parallel-review"
    assert command.count == 3
    assert command.agent_models == {"synthesizer": "openai/gpt-5.4"}


def test_resolves_prompt_attachments_and_the_single_scalable_role(tmp_path) -> None:
    evidence = tmp_path / "evidence.md"
    evidence.write_text("Shared evidence.", encoding="utf-8")

    prompt = resolve_multiagent_prompt(
        "Review this.",
        ("@evidence.md",),
        cwd=tmp_path,
    )

    assert prompt.startswith("Review this.\n\n## Attached:")
    assert prompt.endswith("Shared evidence.")
    assert resolve_multiagent_replicas({}, 3, recipe=_recipe()) == {
        "reviewer": 3
    }
    with pytest.raises(ValueError, match="conflicts"):
        resolve_multiagent_replicas(
            {"reviewer": 2},
            3,
            recipe=_recipe(),
        )


def test_rejects_invalid_limits_without_exiting_the_product_process() -> None:
    with pytest.raises(MultiAgentCliUsageError, match="timeout must be positive"):
        parse_multiagent_command(
            (
                "run",
                "parallel-review",
                "--prompt",
                "Review it.",
                "--timeout",
                "0",
            )
        )


def test_projects_recipe_catalog_and_result_as_stable_json() -> None:
    catalog_output = StringIO()
    write_multiagent_recipe_catalog(
        catalog_output,
        (_recipe(),),
        output_format="json",
    )
    assert json.loads(catalog_output.getvalue()) == [
        {
            "id": "parallel-review",
            "description": "Review in parallel.",
            "roles": ["reviewer", "synthesizer"],
        }
    ]

    root = AgentRef(AgentPath.root(), 1)
    reviewer = AgentRef(AgentPath.root().child("reviewer"), 1)
    notice = AgentCompletionNotice(
        notice_id="notice-1",
        sender_ref=reviewer,
        recipient_ref=root,
        round_id=1,
        terminal=TerminalPayload(
            status="completed",
            final_message="Looks good.",
            usage=AgentUsage(
                latest_input_tokens=12,
                cumulative_output_tokens=7,
            ),
            duration_ms=25,
            tool_uses=2,
        ),
        summary="Reviewed.",
    )
    result_output = StringIO()
    write_multiagent_recipe_result(
        result_output,
        RecipeExecutionResult(
            recipe_id="parallel-review",
            notices=(notice,),
            final_notice=notice,
        ),
        output_format="json",
    )

    payload = json.loads(result_output.getvalue())
    assert payload["status"] == "completed"
    assert payload["final_message"] == "Looks good."
    assert payload["agents"] == [
        {
            "path": "/root/reviewer",
            "status": "completed",
            "summary": "Reviewed.",
            "final_message": "Looks good.",
            "duration_ms": 25,
            "usage": {
                "latest_input_tokens": 12,
                "cumulative_output_tokens": 7,
            },
            "tool_uses": 2,
            "workspace_ref": None,
            "artifact_refs": [],
            "change_set_ref": None,
        }
    ]
