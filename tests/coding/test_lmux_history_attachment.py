"""Temporary attachment ownership; connection remains with the outer owner."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from loushang.appserver.protocol import AckV1

from . import _lmux_history_seed as seed


@pytest.mark.parametrize("fault", [None, "attach-lost", "wrong-member", "seed-error", "seed-cancel",
                                  "detach-lost", "detach-bad-ack", "both"])
def test_attachment_failure_never_returns_seed_success(monkeypatch, fault):
    events, identity = [], object()
    primary = asyncio.CancelledError() if fault == "seed-cancel" else RuntimeError("seed failed")
    deadline = time.monotonic() + 660

    async def attach(request):
        events.append("attach")
        assert request.selector.mux_space_id == "mux"
        if fault == "attach-lost":
            raise TimeoutError("accepted attachment reply lost")
        return SimpleNamespace(attachment_id="attachment", controller_generation=2,
            mux_space=SimpleNamespace(mux_space_id="mux", members=[SimpleNamespace(
                member_id="other" if fault == "wrong-member" else "member", session=identity)]))

    async def populate(client, **kwargs):
        events.append("seed")
        assert kwargs == dict(attachment_id="attachment", generation=2, member_id="member",
                              identity=identity, deadline=deadline - 30)
        if fault in {"seed-error", "seed-cancel", "both"}:
            raise primary
        return {"rounds": ["synthetic-evidence"]}

    async def detach(request):
        events.append("detach")
        assert request.attachment_id == "attachment" and request.controller_generation == 2
        if fault in {"detach-lost", "both"}:
            raise TimeoutError("detach reply lost")
        return object() if fault == "detach-bad-ack" else AckV1()

    monkeypatch.setattr(seed, "seed_history", populate)
    client = SimpleNamespace(attach_mux=attach, detach_mux=detach)
    async def run():
        return await seed.seed_attached_history(client, mux_id="mux", member_id="member", identity=identity, deadline=deadline)
    if fault:
        expected = asyncio.CancelledError if fault == "seed-cancel" else RuntimeError if fault in {"seed-error", "both"} else ValueError if fault in {"wrong-member", "detach-bad-ack"} else TimeoutError
        with pytest.raises(expected) as caught:
            asyncio.run(run())
        if fault in {"seed-error", "seed-cancel", "both"}:
            assert caught.value is primary
        if fault == "both":
            assert primary.__notes__ == ["history detach failed: TimeoutError"]
    else:
        result = asyncio.run(run())
        assert result["rounds"] == ["synthetic-evidence"]
        assert result["detached_at"] < deadline
        receipt = result["attachment"]
        assert receipt["deadline"] == deadline
        assert receipt["attach_started_at"] <= receipt["attached_at"] <= receipt["detach_started_at"] <= result["detached_at"]
        assert receipt["attach_deadline"] == min(deadline, receipt["attach_started_at"] + 30)
        assert receipt["detach_deadline"] == min(deadline, receipt["detach_started_at"] + 30)
    assert events == (["attach"] if fault == "attach-lost" else
                      ["attach", "detach"] if fault == "wrong-member" else ["attach", "seed", "detach"])
