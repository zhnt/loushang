from __future__ import annotations

import pytest

from loushang.harness.plugin_management.application import (
    PluginManagementApplicationPorts,
    PluginManagementApplicationResultV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandAuthorityV1,
    PluginDesiredCommandRepairError,
    resume_plugin_desired_operation,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)


def test_desired_repair_refuses_package_install_operation_without_submission() -> None:
    package = PluginPackageRevisionRefV1(
        plugin_id="reviewpack", plugin_version="1",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        package_source_identity="/private/source/reviewpack.whl",
    )
    command = PluginManagementCommandV1(
        action="install",
        mutation=PluginDesiredStateMutationV1(
            operation_id="package:install", idempotency_key="package:install",
            expected_inventory_revision=0,
            installation_key=PluginInstallationKeyV1(
                product_id="coding", installation_scope="workspace",
                scope_id="workspace:test", plugin_id="reviewpack",
            ),
            desired_state="installed_disabled", package_revision=package,
            actor_id="coding:sdk", policy_revision="coding-plugin-management-sdk-v1",
        ),
    )
    submitted: list[object] = []

    class Commands:
        def operation(self, _operation_id: str, *, correlation_id: str):
            return PluginManagementApplicationResultV1(
                correlation_id=correlation_id,
                operation=PluginManagementOperationEventV1.accepted(
                    journal_revision=1, command=command,
                ),
            )

        def submit(self, request: object) -> None:
            submitted.append(request)

    class Queries:
        def snapshot(self, _query: object) -> None:
            raise AssertionError("repair must not query the read model")

    ports = PluginManagementApplicationPorts(
        commands=Commands(), queries=Queries(),  # type: ignore[arg-type]
    )
    authority = PluginDesiredCommandAuthorityV1(
        product_id="coding", installation_scope="workspace",
        scope_id="workspace:test", actor_id="coding:sdk",
        policy_revision="coding-plugin-management-sdk-v1",
    )
    with pytest.raises(PluginDesiredCommandRepairError) as refused:
        resume_plugin_desired_operation(
            ports, authority, operation_id="package:install",
            correlation_id="sdk:repair",
        )
    assert refused.value.code == "plugin_management_repair_unsupported_operation"
    assert submitted == []
