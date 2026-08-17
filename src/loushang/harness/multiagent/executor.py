"""Immediate recipe execution over one session-owned multi-agent runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from .context import SubagentContextPlan
from .recipes import CollaborationRecipe, RecipeRole
from .types import (
    AgentCompletionNotice,
    AgentPath,
    AgentRecord,
    ControlCaller,
    HostCaller,
)

RecipeContextBuilder = Callable[
    [RecipeRole, str | None],
    SubagentContextPlan[Any] | None,
]


class ImmediateRecipeRuntime(Protocol):
    """The session operations used by the immediate recipe layer."""

    async def spawn_child(
        self,
        *,
        caller: ControlCaller,
        parent_path: AgentPath,
        name: str,
        agent_type: str,
        initial_prompt: str,
        context_plan: SubagentContextPlan[Any] | None = None,
    ) -> AgentRecord: ...

    async def await_completion(
        self,
        *,
        caller: ControlCaller,
        target: AgentPath,
        timeout: float | None = None,
    ) -> AgentCompletionNotice: ...

    async def close_agent(
        self,
        *,
        caller: ControlCaller,
        target: AgentPath,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class RecipeRunRequest:
    prompt: str
    replicas: Mapping[str, int] = field(default_factory=dict)
    agent_models: Mapping[str, str] = field(default_factory=dict)
    max_parallel: int | None = None
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("recipe prompt must be non-empty")
        replicas = dict(self.replicas)
        agent_models = dict(self.agent_models)
        if any(type(value) is not int or value < 1 for value in replicas.values()):
            raise ValueError("recipe replica counts must be positive integers")
        if any(not value.strip() for value in agent_models.values()):
            raise ValueError("recipe model overrides must be non-empty")
        if self.max_parallel is not None and (
            type(self.max_parallel) is not int or self.max_parallel < 1
        ):
            raise ValueError("max_parallel must be a positive integer")
        if self.timeout is not None:
            if isinstance(self.timeout, bool) or not isinstance(
                self.timeout,
                (int, float),
            ):
                raise TypeError("recipe timeout must be numeric")
            if self.timeout <= 0:
                raise ValueError("recipe timeout must be positive")
        object.__setattr__(self, "replicas", MappingProxyType(replicas))
        object.__setattr__(self, "agent_models", MappingProxyType(agent_models))


@dataclass(frozen=True, slots=True)
class RecipeExecutionResult:
    recipe_id: str
    notices: tuple[AgentCompletionNotice, ...]
    final_notice: AgentCompletionNotice

    @property
    def status(self) -> str:
        return self.final_notice.terminal.status

    @property
    def final_message(self) -> str:
        return self.final_notice.terminal.final_message


class RecipeExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ImmediateRecipeExecutor:
    """Execute bounded phase-one topologies and always release their children."""

    def __init__(
        self,
        runtime: ImmediateRecipeRuntime,
        *,
        caller: ControlCaller | None = None,
        build_context: RecipeContextBuilder | None = None,
    ) -> None:
        self._runtime = runtime
        self._caller = caller or HostCaller()
        self._build_context = build_context or (lambda _role, _model: None)

    async def run(
        self,
        recipe: CollaborationRecipe,
        request: RecipeRunRequest,
    ) -> RecipeExecutionResult:
        self._validate_request(recipe, request)
        owned: list[AgentPath] = []
        primary_error: BaseException | None = None
        try:
            if recipe.recipe_id == "parallel-review":
                return await self._parallel_review(recipe, request, owned)
            if recipe.recipe_id == "debate":
                return await self._debate(recipe, request, owned)
            raise RecipeExecutionError(
                "unsupported_recipe",
                f"immediate execution is not implemented for {recipe.recipe_id!r}",
            )
        except BaseException as error:
            primary_error = error
            raise
        finally:
            cleanup_errors = await self._close_owned(owned)
            if cleanup_errors and primary_error is None:
                joined = "; ".join(str(error) for error in cleanup_errors)
                raise RecipeExecutionError(
                    "recipe_cleanup_failed",
                    f"recipe completed but child cleanup failed: {joined}",
                )

    async def _parallel_review(
        self,
        recipe: CollaborationRecipe,
        request: RecipeRunRequest,
        owned: list[AgentPath],
    ) -> RecipeExecutionResult:
        reviewer = _required_role(recipe, "reviewer")
        synthesizer = _required_role(recipe, "synthesizer")
        replicas = request.replicas.get("reviewer", reviewer.default_replicas)
        parallel = min(replicas, request.max_parallel or replicas)
        notices: list[AgentCompletionNotice] = []

        for start in range(1, replicas + 1, parallel):
            paths = []
            for index in range(start, min(replicas + 1, start + parallel)):
                record = await self._spawn(
                    reviewer,
                    name=f"reviewer-{index}",
                    prompt=(
                        "Independently review the following request. Lead with concrete "
                        f"findings and evidence.\n\n{request.prompt}"
                    ),
                    request=request,
                )
                owned.append(record.path)
                paths.append(record.path)
            notices.extend(await self._await_completions(paths, request))

        evidence = _format_evidence(notices)
        final_record = await self._spawn(
            synthesizer,
            name="synthesizer",
            prompt=(
                "Synthesize the independent reviews below. Preserve disagreements, "
                "separate blockers from optional improvements, and give one final "
                f"recommendation.\n\nRequest:\n{request.prompt}\n\nReviews:\n{evidence}"
            ),
            request=request,
        )
        owned.append(final_record.path)
        final = await self._runtime.await_completion(
            caller=self._caller,
            target=final_record.path,
            timeout=request.timeout,
        )
        return RecipeExecutionResult(
            recipe_id=recipe.recipe_id,
            notices=(*notices, final),
            final_notice=final,
        )

    async def _debate(
        self,
        recipe: CollaborationRecipe,
        request: RecipeRunRequest,
        owned: list[AgentPath],
    ) -> RecipeExecutionResult:
        notices: list[AgentCompletionNotice] = []
        proposer = _required_role(recipe, "proposer")
        critic = _required_role(recipe, "critic")
        judge = _required_role(recipe, "judge")

        proposal = await self._run_one(
            proposer,
            name="proposer",
            prompt=(
                "Make the strongest evidence-based case in favor of the following "
                f"proposal.\n\n{request.prompt}"
            ),
            request=request,
            owned=owned,
        )
        _require_completed(proposal)
        notices.append(proposal)
        critique = await self._run_one(
            critic,
            name="critic",
            prompt=(
                "Challenge the proposal and the argument below. Find counterexamples, "
                "hidden costs, and invalid assumptions.\n\n"
                f"Question:\n{request.prompt}\n\nProposer:\n"
                f"{proposal.terminal.final_message}"
            ),
            request=request,
            owned=owned,
        )
        _require_completed(critique)
        notices.append(critique)
        decision = await self._run_one(
            judge,
            name="judge",
            prompt=(
                "Act as an impartial judge. Evaluate both positions against the "
                "evidence, state unresolved uncertainty, and give a decision.\n\n"
                f"Question:\n{request.prompt}\n\nProposer:\n"
                f"{proposal.terminal.final_message}\n\nCritic:\n"
                f"{critique.terminal.final_message}"
            ),
            request=request,
            owned=owned,
        )
        notices.append(decision)
        return RecipeExecutionResult(
            recipe_id=recipe.recipe_id,
            notices=tuple(notices),
            final_notice=decision,
        )

    async def _run_one(
        self,
        role: RecipeRole,
        *,
        name: str,
        prompt: str,
        request: RecipeRunRequest,
        owned: list[AgentPath],
    ) -> AgentCompletionNotice:
        record = await self._spawn(
            role,
            name=name,
            prompt=prompt,
            request=request,
        )
        owned.append(record.path)
        return await self._runtime.await_completion(
            caller=self._caller,
            target=record.path,
            timeout=request.timeout,
        )

    async def _spawn(
        self,
        role: RecipeRole,
        *,
        name: str,
        prompt: str,
        request: RecipeRunRequest,
    ) -> AgentRecord:
        model = request.agent_models.get(role.name)
        return await self._runtime.spawn_child(
            caller=self._caller,
            parent_path=AgentPath.root(),
            name=name,
            agent_type=role.agent_type,
            initial_prompt=prompt,
            context_plan=self._build_context(role, model),
        )

    async def _await_completions(
        self,
        paths: list[AgentPath],
        request: RecipeRunRequest,
    ) -> tuple[AgentCompletionNotice, ...]:
        tasks = tuple(
            asyncio.create_task(
                self._runtime.await_completion(
                    caller=self._caller,
                    target=path,
                    timeout=request.timeout,
                ),
                name=f"recipe:wait:{path}",
            )
            for path in paths
        )
        try:
            return tuple(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _close_owned(
        self,
        owned: list[AgentPath],
    ) -> tuple[Exception, ...]:
        errors: list[Exception] = []
        for path in reversed(owned):
            try:
                await self._runtime.close_agent(
                    caller=self._caller,
                    target=path,
                )
            except Exception as error:
                errors.append(error)
        return tuple(errors)

    @staticmethod
    def _validate_request(
        recipe: CollaborationRecipe,
        request: RecipeRunRequest,
    ) -> None:
        role_names = {role.name for role in recipe.roles}
        unknown_models = set(request.agent_models) - role_names
        unknown_replicas = set(request.replicas) - role_names
        if unknown_models:
            raise ValueError(
                "model overrides name unknown roles: "
                + ", ".join(sorted(unknown_models))
            )
        if unknown_replicas:
            raise ValueError(
                "replica overrides name unknown roles: "
                + ", ".join(sorted(unknown_replicas))
            )
        for name, count in request.replicas.items():
            role = _required_role(recipe, name)
            if not role.scalable:
                raise ValueError(f"recipe role is not scalable: {name}")
            if not 1 <= count <= role.maximum_replicas:
                raise ValueError(
                    f"{name} replicas must be between 1 and {role.maximum_replicas}"
                )


def _required_role(recipe: CollaborationRecipe, name: str) -> RecipeRole:
    role = recipe.role(name)
    if role is None:
        raise RecipeExecutionError(
            "invalid_recipe",
            f"recipe {recipe.recipe_id!r} is missing required role {name!r}",
        )
    return role


def _require_completed(notice: AgentCompletionNotice) -> None:
    if notice.terminal.status != "completed":
        raise RecipeExecutionError(
            "recipe_agent_failed",
            f"{notice.sender_ref.path} ended as {notice.terminal.status}: "
            f"{notice.terminal.final_message}",
        )


def _format_evidence(notices: list[AgentCompletionNotice]) -> str:
    return "\n\n".join(
        f"### {notice.sender_ref.path} [{notice.terminal.status}]\n"
        f"{notice.terminal.final_message}"
        for notice in notices
    )


__all__ = [
    "ImmediateRecipeExecutor",
    "ImmediateRecipeRuntime",
    "RecipeContextBuilder",
    "RecipeExecutionError",
    "RecipeExecutionResult",
    "RecipeRunRequest",
]
