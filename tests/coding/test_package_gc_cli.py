from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_dependency_wheel,
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    open_posix_local_wheel_product_root_gc,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_dependency_journal import (
    PackageDependencyGcJournal,
    PackageDependencyGcStartV1,
)
from loushang.harness.plugin_management.package_gc_target import (
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PackagePhysicalStagingError,
    PosixPackageDependencyMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWorkerAdmissionV1,
)
from tests.coding.test_package_worker_candidate_wheel import (
    _dependency_library_wheel,
    _worker_wheel,
)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted GC")
def test_offline_gc_command_prepares_exact_candidate_and_replays_result(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="d" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = owner.runtime_owner.product_owner
        state = product.desired_state.snapshot()
        selected = next(
            item
            for item in state.installations
            if item.installation_key.plugin_id == "coding.arch.default"
        )
        revision = selected.selection.package_revision
        assert revision is not None
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:remove-arch-for-cli",
                    idempotency_key="operator:remove-arch-for-cli",
                    expected_inventory_revision=state.inventory_revision,
                    installation_key=selected.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        settlements = PackageStoreSettlementJournal(
            product.state_root / "root-settlements.jsonl"
        )
        target = resolve_plugin_package_gc_root_target(
            revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=PackageCommittedSetJournal(
                product.state_root / "committed-sets.jsonl"
            ).records(),
            settlements=settlements.records(),
        )
        exact_root = product.plugin_store_root / target.settlement.final_name
        other_roots = tuple(
            product.plugin_store_root / item.final_name
            for item in settlements.records()
            if item.settlement_id != target.settlement_id
        )
        assert exact_root.is_dir()
        assert all(root.is_dir() for root in other_roots)
    finally:
        owner.close()

    entrypoint = Path(sys.executable).with_name("loushang-package-gc")
    assert entrypoint.is_file()
    prefix = (str(entrypoint), "--workspace", str(workspace))

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (*prefix, *args),
            env=environ,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )

    assert run("list").returncode == 1
    prepared = run("prepare")
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout)["disposition"] == "prepared"
    listed = run("list")
    assert listed.returncode == 0, listed.stderr
    listing = json.loads(listed.stdout)
    assert listing["dependencyRetention"] == []
    assert listing["dependencyRepairs"] == []
    candidates = listing["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["pluginId"] == "coding.arch.default"
    candidate_id = candidates[0]["candidateId"]
    missing_debt = run("inspect-dependency-debt", "--start-id", "0" * 64)
    assert missing_debt.returncode == 1
    assert (
        "plugin_package_gc_dependency_terminal_debt_unavailable" in missing_debt.stderr
    )
    missing_repair = run("inspect-dependency-repair", "--review-id", "0" * 64)
    assert missing_repair.returncode == 1
    assert (
        "plugin_package_gc_dependency_repair_review_unavailable"
        in missing_repair.stderr
    )
    unreviewed = run(
        "review-dependency-debt",
        "--start-id",
        "0" * 64,
        "--terminal-attempt-id",
        "1" * 64,
        "--settlement-id",
        "2" * 64,
        "--error-code",
        "package_publication_root_untrusted",
        "--remediation-reference",
        "incident:reviewed",
    )
    assert unreviewed.returncode == 1
    assert "plugin_package_gc_dependency_terminal_debt_unavailable" in unreviewed.stderr
    wrong_prior = run(
        "review-dependency-debt",
        "--start-id",
        "0" * 64,
        "--terminal-attempt-id",
        "1" * 64,
        "--settlement-id",
        "2" * 64,
        "--error-code",
        "package_publication_root_untrusted",
        "--remediation-reference",
        "incident:second-remediation",
        "--prior-repair-result-id",
        "3" * 64,
    )
    assert wrong_prior.returncode == 1
    assert (
        "plugin_package_gc_dependency_terminal_debt_unavailable" in wrong_prior.stderr
    )
    unapproved_repair = run(
        "repair-dependency-debt",
        "--review-id",
        "0" * 64,
        "--attempt-key",
        "first",
    )
    assert unapproved_repair.returncode == 1
    assert (
        "plugin_package_gc_dependency_repair_review_unavailable"
        in unapproved_repair.stderr
    )
    missing = run("delete", "--candidate-id", "0" * 64, "--attempt-key", "first")
    assert missing.returncode == 1
    premature_retry = run(
        "retry", "--reservation-id", "0" * 64, "--attempt-key", "first"
    )
    assert premature_retry.returncode == 1
    assert "plugin_package_gc_deletion_not_started" in premature_retry.stderr
    assert exact_root.is_dir()

    deleted = run("delete", "--candidate-id", candidate_id, "--attempt-key", "first")
    assert deleted.returncode == 0, deleted.stderr
    result = json.loads(deleted.stdout)
    assert result["disposition"] == "succeeded"
    assert result["settlementId"] == target.settlement_id
    assert not exact_root.exists()
    assert all(root.is_dir() for root in other_roots)

    repeated = run("delete", "--candidate-id", candidate_id, "--attempt-key", "first")
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout) == result
    retry = run(
        "retry",
        "--reservation-id",
        result["reservationId"],
        "--attempt-key",
        "second",
    )
    assert retry.returncode == 0, retry.stderr
    assert json.loads(retry.stdout) == result
    final = run("list")
    assert final.returncode == 0, final.stderr
    assert json.loads(final.stdout)["statuses"][0]["state"] == "succeeded"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted GC")
def test_installed_gc_command_repairs_real_product_dependency_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}
    monkeypatch.setenv("LOUSHANG_HOME", environ["LOUSHANG_HOME"])
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="e" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    source = tmp_path / "reviewworker-2-py3-none-manylinux_2_17_x86_64.whl"
    source.write_bytes(_worker_wheel(shape="dependency", version="2"))
    dependency = tmp_path / "dependency-1-py3-none-any.whl"
    dependency.write_bytes(_dependency_library_wheel())
    admit_coding_external_worker_wheel(
        lifecycle,
        source=source,
        admission=PackageProductLocalWorkerAdmissionV1(
            contribution_id="query-provider",
            owner_id="coding",
            native_platform="linux-x86_64",
        ),
    )
    admit_coding_external_dependency_wheel(lifecycle, source=dependency)

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        (binding,) = tuple(
            item for item in product.policy.bindings if item.plugin_id == "reviewworker"
        )
        runtime = product.factory_for_session(
            session_id="dependency-gc-install",
            cwd=workspace,
            runtime_id="dependency-gc-install",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="dependency-gc-install",
                cwd=str(workspace),
            )
        )
        try:
            runtime.activate()
            installed = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="dependency-gc-install",
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert installed.handled and installed.record is not None
            assert installed.record.lifecycle == "installed", installed.evidence
        finally:
            runtime.dispose_runtime()
        snapshot = product.desired_state.snapshot()
        (installation,) = tuple(
            item
            for item in snapshot.installations
            if item.installation_key.plugin_id == "reviewworker"
        )
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="dependency-gc-remove",
                    idempotency_key="dependency-gc-remove",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=installation.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
    finally:
        owner.close()

    entrypoint = Path(sys.executable).with_name("loushang-package-gc")
    assert entrypoint.is_file()
    prefix = (
        str(entrypoint), "--workspace", str(workspace), "--worker-candidates"
    )

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (*prefix, *args),
            env=environ,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )

    prepared = run("prepare")
    assert prepared.returncode == 0, prepared.stderr
    listed = run("list")
    assert listed.returncode == 0, listed.stderr
    (candidate,) = json.loads(listed.stdout)["candidates"]
    assert candidate["pluginId"] == "reviewworker"
    deleted = run(
        "delete", "--candidate-id", candidate["candidateId"],
        "--attempt-key", "dependency-root",
    )
    assert deleted.returncode == 0, deleted.stderr
    assert json.loads(deleted.stdout)["disposition"] == "succeeded"

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert isinstance(product, PosixLocalWheelProductSessionOwner)
        gc = open_posix_local_wheel_product_root_gc(product)
        (orphan,) = gc.dependency_inspections()
        assert orphan.retention.disposition == "orphan_candidate"
        assert orphan.target is not None
        settlement = orphan.target.settlement
        dependency_tree = product.dependency_store_root / settlement.final_name
        assert dependency_tree.is_dir()

        def fail_store_delete(*args: object, **kwargs: object) -> object:
            raise PackagePhysicalStagingError(
                "injected Product dependency Store failure",
                code="package_publication_root_untrusted",
            )

        with patch.object(
            PosixPackageDependencyMaterializationStore,
            "delete_settlement",
            fail_store_delete,
        ):
            failed = gc.delete_dependency(
                orphan.retention.dependency_ref.ref_id,
                expected_settlement_id=settlement.settlement_id,
                operation_id="dependency-gc-terminal",
                idempotency_key="dependency-gc-terminal",
            )
        assert failed.disposition == "terminal_failure"
        assert failed.error_code == "package_publication_root_untrusted"
        assert dependency_tree.is_dir()
        (start, _) = PackageDependencyGcJournal(
            product.state_root / "dependency-gc.jsonl"
        ).events()
        assert isinstance(start, PackageDependencyGcStartV1)
    finally:
        owner.close()

    inspected = run("inspect-dependency-debt", "--start-id", start.start_id)
    assert inspected.returncode == 0, inspected.stderr
    debt = json.loads(inspected.stdout)
    assert debt["attemptId"] == failed.attempt_id
    assert debt["settlementId"] == settlement.settlement_id
    wrong_review = run(
        "review-dependency-debt",
        "--start-id", start.start_id,
        "--terminal-attempt-id", failed.attempt_id,
        "--settlement-id", "0" * 64,
        "--error-code", failed.error_code,
        "--remediation-reference", "incident:wrong-settlement",
    )
    assert wrong_review.returncode == 1
    assert "plugin_package_gc_dependency_repair_review_refused" in wrong_review.stderr
    assert dependency_tree.is_dir()
    unreviewed = run(
        "repair-dependency-debt",
        "--review-id", "0" * 64,
        "--attempt-key", "unreviewed",
    )
    assert unreviewed.returncode == 1
    assert "plugin_package_gc_dependency_repair_review_unavailable" in unreviewed.stderr
    assert dependency_tree.is_dir()
    reviewed = run(
        "review-dependency-debt",
        "--start-id", start.start_id,
        "--terminal-attempt-id", failed.attempt_id,
        "--settlement-id", settlement.settlement_id,
        "--error-code", failed.error_code,
        "--remediation-reference", "incident:real-product-dependency-debt",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    review_id = json.loads(reviewed.stdout)["reviewId"]
    repaired = run(
        "repair-dependency-debt",
        "--review-id", review_id,
        "--attempt-key", "reviewed-repair",
    )
    assert repaired.returncode == 0, repaired.stderr
    result = json.loads(repaired.stdout)
    assert result["disposition"] == "succeeded"
    assert result["settlementId"] == settlement.settlement_id
    assert not dependency_tree.exists()
    replay = run(
        "repair-dependency-debt",
        "--review-id", review_id,
        "--attempt-key", "reviewed-repair",
    )
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout) == result
    ordinary_retry = run(
        "retry-dependency",
        "--start-id", start.start_id,
        "--attempt-key", "ordinary-after-repair",
    )
    assert ordinary_retry.returncode == 0, ordinary_retry.stderr
    retry_result = json.loads(ordinary_retry.stdout)
    assert retry_result["attemptId"] == failed.attempt_id
    assert retry_result["disposition"] == "terminal_failure"
    status = run("inspect-dependency-repair", "--review-id", review_id)
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["state"] == "succeeded"
