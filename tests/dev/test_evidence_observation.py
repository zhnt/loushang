"""An empty process tree cannot discharge missing native observations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_evidence_process import supervisor

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX observation registry")


@pytest.mark.parametrize("phase", ["open", "admitted", "unknown", "missing", "corrupt", "foreign",
    "duplicate-phase", "duplicate-token", "duplicate-registry-field"])
def test_observation_debt_precedes_every_cleanup_action(tmp_path, monkeypatch, phase):
    ledger = supervisor._support("_evidence_observation")
    ticket = ledger.create(tmp_path)
    if phase == "admitted":
        ledger.admit(ticket["path"], 1234, [1235])
    elif phase == "unknown":
        ledger.unknown(ticket["path"])
    elif phase == "missing":
        ticket["path"].unlink()
    elif phase == "corrupt":
        ticket["path"].write_text("{")
    elif phase == "foreign":
        value = json.loads(ticket["path"].read_text())
        value.update(token="foreign", phase="closed", controller=1234, children=[1235])
        ticket["path"].write_text(json.dumps(value))
    elif phase.startswith("duplicate"):
        ledger.admit(ticket["path"], 1234, [1235])
        ledger.complete(ticket["path"])
        if phase == "duplicate-registry-field":
            path = ticket["path"].parent / "registry.json"
            path.write_text(path.read_text().replace('"sealed": false', '"sealed": true, "sealed": false'))
        else:
            source = ticket["path"].read_text()
            if phase == "duplicate-phase":
                source = source.replace('"phase": "closed"', '"phase": "admitted", "phase": "closed"')
            else:
                source = source.replace('"token":', '"token": "foreign", "token":')
            ticket["path"].write_text(source)
    events = []
    process = SimpleNamespace(
        pid=1234,
        kill=lambda: events.append("kill"),
        wait=lambda **_: events.append("reap"),
    )
    support = supervisor._support
    monkeypatch.setattr(supervisor, "_support", lambda name: (
        support(name) if name == "_evidence_observation" else
        SimpleNamespace(reclaim_descendants=lambda *a, **k: events.append("scan") or 0)
    ))
    monkeypatch.setattr(supervisor, "_send", lambda *args: events.append("release"))
    with pytest.raises(RuntimeError, match="observation.*pending"):
        supervisor._cleanup(process, None, forced=True, state={"observation": ticket})
    assert not events


def test_observation_requires_admission_and_preserves_unknown_debt(tmp_path):
    ledger = supervisor._support("_evidence_observation")
    ticket = ledger.create(tmp_path)
    with pytest.raises(ValueError):
        ledger.complete(ticket["path"])
    ledger.admit(ticket["path"], 1234, [1235])
    ledger.unknown(ticket["path"])
    with pytest.raises(ValueError):
        ledger.complete(ticket["path"])
    with pytest.raises(RuntimeError, match="observation.*pending"):
        ledger.require_closed(ticket)


def test_observation_closed_receipt_keeps_exact_owner_identity(tmp_path):
    ledger = supervisor._support("_evidence_observation")
    ticket = ledger.create(tmp_path)
    ledger.admit(ticket["path"], 1234, [1235, 1236])
    ledger.complete(ticket["path"])
    ledger.complete(ticket["path"])
    ledger.require_closed(ticket)
    value = json.loads(ticket["path"].read_text())
    assert value == {
        "token": ticket["token"], "phase": "closed", "controller": 1234,
        "children": [1235, 1236],
    }


@pytest.mark.parametrize("child_environment", [{}, {"G17_NATIVE_OBSERVATION": "foreign-ticket"}])
def test_zero_spawn_failure_uses_supervisor_parent_not_child_environment(
    tmp_path, monkeypatch, child_environment,
):
    ledger = supervisor._support("_evidence_observation")
    outer = ledger.create(tmp_path, observation=False)
    monkeypatch.setenv(ledger.ENVIRONMENT_KEY, str(outer["path"]))
    child = tmp_path / "child"
    child.mkdir()
    calls = []

    def fail_spawn(argv, **kwargs):
        calls.append(kwargs["env"][ledger.ENVIRONMENT_KEY])
        with pytest.raises(RuntimeError, match="observation.*pending"):
            ledger.require_closed(outer)
        raise FileNotFoundError("missing interpreter")

    monkeypatch.setattr(supervisor.subprocess, "Popen", fail_spawn)
    with pytest.raises(FileNotFoundError):
        supervisor.run_pytest(
            [sys.executable, "-I", "-m", "pytest"], cwd=child,
            environment=child_environment, timeout=1, observation=True,
        )
    assert len(calls) == 1
    nested = Path(calls[0])
    assert nested.parent == outer["path"].parent and nested != outer["path"]
    assert json.loads(nested.read_text())["phase"] == "aborted"
    ledger.require_closed(outer)
    assert not (child / "native-observations").exists()


@pytest.mark.parametrize("controller,children", [(True, [12]), (1, [12]), (12, []),
    (12, [12]), (12, [13, 13]), (12, [False]), (12, list(range(20, 29)))])
def test_observation_rejects_unbounded_or_ambiguous_process_identity(tmp_path, controller, children):
    ledger = supervisor._support("_evidence_observation")
    ticket = ledger.create(tmp_path)
    with pytest.raises(ValueError):
        ledger.admit(ticket["path"], controller, children)
    assert json.loads(ticket["path"].read_text())["phase"] == "open"


def test_ancestor_retains_nested_observation_after_inner_workspace_is_removed(tmp_path):
    ledger = supervisor._support("_evidence_observation")
    outer = ledger.create(tmp_path, observation=False)
    scratch = tmp_path / "inner-workspace"
    scratch.mkdir()
    inner = ledger.create(scratch, parent=outer["path"])
    assert inner["path"].parent == outer["path"].parent
    scratch.rmdir()
    with pytest.raises(RuntimeError, match="observation.*pending"):
        ledger.require_closed(outer)
    ledger.admit(inner["path"], 1234, [1235])
    ledger.complete(inner["path"])
    ledger.require_closed(outer)
    with pytest.raises(RuntimeError, match="sealed"):
        ledger.create(tmp_path, parent=inner["path"])


def test_close_publication_failure_retains_admission_for_exact_retry(tmp_path, monkeypatch):
    ledger = supervisor._support("_evidence_observation")
    ticket = ledger.create(tmp_path)
    ledger.admit(ticket["path"], 1234, [1235])
    replace = Path.replace
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", lambda *args: (_ for _ in ()).throw(OSError("write-fault")))
        with pytest.raises(OSError):
            ledger.complete(ticket["path"])
    assert Path.replace is replace
    assert json.loads(ticket["path"].read_text())["phase"] == "admitted"
    with pytest.raises(RuntimeError, match="observation.*pending"):
        ledger.require_closed(ticket)
    ledger.complete(ticket["path"])
    ledger.require_closed(ticket)
    with pytest.raises(ValueError):
        ledger.admit(ticket["path"], 2345, [2346])


def test_observation_depth_bound_rejects_before_scope_is_registered(tmp_path):
    ledger = supervisor._support("_evidence_observation")
    root = current = ledger.create(tmp_path, observation=False)
    for _ in range(31):
        current = ledger.create(tmp_path, parent=current["path"], observation=False)
    before = (root["path"].parent / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="ancestry bound"):
        ledger.create(tmp_path, parent=current["path"])
    assert (root["path"].parent / "registry.json").read_bytes() == before
    ledger.require_closed(root)


@pytest.mark.parametrize("winner", ["register", "seal"])
def test_registration_and_ancestor_seal_have_one_interprocess_cut(tmp_path, monkeypatch, winner):
    ledger = supervisor._support("_evidence_observation")
    outer = ledger.create(tmp_path, observation=False)
    script = Path(ledger.__file__)
    worker = r'''
import os, runpy, sys, time
from pathlib import Path
m = runpy.run_path(sys.argv[1])
root, parent, winner = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
def wait(name):
    end = time.monotonic() + 10
    while not (root / name).exists():
        assert time.monotonic() < end
        time.sleep(.01)
publish = m['create'].__globals__['_publish']
def held(path, value):
    publish(path, value)
    if path.name == 'registry.json':
        (root / 'registered').touch()
        wait('release')
if winner == 'register':
    m['create'].__globals__['_publish'] = held
else:
    wait('go')
(root / 'attempt').touch()
try:
    ticket = m['create'](root, parent=parent)
except RuntimeError:
    (root / 'rejected').touch()
else:
    (root / 'spawn-authorized').write_text(str(ticket['path']))
'''
    process = subprocess.Popen([sys.executable, "-I", "-c", worker,
                                str(script), str(tmp_path), str(outer["path"]), winner])

    def wait(name):
        deadline = time.monotonic() + 10
        while not (tmp_path / name).exists():
            assert time.monotonic() < deadline, name
            time.sleep(0.01)

    try:
        if winner == "register":
            wait("registered")
            (tmp_path / "release").touch()
            with pytest.raises(RuntimeError, match="observation.*pending"):
                ledger.require_closed(outer)
        else:
            publish = ledger._publish

            def held(path, value):
                publish(path, value)
                if path.name == "registry.json":
                    (tmp_path / "go").touch()
                    wait("attempt")

            monkeypatch.setattr(ledger, "_publish", held)
            ledger.require_closed(outer)
        assert process.wait(timeout=10) == 0
        assert (tmp_path / "spawn-authorized").exists() == (winner == "register")
        assert (tmp_path / "rejected").exists() == (winner == "seal")
    finally:
        (tmp_path / "release").touch()
        (tmp_path / "go").touch()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
