"""Fixed installed parent entry for synthetic managed Product tests only."""

from __future__ import annotations

import runpy
import sys
from contextlib import nullcontext
from functools import partial
from pathlib import Path


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    diagnostic = arguments[:1] == ["--admission-diagnostic"]
    if diagnostic:
        arguments = arguments[1:]
    interaction_diagnostic = arguments[:1] == ["--interaction-diagnostic"]
    if interaction_diagnostic:
        arguments = arguments[1:]
    if arguments not in (["new", "-s", "perf"], ["start", "-t", "perf"]):
        raise ValueError("fixed Product parent accepts only new -s perf or start -t perf")

    from loushang.coding.cli import lmux, lmux_command

    prefix = Path(sys.prefix).resolve()
    for module in (lmux, lmux_command):
        if not Path(module.__file__).resolve().is_relative_to(prefix):
            raise ValueError("fixed parent must use its measured installation")
    factory = runpy.run_path(str(Path(__file__).with_name("_lmux_product_child.py")))["request_factory"]
    if diagnostic:
        factory = partial(factory, admission_diagnostic=True)
    original = lmux_command.coding_managed_process_request
    observation = nullcontext()
    if interaction_diagnostic:
        from loushang.appserver.remote_client import RemoteAppClientV1

        helpers = Path(__file__).resolve().parent
        trace_type = runpy.run_path(str(helpers / "_hosted_boundary_trace.py"))["BoundaryTrace"]
        observe = runpy.run_path(str(helpers / "_lmux_interaction_receipt.py"))["observe_interaction_receipts"]
        observation = observe(RemoteAppClientV1, trace_type(Path.cwd() / "lmux-interaction-observations"))
    try:
        lmux_command.coding_managed_process_request = factory
        with observation:
            return lmux.main(arguments)
    finally:
        lmux_command.coding_managed_process_request = original


if __name__ == "__main__":
    raise SystemExit(main())
