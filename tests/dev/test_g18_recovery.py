from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/_g18_recovery.py"
SPEC = importlib.util.spec_from_file_location("g18_recovery", SCRIPT)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def state(tmp_path):
    if sys.platform != "linux":
        pytest.skip("Linux-native recovery state, not external-platform acceptance")
    scratch = tmp_path / "scratch"
    artifacts = tmp_path / "artifacts"
    scratch.mkdir()
    artifacts.mkdir()
    return recovery.RecoveryState(scratch, artifacts)


def seed(subject, control):
    (control / "registry.json").write_text("supervisor-only")
    (subject / "workspace/platform/plugin-state").mkdir(parents=True)
    (subject / "home/empty").mkdir(parents=True)
    (subject / "workspace/platform/plugin-state/unknown.jsonl").write_bytes(b"opaque\n")
    (subject / "workspace/.lease").write_bytes(b"inactive startup identity")
    locked = subject / "workspace/platform/plugin-state"
    locked.chmod(0o555)
    return "seed-owner-settled"


def test_complete_opaque_reset_is_independent_and_never_resets_registry(tmp_path):
    subject = state(tmp_path)
    assert subject.prepare(seed) == "seed-owner-settled"
    expected = subject.receipt
    preceding_identity = (subject.subject.stat().st_dev, subject.subject.stat().st_ino)

    def mutate(root, control):
        assert root == subject.subject
        assert recovery.inventory(root) == expected["manifest"]
        assert subject.receipt["restores"] >= 1
        assert (root.stat().st_dev, root.stat().st_ino) != preceding_identity
        assert (control / "registry.json").read_text() == "supervisor-only"
        data = root / "workspace/platform/plugin-state"
        assert (data / "unknown.jsonl").stat().st_ino != (
            subject.seed / "workspace/platform/plugin-state/unknown.jsonl"
        ).stat().st_ino
        data.chmod(0o755)
        (data / "unknown.jsonl").write_bytes(b"candidate mutation\n")
        (data / "extra.json").write_text("extra opaque state")
        (root / "home/empty").rmdir()
        return "sample-owner-settled"

    assert subject.sample(mutate) == "sample-owner-settled"
    preceding_identity = (subject.subject.stat().st_dev, subject.subject.stat().st_ino)
    assert subject.sample(mutate) == "sample-owner-settled"
    assert subject.receipt["restores"] == 2
    assert recovery.inventory(subject.seed) == expected["manifest"]
    expected["manifest"].clear()
    assert subject.receipt["manifest"]


@pytest.mark.parametrize("kind", ["symlink", "fifo", "privileged"])
def test_unknown_input_is_not_silently_omitted(tmp_path, kind):
    subject = state(tmp_path)

    def prepare(root, control):
        path = root / "unknown"
        if kind == "symlink":
            path.symlink_to(control, target_is_directory=True)
        elif kind == "fifo":
            os.mkfifo(path)
        else:
            path.write_text("unsupported")
            path.chmod(0o4755)

    with pytest.raises(ValueError):
        subject.prepare(prepare)
    with pytest.raises(RuntimeError):
        subject.sample(lambda *_: pytest.fail("must not spawn"))


def test_pending_owner_cannot_capture_or_reset(tmp_path):
    subject = state(tmp_path)

    def prepare(root, control):
        with pytest.raises(RuntimeError, match="pending"):
            subject.prepare(seed)
        with pytest.raises(RuntimeError, match="pending"):
            subject.sample(lambda *_: pytest.fail("must not spawn"))
        seed(root, control)

    subject.prepare(prepare)

    def sample(*_):
        with pytest.raises(RuntimeError, match="pending"):
            subject.sample(lambda *_: pytest.fail("must not spawn"))

    subject.sample(sample)


@pytest.mark.parametrize("during", ["prepare", "sample"])
def test_failed_owner_retains_state_and_never_retries(tmp_path, during):
    subject = state(tmp_path)

    def failed(root, control):
        (root / "failure-evidence").write_text("retained")
        raise RuntimeError("failed owned run")

    if during == "sample":
        subject.prepare(seed)
    with pytest.raises(RuntimeError, match="failed owned run"):
        getattr(subject, during)(failed)
    assert (subject.subject / "failure-evidence").read_text() == "retained"
    with pytest.raises(RuntimeError, match="failed"):
        subject.sample(lambda *_: pytest.fail("must not spawn"))


@pytest.mark.parametrize("fault", ["content", "missing", "extra", "mode", "copy"])
def test_bad_snapshot_or_incomplete_restore_never_spawns(tmp_path, monkeypatch, fault):
    subject = state(tmp_path)
    subject.prepare(seed)
    target = subject.seed / "workspace/.lease"
    if fault == "content":
        target.write_bytes(b"changed")
    elif fault == "missing":
        target.unlink()
    elif fault == "extra":
        (subject.seed / "extra").write_text("unbound")
    elif fault == "mode":
        target.chmod(0o444)
    else:

        def fail_copy(*args, **kwargs):
            raise OSError("disk quota")

        monkeypatch.setattr(shutil, "copytree", fail_copy)
    before = recovery.inventory(subject.subject)
    with pytest.raises((ValueError, OSError)):
        subject.sample(lambda *_: pytest.fail("must not spawn"))
    assert recovery.inventory(subject.subject) == before
    with pytest.raises(RuntimeError):
        subject.sample(lambda *_: pytest.fail("must not spawn"))


def test_candidate_cannot_modify_pristine_seed_without_invalidating_run(tmp_path):
    subject = state(tmp_path)
    subject.prepare(seed)

    def sample(*_):
        (subject.seed / "workspace/.lease").write_bytes(b"modified")

    with pytest.raises(ValueError, match="candidate changed"):
        subject.sample(sample)
    with pytest.raises(RuntimeError):
        subject.sample(lambda *_: pytest.fail("must not spawn"))


@pytest.mark.parametrize("system", ["Darwin", "Windows"])
def test_non_linux_recovery_rejects_before_creating_state(
    tmp_path, monkeypatch, system
):
    monkeypatch.setattr(recovery.platform, "system", lambda: system)
    with pytest.raises(ValueError, match="Linux recovery state only"):
        recovery.RecoveryState(tmp_path, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_manifest_is_portable_and_records_empty_directories_and_bytes(tmp_path):
    (tmp_path / "empty").mkdir()
    (tmp_path / "journal.jsonl").write_bytes(b"not interpreted by this tool\n")
    value = recovery.inventory(tmp_path)
    assert set(value) == {".", "empty", "journal.jsonl"}
    assert value["empty"]["kind"] == "directory"
    assert value["journal.jsonl"]["kind"] == "file"
    assert value["journal.jsonl"]["size"] == 29
