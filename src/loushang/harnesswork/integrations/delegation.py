"""Work-to-child-round coordination over the existing Session owners.

The original MultiAgent runtime owns child identities, rounds and cleanup;
this integration retains only their admitted Work association and tasks.
Products supply value policies and the existing child factory.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace

from loushang.harness.artifacts import SessionBlobRef
from loushang.harness.multiagent import HostCaller, MultiAgentError
from loushang.harness.session.model_selection import model_identity_data
from loushang.harness.session.multiagent import build_agent_context_plan
from loushang.harnesswork import WorkCancellationOutcome
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import canonical, plain


class SessionGoalDelegation:
    """Associate the original family with one admitted delegated Work at a time.

    The Product binds the actual control/runtime and child factory after this
    state initialization. Private policy attributes declare choice/view/Work
    types, ref and message value codecs, tool/phase/worker vocabulary, operation
    and blob labels. _binding, _context_material, _freeze, _report and
    _evidence_fact are pure value policies. _context_prompt reads the Product
    prompt; _work_type retains its real compatibility class. These hooks do not
    own Task, Transcript, Blob or round operations; those stay in this bridge
    and the original owners it calls.
    """

    def __init__(
        self, *, session, work, allowance, blobs, reader, source_identity, selection
    ):
        self.session, self.work, self.allowance = session, work, allowance
        self.blobs, self.reader, self.source_identity = blobs, reader, source_identity
        self.selection = selection
        self.revision = 0
        self.gate = asyncio.Lock()
        self.children = {}
        self.last_ref = None
        self.active = None
        self.closing = False
        self.fenced = False
        self.cleanup_pending = set()
        self.model = self.model_data(session)

    @staticmethod
    def model_data(session):
        return asdict(model_identity_data(session.agent.model))

    def _available(self):
        if self.closing or self.fenced or self.cleanup_pending or self.allowance.fenced:
            raise GoalError("delegated Session family unavailable")
        if self.model_data(self.session) != self.model:
            raise GoalError("parent model changed")

    def _reusable(self, ref, expected=None):
        child = self.children.get(ref)
        record = self.control.registry.get(ref)
        if child is None or child.session is None or record is None:
            raise GoalError("reuse target unavailable")
        run = (
            self.work.get_run_for_operation(child.last_operation)
            if child.last_operation
            else None
        )
        if (
            record.status != "completed"
            or record.round_id != child.last_round
            or child.session.pending_message_count
            or child.session.is_streaming
            or run is None
            or run.status != "completed"
            or self.model_data(child.session) != self.model
            or (expected is not None and expected != self._binding(child))
        ):
            raise GoalError("reuse target not idle with a confirmed handoff")
        return child

    def views(self):
        return tuple(
            self._view_type(
                ref,
                child.session.session_id if child.session else "",
                record.status,
                record.round_id,
                child.origin,
            )
            for ref, child in self.children.items()
            if (record := self.control.registry.get(ref)) is not None
        )

    def select(self, choice):
        self._available()
        if self.active is not None or self.gate.locked():
            raise GoalError("delegated execution busy")
        if choice is not None and not isinstance(choice, self._choice_type):
            raise GoalError("invalid Session choice")
        self.selection = choice
        self.revision += 1

    def prepare(self, basis, operation, spec, turn):
        self._available()
        if self.active is not None:
            raise GoalError("delegated execution busy")
        choice = self.selection
        if choice is None:
            choice = (
                self._choice_type("reuse", target=self.last_ref)
                if self.last_ref
                else self._choice_type("fresh")
            )
        child = self._reusable(choice.target) if choice.mode == "reuse" else None
        if choice.mode != "reuse":
            self._check_creation()
        plan, history = self._build_context(choice)
        frozen = self._freeze(basis, operation, spec, turn, choice, history, child)
        # Operation and Goal intent retain independent immutable snapshots.
        operation = replace(
            operation,
            kind=self._operation_kind,
            payload={**operation.payload, self._payload_key: plain(frozen)},
        )
        return (
            operation,
            self._work_type(self, choice, plan, plain(frozen), turn.text),
            frozen,
        )

    def _check_creation(self):
        self.control.check_spawn(
            caller=HostCaller(),
            parent_path=self.control.root_ref.path,
            agent_type=self._worker_type,
        )

    def confirm(self, value):
        try:
            self._available()
            if self.active is not None or value["selection_revision"] != self.revision:
                return False
            if value["mode"] == "reuse":
                child = next(
                    c
                    for c in self.children.values()
                    if self._ref_data(c.ref) == value["reuse"]["ref"]
                )
                self._reusable(child.ref, value["reuse"])
            else:
                self._check_creation()
            return True
        except (ValueError, KeyError, StopIteration, MultiAgentError):
            return False

    async def release(self, ref):
        async with self.gate:
            if self.active is not None or self.closing:
                raise GoalError("delegated execution busy")
            record = self.control.registry.get(ref)
            if ref not in self.children:
                raise GoalError("unknown exact child identity")
            if record is None:
                # The original shielded close may have finished after its caller
                # was cancelled. Registry retirement is the authority for that.
                self.cleanup_pending.discard(ref)
                if self.last_ref == ref:
                    self.last_ref = None
                return
            if record.status == "running":
                raise GoalError("cannot release an active child")
            self.cleanup_pending.add(ref)
            result = await self.runtime.close_agent(
                caller=HostCaller(), target=ref.path
            )
            if result.dispose_errors:
                self.cleanup_pending.add(ref)
                raise GoalError("child cleanup pending")
            self.cleanup_pending.discard(ref)
            if self.last_ref == ref:
                self.last_ref = None

    async def close(self):
        self.closing = True
        await self.runtime.dispose()

    def _build_context(self, choice, watermark=None):
        plan, watermark = build_agent_context_plan(
            session=self.session,
            blobs=self.blobs,
            choice=choice,
            watermark=watermark,
            system_prompt=self._context_prompt,
            allowed_tools=self._tools,
            error_type=GoalError,
            detach_message=self._detach_message,
        )
        return plan, self._context_material(choice, plan, watermark)

    def _publish_report(self, context, report, session_id):
        ref = self.blobs.put_bytes(
            canonical(report).encode(),
            logical_name=f"{self._blob_prefix}/{context.run_id}/{self._report_role}.json",
            kind=self._blob_kind,
            media_type=self._blob_media_type,
            source=self._blob_source,
        )
        self.blobs.read_bytes(ref)
        blob = SessionBlobRef.from_manifest_entry(ref.manifest_entry())
        context.publish(self._evidence_fact(blob, context, session_id))


class DelegatedSessionWork:
    def __init__(self, family, choice, plan, frozen, prompt):
        self.family, self.choice, self.plan = family, choice, plan
        self.frozen, self.prompt = frozen, prompt
        self.cancelled = False
        self.task = self.creation = None
        self.ref = None
        self.round = None

    async def execute(self, operation, context):
        async with self.family.gate:
            if self.cancelled:
                raise GoalError("delegated Work cancelled before dispatch")
            if self.task is not None:
                raise GoalError("duplicate delegated dispatch")
            self.task = asyncio.create_task(self._execute(operation, context))
        await asyncio.shield(self.task)

    async def _execute(self, operation, context):
        family = self.family
        allowance = family.allowance
        child = None
        entered = False
        try:
            async with family.gate:
                if self.cancelled or not family.confirm(self.frozen):
                    raise GoalError("delegated admission changed")
                if (
                    plain(operation.payload.get(family._payload_key)) != self.frozen
                    or context.step_id != family._phase
                ):
                    raise GoalError("delegated operation mismatch")
                family.active = self
                allowance.enter(operation.operation_id, family._phase)
                entered = True
            if self.choice.mode == "inherit":
                manager = family.session.session_manager
                watermark = self.frozen["history"]["watermark"]
                records = tuple(manager.get_branch(watermark))
                source = await family.reader.read([r.record_id for r in records])
                if (
                    source.store_identity != family.source_identity
                    or tuple(r.record for r in source.records) != records
                ):
                    raise GoalError("inherited source changed or unavailable")
                plan, material = family._build_context(self.choice, watermark)
                if material != self.frozen["history"]:
                    raise GoalError("inherited context changed")
                self.plan = plan
            async with family.gate:
                if self.cancelled:
                    raise GoalError("delegated Work cancelled before delivery")
                if self.choice.mode == "reuse":
                    child = family._reusable(self.choice.target, self.frozen["reuse"])
                    child.policy.step = family._phase
                    self.ref = child.ref
                    receipt = await family.runtime.send_message(
                        caller=HostCaller(),
                        target=self.ref.path,
                        text=self.prompt,
                    )
                    self.round = receipt.round_id
                    if (
                        not receipt.triggered_new_round
                        or receipt.recipient_ref != self.ref
                        or self.round != child.last_round + 1
                    ):
                        raise GoalError(
                            "child delivery did not start the admitted round"
                        )
                else:
                    self.creation = asyncio.create_task(
                        family.runtime.spawn_child(
                            caller=HostCaller(),
                            parent_path=family.control.root_ref.path,
                            name=operation.operation_id,
                            agent_type=family._worker_type,
                            initial_prompt=self.prompt,
                            context_plan=self.plan,
                        )
                    )
            if self.creation is not None:
                record = await asyncio.shield(self.creation)
                self.ref, self.round = record.ref, record.round_id
                child = family.children[self.ref]
                child.origin = operation.operation_id
            completion = await family.runtime.await_completion(
                caller=HostCaller(), target=self.ref.path
            )
            if (
                self.cancelled
                and completion.sender_ref == self.ref
                and completion.round_id == self.round
            ):
                # The domain cancellation port has stopped this exact child
                # round. Report interruption rather than a business failure;
                # identity mismatches and real cleanup errors remain failures.
                raise asyncio.CancelledError
            if (
                self.cancelled
                or completion.sender_ref != self.ref
                or completion.round_id != self.round
                or completion.terminal.status != "completed"
                or allowance.failed
            ):
                raise GoalError("child round did not complete successfully")
            report = family._report(
                operation, context, self.frozen, self.ref, self.round, child, completion
            )
            family._publish_report(context, report, operation.session_id)
            child.last_operation, child.last_round = operation.operation_id, self.round
            family.last_ref = self.ref
        except BaseException:
            # Settle the real round before releasing permissions/allowance. The
            # shared creation owner retains partially created resources on error.
            if self.ref is not None:
                try:
                    await family.runtime.interrupt_agent(
                        caller=HostCaller(), target=self.ref.path
                    )
                except BaseException:
                    family.fenced = allowance.fenced = True
            elif self.creation is not None and not self.creation.cancelled():
                error = self.creation.exception() if self.creation.done() else None
                if getattr(error, "owner", None) is not None:
                    family.cleanup_pending.add(error.ref)
            raise
        finally:
            if child is not None:
                try:
                    await child.session.wait_for_idle()
                except BaseException:
                    family.fenced = allowance.fenced = True
                    raise
                child.policy.step = None
            if entered:
                allowance.leave(operation.operation_id)
            if family.active is self:
                family.active = None

    async def cancel_and_wait(self, operation, context):
        family = self.family
        try:
            async with family.gate:
                self.cancelled = True
                creation = self.creation
                if creation is not None and not creation.done():
                    creation.cancel()
            if creation is not None:
                try:
                    record = await asyncio.shield(creation)
                    self.ref, self.round = record.ref, record.round_id
                except asyncio.CancelledError:
                    if not creation.done():
                        raise
                except BaseException as error:
                    if getattr(error, "owner", None) is not None:
                        raise
            if self.ref is not None:
                await family.runtime.interrupt_agent(
                    caller=HostCaller(), target=self.ref.path
                )
            if self.task is not None:
                try:
                    await asyncio.shield(self.task)
                except (GoalError, asyncio.CancelledError):
                    if not self.task.done():
                        raise
            if family.fenced or family.allowance.fenced:
                raise GoalError("delegated cancellation cleanup unresolved")
            return WorkCancellationOutcome.settled()
        except BaseException as error:
            family.fenced = True
            return WorkCancellationOutcome.failed(str(error))
