"""Retained witness protocol controls; native CLI composition is separate."""

from __future__ import annotations

import json
import os
import runpy
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.coding import _hosted_darwin_witness as module


def _fixture(root):
    calls, exits = [], [None]
    process = SimpleNamespace(pid=1234, wait=lambda **kw: calls.append(("wait", kw)) or 7)
    api = SimpleNamespace(modes=lambda: [1, 2], exited_unreaped=lambda pid: exits[0])
    retained = module.RetainedWitness(
        root, ["actual-cli"], api=api,
        spawn=lambda args: calls.append(("spawn", args)) or process,
    )
    return retained, calls, exits


def test_witness_requires_observed_exit_reap_and_separate_release(tmp_path):
    retained, calls, exits = _fixture(tmp_path)
    assert not retained.step()
    assert json.loads((tmp_path / "started").read_text())["pid"] == 1234
    (tmp_path / "sample.request").write_text("1234")
    assert not retained.step()
    assert json.loads((tmp_path / "sample").read_text()) == {"modes": [1, 2]}
    exits[0] = 7
    assert not retained.step()
    assert retained.phase == "awaiting-reap"
    assert calls == [("spawn", ["actual-cli"])]
    assert json.loads((tmp_path / "exited-retained").read_text()) == {"code": 7, "modes": [1, 2]}
    (tmp_path / "reap.request").write_text("1234")
    assert not retained.step()
    assert calls[-1] == ("wait", {"timeout": 0})
    assert retained.phase == "awaiting-release"
    (tmp_path / "release").write_text("1234")
    assert retained.step()
    assert sum(name == "wait" for name, _ in calls) == 1


@pytest.mark.parametrize("name", ["reap.request", "release"])
@pytest.mark.parametrize("started", [False, True])
def test_witness_rejects_early_commands_without_reaping(tmp_path, name, started):
    retained, calls, _ = _fixture(tmp_path)
    if started:
        retained.step()
    (tmp_path / name).write_text("1234")
    with pytest.raises(RuntimeError):
        retained.step()
    assert all(call[0] != "wait" for call in calls)
    assert len(calls) == int(started)


@pytest.mark.parametrize("value", ["1235", "1234\n", '{"pid":1234}', "1" * 200])
def test_witness_rejects_wrong_reap_identity(tmp_path, value):
    retained, calls, exits = _fixture(tmp_path)
    retained.step()
    exits[0] = 7
    retained.step()
    (tmp_path / "reap.request").write_text(value)
    with pytest.raises(RuntimeError, match="identity"):
        retained.step()
    assert len(calls) == 1


@pytest.mark.parametrize("receipt", ["started", "exited-retained", "reaped"])
def test_witness_publication_retry_keeps_original_child_and_exit_proof(tmp_path, monkeypatch, receipt):
    retained, calls, exits = _fixture(tmp_path)
    publish = module.publish
    failed = []

    def fail_once(root, name, value):
        if name == receipt and not failed:
            failed.append(name)
            raise module.ReceiptIOError("receipt temporarily unavailable")
        publish(root, name, value)

    monkeypatch.setattr(module, "publish", fail_once)
    if receipt != "started":
        retained.step()
        exits[0] = 7
    if receipt == "reaped":
        retained.step()
        (tmp_path / "reap.request").write_text("1234")
    with pytest.raises(OSError):
        retained.step()
    assert not retained.step()
    assert failed == [receipt]
    assert sum(name == "spawn" for name, _ in calls) == 1
    assert sum(name == "wait" for name, _ in calls) == (receipt == "reaped")


def test_witness_never_retries_ambiguous_spawn(tmp_path):
    retained, calls, _ = _fixture(tmp_path)

    def interrupted(args):
        calls.append(("ambiguous", args))
        raise KeyboardInterrupt

    retained.spawn = interrupted
    with pytest.raises(KeyboardInterrupt):
        retained.step()
    with pytest.raises(RuntimeError, match="spawn outcome unknown"):
        retained.step()
    assert len(calls) == 1


def test_published_sample_cannot_block_later_exit_observation(tmp_path, monkeypatch):
    retained, calls, exits = _fixture(tmp_path)
    publish, samples = module.publish, []

    def sample_once(root, name, value):
        if name == "sample":
            samples.append(name)
            if len(samples) > 1:
                raise module.ReceiptIOError("sample no longer writable")
        publish(root, name, value)

    monkeypatch.setattr(module, "publish", sample_once)
    retained.step()
    (tmp_path / "sample.request").write_text("1234")
    retained.step()
    exits[0] = 7
    retained.step()
    (tmp_path / "reap.request").write_text("1234")
    retained.step()
    (tmp_path / "release").write_text("1234")
    assert retained.step()
    assert samples == ["sample"]
    assert sum(name == "wait" for name, _ in calls) == 1


def test_witness_loop_never_recovers_native_observation_failure_as_success(tmp_path, monkeypatch):
    retained, calls, _ = _fixture(tmp_path)
    observations, sleeps = [], []

    def observe(pid):
        observations.append(pid)
        if len(observations) == 1:
            raise OSError("native observation unknown")
        return 7

    class EndControl(BaseException):
        pass

    def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 3:
            raise EndControl

    retained.api.exited_unreaped = observe
    monkeypatch.setattr(module.time, "sleep", sleep)
    previous = signal.getsignal(signal.SIGINT)
    try:
        with pytest.raises(EndControl):
            module.witness(tmp_path, retained.arguments, api=retained.api, spawn=retained.spawn)
    finally:
        signal.signal(signal.SIGINT, previous)
    assert len(observations) == 1
    assert len(calls) == 1
    assert (tmp_path / "failed").exists()
    assert not (tmp_path / "exited-retained").exists()
    assert not (tmp_path / "reaped").exists()


def test_witness_loop_retries_receipt_stat_failure_without_respawn(tmp_path, monkeypatch):
    retained, calls, exits = _fixture(tmp_path)
    exists, failures = Path.exists, []

    def stat_once(path):
        if path.name == "reap.request" and not failures:
            failures.append(path.name)
            raise OSError("stat temporarily unavailable")
        return exists(path)

    def tick(delay):
        if exists(tmp_path / "reaped"):
            (tmp_path / "release").write_text("1234")
        elif exists(tmp_path / "exited-retained"):
            (tmp_path / "reap.request").write_text("1234")
        elif exists(tmp_path / "started"):
            exits[0] = 7

    monkeypatch.setattr(Path, "exists", stat_once)
    monkeypatch.setattr(module.time, "sleep", tick)
    previous = signal.getsignal(signal.SIGINT)
    try:
        assert module.witness(tmp_path, retained.arguments, api=retained.api, spawn=retained.spawn) == 0
    finally:
        signal.signal(signal.SIGINT, previous)
    assert failures == ["reap.request"]
    assert calls == [("spawn", ["actual-cli"]), ("wait", {"timeout": 0})]


@pytest.mark.skipif(os.name != "posix", reason="POSIX registry admission")
@pytest.mark.parametrize("fault", [None, "missing", "sealed", "unknown", "unregistered"])
def test_witness_entry_requires_registered_open_scope_and_strips_product_control(tmp_path, fault):
    ledger = runpy.run_path(str(Path(module.__file__).resolve().parents[2] / "scripts/dev/_evidence_observation.py"))
    ticket = ledger["create"](tmp_path)
    key = ledger["ENVIRONMENT_KEY"]
    environment = {key: str(ticket["path"]), key.lower(): "forged", "KEEP": "value"}
    if fault == "missing":
        environment.pop(key)
    elif fault == "sealed":
        with pytest.raises(RuntimeError):
            ledger["require_closed"](ticket)
    elif fault == "unknown":
        ledger["unknown"](ticket["path"])
    elif fault == "unregistered":
        path = ticket["path"].with_name("0" * 32 + ".json")
        path.write_text(json.dumps({"token": "0" * 32, "phase": "open"}))
        environment[key] = str(path)
    if fault:
        with pytest.raises((RuntimeError, KeyError)):
            module._product_environment(environment)
    else:
        assert module._product_environment(environment) == {"KEEP": "value"}


def test_protocol_cleanup_retries_timeouts_before_releasing_owner(tmp_path, monkeypatch):
    from tests.coding import _hosted_terminal
    from tests.coding import test_hosted_darwin_primitives as primitives

    calls, waits = [], []
    previous = signal.getsignal(signal.SIGINT)
    (tmp_path / "started").write_text('{"pid":1234}')
    (tmp_path / "exited-retained").touch()
    (tmp_path / "reaped").touch()

    def until(predicate):
        assert signal.getsignal(signal.SIGINT) != previous
        calls.append("until")
        if len(calls) == 1:
            raise TimeoutError("transient barrier failure")
        assert predicate()

    def wait(**kwargs):
        waits.append("wait")
        if len(waits) == 1:
            raise TimeoutError("transient witness wait failure")
        return 0

    monkeypatch.setattr(primitives, "_until", until)
    monkeypatch.setattr(_hosted_terminal, "process_table", lambda: {})
    monkeypatch.setitem(globals(), "print", lambda *a, **kw: (_ for _ in ()).throw(ValueError("closed stdout")))
    driver = SimpleNamespace(wait=wait, close=lambda: calls.append("close"))
    assert _settle_protocol_control(driver, tmp_path) == (1234, 0)
    assert waits == ["wait", "wait"]
    assert calls[-1] == "close"
    assert signal.getsignal(signal.SIGINT) == previous


def _settle_protocol_control(driver, root):
    from tests.coding._hosted_terminal import process_table
    from tests.coding.test_hosted_darwin_primitives import _until

    previous = signal.signal(signal.SIGINT, lambda *_: None)
    try:
        while True:
            try:
                _until(lambda: (root / "started").exists())
                child = json.loads((root / "started").read_text())["pid"]
                if not (root / "exited-retained").exists():
                    driver.write("x")
                    _until(lambda: (root / "exited-retained").exists())
                (root / "reap.request").write_text(str(child))
                _until(lambda: (root / "reaped").exists())
                _until(lambda child=child: child not in process_table())
                (root / "release").write_text(str(child))
                code = driver.wait(timeout=5)
                driver.close()
                return child, code
            except (Exception, KeyboardInterrupt):
                with suppress(OSError, ValueError):
                    print("witness protocol cleanup pending; owner retained", flush=True)
                time.sleep(0.01)
    finally:
        signal.signal(signal.SIGINT, previous)


@pytest.mark.skipif(os.name != "posix", reason="POSIX registry ancestry")
@pytest.mark.parametrize("sealed", [False, True])
def test_witness_entry_allows_unused_supervisor_but_not_sealed_ancestor(tmp_path, sealed):
    ledger = runpy.run_path(str(Path(module.__file__).resolve().parents[2] / "scripts/dev/_evidence_observation.py"))
    outer = ledger["create"](tmp_path, observation=False)
    inner = ledger["create"](tmp_path, parent=outer["path"], observation=True)
    environment = {ledger["ENVIRONMENT_KEY"]: str(inner["path"]), "KEEP": "value"}
    if sealed:
        with pytest.raises(RuntimeError):
            ledger["require_closed"](outer)
        with pytest.raises(RuntimeError, match="unavailable"):
            module._product_environment(environment)
    else:
        assert module._product_environment(environment) == {"KEEP": "value"}


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux WNOWAIT/PTY protocol control")
@pytest.mark.parametrize("interrupt", [False, True])
def test_witness_retains_real_child_exit_and_terminal_until_authorized_reap(tmp_path, interrupt):
    from tests.coding._hosted_terminal import process_table
    from tests.coding.test_hosted_darwin_primitives import _until
    from tests.tui.terminal_process_support import spawn_terminal_process

    child_code = (
        "import os,sys,termios,tty\n"
        "baseline=termios.tcgetattr(0)\n"
        "code=0\n"
        "try:\n"
        "    tty.setraw(0)\n"
        "    os.write(1,b'child-ready')\n"
        "    assert os.read(0,1)==b'x'\n"
        "except KeyboardInterrupt:\n"
        "    code=130\n"
        "finally:\n"
        "    termios.tcsetattr(0,termios.TCSANOW,baseline)\n"
        "sys.exit(code)\n"
    )
    driver_code = (
        "import os,runpy,termios\nfrom pathlib import Path\n"
        f"definitions=runpy.run_path({str(Path(module.__file__))!r})\n"
        "class Api:\n"
        "    def modes(self):\n"
        "        attrs=termios.tcgetattr(0)\n"
        "        attrs[6]=[v[0] if isinstance(v,bytes) else v for v in attrs[6]]\n"
        "        return attrs\n"
        "    def exited_unreaped(self,pid):\n"
        "        info=os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)\n"
        "        return None if info is None else info.si_status\n"
        f"raise SystemExit(definitions['witness'](Path({str(tmp_path)!r}),"
        f"{[sys.executable, '-I', '-S', '-c', child_code]!r},api=Api()))\n"
    )
    driver = spawn_terminal_process(
        [sys.executable, "-I", "-S", "-c", driver_code],
        cwd=tmp_path, env=os.environ, columns=80, rows=24,
    )
    child = None
    try:
        driver.read_until(lambda out: "child-ready" in out, timeout=5)
        _until(lambda: (tmp_path / "started").exists())
        started = json.loads((tmp_path / "started").read_text())
        child = started["pid"]
        (tmp_path / "sample.request").write_text(str(child))
        _until(lambda: (tmp_path / "sample").exists())
        assert json.loads((tmp_path / "sample").read_text())["modes"] != started["baseline"]
        if interrupt:
            # The unreleased witness reserves this owned group identity. Its
            # caught handler must not become SIG_IGN in the exec'd child.
            assert os.getpgid(started["witness"]) == started["witness"]
            os.killpg(started["witness"], signal.SIGINT)
        else:
            driver.write("x")
        _until(lambda: (tmp_path / "exited-retained").exists())
        finished = json.loads((tmp_path / "exited-retained").read_text())
        assert finished == {"code": 130 if interrupt else 0, "modes": started["baseline"]}
        assert process_table()[child][0] == started["witness"]
        assert "Z" in process_table()[child][1]
        assert driver.is_alive()
    finally:
        # This fixed child has no descendants. Keep the actual witness until
        # its child exits/reaps, even when an assertion above fails.
        settled_child, code = _settle_protocol_control(driver, tmp_path)
    assert settled_child == child and code == 0
    assert child not in process_table()
