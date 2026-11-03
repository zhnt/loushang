"""Windows Package GC must account for every Worker-owned state-root name."""

from __future__ import annotations

import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.coding.package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from loushang.coding.package_product_worker_windows_gc_history import (
    _require_c5_gc_history,
    _require_known_windows_worker_state_names,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySourceFileV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)


def test_windows_worker_history_source_identity_round_trips_strictly() -> None:
    source = CodingWindowsWorkerHistorySourceFileV1(
        name="worker-opt-in.jsonl", size=3, sha256_digest=sha256(b"abc").hexdigest()
    )
    snapshot = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a", store_id="store-a", lease_owner_revision=2, files=(source,)
    )
    assert (
        CodingWindowsWorkerHistorySourceSnapshotV1.from_dict(snapshot.to_dict())
        == snapshot
    )
    changed = snapshot.to_dict()
    changed["snapshotDigest"] = sha256(b"changed").hexdigest()
    with pytest.raises(ValueError, match="source snapshot is invalid"):
        CodingWindowsWorkerHistorySourceSnapshotV1.from_dict(changed)
    changed = snapshot.to_dict()
    changed["files"] = [{**source.to_dict(), "size": True}]
    with pytest.raises(ValueError, match="source file is invalid"):
        CodingWindowsWorkerHistorySourceSnapshotV1.from_dict(changed)
    with pytest.raises(ValueError, match="source file is invalid"):
        CodingWindowsWorkerHistorySourceFileV1(
            name="worker-history-base-opt-in-v1.json",
            size=3,
            sha256_digest=sha256(b"abc").hexdigest(),
        )


def test_windows_worker_gc_accepts_current_owned_state_names() -> None:
    attempt_id = "ab" * 16
    _require_known_windows_worker_state_names(
        (
            "worker-opt-in.jsonl",
            "worker-opt-in.jsonl.lock",
            "worker-native-release-approvals.jsonl",
            "worker-native-release-approvals.jsonl.lock",
            "worker-native-backend-release-v1.whl",
            "worker-history-preparation-v1.json",
            "worker-history-preparation-v1.json.stage",
            "worker-history-checkpoint-v1.json",
            "worker-history-checkpoint-v1.json.stage",
            "worker-history-base-opt-in-v1.json",
            "worker-history-base-opt-in-v1.json.stage",
            "worker-history-base-receipt-v1.json",
            "worker-history-base-supervisor-v1.json",
            "worker-history-base-c5-v1.json",
            "worker-history-base-launch-intent-v1.json",
            "worker-history-base-native-provisioning-v1.json",
            "worker-activation-receipts.jsonl",
            "worker-activation-receipts.jsonl.lock",
            "worker-activation-state.jsonl",
            "worker-activation-state.jsonl.lock",
            "worker-activation-state.h00000001.json",
            "worker-supervisor.jsonl",
            "worker-supervisor.jsonl.lock",
            f"worker-launch-intent-{attempt_id}.json",
            f"worker-native-provisioning-{attempt_id}.jsonl",
            f"worker-native-provisioning-{attempt_id}.jsonl.lock",
            f"worker-stage-retired-{attempt_id}.json",
            "committed-sets.jsonl",
        )
    )


@pytest.mark.skipif(os.name != "nt", reason="native Windows Product root required")
def test_windows_worker_history_source_capture_is_private_and_fail_closed(
    tmp_path: Path,
) -> None:
    from loushang.coding._plugin_lifecycle import (
        resolve_ephemeral_coding_plugin_lifecycle_state_layout,
    )
    from loushang.coding.package_pre_b_snapshot import (
        cutover_and_bootstrap_coding_package_product,
    )
    from loushang.coding.package_product_runtime import (
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.package_product_worker_windows_checkpoint import (
        publish_coding_windows_worker_history_checkpoint,
    )
    from loushang.coding.package_product_worker_windows_history_preparation import (
        prepare_coding_windows_worker_history,
    )
    from loushang.coding.package_product_worker_windows_history_sources import (
        CodingWindowsWorkerHistorySemanticReadV1,
        capture_coding_windows_worker_history_sources,
        read_coding_windows_worker_history_semantics,
        review_coding_windows_worker_settled_history_sources,
    )
    from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
    from loushang.harness.config.agent import SettingsManager
    from loushang.harness.package_product.product_runtime import (
        PackageProductRuntimeRequestV1,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
        open_windows_regular_file_at,
        windows_flush_directory,
        windows_flush_file,
        windows_unlink_at,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="e" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        before = capture_coding_windows_worker_history_sources(product)
        settled = review_coding_windows_worker_settled_history_sources(product)
        assert settled.source_snapshot == before
        semantic = read_coding_windows_worker_history_semantics(product)
        assert semantic.source_snapshot == before
        assert semantic.offline_recovery.store_id == before.store_id
        assert semantic.offline_recovery.gc_revision_refs == frozenset()
        with patch(
            "loushang.coding.package_legacy_windows_receipt.windows_rename_at",
            side_effect=RuntimeError("injected preparation publication interruption"),
        ):
            with pytest.raises(RuntimeError, match="publication interruption"):
                prepare_coding_windows_worker_history(product)
        with pytest.raises(ValueError, match="stage remains"):
            capture_coding_windows_worker_history_sources(product)
        prepared = prepare_coding_windows_worker_history(product)
        assert prepared.source_snapshot == before
        assert prepare_coding_windows_worker_history(product) == prepared
        assert capture_coding_windows_worker_history_sources(product) == before
        assert read_coding_windows_worker_history_semantics(product) == semantic
        with patch(
            "loushang.coding.package_legacy_windows_receipt.windows_rename_at",
            side_effect=RuntimeError("injected checkpoint publication interruption"),
        ):
            with pytest.raises(RuntimeError, match="publication interruption"):
                publish_coding_windows_worker_history_checkpoint(product)
        with pytest.raises(ValueError, match="stage remains"):
            capture_coding_windows_worker_history_sources(product)
        checkpoint = publish_coding_windows_worker_history_checkpoint(product)
        assert checkpoint.source_snapshot == before
        assert publish_coding_windows_worker_history_checkpoint(product) == checkpoint
        assert capture_coding_windows_worker_history_sources(product) == before
        with pytest.raises(ValueError, match="semantic read is invalid"):
            CodingWindowsWorkerHistorySemanticReadV1(
                source_snapshot=before,
                offline_recovery=replace(
                    semantic.offline_recovery, store_id="different-store"
                ),
            )
        session_id = "windows-history-source-active"
        factory = product.factory_for_session(
            session_id=session_id,
            cwd=workspace,
            runtime_id="runtime:windows-history-source-active",
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=session_id, cwd=str(workspace)
            )
        )
        try:
            with pytest.raises(ValueError, match="runtime remains active"):
                capture_coding_windows_worker_history_sources(product)
            with pytest.raises(ValueError, match="runtime remains active"):
                review_coding_windows_worker_settled_history_sources(product)
            with pytest.raises(ValueError, match="runtime remains active"):
                read_coding_windows_worker_history_semantics(product)
        finally:
            runtime.dispose_runtime()
        name = "worker-opt-in.jsonl.lock"
        payload = b"history-source-byte-identity"
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            with WindowsPrivateDirectoryAcl() as acl:
                descriptor = open_windows_regular_file_at(
                    root,
                    name,
                    create_new=True,
                    write=True,
                    security_descriptor=acl.security_descriptor,
                )
                try:
                    assert os.write(descriptor, payload) == len(payload)
                    windows_flush_file(descriptor)
                finally:
                    os.close(descriptor)
            windows_flush_directory(root)
        captured = capture_coding_windows_worker_history_sources(product)
        assert captured.snapshot_digest != before.snapshot_digest
        assert {item.name for item in captured.files} == {
            item.name for item in before.files
        } | {name}
        retained = next(item for item in captured.files if item.name == name)
        assert retained.size == len(payload)
        assert retained.sha256_digest == sha256(payload).hexdigest()

        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            with WindowsPrivateDirectoryAcl() as acl:
                unknown = open_windows_regular_file_at(
                    root,
                    "worker-future-reference.json",
                    create_new=True,
                    write=True,
                    security_descriptor=acl.security_descriptor,
                )
                os.close(unknown)
            windows_flush_directory(root)
        with pytest.raises(ValueError, match="state owner is unrecognized"):
            capture_coding_windows_worker_history_sources(product)
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            windows_unlink_at(root, "worker-future-reference.json")
            windows_unlink_at(root, name)
            windows_flush_directory(root)
        assert (
            capture_coding_windows_worker_history_sources(product).files == before.files
        )

        stage_name = "worker-stage-retired-" + "ab" * 16 + ".json.stage"
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            with WindowsPrivateDirectoryAcl() as acl:
                staged = open_windows_regular_file_at(
                    root,
                    stage_name,
                    create_new=True,
                    write=True,
                    security_descriptor=acl.security_descriptor,
                )
                os.close(staged)
            windows_flush_directory(root)
        with pytest.raises(ValueError, match="history stage remains"):
            capture_coding_windows_worker_history_sources(product)
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            windows_unlink_at(root, stage_name)
            windows_flush_directory(root)
    finally:
        owner.close()


@pytest.mark.parametrize(
    "name",
    (
        "worker-future-reference.json",
        "worker-native-release-v1",
        ".worker-future-reference.json.stage",
        "worker-opt-in.jsonl.stage",
        "worker-native-provisioning-" + "ab" * 16 + ".jsonl.stage",
        "worker-activation-state.h00000001.json.stage",
        "worker-activation-state.h0000001.json",
        "worker-payload-" + "ab" * 16,
    ),
)
def test_windows_worker_gc_rejects_unknown_or_staged_owner(name: str) -> None:
    with pytest.raises(ValueError, match="state owner is unrecognized"):
        _require_known_windows_worker_state_names((name,))


def test_windows_worker_gc_requires_settled_c5_to_match_launched_attempt_and_receipt() -> (
    None
):
    retained = CodingProductWorkerRetainedAttemptV1(
        attempt_id="a" * 32,
        receipt_fingerprint="r",
        policy_fingerprint="p",
        owner_generation=1,
        cleanup_contract_version=2,
        host_identity="host",
        boot_identity="boot",
        phase="settled",
        last_seen_revision=3,
        current=False,
    )
    launched = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=retained.attempt_id,
        payload_directory_identity=None,
        native_phase=None,
        native_revision=None,
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
        native_job_name="job",
        launch_request_fingerprint="request",
        launch_receipt_fingerprint="r",
    )
    state: dict[str, object] = {"attempts": {}, "publications": {}}
    jobs = {retained.attempt_id: True}
    _require_c5_gc_history(state, (retained,), (launched,), {"r": ("p", 1)}, jobs)
    retired_before_launch = replace(
        launched,
        attempt_id="b" * 32,
        native_job_name=None,
        launch_request_fingerprint=None,
        launch_receipt_fingerprint=None,
    )
    _require_c5_gc_history(
        state, (retained,), (launched, retired_before_launch), {"r": ("p", 1)}, jobs
    )
    with pytest.raises(ValueError, match="C5 owner is incomplete"):
        _require_c5_gc_history(None, (retained,), (launched,), {"r": ("p", 1)}, jobs)
    with pytest.raises(ValueError, match="C5 activation remains active"):
        _require_c5_gc_history(
            {"attempts": {}, "publications": {"p": {}}},
            (retained,),
            (launched,),
            {"r": ("p", 1)},
            jobs,
        )
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(state, (), (launched,), {"r": ("p", 1)}, jobs)
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(
            state, (retained,), (launched,), {"r": ("changed", 1)}, jobs
        )
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(
            state,
            (replace(retained, phase="retired"),),
            (launched,),
            {"r": ("p", 1)},
            jobs,
        )
    with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
        _require_c5_gc_history(
            state,
            (retained,),
            (replace(launched, launch_receipt_fingerprint="changed"),),
            {"r": ("p", 1)},
            jobs,
        )
    for native_observation in (False, None):
        with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
            _require_c5_gc_history(
                state,
                (retained,),
                (launched,),
                {"r": ("p", 1)},
                {retained.attempt_id: native_observation},
            )
    for invalid in (
        replace(retained, cleanup_contract_version=1),
        replace(retained, owner_generation=2),
    ):
        with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
            _require_c5_gc_history(
                state, (invalid,), (launched,), {"r": ("p", 1)}, jobs
            )
