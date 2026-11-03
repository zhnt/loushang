"""Dedicated Coding child entry for the managed Linux deployment.

The parent supplies a durable invocation and one inherited control descriptor.
This module does not initialize directories, discover services or infer stop
facts. Before application binding, failure exits nonzero without a clean-stop
claim; after binding, the existing child process owner controls all settlement.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import monotonic, sleep

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.bootstrap import ManagedChildBootstrapV1
from loushang.apphost.managed.contracts import ManagedContractError, _path
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.apphost.managed.paths import resolve_managed_paths
from loushang.hosting.contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)

APPLICATION_ID = "coding.default"
ENDPOINT = "workspace"


def coding_managed_process_request(
    invocation: ManagedChildInvocationV1, descriptor: int, *, executable: str,
    environment: Mapping[str, str], session_root: Path | None = None,
) -> ProcessLaunchRequest:
    """Pure launch material for the installed module, with frozen home/runtime."""
    if type(invocation) is not ManagedChildInvocationV1 or invocation.service.product_id != "coding":
        raise ManagedContractError()
    _descriptor(descriptor)
    _path(executable)
    selected = session_root if session_root is not None else Path(invocation.namespace.platform_home) / "data/sessions"
    if not isinstance(selected, Path):
        raise ManagedContractError()
    _path(str(selected))
    effective = dict(environment)
    effective["LOUSHANG_HOME"] = invocation.namespace.platform_home
    effective["LOUSHANG_RUNTIME_DIR"] = invocation.runtime_root
    effective["LOUSHANG_TMPDIR"] = _temporary(invocation)
    return ProcessLaunchRequest(
        (executable, "-m", "loushang.coding.managed_process", invocation.to_json(), str(selected), str(descriptor)),
        invocation.service.workspace, tuple(effective.items()),
        ProcessStreamSpec(ProcessStdinMode.CLOSED, ProcessStdoutMode.DISCARD, ProcessStderrMode.DISCARD),
    )


def _descriptor(value: int) -> None:
    if type(value) is not int or not 3 <= value < 2**31:
        raise ManagedContractError()


def _temporary(invocation: ManagedChildInvocationV1) -> str:
    return str(resolve_managed_paths(
        invocation.namespace, invocation.service, invocation.instance,
        runtime_root=invocation.runtime_root, temporary_override=invocation.temporary_override,
    ).temporary)


def _run(arguments: Sequence[str]) -> int:
    if len(arguments) != 3:
        raise ManagedContractError()
    invocation = ManagedChildInvocationV1.from_json(arguments[0])
    if invocation.service.product_id != "coding":
        raise ManagedContractError()
    _path(arguments[1])
    if not arguments[2].isascii() or not arguments[2].isdecimal() or len(arguments[2]) > 10:
        raise ManagedContractError()
    descriptor = int(arguments[2])
    _descriptor(descriptor)
    # Invocation identity wins over mutable inherited environment. Product
    # configuration is consumed only after this dedicated process is bound.
    os.environ["LOUSHANG_HOME"] = invocation.namespace.platform_home
    os.environ["LOUSHANG_RUNTIME_DIR"] = invocation.runtime_root
    os.environ["LOUSHANG_TMPDIR"] = _temporary(invocation)
    endpoint = socket.socket(fileno=descriptor)
    bootstrap: ManagedChildBootstrapV1 | None = None
    try:
        # The frontend imports this module only to construct launch material.
        # Load the backend in its actual child, with endpoint cleanup already
        # owned and before the native admission budget begins.
        from .managed_local import (
            CodingManagedLocalCommandV1,
            create_coding_managed_local_launch,
        )

        bootstrap = ManagedChildBootstrapV1(
            invocation.namespace, invocation.service, invocation.instance,
            invocation.attempt_id, endpoint, runtime_root=invocation.runtime_root,
            temporary_override=invocation.temporary_override,
            diagnostics=True,
        )
        deadline = monotonic() + 15
        while True:
            try:
                bootstrap.open(deadline=deadline)
                break
            except ManagedStorageError as error:
                if error.code != "busy" or monotonic() >= deadline:
                    raise
                sleep(0.01)  # Same admission and frozen budget, never a new owner.
        launch = create_coding_managed_local_launch(
            invocation, session_root=Path(arguments[1]), application_id=APPLICATION_ID,
            endpoint=ENDPOINT, session_discovery=True,
            store_state_root=Path(invocation.namespace.platform_home) / "state/session-stores",
            managed_mux=bootstrap.managed_mux_binding(application_id=APPLICATION_ID),
        )
        capture_factory = bootstrap.output_capture_factory(deadline=deadline)
        trace = None
        if invocation.trace_deadline_ms is not None:
            trace_deadline = invocation.trace_deadline_ms / 1000
            if monotonic() < trace_deadline:
                try:
                    trace = bootstrap.prepare_trace(deadline=trace_deadline)
                except ManagedStorageError as error:
                    if error.code != "busy" or monotonic() < trace_deadline:
                        raise
        bootstrap.bind(CodingManagedLocalCommandV1(launch, output_capture_factory=capture_factory))
        if trace is not None:
            # Dedicated process-wide composition, never a per-Session context.
            # The child settles native work before this borrowed sink is removed.
            from loushang.foundation.observability.runtime import (
                observability_runtime_context,
            )

            with observability_runtime_context(
                session_id=None, cwd=invocation.service.workspace, mode="managed",
                trace_sink=trace, trace_scopes=frozenset({"turn.start.performance", "host"}),
            ):
                bootstrap.trace_sink_installed(trace)
                return bootstrap.run_process()
        return bootstrap.run_process()
    finally:
        if bootstrap is not None:
            bootstrap.close()
        else:
            endpoint.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Dedicated-process entry; never expose untrusted argument/exception text."""
    try:
        return _run(sys.argv[1:] if argv is None else argv)
    except Exception:
        print("managed_process_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["coding_managed_process_request"]
