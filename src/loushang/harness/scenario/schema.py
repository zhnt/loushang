from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from loushang.harness.scenario.events import EventPattern, WorkflowEvent


@dataclass(frozen=True)
class CommandExpectation:
    run: str
    exit_code: int = 0
    stdout_contains: tuple[str, ...] = ()
    stderr_contains: tuple[str, ...] = ()
    stderr_not_contains: tuple[str, ...] = ()
    timeout_s: float | None = None


@dataclass(frozen=True)
class StepExpectation:
    assistant_contains: tuple[str, ...] = ()
    assistant_contains_any: tuple[str, ...] = ()
    assistant_not_contains: tuple[str, ...] = ()
    files_exist: tuple[str, ...] = ()
    files_not_exist: tuple[str, ...] = ()
    files_contain: dict[str, str] = field(default_factory=dict)
    command: CommandExpectation | None = None
    no_traceback: bool = False


@dataclass(frozen=True)
class PromptStep:
    prompt: str
    timeout_s: float | None = None
    hold: bool = False
    expect: StepExpectation = field(default_factory=StepExpectation)
    kind: Literal["prompt"] = "prompt"


@dataclass(frozen=True)
class WaitForStep:
    event: str = ""
    timeout_s: float = 5.0
    kind: Literal["wait_for"] = "wait_for"


@dataclass(frozen=True)
class WaitStep:
    duration_s: float = 0.0
    kind: Literal["wait"] = "wait"


@dataclass(frozen=True)
class SteerStep:
    text: str = ""
    kind: Literal["steer"] = "steer"


@dataclass(frozen=True)
class FollowUpStep:
    text: str = ""
    kind: Literal["follow_up"] = "follow_up"


@dataclass(frozen=True)
class AbortStep:
    kind: Literal["abort"] = "abort"


@dataclass(frozen=True)
class WorkflowExpectation:
    events: tuple[EventPattern, ...] = ()
    not_events: tuple[EventPattern, ...] = ()
    queue: dict[str, tuple[str, ...]] = field(default_factory=dict)
    session_state: dict[str, object] = field(default_factory=dict)
    session_stats: dict[str, object] = field(default_factory=dict)
    context_usage: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExpectStep:
    expect: WorkflowExpectation = field(default_factory=WorkflowExpectation)
    kind: Literal["expect"] = "expect"


WorkflowStep: TypeAlias = (
    PromptStep
    | WaitForStep
    | WaitStep
    | SteerStep
    | FollowUpStep
    | AbortStep
    | ExpectStep
)


@dataclass(frozen=True)
class Workflow:
    name: str
    steps: tuple[WorkflowStep, ...]
    backend: str | None = None


@dataclass(frozen=True)
class CheckResult:
    label: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class WorkflowStepResult:
    index: int
    prompt: str
    assistant_text: str = ""
    checks: tuple[CheckResult, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(check.ok for check in self.checks)


@dataclass(frozen=True)
class WorkflowResult:
    name: str
    step_results: tuple[WorkflowStepResult, ...]
    events: tuple[WorkflowEvent, ...] = ()

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.step_results)
