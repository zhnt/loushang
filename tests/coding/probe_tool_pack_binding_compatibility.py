"""Fixed pre-convergence Tool owner contracts; no tools or servers execute."""

from __future__ import annotations

import asyncio
import importlib
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.harness.capabilities.consumer_requirements import (
    ProductCapabilityConsumerRequirementEntry,
    ProductCompositionAuthorityContext,
)
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
)
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.runtime.bindings import RuntimeBindingState
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationIdentity,
    RegistrationLease,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
)
from loushang.harness.tools.core import project_tool_definition


def build_owner(domain, *, mode="on_demand", scope_id="workspace:sample", revision=7):
    """Mint an inert real authority decision, rather than bypass its constructor."""
    module = importlib.import_module(f"loushang.coding.{domain}._plugin_tool_owner")
    requirement = getattr(module, f"CODING_{domain.upper()}_TOOL_RUNTIME_REQUIREMENT")
    plugin_id = f"coding.{domain}.default"
    contribution_id = f"coding-{domain}-tools"
    contribution = CatalogConsumerContributionSpec(
        "tool_pack", f"coding.{domain}.tools", 1, module._TOOL_NAMES, (requirement,)
    )
    candidate = OwnerContributionCandidateEnvelope(
        owner_id="coding.tools",
        plugin_id=plugin_id,
        contribution_id=contribution_id,
        contribution=contribution,
        plugin_candidate_fingerprint="1" * 64,
        declaration_fingerprint="2" * 64,
        declaration_evidence_fingerprint="3" * 64,
        package_content_digest="4" * 64,
        dependency_lock_digest="5" * 64,
        product_id="coding",
        scope_id=scope_id,
        product_policy_revision="product-policy-1",
        instance_revision_ref=PluginInstanceRevisionRef(
            f"{plugin_id}@{scope_id}", plugin_id, revision
        ),
        package_source_identity=f"local:{plugin_id}",
        source_trust_class="first_party",
        source_trust_policy_revision="trust-1",
        source_trusted=True,
    )
    authority = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id="coding.tools",
            contribution_kind="tool_pack",
            product_id="coding",
            policy_revision="owner-policy-1",
            revocation_epoch=0,
            allowed_source_trust_classes=("first_party",),
            allowed_collection_ids=(contribution.catalog_id,),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    )
    admission = authority.admit(candidate, issued_at=100, expires_at=200)
    trust = PluginSourceTrustSnapshotV1(
        plugin_id, candidate.package_source_identity, "first_party", "trust-1", True
    )
    context = ProductCompositionAuthorityContext(
        product_id="coding",
        scope_id=scope_id,
        product_policy_revision="product-policy-1",
        evaluated_at=150,
        owner_snapshots=(authority.snapshot(),),
        trust_snapshots=(trust,),
    )
    gate = SessionCapabilityOwnerAuthorityGate(
        authority_context=context,
        owner_snapshot_reader=lambda *_: authority.snapshot(),
        trust_snapshot_reader=lambda *_: trust,
        product_policy_revision_reader=lambda *_: "product-policy-1",
        clock=lambda: 150,
    )
    entry = ProductCapabilityConsumerRequirementEntry(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=plugin_id,
        contribution_id=contribution_id,
        admission_fingerprint=admission.fingerprint,
        consumer_scope=admission.consumer_scope,
        consumer_refresh_boundary=admission.consumer_refresh_boundary,
        requirement=requirement,
    )
    facets = CapabilityBundleValue((CapabilityFacetBinding("tool-runtime", object()),))
    capture = SessionCapabilityConsumerCapture(
        entry,
        CapabilityFacetSet(requirement, _lease=RuntimeBindingState(facets).capture()),
    )
    cls = getattr(
        module, "CodingLspToolOwner" if domain == "lsp" else "CodingArchToolOwner"
    )
    return cls(admission, gate, mode, scope_id), capture


class RecordingPort:
    def __init__(
        self, *, fail_dispose_once=False, fail_stage_on=None, rollback="removed"
    ):
        self.fail_stage_on = fail_stage_on
        self.rollback = rollback
        self.leases = []
        self.calls = []
        self.events = []
        self.failures_left = int(fail_dispose_once)

    def stage_runtime_tool(self, tool, *, owner, enabled=True, source_info=None):
        if tool.name == self.fail_stage_on:
            self.events.append(f"fail:{tool.name}")
            raise RuntimeError("injected staging failure")
        self.calls.append(
            {
                "name": tool.name,
                "owner_kind": owner.owner_kind,
                "owner_id": owner.owner_id,
                "runtime_id": owner.runtime_id,
                "generation": owner.generation,
                "enabled": enabled,
                "source_fields": {
                    name: getattr(source_info, name)
                    for name in (
                        "plugin_id",
                        "contribution_id",
                        "admission_fingerprint",
                    )
                },
                "source_equals_clone": source_info == deepcopy(source_info),
                "source_projection": project_tool_definition(tool, source_info)[
                    "sourceInfo"
                ],
            }
        )
        self.events.append(f"stage:{tool.name}")

        def dispose():
            self.events.append(f"dispose:{tool.name}")
            if self.failures_left:
                self.failures_left -= 1
                return RegistrationDisposalResult(state="failed_retryable")
            return RegistrationDisposalResult(state="removed")

        def rollback():
            self.events.append(f"rollback:{tool.name}")
            if self.rollback == "cancelled":
                raise asyncio.CancelledError("rollback interrupted")
            return RegistrationDisposalResult(state=self.rollback)

        lease = RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity("tool", f"fixed:{tool.name}", tool.name),
            dispose=dispose,
            activate=lambda: self.events.append(f"activate:{tool.name}"),
            deactivate=lambda: self.events.append(f"deactivate:{tool.name}"),
            rollback=rollback,
        )
        self.leases.append(lease)
        return lease


def error_value(error):
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
        "code": getattr(error, "code", None),
    }


async def observe_binding(domain, mode):
    owner, capture = build_owner(domain, mode=mode)
    port = RecordingPort()
    binding = owner.bind(port)
    value = binding.stage((capture,))
    prepared_receipt = binding.retirement_receipt(value).to_dict()
    binding.commit(value)
    committed_receipt = binding.retirement_receipt(value).to_dict()
    binding.rollback_commit(value)
    binding.commit(value)
    await binding.dispose(value)
    return {
        "calls": port.calls,
        "prepared_receipt": prepared_receipt,
        "committed_receipt": committed_receipt,
        "events": port.events,
    }


async def observe_retry(domain):
    owner, capture = build_owner(domain)
    port = RecordingPort(fail_dispose_once=True)
    binding = owner.bind(port)
    value = binding.stage((capture,))
    binding.commit(value)
    scope = value.scope
    try:
        await binding.dispose(value)
    except RuntimeError as error:
        result = {"first_error": error_value(error)}
    else:
        raise AssertionError("original failed disposal must be reported")
    result["retry_scope_state"] = scope.state
    await binding.dispose(value)
    result["same_scope_after_retry"] = value.scope is scope
    result["final_scope_state"] = scope.state
    result["events"] = port.events
    return result


async def observe_families():
    result = {}
    for domain in ("lsp", "arch"):
        owner, capture = build_owner(domain)
        binding = owner.bind(RecordingPort())
        value = binding.stage((capture,))
        same, _ = build_owner(domain, scope_id="workspace:another")
        same_binding = same.bind(RecordingPort())
        same_binding.commit(value)
        result[f"{domain}:same_family_other_scope"] = "accepted"
        same_binding.rollback_commit(value)
        other, _ = build_owner("arch" if domain == "lsp" else "lsp")
        other_binding = other.bind(RecordingPort())
        for operation in ("commit", "rollback_commit", "retirement_receipt"):
            try:
                getattr(other_binding, operation)(value)
            except TypeError as error:
                result[f"{domain}:cross_family:{operation}"] = error_value(error)
            else:
                raise AssertionError("original cross-family value must be rejected")
        try:
            await other_binding.dispose(value)
        except TypeError as error:
            result[f"{domain}:cross_family:dispose"] = error_value(error)
        await binding.dispose(value)
    return result


FIXTURE = Path(__file__).parent / "fixtures/tool_pack_binding_v1.json"


@pytest.mark.parametrize("domain", ("lsp", "arch"))
@pytest.mark.parametrize("mode", ("on_demand", "always"))
def test_tool_pack_identity_source_and_retirement_match_original(domain, mode):
    expected = json.loads(FIXTURE.read_text())
    assert asyncio.run(observe_binding(domain, mode)) == expected[f"{domain}:{mode}"]


@pytest.mark.parametrize("domain", ("lsp", "arch"))
def test_failed_disposal_keeps_original_scope_for_retry(domain):
    expected = json.loads(FIXTURE.read_text())
    assert asyncio.run(observe_retry(domain)) == expected[f"{domain}:retry"]


def test_generation_family_boundaries_match_original():
    expected = json.loads(FIXTURE.read_text())
    assert asyncio.run(observe_families()) == expected["families"]


async def observe_stage_failure(rollback):
    owner, capture = build_owner("lsp")
    port = RecordingPort(fail_stage_on="inspect_symbol", rollback=rollback)
    binding = owner.bind(port)
    try:
        binding.stage((capture,))
    except BaseException as error:
        result = {
            "error": error_value(error),
            "notes": getattr(error, "__notes__", []),
            "context": None
            if error.__context__ is None
            else error_value(error.__context__),
            "cause": None if error.__cause__ is None else error_value(error.__cause__),
            "events": list(port.events),
            "lease_states": [lease.state for lease in port.leases],
        }
    else:
        raise AssertionError("partial stage must fail")
    for lease in port.leases:
        await lease.dispose()
    return result


def observe_projection_failure():
    owner, capture = build_owner("lsp")
    port = RecordingPort()
    binding = owner.bind(port)
    module = importlib.import_module("loushang.coding.lsp._plugin_tool_owner")
    with patch.object(
        module,
        "create_inspect_symbol_tool_definition",
        side_effect=ValueError("second definition rejected"),
    ):
        try:
            binding.stage((capture,))
        except ValueError as error:
            return {"error": error_value(error), "events": port.events}
    raise AssertionError("all definitions must be built before registering the first")


def observe_slot(domain):
    from loushang.harness.runtime.registration import RegistrationOwner

    module = importlib.import_module(
        "loushang.coding._base_plugin_owners"
        if domain == "base"
        else f"loushang.coding.{domain}._plugin_tool_owner"
    )
    title = {"lsp": "Lsp", "arch": "Arch", "base": "Base"}[domain]
    slot = getattr(module, f"Coding{title}ToolRegistrationSlot")()
    owner = RegistrationOwner("product", "test", "workspace:sample", 7)
    sentinel = object()
    result = {"has_instance_dict": hasattr(slot, "__dict__")}
    try:
        slot.stage_runtime_tool(sentinel, owner=owner)
    except RuntimeError as error:
        result["unbound"] = error_value(error)
    try:
        slot.bind(object())
    except TypeError as error:
        result["invalid"] = error_value(error)

    class Port:
        def stage_runtime_tool(self, tool, **kwargs):
            result["same_tool"] = tool is sentinel
            result["same_owner"] = kwargs["owner"] is owner
            result["enabled"] = kwargs["enabled"]
            result["same_source"] = kwargs["source_info"] is sentinel
            return sentinel

    slot.bind(Port())
    value = slot.stage_runtime_tool(
        sentinel, owner=owner, enabled=False, source_info=sentinel
    )
    result["same_result"] = value is sentinel
    try:
        slot.bind(object())
    except RuntimeError as error:
        result["rebind"] = error_value(error)
    return result


FAILURE_FIXTURE = Path(__file__).parent / "fixtures/tool_pack_failures_v1.json"


@pytest.mark.parametrize("rollback", ("removed", "failed_retryable", "cancelled"))
def test_partial_stage_keeps_original_rollback_and_exception_priority(rollback):
    expected = json.loads(FAILURE_FIXTURE.read_text())
    assert asyncio.run(observe_stage_failure(rollback)) == expected[f"stage:{rollback}"]


def test_complete_definition_projection_precedes_any_registration():
    expected = json.loads(FAILURE_FIXTURE.read_text())
    assert observe_projection_failure() == expected["projection"]


@pytest.mark.parametrize("domain", ("base", "lsp", "arch"))
def test_registration_slot_keeps_original_binding_and_passthrough_contract(domain):
    expected = json.loads(FAILURE_FIXTURE.read_text())
    assert observe_slot(domain) == expected[f"slot:{domain}"]


async def observe_live_inputs(domain, change):
    initial_mode = "always" if change == "disable_before_stage" else "on_demand"
    owner, capture = build_owner(domain, mode=initial_mode)
    port = RecordingPort()
    binding = owner.bind(port)
    if change == "disable_before_stage":
        owner.mode = "on_demand"
    elif change == "enable_before_stage":
        owner.mode = "always"
    elif change == "scope_before_stage":
        owner.scope_id = "workspace:changed"
    elif change == "admission_before_stage":
        replacement, capture = build_owner(domain, revision=8)
        owner.admission = replacement.admission

    if change == "mode_between_tools":
        original_stage = port.stage_runtime_tool

        def stage_and_change(*args, **kwargs):
            result = original_stage(*args, **kwargs)
            owner.mode = "always"
            return result

        port.stage_runtime_tool = stage_and_change

    module = importlib.import_module(f"loushang.coding.{domain}._plugin_tool_owner")
    name = (
        "create_inspect_symbol_tool_definition"
        if domain == "lsp"
        else "create_inspect_import_graph_tool_definition"
    )
    original_factory = getattr(module, name)

    def project_then_change(*args, **kwargs):
        definition = original_factory(*args, **kwargs)
        replacement, _ = build_owner(domain, revision=8)
        owner.admission = replacement.admission
        owner.scope_id = "workspace:after-projection"
        owner.mode = "always"
        return definition

    if change == "metadata_after_projection":
        with patch.object(module, name, side_effect=project_then_change):
            value = binding.stage((capture,))
    else:
        value = binding.stage((capture,))
    if change == "receipt_after_stage":
        other, _ = build_owner("arch" if domain == "lsp" else "lsp")
        owner.admission = other.admission
    receipt = binding.retirement_receipt(value).to_dict()
    calls = [
        {
            k: call[k]
            for k in ("name", "enabled", "runtime_id", "generation", "source_fields")
        }
        for call in port.calls
    ]
    await binding.dispose(value)
    return {"calls": calls, "receipt": receipt}


LIVE_CHANGES = (
    "disable_before_stage",
    "enable_before_stage",
    "scope_before_stage",
    "admission_before_stage",
    "metadata_after_projection",
    "receipt_after_stage",
)
LIVE_FIXTURE = Path(__file__).parent / "fixtures/tool_pack_live_inputs_v1.json"


@pytest.mark.parametrize("domain", ("lsp", "arch"))
@pytest.mark.parametrize("change", LIVE_CHANGES)
def test_original_stage_and_receipt_field_reading_times(domain, change):
    expected = json.loads(LIVE_FIXTURE.read_text())
    assert (
        asyncio.run(observe_live_inputs(domain, change))
        == expected[f"{domain}:{change}"]
    )


def test_original_mode_is_read_for_each_tool_registration():
    expected = json.loads(LIVE_FIXTURE.read_text())
    assert (
        asyncio.run(observe_live_inputs("lsp", "mode_between_tools"))
        == expected["lsp:mode_between_tools"]
    )
