from __future__ import annotations

import json
import os
import selectors
import stat
import subprocess
import sys
from threading import Event

import pytest

from loushang.harness.transcript.store_admission import TranscriptStoreAdmission
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux retained storage")


def owner(tmp_path, *, create=False):
    return TranscriptStoreAdmission(tmp_path / "data/sessions", state_root=tmp_path / "state/session-stores",
                                    create_if_missing=create)


def snapshot(path):
    return {str(p): (p.lstat().st_dev, p.lstat().st_ino, p.lstat().st_mode, p.lstat().st_mtime_ns,
                    p.read_bytes() if p.is_file() else None)
            for p in (path, *path.rglob("*"))}


def test_constructor_and_missing_restore_create_nothing(tmp_path):
    admission = owner(tmp_path)
    assert not tuple(tmp_path.iterdir())
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            admission.open()
    finally:
        admission.close()
    assert not tuple(tmp_path.iterdir()) and not admission.cleanup_pending


@pytest.mark.parametrize("legacy", [False, True])
def test_inspect_never_registers_or_initializes_even_with_creation_enabled(tmp_path, legacy):
    admission = owner(tmp_path, create=True)
    if legacy:
        admission.root.mkdir(parents=True, mode=0o700)
        (admission.root / "old.jsonl").write_bytes(b"history")
    before = snapshot(tmp_path)
    try:
        assert admission.inspect() is None
    finally:
        admission.close()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("loss", ["none", "root", "replacement", "parent", "marker"])
def test_readonly_inspection_distinguishes_known_store_from_missing_or_replaced(tmp_path, loss):
    first = owner(tmp_path, create=True)
    try:
        binding = first.open()
    finally:
        first.close()
    if loss in ("root", "replacement"):
        first.root.rename(tmp_path / "original")
        if loss == "replacement":
            first.root.mkdir(mode=0o700)
    elif loss == "parent":
        first.root.parent.rename(tmp_path / "original")
        first.root.parent.mkdir(mode=0o700)
        (tmp_path / "original/sessions").rename(first.root)
    elif loss == "marker":
        (first.witness_root / "admission.json").rename(tmp_path / "old-marker")
    before = snapshot(tmp_path)
    selected = owner(tmp_path)
    try:
        if loss == "none":
            assert selected.inspect() == binding
            selected.check()
        else:
            with pytest.raises(TranscriptWriterError, match="unavailable|incomplete|conflict"):
                selected.inspect()
    finally:
        selected.close()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("observed_at", ["before_open", "intent"])
def test_prior_positive_or_unknown_root_evidence_prevents_creation(tmp_path, monkeypatch, observed_at):
    observed = Event()
    admission = TranscriptStoreAdmission(tmp_path / "data/sessions", state_root=tmp_path / "state/session-stores",
                                         create_if_missing=True, root_observed=observed)
    if observed_at == "before_open":
        observed.set()
    else:
        write = admission._write

        def signal(record):
            write(record)
            observed.set()

        monkeypatch.setattr(admission, "_write", signal)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            admission.open()
    finally:
        admission.close()
    assert not admission.root.exists()
    if observed_at == "before_open":
        assert not tuple(tmp_path.iterdir())


def test_first_new_creates_private_root_then_reopen_is_readonly(tmp_path):
    admission = owner(tmp_path, create=True)
    try:
        binding = admission.open()
        assert stat.S_IMODE(admission.root.stat().st_mode) == 0o700
        assert list(admission.root.iterdir()) == []
    finally:
        admission.close()
    before = snapshot(tmp_path)
    second = owner(tmp_path)
    try:
        assert second.open() == binding
    finally:
        second.close()
    assert snapshot(tmp_path) == before
    writer = TranscriptWriterLease(admission.root, "coding", "one",
                                    expected_root_identity=binding.root_identity,
                                    expected_parent_identity=binding.parent_identity)
    try:
        writer.acquire()
    finally:
        writer.close()


def test_legacy_store_and_images_are_never_modified(tmp_path):
    root = tmp_path / "data/sessions"
    root.mkdir(parents=True, mode=0o755)
    root.parent.chmod(0o755)
    root.chmod(0o755)
    (root / "old.jsonl").write_bytes(b"legacy transcript\n")
    # Existing standalone v1 admission remains usable; it does not enroll an
    # unknown shared family merely because attachment names are present.
    previous = owner(tmp_path)
    try:
        previous.open()
    finally:
        previous.close()
    assets = root.parent / "session-assets"
    assets.mkdir(mode=0o755)
    (assets / "old.png").write_bytes(b"image bytes")
    before = snapshot(root.parent)
    admission = owner(tmp_path)
    try:
        admission.open()
    finally:
        admission.close()
    assert snapshot(root.parent) == before


@pytest.mark.parametrize("lost", ["root", "parent", "marker", "lock", "witness", "witness_symlink"])
def test_known_store_loss_or_replacement_is_not_new_empty_store(tmp_path, lost):
    admission = owner(tmp_path, create=True)
    try:
        admission.open()
    finally:
        admission.close()
    if lost == "root":
        admission.root.rename(tmp_path / "old-sessions")
    elif lost == "parent":
        admission.root.parent.rename(tmp_path / "old-data")
        admission.root.parent.mkdir(mode=0o700)
        (tmp_path / "old-data/sessions").rename(admission.root)
    elif lost == "marker":
        (admission.witness_root / "admission.json").rename(tmp_path / "old-marker")
    elif lost == "lock":
        next((admission.witness_root / ".store-admission-locks").iterdir()).rename(tmp_path / "old-lock")
    else:
        admission.witness_root.rename(tmp_path / "old-witness")
        if lost == "witness_symlink":
            admission.witness_root.symlink_to(tmp_path / "old-witness", target_is_directory=True)
        else:
            admission.witness_root.mkdir()
    before = snapshot(tmp_path)
    second = owner(tmp_path, create=True)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable|conflict|incomplete"):
            second.open()
    finally:
        second.close()
    assert before == snapshot(tmp_path)


@pytest.mark.parametrize("residue", ["session-assets", ".session-blob-writers"])
def test_missing_root_with_attachment_residue_cannot_initialize(tmp_path, residue):
    (tmp_path / "data" / residue).mkdir(parents=True)
    before = snapshot(tmp_path)
    admission = owner(tmp_path, create=True)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            admission.open()
    finally:
        admission.close()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("stage", ["intent", "root", "publication"])
def test_lost_receipt_never_replays_initialization(tmp_path, monkeypatch, stage):
    admission = owner(tmp_path, create=True)
    write, acquire = admission._write, admission._open_store

    def failed_write(record):
        write(record)
        if (record["phase"] == "initializing") == (stage == "intent"):
            raise OSError("lost publication receipt")

    def failed_acquire(*, create):
        acquire(create=create)
        raise OSError("lost root creation receipt")

    family_write = admission._family._write

    def failed_completion():
        family_write()
        member = admission._family._record["members"].get(admission._key)
        if member is not None and member["phase"] == "initialized":
            raise OSError("lost family completion receipt")

    with monkeypatch.context() as patch:
        if stage == "root":
            patch.setattr(admission, "_open_store", failed_acquire)
        elif stage == "publication":
            patch.setattr(admission._family, "_write", failed_completion)
        else:
            patch.setattr(admission, "_write", failed_write)
        try:
            with pytest.raises(TranscriptWriterError, match="unavailable"):
                admission.open()
        finally:
            admission.close()
    before = snapshot(tmp_path)
    second = owner(tmp_path, create=True)
    try:
        if stage == "publication":
            second.open()
        else:
            with pytest.raises(TranscriptWriterError, match="incomplete"):
                second.open()
    finally:
        second.close()
    assert before == snapshot(tmp_path)


def test_shared_key_has_no_product_workspace_or_machine_partition(tmp_path):
    first, second = owner(tmp_path, create=True), owner(tmp_path, create=True)
    assert first.witness_root == second.witness_root
    try:
        binding = first.open()
        with pytest.raises(TranscriptWriterError, match="busy"):
            second.open()
    finally:
        first.close()
        second.close()
    third = owner(tmp_path, create=True)
    try:
        assert third.open() == binding
    finally:
        third.close()


def test_malformed_known_record_is_not_overwritten(tmp_path):
    admission = owner(tmp_path, create=True)
    try:
        admission.open()
    finally:
        admission.close()
    marker = admission.witness_root / "admission.json"
    record = json.loads(marker.read_bytes())
    record["root"][0] = True
    marker.write_text(json.dumps(record))
    before = snapshot(tmp_path)
    second = owner(tmp_path, create=True)
    try:
        with pytest.raises(TranscriptWriterError):
            second.open()
    finally:
        second.close()
    assert before == snapshot(tmp_path)


def test_exclusive_native_root_does_not_adopt_a_racing_directory(tmp_path, monkeypatch):
    admission = owner(tmp_path, create=True)
    original = os.mkdir

    def race(path, *args, **kwargs):
        if path == "sessions":
            original(path, *args, **kwargs)
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "mkdir", race)
        try:
            with pytest.raises(TranscriptWriterError, match="conflict"):
                admission.open()
        finally:
            admission.close()
    assert list(admission.root.iterdir()) == []
    assert json.loads((admission.witness_root / "admission.json").read_bytes())["phase"] == "initializing"


def test_observed_legacy_root_disappearance_cannot_become_creation(tmp_path, monkeypatch):
    admission = owner(tmp_path, create=True)
    admission.root.mkdir(parents=True, mode=0o700)
    admission.root.parent.chmod(0o700)
    write = admission._write

    def disappear(record):
        write(record)
        admission.root.rename(tmp_path / "original-sessions")

    monkeypatch.setattr(admission, "_write", disappear)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            admission.open()
    finally:
        admission.close()
    assert not admission.root.exists()


@pytest.mark.parametrize("replacement", ["root", "parent"])
def test_legacy_identity_is_retained_across_intent_publication(tmp_path, monkeypatch, replacement):
    admission = owner(tmp_path, create=True)
    admission.root.mkdir(parents=True, mode=0o700)
    admission.root.parent.chmod(0o700)
    (admission.root / "original.jsonl").write_bytes(b"history")
    write = admission._write
    snapshots = []

    def replace(record):
        write(record)
        source = admission.root if replacement == "root" else admission.root.parent
        source.rename(tmp_path / "original")
        source.mkdir(mode=0o700)
        if replacement == "parent":
            (tmp_path / "original/sessions").rename(admission.root)
        snapshots.append(snapshot(tmp_path))

    monkeypatch.setattr(admission, "_write", replace)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            admission.open()
    finally:
        admission.close()
    assert snapshot(tmp_path) == snapshots[0]


_CHILD = """
import os, sys
from pathlib import Path
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission
from loushang.harness.transcript.writer_lease import TranscriptWriterError
base, stage = Path(sys.argv[1]), sys.argv[2]
owner = TranscriptStoreAdmission(base / 'data/sessions', state_root=base / 'state/session-stores',
                                 create_if_missing=True)
write, fresh, root = owner._write, owner._family._fresh.acquire, owner._open_store
family_write = owner._family._write
def publish(record):
    write(record)
    if stage == 'intent' and record['phase'] == 'initializing':
        os._exit(23)
def completed():
    family_write()
    member = owner._family._record['members'].get(owner._key)
    if stage == 'publication' and member is not None and member['phase'] == 'initialized':
        os._exit(23)
def create_witness():
    if stage == 'race':
        print('ready', flush=True)
        assert sys.stdin.readline().strip() == 'go'
    fresh()
    if stage == 'witness':
        os._exit(23)
def create_root(*, create):
    root(create=create)
    if stage == 'root':
        os._exit(23)
owner._write, owner._family._fresh.acquire, owner._open_store = publish, create_witness, create_root
owner._family._write = completed
try:
    owner.open()
    print('admitted', flush=True)
except TranscriptWriterError as error:
    print(error.code, flush=True)
finally:
    owner.close()
"""


@pytest.mark.parametrize("stage", ["witness", "intent", "root", "publication"])
def test_actual_process_crash_preserves_incomplete_or_initialized_fact(tmp_path, stage):
    result = subprocess.run([sys.executable, "-c", _CHILD, str(tmp_path), stage],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 23, result.stderr
    before = snapshot(tmp_path)
    admission = owner(tmp_path, create=True)
    try:
        if stage == "publication":
            admission.open()
        else:
            with pytest.raises(TranscriptWriterError, match="incomplete"):
                admission.open()
    finally:
        admission.close()
    assert snapshot(tmp_path) == before


def test_two_actual_initializers_have_one_exclusive_creator(tmp_path):
    children = []
    try:
        for _ in range(2):
            child = subprocess.Popen([sys.executable, "-c", _CHILD, str(tmp_path), "race"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            children.append(child)
            with selectors.DefaultSelector() as selected:
                selected.register(child.stdout, selectors.EVENT_READ)
                assert selected.select(15), "initializer did not reach the pre-create gate"
                assert child.stdout.readline().strip() == "ready"
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        outcomes = []
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            outcomes.append(stdout.strip())
        assert sorted(outcomes) == ["admitted", "conflict"]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
    before = snapshot(tmp_path)
    admission = owner(tmp_path)
    try:
        admission.open()
    finally:
        admission.close()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("legacy", [False, True])
def test_witness_is_published_with_record_before_data_admission(tmp_path, monkeypatch, legacy):
    from loushang.harness.transcript import _admission_publication as publication

    selected = owner(tmp_path, create=True)
    if legacy:
        selected.root.parent.mkdir(mode=0o700)
        selected.root.mkdir(mode=0o700)
    rename = publication._rename_noreplace
    observed = []
    initial = {}

    def publish(parent, source, target):
        stage = selected.witness_root.parent / source
        destination = selected.witness_root.parent / target
        assert not destination.exists()
        record = json.loads((stage / "admission.json").read_bytes())
        assert record["phase"] == "initializing"
        assert record["witness"] == [stage.stat().st_dev, stage.stat().st_ino]
        observed.append(record["version"])
        initial[destination] = record
        rename(parent, source, target)
        assert (destination / "admission.json").exists()

    monkeypatch.setattr(publication, "_rename_noreplace", publish)
    try:
        selected.open()
        assert observed == (["transcript-store-admission/v1"] if legacy else [
            "transcript-store-family/v1", "transcript-store-admission/v2"
        ])
        for destination, first in initial.items():
            completed = json.loads((destination / "admission.json").read_bytes())
            identity = "operation" if "operation" in first else "incarnation"
            assert first[identity] == completed[identity]
        assert not list(selected.witness_root.parent.glob(".admission-stage-*"))
    finally:
        selected.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_exact_initialized_backup_restores_only_missing_record(tmp_path, legacy):
    if legacy:
        (tmp_path / "data").mkdir(mode=0o700)
        (tmp_path / "data/sessions").mkdir(mode=0o700)
    original = owner(tmp_path, create=True)
    try:
        expected = original.open()
        record = original.witness_root / "admission.json"
        backup = record.read_bytes()
    finally:
        original.close()
    record.unlink()
    before = snapshot(tmp_path)
    recovery = owner(tmp_path)
    try:
        assert recovery.restore_record_from_backup(backup) == expected
        recovery.check()
        assert record.read_bytes() == backup
    finally:
        recovery.close()
    after = snapshot(tmp_path)
    # Only the missing leaf and its parent directory mtime may change.
    for name, metadata in before.items():
        assert (after[name][:3], after[name][4]) == (metadata[:3], metadata[4])
        if name != str(record.parent):
            assert after[name] == metadata
    assert set(after) == set(before) | {str(record)}
    assert not recovery.cleanup_pending
    restored = owner(tmp_path)
    try:
        assert restored.inspect() == expected
    finally:
        restored.close()


@pytest.mark.parametrize("loss", ["root", "parent", "lock", "witness", "family", "backup", "phase", "incarnation", "member"])
def test_backup_restore_rejects_changed_or_unproven_identity_without_writes(tmp_path, loss):
    original = owner(tmp_path, create=True)
    try:
        original.open()
        record = original.witness_root / "admission.json"
        backup = record.read_bytes()
    finally:
        original.close()
    record.unlink()
    if loss == "root":
        original.root.rename(tmp_path / "saved-root")
        original.root.mkdir(mode=0o700)
    elif loss == "parent":
        original.root.parent.rename(tmp_path / "saved-data")
        original.root.parent.mkdir(mode=0o700)
        (tmp_path / "saved-data/sessions").rename(original.root)
    elif loss == "lock":
        path = next((original.witness_root / ".store-admission-locks").iterdir())
        path.rename(tmp_path / "saved-lock")
        path.write_bytes(b"")
        path.chmod(0o600)
    elif loss == "witness":
        original.witness_root.rename(tmp_path / "saved-witness")
        original.witness_root.mkdir(mode=0o700)
    elif loss == "family":
        original._family.root.rename(tmp_path / "saved-family")
    elif loss == "backup":
        value = json.loads(backup)
        value["store"] = "0" * 64
        backup = json.dumps(value).encode()
    elif loss == "phase":
        value = json.loads(backup)
        value["phase"] = "initializing"
        backup = json.dumps(value).encode()
    elif loss in {"incarnation", "member"}:
        value = json.loads(backup)
        value["family" if loss == "incarnation" else "member"] = "0" * 32
        backup = json.dumps(value).encode()
    before = snapshot(tmp_path)
    recovery = owner(tmp_path)
    try:
        with pytest.raises(TranscriptWriterError):
            recovery.restore_record_from_backup(backup)
    finally:
        recovery.close()
    assert snapshot(tmp_path) == before


def test_restore_never_overwrites_record_created_during_validation(tmp_path, monkeypatch):
    original = owner(tmp_path, create=True)
    try:
        original.open()
        path = original.witness_root / "admission.json"
        backup = path.read_bytes()
    finally:
        original.close()
    path.unlink()
    recovery = owner(tmp_path)
    check = recovery.check

    def competing_record():
        check()
        path.write_bytes(b"keep concurrent record")
        path.chmod(0o600)

    monkeypatch.setattr(recovery, "check", competing_record)
    try:
        with pytest.raises(TranscriptWriterError):
            recovery.restore_record_from_backup(backup)
        assert path.read_bytes() == b"keep concurrent record"
    finally:
        recovery.close()


def test_old_missing_record_remains_blocking_with_local_diagnostics(tmp_path):
    from loushang.harness.transcript.writer_lease import TranscriptStoreAdmissionError

    broken = owner(tmp_path, create=True)
    (tmp_path / "state").mkdir(mode=0o700)
    broken.witness_root.parent.mkdir(mode=0o700)
    broken.witness_root.mkdir(mode=0o700)
    (broken.witness_root / ".store-admission-locks").mkdir(mode=0o700)
    before = snapshot(tmp_path)
    unrelated = TranscriptStoreAdmission(tmp_path / "new/data/sessions",
                                         state_root=broken.witness_root.parent,
                                         create_if_missing=True)
    try:
        with pytest.raises(TranscriptStoreAdmissionError) as caught:
            unrelated.open()
        assert caught.value.record_path == broken.witness_root / "admission.json"
        assert caught.value.stage == "read_record"
        assert str(caught.value) == "transcript_writer:incomplete"
        assert str(broken.witness_root) in caught.value.__notes__[0]
    finally:
        unrelated.close()
        broken.close()
    assert snapshot(tmp_path) == before


_STAGE_CRASH = """
import os,sys
from pathlib import Path
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission
from loushang.harness.transcript import _admission_publication as publication
base=Path(sys.argv[1])
publication._rename_noreplace=lambda *args: os._exit(24)
selected=TranscriptStoreAdmission(base/'data/sessions',state_root=base/'state/session-stores',create_if_missing=True)
selected.open()
"""


def test_process_exit_before_publication_never_leaves_formal_identity_or_blocks_new_store(tmp_path):
    result = subprocess.run([sys.executable, "-c", _STAGE_CRASH, str(tmp_path)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 24, result.stderr
    selected = owner(tmp_path, create=True)
    assert not selected.root.exists()
    stages = list(selected.witness_root.parent.glob(".admission-stage-*"))
    assert len(stages) == 1
    before = snapshot(stages[0])
    try:
        selected.open()
        assert selected.root.exists()
        assert snapshot(stages[0]) == before
    finally:
        selected.close()


def test_publication_never_replaces_empty_target_directory(tmp_path, monkeypatch):
    from loushang.harness.transcript import _admission_publication as publication

    selected = owner(tmp_path, create=True)
    rename = publication._rename_noreplace
    identity = []

    def competing_directory(parent, source, target):
        final = selected.witness_root.parent / target
        final.mkdir(mode=0o700)
        identity.append(final.stat().st_ino)
        rename(parent, source, target)

    monkeypatch.setattr(publication, "_rename_noreplace", competing_directory)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            selected.open()
        assert selected._family.root.stat().st_ino == identity[0]
        assert not selected.root.exists()
    finally:
        selected.close()


@pytest.mark.parametrize("effect", [False, True])
def test_unknown_publication_receipt_never_grants_data_creation(tmp_path, monkeypatch, effect):
    from loushang.harness.transcript import _admission_publication as publication

    selected = owner(tmp_path, create=True)
    rename = publication._rename_noreplace

    def lost_receipt(parent, source, target):
        if effect:
            rename(parent, source, target)
        raise OSError("test publication acknowledgement lost")

    monkeypatch.setattr(publication, "_rename_noreplace", lost_receipt)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            selected.open()
        assert not selected.root.parent.exists()
        assert (selected._family.root / "admission.json").exists() == effect
    finally:
        selected.close()
    assert not selected.cleanup_pending


def test_published_witness_sync_failure_is_retained_without_data_admission(tmp_path, monkeypatch):
    from loushang.harness.transcript import _admission_publication as publication

    selected = owner(tmp_path, create=True)
    rename, fsync = publication._rename_noreplace, os.fsync
    failed = []
    published = []

    def record_publication(parent, source, target):
        rename(parent, source, target)
        published.append(parent)

    def fail_parent_once(fd):
        if published and fd == published[-1] and not failed:
            failed.append(fd)
            raise OSError("test parent durability acknowledgement lost")
        fsync(fd)

    monkeypatch.setattr(publication, "_rename_noreplace", record_publication)
    monkeypatch.setattr(os, "fsync", fail_parent_once)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            selected.open()
        assert not selected.root.parent.exists()
        assert selected.cleanup_pending
        assert "publication_parent" in selected._family._fresh._sync_pending
    finally:
        selected.close()
    assert not selected.cleanup_pending
    retry = owner(tmp_path, create=True)
    try:
        with pytest.raises(TranscriptWriterError, match="incomplete"):
            retry.open()
    finally:
        retry.close()


def test_backup_restore_refuses_present_record_and_family_downgrade(tmp_path):
    original = owner(tmp_path, create=True)
    try:
        original.open()
        path = original.witness_root / "admission.json"
        backup = path.read_bytes()
    finally:
        original.close()
    same = owner(tmp_path)
    before = snapshot(tmp_path)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            same.restore_record_from_backup(backup)
    finally:
        same.close()
    assert snapshot(tmp_path) == before
    path.unlink()
    value = json.loads(backup)
    value.pop("family")
    value.pop("member")
    value["version"] = "transcript-store-admission/v1"
    downgrade = owner(tmp_path)
    before = snapshot(tmp_path)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            downgrade.restore_record_from_backup(json.dumps(value).encode())
    finally:
        downgrade.close()
    assert snapshot(tmp_path) == before


def test_failed_restore_does_not_leave_backup_as_a_live_record_authority(tmp_path, monkeypatch):
    from loushang.harness.journal._rooted_io import RootedFile

    original = owner(tmp_path, create=True)
    try:
        original.open()
        path = original.witness_root / "admission.json"
        backup = path.read_bytes()
    finally:
        original.close()
    path.unlink()
    before = snapshot(tmp_path)
    recovery = owner(tmp_path)

    def fail_publication(*args, **kwargs):
        raise OSError("test restore never published")

    monkeypatch.setattr(RootedFile, "atomic_write", fail_publication)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            recovery.restore_record_from_backup(backup)
        with pytest.raises(TranscriptWriterError, match="incomplete"):
            recovery.check()
    finally:
        recovery.close()
    assert snapshot(tmp_path) == before
