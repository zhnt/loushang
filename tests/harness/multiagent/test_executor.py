from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from loushang.harness.multiagent import (
    AgentPath,
    AgentTypeRegistry,
    AgentTypeSpec,
    ForkedHistory,
    ForkTier,
    HostCaller,
    ImmediateRecipeExecutor,
    MultiAgentControl,
    RecipeExecutionError,
    RecipeRunRequest,
    SubagentContextPlan,
    core_recipe_catalog,
)

NOW = datetime(2026, 7, 26, tzinfo=UTC)
HOST = HostCaller()


class _Runtime:
    def __init__(
        self,
        *,
        fail_await_for: str | None = None,
        failed_agents: frozenset[str] = frozenset(),
    ) -> None:
        self.control = MultiAgentControl(
            agent_types=AgentTypeRegistry(
                AgentTypeSpec(
                    name=name,
                    maximum_children=3 if name == "reviewer" else 1,
                )
                for name in ("reviewer", "synthesizer", "proposer", "critic", "judge")
            ),
            clock=lambda: NOW,
        )
        self.prompts: dict[AgentPath, str] = {}
        self.context_models: dict[AgentPath, str | None] = {}
        self.closed: list[AgentPath] = []
        self.fail_await_for = fail_await_for
        self.failed_agents = failed_agents

    async def spawn_child(
        self,
        *,
        caller,
        parent_path,
        name,
        agent_type,
        initial_prompt,
        context_plan=None,
    ):
        record = self.control.spawn(
            caller=caller,
            parent_path=parent_path,
            name=name,
            agent_type=agent_type,
        )
        self.prompts[record.path] = initial_prompt
        self.context_models[record.path] = (
            context_plan.model if context_plan is not None else None
        )
        running = self.control.begin_round(record.ref)
        assert running.record is not None
        transition = self.control.finish_round(
            record.ref,
            round_id=running.record.round_id,
            status="failed" if name in self.failed_agents else "completed",
            final_message=(
                f"Failure from {record.path}"
                if name in self.failed_agents
                else f"Full response from {record.path}"
            ),
            duration_ms=1,
            summary=f"Summary from {record.path}",
        )
        assert transition.record is not None
        return transition.record

    async def await_completion(self, *, caller, target, timeout=None):
        del caller, timeout
        if target.name == self.fail_await_for:
            raise RuntimeError("configured wait failure")
        record = self.control.registry.current(target)
        assert record is not None
        notice = self.control.completion_notice(
            record.ref,
            round_id=record.round_id,
        )
        assert notice is not None
        return notice

    async def close_agent(self, *, caller, target):
        plan = self.control.plan_close_tree(caller=caller, target=target)
        for record in plan:
            self.control.commit_closed(record.ref)
            self.closed.append(record.path)
        return tuple(plan)


def _recipe(recipe_id: str):
    recipe = core_recipe_catalog().resolve(recipe_id)
    assert recipe is not None
    return recipe


def test_parallel_review_fans_out_then_synthesizes_full_terminal_messages() -> None:
    async def scenario() -> None:
        runtime = _Runtime()
        executor = ImmediateRecipeExecutor(runtime)

        result = await executor.run(
            _recipe("parallel-review"),
            RecipeRunRequest(
                prompt="Review this architecture.",
                replicas={"reviewer": 3},
            ),
        )

        assert [notice.sender_ref.path.name for notice in result.notices] == [
            "reviewer-1",
            "reviewer-2",
            "reviewer-3",
            "synthesizer",
        ]
        synthesizer_prompt = runtime.prompts[AgentPath.root().child("synthesizer")]
        assert "Full response from /root/reviewer-1" in synthesizer_prompt
        assert result.final_message == "Full response from /root/synthesizer"
        assert set(runtime.closed) == set(runtime.prompts)

    asyncio.run(scenario())


def test_debate_runs_proposer_critic_judge_and_applies_role_model_context() -> None:
    def build_context(role, model):
        return SubagentContextPlan(
            system_prompt=f"System prompt for {role.name}",
            model=model,
            history=ForkedHistory(
                requested_tier=ForkTier.none(),
                effective_tier=ForkTier.none(),
                watermark=None,
                messages=(),
            ),
        )

    async def scenario() -> None:
        runtime = _Runtime()
        executor = ImmediateRecipeExecutor(runtime, build_context=build_context)

        result = await executor.run(
            _recipe("debate"),
            RecipeRunRequest(
                prompt="Adopt the proposal?",
                agent_models={"critic": "provider/critic-model"},
            ),
        )

        assert [notice.sender_ref.path.name for notice in result.notices] == [
            "proposer",
            "critic",
            "judge",
        ]
        assert runtime.context_models[AgentPath.root().child("critic")] == (
            "provider/critic-model"
        )
        assert (
            "Full response from /root/proposer"
            in runtime.prompts[AgentPath.root().child("critic")]
        )
        assert (
            "Full response from /root/critic"
            in runtime.prompts[AgentPath.root().child("judge")]
        )

    asyncio.run(scenario())


def test_recipe_failure_closes_every_child_that_was_already_spawned() -> None:
    async def scenario() -> None:
        runtime = _Runtime(fail_await_for="reviewer-2")
        executor = ImmediateRecipeExecutor(runtime)

        with pytest.raises(RuntimeError, match="configured wait failure"):
            await executor.run(
                _recipe("parallel-review"),
                RecipeRunRequest(prompt="Review.", replicas={"reviewer": 2}),
            )

        assert set(runtime.closed) == {
            AgentPath.root().child("reviewer-1"),
            AgentPath.root().child("reviewer-2"),
        }

    asyncio.run(scenario())


def test_recipe_rejects_unknown_or_unbounded_overrides_before_spawning() -> None:
    runtime = _Runtime()
    executor = ImmediateRecipeExecutor(runtime)

    with pytest.raises(ValueError, match="unknown roles"):
        asyncio.run(
            executor.run(
                _recipe("debate"),
                RecipeRunRequest(
                    prompt="Decide.",
                    agent_models={"reviewer": "provider/model"},
                ),
            )
        )
    with pytest.raises(ValueError, match="between 1 and 3"):
        asyncio.run(
            executor.run(
                _recipe("parallel-review"),
                RecipeRunRequest(prompt="Review.", replicas={"reviewer": 4}),
            )
        )
    assert runtime.prompts == {}


def test_debate_stops_after_a_failed_required_role() -> None:
    async def scenario() -> None:
        runtime = _Runtime(failed_agents=frozenset({"proposer"}))
        executor = ImmediateRecipeExecutor(runtime)

        with pytest.raises(RecipeExecutionError) as error:
            await executor.run(
                _recipe("debate"),
                RecipeRunRequest(prompt="Adopt it?"),
            )

        assert error.value.code == "recipe_agent_failed"
        assert AgentPath.root().child("critic") not in runtime.prompts
        assert runtime.closed == [AgentPath.root().child("proposer")]

    asyncio.run(scenario())
