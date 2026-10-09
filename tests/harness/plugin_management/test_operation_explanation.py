from __future__ import annotations

import json

import pytest

from loushang.harness.plugin_management.application import (
    PluginManagementApplicationResultV1,
)
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationProjector,
    PluginOperationExplanationRequestV1,
    project_plugin_operation_explanation,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
    PluginManagementOperationResultV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredSelectionV1,
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageClassificationBasisFactV1,
    PackageClassificationBasisKind,
    PackageClassificationFactsV1,
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.product_handoff import (
    package_product_command_identity,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def _package_operation(plugin_id: str):
    kinds: tuple[PackageClassificationBasisKind, ...] = (
        "explicit_plugin_intent",
        "existing_plugin_binding",
        "existing_plugin_history",
        "independent_non_plugin_authority",
    )
    facts = PackageClassificationFactsV1(
        facts=tuple(
            PackageClassificationBasisFactV1(
                kind=kind,
                present=kind == "explicit_plugin_intent",
                authority_id="test:classification",
                owner_revision="test:1",
            )
            for kind in kinds
        ),
        policy_revision="test:classification",
        classifier_epoch=1,
    )
    request = PackageLifecycleRequestV1(
        operation_id="test:install",
        action="install",
        product_id="coding",
        scope_id="workspace-1",
        requested_package="reviewpack==1",
        requested_plugin_id=plugin_id,
        canonical_source_identity="local:/private/secret-wheel.whl",
        policy_revision="test:package",
        quota_profile_revision="test:quota",
        resolution_environment_fingerprint="e" * 64,
        classification_facts=facts,
    )
    status = PackageLifecycleStatusV1(
        operation_id=request.operation_id,
        request_fingerprint=request.request_fingerprint,
        phase="accepted",
        disposition="active",
        attempt_epoch=1,
        journal_revision=1,
        attempt_revision=0,
    )
    return request, status


class _PackageOperations:
    def __init__(self, plugin_id: str) -> None:
        self.observed = _package_operation(plugin_id)

    def read_operation(self, operation_id: str):
        return self.observed if operation_id == "test:install" else None


class _ManagementCommands:
    def __init__(self, *, package_plugin_id: str = "reviewpack") -> None:
        request, _status = _package_operation(package_plugin_id)
        self.command_id = package_product_command_identity(
            request.operation_id, request.request_fingerprint
        )[0]
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id="workspace-1",
            plugin_id="reviewpack",
        )
        revision = PluginPackageRevisionRefV1(
            plugin_id="reviewpack",
            plugin_version="1",
            package_content_digest="a" * 64,
            dependency_lock_digest="b" * 64,
            package_source_identity="local:/private/secret-wheel.whl",
        )
        self.event = PluginManagementOperationEventV1.accepted(
            journal_revision=2,
            command=PluginManagementCommandV1(
                action="install",
                mutation=PluginDesiredStateMutationV1(
                    operation_id=self.command_id,
                    idempotency_key="test:install",
                    expected_inventory_revision=0,
                    installation_key=key,
                    desired_state="installed_disabled",
                    package_revision=revision,
                    actor_id="test:operator",
                    policy_revision="test:management",
                ),
            ),
        )

    def operation(self, operation_id: str, *, correlation_id: str):
        if operation_id != self.command_id:
            return None
        return PluginManagementApplicationResultV1(
            correlation_id=correlation_id,
            operation=self.event,
        )


def test_operation_explanation_matches_identity_without_claiming_handoff() -> None:
    result = PluginOperationExplanationProjector(
        package_operations=_PackageOperations("reviewpack"),
        management_commands=_ManagementCommands(),
        clock_ns=lambda: 123,
    ).explain_operation("test:install", correlation_id="test:explain")

    assert result.join_status == "same_identity"
    assert result.management_operation_id.startswith("package:")
    assert result.management_operation_id != result.operation_id
    assert result.management_status == "observed"
    assert result.package.status == "observed"
    assert "package_product_handoff" in result.evidence_gaps
    assert result.snapshot_status == "partial_evidence"
    encoded = json.dumps(result.to_dict())
    assert "secret-wheel" not in encoded
    assert "/private/" not in encoded


def test_operation_explanation_reports_cross_owner_identity_conflict() -> None:
    package = _PackageOperations("otherpack")
    result = PluginOperationExplanationProjector(
        package_operations=package,
        management_commands=_ManagementCommands(package_plugin_id="otherpack"),
        clock_ns=lambda: 123,
    ).explain_operation("test:install", correlation_id="test:conflict")

    assert result.join_status == "identity_conflict"
    assert "owner_identity_conflict" in result.evidence_gaps


def test_operation_explanation_transport_rejects_cross_scope_owner_facts() -> None:
    result = PluginOperationExplanationProjector(
        package_operations=_PackageOperations("reviewpack"),
        management_commands=_ManagementCommands(),
        clock_ns=lambda: 123,
    ).explain_operation("test:install", correlation_id="test:explain")

    class Query:
        def explain_plugin_operation(self, _request: PluginOperationExplanationRequestV1):
            return result

    with pytest.raises(ValueError, match="changed Product request"):
        project_plugin_operation_explanation(
            Query(),
            PluginOperationExplanationRequestV1(
                correlation_id="test:explain",
                product_id="coding",
                scope_id="workspace:foreign",
                operation_id="test:install",
            ),
        )


def test_successful_a1_enable_has_no_package_handoff_gap() -> None:
    installed = _ManagementCommands()
    key = installed.event.command.mutation.installation_key
    package = installed.event.command.mutation.package_revision
    assert package is not None
    instance = PluginInstanceRevisionRef(
        instance_id="reviewpack-instance", plugin_id="reviewpack", revision=1
    )
    mutation = PluginDesiredStateMutationV1(
        operation_id="test:enable",
        idempotency_key="test:enable",
        expected_inventory_revision=1,
        installation_key=key,
        desired_state="installed_enabled",
        package_revision=None,
        actor_id="coding:cli",
        policy_revision="test:management",
    )
    transition = PluginDesiredStateTransitionV1(
        inventory_revision=2,
        transition_kind="enable",
        mutation=mutation,
        previous_state=PluginInstallationStateV1(
            installation_key=key,
            selection=PluginDesiredSelectionV1(
                desired_state="installed_disabled",
                package_revision=package,
                instance_revision_ref=None,
            ),
            latest_instance_revision_ref=None,
        ),
        committed_state=PluginInstallationStateV1(
            installation_key=key,
            selection=PluginDesiredSelectionV1(
                desired_state="installed_enabled",
                package_revision=package,
                instance_revision_ref=instance,
            ),
            latest_instance_revision_ref=instance,
        ),
    )
    event = PluginManagementOperationEventV1.terminal(
        journal_revision=3,
        command=PluginManagementCommandV1(action="enable", mutation=mutation),
        result=PluginManagementOperationResultV1(
            disposition="succeeded", transition=transition, error_code=None
        ),
    )

    class NoPackage:
        def read_operation(self, _operation_id: str):
            return None

    class Management:
        def operation(self, operation_id: str, *, correlation_id: str):
            return (
                PluginManagementApplicationResultV1(
                    correlation_id=correlation_id, operation=event
                )
                if operation_id == "test:enable"
                else None
            )

    result = PluginOperationExplanationProjector(
        package_operations=NoPackage(), management_commands=Management()
    ).explain_operation("test:enable", correlation_id="test:a1-enable")
    assert result.to_dict()["operationKind"] == "a1_desired"
    assert result.join_status == "management_only"
    assert result.management_disposition == "succeeded"
    assert result.management_actor_id == "coding:cli"
    assert result.handoff_evidence == "not_queried"
    assert "package_operation" not in result.evidence_gaps
    assert "package_product_handoff" not in result.evidence_gaps
