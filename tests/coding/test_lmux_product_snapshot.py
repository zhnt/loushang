import asyncio
import time
from types import SimpleNamespace as NS

import pytest

from loushang.appserver.protocol import TranscriptRecordKindV1 as Kind

from . import _lmux_product_snapshot as observer
from ._lmux_product_snapshot import (
    confirm_denied_tool_reply,
    confirm_interrupted_reply,
    confirm_natural_reply,
    confirm_pending_reply,
    confirm_reply,
    confirm_tool_reply,
)


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("fault", [None, "duplicate", "wrong-nonce", "wrong-state", "error"])
def test_natural_snapshot_requires_exact_original_and_next_turn(pending, fault):
    identity, detached = object(), []
    nonce, next_nonce = "a" * 32, "b" * 32
    expected = "LMUX_REPLY_" + (nonce if pending else next_nonce)
    records = [(Kind.USER, "gated " + ("c" * 32 if fault == "wrong-nonce" else nonce))]
    if not pending:
        records += [(Kind.ASSISTANT, "LMUX_REPLY_" + nonce),
                    (Kind.USER, "reply " + next_nonce), (Kind.ASSISTANT, expected)]
    if fault == "duplicate":
        records.append(records[-1])
    if fault == "error":
        records.append((Kind.ERROR, "failure"))

    class Client:
        async def attach_mux(self, request):
            return NS(attachment_id="attachment", controller_generation=1,
                      mux_space=NS(mux_space_id="mux", members=(
                          NS(member_id="member", session=identity, title="FirstUse"),)))

        async def snapshot_session(self, request):
            return NS(identity=identity, running=not pending if fault == "wrong-state" else pending,
                      records=tuple(NS(kind=k, text=t) for k, t in records))

        async def detach_mux(self, request):
            detached.append(request)

    async def run():
        return await confirm_natural_reply(Client(), mux_id="mux", member_id="member",
            identity=identity, expected=expected, natural_nonce=nonce, pending=pending,
            deadline=time.monotonic() + 5)
    if fault is None:
        asyncio.run(run())
    else:
        with pytest.raises(AssertionError):
            asyncio.run(run())
    assert len(detached) == 1


@pytest.mark.parametrize("denied", [False, True])
@pytest.mark.parametrize("fault", [None, "duplicate", "wrong-user", "missing-call", "wrong-reply", "running", "error"])
def test_tool_snapshot_is_fresh_exact_formal_result(fault, denied):
    identity, detached = object(), []
    expected = "Tool lmux_evidence requires approval" if denied else "LMUX_TOOL_COMPLETED"
    unexpected = "LMUX_TOOL_COMPLETED" if denied else "Tool lmux_evidence requires approval"
    records = [(Kind.USER, "wrong" if fault == "wrong-user" else "approval"),
               (Kind.ASSISTANT, ""), (Kind.ASSISTANT, unexpected if fault == "wrong-reply" else expected)]
    if fault == "duplicate":
        records.append(records[-1])
    elif fault == "missing-call":
        records.pop(1)
    elif fault == "error":
        records.append((Kind.ERROR, "failure"))

    class Client:
        async def attach_mux(self, request):
            return NS(attachment_id="attachment", controller_generation=1,
                      mux_space=NS(mux_space_id="mux", members=(
                          NS(member_id="member", session=identity, title="FirstUse"),)))

        async def snapshot_session(self, request):
            return NS(identity=identity, running=fault == "running", title="Coding",
                      records=tuple(NS(kind=k, text=t) for k, t in records))

        async def detach_mux(self, request):
            detached.append(request)

    async def run():
        confirm = confirm_denied_tool_reply if denied else confirm_tool_reply
        return await confirm(Client(), mux_id="mux", member_id="member", identity=identity,
                             expected=expected, deadline=time.monotonic() + 5)
    if fault is None:
        assert asyncio.run(run()).running is False
    else:
        with pytest.raises(AssertionError):
            asyncio.run(run())
    assert len(detached) == 1


@pytest.mark.parametrize("expected", ["LMUX_TOOL_COMPLETED", "", "Tool another requires approval"])
def test_denial_snapshot_rejects_wrong_witness_before_attaching(expected):
    with pytest.raises(ValueError, match="denied tool reply witness"):
        asyncio.run(confirm_denied_tool_reply(object(), mux_id="mux", member_id="member",
                    identity=object(), expected=expected, deadline=time.monotonic() + 5))


@pytest.mark.parametrize("fault", [None, "missing-empty", "extra-empty", "old-success", "duplicate-b", "reordered", "running", "identity", "error"])
def test_reply_after_interrupt_requires_exact_order_and_one_new_reply(fault):
    identity = object()
    prior, next_nonce = "a" * 32, "b" * 32
    expected = "LMUX_REPLY_" + next_nonce
    records = [(Kind.USER, "delayed " + prior), (Kind.ASSISTANT, ""),
               (Kind.USER, "reply " + next_nonce), (Kind.ASSISTANT, expected)]
    if fault == "missing-empty":
        records.pop(1)
    elif fault == "extra-empty":
        records.insert(2, (Kind.ASSISTANT, ""))
    elif fault == "old-success":
        records[1] = (Kind.ASSISTANT, "LMUX_REPLY_" + prior)
    elif fault == "duplicate-b":
        records.append((Kind.ASSISTANT, expected))
    elif fault == "reordered":
        records[0], records[2] = records[2], records[0]
    elif fault == "error":
        records.append((Kind.ERROR, "failure"))
    detached = []

    class Client:
        async def attach_mux(self, request):
            return NS(attachment_id="attachment", controller_generation=1,
                      mux_space=NS(mux_space_id="mux", members=(
                          NS(member_id="member", session=identity, title="FirstUse"),)))

        async def snapshot_session(self, request):
            return NS(identity=object() if fault == "identity" else identity, title="Coding",
                      running=fault == "running", records=tuple(NS(kind=k, text=t) for k, t in records))

        async def detach_mux(self, request):
            detached.append(request)

    async def run():
        return await confirm_interrupted_reply(Client(), mux_id="mux", member_id="member", identity=identity,
                                              expected=expected, interrupted_nonce=prior,
                                              deadline=time.monotonic() + 5)

    if fault is None:
        assert asyncio.run(run()).running is False
    else:
        with pytest.raises(AssertionError):
            asyncio.run(run())
    assert len(detached) == 1


@pytest.mark.parametrize("fault", [None, "finished", "committed", "wrong-request", "error", "detach"])
def test_delayed_snapshot_is_running_without_a_committed_reply(fault):
    identity = object()
    nonce = "b" * 32
    calls = []

    class Client:
        async def attach_mux(self, request):
            calls.append("attach")
            return NS(attachment_id="attachment", controller_generation=1,
                      mux_space=NS(mux_space_id="mux", members=(
                          NS(member_id="member", session=identity, title="FirstUse"),)))

        async def snapshot_session(self, request):
            calls.append("snapshot")
            records = [NS(kind=Kind.USER, text="delayed " + ("a" * 32 if fault == "wrong-request" else nonce))]
            if fault == "committed":
                records.append(NS(kind=Kind.ASSISTANT, text="LMUX_REPLY_" + nonce))
            if fault == "error":
                records.append(NS(kind=Kind.ERROR, text="error"))
            return NS(identity=identity, title="Coding", running=fault != "finished", records=records)

        async def detach_mux(self, request):
            calls.append("detach")
            if fault == "detach":
                raise RuntimeError("detach failed")

    async def run():
        return await confirm_pending_reply(Client(), mux_id="mux", member_id="member", identity=identity,
                                           expected="LMUX_REPLY_" + nonce, deadline=time.monotonic() + 5)

    if fault is None:
        assert asyncio.run(run()).running is True
    else:
        with pytest.raises(RuntimeError if fault == "detach" else AssertionError):
            asyncio.run(run())
    assert calls == ["attach", "snapshot", "detach"]


@pytest.mark.parametrize("fault", [None, "mux", "member", "member-title", "identity", "running", "duplicate", "error", "detach", "missing-user", "wrong-user", "extra-user", "reordered"])
def test_snapshot_confirmation_requires_exact_committed_reply_and_detaches(fault):
    expected = "LMUX_REPLY_" + "a" * 32
    identity = object()
    calls = []
    member = NS(member_id="wrong" if fault == "member" else "member", session=identity,
                title="Wrong" if fault == "member-title" else "FirstUse")
    records = [NS(kind=Kind.USER, text="reply " + "a" * 32), NS(kind=Kind.ASSISTANT, text=expected)]
    if fault == "missing-user":
        records.pop(0)
    elif fault == "wrong-user":
        records[0].text = "reply " + "b" * 32
    elif fault == "extra-user":
        records.insert(0, NS(kind=Kind.USER, text="old request"))
    elif fault == "reordered":
        records.reverse()
    if fault == "duplicate":
        records *= 2
    if fault == "error":
        records.append(NS(kind=Kind.ERROR, text="failed"))
    snapshot = NS(identity=object() if fault == "identity" else identity,
                  title="Coding", running=fault == "running", records=records)

    class Client:
        async def attach_mux(self, request):
            calls.append("attach")
            assert request.selector.mux_space_id == "mux"
            return NS(attachment_id="attachment", controller_generation=1,
                      mux_space=NS(mux_space_id="wrong" if fault == "mux" else "mux", members=(member,)))

        async def snapshot_session(self, request):
            calls.append("snapshot")
            assert (request.attachment_id, request.controller_generation, request.member_id) == ("attachment", 1, "member")
            return snapshot

        async def detach_mux(self, request):
            calls.append("detach")
            assert (request.attachment_id, request.controller_generation) == ("attachment", 1)
            if fault == "detach":
                raise RuntimeError("detach failed")

    async def run():
        return await confirm_reply(Client(), mux_id="mux", member_id="member", identity=identity,
                                   expected=expected, deadline=time.monotonic() + 5)

    if fault is None:
        assert asyncio.run(run()) is snapshot
    else:
        with pytest.raises(RuntimeError if fault == "detach" else AssertionError):
            asyncio.run(run())
    assert calls[0] == "attach" and calls[-1] == "detach"


@pytest.mark.parametrize("deadline", [0, float("nan"), float("inf")])
def test_invalid_or_expired_deadline_does_not_dispatch(deadline):
    class Client:
        def attach_mux(self, request):
            pytest.fail("expired observation dispatched attach")

    with pytest.raises(TimeoutError if deadline == 0 else ValueError):
        asyncio.run(confirm_reply(Client(), mux_id="mux", member_id="member", identity=object(),
                                  expected="LMUX_REPLY_" + "a" * 32, deadline=deadline))


def test_late_synchronous_snapshot_is_not_success(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(observer.time, "monotonic", lambda: clock[0])
    identity = object()
    calls = []

    class Client:
        async def attach_mux(self, request):
            calls.append("attach")
            return NS(attachment_id="attachment", controller_generation=1,
                      mux_space=NS(mux_space_id="mux", members=(NS(member_id="member", session=identity, title="FirstUse"),)))

        async def snapshot_session(self, request):
            calls.append("snapshot")
            clock[0] = 102.0
            return NS(identity=identity, title="FirstUse", running=False,
                      records=(NS(kind=Kind.ASSISTANT, text="LMUX_REPLY_" + "a" * 32),))

        def detach_mux(self, request):
            pytest.fail("deadline-expired detach must be left to outer connection close")

    with pytest.raises(TimeoutError, match="response arrived") as failure:
        asyncio.run(confirm_reply(Client(), mux_id="mux", member_id="member", identity=identity,
                                  expected="LMUX_REPLY_" + "a" * 32, deadline=101.0))
    assert calls == ["attach", "snapshot"]
    assert any("detach failed: TimeoutError" in note for note in failure.value.__notes__)
