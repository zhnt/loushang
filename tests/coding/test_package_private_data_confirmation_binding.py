"""Fenced Coding Product owns the confirmation journal location without issuing it."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from loushang.coding.package_product_runtime import (
    open_coding_builtin_product_runtime_owner,
    open_coding_fenced_product_application_owner,
    open_coding_package_product_state,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)


def test_confirmation_owner_is_pinned_to_fenced_product_state_without_issuance(
    tmp_path: Path,
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
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        state = open_coding_package_product_state(lifecycle, owner.epoch_runtime)
        expected = product.state_root / "private-data-confirmations.jsonl"
        assert state.private_data_confirmation.path == expected
        assert state.private_data_deletion.path == (
            product.state_root / "private-data-deletions.jsonl"
        )
        assert not expected.exists()
        foreign = replace(
            state,
            private_data_confirmation=PluginPrivateDataConfirmationJournal(
                tmp_path / "foreign-confirmations.jsonl"
            ),
        )
        with pytest.raises(ValueError, match="state authority changed"):
            open_coding_builtin_product_runtime_owner(
                lifecycle,
                owner.epoch_runtime,
                foreign,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
        foreign_deletion = replace(
            state,
            private_data_deletion=CodingArchPrivateDataDeletionJournal(
                tmp_path / "foreign-state"
            ),
        )
        with pytest.raises(ValueError, match="state authority changed"):
            open_coding_builtin_product_runtime_owner(
                lifecycle,
                owner.epoch_runtime,
                foreign_deletion,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
        assert not expected.exists()
        assert not state.private_data_deletion.path.exists()
        assert not (tmp_path / "foreign-confirmations.jsonl").exists()
    finally:
        owner.close()
