"""Fixed installed managed-child composition for first-use tests only.

Accept only the production invocation/session-root/control-descriptor arguments.
The test parent precreates a private observations directory in its workspace.
No dynamic provider/module/executable selection is exposed to production.
"""

from __future__ import annotations

import os
import runpy
import stat
import sys
from dataclasses import replace
from pathlib import Path


def request_factory(invocation, descriptor, *, executable, environment, session_root=None, admission_diagnostic=False):
    """Keep original launch facts; select only this fixed, frozen test entry."""
    from loushang.coding.managed_process import coding_managed_process_request

    original = coding_managed_process_request(
        invocation, descriptor, executable=executable,
        environment=environment, session_root=session_root,
    )
    return replace(original, argv=(
        original.argv[0], "-I", str(Path(__file__).resolve()), *original.argv[3:],
        *(("--admission-diagnostic",) if admission_diagnostic else ()),
    ))


def main(arguments=None):
    from loushang.apphost.managed.invocation import ManagedChildInvocationV1
    from loushang.coding import managed_process

    arguments = list(sys.argv[1:] if arguments is None else arguments)
    diagnostic = len(arguments) == 4 and arguments[-1] == "--admission-diagnostic"
    if diagnostic:
        arguments = arguments[:-1]
    if len(arguments) != 3:
        raise ValueError("fixed child requires original managed arguments")
    origin = Path(managed_process.__file__).resolve()
    if not origin.is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError("fixed child must use its measured installation")
    invocation = ManagedChildInvocationV1.from_json(arguments[0])
    root = Path(invocation.service.workspace) / "lmux-test-observations"
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or root.resolve() != root):
        raise ValueError("test observation root must be precreated and private")

    # Fixed sibling resources are bound by the collector's helper manifest.
    # Loading BoundaryTrace alone does not call its instrumenting install().
    helpers = Path(__file__).resolve().parent
    trace_type = runpy.run_path(str(helpers / "_hosted_boundary_trace.py"))["BoundaryTrace"]
    run_product = runpy.run_path(str(helpers / "_lmux_synthetic_product.py"))["run_product"]
    trace = trace_type(root)
    trace.emit("fixed_product_selected", instance_id=invocation.instance.instance_id)
    options = {"admission_diagnostic": trace.emit} if diagnostic else {}
    gate_root = root / "completion-gates"
    if gate_root.exists():
        gate_type = runpy.run_path(str(helpers / "_lmux_completion_gate.py"))["CompletionGate"]
        options["completion_gate"] = gate_type(gate_root, invocation.instance.instance_id)
    result = run_product(arguments, lambda phase, identity: trace.emit(phase, call_id=identity), **options)
    trace.emit("fixed_product_returned", status=result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
