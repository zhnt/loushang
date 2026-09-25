from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_target import (
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
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

    prefix = (
        sys.executable,
        "-m",
        "loushang.coding.cli.package_gc",
        "--workspace",
        str(workspace),
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

    assert run("list").returncode == 1
    prepared = run("prepare")
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout)["disposition"] == "prepared"
    listed = run("list")
    assert listed.returncode == 0, listed.stderr
    candidates = json.loads(listed.stdout)["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["pluginId"] == "coding.arch.default"
    candidate_id = candidates[0]["candidateId"]
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
