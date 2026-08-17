from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import cast

from loushang.harness.approval import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResolver,
    resolve_approval,
)
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.routing import (
    ExtensionRoutePlan,
    RegisteredExtensionHandler,
    ResolvedExtensionRoute,
)
from loushang.harness.extensions.types import (
    ExtensionPolicyDecision,
    LoadedExtension,
    RegisteredControlContribution,
    extension_is_active,
)
from loushang.harness.policy import (
    PolicyDecision,
    PolicyEvaluationError,
    PolicyEvaluator,
    PolicySubject,
    evaluate_policy,
)
from loushang.harness.resources.diagnostics import resource_diagnostic


@dataclass(frozen=True)
class ResolvedControlContributions:
    """Executable control-plane values after activation and route resolution."""

    policy_evaluators: tuple[PolicyEvaluator, ...]
    approval_resolver: ApprovalResolver | None
    policy_records: tuple[RegisteredControlContribution, ...]
    approval_records: tuple[RegisteredControlContribution, ...]
    selected_approval_record: RegisteredControlContribution | None


@dataclass(frozen=True)
class _ResolvedControlRecord:
    route: ResolvedExtensionRoute
    record: RegisteredControlContribution


@dataclass(frozen=True)
class _ExtensionPolicyEvaluator:
    resolved: _ResolvedControlRecord
    diagnostics: list[DiagnosticDraft]

    async def evaluate(self, subject: PolicySubject, /) -> PolicyDecision | None:
        try:
            return await evaluate_policy(
                cast(PolicyEvaluator, self.resolved.record.value),
                subject,
            )
        except PolicyEvaluationError as exc:
            self.diagnostics.append(
                _control_diagnostic(
                    self.resolved.route,
                    code="extension_policy_evaluation_failed",
                    message=(
                        f"Extension policy contribution "
                        f"{self.resolved.record.descriptor.name!r} failed: {exc}"
                    ),
                )
            )
            if self.resolved.record.descriptor.on_error == "fail_chain":
                raise
            return None


@dataclass(frozen=True)
class _ExtensionApprovalResolver:
    resolved: _ResolvedControlRecord
    diagnostics: list[DiagnosticDraft]

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        try:
            return await resolve_approval(
                cast(ApprovalResolver, self.resolved.record.value),
                request,
            )
        except Exception as exc:
            self.diagnostics.append(
                _control_diagnostic(
                    self.resolved.route,
                    code="extension_approval_resolution_failed",
                    message=(
                        f"Extension approval contribution "
                        f"{self.resolved.record.descriptor.name!r} failed: {exc}"
                    ),
                )
            )
            raise


def resolve_control_contributions(
    extensions: Sequence[LoadedExtension],
    *,
    diagnostics: list[DiagnosticDraft],
) -> ResolvedControlContributions:
    """Resolve policy chains and the exclusive approval replacement.

    Policy records remain in resolved order and are wrapped so their declared
    error policy is preserved. The first resolved approval record wins; later
    active records are retained for inspection and reported as one conflict.
    """

    records_by_registration: dict[int, RegisteredControlContribution] = {}
    extension_registrations: list[
        tuple[LoadedExtension, tuple[RegisteredExtensionHandler, ...]]
    ] = []
    for extension in extensions:
        registrations: list[RegisteredExtensionHandler] = []
        inactive_registrations: list[RegisteredExtensionHandler] = []
        extension_active = extension_is_active(extension)
        for record in extension.control_contributions:
            descriptor = record.descriptor
            record_active = extension_active and descriptor.active
            if record_active:
                if (
                    descriptor.type == "approval"
                    and descriptor.on_error != "fail_chain"
                ):
                    diagnostics.append(
                        _invalid_control_diagnostic(
                            extension,
                            record,
                            reason=(
                                "approval is an exclusive replacement and must "
                                "use on_error='fail_chain'"
                            ),
                        )
                    )
                    continue
                required_method = (
                    "evaluate" if descriptor.type == "policy" else "resolve"
                )
                try:
                    control_method = getattr(record.value, required_method, None)
                except Exception as exc:
                    diagnostics.append(
                        _invalid_control_diagnostic(
                            extension,
                            record,
                            required_method=required_method,
                            reason=f"accessing {required_method} failed: {exc}",
                        )
                    )
                    continue
                if not callable(control_method):
                    diagnostics.append(
                        _invalid_control_diagnostic(
                            extension,
                            record,
                            required_method=required_method,
                        )
                    )
                    continue
            try:
                registration = RegisteredExtensionHandler(
                    local_route_id=descriptor.name,
                    event_name=descriptor.type,
                    handler=_control_marker,
                    priority=descriptor.priority if record_active else 0,
                    after=descriptor.after if record_active else (),
                    before=descriptor.before if record_active else (),
                    on_error=descriptor.on_error if record_active else "skip",
                )
            except (TypeError, ValueError) as exc:
                if record_active:
                    diagnostics.append(
                        _invalid_control_diagnostic(
                            extension,
                            record,
                            reason=str(exc),
                        )
                    )
                continue
            if record_active:
                records_by_registration[id(registration)] = record
                registrations.append(registration)
            else:
                inactive_registrations.append(registration)
        extension_registrations.append((extension, tuple(registrations)))
        if extension_active and inactive_registrations:
            inactive_extension = replace(
                extension,
                policy=ExtensionPolicyDecision(enabled=False),
            )
            extension_registrations.append(
                (inactive_extension, tuple(inactive_registrations))
            )
        elif inactive_registrations:
            extension_registrations[-1] = (
                extension,
                tuple(inactive_registrations),
            )

    plan = ExtensionRoutePlan.from_extension_registrations(
        extension_registrations,
        diagnostics=diagnostics,
    )
    policies = tuple(
        _ResolvedControlRecord(
            route=route,
            record=records_by_registration[id(route.registration)],
        )
        for route in plan.routes_for("policy")
    )
    approvals = tuple(
        _ResolvedControlRecord(
            route=route,
            record=records_by_registration[id(route.registration)],
        )
        for route in plan.routes_for("approval")
    )

    if len(approvals) > 1:
        selected = approvals[0]
        diagnostics.append(
            _control_diagnostic(
                selected.route,
                code="conflicting_extension_approval_contributions",
                message=(
                    "Multiple active approval contributions resolved for the "
                    f"exclusive slot; selected {selected.route.route_id!r}."
                ),
                metadata={
                    "selected_route_id": selected.route.route_id,
                    "conflicting_route_ids": tuple(
                        resolved.route.route_id for resolved in approvals[1:]
                    ),
                },
            )
        )

    selected_approval = approvals[0] if approvals else None
    return ResolvedControlContributions(
        policy_evaluators=tuple(
            _ExtensionPolicyEvaluator(resolved, diagnostics) for resolved in policies
        ),
        approval_resolver=(
            _ExtensionApprovalResolver(selected_approval, diagnostics)
            if selected_approval is not None
            else None
        ),
        policy_records=tuple(resolved.record for resolved in policies),
        approval_records=tuple(resolved.record for resolved in approvals),
        selected_approval_record=(
            selected_approval.record if selected_approval is not None else None
        ),
    )


def _control_marker(event: object, context: object) -> None:
    del event, context


def _invalid_control_diagnostic(
    extension: LoadedExtension,
    record: RegisteredControlContribution,
    *,
    required_method: str | None = None,
    reason: str | None = None,
) -> DiagnosticDraft:
    descriptor = record.descriptor
    if reason is None:
        reason = f"value must provide callable {required_method}()"
    return resource_diagnostic(
        code="invalid_extension_control_contribution",
        message=(
            f"Invalid extension {descriptor.type} contribution "
            f"{descriptor.name!r}: {reason}."
        ),
        source_path=extension.source_path,
        resource_id=descriptor.name,
        resource_type="extension",
        source_kind=extension.source_kind,
        metadata={
            "extension_name": extension.name,
            "contribution_type": descriptor.type,
            "required_method": required_method or "",
        },
    )


def _control_diagnostic(
    route: ResolvedExtensionRoute,
    *,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> DiagnosticDraft:
    source_info = route.source_info
    return resource_diagnostic(
        code=code,
        message=message,
        source_path=route.extension.source_path,
        resource_id=route.registration.local_route_id,
        resource_type="extension",
        source_kind=route.extension.source_kind,
        metadata={
            "extension_name": route.extension.name,
            "route_id": route.route_id,
            "source": source_info.source,
            "scope": source_info.scope,
            "origin": source_info.origin,
            "base_dir": (
                source_info.base_dir.as_posix()
                if source_info.base_dir is not None
                else route.extension.source_path.parent.as_posix()
            ),
            **(metadata or {}),
        },
    )


__all__ = [
    "ResolvedControlContributions",
    "resolve_control_contributions",
]
