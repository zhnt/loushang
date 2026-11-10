"""Original planning-reply handoff over the canonical Session/Work boundaries.

Domain parsers and evidence encoding are injected. This integration delegates
execution and cancellation and owns only its original temporary subscription.
"""
from __future__ import annotations

from loushang.harness.session.response_proof import ResponseBoundary


class PlanningWork:
    def __init__(
        self, delegate, *, session, read_transcript, model_failed, prompt, input_ref,
        known_evidence, parser, capture_response, write_response, publish_report,
        rejection_error,
    ):
        self.delegate, self.session = delegate, session
        self._read_transcript, self._model_failed = read_transcript, model_failed
        self.prompt, self.input_ref = prompt, input_ref
        self.known_evidence, self.parser = tuple(known_evidence), parser
        self._capture_response = capture_response
        self._write_response, self._publish_report = write_response, publish_report
        self.rejection_error = rejection_error

    async def execute(self, operation, context):
        manager = self._read_transcript()
        boundary = ResponseBoundary.capture(manager)
        events = []

        async def listen(event):
            if event.kind == "agent.message_end":
                events.append(event)

        unsubscribe = self.session.subscribe_runtime_events(listen)
        try:
            await self.delegate.execute(operation, context)
            await self.session.wait_for_idle()
        finally:
            unsubscribe()
        report: dict[str, object] = {
            "version": 1,
            "operation_id": operation.operation_id,
            "run_id": context.run_id,
            "session_id": operation.session_id,
            "input_ref": self.input_ref,
        }
        try:
            if self._model_failed():
                raise self.rejection_error("planning model allowance failed")
            raw, proof = self._capture_response(
                manager,
                boundary,
                session_id=operation.session_id,
                prompt=self.prompt,
                events=events,
            )
            report["response_ref"] = self._write_response(operation, raw)
            report["response_proof"] = proof
            proposal = self.parser(raw, known_evidence=self.known_evidence)
            report["proposal"] = proposal.data()
            report["rejection"] = None
        except self.rejection_error as error:
            report["proposal"] = None
            report["rejection"] = str(error)
        self._publish_report(context, report, operation.session_id)

    async def cancel_and_wait(self, operation, context):
        return await self.delegate.cancel_and_wait(operation, context)


class _ScopedSessionWork:
    """Retain an admitted model Work configuration until its Session is idle."""

    _scoped_phase: str
    _step_tools: dict[str, tuple[str, ...]]
    _error_type: type[Exception]
    _binding_error: str
    _unsupported_step: str
    _failed_allowance: str

    def __init__(
        self,
        delegate,
        *,
        session,
        allowance,
        policy,
        phase,
        execution=None,
        step_aliases=None,
    ):
        self.delegate, self.session, self.allowance = delegate, session, allowance
        self.policy, self.phase = policy, phase
        self.step_aliases = dict(step_aliases or {})
        self.execution = execution

    async def execute(self, operation, context):
        if self.execution is None:
            raise self._error_type(self._binding_error)
        reservation = self.execution()
        if reservation is None:
            raise self._error_type(self._binding_error)
        self.allowance.enter(operation.operation_id, self.phase)
        step = context.step_id if self.phase == self._scoped_phase else None
        step = self.step_aliases.get(step, step)
        self.policy.step = step
        tools = next(
            (names for name, names in self._step_tools.items() if step == name), ()
        )
        try:
            if self.phase == self._scoped_phase and step not in self._step_tools:
                raise self._error_type(self._unsupported_step)
            self.session.configure_execution(
                reservation,
                stream_fn=self.allowance.stream,
                tool_names=tuple(tools),
                additional_policy=self.policy,
            )
            result = await self.delegate.execute(operation, context)
            if self.phase == self._scoped_phase and self.allowance.failed:
                raise self._error_type(self._failed_allowance)
            return result
        finally:
            # Do not end the phase while an original Session invocation is live.
            try:
                await self.session.wait_for_idle()
                self.policy.step = None
                self.session.runtime.execution_configuration.release_execution(
                    reservation
                )
            except BaseException:
                self.allowance.fenced = True
                raise
            finally:
                self.policy.step = None
                self.allowance.leave(operation.operation_id)

    async def cancel_and_wait(self, operation, context):
        return await self.delegate.cancel_and_wait(operation, context)
