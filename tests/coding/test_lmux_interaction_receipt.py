import asyncio
import time
from types import SimpleNamespace as NS

import pytest

from loushang.appserver.protocol import (
    AckV1,
    InteractionOutcomeV1,
    InteractionRespondV1,
)

from ._hosted_boundary_trace import BoundaryTrace
from ._lmux_interaction_receipt import observe_interaction_receipts
from ._lmux_product_probe import _denial_receipt


@pytest.mark.parametrize("fault", [None, "lost", "wrong-result", "wrong-member", "approve", "duplicate", "old"])
def test_original_denial_receipt_is_required_not_just_model_echo(tmp_path, fault):
    root = tmp_path / "lmux-interaction-observations"
    root.mkdir(mode=0o700)
    trace = BoundaryTrace(root)
    calls = []
    receipt = AckV1()
    request = InteractionRespondV1("attachment", 1, "member", "interaction",
                                  InteractionOutcomeV1.APPROVE if fault == "approve" else InteractionOutcomeV1.DENY)

    class Client:
        async def respond_interaction(self, value):
            assert value is request
            calls.append(value)
            if fault == "lost":
                raise TimeoutError("lost reply")
            return NS() if fault == "wrong-result" else receipt

    original = Client.respond_interaction
    started = time.monotonic_ns()

    async def run():
        with observe_interaction_receipts(Client, trace):
            assert await Client().respond_interaction(request) is receipt
            if fault == "duplicate":
                await Client().respond_interaction(request)

    if fault in {"lost", "wrong-result"}:
        with pytest.raises((TimeoutError, TypeError)):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert Client.respond_interaction is original
    assert len(calls) == (2 if fault == "duplicate" else 1)
    target = {"members": [{"memberId": "other" if fault == "wrong-member" else "member"}]}
    if fault == "old":
        started = time.monotonic_ns()
    if fault is None:
        _denial_receipt(tmp_path, target, not_before_ns=started)
    else:
        with pytest.raises(AssertionError):
            _denial_receipt(tmp_path, target, not_before_ns=started)


def test_dropped_deny_cannot_be_replaced_by_identical_error_echo(tmp_path):
    root = tmp_path / "lmux-interaction-observations"
    root.mkdir(mode=0o700)
    BoundaryTrace(root)  # Parent exists, but no original request was sent.
    with pytest.raises(AssertionError):
        _denial_receipt(tmp_path, {"members": [{"memberId": "member"}]}, not_before_ns=0)
