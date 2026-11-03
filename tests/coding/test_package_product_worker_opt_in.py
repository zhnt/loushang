"""Durable Product Worker opt-in decisions remain default-dark and replayable."""

from __future__ import annotations

import os
from dataclasses import replace
from hashlib import sha256

import pytest

import loushang.coding.package_product_worker_opt_in as opt_in_module
from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
    write_coding_worker_checkpoint_anchor,
)
from loushang.coding.package_product_worker_history_segments import (
    _head_bytes,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)
from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournal,
    CodingWorkerOptInJournalError,
    _opt_in_line,
)
from loushang.coding.package_product_worker_policy import CodingWorkerOptInV1
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationError,
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)


def test_worker_opt_in_writer_fences_anchored_checkpoint_ids(tmp_path) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    scope_id = "workspace:" + "a" * 64
    gate = PluginPackageGcReservationJournal(root / "gc-reservations.jsonl")
    journal = CodingWorkerOptInJournal(
        root / "worker-opt-in.jsonl",
        scope_id=scope_id,
        gc_gate=gate,
        store_id="store",
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
    allowed = journal.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-1",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    )
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=0,
            last_sealed_revision=0,
            segments=(journal.path.read_bytes() if stem == "worker-opt-in" else b"",),
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id=scope_id,
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint="b" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=("allow-1", "retired-op"),
        new_attempt_ids=("a" * 32,),
        new_receipt_fingerprints=("b" * 64,),
        opt_in_generation_high_water=(
            (opt_in.plugin_id, 1, 0, "allow", allowed.decision_digest),
        ),
        supervisor_epoch_high_water=(),
    )
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    io = RootedFileIO(root, root_fd)
    try:
        with io.bind(root / "worker-history-checkpoints.jsonl", durable=True) as rooted:
            assert rooted.acquire_lock(
                exclusive=True,
                suffix=".lock",
                initialize_empty_target_if_new=True,
            )
            initialize_coding_worker_active_head(
                rooted,
                stem="worker-history-checkpoints",
                stream_id="worker-history-checkpoints",
            )
            line = canonical_json_bytes(checkpoint.to_dict()) + b"\n"
            rooted.append_bytes(line)
            commit_coding_worker_active_segment(
                rooted,
                stem="worker-history-checkpoints",
                stream_id="worker-history-checkpoints",
                generation=0,
                previous_raw=b"",
                appended_line=line,
            )
            anchor = CodingWorkerCheckpointAnchorV1.create(
                scope_id=scope_id,
                store_id="store",
                latest_revision=1,
                latest_digest=checkpoint.record_digest,
            )
            write_coding_worker_checkpoint_anchor(rooted, expected=None, current=anchor)
    finally:
        io.cleanup()
        os.close(root_fd)

    before = journal.path.read_bytes()
    with pytest.raises(CodingWorkerOptInJournalError) as retired:
        journal.change(
            plugin_id=opt_in.plugin_id,
            operation_id="retired-op",
            expected_generation=1,
            action="revoke",
            opt_in=None,
        )
    assert retired.value.code == "coding_worker_opt_in_operation_retired"
    assert journal.path.read_bytes() == before

    ownerless = CodingWorkerOptInJournal(journal.path, scope_id=scope_id, gc_gate=gate)
    with pytest.raises(CodingWorkerOptInJournalError) as missing_owner:
        ownerless.change(
            plugin_id=opt_in.plugin_id,
            operation_id="revoke-ownerless",
            expected_generation=1,
            action="revoke",
            opt_in=None,
        )
    assert missing_owner.value.code == "coding_worker_opt_in_checkpoint_owner_required"
    assert journal.path.read_bytes() == before

    head_path = root / "worker-opt-in.head.json"
    original_head = head_path.read_bytes()
    forked = CodingWorkerOptInDecisionV1.create(
        journal_revision=1,
        scope_id=scope_id,
        plugin_id=opt_in.plugin_id,
        operation_id="allow-fork",
        generation=1,
        kill_switch_generation=0,
        action="allow",
        opt_in=opt_in,
    )
    forked_raw = _opt_in_line(forked)
    journal.path.write_bytes(forked_raw)
    head_path.write_bytes(_head_bytes("worker-opt-in", 0, forked_raw))
    try:
        with pytest.raises(CodingWorkerOptInJournalError) as rewritten:
            journal.change(
                plugin_id=opt_in.plugin_id,
                operation_id="revoke-after-fork",
                expected_generation=1,
                action="revoke",
                opt_in=None,
            )
        assert rewritten.value.code == "coding_worker_opt_in_checkpoint_source_changed"
    finally:
        journal.path.write_bytes(before)
        head_path.write_bytes(original_head)

    # A head-anchored but uncommitted checkpoint append has no tombstone power.
    with (root / "worker-history-checkpoints.jsonl").open("ab") as handle:
        handle.write(b'{"pending":true}\n')
    revoked = journal.change(
        plugin_id=opt_in.plugin_id,
        operation_id="revoke-new",
        expected_generation=1,
        action="revoke",
        opt_in=None,
    )
    assert revoked.generation == 2


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
    assert (
        reopened.change(
            plugin_id=opt_in.plugin_id,
            operation_id="allow-1",
            expected_generation=0,
            action="allow",
            opt_in=opt_in,
        )
        == allowed
    )
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
        opt_in=replace(opt_in, owner_selection_generation=3, kill_switch_generation=1),
    )
    assert allowed_again.generation == 3
    assert allowed_again.kill_switch_generation == 1
    assert journal.current(opt_in.plugin_id) == allowed_again
    assert reopened.history_read_only() == (allowed, revoked, allowed_again)
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
    with pytest.raises(CodingWorkerOptInJournalError) as truncated:
        reopened.current(opt_in.plugin_id)
    assert truncated.value.code == "coding_worker_segment_head_changed"


def test_worker_opt_in_read_only_status_requires_existing_gc_gate_and_never_writes(
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
    with pytest.raises(FileNotFoundError):
        journal.current_read_only("example.worker")
    with pytest.raises(FileNotFoundError):
        journal.history_read_only()
    assert tuple(root.iterdir()) == ()

    with gate.guard():
        pass
    assert journal.current_read_only("example.worker") is None
    assert journal.history_read_only() == ()
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
        operation_id="allow-read-only",
        expected_generation=0,
        action="allow",
        opt_in=opt_in,
    )
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    assert journal.current_read_only(opt_in.plugin_id) == allowed
    assert journal.history_read_only() == (allowed,)
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    with gate.read_snapshot_guard():
        assert journal.current(opt_in.plugin_id) == allowed
        with pytest.raises(PluginPackageGcReservationError) as blocked_write:
            journal.change(
                plugin_id=opt_in.plugin_id,
                operation_id="revoke-inside-read-guard",
                expected_generation=1,
                action="revoke",
                opt_in=None,
            )
        assert blocked_write.value.code == "plugin_package_gc_read_guard_nested"
        assert journal.current(opt_in.plugin_id) == allowed
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    lock = root / "worker-opt-in.jsonl.lock"
    retained_lock = root / "retained-worker-opt-in.lock"
    lock.rename(retained_lock)
    with pytest.raises(CodingWorkerOptInJournalError) as missing_lock:
        journal.current_read_only(opt_in.plugin_id)
    assert missing_lock.value.code == "coding_worker_opt_in_lock_missing"
    assert not lock.exists()
    assert journal.path.read_bytes() == before[journal.path.name]


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
    assert (
        reopened.change(
            plugin_id=opt_in.plugin_id,
            operation_id="allow-1",
            expected_generation=0,
            action="allow",
            opt_in=opt_in,
        )
        == allowed
    )
    allowed_again = reopened.change(
        plugin_id=opt_in.plugin_id,
        operation_id="allow-3",
        expected_generation=2,
        action="allow",
        opt_in=replace(opt_in, owner_selection_generation=3, kill_switch_generation=1),
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


def test_worker_opt_in_refuses_lost_active_revocation(
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
    assert allowed.action == "allow"
    assert journal.current(opt_in.plugin_id) == revoked
    (root / "worker-opt-in.g00000001.jsonl").unlink()
    reopened = CodingWorkerOptInJournal(
        journal.path, scope_id=journal.scope_id, gc_gate=gate
    )
    with pytest.raises(CodingWorkerOptInJournalError) as missing:
        reopened.current(opt_in.plugin_id)
    assert missing.value.code == "coding_worker_segment_active_missing"


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
