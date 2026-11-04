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
