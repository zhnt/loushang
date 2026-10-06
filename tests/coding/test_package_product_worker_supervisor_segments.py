"""Product Supervisor history retains epochs across Linux segment publication."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import loushang.coding.package_product_worker_supervisor_journal as supervisor_module
from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_payload import (
    open_coding_product_worker_supervisor_journal,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationError,
)
from loushang.harness.worker import WorkerLaunchIdentityV1
from loushang.harness.worker.journal import WorkerSupervisorJournalError

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Product journal")


def _product(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    return open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )


def _identity(*, attempt: str, epoch: int) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id="workerprobe",
        plugin_revision_digest="a" * 64,
        contribution_id="query-provider",
        owner_id="coding",
        product_id="coding",
        scope_id="test-scope",
        owner_generation=1,
        declaration_fingerprint="b" * 64,
        worker_configuration_fingerprint="c" * 64,
        attempt_id=attempt * 32,
        supervisor_epoch=epoch,
        session_nonce="d" * 64,
    )


def test_product_supervisor_empty_reads_do_not_create_history_or_reset_orphan_lock(
    tmp_path: Path,
) -> None:
    owner = _product(tmp_path)
    try:
        product = owner.runtime_owner.product_owner
        journal = open_coding_product_worker_supervisor_journal(product)
        identity = _identity(attempt="1", epoch=1)
        lock = product.state_root / "worker-supervisor.jsonl.lock"
        history = product.state_root / "worker-supervisor.jsonl"
        assert journal.status(identity.attempt_id) is None
        assert journal.next_supervisor_epoch(identity) == 1
        assert journal.incomplete() == ()
        assert not lock.exists() and not history.exists()
        lock.touch(mode=0o600)
        with pytest.raises(WorkerSupervisorJournalError) as orphan:
            journal.claim(identity, max_attempts=3)
        assert orphan.value.code == "worker_supervisor_journal_corrupt"
        assert not history.exists()
        lock.unlink()
        with product.gc_gate.read_snapshot_guard():
            assert journal.status(identity.attempt_id) is None
            with pytest.raises(PluginPackageGcReservationError) as blocked_write:
                journal.claim(identity, max_attempts=3)
            assert blocked_write.value.code == "plugin_package_gc_read_guard_nested"
            assert not lock.exists() and not history.exists()
        journal.claim(identity, max_attempts=3)
        history.unlink()
        with pytest.raises(WorkerSupervisorJournalError) as missing:
            journal.status(identity.attempt_id)
        assert missing.value.code == "worker_supervisor_journal_corrupt"
    finally:
        owner.close()


def test_product_supervisor_reopens_sealed_history_and_refuses_changed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _product(tmp_path)
    try:
        product = owner.runtime_owner.product_owner
        monkeypatch.setattr(supervisor_module, "_MAX_RECORDS", 2)
        identity = _identity(attempt="1", epoch=1)
        journal = open_coding_product_worker_supervisor_journal(product)
        claimed = journal.claim(identity, max_attempts=3)
        launching = journal.transition(
            identity.attempt_id,
            expected_phase="claimed",
            next_phase="launching",
            expected_record_revision=claimed.record_revision,
            expected_supervisor_epoch=1,
        )
        handshaking = journal.transition(
            identity.attempt_id,
            expected_phase="launching",
            next_phase="handshaking",
            expected_record_revision=launching.record_revision,
            expected_supervisor_epoch=1,
        )
        assert handshaking.record_revision == 3
        assert (product.state_root / "worker-supervisor.segments.json").is_file()
        reopened = open_coding_product_worker_supervisor_journal(product)
        assert reopened.status(identity.attempt_id) == handshaking
        with pytest.raises(WorkerSupervisorJournalError) as reused:
            reopened.claim(identity, max_attempts=3)
        assert reused.value.code == "worker_attempt_already_claimed"
        sealed = product.state_root / "worker-supervisor.jsonl"
        original = sealed.read_bytes()
        sealed.write_bytes(original + b"{}\n")
        with pytest.raises(WorkerSupervisorJournalError) as changed:
            reopened.status(identity.attempt_id)
        assert changed.value.code == "worker_supervisor_journal_corrupt"
        sealed.write_bytes(original)
        assert reopened.status(identity.attempt_id) == handshaking
        current = handshaking
        for phase in ("healthy", "draining", "stopped"):
            current = reopened.transition(
                identity.attempt_id,
                expected_phase=current.phase,
                next_phase=phase,  # type: ignore[arg-type]
                expected_record_revision=current.record_revision,
                expected_supervisor_epoch=1,
            )
        successor = _identity(attempt="2", epoch=2)
        assert reopened.next_supervisor_epoch(successor) == 2
        successor_claim = reopened.claim(successor, max_attempts=3)
        assert successor_claim.record_revision == 7
        assert successor_claim.supervisor_epoch == 2
        assert successor_claim.restart_ordinal == 1
        assert open_coding_product_worker_supervisor_journal(product).status(
            identity.attempt_id
        ) == current
    finally:
        owner.close()


def test_product_supervisor_reopens_after_manifest_publication_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _product(tmp_path)
    try:
        product = owner.runtime_owner.product_owner
        monkeypatch.setattr(supervisor_module, "_MAX_RECORDS", 1)
        identity = _identity(attempt="1", epoch=1)
        journal = open_coding_product_worker_supervisor_journal(product)
        claimed = journal.claim(identity, max_attempts=3)
        original_write = RootedFile.atomic_write

        def interrupt_after_publish(target, data, *, fsync=True, exclusive=False):
            original_write(target, data, fsync=fsync, exclusive=exclusive)
            raise OSError("interrupted after durable manifest publication")

        monkeypatch.setattr(RootedFile, "atomic_write", interrupt_after_publish)
        with pytest.raises(OSError, match="interrupted after"):
            journal.transition(
                identity.attempt_id,
                expected_phase="claimed",
                next_phase="launching",
                expected_record_revision=claimed.record_revision,
                expected_supervisor_epoch=1,
            )
        monkeypatch.setattr(RootedFile, "atomic_write", original_write)
        reopened = open_coding_product_worker_supervisor_journal(product)
        assert reopened.status(identity.attempt_id) == claimed
        launching = reopened.transition(
            identity.attempt_id,
            expected_phase="claimed",
            next_phase="launching",
            expected_record_revision=claimed.record_revision,
            expected_supervisor_epoch=1,
        )
        assert launching.record_revision == 2
        assert reopened.status(identity.attempt_id) == launching
    finally:
        owner.close()
