"""Optional Goal coordination over the original local WorkRuntime.

The controller borrows its collaborators. Product owns physical storage, domain
truth and Session disposal. One explicit advance admits at most one Work.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import uuid4

from loushang.harnesswork.runtime import WorkRuntime
from loushang.harnesswork.types import WorkOperation, WorkRunSpec, WorkStepSpec

from .contracts import (
    GoalAcceptancePolicy,
    GoalAssessment,
    GoalBasis,
    GoalFacts,
    GoalRecordStore,
    NextWorkPolicy,
    PolicyStop,
    WorkCandidate,
)
from .records import (
    TERMINAL,
    CommandReceipt,
    GoalError,
    GoalHeader,
    GoalHistory,
    GoalRecord,
    GoalState,
    Requirement,
    canonical,
    plain,
    positive,
    replay,
    text,
)


class GoalController:
    def __init__(
        self,
        *,
        header: GoalHeader,
        store: GoalRecordStore,
        work: WorkRuntime,
        next_work: NextWorkPolicy,
        acceptance: GoalAcceptancePolicy,
    ) -> None:
        self.header, self._store, self._work = header, store, work
        self._next, self._acceptance = next_work, acceptance
        self._fenced = False
        self._retired = False
        self._quiescing = False
        self._quiescence_error: BaseException | None = None
        self._inflight: set[asyncio.Task[object]] = set()
        self._advancing = False
        self.last_error: BaseException | None = None
        self._history = replay(header, ())
        self._reload()
        self.facts()  # Detect contradictory not-submitted/Work history on open.

    @property
    def fenced(self) -> bool:
        return self._fenced or self._retired

    @property
    def history(self) -> GoalHistory:
        return self._history

    def query(self, goal_id: str) -> GoalState:
        return self._history.goal(goal_id)

    def facts(self) -> GoalFacts:
        if self._retired:
            raise GoalError("Goal controller retired")
        runs = []
        unresolved = False
        for batch in self._history.batches:
            run = self._work.get_run_for_operation(batch.operation_id)
            if batch.not_submitted:
                if run is not None:
                    self.fence()
                    raise GoalError("not_submitted contradicts original Work")
                continue
            if run is None:
                unresolved = True
                continue
            if run.session_id != self.header.session_id or (
                batch.run_receipt is not None and batch.run_receipt != run.run_id
            ):
                self.fence()
                raise GoalError("Work identity contradicts Goal association")
            runs.append(run)
            if run.status == "orphaned":
                unresolved = True
            elif run.status in {"completed", "failed", "cancelled"}:
                # A cancelled Work alone does not prove that its effects settled.
                try:
                    unresolved |= self._work.get_cancellation(
                        run.run_id
                    ).status not in {"not_requested", "settled"}
                except Exception:
                    unresolved = True
        busy = bool(self._work.active_runs(session_id=self.header.session_id))
        return GoalFacts(self._history.batches, tuple(runs), busy, unresolved)

    def create(
        self,
        goal_id: str,
        requirements: Sequence[Requirement],
        *,
        command_id: str,
        limit: int,
        metadata: Mapping[str, object] | None = None,
    ) -> CommandReceipt:
        request = {
            "requirements": self._requirements(requirements),
            "limit": positive(limit),
            "metadata": dict(metadata or {}),
        }
        cached = self._begin("create", goal_id, command_id, 0, 0, request)
        if cached:
            return cached
        self._append("created", goal_id, command_id, request)
        return self._finish(goal_id, command_id, "created")

    def revise(
        self,
        goal_id: str,
        requirements: Sequence[Requirement],
        *,
        command_id: str,
        revision: int,
        epoch: int,
        reason: str,
    ) -> CommandReceipt:
        data = {
            "requirements": self._requirements(requirements),
            "reason": text(reason),
        }
        cached = self._begin("revise", goal_id, command_id, revision, epoch, data)
        if cached:
            return cached
        self._append("requirements_revised", goal_id, command_id, data)
        return self._finish(goal_id, command_id, "revised")

    def control(
        self,
        goal_id: str,
        action: str,
        *,
        command_id: str,
        revision: int,
        epoch: int,
        reason: str,
        limit: int | None = None,
    ) -> CommandReceipt:
        states = {
            "pause": "paused",
            "resume": "active",
            "abandon": "abandoned",
            "fail": "failed",
        }
        if action not in states:
            raise GoalError("unknown Goal control")
        data: dict[str, object] = {"status": states[action], "reason": text(reason)}
        if limit is not None:
            data["limit"] = positive(limit)
        cached = self._cached(action, goal_id, command_id, revision, epoch, data)
        if cached:
            return cached
        self._mutable()  # No Work/policy borrowing after fence, even for resume.
        if action == "resume":
            facts = self.facts()
            if facts.unresolved or facts.busy:
                raise GoalError(
                    "execution_unresolved" if facts.unresolved else "work_running"
                )
            goal = self.query(goal_id)
            if sum(b.goal_id == goal_id for b in self._history.batches) >= (
                limit or goal.limit
            ):
                raise GoalError("batch_limit")
            basis = self._basis(goal_id)
            confirmation = self._next.confirm_resume(basis, facts)
            if confirmation is not True:
                raise GoalError(
                    confirmation.reason
                    if isinstance(confirmation, PolicyStop)
                    else "resume_not_ready"
                )
            if (
                self.fenced
                or self.query(goal_id) != basis.goal
                or self._history.sequence != basis.sequence
            ):
                raise GoalError("resume basis changed during confirmation")
        cached = self._begin(action, goal_id, command_id, revision, epoch, data)
        if cached:
            return cached
        self._append("control_changed", goal_id, command_id, data)
        return self._finish(goal_id, command_id, action)

    def replace(
        self,
        goal_id: str,
        new_goal_id: str,
        requirements: Sequence[Requirement],
        *,
        command_id: str,
        revision: int,
        epoch: int,
        reason: str,
        limit: int,
        metadata: Mapping[str, object] | None = None,
    ) -> CommandReceipt:
        data = {
            "new_goal_id": text(new_goal_id),
            "requirements": self._requirements(requirements),
            "reason": text(reason),
            "limit": positive(limit),
            "metadata": dict(metadata or {}),
        }
        cached = self._begin("replace", goal_id, command_id, revision, epoch, data)
        if cached:
            return cached
        self._append("replaced", goal_id, command_id, data)
        return self._finish(goal_id, command_id, "replaced")

    async def advance(
        self, goal_id: str, *, command_id: str, revision: int, epoch: int
    ) -> CommandReceipt:
        cached = self._cached("advance", goal_id, command_id, revision, epoch, {})
        if cached:
            return cached
        self._mutable()
        if self._advancing:
            raise GoalError("Goal operation in progress")
        goal = self.query(goal_id)
        if goal.status != "active":
            raise GoalError("Goal is not active")
        facts = self.facts()
        if facts.unresolved or facts.busy:
            raise GoalError(
                "execution_unresolved" if facts.unresolved else "work_running"
            )
        self._begin("advance", goal_id, command_id, revision, epoch, {})
        task = asyncio.current_task()
        assert task is not None
        self._inflight.add(task)
        self._advancing = True
        try:
            basis = self._basis(goal_id)
            assessment = await self._acceptance.assess(basis, facts)
            if not self._current(basis):
                return self._finish(goal_id, command_id, "stale")
            result = self._complete(assessment, goal_id, command_id)
            if result:
                return result
            if assessment.status == "needs_user":
                return self._pause(goal_id, command_id, assessment.reason)
            if sum(b.goal_id == goal_id for b in self._history.batches) >= goal.limit:
                return self._pause(goal_id, command_id, "batch_limit")
            candidate = await self._next.prepare(basis, self.facts())
            if not self._current(basis):
                return self._finish(goal_id, command_id, "stale")
            if isinstance(candidate, PolicyStop):
                return self._pause(goal_id, command_id, candidate.reason)
            self._candidate(candidate, basis)
            if not self._next.confirm_candidate(candidate) or not self._current(basis):
                return self._pause(goal_id, command_id, "candidate_outdated")
            bid = f"batch-{uuid4().hex}"
            op = candidate.operation
            self._append(
                "batch_intent",
                goal_id,
                command_id,
                {
                    "batch_id": bid,
                    "operation_id": op.operation_id,
                    "basis": basis.identity,
                    "source": candidate.source,
                },
            )
            # Immutable basis_N -> exact own intent_N+1, never retag a proposal.
            receipt = self._history.batches[-1]
            if (
                receipt.command_id != command_id
                or receipt.intent_sequence != basis.sequence + 1
                or self._history.sequence != receipt.intent_sequence
                or not self._same_goal(basis)
                or not self._next.confirm_candidate(candidate)
            ):
                self._append(
                    "batch_not_submitted",
                    goal_id,
                    command_id,
                    {"batch_id": bid, "operation_id": op.operation_id},
                )
                return self._finish(goal_id, command_id, "not_submitted")
            # Original local accept has no suspension before admission. From this
            # point even an exception cannot be turned into a not-called proof.
            try:
                dispatch_op = WorkOperation(
                    op.operation_id,
                    op.kind,
                    op.session_id,
                    op.domain,
                    cast(Mapping[str, object], plain(op.payload)),
                    cast(Mapping[str, object], plain(op.source)),
                )
                original_spec = candidate.spec
                dispatch_spec = WorkRunSpec(
                    run_id=original_spec.run_id,
                    method_id=original_spec.method_id,
                    plan_id=original_spec.plan_id,
                    step_id=original_spec.step_id,
                    run_event_payload=cast(
                        Mapping[str, object], plain(original_spec.run_event_payload)
                    ),
                    scope_event_payload=cast(
                        Mapping[str, object], plain(original_spec.scope_event_payload)
                    ),
                    steps=tuple(
                        WorkStepSpec(
                            s.step_id, cast(Mapping[str, object], plain(s.payload))
                        )
                        for s in original_spec.steps
                    ),
                )
                run = await self._work.accept(dispatch_op, spec=dispatch_spec)
                self._append(
                    "batch_associated",
                    goal_id,
                    command_id,
                    {
                        "batch_id": bid,
                        "operation_id": op.operation_id,
                        "run_id": run.run_id,
                    },
                )
                try:
                    await self._work.wait(run.run_id)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # Retain original failure and evidence, not a fake success.
                    self.last_error = error
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.last_error = error
                if self._fenced:
                    raise
                return self._pause(
                    goal_id, command_id, "acceptance_or_execution_unknown"
                )
            if self._fenced:
                raise GoalError("controller fenced")
            if not self._same_goal(basis):
                return self._finish(
                    goal_id, command_id, "stale", {"operation_id": op.operation_id}
                )
            facts = self.facts()
            if facts.unresolved:
                return self._pause(goal_id, command_id, "execution_unresolved")
            current = self._basis(goal_id)
            assessment = await self._acceptance.assess(current, facts)
            if not self._current(current):
                return self._finish(
                    goal_id, command_id, "stale", {"operation_id": op.operation_id}
                )
            result = self._complete(assessment, goal_id, command_id)
            if result:
                return result
            if assessment.status == "needs_user":
                return self._pause(goal_id, command_id, assessment.reason)
            return self._finish(
                goal_id, command_id, "work_finished", {"operation_id": op.operation_id}
            )
        finally:
            self._inflight.discard(task)
            self._advancing = False

    async def request_cancel(self, goal_id: str) -> tuple[object, ...]:
        """Original cancellation remains available when append fenced, until close."""
        if self._retired or self._quiescing:
            raise GoalError("Goal controller closing or retired")
        task = asyncio.current_task()
        assert task is not None
        self._inflight.add(task)
        try:
            self.query(goal_id)
            results = []
            for batch in self._history.batches:
                if batch.goal_id != goal_id or batch.not_submitted:
                    continue
                run = self._work.get_run_for_operation(batch.operation_id)
                if run is not None and run.status in {
                    "accepted",
                    "running",
                    "cancelling",
                }:
                    await self._work.cancel(run.run_id)
                    results.append(self._work.get_cancellation(run.run_id))
            return tuple(results)
        finally:
            self._inflight.discard(task)

    def fence(self) -> None:
        self._fenced = True

    def begin_close(self) -> None:
        self.fence()
        self._quiescing = True

    async def quiesce(self) -> None:
        self.begin_close()
        if self._quiescence_error is not None:
            raise self._quiescence_error
        current = asyncio.current_task()
        tasks = tuple(t for t in self._inflight if t is not current)
        for task in tasks:
            task.cancel()
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    self._quiescence_error = result
                    raise result

    async def settle_work(self) -> None:
        """Borrow original cancellation, never dispose an entire shared runtime."""
        if self._retired:
            raise GoalError("Goal controller retired")
        for run in self._work.active_runs(session_id=self.header.session_id):
            if any(b.operation_id == run.operation_id for b in self._history.batches):
                await self._work.cancel(run.run_id)

    def retire(self) -> None:
        if self._retired:
            return
        if self._quiescence_error is not None:
            raise self._quiescence_error
        if self._inflight or self._work.active_runs(session_id=self.header.session_id):
            raise GoalError("borrowed capabilities still active")
        self._retired = self._fenced = True

    def _reload(self) -> None:
        try:
            header, records = self._store.load()
            if header != self.header:
                raise GoalError("Goal store identity or policy changed")
            self._history = replay(header, records)
        except BaseException:
            self.fence()
            raise

    def _append(
        self, kind: str, gid: str, cid: str, data: Mapping[str, object]
    ) -> None:
        self._mutable()
        record = GoalRecord(
            self._history.sequence + 1, self.header.scope_id, gid, kind, cid, data
        )
        proposed = replay(self.header, (*self._history.records, record))
        try:
            ack = self._store.append(self._history.sequence, record)
            if type(ack) is not int or ack != record.sequence:
                raise GoalError("Goal append acknowledgement mismatch")
        except BaseException:
            self.fence()
            raise
        self._history = proposed

    def _cached(
        self,
        action: str,
        gid: str,
        cid: str,
        rev: int,
        epoch: int,
        data: Mapping[str, object],
    ) -> CommandReceipt | None:
        text(cid)
        request = self._request(action, gid, rev, epoch, data)
        old = self._history.commands.get(cid)
        if old is not None and old.request != request:
            raise GoalError("command id reused with different content")
        return old

    def _begin(
        self,
        action: str,
        gid: str,
        cid: str,
        rev: int,
        epoch: int,
        data: Mapping[str, object],
    ) -> CommandReceipt | None:
        old = self._cached(action, gid, cid, rev, epoch, data)
        if old:
            return old
        self._mutable()
        if action == "create":
            if gid in self._history.goals or any(
                g.status not in TERMINAL for g in self._history.goals.values()
            ):
                raise GoalError("Goal exists or scope already active")
        else:
            g = self.query(gid)
            if (
                type(rev) is not int
                or type(epoch) is not int
                or (rev, epoch) != (g.revision, g.epoch)
            ):
                raise GoalError("stale Goal command")
        # Validate a synchronous primary effect before admitting its command.
        # The same Records reducer owns both this check and eventual replay.
        effect = {
            "create": "created",
            "revise": "requirements_revised",
            "replace": "replaced",
            "pause": "control_changed",
            "resume": "control_changed",
            "abandon": "control_changed",
            "fail": "control_changed",
        }.get(action)
        if effect is not None:
            seq = self._history.sequence
            admission = GoalRecord(
                seq + 1,
                self.header.scope_id,
                gid,
                "command_received",
                cid,
                {"request": self._request(action, gid, rev, epoch, data)},
            )
            replay(
                self.header,
                (
                    *self._history.records,
                    admission,
                    GoalRecord(seq + 2, self.header.scope_id, gid, effect, cid, data),
                ),
            )
        self._append(
            "command_received",
            gid,
            cid,
            {"request": self._request(action, gid, rev, epoch, data)},
        )
        return None

    @staticmethod
    def _request(
        action: str, gid: str, rev: int, epoch: int, data: Mapping[str, object]
    ) -> str:
        return canonical(
            {
                "action": text(action),
                "goal_id": text(gid),
                "revision": rev,
                "epoch": epoch,
                "data": data,
            }
        )

    def _finish(
        self,
        gid: str,
        cid: str,
        outcome: str,
        details: Mapping[str, object] | None = None,
    ) -> CommandReceipt:
        self._append(
            "command_finished",
            gid,
            cid,
            {"outcome": outcome, "details": dict(details or {})},
        )
        return self._history.commands[cid]

    def _pause(self, gid: str, cid: str, reason: str) -> CommandReceipt:
        if self.query(gid).status == "active":
            self._append(
                "control_changed", gid, cid, {"status": "paused", "reason": reason}
            )
        return self._finish(gid, cid, "paused", {"reason": reason})

    def _basis(self, gid: str) -> GoalBasis:
        return GoalBasis(self.header, self.query(gid), self._history.sequence)

    def _current(self, basis: GoalBasis) -> bool:
        return (
            not self.fenced
            and self._same_goal(basis)
            and self._history.sequence == basis.sequence
        )

    def _same_goal(self, basis: GoalBasis) -> bool:
        return (
            not self.fenced
            and self.query(basis.goal.id) == basis.goal
            and self.query(basis.goal.id).status == "active"
        )

    def _candidate(self, candidate: WorkCandidate, basis: GoalBasis) -> None:
        if (
            candidate.basis != basis
            or candidate.operation.session_id != self.header.session_id
        ):
            raise GoalError("candidate basis or Session mismatch")
        if (
            self._work.get_run_for_operation(candidate.operation.operation_id)
            is not None
        ):
            raise GoalError("candidate operation already exists")
        facts = self.facts()
        if facts.busy or facts.unresolved:
            raise GoalError("original Work not idle/known")

    def _complete(
        self, assessment: GoalAssessment, gid: str, cid: str
    ) -> CommandReceipt | None:
        if assessment.basis != self._basis(gid):
            raise GoalError("assessment basis mismatch")
        if assessment.status not in {
            "satisfied",
            "unmet",
            "more_evidence",
            "needs_user",
        }:
            raise GoalError("unknown assessment status")
        if assessment.status != "satisfied":
            return None
        if (
            not assessment.proof
            or not assessment.operations
            or set(assessment.coverage)
            != {r.id for r in assessment.basis.goal.requirements}
        ):
            raise GoalError("incomplete acceptance proof")
        facts = self.facts()
        if facts.busy or facts.unresolved:
            raise GoalError("execution not settled")
        for op in assessment.operations:
            if not any(
                b.operation_id == op
                and b.goal_id == gid
                and b.revision == assessment.basis.goal.revision
                and b.epoch == assessment.basis.goal.epoch
                and b.run_receipt is not None
                and not b.not_submitted
                for b in facts.batches
            ):
                raise GoalError("success dependency belongs to an old Goal basis")
        for op in assessment.operations:
            if not any(
                r.operation_id == op and r.status == "completed" for r in facts.runs
            ):
                raise GoalError("success dependency not completed in original Work")
        if not self._acceptance.confirm_current(assessment) or not self._current(
            assessment.basis
        ):
            return self._pause(gid, cid, "acceptance_outdated")
        self._append(
            "acceptance_decided",
            gid,
            cid,
            {
                "basis": assessment.basis.identity,
                "coverage": assessment.coverage,
                "operations": assessment.operations,
                "proof": assessment.proof,
            },
        )
        return self._finish(gid, cid, "completed")

    def _mutable(self) -> None:
        if self.fenced:
            raise GoalError("Goal controller fenced or retired")

    @staticmethod
    def _requirements(values: Sequence[Requirement]) -> object:
        return plain(tuple({"id": r.id, "text": r.text} for r in values))
