"""Transactional construction and retirement for accepted Capability plans."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass

from loushang.harness.capabilities.graph_planning import (
    PlannedCapability,
    RuntimeCapabilityGraphPlan,
)
from loushang.harness.capabilities.graph_runtime import (
    CapabilityGraphBindingAttempt,
    MountGraphSnapshot,
    MountNodeSnapshot,
    MountRequirementSnapshot,
    RegistrationAttachmentState,
    RegistrationInventoryEntry,
    RegistrationInventorySnapshot,
    RuntimeCapabilityGraphRuntime,
    _MountedCapability,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityDependencyBinding,
    CapabilityProviderContext,
    CapabilityRegistrationCollector,
)
from loushang.harness.runtime.bindings import RuntimeBindingState
from loushang.harness.runtime.registration import (
    RegistrationOwner,
    RegistrationScope,
    _await_cancellation_atomic,
)


@dataclass(frozen=True)
class CapabilityGraphBindResult:
    snapshot: MountGraphSnapshot
    created_capability_ids: tuple[str, ...]
    reused_capability_ids: tuple[str, ...]
    retirement_diagnostic_codes: tuple[str, ...] = ()


class CapabilityGraphBindingError(RuntimeError):
    """Redacted graph binding failure that preserves the prior committed graph."""

    def __init__(self, diagnostic_codes: tuple[str, ...]) -> None:
        self.diagnostic_codes = tuple(sorted(set(diagnostic_codes)))
        super().__init__(
            "Capability graph binding failed: " + ", ".join(self.diagnostic_codes)
        )


class RuntimeCapabilityGraphBinder:
    """Bind one pure plan transactionally without becoming a graph authority."""

    async def bind(
        self,
        runtime: RuntimeCapabilityGraphRuntime,
        plan: RuntimeCapabilityGraphPlan,
        provider_bindings: tuple[CapabilityBundleProviderBinding, ...],
    ) -> CapabilityGraphBindResult:
        if not isinstance(runtime, RuntimeCapabilityGraphRuntime):
            raise TypeError("graph Binder requires RuntimeCapabilityGraphRuntime")
        if not isinstance(plan, RuntimeCapabilityGraphPlan):
            raise TypeError("graph Binder requires RuntimeCapabilityGraphPlan")
        bindings = tuple(provider_bindings)
        if any(
            not isinstance(item, CapabilityBundleProviderBinding) for item in bindings
        ):
            raise TypeError(
                "provider_bindings must contain CapabilityBundleProviderBinding values"
            )

        async with runtime._binding_lock:
            if runtime._closed:
                raise RuntimeError("Capability Mount graph is disposed")
            if plan.product_id != runtime.product_id:
                raise ValueError("graph plan Product does not match graph runtime")

            attempt_number = runtime._next_attempt_number()
            target_generation = runtime.generation + 1
            try:
                indexed = _index_bindings(plan, bindings)
                signatures = _binding_signatures(plan, indexed)
                assembly_fingerprint = _assembly_fingerprint(
                    runtime,
                    plan,
                    signatures,
                )
            except CapabilityGraphBindingError as exc:
                runtime._last_attempt = CapabilityGraphBindingAttempt(
                    attempt_number=attempt_number,
                    state="failed",
                    target_generation=target_generation,
                    assembly_fingerprint=None,
                    diagnostic_codes=exc.diagnostic_codes,
                )
                raise

            current = runtime.snapshot
            if (
                current is not None
                and current.assembly_fingerprint == assembly_fingerprint
            ):
                reused = plan.binding_order
                runtime._last_attempt = CapabilityGraphBindingAttempt(
                    attempt_number=attempt_number,
                    state="committed",
                    target_generation=runtime.generation,
                    assembly_fingerprint=assembly_fingerprint,
                    reused_capability_ids=reused,
                )
                return CapabilityGraphBindResult(
                    snapshot=current,
                    created_capability_ids=(),
                    reused_capability_ids=reused,
                )

            candidate: dict[str, _MountedCapability] = {}
            staged: list[_MountedCapability] = []
            constructing_scopes: list[RegistrationScope] = []
            reused_ids: list[str] = []
            created_ids: list[str] = []
            try:
                for node in plan.nodes:
                    capability_id = node.capability_id
                    previous = runtime._nodes.get(capability_id)
                    signature = signatures[capability_id]
                    if previous is not None and previous.binding_signature == signature:
                        candidate[capability_id] = previous
                        reused_ids.append(capability_id)
                        continue

                    binding = indexed[capability_id]
                    owner = RegistrationOwner(
                        owner_kind="capability",
                        owner_id=capability_id,
                        runtime_id=runtime.runtime_id,
                        generation=target_generation,
                    )
                    registration_scope = RegistrationScope(owner)
                    constructing_scopes.append(registration_scope)
                    dependencies = tuple(
                        CapabilityDependencyBinding(
                            requirement=requirement,
                            _value=candidate[requirement.capability].value,
                        )
                        for requirement in node.requirements
                    )
                    value = await binding.construct(
                        CapabilityProviderContext(
                            product_id=runtime.product_id,
                            runtime_id=runtime.runtime_id,
                            generation=target_generation,
                            registrations=CapabilityRegistrationCollector(
                                registration_scope
                            ),
                            dependencies=dependencies,
                        )
                    )
                    mounted = _MountedCapability(
                        planned=node,
                        provider_binding=binding,
                        value=value,
                        binding_state=RuntimeBindingState(
                            value,
                            unbound_message="Capability is no longer mounted.",
                            stale_message="Capability facet lease is stale.",
                        ),
                        registration_scope=registration_scope,
                        binding_signature=signature,
                        mount_generation=target_generation,
                    )
                    staged.append(mounted)
                    constructing_scopes.remove(registration_scope)
                    if set(value.facet_ids) != set(node.provider.facets):
                        raise CapabilityGraphBindingError(
                            ("provider_returned_invalid_facets",)
                        )
                    candidate[capability_id] = mounted
                    created_ids.append(capability_id)

                # Deliver cancellation before entering the no-await publication window.
                await asyncio.sleep(0)
                for mounted in staged:
                    mounted.registration_scope.commit()
                snapshot = _mount_snapshot(
                    runtime,
                    plan,
                    candidate,
                    target_generation=target_generation,
                    assembly_fingerprint=assembly_fingerprint,
                )
            except asyncio.CancelledError as cancelled:
                rollback_codes, _ = await _cleanup_candidate_and_retain(
                    runtime,
                    tuple(constructing_scopes),
                    tuple(staged),
                )
                runtime._last_attempt = CapabilityGraphBindingAttempt(
                    attempt_number=attempt_number,
                    state="cancelled",
                    target_generation=target_generation,
                    assembly_fingerprint=assembly_fingerprint,
                    created_capability_ids=tuple(created_ids),
                    reused_capability_ids=tuple(reused_ids),
                    diagnostic_codes=rollback_codes,
                )
                raise cancelled
            except Exception as exc:
                rollback_codes, cleanup_cancellation = (
                    await _cleanup_candidate_and_retain(
                        runtime,
                        tuple(constructing_scopes),
                        tuple(staged),
                    )
                )
                if cleanup_cancellation is not None:
                    runtime._last_attempt = CapabilityGraphBindingAttempt(
                        attempt_number=attempt_number,
                        state="cancelled",
                        target_generation=target_generation,
                        assembly_fingerprint=assembly_fingerprint,
                        created_capability_ids=tuple(created_ids),
                        reused_capability_ids=tuple(reused_ids),
                        diagnostic_codes=rollback_codes,
                    )
                    raise cleanup_cancellation from exc
                code = (
                    exc.diagnostic_codes
                    if isinstance(exc, CapabilityGraphBindingError)
                    else ("provider_construction_failed",)
                )
                diagnostic_codes = tuple((*code, *rollback_codes))
                runtime._last_attempt = CapabilityGraphBindingAttempt(
                    attempt_number=attempt_number,
                    state="failed",
                    target_generation=target_generation,
                    assembly_fingerprint=assembly_fingerprint,
                    created_capability_ids=tuple(created_ids),
                    reused_capability_ids=tuple(reused_ids),
                    diagnostic_codes=diagnostic_codes,
                )
                raise CapabilityGraphBindingError(diagnostic_codes) from exc

            previous_nodes = runtime._nodes
            replaced = tuple(
                previous_nodes[capability_id]
                for capability_id in reversed(tuple(previous_nodes))
                if candidate.get(capability_id) is not previous_nodes[capability_id]
            )
            runtime._nodes = candidate
            runtime._generation = target_generation
            runtime._snapshot = snapshot
            _record_incomplete_retirements(runtime, replaced)
            _publish_registration_inventory(runtime)
            for mounted in replaced:
                mounted.binding_state.invalidate()

            runtime._last_attempt = CapabilityGraphBindingAttempt(
                attempt_number=attempt_number,
                state="committed",
                target_generation=target_generation,
                assembly_fingerprint=assembly_fingerprint,
                created_capability_ids=tuple(created_ids),
                reused_capability_ids=tuple(reused_ids),
            )
            cleanup_task = asyncio.create_task(_cleanup_nodes_once(replaced))
            try:
                retirement_codes = await _await_cancellation_atomic(cleanup_task)
            except asyncio.CancelledError:
                retirement_codes = cleanup_task.result()
                _prune_completed_cleanup(runtime)
                _publish_registration_inventory(runtime)
                runtime._last_attempt = CapabilityGraphBindingAttempt(
                    attempt_number=attempt_number,
                    state="committed",
                    target_generation=target_generation,
                    assembly_fingerprint=assembly_fingerprint,
                    created_capability_ids=tuple(created_ids),
                    reused_capability_ids=tuple(reused_ids),
                    diagnostic_codes=retirement_codes,
                )
                raise
            _prune_completed_cleanup(runtime)
            _publish_registration_inventory(runtime)
            runtime._last_attempt = CapabilityGraphBindingAttempt(
                attempt_number=attempt_number,
                state="committed",
                target_generation=target_generation,
                assembly_fingerprint=assembly_fingerprint,
                created_capability_ids=tuple(created_ids),
                reused_capability_ids=tuple(reused_ids),
                diagnostic_codes=retirement_codes,
            )
            return CapabilityGraphBindResult(
                snapshot=snapshot,
                created_capability_ids=tuple(created_ids),
                reused_capability_ids=tuple(reused_ids),
                retirement_diagnostic_codes=retirement_codes,
            )

    async def dispose(self, runtime: RuntimeCapabilityGraphRuntime) -> tuple[str, ...]:
        """Retire every owned Mount exactly once and invalidate Consumer leases."""

        if not isinstance(runtime, RuntimeCapabilityGraphRuntime):
            raise TypeError("graph Binder requires RuntimeCapabilityGraphRuntime")
        async with runtime._binding_lock:
            if (
                runtime._closed
                and not runtime._retired_nodes
                and not runtime._retired_scopes
            ):
                attempt = runtime.last_attempt
                return () if attempt is None else attempt.diagnostic_codes
            nodes = (
                ()
                if runtime._closed
                else tuple(reversed(tuple(runtime._nodes.values())))
            )
            if not runtime._closed:
                for mounted in nodes:
                    mounted.binding_state.invalidate(
                        "Capability Mount graph is disposed."
                    )
                runtime._nodes = {}
                runtime._closed = True
                _record_incomplete_retirements(runtime, nodes)
            retiring_nodes = tuple(runtime._retired_nodes)
            retiring_scopes = tuple(runtime._retired_scopes)
            _publish_registration_inventory(runtime)
            runtime._last_attempt = CapabilityGraphBindingAttempt(
                attempt_number=runtime._next_attempt_number(),
                state="disposed",
                target_generation=runtime.generation,
                assembly_fingerprint=(
                    None
                    if runtime.snapshot is None
                    else runtime.snapshot.assembly_fingerprint
                ),
            )
            cleanup_task = asyncio.create_task(
                _cleanup_candidate_once(retiring_scopes, retiring_nodes)
            )
            try:
                codes = await _await_cancellation_atomic(cleanup_task)
            except asyncio.CancelledError:
                codes = cleanup_task.result()
                _prune_completed_cleanup(runtime)
                _publish_registration_inventory(runtime)
                runtime._last_attempt = CapabilityGraphBindingAttempt(
                    attempt_number=runtime._attempt_number,
                    state="disposed",
                    target_generation=runtime.generation,
                    assembly_fingerprint=(
                        None
                        if runtime.snapshot is None
                        else runtime.snapshot.assembly_fingerprint
                    ),
                    diagnostic_codes=codes,
                )
                raise
            _prune_completed_cleanup(runtime)
            _publish_registration_inventory(runtime)
            runtime._last_attempt = CapabilityGraphBindingAttempt(
                attempt_number=runtime._attempt_number,
                state="disposed",
                target_generation=runtime.generation,
                assembly_fingerprint=(
                    None
                    if runtime.snapshot is None
                    else runtime.snapshot.assembly_fingerprint
                ),
                diagnostic_codes=codes,
            )
            return codes


def _index_bindings(
    plan: RuntimeCapabilityGraphPlan,
    bindings: tuple[CapabilityBundleProviderBinding, ...],
) -> dict[str, CapabilityBundleProviderBinding]:
    indexed: dict[str, CapabilityBundleProviderBinding] = {}
    duplicates: set[str] = set()
    for binding in bindings:
        capability_id = binding.provider.capability_id
        if capability_id in indexed:
            duplicates.add(capability_id)
        indexed[capability_id] = binding
    expected = set(plan.binding_order)
    actual = set(indexed)
    codes: list[str] = []
    if duplicates:
        codes.append("duplicate_provider_binding")
    if expected - actual:
        codes.append("missing_provider_binding")
    if actual - expected:
        codes.append("unexpected_provider_binding")
    for node in plan.nodes:
        if any(
            requirement.binding == "stable_reference"
            for requirement in node.requirements
        ):
            codes.append("stable_reference_binding_not_implemented")
        selected_binding = indexed.get(node.capability_id)
        if selected_binding is not None and selected_binding.provider != node.provider:
            codes.append("provider_binding_metadata_mismatch")
    if codes:
        raise CapabilityGraphBindingError(tuple(codes))
    return indexed


def _binding_signatures(
    plan: RuntimeCapabilityGraphPlan,
    bindings: dict[str, CapabilityBundleProviderBinding],
) -> dict[str, str]:
    signatures: dict[str, str] = {}
    for node in plan.nodes:
        binding = bindings[node.capability_id]
        payload = {
            "binding_input_fingerprint": binding.binding_input_fingerprint,
            "capability": _planned_node_payload(node),
            "dependency_signatures": [
                [dependency_id, signatures[dependency_id]]
                for dependency_id in node.dependency_ids
            ],
            "scope_instance_id": binding.scope_instance_id,
        }
        signatures[node.capability_id] = _fingerprint(payload)
    return signatures


def _planned_node_payload(node: PlannedCapability) -> dict[str, object]:
    definition = node.definition
    provider = node.provider
    return {
        "authority_ceiling": sorted(definition.authority_ceiling),
        "capability_id": node.capability_id,
        "contract_version": definition.contract_version,
        "definition_facets": list(definition.facets),
        "owner_id": definition.owner_id,
        "phase": definition.phase,
        "provider": {
            "compatible_contract": [
                provider.compatible_contract.minimum,
                provider.compatible_contract.maximum,
            ],
            "facets": list(provider.facets),
            "implementation_version": provider.implementation_version,
            "provider_id": provider.provider_id,
            "required_authorities": sorted(provider.required_authorities),
            "selection_rule": provider.selection_rule,
            "source_id": provider.source_id,
        },
        "refresh_boundary": definition.refresh_boundary,
        "requirements": [
            {
                "binding": requirement.binding,
                "capability": requirement.capability,
                "compatible_contract": [
                    requirement.compatible_contract.minimum,
                    requirement.compatible_contract.maximum,
                ],
                "facets": list(requirement.facets),
                "optional": requirement.optional,
            }
            for requirement in node.requirements
        ],
        "scope": definition.scope,
    }


def _assembly_fingerprint(
    runtime: RuntimeCapabilityGraphRuntime,
    plan: RuntimeCapabilityGraphPlan,
    signatures: dict[str, str],
) -> str:
    return _fingerprint(
        {
            "nodes": [
                [capability_id, signatures[capability_id]]
                for capability_id in plan.binding_order
            ],
            "product_id": runtime.product_id,
            "profile_fingerprint": runtime.profile_fingerprint,
            "roots": list(plan.roots),
            "runtime_id": runtime.runtime_id,
            "schema_version": 1,
        }
    )


def _mount_snapshot(
    runtime: RuntimeCapabilityGraphRuntime,
    plan: RuntimeCapabilityGraphPlan,
    mounted_nodes: dict[str, _MountedCapability],
    *,
    target_generation: int,
    assembly_fingerprint: str,
) -> MountGraphSnapshot:
    required_by: dict[str, list[str]] = {
        capability_id: [] for capability_id in plan.binding_order
    }
    for node in plan.nodes:
        for dependency_id in node.dependency_ids:
            required_by[dependency_id].append(node.capability_id)
    snapshots = tuple(
        MountNodeSnapshot(
            capability_id=node.capability_id,
            owner_id=node.definition.owner_id,
            contract_version=node.definition.contract_version,
            facets=node.provider.facets,
            scope=node.definition.scope,
            scope_instance_id=mounted_nodes[
                node.capability_id
            ].provider_binding.scope_instance_id,
            refresh_boundary=node.definition.refresh_boundary,
            phase=node.definition.phase,
            mount_generation=mounted_nodes[node.capability_id].mount_generation,
            provider_id=node.provider.provider_id,
            provider_version=node.provider.implementation_version,
            provider_source_id=node.provider.source_id,
            selection_rule=node.provider.selection_rule,
            binding_signature=mounted_nodes[node.capability_id].binding_signature,
            requirements=tuple(
                MountRequirementSnapshot(
                    capability_id=requirement.capability,
                    facets=requirement.facets,
                    minimum_contract_version=requirement.compatible_contract.minimum,
                    maximum_contract_version=requirement.compatible_contract.maximum,
                    binding=requirement.binding,
                )
                for requirement in node.requirements
            ),
            required_by=tuple(sorted(required_by[node.capability_id])),
        )
        for node in plan.nodes
    )
    return MountGraphSnapshot(
        schema_version=1,
        graph_id=runtime.graph_id,
        product_id=runtime.product_id,
        runtime_id=runtime.runtime_id,
        profile_fingerprint=runtime.profile_fingerprint,
        generation=target_generation,
        roots=plan.roots,
        assembly_fingerprint=assembly_fingerprint,
        nodes=snapshots,
    )


def _registration_inventory(
    runtime: RuntimeCapabilityGraphRuntime,
) -> RegistrationInventorySnapshot:
    scopes: list[tuple[RegistrationScope, RegistrationAttachmentState]] = []
    seen_scopes: set[int] = set()
    for mounted in runtime._nodes.values():
        scope = mounted.registration_scope
        if id(scope) not in seen_scopes:
            scopes.append((scope, "effective"))
            seen_scopes.add(id(scope))
    for mounted in runtime._retired_nodes:
        scope = mounted.registration_scope
        if id(scope) not in seen_scopes:
            scopes.append((scope, "pending_retirement"))
            seen_scopes.add(id(scope))
    for scope in runtime._retired_scopes:
        if id(scope) not in seen_scopes:
            scopes.append((scope, "pending_retirement"))
            seen_scopes.add(id(scope))

    entries = tuple(
        sorted(
            (
                RegistrationInventoryEntry(
                    registration_id=identity.registration_id,
                    surface=identity.surface,
                    public_key=identity.public_key,
                    owner_kind=owner.owner_kind,
                    owner_id=owner.owner_id,
                    runtime_id=owner.runtime_id,
                    owner_generation=owner.generation,
                    attachment=attachment,
                    state=state,
                )
                for scope, attachment in scopes
                for owner, identity, state in scope.inventory
                if state != "disposed"
            ),
            key=lambda entry: (
                entry.owner_id,
                entry.surface,
                entry.public_key or "",
                entry.registration_id,
            ),
        )
    )
    revision = _fingerprint(
        {
            "entries": [
                {
                    "owner_generation": entry.owner_generation,
                    "owner_id": entry.owner_id,
                    "owner_kind": entry.owner_kind,
                    "attachment": entry.attachment,
                    "public_key": entry.public_key,
                    "registration_id": entry.registration_id,
                    "runtime_id": entry.runtime_id,
                    "state": entry.state,
                    "surface": entry.surface,
                }
                for entry in entries
            ],
            "graph_id": runtime.graph_id,
            "mount_generation": runtime.generation,
            "schema_version": 1,
        }
    )
    return RegistrationInventorySnapshot(
        schema_version=1,
        graph_id=runtime.graph_id,
        runtime_id=runtime.runtime_id,
        mount_generation=runtime.generation,
        revision=revision,
        entries=entries,
    )


def _publish_registration_inventory(runtime: RuntimeCapabilityGraphRuntime) -> None:
    runtime._registration_inventory = _registration_inventory(runtime)


async def _cleanup_nodes_once(
    nodes: tuple[_MountedCapability, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    for mounted in nodes:
        report = await mounted.registration_scope.dispose()
        if report.has_failures:
            codes.append("registration_retirement_failed")
        if not mounted.provider_released:
            try:
                await mounted.provider_binding.release(mounted.value)
            except asyncio.CancelledError:
                codes.append("provider_retirement_cancelled")
            except Exception:
                codes.append("provider_retirement_failed")
            else:
                mounted.provider_released = True
    return tuple(sorted(set(codes)))


async def _cleanup_candidate_once(
    scopes: tuple[RegistrationScope, ...],
    nodes: tuple[_MountedCapability, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            set(
                (
                    *await _cleanup_scopes_once(scopes),
                    *await _cleanup_nodes_once(nodes),
                )
            )
        )
    )


async def _cleanup_scopes_once(
    scopes: tuple[RegistrationScope, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    for scope in scopes:
        report = await scope.dispose()
        if report.has_failures:
            codes.append("registration_rollback_failed")
    return tuple(sorted(set(codes)))


async def _cleanup_candidate_and_retain(
    runtime: RuntimeCapabilityGraphRuntime,
    scopes: tuple[RegistrationScope, ...],
    nodes: tuple[_MountedCapability, ...],
) -> tuple[tuple[str, ...], asyncio.CancelledError | None]:
    cleanup_task = asyncio.create_task(
        _cleanup_candidate_once(
            tuple(reversed(scopes)),
            tuple(reversed(nodes)),
        )
    )
    cancellation: asyncio.CancelledError | None = None
    try:
        codes = await _await_cancellation_atomic(cleanup_task)
    except asyncio.CancelledError as exc:
        cancellation = exc
        codes = cleanup_task.result()
    _record_incomplete_candidate(runtime, scopes, nodes)
    _publish_registration_inventory(runtime)
    return codes, cancellation


def _node_cleanup_complete(mounted: _MountedCapability) -> bool:
    return mounted.registration_scope.state == "disposed" and mounted.provider_released


def _scope_cleanup_complete(scope: RegistrationScope) -> bool:
    return scope.state == "disposed"


def _record_incomplete_retirements(
    runtime: RuntimeCapabilityGraphRuntime,
    nodes: tuple[_MountedCapability, ...],
) -> None:
    existing = {id(mounted) for mounted in runtime._retired_nodes}
    runtime._retired_nodes.extend(
        mounted
        for mounted in nodes
        if id(mounted) not in existing and not _node_cleanup_complete(mounted)
    )


def _record_incomplete_scopes(
    runtime: RuntimeCapabilityGraphRuntime,
    scopes: tuple[RegistrationScope, ...],
) -> None:
    existing = {id(scope) for scope in runtime._retired_scopes}
    runtime._retired_scopes.extend(
        scope
        for scope in scopes
        if id(scope) not in existing and not _scope_cleanup_complete(scope)
    )


def _record_incomplete_candidate(
    runtime: RuntimeCapabilityGraphRuntime,
    scopes: tuple[RegistrationScope, ...],
    nodes: tuple[_MountedCapability, ...],
) -> None:
    _record_incomplete_scopes(runtime, scopes)
    _record_incomplete_retirements(runtime, nodes)


def _prune_completed_cleanup(runtime: RuntimeCapabilityGraphRuntime) -> None:
    runtime._retired_scopes = [
        scope
        for scope in runtime._retired_scopes
        if not _scope_cleanup_complete(scope)
    ]
    runtime._retired_nodes = [
        mounted
        for mounted in runtime._retired_nodes
        if not _node_cleanup_complete(mounted)
    ]


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "CapabilityGraphBindResult",
    "CapabilityGraphBindingError",
    "RuntimeCapabilityGraphBinder",
]
