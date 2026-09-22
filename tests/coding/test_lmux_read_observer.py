"""Fault boundaries of the process-only test observer, not a new runtime port."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from loushang.apphost.managed import (
    connection,
    defaults,
    discovery,
    lifecycle,
    mux_management,
    namespace_admission,
    paths,
)
from loushang.coding.cli import mux as mux_cli

from ._g18_native_probe import (
    managed_history_confirmation,
    managed_history_observation,
    managed_read_observation,
    managed_reply_observation,
)


@pytest.fixture
def observer_runners(monkeypatch):
    original, runners = asyncio.Runner, []

    def retained_runner():
        runner = original()
        runners.append(runner)
        return runner

    monkeypatch.setattr(asyncio, "Runner", retained_runner)
    try:
        yield
    finally:
        # Production would exit its observer process on cleanup debt. Our
        # intercepted hard exit must not leak that process's fake-resource loop.
        for runner in runners:
            runner.close()


@pytest.mark.parametrize("fault", [
    None, "prepare-cancel", "read-cancel", "connection-close", "journal-close",
    "namespace-close", "runner-start", "native-missing", "native-replaced",
    "reply-ok", "pending-ok", "attach-lost", "snapshot-cancel",
    "history-ok", "history-seed-error", "history-close", "history-late-read", "history-late-verify",
    "warm-ok", "warm-tail", "warm-running", "warm-identity", "warm-snapshot-id", "warm-close", "warm-detach",
])
def test_managed_read_retains_borrowed_owners_until_connection_settles(monkeypatch, tmp_path, fault, observer_runners):
    events = []
    clock = [0.0]
    if fault == "history-late-read":
        from . import _g18_native_probe
        monkeypatch.setattr(_g18_native_probe, "time", SimpleNamespace(monotonic=lambda: clock[0], perf_counter=lambda: clock[0]))
    retained = {}
    native, identities = object(), []
    from loushang.appserver.protocol import SessionScopeV1
    session = SimpleNamespace(product_id="coding", continuity_id="continuity-1",
                              session_id="session-1", scope=SessionScopeV1.USER_HOME,
                              scope_fingerprint="c" * 64)

    class Namespace:
        def __init__(self, *args, **kwargs):
            self.cleanup_pending = True
            retained["namespace"] = self

        def open(self, **kwargs):
            events.append("namespace-open")
            return object()

        def close(self):
            assert "connection" not in retained or not retained["connection"].cleanup_pending
            assert "journal" not in retained or retained["journal"].closed
            events.append("namespace-close")
            if fault == "namespace-close":
                raise OSError("namespace still owned")
            self.cleanup_pending = False

    class Journal:
        def __init__(self, *args, **kwargs):
            self.closed = False
            retained["journal"] = self

        def open(self, **kwargs):
            events.append("journal-open")

        def read(self, **kwargs):
            assert not self.closed
            assert kwargs["wait_for_lock"] is True
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return SimpleNamespace(
                handoff=SimpleNamespace(instance=object() if fault == "native-replaced" else retained["connection"].instance),
                native_identity=None if fault == "native-missing" else native,
            )

        def close(self):
            assert "connection" not in retained or not retained["connection"].cleanup_pending
            events.append("journal-close")
            if fault == "journal-close":
                raise OSError("journal still owned")
            self.closed = True

    class Connection:
        def __init__(self, *args, **kwargs):
            self.cleanup_pending = True
            self.instance = SimpleNamespace(instance_id="a" * 32)
            self.application_id = "coding.default"
            self.client = self
            retained["connection"] = self

        async def prepare(self, **kwargs):
            events.append("prepare")
            if fault == "prepare-cancel":
                raise asyncio.CancelledError()

        async def read_mux(self, request):
            events.append("read")
            if fault == "history-late-read":
                clock[0] = 31.0
            assert request.selector.mux_space_id == "mux-perf"
            if fault == "read-cancel":
                raise asyncio.CancelledError()
            return SimpleNamespace(mux_space_id="mux-perf", name="perf", members=(
                SimpleNamespace(member_id="member-1", session=session, title="FirstUse"),
            ))

        async def close(self):
            events.append("connection-close")
            if fault in {"connection-close", "history-close", "warm-close"}:
                raise TimeoutError("connection still owns native IO")
            self.cleanup_pending = False

        async def attach_mux(self, request):
            events.append("attach")
            if fault == "attach-lost":
                raise TimeoutError("attachment accepted but response lost")
            return SimpleNamespace(
                attachment_id="attachment", controller_generation=1,
                mux_space=await self.read_mux(request),
            )

        async def snapshot_session(self, request):
            from loushang.appserver.protocol import TranscriptRecordKindV1
            events.append("snapshot")
            if fault is not None and fault.startswith("warm-"):
                from ._lmux_history_recipe import OMITTED, history_records
                rows = [["status", OMITTED], *history_records()[-14:]]
                if fault == "warm-tail":
                    rows[-1][1] = "incorrect final text"
                return SimpleNamespace(identity=object() if fault == "warm-snapshot-id" else session,
                    running=fault == "warm-running",
                    records=[SimpleNamespace(kind=TranscriptRecordKindV1(kind), text=text) for kind, text in rows])
            if fault == "snapshot-cancel":
                raise asyncio.CancelledError()
            records = [SimpleNamespace(kind=TranscriptRecordKindV1.USER,
                                       text=("delayed " if fault == "pending-ok" else "reply ") + "a" * 32)]
            if fault != "pending-ok":
                records.append(SimpleNamespace(kind=TranscriptRecordKindV1.ASSISTANT, text="LMUX_REPLY_" + "a" * 32))
            return SimpleNamespace(identity=session, title="Coding", running=fault == "pending-ok", records=records)

        async def detach_mux(self, request):
            events.append("detach")
            if fault == "warm-detach":
                raise TimeoutError("detach response lost")

    item = SimpleNamespace(service=SimpleNamespace(service_id="b" * 64),
                           instance=SimpleNamespace(instance_id="a" * 32), reservation=object())
    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **kwargs: SimpleNamespace(
        namespace=object(), platform=SimpleNamespace(runtime=tmp_path),
    ))
    monkeypatch.setattr(namespace_admission, "ManagedNamespaceAdmissionV1", Namespace)
    monkeypatch.setattr(lifecycle, "ManagedServiceJournalV1", Journal)
    monkeypatch.setattr(connection, "ManagedConnectionLeaseV1", Connection)
    monkeypatch.setattr(discovery, "ManagedDiscoveryV1", lambda *args: SimpleNamespace(resolve=lambda *a, **k: item))
    monkeypatch.setattr(paths, "resolve_managed_service_paths", lambda *a, **k: SimpleNamespace(lifecycle=tmp_path))
    monkeypatch.setattr(mux_management, "ManagedMuxManagerV1", lambda *a, **k: SimpleNamespace(
        inspect_mux=lambda *a, **k: SimpleNamespace(creation=SimpleNamespace(mux_space_id="mux-perf")),
    ))

    def hard_exit(code):
        events.append("hard-exit")
        raise RuntimeError("outer observer must classify unresolved cleanup as failure")

    monkeypatch.setattr(os, "_exit", hard_exit)
    if fault == "runner-start":
        def refused(*args):
            raise RuntimeError("runner unavailable")
        monkeypatch.setattr(mux_cli, "_execute", refused)
    if fault is not None and fault.startswith("warm-"):
        target = {"instanceId": "a" * 32, "serviceId": "b" * 64, "muxId": "mux-perf",
                  "members": [{"memberId": "member-1", "sessionId": "session-1"}]}
        expected = {**vars(session), "scope": session.scope.value}
        if fault == "warm-identity":
            expected["continuity_id"] = "different-continuity"
        if fault == "warm-ok":
            result = managed_history_confirmation({}, target, expected, native_identity=identities)
            assert result["history_snapshot"]["identity"] == expected
            assert result["history_snapshot"]["running"] is False
            assert len(result["history_snapshot"]["records"]) == 15
            assert result["observed_at"] <= result["history_snapshot"]["confirmed_at"] <= result["connection_settled_at"]
            assert identities == [native]
        else:
            with pytest.raises(RuntimeError):
                managed_history_confirmation({}, target, expected, native_identity=identities)
        if fault == "warm-identity":
            assert "attach" not in events and "snapshot" not in events
        else:
            assert events.index("attach") < events.index("snapshot") < events.index("detach") < events.index("connection-close")
        if fault != "warm-close":
            assert events.index("connection-close") < events.index("journal-close") < events.index("namespace-close")
    elif fault in {"history-ok", "history-seed-error", "history-close", "history-late-read", "history-late-verify"}:
        import time

        from . import _g18_native_probe, _lmux_history_seed
        offset = [0.0]
        if fault == "history-late-verify":
            # Advance only this observer's clock; never change asyncio's clock.
            monkeypatch.setattr(_g18_native_probe, "time", SimpleNamespace(**(
                vars(time) | {"monotonic": lambda: time.monotonic() + offset[0]})))
        target = {"instanceId": "a" * 32, "serviceId": "b" * 64, "muxId": "mux-perf",
                  "members": [{"memberId": "member-1", "sessionId": "session-1"}]}
        async def seed(client, **kwargs):
            events.append("history-seed")
            assert 650 < kwargs["deadline"] - time.monotonic() <= 660
            assert kwargs["identity"] is session
            if fault == "history-seed-error":
                raise ValueError("seed failed after admission")
            if fault == "history-late-verify":
                offset[0] = 700.0
            return {"rounds": ["settled"]}
        monkeypatch.setattr(_lmux_history_seed, "seed_attached_history", seed)
        if fault == "history-ok":
            result = managed_history_observation({}, target)
            assert result["history_seed"] == {"rounds": ["settled"]}
            receipt = result["verification"]
            assert receipt["deadline"] == receipt["started_at"] + 660
            assert result["observed_at"] <= receipt["started_at"] <= receipt["completed_at"] < receipt["deadline"]
            assert receipt["completed_at"] <= result["connection_settled_at"]
        else:
            with pytest.raises(RuntimeError) as caught:
                managed_history_observation({}, target)
            if fault == "history-late-verify":
                assert isinstance(caught.value.__cause__, TimeoutError)
                assert str(caught.value.__cause__) == "managed verification returned after deadline"
        if fault == "history-late-read":
            assert "history-seed" not in events and "attach" not in events
        else:
            assert events.index("history-seed") < events.index("connection-close")
        if fault != "history-close":
            assert events.index("connection-close") < events.index("journal-close") < events.index("namespace-close")
    elif fault in {"reply-ok", "pending-ok", "attach-lost", "snapshot-cancel"}:
        target = {"instanceId": "a" * 32, "serviceId": "b" * 64, "muxId": "mux-perf",
                  "members": [{"memberId": "member-1", "sessionId": "session-1"}]}
        if fault in {"reply-ok", "pending-ok"}:
            result = managed_reply_observation({}, target, "LMUX_REPLY_" + "a" * 32, pending=fault == "pending-ok")
            assert result["pendingConfirmed" if fault == "pending-ok" else "replyConfirmed"] is True
            assert ("replyConfirmed" in result) is (fault == "reply-ok")
            snapshot = result["snapshot"]
            assert snapshot["identity"]["session_id"] == "session-1"
            assert snapshot["identity"]["scope"] == SessionScopeV1.USER_HOME.value
            assert snapshot["confirmed_at"] >= result["observed_at"]
            assert snapshot["records"][0] == {"kind": "user", "text": ("delayed " if fault == "pending-ok" else "reply ") + "a" * 32}
            assert len(snapshot["records"]) == (1 if fault == "pending-ok" else 2)
        else:
            with pytest.raises(asyncio.CancelledError if fault.endswith("cancel") else RuntimeError) as failure:
                managed_reply_observation({}, target, "LMUX_REPLY_" + "a" * 32)
            if fault == "attach-lost":
                assert isinstance(failure.value.__cause__, TimeoutError)
                assert str(failure.value.__cause__) == "attachment accepted but response lost"
        assert events.index("attach") < events.index("connection-close")
        assert events.index("connection-close") < events.index("journal-close") < events.index("namespace-close")
        assert ("detach" in events) is (fault != "attach-lost")
    elif fault is None:
        result = managed_read_observation({}, "first-member", native_identity=identities)
        assert identities == [native]
        assert result["members"] == [{"memberId": "member-1", "sessionId": "session-1"}]
        assert events.index("connection-close") < events.index("journal-close") < events.index("namespace-close")
    else:
        with pytest.raises(asyncio.CancelledError if fault.endswith("cancel") else RuntimeError) as failure:
            managed_read_observation({}, "first-member", native_identity=identities)
        if fault in {"native-missing", "native-replaced"}:
            assert isinstance(failure.value.__cause__, AssertionError)
        assert identities == []
    if fault in {"connection-close", "history-close", "warm-close"}:
        assert retained["connection"].cleanup_pending
        assert "journal-close" not in events and "namespace-close" not in events
    elif fault == "journal-close":
        assert not retained["journal"].closed and "namespace-close" not in events
    elif fault == "namespace-close":
        assert retained["namespace"].cleanup_pending
    else:
        assert not retained["namespace"].cleanup_pending
    assert ("hard-exit" in events) is (fault in {"connection-close", "history-close", "warm-close", "journal-close", "namespace-close"})
