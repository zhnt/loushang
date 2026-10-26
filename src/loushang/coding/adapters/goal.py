"""Opt-in Coding Goal SDK for the reviewed finite calculator profile.

Constructs and owns a dedicated original SDK Session. It does not expose a raw
Session or create another execution queue. Product disposal is writer-last.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loushang.coding import create_agent_session_runtime
from loushang.coding.adapters._goal_calculator import (
    POLICY_ID,
    REQUIREMENTS,
    CalculatorPolicy,
    initial_metadata,
)
from loushang.coding.adapters._goal_store import GoalJournal, goal_journal_path
from loushang.coding.adapters._verification_work import CodingVerificationExecutor
from loushang.harness.artifacts import SessionBlobStore
from loushang.harnesswork import JsonlEventLogBackend, WorkRuntime
from loushang.harnesswork.cancellation_projection import project_work_cancellations
from loushang.harnesswork.goal import GoalController, GoalError, GoalHeader, GoalState
from loushang.harnesswork.goal.contracts import GoalBasis, GoalFacts
from loushang.harnesswork.goal.records import replay
from loushang.harnesswork.ports import WorkExecutionBinding
from loushang.harnesswork.run_projection import project_work_runs


@dataclass(frozen=True)
class CodingGoalView:
    goal: GoalState
    validity: str
    reason: str
    execution_unresolved: bool = False


def _view(state, assessment, *, unresolved=False, busy=False) -> CodingGoalView:
    validity = (
        "unknown"
        if unresolved or busy
        else "current"
        if assessment.status == "satisfied"
        else assessment.proof.get("validity", "unknown")
        if assessment.status == "needs_user"
        else "outdated"
        if state.status == "completed"
        else "not_satisfied"
    )
    return CodingGoalView(state, validity, assessment.reason, unresolved)


class GoalConstructionError(RuntimeError):
    """Construction failed and its cleanup owner must be retained for close."""

    def __init__(self, owner: CodingGoal, error: BaseException):
        super().__init__("Goal construction cleanup pending")
        self.owner, self.error = owner, error


class _Resolver:
    def __init__(self, verification, prepared):
        self.verification, self.prepared = verification, prepared

    def resolve(self, operation, spec):
        if operation.kind == "VerifyCodingCommand":
            return WorkExecutionBinding(self.verification)
        if operation.operation_id not in self.prepared:
            raise GoalError("unprepared Coding Goal operation")
        return self.prepared.pop(operation.operation_id)


class CodingGoal:
    """A retained Product owner. Use open(); retain exceptions with cleanup owner."""

    def __init__(self, workspace: Path, data_root: Path):
        self.workspace, self.data_root = workspace, data_root
        self.session_id = ""
        self._sdk: Any = None
        self._session: Any = None
        self._store: Any = None
        self._core: GoalController | None = None
        self._policy: Any = None
        self._work: Any = None
        self._closing = self._closed = False
        self._queries: set[asyncio.Task] = set()
        self._close_task: asyncio.Task | None = None
        self._query_cleanup_error: BaseException | None = None
        self._callbacks_quiet = self._work_settled = False
        self._session_retired = self._core_retired = self._writer_closed = False
        self._prepared: dict[str, WorkExecutionBinding] = {}

    @classmethod
    async def open(
        cls,
        *,
        workspace: Path,
        data_root: Path,
        model=None,
        session_id: str | None = None,
        stream_fn=None,
        approval_resolver=None,
        tool_policy_evaluator=None,
    ) -> CodingGoal:
        owner = cls(workspace.resolve(), data_root.resolve())
        try:
            owner._sdk = create_agent_session_runtime(
                session_dir=owner.data_root / "sessions",
                model=model,
                stream_fn=stream_fn,
                active_tool_names=["read", "edit", "write"],
                allowed_tool_names=["read", "edit", "write", "bash"],
                composition_set="coding-standard",
                enable_multiagent=False,
                approval_resolver=approval_resolver,
                tool_policy_evaluator=tool_policy_evaluator,
                system_prompt=(
                    "You repair a finite integer calculator using the supplied explicit Method. "
                    "Use read/edit/write file tools only. Change only calculator.py. "
                    "Do not change tests, Method or project paths. Do not claim Goal completion."
                ),
            )
            owner._session = (
                await owner._sdk.create_session(cwd=str(owner.workspace))
                if session_id is None
                else await owner._sdk.restore_session(session_id)
            )
            owner.session_id = owner._session.session_id
            if (
                Path(owner._session.session_manager.get_cwd()).resolve()
                != owner.workspace
            ):
                raise GoalError("restored Session workspace mismatch")
            runner = owner._session.extension_runner
            if runner is not None and any(
                runner.has_handlers(name)
                for name in [
                    "user_bash",
                    "tool_call",
                    "tool_result",
                    "before_agent_start",
                ]
            ):
                raise GoalError(
                    "calculator Goal does not support execution-replacing hooks"
                )
            if set(owner._session.get_active_tool_names()) != {"read", "edit", "write"}:
                raise GoalError("calculator Goal requires original file tools")
            if runner is not None and any(
                runner.get_tool_extension_name(name) is not None
                for name in ["read", "edit", "write", "bash"]
            ):
                raise GoalError(
                    "calculator Goal does not support replacement tool providers"
                )
            header = GoalHeader(owner.session_id, owner.session_id, POLICY_ID)
            owner._store = GoalJournal(owner.data_root / "sessions", header)
            owner._store.open(create=session_id is None)
            blobs = SessionBlobStore(owner.data_root, owner.session_id)
            work_path = goal_journal_path(
                owner.data_root / "sessions", owner.session_id
            ).with_suffix(".work.jsonl")
            log = JsonlEventLogBackend(work_path)
            executor = CodingVerificationExecutor(
                session=owner._session, blobs=blobs, event_log=log
            )
            owner._work = WorkRuntime(
                event_log=log, resolver=_Resolver(executor, owner._prepared)
            )
            owner._policy = CalculatorPolicy(
                workspace=owner.workspace,
                session=owner._session,
                blobs=blobs,
                event_log=log,
                prepared=owner._prepared,
            )
            owner._core = GoalController(
                header=header,
                store=owner._store,
                work=owner._work,
                next_work=owner._policy,
                acceptance=owner._policy,
            )
            return owner
        except BaseException as error:
            try:
                await owner.close()
            except BaseException:
                raise GoalConstructionError(owner, error) from error
            raise

    @property
    def controller(self) -> GoalController:
        # The handle exposes Goal control, never the mutable Session/Work.
        if self._core is None:
            raise GoalError("Goal not open")
        return self._core

    def create(self, goal_id: str, *, command_id: str, limit: int = 6):
        self._open_for_commands()
        prior = self.controller.history.commands.get(command_id)
        metadata = (
            json.loads(prior.request)["data"]["metadata"]
            if prior is not None
            else initial_metadata(self.workspace, self._policy.blobs)
        )
        return self.controller.create(
            goal_id, REQUIREMENTS, command_id=command_id, limit=limit, metadata=metadata
        )

    async def advance(
        self, goal_id: str, *, command_id: str, revision: int, epoch: int
    ):
        self._open_for_commands()
        try:
            return await self.controller.advance(
                goal_id, command_id=command_id, revision=revision, epoch=epoch
            )
        finally:
            # Resolver consumes accepted bindings. Drop only preparations which
            # never acquired an original Work, including rejected/stale proposals.
            for op in tuple(self._prepared):
                if self._work.get_run_for_operation(op) is None:
                    self._prepared.pop(op, None)

    async def query(self, goal_id: str) -> CodingGoalView:
        core = self.controller
        state = core.query(goal_id)
        if self._closing or self._closed or core.fenced:
            return CodingGoalView(state, "not_checked", "closing_or_fenced")
        task = asyncio.current_task()
        if task:
            self._queries.add(task)
        try:
            facts = core.facts()
            assessment = await self._policy.assess(
                GoalBasis(core.header, state, core.history.sequence), facts
            )
            return _view(
                state, assessment, unresolved=facts.unresolved, busy=facts.busy
            )
        finally:
            if task:
                self._queries.discard(task)

    def steer(self, goal_id: str, text: str, *, images=None) -> None:
        self._input(goal_id, "steer", text, images)

    def follow_up(self, goal_id: str, text: str, *, images=None) -> None:
        self._input(goal_id, "follow_up", text, images)

    def clear_queue(self):
        self._open_for_commands()
        return self._session.clear_queue()

    def _input(self, goal_id: str, method: str, text: str, images) -> None:
        self._open_for_commands()
        core = self.controller
        state = core.query(goal_id)
        batches = [
            b
            for b in core.history.batches
            if b.goal_id == goal_id and not b.not_submitted
        ]
        batch = batches[-1] if batches else None
        run = self._work.get_run_for_operation(batch.operation_id) if batch else None
        if (
            state.status != "active"
            or batch is None
            or batch.source.get("phase") != "repair"
            or run is None
            or run.status != "running"
        ):
            raise GoalError("execution input unavailable outside running repair")
        getattr(self._session, method)(text, images=images)

    def _open_for_commands(self):
        if self._closing or self._closed or self.controller.fenced:
            raise GoalError("Coding Goal closing or fenced")

    async def close(self) -> None:
        self._closing = True
        if self._closed:
            return
        if self._core is not None:
            self._core.begin_close()
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(
                self._close(), name="coding-goal-close"
            )
        # Caller cancellation retains the original cleanup task and owner.
        await asyncio.shield(self._close_task)

    async def _close(self):
        if not self._callbacks_quiet:
            if self._query_cleanup_error is not None:
                raise self._query_cleanup_error
            current = asyncio.current_task()
            queries = tuple(t for t in self._queries if t is not current)
            for task in queries:
                task.cancel()
            if queries:
                results = await asyncio.gather(*queries, return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException) and not isinstance(
                        result, asyncio.CancelledError
                    ):
                        self._query_cleanup_error = result
                        raise result
            if self._core is not None:
                await self._core.quiesce()
            self._callbacks_quiet = True
        if not self._work_settled:
            if self._core is not None:
                await self._core.settle_work()
            self._work_settled = True
        if not self._session_retired:
            if self._sdk is not None:
                await self._sdk.dispose_session_runtime()
            self._session_retired = True
        if not self._core_retired:
            if self._core is not None:
                self._core.retire()
            self._core_retired = True
        if not self._writer_closed:
            if self._store is not None:
                self._store.close()
            self._writer_closed = True
        self._prepared.clear()
        self._closed = True


def inspect_goal(
    *, workspace: Path, data_root: Path, session_id: str, goal_id: str
) -> CodingGoalView:
    """Cold read without creating a model Session, dispatching or writing events."""
    header = GoalHeader(session_id, session_id, POLICY_ID)
    store = GoalJournal(data_root.resolve() / "sessions", header, read_only=True)
    try:
        store.open()
        actual, records = store.load()
        history = replay(actual, records)
        state = history.goal(goal_id)
        if actual != header:
            return CodingGoalView(state, "not_checked", "unsupported_policy")
        path = goal_journal_path(
            data_root.resolve() / "sessions", session_id
        ).with_suffix(".work.jsonl")
        log = JsonlEventLogBackend(path)
        runs = tuple(project_work_runs(log.query(), mark_incomplete_orphaned=True))
        unresolved = any(
            not b.not_submitted
            and not any(
                r.operation_id == b.operation_id and r.status != "orphaned"
                for r in runs
            )
            for b in history.batches
        )
        cancellations = {r.run_id: r for r in project_work_cancellations(log.query())}
        for b in history.batches:
            if b.not_submitted:
                continue
            found = next((r for r in runs if r.operation_id == b.operation_id), None)
            if found is not None:
                if found.session_id != session_id or (
                    b.run_receipt and b.run_receipt != found.run_id
                ):
                    raise GoalError("Goal/Work association mismatch")
                observation = cancellations.get(found.run_id)
                if observation is None or observation.status not in {
                    "not_requested",
                    "settled",
                }:
                    unresolved = True
        if any(
            b.not_submitted and any(r.operation_id == b.operation_id for r in runs)
            for b in history.batches
        ):
            raise GoalError("not_submitted contradicts original Work")
        blobs = SessionBlobStore(data_root.resolve(), session_id, read_only=True)
        policy = CalculatorPolicy(
            workspace=workspace.resolve(),
            session=SimpleNamespace(pending_message_count=0),
            blobs=blobs,
            event_log=log,
            prepared={},
        )
        assessment = policy.assess_now(
            GoalBasis(actual, state, history.sequence),
            GoalFacts(history.batches, runs, unresolved=unresolved),
        )
        return _view(state, assessment, unresolved=unresolved)
    finally:
        store.close()
