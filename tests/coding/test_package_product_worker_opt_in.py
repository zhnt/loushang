"""Durable Product Worker opt-in decisions remain default-dark and replayable."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

import loushang.coding.package_product_worker_opt_in as opt_in_module
from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInJournal,
    CodingWorkerOptInJournalError,
)
from loushang.coding.package_product_worker_policy import CodingWorkerOptInV1
from loushang.harness.journal import JournalFileError
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)


def test_worker_opt_in_decision_reopens_and_revocation_fences_old_generation(
    tmp_path,
) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    gate = PluginPackageGcReservationJournal(root / "gc-reservations.jsonl")
    journal = CodingWorkerOptInJournal(
        root / "worker-opt-in.jsonl",
        scope_id="workspace:" + "a" * 64,
        gc_gate=gate,
    )
    assert journal.current("example.worker") is None
    assert not journal.path.exists()
    assert not (root / "worker-opt-in.jsonl.lock").exists()
    opt_in = CodingWorkerOptInV1(
        plugin_id="example.worker",
        contribution_id="query-provider",
        owner_id="coding.lsp",
        artifact_digest=sha256(b"wheel").hexdigest(),
        native_platform="linux-x86_64",
        owner_selection_generation=1,
        kill_switch_generation=0,
        require_worker=True,
    )
    allowed = journal.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-1",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    )
    reopened = CodingWorkerOptInJournal(
        journal.path, scope_id="workspace:" + "a" * 64, gc_gate=gate
    )
    assert reopened.current(opt_in.plugin_id) == allowed
    assert reopened.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-1",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    ) == allowed
    with pytest.raises(CodingWorkerOptInJournalError) as stale:
        reopened.change(
            plugin_id=opt_in.plugin_id,
            operation_id="allow-stale",
            expected_generation=0,
            action="allow",
            opt_in=opt_in,
        )
    assert stale.value.code == "coding_worker_opt_in_stale"
    revoked = reopened.change(
        plugin_id=opt_in.plugin_id,
        operation_id="revoke-2",
        expected_generation=1,
        action="revoke",
        opt_in=None,
    )
    assert revoked.generation == 2
    assert revoked.kill_switch_generation == 1
    assert revoked.opt_in is None
    with pytest.raises(CodingWorkerOptInJournalError) as reused:
        reopened.change(
            plugin_id=opt_in.plugin_id,
            operation_id="allow-1",
            expected_generation=0,
            action="allow",
            opt_in=replace(opt_in, artifact_digest=sha256(b"other").hexdigest()),
        )
    assert reused.value.code == "coding_worker_opt_in_operation_conflict"
    with pytest.raises(CodingWorkerOptInJournalError) as old_kill:
        reopened.change(
            plugin_id=opt_in.plugin_id,
            operation_id="allow-3-bad",
            expected_generation=2,
            action="allow",
            opt_in=replace(opt_in, owner_selection_generation=3),
        )
    assert old_kill.value.code == "coding_worker_opt_in_generation_invalid"
    allowed_again = reopened.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-3",
        expected_generation=2,
        action="allow",
        opt_in=replace(
            opt_in, owner_selection_generation=3, kill_switch_generation=1
        ),
    )
    assert allowed_again.generation == 3
    assert allowed_again.kill_switch_generation == 1
    assert journal.current(opt_in.plugin_id) == allowed_again
    retained = root / "retained-worker-opt-in.jsonl"
    journal.path.rename(retained)
    victim = tmp_path / "victim.jsonl"
    victim.write_bytes(b"private-data")
    journal.path.symlink_to(victim)
    with pytest.raises(OSError):
        journal.current(opt_in.plugin_id)
    assert victim.read_bytes() == b"private-data"
    journal.path.unlink()
    retained.rename(journal.path)
    with journal.path.open("ab") as handle:
        handle.write(b"{")
    with pytest.raises(JournalFileError):
        reopened.current(opt_in.plugin_id)


def test_worker_opt_in_rotates_without_resetting_generation_or_operation_id(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    gate = PluginPackageGcReservationJournal(root / "gc-reservations.jsonl")
    journal = CodingWorkerOptInJournal(
        root / "worker-opt-in.jsonl",
        scope_id="workspace:" + "a" * 64,
        gc_gate=gate,
    )
    monkeypatch.setattr(opt_in_module, "_MAX_EVENTS", 1)
    opt_in = CodingWorkerOptInV1(
        plugin_id="example.worker",
        contribution_id="query-provider",
        owner_id="coding.lsp",
        artifact_digest=sha256(b"wheel").hexdigest(),
        native_platform="linux-x86_64",
        owner_selection_generation=1,
        kill_switch_generation=0,
        require_worker=True,
    )
    allowed = journal.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-1",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    )
    revoked = journal.change(
        plugin_id=opt_in.plugin_id,
        operation_id="revoke-2",
        expected_generation=1,
        action="revoke",
        opt_in=None,
    )
    reopened = CodingWorkerOptInJournal(
        journal.path, scope_id=journal.scope_id, gc_gate=gate
    )
    assert reopened.current(opt_in.plugin_id) == revoked
    assert reopened.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-1",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    ) == allowed
    allowed_again = reopened.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-3",
        expected_generation=2,
        action="allow",
        opt_in=replace(
            opt_in, owner_selection_generation=3, kill_switch_generation=1
        ),
    )
    assert allowed_again.journal_revision == 3
    assert allowed_again.generation == 3
    assert reopened.current(opt_in.plugin_id) == allowed_again
    assert (root / "worker-opt-in.segments.json").is_file()
    sealed = journal.path
    original = sealed.read_bytes()
    sealed.write_bytes(original + b"{}\n")
    with pytest.raises(CodingWorkerOptInJournalError) as changed:
        reopened.current(opt_in.plugin_id)
    assert changed.value.code == "coding_worker_sealed_segment_changed"
    sealed.write_bytes(original)
    assert reopened.current(opt_in.plugin_id) == allowed_again


def test_worker_opt_in_refuses_history_reset_behind_retained_lock(tmp_path) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    gate = PluginPackageGcReservationJournal(root / "gc-reservations.jsonl")
    journal = CodingWorkerOptInJournal(
        root / "worker-opt-in.jsonl",
        scope_id="workspace:" + "a" * 64,
        gc_gate=gate,
    )
    opt_in = CodingWorkerOptInV1(
        plugin_id="example.worker",
        contribution_id="query-provider",
        owner_id="coding.lsp",
        artifact_digest=sha256(b"wheel").hexdigest(),
        native_platform="linux-x86_64",
        owner_selection_generation=1,
        kill_switch_generation=0,
        require_worker=True,
    )
    lock = root / "worker-opt-in.jsonl.lock"
    lock.touch(mode=0o600)
    with pytest.raises(CodingWorkerOptInJournalError) as orphan:
        journal.change(
            plugin_id=opt_in.plugin_id,
            operation_id="allow-1",
            expected_generation=0,
            action="allow",
            opt_in=opt_in,
        )
    assert orphan.value.code == "coding_worker_opt_in_orphan_lock"
    assert not journal.path.exists()
    lock.unlink()
    journal.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-1",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    )
    journal.path.unlink()
    with pytest.raises(CodingWorkerOptInJournalError) as removed:
        journal.current(opt_in.plugin_id)
    assert removed.value.code == "coding_worker_opt_in_orphan_lock"


def test_worker_opt_in_recovers_after_manifest_publish_interruption(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    gate = PluginPackageGcReservationJournal(root / "gc-reservations.jsonl")
    journal = CodingWorkerOptInJournal(
        root / "worker-opt-in.jsonl",
        scope_id="workspace:" + "a" * 64,
        gc_gate=gate,
    )
    monkeypatch.setattr(opt_in_module, "_MAX_EVENTS", 1)
    opt_in = CodingWorkerOptInV1(
        plugin_id="example.worker",
        contribution_id="query-provider",
        owner_id="coding.lsp",
        artifact_digest=sha256(b"wheel").hexdigest(),
        native_platform="linux-x86_64",
        owner_selection_generation=1,
        kill_switch_generation=0,
        require_worker=True,
    )
    allowed = journal.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-1",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    )
    original_write = RootedFile.atomic_write

    def interrupt_after_publish(target, data, *, fsync=True, exclusive=False):
        original_write(target, data, fsync=fsync, exclusive=exclusive)
        raise OSError("interrupted after durable manifest publication")

    monkeypatch.setattr(RootedFile, "atomic_write", interrupt_after_publish)
    with pytest.raises(OSError, match="interrupted after"):
        journal.change(
            plugin_id=opt_in.plugin_id,
            operation_id="revoke-2",
            expected_generation=1,
            action="revoke",
            opt_in=None,
        )
    monkeypatch.setattr(RootedFile, "atomic_write", original_write)
    reopened = CodingWorkerOptInJournal(
        journal.path, scope_id=journal.scope_id, gc_gate=gate
    )
    assert reopened.current(opt_in.plugin_id) == allowed
    revoked = reopened.change(
        plugin_id=opt_in.plugin_id,
        operation_id="revoke-2",
        expected_generation=1,
        action="revoke",
        opt_in=None,
    )
    assert revoked.journal_revision == 2
    assert reopened.current(opt_in.plugin_id) == revoked
