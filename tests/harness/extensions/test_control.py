from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.approval import ApprovalDecision, ApprovalRequest
from loushang.harness.extensions.api import ExtensionContributionAPI
from loushang.harness.extensions.contributions import surfaces_from_loaded_extension
from loushang.harness.extensions.control import resolve_control_contributions
from loushang.harness.extensions.manifest import ExtensionManifest
from loushang.harness.extensions.types import ExtensionPolicyDecision
from loushang.harness.policy import (
    CustomPolicySubject,
    PolicyDecision,
    PolicyEvaluationError,
)


class _Evaluator:
    def __init__(
        self,
        decision: PolicyDecision | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.decision = decision
        self.error = error

    def evaluate(self, subject):
        del subject
        if self.error is not None:
            raise self.error
        return self.decision


class _Resolver:
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision

    def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        del request
        return self.decision


def _api(name: str) -> ExtensionContributionAPI:
    return ExtensionContributionAPI(
        name=name,
        source_path=Path(f"/tmp/{name}"),
        entry_path=Path(f"/tmp/{name}/extension.py"),
    )


def test_control_api_keeps_runtime_values_out_of_surface_metadata() -> None:
    evaluator = _Evaluator(PolicyDecision.allow())
    resolver = _Resolver(ApprovalDecision.allow())
    api = _api("runtime-name")

    api.register_policy(
        " guard ",
        evaluator,
        priority=20,
        after=(" extension:base ",),
        on_error="fail_chain",
    )
    api.register_approval("interactive", resolver)

    extension = api.build_loaded_extension()
    policy, approval = extension.control_contributions
    assert policy.descriptor.name == "guard"
    assert policy.descriptor.after == ("extension:base",)
    assert policy.descriptor.on_error == "fail_chain"
    assert policy.value is evaluator
    assert approval.value is resolver
    assert approval.descriptor.on_error == "fail_chain"
    assert "value" not in policy.descriptor.metadata

    projected = surfaces_from_loaded_extension(
        replace(
            extension,
            manifest=ExtensionManifest(id="manifest-id", name="Manifest"),
        )
    )
    controls = [
        surface for surface in projected if surface.type in {"policy", "approval"}
    ]
    assert [(surface.type, surface.name) for surface in controls] == [
        ("policy", "guard"),
        ("approval", "interactive"),
    ]
    assert {surface.extension_id for surface in controls} == {"manifest-id"}


def test_policy_control_contributions_fail_chain_by_default() -> None:
    api = _api("secure-default")
    api.register_policy("guard", _Evaluator(PolicyDecision.allow()))

    record = api.build_loaded_extension().control_contributions[0]

    assert record.descriptor.on_error == "fail_chain"


def test_control_api_rejects_invalid_ordering_metadata() -> None:
    api = _api("invalid")

    with pytest.raises(TypeError, match="priority"):
        api.register_policy("guard", _Evaluator(), priority=True)
    with pytest.raises(TypeError, match="sequence of strings"):
        api.register_policy("guard", _Evaluator(), after="extension:base")
    with pytest.raises(ValueError, match="error policy"):
        api.register_policy(
            "guard",
            _Evaluator(),
            on_error="unknown",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        api.register_approval(  # type: ignore[call-arg]
            "interactive",
            _Resolver(ApprovalDecision.allow()),
            on_error="skip",
        )


def test_control_resolver_rejects_skip_semantics_for_exclusive_approval() -> None:
    api = _api("invalid-approval-semantics")
    api.register_approval("interactive", _Resolver(ApprovalDecision.allow()))
    extension = api.build_loaded_extension()
    record = extension.control_contributions[0]
    extension = replace(
        extension,
        control_contributions=[
            replace(
                record,
                descriptor=replace(record.descriptor, on_error="skip"),
            )
        ],
    )
    diagnostics = []

    resolved = resolve_control_contributions([extension], diagnostics=diagnostics)

    assert resolved.approval_resolver is None
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "invalid_extension_control_contribution"
    ]
    assert "exclusive replacement" in diagnostics[0].message


def test_control_resolver_isolates_shape_property_failures() -> None:
    class ExplosiveEvaluator:
        @property
        def evaluate(self):
            raise RuntimeError("shape inspection failed")

    api = _api("broken-shape")
    api.register_policy("guard", ExplosiveEvaluator())
    diagnostics = []

    resolved = resolve_control_contributions(
        [api.build_loaded_extension()],
        diagnostics=diagnostics,
    )

    assert resolved.policy_evaluators == ()
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "invalid_extension_control_contribution"
    ]
    assert "shape inspection failed" in diagnostics[0].message


def test_resolver_returns_all_policies_in_resolved_order() -> None:
    base_api = _api("base")
    base_evaluator = _Evaluator(PolicyDecision.allow())
    base_api.register_policy("base", base_evaluator)
    tail_api = _api("tail")
    tail_evaluator = _Evaluator(PolicyDecision.ask("review"))
    tail_api.register_policy(
        "tail",
        tail_evaluator,
        priority=100,
        after=("route:base/policy/base",),
    )
    diagnostics = []

    resolved = resolve_control_contributions(
        [tail_api.build_loaded_extension(), base_api.build_loaded_extension()],
        diagnostics=diagnostics,
    )

    assert [record.descriptor.name for record in resolved.policy_records] == [
        "base",
        "tail",
    ]
    assert len(resolved.policy_evaluators) == 2
    assert resolved.approval_resolver is None
    assert diagnostics == []


def test_policy_wrapper_honors_skip_and_fail_chain() -> None:
    skip_api = _api("skip")
    skip_api.register_policy(
        "broken",
        _Evaluator(error=RuntimeError("skip failure")),
        on_error="skip",
    )
    fail_api = _api("fail")
    fail_api.register_policy(
        "broken",
        _Evaluator(error=RuntimeError("fail failure")),
        on_error="fail_chain",
    )
    diagnostics = []
    skip = resolve_control_contributions(
        [skip_api.build_loaded_extension()],
        diagnostics=diagnostics,
    )

    decision = asyncio.run(
        skip.policy_evaluators[0].evaluate(CustomPolicySubject(kind="tool"))
    )

    assert decision is None
    assert diagnostics[0].code == "extension_policy_evaluation_failed"
    assert diagnostics[0].details["metadata"]["route_id"] == "skip/policy/broken"

    fail = resolve_control_contributions(
        [fail_api.build_loaded_extension()],
        diagnostics=diagnostics,
    )
    with pytest.raises(PolicyEvaluationError, match="fail failure"):
        asyncio.run(
            fail.policy_evaluators[0].evaluate(CustomPolicySubject(kind="tool"))
        )
    assert [item.code for item in diagnostics] == [
        "extension_policy_evaluation_failed",
        "extension_policy_evaluation_failed",
    ]


def test_approval_uses_first_resolved_valid_active_record_and_reports_conflict() -> (
    None
):
    low_api = _api("low")
    low_resolver = _Resolver(ApprovalDecision.deny("low"))
    low_api.register_approval("low", low_resolver)
    high_api = _api("high")
    high_resolver = _Resolver(ApprovalDecision.allow())
    high_api.register_approval("high", high_resolver, priority=10)
    invalid_api = _api("invalid")
    invalid_api.register_approval("invalid", object(), priority=100)
    diagnostics = []

    resolved = resolve_control_contributions(
        [
            low_api.build_loaded_extension(),
            invalid_api.build_loaded_extension(),
            high_api.build_loaded_extension(),
        ],
        diagnostics=diagnostics,
    )

    assert resolved.approval_resolver is not None
    assert (
        asyncio.run(
            resolved.approval_resolver.resolve(
                ApprovalRequest(tool_name="write", arguments={})
            )
        )
        == ApprovalDecision.allow()
    )
    assert resolved.selected_approval_record is resolved.approval_records[0]
    assert [record.descriptor.name for record in resolved.approval_records] == [
        "high",
        "low",
    ]
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "invalid_extension_control_contribution",
        "conflicting_extension_approval_contributions",
    ]
    conflict = diagnostics[1]
    assert conflict.details["metadata"]["selected_route_id"] == "high/approval/high"
    assert conflict.details["metadata"]["conflicting_route_ids"] == (
        "low/approval/low",
    )


def test_approval_conflict_survives_duplicate_extension_and_contribution_ids() -> None:
    first_api = _api("duplicate")
    first_resolver = _Resolver(ApprovalDecision.allow())
    first_api.register_approval("interactive", first_resolver)
    second_api = _api("duplicate")
    second_resolver = _Resolver(ApprovalDecision.deny("second"))
    second_api.register_approval("interactive", second_resolver)
    diagnostics = []

    resolved = resolve_control_contributions(
        [first_api.build_loaded_extension(), second_api.build_loaded_extension()],
        diagnostics=diagnostics,
    )

    assert resolved.approval_resolver is not None
    assert (
        asyncio.run(
            resolved.approval_resolver.resolve(
                ApprovalRequest(tool_name="write", arguments={})
            )
        )
        == ApprovalDecision.allow()
    )
    assert len(resolved.approval_records) == 2
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "duplicate_extension_route_id",
        "conflicting_extension_approval_contributions",
    ]
    assert diagnostics[1].details["metadata"]["conflicting_route_ids"] == (
        "duplicate/approval/interactive#duplicate-2",
    )


@pytest.mark.parametrize("failure_kind", ["sync", "async", "invalid"])
def test_approval_wrapper_reports_extension_failures_and_propagates(
    failure_kind: str,
) -> None:
    class FailingResolver:
        def resolve(self, request: ApprovalRequest):
            del request
            if failure_kind == "sync":
                raise RuntimeError("sync approval failed")
            if failure_kind == "invalid":
                return object()

            async def fail():
                raise LookupError("async approval failed")

            return fail()

    api = _api(f"approval-{failure_kind}")
    api.register_approval("interactive", FailingResolver())
    diagnostics = []
    resolved = resolve_control_contributions(
        [api.build_loaded_extension()],
        diagnostics=diagnostics,
    )
    assert resolved.approval_resolver is not None

    expected_error = {
        "sync": RuntimeError,
        "async": LookupError,
        "invalid": TypeError,
    }[failure_kind]
    with pytest.raises(expected_error):
        asyncio.run(
            resolved.approval_resolver.resolve(
                ApprovalRequest(tool_name="write", arguments={})
            )
        )

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "extension_approval_resolution_failed"
    ]
    assert diagnostics[0].details["metadata"]["route_id"] == (
        f"approval-{failure_kind}/approval/interactive"
    )


def test_approval_wrapper_does_not_diagnose_cancellation() -> None:
    class CancelledResolver:
        async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
            del request
            raise asyncio.CancelledError

    api = _api("cancelled-approval")
    api.register_approval("interactive", CancelledResolver())
    diagnostics = []
    resolved = resolve_control_contributions(
        [api.build_loaded_extension()],
        diagnostics=diagnostics,
    )
    assert resolved.approval_resolver is not None

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            resolved.approval_resolver.resolve(
                ApprovalRequest(tool_name="write", arguments={})
            )
        )

    assert diagnostics == []


def test_inactive_control_routes_are_known_without_inspecting_runtime_values() -> None:
    class ExplosiveEvaluator:
        @property
        def evaluate(self):
            raise AssertionError("inactive contribution must not be inspected")

    optional_api = _api("optional")
    optional_api.register_policy("guard", ExplosiveEvaluator())
    optional = replace(
        optional_api.build_loaded_extension(),
        policy=ExtensionPolicyDecision(enabled=False),
    )

    partial_api = _api("partial")
    partial_api.register_policy("disabled", ExplosiveEvaluator())
    partial = partial_api.build_loaded_extension()
    partial_record = partial.control_contributions[0]
    partial = replace(
        partial,
        control_contributions=[
            replace(
                partial_record,
                descriptor=replace(partial_record.descriptor, active=False),
            )
        ],
    )

    active_api = _api("active")
    active_evaluator = _Evaluator(PolicyDecision.allow())
    active_api.register_policy(
        "active",
        active_evaluator,
        after=(
            "route:optional/policy/guard",
            "route:partial/policy/disabled",
        ),
    )
    diagnostics = []

    resolved = resolve_control_contributions(
        [optional, partial, active_api.build_loaded_extension()],
        diagnostics=diagnostics,
    )

    assert [record.value for record in resolved.policy_records] == [active_evaluator]
    assert diagnostics == []
