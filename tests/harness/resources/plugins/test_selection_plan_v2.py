from __future__ import annotations

from dataclasses import fields, replace

import pytest

from loushang.harness.resources.plugins.selection import (
    PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION,
    PLUGIN_PREFLIGHT_CONTEXT_VERSION,
    PLUGIN_SELECTION_PLAN_VERSION,
    PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelectionError,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)


def test_selection_plan_v2_is_the_single_exact_product_input() -> None:
    plan = _plan()

    assert PLUGIN_PREFLIGHT_CONTEXT_VERSION == 1
    assert PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION == 1
    assert PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION == 1
    assert PLUGIN_SELECTION_PLAN_VERSION == 2
    assert plan.plan_version == 2
    assert plan.context.context_version == 1
    assert plan.context.product_id == "coding"
    assert plan.source_trust_snapshots[0].trust_snapshot_version == 1
    assert plan.effective_configuration_set.configuration_set_version == 1
    assert plan.allowed_authority_ceiling == ("filesystem", "process")
    assert tuple(item.name for item in fields(plan)) == (
        "context",
        "selected_plugin_ids",
        "selected_contributions",
        "source_trust_snapshots",
        "effective_configuration_set",
        "allowed_authority_ceiling",
        "plan_version",
    )
    assert tuple(item.name for item in fields(plan.context)) == (
        "product_id",
        "scope_id",
        "policy_revision",
        "instance_revision_refs",
        "context_version",
    )
    assert not hasattr(plan, "product_id")
    assert not hasattr(plan, "source_trust")
    assert not hasattr(plan, "allowed_authorities")


def test_effective_configuration_is_frozen_and_accepts_exact_secret_refs() -> None:
    secret_ref = {
        "$secretRef": {
            "authorityClass": "credential.read",
            "providerId": "system-keyring",
            "referenceId": "git-token",
            "rotationEpoch": 3,
            "secretReferenceVersion": 1,
        }
    }
    entry = PluginEffectiveConfigurationEntry(
        plugin_id="review-pack",
        contribution_id="review-provider",
        configuration={"auth": secret_ref, "mode": "review"},
    )

    assert entry.to_dict() == {
        "configuration": {"auth": secret_ref, "mode": "review"},
        "contributionId": "review-provider",
        "pluginId": "review-pack",
    }
    with pytest.raises(TypeError):
        entry.configuration["mode"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    "secret_ref",
    [
        {"$secretRef": "git-token"},
        {"$secretRef": {}, "peer": True},
        {
            "$secretRef": {
                "authorityClass": "credential.read",
                "providerId": "system-keyring",
                "referenceId": "git-token",
                "rotationEpoch": True,
                "secretReferenceVersion": 1,
            }
        },
        {
            "$secretRef": {
                "authorityClass": "credential.read",
                "providerId": "system-keyring",
                "referenceId": "git-token",
                "rotationEpoch": 0,
                "secretReferenceVersion": 2,
            }
        },
    ],
)
def test_effective_configuration_rejects_malformed_secret_refs(
    secret_ref: object,
) -> None:
    with pytest.raises(PluginSelectionError) as caught:
        PluginEffectiveConfigurationEntry(
            plugin_id="review-pack",
            contribution_id="review-provider",
            configuration={"auth": secret_ref},
        )

    assert caught.value.code == "invalid_plugin_effective_configuration"


def test_plan_rejects_noncanonical_or_incomplete_product_facts() -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="sorted"):
        replace(
            plan,
            allowed_authority_ceiling=("process", "filesystem"),
        )
    with pytest.raises(TypeError, match="requires"):
        replace(plan.context, instance_revision_refs=())
    with pytest.raises(ValueError, match="cover selected"):
        replace(
            plan,
            context=replace(
                plan.context,
                instance_revision_refs=(
                    PluginInstanceRevisionRef(
                        instance_id="other-pack@product",
                        plugin_id="other-pack",
                        revision=1,
                    ),
                ),
            ),
        )
    with pytest.raises(ValueError, match="cover selected"):
        replace(plan, source_trust_snapshots=())
    with pytest.raises(PluginSelectionError) as caught:
        replace(
            plan,
            effective_configuration_set=PluginEffectiveConfigurationSetV1(entries=()),
        )
    assert caught.value.code == "invalid_plugin_effective_configuration"


def test_plan_input_versions_reject_boolean_and_numeric_aliases() -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="context version"):
        replace(plan.context, context_version=True)
    with pytest.raises(ValueError, match="snapshot version"):
        replace(
            plan.source_trust_snapshots[0],
            trust_snapshot_version=1.0,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="configuration set version"):
        replace(
            plan.effective_configuration_set,
            configuration_set_version=True,
        )
    with pytest.raises(ValueError, match="selection plan version"):
        replace(plan, plan_version=2.0)  # type: ignore[arg-type]
    with pytest.raises(PluginSelectionError) as caught:
        replace(
            plan,
            effective_configuration_set=PluginEffectiveConfigurationSetV1(
                entries=(
                    PluginEffectiveConfigurationEntry(
                        plugin_id="extra-pack",
                        contribution_id="extra-provider",
                        configuration={},
                    ),
                )
            ),
        )
    assert caught.value.code == "invalid_plugin_effective_configuration"


def _plan() -> PluginSelectionPlanV2:
    return PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="review-pack@product",
                    plugin_id="review-pack",
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=("review-pack",),
        selected_contributions=(
            PluginContributionRef("review-pack", "review-provider"),
        ),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id="review-pack",
                package_source_identity="local:/plugins/review-pack",
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                PluginEffectiveConfigurationEntry(
                    plugin_id="review-pack",
                    contribution_id="review-provider",
                    configuration={"mode": "review"},
                ),
            ),
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )
