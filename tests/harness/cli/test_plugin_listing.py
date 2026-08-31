from __future__ import annotations

from loushang.harness.cli.plugin_listing import list_plugin_records
from loushang.harness.cli.plugin_management import PluginManagementCliBinding
from loushang.harness.plugin_management import (
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginManagementApplicationPorts,
    PluginManagementCommandApplication,
    PluginManagementCommandV1,
    PluginManagementReadModelProjector,
    PluginManagementService,
    PluginManagementSourceRecordV1,
    PluginManagementSourceSnapshotV1,
    PluginPackageRevisionRefV1,
)


def test_plugin_listing_projects_common_read_model_without_settings_peer(
    tmp_path,
) -> None:
    desired = PluginDesiredStateLedger(tmp_path / "desired.jsonl")
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
    )
    event = service.submit(
        PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id="install-review",
                idempotency_key="install-review",
                expected_inventory_revision=0,
                installation_key=_key(),
                desired_state="installed_disabled",
                package_revision=_package(),
                actor_id="test",
                policy_revision="test",
            ),
        )
    )
    assert event.result is not None
    source = _Source(
        PluginManagementSourceSnapshotV1(
            owner_revision="settings:1",
            records=(
                PluginManagementSourceRecordV1(
                    installation_key=_key(),
                    source_identity="local:/plugins/review-pack",
                    source_kind="local",
                    availability="available",
                    source_location="/plugins/review-pack",
                    plugin_version="2",
                    manifest_enabled_default=True,
                ),
            ),
        )
    )
    binding = PluginManagementCliBinding(
        ports=PluginManagementApplicationPorts(
            commands=PluginManagementCommandApplication(service),
            queries=PluginManagementReadModelProjector(
                desired_state=desired,
                operations=service,
                source=source,
            ),
        ),
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        actor_id="cli",
        policy_revision="cli-v1",
    )

    records = list_plugin_records(binding)

    assert records == [
        {
            "name": "review-pack",
            "version": "1",
            "path": "/plugins/review-pack",
            "source": "/plugins/review-pack",
            "kind": "local",
            "enabled": False,
            "desiredState": "installed_disabled",
            "convergence": "unknown",
            "migrationStatus": None,
        }
    ]


class _Source:
    def __init__(self, snapshot: PluginManagementSourceSnapshotV1) -> None:
        self.value = snapshot

    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        return self.value


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="review-pack",
    )


def _package() -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="review-pack",
        plugin_version="1",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="local:/plugins/review-pack",
    )
