from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

import loushang.coding.package_product_runtime as product_runtime_module
from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
def test_expanded_product_policy_reopens_existing_builtin_selections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    original_policy = product_runtime_module.coding_builtin_product_local_wheel_policy

    def extended_policy(*args, **kwargs):
        policy = original_policy(*args, **kwargs)
        extra = PackageProductLocalWheelBindingV1(
            source_identity=str(policy.source_root / "review_pack-1-py3-none-any.whl"),
            requested_package="review-pack==1",
            plugin_id="review-pack",
            artifact_digest="b" * 64,
            plugin_manifest_path="review_pack/plugin.json",
            source_trust_class="legacy-local-reacquired",
        )
        expanded = replace(
            policy,
            bindings=tuple(
                sorted((*policy.bindings, extra), key=lambda item: item.source_identity)
            ),
        )
        assert expanded.authority_revision != policy.authority_revision
        return expanded

    monkeypatch.setattr(
        product_runtime_module,
        "coding_builtin_product_local_wheel_policy",
        extended_policy,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        factory = owner.runtime_owner.product_owner.factory_for_session(
            session_id="policy-reopen",
            cwd=workspace,
            runtime_id="policy-reopen",
        )
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="policy-reopen", cwd=str(workspace)
            )
        )
        try:
            runtime = binding.activate()
            for plugin_id in (
                "coding.base",
                "coding.lsp.default",
                "coding.arch.default",
            ):
                selected = runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                )
                assert selected.verified_manifest().name == plugin_id
        finally:
            binding.dispose_runtime()
    finally:
        owner.close()
