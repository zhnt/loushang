"""Opt-in Coding Goal SDK for the reviewed finite calculator profile.

Constructs and owns a dedicated original SDK Session. It does not expose a raw
Session or create another execution queue. Product disposal is writer-last.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from loushang.coding import create_agent_session_runtime
from loushang.coding.adapters._goal_calculator import (
    POLICY_ID,
    REQUIREMENTS,
    CalculatorPolicy,
    initial_metadata,
)
from loushang.coding.adapters._goal_store import GoalJournal, goal_journal_path
from loushang.coding.adapters._goal_work_sources import (
    GoalWorkSourceCleanupError as GoalWorkSourceCleanupError,
)
from loushang.coding.adapters._goal_work_sources import (
    GoalWorkSourceView as GoalWorkSourceView,
)
from loushang.coding.adapters._goal_work_sources import (
    _goal_work_facts,
)
from loushang.coding.adapters._goal_work_sources import (
    read_goal_work_sources as read_goal_work_sources,
)
from loushang.coding.adapters._verification_work import CodingVerificationExecutor
from loushang.foundation.platform_paths import resolve_platform_home
from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.policy import PolicyEvaluatorChain
from loushang.harness.transcript.source_reader import TranscriptSourceReader
from loushang.harnesswork import JsonlEventLogBackend, WorkRuntime
from loushang.harnesswork.goal import GoalController, GoalError, GoalHeader, GoalState
from loushang.harnesswork.goal.contracts import GoalBasis, GoalFacts
from loushang.harnesswork.goal.records import plain, replay
from loushang.harnesswork.integrations.transcript import WorkTranscriptSource
from loushang.harnesswork.ports import WorkExecutionBinding
from loushang.harnesswork.types import WorkRecordingPolicy

if TYPE_CHECKING:
    from ._goal_planning_limits import PlanningCallAllowance


@dataclass(frozen=True)
class CodingGoalView:
    goal: GoalState
    validity: str
    reason: str
    execution_unresolved: bool = False
    planning: dict[str, object] | None = None


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


def _validate_goal_session(session, workspace, model_planning):
    if Path(session.session_manager.get_cwd()).resolve() != workspace:
        raise GoalError("restored Session workspace mismatch")
    runner = session.extension_runner
    if runner is not None and any(
        runner.has_handlers(name)
        for name in [
            "user_bash",
            *(["input", "context"] if model_planning else []),
            "tool_call",
            "tool_result",
            "before_agent_start",
        ]
    ):
        raise GoalError("calculator Goal does not support execution-replacing hooks")
    if set(session.get_active_tool_names()) != {"read", "edit", "write"}:
        raise GoalError("calculator Goal requires original file tools")
    if runner is not None and any(
        runner.get_tool_extension_name(name) is not None
        for name in ["read", "edit", "write", "bash"]
    ):
        raise GoalError("calculator Goal does not support replacement tool providers")
    if model_planning:
        session.set_auto_retry_enabled(False)
        session.set_auto_compaction_enabled(False)
        if session.auto_retry_enabled or session.auto_compaction_enabled:
            raise GoalError(
                "model planning requires Session retry and compaction disabled"
            )


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
        self._model_planning = False
        self._profile = None
        self._allowance: PlanningCallAllowance | None = None
        self._source_reader: TranscriptSourceReader | None = None
        self._source_retired = False
        self._delegation = None

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
        model_planning: bool = False,
        transcript_retained_until: datetime | None = None,
    ) -> CodingGoal:
        return await cls._open(
            workspace=workspace,
            data_root=data_root,
            model=model,
            session_id=session_id,
            stream_fn=stream_fn,
            approval_resolver=approval_resolver,
            tool_policy_evaluator=tool_policy_evaluator,
            model_planning=model_planning,
            transcript_retained_until=transcript_retained_until,
        )

    @classmethod
    async def _open(
        cls,
        *,
        workspace: Path,
        data_root: Path,
        model=None,
        session_id: str | None = None,
        stream_fn=None,
        approval_resolver=None,
        tool_policy_evaluator=None,
        model_planning: bool = False,
        profile=None,
        transcript_retained_until: datetime | None = None,
    ) -> CodingGoal:
        if type(model_planning) is not bool:
            raise GoalError("model_planning must be an explicit boolean")
        if transcript_retained_until is not None and (
            not isinstance(transcript_retained_until, datetime)
            or transcript_retained_until.utcoffset() is None
        ):
            raise GoalError("Transcript retention requires a timezone-aware datetime")
        if model_planning and (stream_fn is not None or session_id is not None):
            raise GoalError(
                "model planning requires a fresh Session and the standard AI stream"
            )
        owner = cls(workspace.resolve(), data_root.resolve())
        owner._model_planning = model_planning
        owner._profile = profile
        try:
            policy_id = POLICY_ID
            if model_planning:
                from ._goal_planning_limits import PlanningCallAllowance
                from ._goal_planning_work import PlanningToolPolicy
                from ._goal_proposal import POLICY_ID as PLANNING_POLICY_ID

                owner._allowance = PlanningCallAllowance()
                planning_tool_policy = (
                    profile.tool_policy(owner.workspace)
                    if profile is not None
                    else PlanningToolPolicy(owner.workspace)
                )
                tool_policy_evaluator = PolicyEvaluatorChain(
                    (planning_tool_policy, tool_policy_evaluator)
                    if tool_policy_evaluator is not None
                    else (planning_tool_policy,),
                    strategy="most_restrictive",
                )
                stream_fn = owner._allowance.stream
                policy_id = (
                    profile.policy_id if profile is not None else PLANNING_POLICY_ID
                )
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
                system_prompt=profile.system_prompt
                if profile is not None
                else (
                    "Pursue the supplied finite Coding Goal. In planning turns, choose "
                    "a next action and revisable route using current evidence; return "
                    "only the required JSON and do not call tools. In Method execution "
                    "turns follow the explicit step, changing only calculator.py. "
                    "Do not modify requirements, tests, Method or permissions. "
                    "Only independent verification can establish Goal completion."
                    if model_planning
                    else "You repair a finite integer calculator using the supplied explicit Method. "
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
            _validate_goal_session(owner._session, owner.workspace, model_planning)
            header = GoalHeader(owner.session_id, owner.session_id, policy_id)
            owner._store = GoalJournal(owner.data_root / "sessions", header)
            owner._store.open(create=session_id is None)
            transcript_source = None
            delegated = getattr(profile, "execution_policy", None) is not None
            if transcript_retained_until is not None or delegated:
                session_file = owner._session.session_manager.get_session_file()
                if session_file is None:
                    raise GoalError(
                        "Goal Transcript source requires a persistent Session"
                    )
                owner._source_reader = TranscriptSourceReader(
                    session_file=Path(session_file),
                    conversation_id=owner.session_id,
                    store_state_root=resolve_platform_home() / "state/session-stores",
                )
                if transcript_retained_until is not None:
                    transcript_source = await WorkTranscriptSource.bind(
                        owner._source_reader,
                        binding_id=f"coding-goal:{owner.session_id}",
                        retained_until=transcript_retained_until,
                    )
            blobs = SessionBlobStore(owner.data_root, owner.session_id)
            if delegated:
                from ._goal_delegation import DelegatedSessions

                identity = await owner._source_reader.inspect_identity()
                owner._delegation = DelegatedSessions(
                    owner,
                    profile,
                    blobs,
                    owner._source_reader,
                    identity.store_identity,
                    approval_resolver,
                )
            work_path = goal_journal_path(
                owner.data_root / "sessions", owner.session_id
            ).with_suffix(".work.jsonl")
            log = JsonlEventLogBackend(work_path)
            executor = CodingVerificationExecutor(
                session=owner._session, blobs=blobs, event_log=log
            )
            verification_executor: Any = executor
            if model_planning:
                from ._goal_planning_work import ScopedVerificationWork

                verification_executor = ScopedVerificationWork(
                    executor, policy=planning_tool_policy
                )
            owner._work = WorkRuntime(
                event_log=log,
                resolver=_Resolver(verification_executor, owner._prepared),
                recording_version=1,
                recording_policy=WorkRecordingPolicy(require_persistence=True),
            )
            owner._policy = CalculatorPolicy(
                workspace=owner.workspace,
                session=owner._session,
                blobs=blobs,
                event_log=log,
                prepared=owner._prepared,
                transcript_source=transcript_source,
            )
            if model_planning:
                from ._goal_planning import ModelPlanningPolicy

                factory = profile.policy if profile is not None else ModelPlanningPolicy
                owner._policy = factory(
                    workspace=owner.workspace,
                    session=owner._session,
                    blobs=blobs,
                    event_log=log,
                    prepared=owner._prepared,
                    transcript_source=transcript_source,
                    allowance=owner._allowance,
                    tool_policy=planning_tool_policy,
                    history=lambda: owner.controller.history,
                )
            if owner._delegation is not None:
                owner._policy.delegation = owner._delegation
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

    def create(self, goal_id: str, *, command_id: str, limit: int | None = None):
        self._open_for_commands()
        limit = (20 if self._model_planning else 6) if limit is None else limit
        if self._model_planning and limit != 20:
            raise GoalError("model-planning profile fixes the total Work limit at 20")
        if self._delegation is not None and any(
            old != goal_id for old in self.controller.history.goals
        ):
            raise GoalError("delegated profile requires a fresh owner for a new Goal")
        prior = self.controller.history.commands.get(command_id)
        metadata = (
            json.loads(prior.request)["data"]["metadata"]
            if prior is not None
            else (
                self._profile.initial_metadata(self.workspace, self._policy.blobs)
                if self._profile is not None
                else initial_metadata(self.workspace, self._policy.blobs)
            )
        )
        if self._model_planning and prior is None:
            from ._goal_proposal import LIMITS

            metadata = {
                **metadata,
                "profile": self.controller.header.policy_id,
                "planning_limits": self._profile.limits
                if self._profile is not None
                else LIMITS,
            }
        return self.controller.create(
            goal_id,
            (self._profile.requirements if self._profile is not None else REQUIREMENTS),
            command_id=command_id,
            limit=limit,
            metadata=metadata,
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

    def planning_trace(self, goal_id: str) -> dict[str, object]:
        """Inspect original facts; never advance, call a model or authorize work."""
        if not self._model_planning:
            raise GoalError("this Goal does not use model planning")
        self._open_for_commands()
        core = self.controller
        state, facts = core.query(goal_id), core.facts()
        return self._policy.trace(
            GoalBasis(core.header, state, core.history.sequence), facts
        )

    def follow_up(self, goal_id: str, text: str, *, images=None) -> None:
        self._input(goal_id, "follow_up", text, images)

    def clear_queue(self):
        self._open_for_commands()
        if self._delegation is not None:
            raise GoalError("direct input unsupported for delegated Goal")
        return self._session.clear_queue()

    def _input(self, goal_id: str, method: str, text: str, images) -> None:
        self._open_for_commands()
        if self._delegation is not None:
            raise GoalError("direct input unsupported for delegated Goal")
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
        if self._allowance is not None and self._allowance.fenced:
            raise GoalError("Coding Goal planning configuration fenced")

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
            if self._delegation is not None:
                await self._delegation.close()
            if not self._source_retired:
                if self._source_reader is not None:
                    await self._source_reader.aclose()
                self._source_retired = True
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
    return _inspect_goal(
        workspace=workspace, data_root=data_root, session_id=session_id, goal_id=goal_id
    )


def _inspect_goal(*, workspace, data_root, session_id, goal_id, profile=None):
    """Cold read without creating a model Session, dispatching or writing events."""
    header = GoalHeader(
        session_id, session_id, profile.policy_id if profile is not None else POLICY_ID
    )
    store = GoalJournal(data_root.resolve() / "sessions", header, read_only=True)
    try:
        store.open()
        actual, records = store.load()
        history = replay(actual, records)
        state = history.goal(goal_id)
        from ._goal_proposal import LIMITS
        from ._goal_proposal import POLICY_ID as PLANNING_POLICY_ID

        supported = actual == header or actual == GoalHeader(
            session_id, session_id, PLANNING_POLICY_ID
        )
        if not supported:
            return CodingGoalView(state, "not_checked", "unsupported_policy")
        if actual.policy_id == PLANNING_POLICY_ID and (
            plain(state.metadata.get("planning_limits")) != LIMITS
            or state.limit != LIMITS["work_intents"]
        ):
            return CodingGoalView(state, "not_checked", "unsupported_planning_limits")
        path = goal_journal_path(
            data_root.resolve() / "sessions", session_id
        ).with_suffix(".work.jsonl")
        log = JsonlEventLogBackend(path)
        runs, unresolved = _goal_work_facts(history, log.query(), session_id)
        blobs = SessionBlobStore(data_root.resolve(), session_id, read_only=True)
        if profile is not None:
            return profile.inspect(
                workspace,
                data_root,
                session_id,
                goal_id,
                actual,
                history,
                log,
                runs,
                unresolved,
                blobs,
            )
        policy = CalculatorPolicy(
            workspace=workspace.resolve(),
            session=SimpleNamespace(pending_message_count=0),
            blobs=blobs,
            event_log=log,
            prepared={},
            policy_id=actual.policy_id,
        )
        assessment = policy.assess_now(
            GoalBasis(actual, state, history.sequence),
            GoalFacts(history.batches, runs, unresolved=unresolved),
        )
        view = _view(state, assessment, unresolved=unresolved)
        if actual.policy_id != PLANNING_POLICY_ID:
            return view
        try:
            from ._goal_planning import ModelPlanningPolicy
            from ._goal_planning_history import PlanningHistory

            manager = (
                PlanningHistory(data_root.resolve() / "sessions", session_id, blobs)
                if any(b.source.get("phase") == "planning" for b in history.batches)
                else None
            )
            reader = ModelPlanningPolicy(
                workspace=workspace.resolve(),
                session=SimpleNamespace(session_id=session_id, session_manager=manager),
                blobs=blobs,
                event_log=log,
                prepared={},
                allowance=None,
                tool_policy=None,
                history=lambda: history,
            )
            trace = reader.trace(
                GoalBasis(actual, state, history.sequence),
                GoalFacts(history.batches, runs, unresolved=unresolved),
            )
        except (ValueError, OSError, KeyError) as error:
            trace = {"status": "unknown", "reason": str(error)}
        return replace(view, planning=trace)
    finally:
        store.close()
