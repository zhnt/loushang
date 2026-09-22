import asyncio
import json
import sys
from io import StringIO
from time import monotonic
from types import SimpleNamespace

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import (
    ManagedHandoffPhaseV1,
    ManagedInstanceRefV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.discovery import (
    ManagedDiscoverySnapshotV1,
    ManagedServiceObservationV1,
)
from loushang.coding.cli import lmux
from loushang.coding.cli import lmux_stop_all as module

from .test_lmux_command import managed_cli as managed_cli
from .test_lmux_status import namespace as namespace
from .test_lmux_status import pytestmark as pytestmark


@pytest.mark.parametrize("args", [["stop", "--all"], ["stop", "--all", "--server", "a" * 64, "--yes"]])
def test_invalid_batch_flags_before_defaults(monkeypatch, args):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **kw: pytest.fail("default lookup"))
    with pytest.raises(SystemExit) as error:
        lmux.main(args)
    assert error.value.code == 2


@pytest.fixture
def batch(namespace, monkeypatch):
    events, results = [], []
    behavior = {}
    observations = []
    for index in range(3):
        service = ManagedServiceKeyV1("coding", f"/workspace-{index}")
        instance = ManagedInstanceRefV1(namespace.namespace.namespace_key, service.service_id, str(index) * 32)
        observations.append(ManagedServiceObservationV1(service, instance, 1,
            ManagedHandoffPhaseV1.PROVISIONAL, False, False))

    class Journal:
        def __init__(self, registry, ns, service, path, **kwargs):
            self.service = service
            events.append(("construct", service.service_id))

        def open(self, **kwargs):
            events.append(("open", self.service.service_id))

        def close(self):
            events.append(("journal_close", self.service.service_id))

    class Stopper:
        def __init__(self, journal, ns, service, instance, **kwargs):
            self.instance = instance
            self.service = service

        async def run(self, *, deadline):
            events.append(("run", self.instance))
            action = behavior.get(self.service.service_id)
            if action is not None:
                await action()

        async def close(self):
            events.append(("stopper_close", self.service.service_id))

    monkeypatch.setattr(module, "ManagedServiceJournalV1", Journal)
    monkeypatch.setattr(module, "ManagedServiceStopOperationV1", Stopper)
    owner = module.StopAll(SimpleNamespace(registry=object()), namespace,
        ManagedDiscoverySnapshotV1(tuple(observations), ()), deadline=monotonic() + 30, emit=results.append)
    return owner, behavior, events, results


def test_partial_failure_keeps_later_frozen_targets_and_closes_all(batch):
    owner, behavior, events, results = batch

    async def fail():
        raise ManagedStorageError("conflict")

    behavior[owner.entries[0].observation.service.service_id] = fail

    async def scenario():
        try:
            with pytest.raises(ManagedStorageError):
                await owner.run()
        finally:
            await owner.close()

    asyncio.run(scenario())
    assert [result["status"] for result in results] == ["failed", "stopped", "stopped"]
    assert [item[1] for item in events if item[0] == "run"] == [entry.observation.instance for entry in owner.entries]
    assert len([item for item in events if item[0] == "journal_close"]) == 3
    assert not owner.cleanup_pending


def test_shared_deadline_does_not_admit_later_entries(batch, monkeypatch):
    owner, behavior, events, results = batch

    async def expire():
        monkeypatch.setattr(module, "monotonic", lambda: owner.deadline + 1)

    behavior[owner.entries[0].observation.service.service_id] = expire

    async def scenario():
        try:
            with pytest.raises(ManagedStorageError):
                await owner.run()
        finally:
            await owner.close()

    asyncio.run(scenario())
    assert len([item for item in events if item[0] == "construct"]) == 1
    assert [result["status"] for result in results] == ["stopped", "not_attempted", "not_attempted"]


def test_cancellation_does_not_stop_next_instance(batch):
    owner, behavior, events, _ = batch

    async def cancel():
        raise asyncio.CancelledError()

    behavior[owner.entries[0].observation.service.service_id] = cancel

    async def scenario():
        try:
            with pytest.raises(asyncio.CancelledError):
                await owner.run()
        finally:
            await owner.close()

    asyncio.run(scenario())
    assert len([item for item in events if item[0] == "run"]) == 1
    assert not owner.cleanup_pending


def test_close_starts_all_original_tasks_even_when_first_hangs(batch):
    owner, _, _, _ = batch

    async def scenario():
        release = asyncio.Event()
        seen = []

        class Stopper:
            def __init__(self, index):
                self.index = index

            async def close(self):
                seen.append(self.index)
                if self.index == 0:
                    await release.wait()

        for index, entry in enumerate(owner.entries):
            entry.stopper = Stopper(index)
        with pytest.raises(ManagedStorageError, match="busy"):
            await owner.close()
        assert seen == [0, 1, 2] and owner.cleanup_pending
        original = owner.entries[0].closing
        release.set()
        await owner.close()
        assert owner.entries[0].closing is original and not owner.cleanup_pending

    asyncio.run(scenario())


def test_missing_namespace_batch_does_not_create(namespace, tmp_path, capsys):
    assert lmux.main(["stop", "--all", "--yes"]) == 1
    assert capsys.readouterr().err == "lmux_not_found\n"
    assert not tuple(tmp_path.iterdir())


def test_confirmation_freezes_services_and_skips_absent_instances(namespace, tmp_path, monkeypatch, capsys):
    from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
    from loushang.apphost.managed.registry import ManagedMuxReservationV1

    admission = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime),
                                            create_if_missing=True)
    try:
        registry = admission.open(deadline=monotonic() + 5)
        service = ManagedServiceKeyV1("coding", str(tmp_path))
        registry.reserve_mux(ManagedMuxReservationV1("first", service, "b" * 32))
        late = ManagedServiceKeyV1("coding", str(tmp_path / "late"))

        class Confirm(StringIO):
            def isatty(self):
                return True

            def readline(self, *args):
                registry.reserve_mux(ManagedMuxReservationV1("late", late, "e" * 32))
                return "yes\n"

        monkeypatch.setattr(sys, "stdin", Confirm())
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert lmux.main(["stop", "--all"]) == 0
        output = capsys.readouterr().out
        assert late.service_id not in output
        assert output.count('"status": "skipped"') == 1
        assert '"reason": "no_instance_at_snapshot"' in output
        assert registry.resolve("first") is not None and registry.resolve("late") is not None
    finally:
        admission.close()


def test_two_muxes_share_one_real_batch_stop(managed_cli, monkeypatch, capsys):
    from concurrent.futures import ThreadPoolExecutor

    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli

    async def screen(shell, **kwargs):
        await shell.start()
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "one"]) == 0
    native = commands[-1].creation._coordinator._starter._process
    assert lmux.main(["new", "-s", "two"]) == 0
    capsys.readouterr()
    # This fixture is the original Popen parent; the stop client cannot reap it.
    with ThreadPoolExecutor(max_workers=1) as pool:
        reaped = pool.submit(native._process.wait, 20)
        assert lmux.main(["stop", "--all", "--yes"]) == 0
        assert reaped.result(timeout=2) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    preview, stopped = output
    assert preview["services"][0]["muxes"] == ["one", "two"]
    assert len(preview["services"]) == 1 and stopped["status"] == "stopped"
    assert stopped["instanceId"] == preview["services"][0]["instanceId"]


def test_failed_cleanup_retries_original_owner_without_stop_replay(batch):
    owner, _, events, _ = batch

    class Journal:
        def __init__(self):
            self.calls = 0

        def close(self):
            self.calls += 1
            if self.calls == 1:
                raise ManagedStorageError("busy")

    journal = Journal()
    owner.entries[0].journal = journal

    async def scenario():
        with pytest.raises(ManagedStorageError):
            await owner.close()
        assert owner.entries[0].journal is journal
        await owner.close()
        assert journal.calls == 2 and not owner.cleanup_pending

    asyncio.run(scenario())
    assert events == []


def test_cancelled_close_waiter_retains_original_cleanup_task(batch):
    owner, _, _, _ = batch

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Stopper:
            async def close(self):
                entered.set()
                await release.wait()

        owner.entries[0].stopper = Stopper()
        waiter = asyncio.create_task(owner.close())
        await entered.wait()
        original = owner.entries[0].closing
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert original is not None and not original.done()
        release.set()
        await owner.close()
        assert owner.entries[0].closing is original and not owner.cleanup_pending

    asyncio.run(scenario())


def test_confirmation_rejects_successor_without_native_or_stop_effect(namespace, tmp_path, monkeypatch, capsys):
    from loushang.apphost.managed.contracts import ManagedStopEvidenceV1
    from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
    from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
    from loushang.apphost.managed.registry import ManagedMuxReservationV1
    from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
    from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1

    admission = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime),
                                            create_if_missing=True)
    service_owner = None
    successor = []
    try:
        registry = admission.open(deadline=monotonic() + 5)
        service = ManagedServiceKeyV1("coding", str(tmp_path))
        registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
        service_owner = ManagedServiceAdmissionV1(admission, service)
        journal = service_owner.open(deadline=monotonic() + 5)
        first = journal.prepare("c" * 32, expected=None)

        class Confirm(StringIO):
            def isatty(self):
                return True

            def readline(self, *args):
                # Legitimate durable transition with no launched native process.
                journal.abort(first.handoff.instance, "c" * 32)
                settled = journal.record_stop_evidence(ManagedStopEvidenceV1(first.handoff.instance, True, True, True))
                successor.append(journal.prepare("d" * 32, expected=settled))
                return "yes\n"

        def forbidden(*args, **kwargs):
            pytest.fail("stale confirmation admitted a native or stop effect")

        monkeypatch.setattr(ManagedServiceStopOperationV1, "_admit", forbidden)
        monkeypatch.setattr(ManagedServiceJournalV1, "request_stop", forbidden)
        monkeypatch.setattr(sys, "stdin", Confirm())
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert lmux.main(["stop", "--all"]) == 1
        output = capsys.readouterr().out
        assert '"code": "conflict"' in output
        assert first.handoff.instance.instance_id in output
        assert successor[0].handoff.instance.instance_id not in output
        assert journal.read() == successor[0] and not successor[0].handoff.stop_requested
    finally:
        if service_owner is not None:
            service_owner.close()
        admission.close()


@pytest.mark.parametrize("answer", ["\n", "no\n", "yes", "yesxxxxx\n"])
def test_batch_cancel_has_no_stop_owner(namespace, monkeypatch, answer):
    from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
    from loushang.coding.cli import lmux_command

    admission = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime),
                                            create_if_missing=True)
    try:
        admission.open(deadline=monotonic() + 5)
    finally:
        admission.close()
    stdin = StringIO(answer)
    monkeypatch.setattr(stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(lmux_command, "StopAll", lambda *a, **kw: pytest.fail("cancel allocated batch"))
    assert lmux.main(["stop", "--all"]) == 0
