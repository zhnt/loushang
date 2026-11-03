"""Diagnostic-only binding observation; never use for performance samples."""

from __future__ import annotations

from dataclasses import replace


class AdmissionTrace:
    """Fail closed for observation, without changing the observed operation."""

    def __init__(self, emit):
        self.emit = emit
        self.disabled = False

    def record(self, action, outcome, error=None):
        if self.disabled:
            return
        try:
            details = {}
            if error is not None:
                name = type(error).__name__
                details["error_type"] = name if name in {
                    "ManagedStorageError", "AppServiceError", "TimeoutError",
                    "CancelledError", "ValueError", "TypeError", "OSError",
                    "RuntimeError", "AssertionError", "KeyboardInterrupt",
                } else "OtherError"
                code = getattr(error, "code", None)
                details["error_code"] = code if type(code) is str and code in {
                    "busy", "unavailable", "closed", "conflict", "invalid_record",
                } else "other"
            self.emit("admission_" + action + "_" + outcome, **details)
        except BaseException:
            # This is the diagnostic sink, not the delegated operation. Even
            # cancellation/interrupt here must not strand an acquired owner or
            # replace the operation's original exception. Missing stages mean
            # incomplete diagnostic evidence, never a successful observation.
            self.disabled = True


class _Admission:
    def __init__(self, trace):
        self.trace = trace
        self.owner = None

    async def acquire(self):
        self.trace.record("acquire", "enter")
        try:
            result = await self.owner.acquire()
        except BaseException as error:
            self.trace.record("acquire", "fail", error)
            raise
        self.trace.record("acquire", "return")
        return result

    def check_creation(self, previous):
        self.trace.record("check", "enter")
        try:
            result = self.owner.check_creation(previous)
        except BaseException as error:
            self.trace.record("check", "fail", error)
            raise
        self.trace.record("check", "return")
        return result

    async def close(self):
        self.trace.record("close", "enter")
        try:
            result = await self.owner.close()
        except BaseException as error:
            self.trace.record("close", "fail", error)
            raise
        self.trace.record("close", "return")
        return result


def observe_binding(binding, trace):
    def prepare(request):
        proxy = _Admission(trace)  # Allocate before receiving the original owner.
        trace.record("prepare", "enter")
        try:
            proxy.owner = binding.prepare(request)
        except BaseException as error:
            trace.record("prepare", "fail", error)
            raise
        trace.record("prepare", "return")
        return proxy

    return replace(binding, prepare=prepare)
