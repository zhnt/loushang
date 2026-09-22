"""Failure-edge and post-return owner facts, never performance evidence."""

import time
from contextlib import ExitStack, contextmanager
from unittest.mock import patch


def _error(value):
    if value is None:
        return None
    name = type(value).__name__
    allowed = {"ManagedChildError", "ManagedStorageError", "AppServiceError", "TimeoutError",
               "CancelledError", "ValueError", "TypeError", "OSError", "RuntimeError",
               "AssertionError", "KeyboardInterrupt", "FileNotFoundError", "PermissionError"}
    code = getattr(value, "code", None)
    return {"type": name if name in allowed else "OtherError",
            "code": code if type(code) is str and code in {
                "startup_failed", "activation_failed", "cleanup_incomplete", "busy",
                "unavailable", "closed", "conflict", "invalid_record"} else "other"}


def _task(task):
    if task is None:
        return {"state": "absent"}
    if not task.done():
        return {"state": "pending"}
    if task.cancelled():
        return {"state": "cancelled"}
    return {"state": "done", "error": _error(task.exception())}


@contextmanager
def observe_startup(bootstrap_type, emit):
    """Borrow original owners; record drive failure and eventual entry return.

    Diagnostic errors cannot alter application results. No task is awaited,
    cancelled, retried, or created here; no IO occurs inside bind's mutex.
    Failure observation awaits the original drive exactly once, before cleanup.
    """
    original = bootstrap_type.bind
    retained = [None, None]
    patches = ExitStack()

    def snapshot(phase, child, application, failure):
        try:
            deadline = child._startup_deadline
            emit(phase, committed=child._committed,
                 failure=_error(failure), prepare=_task(child._prepare_task),
                 activate=_task(child._activate_task), start=_task(application._start_task),
                 deadline_elapsed=(time.monotonic() >= deadline
                                   if type(deadline) in (int, float) else None))
        except BaseException:
            pass  # Diagnostics never replace the original outcome.

    def bind(bootstrap, application, *args, **kwargs):
        child = original(bootstrap, application, *args, **kwargs)
        retained[0], retained[1] = child, application
        child_type = type(child)
        drive = getattr(child_type, "_drive", None)
        if drive is not None:
            async def observed_drive(instance):
                try:
                    return await drive(instance)
                except BaseException as error:
                    if instance is child:
                        snapshot("startup_drive_failed", child, application, error)
                    raise

            patches.enter_context(patch.object(child_type, "_drive", observed_drive))
        return child

    try:
        with patches, patch.object(bootstrap_type, "bind", bind):
            yield
    finally:
        child, application = retained
        if child is not None:
            snapshot("startup_post_return", child, application, child._failure)
