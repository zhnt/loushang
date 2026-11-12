"""Stage 1B provider/observation seam around the unchanged production entry."""
from __future__ import annotations

import asyncio
import faulthandler
import json
import os
import runpy
import sys
from pathlib import Path
from time import monotonic

from _hosted_product_child import scripted_stream

from loushang.agent import synthetic_model_transport
from loushang.ai.model import Capabilities, Model
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.appservice.execution_registry import ExecutionRegistryV1
from loushang.coding.managed_local import CodingManagedLocalCommandV1

root = Path(ManagedChildInvocationV1.from_json(sys.argv[1]).service.host_root)


def audit(kind, **fields):
    with (root / "execution-audit.jsonl").open("a") as stream:
        stream.write(json.dumps({"kind": kind, "pid": os.getpid(), "time": monotonic(), **fields}) + "\n")


async def gate(name):
    deadline = monotonic() + (600 if (root / "desktop-acceptance").exists() else 75)
    while not (root / name).exists():
        assert monotonic() < deadline, f"provider gate expired: {name}"
        await asyncio.sleep(0.01)


@synthetic_model_transport
async def held_stream(model, context, options=None):
    audit("model_entered")
    await gate("advance-after-a")
    audit("model_progressed")
    await gate("finish-after-b")
    result = await scripted_stream(model, context, options)
    audit("model_returned")
    return result


original_init = CodingManagedLocalCommandV1.__init__


def with_provider(self, launch, **kwargs):
    original_init(self, launch, **{**kwargs, "model": Model(
        id="faux-model", name="Faux", provider="faux", endpoint="anthropic-messages",
        capabilities=Capabilities(input=("text",), context_window=128000, max_tokens=4096),
    ), "stream_fn": held_stream, "tools": []})


original_submit = ExecutionRegistryV1.submit


def observed_submit(self, binding, text, submission_id):
    record = original_submit(self, binding, text, submission_id)
    audit("accepted", submission_id=submission_id, execution_id=record.state.execution_id,
          session_id=record.identity.session_id, service_instance_id=self.service_instance_id)
    return record


if (root / "stop-scenario.json").exists():
    from _managed_stop_probe import install

    held_stream = install(root, audit)

if (root / "desktop-scenario-v2").exists():
    from _managed_gui_probe import install as install_gui

    held_stream = install_gui(root, audit)

CodingManagedLocalCommandV1.__init__ = with_provider
ExecutionRegistryV1.submit = observed_submit
with (root / "host-diagnostic.log").open("w") as diagnostic:
    faulthandler.dump_traceback_later(1800 if (root / "desktop-scenario-v2").exists() else
                                     600 if (root / "desktop-acceptance").exists() else 100,
                                     exit=True, file=diagnostic)
    try:
        # All invocation admission, managed Mux, lifecycle, listeners and shutdown
        # run through the production module. No replacement bootstrap/runtime.
        runpy.run_module("loushang.coding.managed_process", run_name="__main__")
    finally:
        faulthandler.cancel_dump_traceback_later()
