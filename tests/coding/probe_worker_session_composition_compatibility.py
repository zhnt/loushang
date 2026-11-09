"""Offline graph values for the frozen original Worker composition contract.

Owner admissions/compiler/resolver are real; prepare and provider factories
raise if called. Forged frozen values are deliberate cross-value corruption
inputs, not evidence of Product or native admission.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from copy import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import patch

import pytest

from loushang.coding import package_product_worker_session_composition as original
from loushang.coding.package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_REQUIREMENT,
)
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION as MODEL,
)
from loushang.harness.capabilities import (
    WORKSPACE_CAPABILITY_DEFINITION as WORKSPACE,
)
from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
    CapabilityDefinition,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderBindingSpec,
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
    CapabilityProviderSymbolLocator,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginManifest,
    PluginSource,
    PublishedPluginPackage,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityComponentRequest,
    SessionCapabilityCompositionInputs,
    SessionCapabilityWorkerComponentRequest,
)


def forge(value, **changes):
    result = copy(value)
    for name, replacement in changes.items():
        object.__setattr__(result, name, replacement)
    return result


_EFFECT_CALLS = []


def never(*_args, **_kwargs):
    _EFFECT_CALLS.append("unexpected effect")
    raise AssertionError("graph relation invoked an effect/factory")


def inputs(*, product="coding", query=True, platform="linux-x86_64"):
    definition = CODING_WORKER_QUERY_DEFINITION
    if not query:
        definition = replace(definition, capability_id="coding.worker.hover")
    provider = CapabilityBundleProvider(
        capability_id=definition.capability_id,
        provider_id="worker.query",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=definition.facets,
        source_id="plugin:worker-fixture",
        selection_rule="offline selected fixture",
    )
    spec = CapabilityWorkerProviderBindingSpec(
        plugin_id="worker-fixture",
        contribution_id="query",
        capability_id=definition.capability_id,
        owner_id="coding",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        manifest_digest="c" * 64,
        reservation_fingerprint="d" * 64,
        declaration_fingerprint="e" * 64,
        worker_configuration_fingerprint="f" * 64,
        executable_digest="a" * 64,
        executable_size=128,
        declared_required=False,
        native_platform=platform,
    )
    trust = PluginSourceTrustSnapshotV1(
        plugin_id=spec.plugin_id,
        package_source_identity="source:fixture",
        source_trust_class="local-worker-candidate",
        source_trust_policy_revision="trust-1",
        trusted=True,
    )
    candidate = CapabilityProviderCandidateEnvelope(
        definition=definition,
        provider=provider,
        binding_spec=spec,
        plugin_candidate_fingerprint="b" * 64,
        declaration_fingerprint=spec.declaration_fingerprint,
        declaration_evidence_fingerprint="c" * 64,
        product_id=product,
        scope_id="session:offline",
        product_policy_revision="product-1",
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="worker-fixture@offline",
            plugin_id=spec.plugin_id,
            revision=1,
        ),
        package_source_identity=trust.package_source_identity,
        source_trust_class=trust.source_trust_class,
        source_trust_policy_revision=trust.source_trust_policy_revision,
        source_trusted=True,
        allowed_authority_ceiling=(),
    )
    owner = CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            policy_revision="owner-1",
            revocation_epoch=1,
            allowed_provider_ids=(provider.provider_id,),
            allowed_source_trust_classes=(trust.source_trust_class,),
            authority_ceiling=(),
            allowed_execution_models=("local_worker",),
        )
    )
    eligibility = owner.grant_eligibility(candidate, issued_at=100, expires_at=220)
    admission = owner.admit(
        candidate, eligibility=eligibility, issued_at=120, expires_at=200
    )
    definitions = (MODEL, WORKSPACE, definition)
    context = ProductCompositionAuthorityContext(
        product_id=product,
        scope_id=candidate.scope_id,
        product_policy_revision="product-1",
        evaluated_at=150,
        owner_snapshots=(),
        trust_snapshots=(),
    )
    workspace_provider = CapabilityBundleProvider(
        capability_id=WORKSPACE.capability_id,
        provider_id="workspace-fixture",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(WORKSPACE.contract_version),
        facets=WORKSPACE.facets,
        source_id="host:fixture",
        selection_rule="offline host fixture",
    )
    workspace = CapabilityBundleProviderBinding(
        provider=workspace_provider,
        scope_instance_id=context.scope_id,
        binding_input_fingerprint="d" * 64,
        create=never,
    )
    ordinary = SessionCapabilityCompositionInputs(
        product_composition=ProductCompositionCompiler().compile(
            authority_context=context,
            mandatory_roots=(MODEL.capability_id, WORKSPACE.capability_id),
            admissions=(),
            definitions=definitions,
            optional_choices=(),
        ),
        resolved_providers=ProductCapabilityProviderResolver().resolve(
            ProductCapabilityProviderSelectionPlanV1(
                product_id=product,
                roots=(),
                choices=(),
                policy_revision="product-1",
            ),
            definitions=definitions,
            admissions=(),
            owner_snapshots=(),
            evaluated_at=150,
            prebound_providers=(workspace_provider,),
        ),
        component_requests=(),
    )
    resolved = ProductCapabilityProviderResolver().resolve(
        ProductCapabilityProviderSelectionPlanV1(
            product_id=product,
            roots=(definition.capability_id,),
            choices=(
                ProductCapabilityProviderChoice(
                    capability_id=definition.capability_id,
                    provider_id=provider.provider_id,
                    candidate_fingerprint=admission.candidate_fingerprint,
                ),
            ),
            policy_revision="product-1",
        ),
        definitions=definitions,
        admissions=(admission,),
        owner_snapshots=(owner.snapshot(),),
        evaluated_at=150,
    )
    request = SessionCapabilityWorkerComponentRequest(
        resolved=resolved.entries[0],
        owner_snapshot=owner.snapshot(),
        trust_snapshot=trust,
        receipt_fingerprint=candidate.plugin_candidate_fingerprint,
        worker_admission_fingerprint="c" * 64,
        prepare=never,
    )
    worker = SessionCapabilityCompositionInputs(
        product_composition=ProductCompositionCompiler().compile(
            authority_context=replace(context, trust_snapshots=(trust,)),
            mandatory_roots=(MODEL.capability_id, definition.capability_id),
            admissions=(),
            definitions=definitions,
            optional_choices=(),
        ),
        resolved_providers=resolved,
        component_requests=(request,),
        host_consumer_requirements=(
            replace(
                CODING_WORKER_QUERY_REQUIREMENT,
                capability=definition.capability_id,
            ),
        ),
    )
    return dict(
        ordinary=ordinary,
        worker=worker,
        definitions=definitions,
        workspace_binding=workspace,
    )


def describe(value):
    if value is None:
        return {"result": "ok"}
    ids = tuple(item.capability_id for item in value.resolved_providers.entries)
    return {
        "fingerprint": value.composition_fingerprint,
        "roots": list(value.product_composition.consumer_requirements.roots),
        "provider_roots": list(value.resolved_providers.roots),
        "provider_ids": list(ids),
        "request_exact_resolution": all(
            request.resolved is entry
            for request, entry in zip(
                value.component_requests,
                value.resolved_providers.entries,
                strict=True,
            )
        ),
        "host_requirements": [
            item.capability for item in value.host_consumer_requirements
        ],
    }


def with_ordinary_component():
    """Real admission/graph values, inert package lease metadata only."""
    values = inputs()
    ordinary = values["ordinary"]
    context = ordinary.product_composition.authority_context
    definition = CapabilityDefinition(
        capability_id="coding.base.fixture",
        owner_id="coding",
        contract_version=1,
        facets=("default",),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )
    provider = CapabilityBundleProvider(
        capability_id=definition.capability_id,
        provider_id="fixture-base",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=definition.facets,
        source_id="plugin:base-fixture",
        selection_rule="offline base fixture",
    )
    spec = CapabilityProviderBindingSpec(
        plugin_id="base-fixture",
        contribution_id="base",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        factory=CapabilityProviderSymbolLocator(
            path="provider.py", symbol="create", execution_model="in_process"
        ),
        disposer=None,
        binding_inputs={},
    )
    trust = PluginSourceTrustSnapshotV1(
        plugin_id=spec.plugin_id,
        package_source_identity="source:base-fixture",
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        trusted=True,
    )
    candidate = CapabilityProviderCandidateEnvelope(
        definition=definition,
        provider=provider,
        binding_spec=spec,
        plugin_candidate_fingerprint="a" * 64,
        declaration_fingerprint="a" * 64,
        declaration_evidence_fingerprint="a" * 64,
        product_id="coding",
        scope_id=context.scope_id,
        product_policy_revision=context.product_policy_revision,
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="base@offline", plugin_id=spec.plugin_id, revision=1
        ),
        package_source_identity=trust.package_source_identity,
        source_trust_class=trust.source_trust_class,
        source_trust_policy_revision=trust.source_trust_policy_revision,
        source_trusted=True,
        allowed_authority_ceiling=(),
    )
    owner = CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id="coding",
            policy_revision="owner-base-1",
            revocation_epoch=1,
            allowed_provider_ids=(provider.provider_id,),
            allowed_source_trust_classes=(trust.source_trust_class,),
            authority_ceiling=(),
        )
    )
    eligibility = owner.grant_eligibility(candidate, issued_at=100, expires_at=220)
    admission = owner.admit(
        candidate, eligibility=eligibility, issued_at=120, expires_at=200
    )
    definitions = (*values["definitions"], definition)
    resolved = ProductCapabilityProviderResolver().resolve(
        ProductCapabilityProviderSelectionPlanV1(
            product_id="coding",
            roots=(definition.capability_id,),
            choices=(
                ProductCapabilityProviderChoice(
                    capability_id=definition.capability_id,
                    provider_id=provider.provider_id,
                    candidate_fingerprint=admission.candidate_fingerprint,
                ),
            ),
            policy_revision=context.product_policy_revision,
        ),
        definitions=definitions,
        admissions=(admission,),
        owner_snapshots=(owner.snapshot(),),
        evaluated_at=context.evaluated_at,
        prebound_providers=ordinary.resolved_providers.prebound_providers,
    )
    root = Path("/inert-package-fixture")
    package = PublishedPluginPackage(
        root=root,
        package_root=root,
        manifest=PluginManifest(name=spec.plugin_id, root=root),
        source=PluginSource(path=root),
        content_digest=spec.package_content_digest,
        revision_handle=SimpleNamespace(
            root=root, content_digest=spec.package_content_digest
        ),
        dependency_lock=SimpleNamespace(
            package_content_digest=spec.package_content_digest,
            digest=spec.dependency_lock_digest,
        ),
    )
    request = SessionCapabilityComponentRequest(
        resolved=resolved.entries[0],
        package=package,
        owner_snapshot=owner.snapshot(),
        trust_snapshot=trust,
        activation_decision_id="a" * 48,
    )
    compilation = ProductCompositionCompiler().compile(
        authority_context=replace(context, trust_snapshots=(trust,)),
        mandatory_roots=(
            MODEL.capability_id,
            WORKSPACE.capability_id,
            definition.capability_id,
        ),
        admissions=(),
        definitions=definitions,
        optional_choices=(),
    )
    return {
        **values,
        "ordinary": SessionCapabilityCompositionInputs(
            product_composition=compilation,
            resolved_providers=resolved,
            component_requests=(request,),
        ),
        "definitions": definitions,
    }


def outcome(call):
    try:
        return describe(call())
    except Exception as error:

        def detail(exc):
            return {
                "type": type(exc).__module__ + "." + type(exc).__name__,
                "message": str(exc),
                "code": getattr(exc, "code", None),
                "cause": None if exc.__cause__ is None else detail(exc.__cause__),
            }

        return {"error": detail(error)}


def observations():
    compose = original.compose_coding_product_worker_with_ordinary_session
    validate = original.validate_coding_product_worker_ordinary_session_inputs
    seen = {}
    for name, options in (
        ("query-linux", {}),
        ("query-windows", {"platform": "windows-amd64"}),
        ("other-worker-id", {"query": False}),
        ("other-product", {"product": "other"}),
    ):
        values = inputs(**options)
        seen["compose:" + name] = outcome(lambda values=values: compose(**values))
        if options.get("product") != "other":
            combined = compose(**values)
            seen["validate:" + name] = outcome(
                lambda values=values, combined=combined: validate(
                    ordinary=values["ordinary"],
                    combined=combined,
                    workspace_binding=values["workspace_binding"],
                )
            )
    values = inputs()
    ordinary, worker = values["ordinary"], values["worker"]
    context = ordinary.product_composition.authority_context
    worker_context = worker.product_composition.authority_context
    for name, changes in (
        ("bad-ordinary-type", {"ordinary": None}),
        ("bad-worker-type", {"worker": None}),
        ("bad-workspace-type", {"workspace_binding": None}),
        ("bad-definition-type", {"definitions": (None,)}),
        ("definitions-duplicate", {"definitions": (*values["definitions"], MODEL)}),
        ("definitions-missing-worker", {"definitions": (MODEL, WORKSPACE)}),
        (
            "definitions-model-changed",
            {
                "definitions": (
                    replace(MODEL, facets=("other",)),
                    *values["definitions"][1:],
                )
            },
        ),
        ("worker-no-request", {"worker": forge(worker, component_requests=())}),
        (
            "worker-prebound",
            {
                "worker": forge(
                    worker,
                    resolved_providers=forge(
                        worker.resolved_providers,
                        prebound_providers=(values["workspace_binding"].provider,),
                    ),
                )
            },
        ),
        (
            "worker-scope",
            {
                "worker": forge(
                    worker,
                    product_composition=forge(
                        worker.product_composition,
                        authority_context=replace(
                            worker_context, scope_id="session:other"
                        ),
                    ),
                )
            },
        ),
        (
            "worker-policy",
            {
                "worker": forge(
                    worker,
                    product_composition=forge(
                        worker.product_composition,
                        authority_context=replace(
                            worker_context, product_policy_revision="other"
                        ),
                    ),
                )
            },
        ),
        (
            "worker-time",
            {
                "worker": forge(
                    worker,
                    product_composition=forge(
                        worker.product_composition,
                        authority_context=replace(worker_context, evaluated_at=151),
                    ),
                )
            },
        ),
        (
            "worker-owner-snapshot",
            {
                "worker": forge(
                    worker,
                    product_composition=forge(
                        worker.product_composition,
                        authority_context=forge(
                            worker_context,
                            owner_snapshots=(
                                worker.component_requests[0].owner_snapshot,
                            ),
                        ),
                    ),
                )
            },
        ),
        (
            "worker-root-overlap",
            {"ordinary": forge(ordinary, resolved_providers=worker.resolved_providers)},
        ),
        (
            "worker-wrong-root",
            {
                "worker": forge(
                    worker,
                    resolved_providers=forge(worker.resolved_providers, roots=()),
                )
            },
        ),
        (
            "trust-conflict",
            {
                "ordinary": forge(
                    ordinary,
                    product_composition=forge(
                        ordinary.product_composition,
                        authority_context=replace(
                            context,
                            trust_snapshots=(
                                replace(
                                    worker.component_requests[0].trust_snapshot,
                                    trusted=False,
                                ),
                            ),
                        ),
                    ),
                )
            },
        ),
        (
            "scope-before-definitions",
            {
                "worker": forge(
                    worker,
                    product_composition=forge(
                        worker.product_composition,
                        authority_context=replace(
                            worker_context, scope_id="session:other"
                        ),
                    ),
                ),
                "definitions": (),
            },
        ),
    ):
        seen["compose:" + name] = outcome(
            lambda changes=changes: compose(**{**values, **changes})
        )
    combined = compose(**values)
    merged_context = combined.product_composition.authority_context
    for name, bad in (
        ("bad-type", None),
        (
            "scope",
            forge(
                combined,
                product_composition=forge(
                    combined.product_composition,
                    authority_context=replace(merged_context, scope_id="other"),
                ),
            ),
        ),
        (
            "policy",
            forge(
                combined,
                product_composition=forge(
                    combined.product_composition,
                    authority_context=replace(
                        merged_context, product_policy_revision="other"
                    ),
                ),
            ),
        ),
        (
            "time",
            forge(
                combined,
                product_composition=forge(
                    combined.product_composition,
                    authority_context=replace(merged_context, evaluated_at=151),
                ),
            ),
        ),
        ("no-worker", forge(combined, component_requests=())),
        (
            "two-workers",
            forge(combined, component_requests=combined.component_requests * 2),
        ),
        (
            "foreign-request-resolution",
            forge(
                combined,
                component_requests=(
                    forge(
                        combined.component_requests[0],
                        resolved=copy(combined.resolved_providers.entries[0]),
                    ),
                ),
            ),
        ),
        ("host-consumers-missing", forge(combined, host_consumer_requirements=())),
        (
            "prebound-missing",
            forge(
                combined,
                resolved_providers=forge(
                    combined.resolved_providers, prebound_providers=()
                ),
            ),
        ),
        (
            "provider-roots-missing",
            forge(
                combined,
                resolved_providers=forge(combined.resolved_providers, roots=()),
            ),
        ),
        (
            "trust-missing",
            forge(
                combined,
                product_composition=forge(
                    combined.product_composition,
                    authority_context=replace(merged_context, trust_snapshots=()),
                ),
            ),
        ),
        (
            "duplicate-trust",
            forge(
                combined,
                product_composition=forge(
                    combined.product_composition,
                    authority_context=forge(
                        merged_context,
                        trust_snapshots=merged_context.trust_snapshots * 2,
                    ),
                ),
            ),
        ),
        (
            "resource-admission-added",
            forge(
                combined,
                product_composition=forge(
                    combined.product_composition, resource_admissions=(object(),)
                ),
            ),
        ),
    ):
        seen["validate:" + name] = outcome(
            lambda bad=bad: validate(
                ordinary=ordinary,
                combined=bad,
                workspace_binding=values["workspace_binding"],
            )
        )
    # The same original compiler/resolver classes are used in both locations.
    with patch.object(
        ProductCompositionCompiler, "compile", side_effect=LookupError("compiler probe")
    ):
        seen["compose:compiler-error"] = outcome(
            lambda values=values: compose(**values)
        )
    with patch.object(
        ProductCapabilityProviderResolver,
        "resolve",
        side_effect=LookupError("resolver probe"),
    ):
        seen["compose:resolver-error"] = outcome(
            lambda values=values: compose(**values)
        )
    with patch.object(
        ProductCapabilityProviderResolver,
        "resolve",
        return_value=forge(combined.resolved_providers, entries=()),
    ):
        seen["compose:resolver-changed-selection"] = outcome(
            lambda values=values: compose(**values)
        )
    enriched = with_ordinary_component()
    base = enriched["ordinary"]
    enriched_combined = compose(**enriched)
    seen["compose:ordinary-component"] = describe(enriched_combined)
    seen["validate:ordinary-component"] = outcome(
        lambda: validate(
            ordinary=base,
            combined=enriched_combined,
            workspace_binding=enriched["workspace_binding"],
        )
    )
    requests = enriched_combined.component_requests
    base_request = next(
        item for item in requests if isinstance(item, SessionCapabilityComponentRequest)
    )
    seen["identity:ordinary-package-retained"] = {
        "package_is_original": base_request.package
        is base.component_requests[0].package,
        "resolved_is_new_entry": base_request.resolved
        is enriched_combined.resolved_providers.entries[0],
    }
    for name, replacement in (
        ("equal-request-same-package", copy(base_request)),
        (
            "equal-request-different-package",
            forge(base_request, package=replace(base_request.package)),
        ),
    ):
        updated = forge(
            enriched_combined,
            component_requests=tuple(
                replacement if request is base_request else request
                for request in requests
            ),
        )
        seen["validate:" + name] = outcome(
            lambda updated=updated: validate(
                ordinary=base,
                combined=updated,
                workspace_binding=enriched["workspace_binding"],
            )
        )
    seen["invariants:no-effects"] = {"calls": len(_EFFECT_CALLS)}
    return seen


_EXPECTED = json.loads(
    Path(__file__)
    .with_name("fixtures")
    .joinpath("worker_session_composition_v1.json")
    .read_text()
)


@pytest.fixture(scope="module")
def actual_observations():
    return observations()


@pytest.mark.parametrize("case", _EXPECTED["observations"])
def test_original_worker_session_relation(case, actual_observations):
    assert actual_observations[case] == _EXPECTED["observations"][case]


@pytest.mark.parametrize("name", _EXPECTED["signatures"])
def test_public_composition_signature_and_resolved_hints(name):
    function = getattr(original, name)
    assert str(inspect.signature(function)) == _EXPECTED["signatures"][name]
    hints = get_type_hints(function)
    assert hints["ordinary"] is SessionCapabilityCompositionInputs
    assert hints["workspace_binding"] is CapabilityBundleProviderBinding


def test_shared_product_assembly_cold_import_has_no_coding_dependency():
    probe = """
import importlib.abc
import sys

class RefuseCoding(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'loushang.coding' or fullname.startswith('loushang.coding.'):
            raise AssertionError('Session assembly imported Coding: ' + fullname)

sys.meta_path.insert(0, RefuseCoding())
from loushang.harness.session.product_composition_assembly import _WorkerSessionComposition
assert not any(n == 'loushang.coding' or n.startswith('loushang.coding.') for n in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", probe], check=True, capture_output=True, text=True
    )
