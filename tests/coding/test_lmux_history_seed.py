"""Borrowed public seed calls; no claim of real connection settlement."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from loushang.appserver.protocol import (
    AckV1,
    AttachmentEventV1,
    SessionEventKindV1,
    SessionEventV1,
)

from . import _lmux_history_seed as seed
from ._lmux_history_recipe import OMITTED, history_records


async def _empty_events(**kwargs):
    return ()


@pytest.mark.parametrize("fault", [None, "lost-ack", "bad-ack", "cancel", "identity", "initial-busy",
                                  "old-then-new", "forever-old", "bad-text", "error", "expired",
                                  "event-lost", "event-cancel", "event-identity", "event-error", "event-shape", "event-size", "event-endless"])
def test_public_seed_never_retries_or_accepts_stale_idle(monkeypatch, fault):
    identity = SimpleNamespace(session_id="session")
    sends, snapshots = [], []
    full = history_records()

    async def sleep(_):
        return None
    monkeypatch.setattr(seed.asyncio, "sleep", sleep)

    async def start(request):
        sends.append(request)
        assert request.attachment_id == "attachment" and request.controller_generation == 1
        assert request.member_id == "member"
        if fault == "lost-ack":
            raise TimeoutError("lost original reply")
        if fault == "cancel":
            raise asyncio.CancelledError()
        return object() if fault == "bad-ack" else AckV1()

    async def snapshot(request):
        snapshots.append(request)
        count = len(sends)
        if fault == "forever-old" or (fault == "old-then-new" and len(snapshots) == 2):
            count = 0
        rows = full[max(0, count * 2 - 14):count * 2]
        if count > 7:
            rows = [["status", OMITTED], *rows]
        if count and fault == "bad-text":
            rows = [*rows[:-1], ["assistant", "wrong"]]
        if count and fault == "error":
            rows = [["error", "failed"]]
        return SimpleNamespace(identity=object() if fault == "identity" else identity,
                               running=fault == "initial-busy",
                               records=[SimpleNamespace(kind=SimpleNamespace(value=kind), text=text) for kind, text in rows])

    async def events(**kwargs):
        if fault == "event-lost":
            raise TimeoutError("event response lost")
        if fault == "event-cancel":
            raise asyncio.CancelledError()
        if fault == "event-shape":
            return []
        if fault in {"event-identity", "event-error", "event-size", "event-endless"}:
            value = AttachmentEventV1("attachment", "member", SessionEventV1(
                "other" if fault == "event-identity" else "session", 1,
                SessionEventKindV1.ERROR if fault == "event-error" else SessionEventKindV1.STATUS))
            return (value,) * (65 if fault == "event-size" else 1)
        return ()

    async def run():
        return await seed.seed_history(SimpleNamespace(start_turn=start, snapshot_session=snapshot, read_events=events),
            attachment_id="attachment", generation=1, member_id="member", identity=identity,
            deadline=0.0 if fault == "expired" else time.monotonic() + 600)

    if fault in {None, "old-then-new"}:
        result = asyncio.run(run())
        assert len(sends) == len(result["rounds"]) == 128
        assert [request.text for request in sends] == [f"history {i:04d}" for i in range(128)]
        for row in result["rounds"]:
            assert row["started_at"] <= row["acknowledged_at"] <= row["settled_at"]
        assert result["rounds"][0]["snapshot_reads"] == (2 if fault == "old-then-new" else 1)
    else:
        expected = asyncio.CancelledError if fault in {"cancel", "event-cancel"} else TimeoutError if fault in {"lost-ack", "forever-old", "expired", "event-lost", "event-endless"} else ValueError
        with pytest.raises(expected):
            asyncio.run(run())
        assert len(sends) == (0 if fault in {"identity", "initial-busy", "expired"} else 1)
        if fault.startswith("event-"):
            assert len(snapshots) == 1  # Only the pre-turn snapshot; no success observation after event failure.
        if fault == "forever-old":
            assert len(snapshots) == 1 + seed.MAX_POLLS


@pytest.mark.parametrize("deadline", [True, -1, float("inf"), float("nan"), 10**400, "later"])
def test_invalid_deadline_is_rejected_before_client_use(deadline):
    with pytest.raises(ValueError):
        asyncio.run(seed.seed_history(None, attachment_id="attachment", generation=1,
                                     member_id="member", identity=object(), deadline=deadline))


@pytest.mark.parametrize("late_round", [0, 127])
@pytest.mark.parametrize("budget", [10.0, 600.0])
def test_validation_time_cannot_cross_round_or_total_deadline(monkeypatch, late_round, budget):
    clock, count = [0.0], [0]
    identity = object()
    full = history_records()
    monkeypatch.setattr(seed, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    validate = seed.validate_history_window

    def slow_validation(rows, index):
        validate(rows, index)
        if index == late_round:
            clock[0] = min(budget, seed.ROUND_SECONDS) + 1
    monkeypatch.setattr(seed, "validate_history_window", slow_validation)

    async def start(request):
        count[0] += 1
        return AckV1()

    async def snapshot(request):
        total = count[0]
        rows = full[max(0, total * 2 - 14):total * 2]
        if total > 7:
            rows = [["status", OMITTED], *rows]
        return SimpleNamespace(identity=identity, running=False,
            records=[SimpleNamespace(kind=SimpleNamespace(value=kind), text=text) for kind, text in rows])

    with pytest.raises(TimeoutError, match="validation exceeded"):
        asyncio.run(seed.seed_history(SimpleNamespace(start_turn=start, snapshot_session=snapshot, read_events=_empty_events),
            attachment_id="attachment", generation=1, member_id="member", identity=identity, deadline=budget))
    assert count[0] == late_round + 1
