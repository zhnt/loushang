from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
    CapabilityProviderDeclarationPayload,
    PluginSymbolReference,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import PluginDeclaration
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
    PluginSelectionError,
    PluginSelectionPlan,
    PluginSelectionResolver,
    PluginSourceTrust,
    build_execution_approval_subject,
)
from loushang.harness.resources.plugins.types import PluginSource


def test_preflight_and_finalize_are_inert_and_reservations_are_one_use(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    contribution = package.contribution_index.items[0]
    plan = _plan(binding.source_identity)
    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        source_trust=plan.source_trust[0],
        binding=binding,
    )
    changed_subject = build_execution_approval_subject(
        package,
        contribution,
        plan=replace(plan, policy_revision="policy-2"),
        source_trust=plan.source_trust[0],
        binding=binding,
    )
    assert changed_subject.digest != subject.digest
    decision = PluginExecutionDecisionRecord(
        decision_id="decision-1",
        subject_digest=subject.digest,
        policy_revision=plan.policy_revision,
        disposition="approved",
    )
    resolver = PluginSelectionResolver()

    preflight = resolver.preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=plan,
        decisions=(decision,),
    )
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        reservation_fingerprint=contribution.fingerprint,
        source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
        source_kind=contribution.declaration_source.kind,
        payload=CapabilityProviderDeclarationPayload(
            provider=CapabilityBundleProvider(
                capability_id="coding.lsp",
                provider_id="review-lsp",
                implementation_version=1,
                compatible_contract=CapabilityContractRange.exact(1),
                facets=("semantic",),
                required_authorities=frozenset({"process"}),
                source_id="plugin:review-pack",
                selection_rule=PLUGIN_PROVIDER_SELECTION_RULE,
            ),
            factory=PluginSymbolReference(
                path="provider.py",
                symbol="create_provider",
                execution_model="in_process",
            ),
            disposer=None,
            binding_inputs=dict(contribution.configuration),
        ).to_dict(),
    )
    assert PluginDeclaration.from_dict(declaration.to_dict()) == declaration

    selection = resolver.finalize(preflight, (declaration,))

    assert len(selection.candidates) == 1
    assert selection.candidates[0].decision_id == "decision-1"
    assert len(selection.candidates[0].fingerprint) == 64
    assert (package.root / "imported.txt").exists() is False
    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(preflight, (declaration,))
    assert caught.value.code == "plugin_preflight_consumed"

    rolled_back = resolver.preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=plan,
        decisions=(decision,),
    )
    resolver.rollback(rolled_back)
    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(rolled_back, (declaration,))
    assert caught.value.code == "plugin_preflight_consumed"
    runtime.close()


def test_preflight_rejects_disabled_plugin_without_importing_code(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, enabled=False)
    binding = runtime.bindings[0]
    resolver = PluginSelectionResolver()

    with pytest.raises(PluginSelectionError) as caught:
        resolver.preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=_plan(binding.source_identity),
            decisions=(),
        )

    assert caught.value.code == "selected_plugin_disabled"
    assert (runtime.packages[0].root / "imported.txt").exists() is False
    runtime.close()


def test_preflight_requires_exact_approval_subject_and_binding(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    plan = _plan(binding.source_identity)
    contribution = package.contribution_index.items[0]
    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        source_trust=plan.source_trust[0],
        binding=binding,
    )
    stale_decision = PluginExecutionDecisionRecord(
        decision_id="stale",
        subject_digest=subject.digest,
        policy_revision="policy-previous",
        disposition="approved",
    )

    with pytest.raises(PluginSelectionError) as caught:
        PluginSelectionResolver().preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=plan,
            decisions=(),
        )
    assert caught.value.code == "plugin_execution_approval_required"

    with pytest.raises(PluginSelectionError) as caught:
        PluginSelectionResolver().preflight(
            runtime.packages,
            bindings=runtime.bindings,
            plan=plan,
            decisions=(stale_decision,),
        )
    assert caught.value.code == "plugin_execution_denied"

    with pytest.raises(PluginSelectionError) as caught:
        PluginSelectionResolver().preflight(
            runtime.packages,
            bindings=(),
            plan=plan,
            decisions=(),
        )
    assert caught.value.code == "plugin_selection_package_mismatch"
    assert (package.root / "imported.txt").exists() is False
    runtime.close()


def test_finalize_fails_closed_on_missing_or_changed_declaration(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    plan = _plan(binding.source_identity)
    contribution = package.contribution_index.items[0]
    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        source_trust=plan.source_trust[0],
        binding=binding,
    )
    decision = PluginExecutionDecisionRecord(
        decision_id="decision-1",
        subject_digest=subject.digest,
        policy_revision=plan.policy_revision,
        disposition="approved",
    )
    resolver = PluginSelectionResolver()
    preflight = resolver.preflight(
        runtime.packages,
        bindings=runtime.bindings,
        plan=plan,
        decisions=(decision,),
    )

    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(preflight, ())
    assert caught.value.code == "plugin_declaration_reservation_mismatch"
    with pytest.raises(PluginSelectionError) as caught:
        resolver.finalize(preflight, ())
    assert caught.value.code == "plugin_preflight_consumed"
    runtime.close()


def test_declaration_ir_rejects_callable_payload() -> None:
    with pytest.raises(ValueError):
        PluginDeclaration(
            plugin_id="review-pack",
            contribution_id="review-provider",
            kind="capability_provider",
            owner="coding.lsp",
            reservation_fingerprint="a" * 64,
            source_descriptor_fingerprint="b" * 64,
            source_kind="in_process",
            payload={"factory": lambda: None},
        )
    with pytest.raises(ValueError):
        PluginDeclaration.from_dict(
            {
                "pluginId": "review-pack",
                "contributionId": "review-provider",
                "kind": "capability_provider",
                "owner": "coding.lsp",
                "reservationFingerprint": "a" * 64,
                "payload": {},
                "irVersion": 1,
                "unknown": True,
            }
        )


def test_subject_v2_closes_over_every_contribution_from_the_same_source(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, include_source_sibling=True)
    package = runtime.packages[0]
    binding = runtime.bindings[0]
    contribution = package.contribution_index.items[0]
    plan = replace(
        _plan(binding.source_identity),
        allowed_authorities=("filesystem", "process"),
    )

    subject = build_execution_approval_subject(
        package,
        contribution,
        plan=plan,
        source_trust=plan.source_trust[0],
        binding=binding,
    )
    closure = package.contribution_index.items
    expected_reservations = {
        "domain": "loushang.plugin-reservation-closure/v1",
        "reservations": [
            {
                "contributionId": item.contribution_id,
                "reservationFingerprint": item.fingerprint,
            }
            for item in closure
        ],
    }
    expected_configurations = {
        "configurations": [
            {
                "configuration": item.to_dict()["configuration"],
                "contributionId": item.contribution_id,
                "pluginId": "review-pack",
            }
            for item in closure
        ],
        "domain": "loushang.plugin-group-configuration/v1",
    }

    assert subject.requested_authorities == ("filesystem", "process")
    assert subject.reservation_closure_fingerprint == sha256(
        StrictPluginJsonCodec.encode(expected_reservations)
    ).hexdigest()
    assert subject.configuration_map_fingerprint == sha256(
        StrictPluginJsonCodec.encode(expected_configurations)
    ).hexdigest()
    runtime.close()


def _runtime(
    tmp_path: Path,
    *,
    enabled: bool = True,
    include_source_sibling: bool = False,
) -> PluginRuntimeResolution:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "provider.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('imported.txt').write_text('imported')\n",
        encoding="utf-8",
    )
    items = [
        {
            "id": "review-provider",
            "kind": "capability_provider",
            "owner": "coding.lsp",
            "contributionExecutionModel": "in_process",
            "declarationSource": {
                "entrypoint": "provider.py:declare",
                "kind": "in_process",
                "sourceVersion": 1,
            },
            "requestedAuthorities": ["process"],
            "configuration": {"mode": "review"},
            "required": True,
        }
    ]
    if include_source_sibling:
        items.append(
            {
                "id": "review-tools",
                "kind": "capability_provider",
                "owner": "coding.tools",
                "contributionExecutionModel": "in_process",
                "declarationSource": {
                    "entrypoint": "provider.py:declare",
                    "kind": "in_process",
                    "sourceVersion": 1,
                },
                "requestedAuthorities": ["filesystem"],
                "configuration": {"mode": "tools"},
                "required": False,
            }
        )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "review-pack",
                "enabled": enabled,
                "contributionIndex": {
                    "version": 2,
                    "items": items,
                },
            }
        ),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    return authority.publish_runtime((inspection,), binding_store=materializer)


def _plan(source_identity: str) -> PluginSelectionPlan:
    return PluginSelectionPlan(
        product_id="coding",
        scope_id="workspace:test",
        policy_revision="policy-1",
        selected_plugin_ids=("review-pack",),
        selected_contributions=(
            PluginContributionRef("review-pack", "review-provider"),
        ),
        source_trust=(
            PluginSourceTrust(
                plugin_id="review-pack",
                source_identity=source_identity,
                trust_class="host-equivalent-local",
                trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        instance_revision_refs=(
            PluginInstanceRevisionRef(
                instance_id="review-pack@product",
                plugin_id="review-pack",
                revision=1,
            ),
        ),
        allowed_authorities=("process",),
    )
