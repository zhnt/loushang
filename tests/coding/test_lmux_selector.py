import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import StringIO
from time import monotonic

import pytest

from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedInstanceRefV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.discovery import ManagedMuxObservationV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.coding.cli import lmux
from loushang.coding.cli import lmux_command as module

from .test_lmux_command import managed_cli as managed_cli


def observation(name):
    reservation = ManagedMuxReservationV1(name, ManagedServiceKeyV1("coding", "/workspace"), "a" * 32)
    return ManagedMuxObservationV1(reservation, None, None, None, False, False)


def committed_observation(name="dev"):
    item = observation(name)
    return replace(item, instance=ManagedInstanceRefV1("b" * 64, item.service.service_id, "c" * 32),
                   revision=1, recorded_phase=ManagedHandoffPhaseV1.COMMITTED)


def test_sole_committed_candidate_is_only_a_selection():
    item = committed_observation()
    assert module._single_candidate((item,)) is item


@pytest.mark.parametrize("case", ["empty", "multiple", "pending", "provisional", "aborting", "stop", "clean", "product", "full_page"])
def test_automatic_selection_rejects_ineligible_observations(monkeypatch, case):
    item = committed_observation()
    page = (item,)
    if case == "empty":
        page = ()
    elif case == "multiple":
        page = (item, observation("pending"))
    elif case == "pending":
        page = (observation("pending"),)
    elif case in {"provisional", "aborting"}:
        page = (replace(item, recorded_phase=ManagedHandoffPhaseV1(case)),)
    elif case in {"stop", "clean"}:
        page = (replace(item, stop_requested=True, cleanly_stopped=case == "clean"),)
    elif case == "product":
        service = ManagedServiceKeyV1("work", "/workspace")
        page = (replace(item, reservation=replace(item.reservation, service=service),
                        instance=replace(item.instance, service_id=service.service_id)),)
    elif case == "full_page":
        monkeypatch.setattr(module, "MAX_PAGE", 1)
    assert module._single_candidate(page) is None


def select(monkeypatch, text, observations):
    from loushang.apphost.managed.mux_probe import (
        ManagedMuxProbeResultV1,
        ManagedMuxProbeSnapshotV1,
    )

    monkeypatch.setattr(module, "MAX_PAGE", 2)
    command = object.__new__(module.ManagedMuxCommand)
    command.stdin, command.stdout = StringIO(text), StringIO()
    command.deadline = 0.0
    monkeypatch.setattr(command, "_probe_snapshot", lambda: pytest.fail("paging must not probe"))
    rows = tuple(ManagedMuxProbeResultV1(item, "unknown") for item in observations)
    result = command._select_probe(ManagedMuxProbeSnapshotV1(rows, True))
    return result, command.stdout.getvalue()


def test_next_page_returns_original_displayed_observation(monkeypatch):
    last = observation("z")
    result, output = select(monkeypatch, "n\n1\n", (observation("a"), observation("b"), last))
    assert result is last
    assert '"name": "z"' in output and '"status": "unknown"' in output


def test_restart_page_and_cancel(monkeypatch):
    result, _ = select(monkeypatch, "n\nr\n\n", (
        observation("a"), observation("b"), observation("z"),
    ))
    assert result is None


def test_exact_full_final_page_stays_then_allows_selection(monkeypatch):
    first = observation("a")
    result, output = select(monkeypatch, "n\n1\n", (first, observation("b")))
    assert result is first and "No more muxes" in output


@pytest.mark.parametrize("text", ["3\n", "x\n", "1" * 40 + "\n"])
def test_invalid_selection_rejects_without_page_io(monkeypatch, text):
    with pytest.raises(ManagedContractError):
        select(monkeypatch, text, (observation("a"),))


def test_bare_pending_snapshot_cancel_never_creates_main(managed_cli, monkeypatch):
    _, commands = managed_cli
    with monkeypatch.context() as patch:
        patch.setattr(module, "_execute", lambda *args, **kwargs: 1)
        assert lmux.main(["new", "-s", "pending"]) == 1
    monkeypatch.setattr(sys, "stdin", StringIO("\n"))
    assert lmux.main([]) == 0
    command = commands[-1]
    assert [(row.observation.name, row.status) for row in command.probe_result.results] == [("pending", "unknown")]
    assert not command.probe.cleanup_pending
    assert command.creation is command.connection is command.starter is None
    assert command.native_closed and not command.active


def test_probe_selector_pages_only_frozen_values(monkeypatch):
    from loushang.apphost.managed.mux_probe import (
        ManagedMuxProbeResultV1,
        ManagedMuxProbeSnapshotV1,
    )

    monkeypatch.setattr(module, "MAX_PAGE", 2)
    command = object.__new__(module.ManagedMuxCommand)
    command.stdin, command.stdout = StringIO("n\nr\nn\n1\n"), StringIO()
    monkeypatch.setattr(command, "_probe_snapshot", lambda: pytest.fail("paging must not probe"))
    rows = tuple(ManagedMuxProbeResultV1(observation(name), "unknown") for name in ("a", "b", "z"))
    assert command._select_probe(ManagedMuxProbeSnapshotV1(rows, True)) == rows[2].observation
    assert command.deadline > monotonic()


def test_probe_selector_refresh_replaces_snapshot(monkeypatch):
    from loushang.apphost.managed.mux_probe import (
        ManagedMuxProbeResultV1,
        ManagedMuxProbeSnapshotV1,
    )

    command = object.__new__(module.ManagedMuxCommand)
    command.stdin, command.stdout = StringIO("f\n1\n"), StringIO()
    original = ManagedMuxProbeSnapshotV1((ManagedMuxProbeResultV1(observation("old"), "unknown"),), True)
    refreshed = ManagedMuxProbeSnapshotV1((ManagedMuxProbeResultV1(observation("new"), "unknown"),), True)
    calls = []
    monkeypatch.setattr(command, "_probe_snapshot", lambda: calls.append(1) or refreshed)
    assert command._select_probe(original).name == "new"
    assert calls == [1]


def test_probe_selector_last_page_next_does_not_fail_or_probe(monkeypatch):
    from loushang.apphost.managed.mux_probe import (
        ManagedMuxProbeResultV1,
        ManagedMuxProbeSnapshotV1,
    )

    command = object.__new__(module.ManagedMuxCommand)
    command.stdin, command.stdout = StringIO("n\n\n"), StringIO()
    monkeypatch.setattr(command, "_probe_snapshot", lambda: pytest.fail("last page must not probe"))
    snapshot = ManagedMuxProbeSnapshotV1((ManagedMuxProbeResultV1(observation("pending"), "unknown"),), True)
    assert command._select_probe(snapshot) is None
    assert "staying on this page" in command.stdout.getvalue()
    assert "n next page" not in command.stdout.getvalue()


@pytest.mark.parametrize("args", [[], ["attach"]])
def test_single_candidate_reconnects_without_reading_selection(managed_cli, tmp_path, monkeypatch, args):
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    attached = []

    async def screen(shell, **kwargs):
        await shell.start()
        attached.append(shell.state)
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(module.ManagedMuxCommand, "_select_probe", lambda *a: pytest.fail("unexpected selector"))
    assert lmux.main(args) == 0, repr(commands[-1].failure)
    assert len(attached) == 2
    assert commands[-1].creation is commands[-1].starter is None
    assert commands[-1].native_closed and not commands[-1].active
    assert not list(elsewhere.iterdir())


def test_only_live_mux_among_multiple_services_attaches_without_selector(managed_cli, tmp_path, monkeypatch):
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    attached = []

    async def screen(shell, **kwargs):
        await shell.start()
        attached.append(shell.state)
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "live"]) == 0
    live_process = commands[-1].creation._coordinator._starter._process
    other = tmp_path / "other"
    other.mkdir()
    assert lmux.main(["new", "-s", "stopped", "--workspace", str(other)]) == 0
    stopped_process = commands[-1].creation._coordinator._starter._process
    stopped_service = ManagedServiceKeyV1("coding", str(other)).service_id
    # This test remains the original Popen parent. Reap its own child while the
    # unrelated stop operation waits for the real process group to disappear.
    with ThreadPoolExecutor(max_workers=1) as pool:
        reaped = pool.submit(stopped_process._process.wait, 20)
        assert lmux.main(["stop", "--server", stopped_service, "--yes"]) == 0, repr(commands[-1].failure)
        assert reaped.result(timeout=2) == 0
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(module.ManagedMuxCommand, "_select_probe", lambda *a: pytest.fail("unique live mux opened selector"))
    monkeypatch.setattr(module.ManagedMuxCommand, "_select_probe", lambda *a: pytest.fail("unique live mux opened selector"))
    assert lmux.main(["attach"]) == 0, repr(commands[-1].failure)
    assert len(attached) == 3
    assert commands[-1].target == "live"
    assert commands[-1].creation is commands[-1].starter is None
    assert live_process._process.poll() is None
    assert commands[-1].native_closed and not commands[-1].active
    assert not tuple(elsewhere.iterdir())


@pytest.mark.parametrize("args", [[], ["attach"]])
def test_single_candidate_handshake_failure_does_not_restart_or_reselect(managed_cli, monkeypatch, args):
    from loushang.apphost.managed import connection
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    entered = []

    async def screen(shell, **kwargs):
        await shell.start()
        entered.append(shell.state)
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0
    attempts = []

    async def reject_handshake(client):
        attempts.append(client)
        raise connection.AppConnectionClosedError()

    monkeypatch.setattr(connection.LocalAppClientConnectionV1, "start", reject_handshake)
    monkeypatch.setattr(module.ManagedMuxCommand, "_select_probe", lambda *a: pytest.fail("unexpected selector"))
    assert lmux.main(args) == 1
    command = commands[-1]
    assert len(attempts) == len(entered) == 1
    assert command.creation is command.starter is None
    assert command.connection is not None and not command.connection.cleanup_pending
    assert command.native_closed and not command.active
