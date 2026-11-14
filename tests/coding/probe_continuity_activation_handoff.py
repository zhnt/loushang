"""Fixed pre-A162 handoff observations; explicitly invoked local validation.

Captured from actual ed8ce6f3b Coding bridge before migration. Source, failed
observer attempt and capture guard remain in external A162 evidence. Controlled
staging/prepare ports isolate compound failures; this does not exercise native IO.
There is no capture mode or default PR test discovery route.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import continuity as product
from loushang.harness.continuity import (
    CONTINUITY_JSONL_MEDIA_TYPE,
    ContinuityActivationPayload,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
)
from loushang.harness.continuity._payload_staging import _ContinuityPayloadStaging

CASES = (
    "success",
    "write-fail",
    "write-cancel",
    "prepare-fail",
    "prepare-cancel",
    "prepare-fail-remove-fail",
    "prepare-cancel-remove-fail",
    "remove-fail",
    "remove-fail-abort-fail",
    "remove-fail-abort-cancel",
    "consume-fail",
    "consume-cancel",
    "consume-fail-abort-fail",
    "consume-cancel-abort-fail",
    "consume-fail-abort-cancel",
    "abort-fail-retry",
    "abort-cancel-retry",
)
EXPECTED = Path(__file__).parent / "fixtures" / "continuity_activation_handoff_v1.json"


def error_graph(error):
    seen = {}

    def visit(value):
        if value is None:
            return None
        if id(value) in seen:
            return {"ref": seen[id(value)]}
        number = len(seen)
        seen[id(value)] = number
        return {
            "id": number,
            "type": type(value).__name__,
            "args": list(value.args),
            "notes": getattr(value, "__notes__", []),
            "suppress": value.__suppress_context__,
            "cause": visit(value.__cause__),
            "context": visit(value.__context__),
        }

    return visit(error)


async def observe(case, monkeypatch):
    events = []
    errors = {
        "write": OSError("write failure"),
        "prepare": ValueError("prepare failure"),
        "remove": OSError("remove failure"),
        "consume": LookupError("consume failure"),
        "abort": RuntimeError("abort failure"),
    }
    for phase in ("write", "prepare", "consume", "abort"):
        if phase + "-cancel" in case:
            errors[phase] = asyncio.CancelledError(phase + " cancelled")

    async def write(_owner, root, payload):
        events.append(["write", str(root), payload.digest])
        if case.startswith("write-"):
            raise errors["write"]
        return SimpleNamespace(path=Path("/private-input/transcript.jsonl"))

    async def remove(_owner, staged):
        events.append(["remove", str(staged.path)])
        if "remove-fail" in case:
            raise errors["remove"]

    class Operation:
        aborts = 0

        async def consume(self):
            events.append(["consume"])
            if case.startswith("consume-"):
                raise errors["consume"]
            return "restored-session"

        async def abort(self):
            self.aborts += 1
            events.append(["abort", self.aborts])
            if "abort-" in case and self.aborts == 1:
                raise errors["abort"]

        async def close(self):
            await self.abort()

    operation = Operation()

    class Runtime:
        async def prepare_restore_session_operation(self, path, **kwargs):
            events.append(["prepare", str(path), kwargs])
            if case.startswith("prepare-"):
                raise errors["prepare"]
            return operation

    owner = product._CONTINUITY_PAYLOAD_STAGING
    monkeypatch.setattr(_ContinuityPayloadStaging, "write_atomic", write)
    monkeypatch.setattr(_ContinuityPayloadStaging, "remove_atomic", remove)
    monkeypatch.setattr(
        product,
        "_write_private_continuity_payload_atomic",
        lambda root, payload: write(owner, root, payload),
    )
    monkeypatch.setattr(
        product,
        "_remove_private_continuity_payload_atomic",
        lambda staged: remove(owner, staged),
    )
    bridge = product.CodingContinuityActivationBridge(
        Runtime(), temporary_root="/private-input", fallback_cwd="/trusted-cwd"
    )
    target = ContinuityTarget(provider_id="remote", opaque_id="one")
    source = ContinuityProviderSourceDescriptor(
        provider_id="remote",
        source="oem",
        source_id="source",
        implementation="remote.provider",
        implementation_version=1,
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n", media_type=CONTINUITY_JSONL_MEDIA_TYPE
    )
    failures = []
    value = None
    try:
        lease = await bridge.prepare(target, payload, source)
        if case.startswith("abort-"):
            try:
                await lease.abort()
            except BaseException as error:
                failures.append(error_graph(error))
            await lease.abort()
        else:
            try:
                value = await lease.consume()
            except BaseException as error:
                failures.append(error_graph(error))
            await lease.abort()
            await lease.close()
    except BaseException as error:
        failures.append(error_graph(error))
    return {
        "events": events,
        "failures": failures,
        "value": value,
        "aborts": operation.aborts,
    }


@pytest.mark.parametrize("case", CASES)
def test_original_handoff(case, monkeypatch):
    assert (
        asyncio.run(observe(case, monkeypatch))
        == json.loads(EXPECTED.read_text())[case]
    )
