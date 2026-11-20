"""Stage 1B provider/observation seam around the unchanged production entry."""
from __future__ import annotations

import asyncio
import base64
import faulthandler
import json
import os
import runpy
import sys
from hashlib import sha256
from pathlib import Path
from time import monotonic

from _hosted_product_child import scripted_stream

from loushang.agent import synthetic_model_transport
from loushang.ai.context import normalize_context
from loushang.ai.model import Capabilities, Model
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.provider import ProviderRequest
from loushang.ai.types import ImagePart
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.appservice.execution_registry import ExecutionRegistryV1
from loushang.coding.hosted.managed.local import CodingManagedLocalCommandV1

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
    if (root / "image-model").exists():
        latest = context.messages[-1]
        parts = latest.content if isinstance(latest.content, list) else []
        images = [sha256(base64.b64decode(part.data)).hexdigest()
                  for part in parts if isinstance(part, ImagePart)]
        request = AnthropicMessagesAdapter().prepare_request(ProviderRequest(
            model, normalize_context(context, model=model), options, "http://127.0.0.1",
            invocation_id="image-test-request",
        ))
        wire = request.payload_for_transport()
        encoded_images = [sha256(base64.b64decode(part["source"]["data"])).hexdigest()
                          for part in wire["messages"][-1]["content"] if part["type"] == "image"]
        assert encoded_images == images
        audit("model_images", images=images, provider_payload_images=encoded_images)
        return await scripted_stream(model, context, options)
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
        api="anthropic-messages" if (root / "image-model").exists() else None,
        capabilities=Capabilities(input=("text", "image") if (root / "image-model").exists() else ("text",), context_window=128000, max_tokens=4096),
    ), "stream_fn": held_stream, "tools": []})


original_submit = ExecutionRegistryV1.submit


def observed_submit(self, binding, text, submission_id, resource_refs=()):
    record = original_submit(self, binding, text, submission_id, resource_refs)
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
        runpy.run_module('loushang.coding.hosted.managed.process', run_name="__main__")
    finally:
        faulthandler.cancel_dump_traceback_later()
