from __future__ import annotations

import json
import os
import sys
from time import monotonic

import pytest

from loushang.apphost.managed.contracts import (
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
)
from loushang.apphost.managed.defaults import resolve_managed_defaults
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.coding.cli import lmux
from loushang.hosting.service import LinuxServiceObserverV1
from tests.apphost.test_managed_namespace_admission import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed status")


@pytest.fixture
def namespace(tmp_path, monkeypatch):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "linux_machine_key", lambda **kw: "a" * 32)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("LOUSHANG_TMPDIR", raising=False)
    return resolve_managed_defaults()


@pytest.mark.parametrize("args", [["status", "--server", "bad:name"],
    ["status", "-t", "bad:name"], ["status", "-t", "dev", "--server", "a" * 64]])
def test_bad_status_selectors_do_not_create_directories(namespace, tmp_path, args):
    with pytest.raises(SystemExit) as error:
        lmux.main(args)
    assert error.value.code == 2 and not tuple(tmp_path.iterdir())


def test_missing_namespace_status_is_readonly_not_found(namespace, tmp_path, capsys):
    assert lmux.main(["status", "-t", "dev"]) == 1
    captured = capsys.readouterr()
    assert captured.err == "lmux_not_found\n" and not captured.out
    assert not tuple(tmp_path.iterdir())


def test_status_by_name_and_id_from_other_cwd_never_starts(namespace, tmp_path, monkeypatch, capsys):
    admission = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime),
                                             create_if_missing=True)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    try:
        registry = admission.open(deadline=monotonic() + 5)
        registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
    finally:
        admission.close()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    from loushang.coding.cli import lmux_command

    def forbidden(*args, **kwargs):
        pytest.fail("status attempted service activation")

    monkeypatch.setattr(lmux_command, "ManagedServiceCoordinatorV1", forbidden)
    monkeypatch.setattr(lmux_command, "ManagedConnectionLeaseV1", forbidden)
    before = tree(tmp_path)
    assert lmux.main(["status", "-t", "dev"]) == 0
    named = json.loads(capsys.readouterr().out)
    assert named["serviceId"] == service.service_id and named["workspace"] == str(tmp_path)
    assert named["instanceId"] is None and named["recordedPhase"] is None
    assert named["liveStatus"] == "not_probed" and named["observation"] == "recorded_only"
    assert named["temporary"]["actualRoot"] is None
    assert named["paths"]["logs"].endswith(f"/servers/{service.service_id}/logs")
    assert lmux.main(["status", "--server", service.service_id]) == 0
    assert json.loads(capsys.readouterr().out) == named
    assert tree(tmp_path) == before


def test_status_projects_journal_facts_without_readiness_or_mutation(namespace, tmp_path, monkeypatch, capsys):
    admission = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime),
                                             create_if_missing=True)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    registry = admission.open(deadline=monotonic() + 5)
    registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
    service_admission = ManagedServiceAdmissionV1(admission, service)
    journal = service_admission.open(deadline=monotonic() + 5)
    observer = LinuxServiceObserverV1.capture(os.getpid())
    from loushang.coding.cli import lmux_command

    def forbidden(*args, **kwargs):
        pytest.fail("status attempted connection or startup")

    monkeypatch.setattr(lmux_command, "ManagedConnectionLeaseV1", forbidden)
    monkeypatch.setattr(lmux_command, "ManagedServiceCoordinatorV1", forbidden)

    def query(phase, stopped=False, clean=False):
        before = tree(tmp_path)
        assert lmux.main(["status", "--server", service.service_id]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["recordedPhase"] == phase and result["stopRequested"] is stopped
        assert result["cleanlyStopped"] is clean and result["liveStatus"] == "not_probed"
        assert result["observation"] == "recorded_only"
        assert lmux.main(["status"]) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["observation"] == "recorded_only" and summary["liveStatus"] == "not_probed"
        assert len(summary["services"]) == 1
        recorded = summary["services"][0]
        for field in ("serviceId", "instanceId", "revision", "recordedPhase", "stopRequested", "cleanlyStopped"):
            assert recorded[field] == result[field]
        assert tree(tmp_path) == before
        return result

    try:
        state = journal.prepare("c" * 32, expected=None)
        assert query("provisional")["instanceId"] == state.handoff.instance.instance_id
        journal.register_native(state.handoff.instance, "c" * 32, observer.identity)
        journal.commit(state.handoff.instance, "c" * 32, native_identity=observer.identity)
        query("committed")
        journal.request_stop(state.handoff.instance)
        query("committed", stopped=True)
        # Durable fixture facts, not claims that this test's process has exited.
        journal.record_stop_evidence(ManagedStopEvidenceV1(state.handoff.instance, True, True, False))
        query("committed", stopped=True)
        journal.record_stop_evidence(ManagedStopEvidenceV1(state.handoff.instance, True, True, True))
        expected = query("committed", stopped=True, clean=True)
        with registry._database.transaction(write=True) as connection:
            connection.execute("DELETE FROM muxes WHERE service_id=?", (service.service_id,))
        assert query("committed", stopped=True, clean=True) == expected
        assert lmux.main(["status", "-t", "dev"]) == 1
        assert capsys.readouterr().err == "lmux_not_found\n"
    finally:
        observer.close()
        service_admission.close()
        admission.close()
