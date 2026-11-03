"""Operation-scoped logical call limits at the existing model stream seam.

No scheduler, execution owner, usage ledger, or domain phase vocabulary.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from loushang.agent.model_transport import (
    is_prepared_request_conformant,
    prepared_request_conformant,
)
from loushang.ai.options import CallOptions, RetryOptions


class CallAllowanceError(RuntimeError):
    pass


class ModelCallAllowance:
    def __init__(self, *, phase_limits: Mapping[str, int], provider_attempts: int,
                 delegate: Callable, total_limit: int | None = None,
                 max_output_tokens: int | None = None, retry_attempts: int | None = None,
                 error_type: type[Exception] = CallAllowanceError) -> None:
        for value in (total_limit, max_output_tokens):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("positive model allowance required")
        if not phase_limits or any(not isinstance(k, str) or not k or type(v) is not int or v <= 0
                                   for k, v in phase_limits.items()):
            raise ValueError("positive phase allowances required")
        if type(provider_attempts) is not int or provider_attempts <= 0:
            raise ValueError("positive provider attempt allowance required")
        if retry_attempts is not None and (type(retry_attempts) is not int or not 0 < retry_attempts <= provider_attempts):
            raise ValueError("retry attempts must fit the provider allowance")
        self._retry_attempts = retry_attempts
        self._phase_limits = dict(phase_limits)
        self._provider_attempts = provider_attempts
        self._stream_delegate = delegate
        self._error_type = error_type
        self.total_limit, self.max_output_tokens = total_limit, max_output_tokens
        self.total_calls = 0
        self.operation_id: str | None = None
        self.phase: str | None = None
        self.calls = 0
        self.failed = False
        self.fenced = False
        self._checkpoint: Callable[[], None] | None = None
        self.stream = self._delegate()
        # A limiter cannot grant a caller-supplied transport a new trust claim.
        # Pass through only a declaration made at the actual transport boundary.
        if is_prepared_request_conformant(delegate):
            prepared_request_conformant(self.stream)

    def _error(self, message: str) -> Exception:
        return self._error_type(message)

    def enter(self, operation_id: str, phase: str) -> None:
        if (
            not operation_id
            or self.fenced
            or self.phase is not None
            or phase not in self._phase_limits
        ):
            raise self._error("model phase unavailable")
        if operation_id != self.operation_id:
            self.operation_id, self.calls, self.failed = operation_id, 0, False
        elif self.failed:
            raise self._error("model operation allowance already failed")
        self.phase = phase

    def leave(self, operation_id: str) -> None:
        if self.operation_id != operation_id:
            self.fenced = True
            raise self._error("model phase ownership mismatch")
        self.phase = None
        # Preserve calls/failed across steps and cancellation settlement.

    def _delegate(self):
        async def bounded_stream(model, context, options=None):
            if self._checkpoint is not None:
                self._checkpoint()
            if self.fenced or self.phase is None or self.failed:
                self.failed = True
                raise self._error("model call outside an admitted phase")
            if self.total_limit is not None and self.total_calls >= self.total_limit:
                self.failed = self.fenced = True
                raise self._error("owner model-call allowance exhausted")
            maximum = self._phase_limits[self.phase]
            if self.calls >= maximum:
                self.failed = True
                raise self._error("model logical-call allowance exhausted")
            if options is not None and not isinstance(options, CallOptions):
                self.failed = True
                raise self._error("unrecognized model call options")
            if self.max_output_tokens is not None or self._retry_attempts is not None:
                options = options or CallOptions()
                changes = {}
                if self.max_output_tokens is not None:
                    output = options.max_output_tokens
                    changes["max_output_tokens"] = min(output, self.max_output_tokens) if output is not None else self.max_output_tokens
                if self._retry_attempts is not None:
                    changes["retry"] = RetryOptions(max_attempts=self._retry_attempts)
                options = replace(options, **changes)
            retry = options.retry if options is not None else None
            if retry is not None and (
                not isinstance(retry, RetryOptions)
                or retry.max_attempts > self._provider_attempts
            ):
                self.failed = True
                raise self._error("provider retry allowance unsupported")
            # No suspension occurs before consuming the allowance. Pass through
            # the exact prepared committer, cancellation authority and response.
            self.calls += 1
            self.total_calls += 1
            try:
                return await self._stream_delegate(model, context, options)
            except BaseException:
                self.failed = True
                raise

        return bounded_stream
