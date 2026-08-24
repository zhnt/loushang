"""Product selection of exact owner-admitted Capability components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Never, Protocol, TypeVar

from loushang.harness.capabilities.component_admission import (
    CapabilityComponentAdmission,
    CapabilityComponentOwnerSnapshot,
)
from loushang.harness.capabilities.component_contracts import (
    CapabilityComponentDefinition,
    _digest_document,
    _require_exact_version,
    _require_nonempty,
    _require_nonnegative_integer,
    _require_sha256,
)

CAPABILITY_COMPONENT_SELECTION_PLAN_VERSION = 1
RESOLVED_CAPABILITY_COMPONENT_VERSION = 1
RESOLVED_CAPABILITY_COMPONENT_SET_VERSION = 1


class CapabilityComponentSelectionError(RuntimeError):
    """Stable fail-closed Product component selection diagnostic."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CapabilityComponentSelectionChoice:
    component_kind: str
    admission_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonempty(self.component_kind, name="selected component kind")
        fingerprints = tuple(self.admission_fingerprints)
        for fingerprint in fingerprints:
            _require_sha256(fingerprint, name="component admission fingerprint")
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("Component selection must not repeat an admission")
        object.__setattr__(self, "admission_fingerprints", fingerprints)

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionFingerprints": list(self.admission_fingerprints),
            "componentKind": self.component_kind,
        }


@dataclass(frozen=True, slots=True)
class CapabilityComponentSelectionPlan:
    product_id: str
    scope_id: str
    capability_id: str
    owner_id: str
    product_policy_revision: str
    choices: tuple[CapabilityComponentSelectionChoice, ...]
    plan_version: int = CAPABILITY_COMPONENT_SELECTION_PLAN_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("Capability id", self.capability_id),
            ("Capability owner id", self.owner_id),
            ("Product policy revision", self.product_policy_revision),
        ):
            _require_nonempty(value, name=name)
        choices = tuple(self.choices)
        if any(not isinstance(item, CapabilityComponentSelectionChoice) for item in choices):
            raise TypeError("Component selection plan requires typed choices")
        kinds = tuple(item.component_kind for item in choices)
        if len(set(kinds)) != len(kinds):
            raise ValueError("Component selection plan must not repeat a component kind")
        if choices != tuple(sorted(choices, key=lambda item: item.component_kind)):
            raise ValueError("Component selection choices must be sorted by kind")
        _require_exact_version(
            self.plan_version,
            supported=CAPABILITY_COMPONENT_SELECTION_PLAN_VERSION,
            name="Capability Component selection plan",
        )
        object.__setattr__(self, "choices", choices)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-component-selection-plan/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "choices": [choice.to_dict() for choice in self.choices],
            "ownerId": self.owner_id,
            "planVersion": self.plan_version,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "scopeId": self.scope_id,
        }


@dataclass(frozen=True, slots=True, init=False)
class ResolvedCapabilityComponent:
    definition: CapabilityComponentDefinition
    admission: CapabilityComponentAdmission = field(repr=False)
    owner_snapshot_fingerprint: str
    selection_plan_fingerprint: str
    selection_ordinal: int
    resolved_version: int

    def __init__(self) -> None:
        raise TypeError("Resolved Capability Component is resolver-constructed")

    def __post_init__(self) -> None:
        if not isinstance(self.definition, CapabilityComponentDefinition):
            raise TypeError("Resolved component requires a Definition")
        if not isinstance(self.admission, CapabilityComponentAdmission):
            raise TypeError("Resolved component requires an admission")
        for name, value in (
            ("component owner snapshot fingerprint", self.owner_snapshot_fingerprint),
            ("component selection plan fingerprint", self.selection_plan_fingerprint),
        ):
            _require_sha256(value, name=name)
        _require_nonnegative_integer(
            self.selection_ordinal,
            name="component selection ordinal",
        )
        _require_exact_version(
            self.resolved_version,
            supported=RESOLVED_CAPABILITY_COMPONENT_VERSION,
            name="Resolved Capability Component",
        )

    @property
    def component_id(self) -> str:
        return self.admission.candidate.component_id

    @property
    def admission_fingerprint(self) -> str:
        return self.admission.fingerprint

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.resolved-capability-component/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionFingerprint": self.admission.fingerprint,
            "componentId": self.component_id,
            "definitionFingerprint": self.definition.fingerprint,
            "ownerSnapshotFingerprint": self.owner_snapshot_fingerprint,
            "resolvedVersion": self.resolved_version,
            "selectionOrdinal": self.selection_ordinal,
            "selectionPlanFingerprint": self.selection_plan_fingerprint,
        }


@dataclass(frozen=True, slots=True, init=False)
class ResolvedCapabilityComponentSet:
    product_id: str
    scope_id: str
    capability_id: str
    owner_id: str
    product_policy_revision: str
    selection_plan_fingerprint: str
    components: tuple[ResolvedCapabilityComponent, ...]
    resolved_set_version: int

    def __init__(self) -> None:
        raise TypeError("Resolved Capability Component set is resolver-constructed")

    def __post_init__(self) -> None:
        for name, value in (
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("Capability id", self.capability_id),
            ("Capability owner id", self.owner_id),
            ("Product policy revision", self.product_policy_revision),
        ):
            _require_nonempty(value, name=name)
        _require_sha256(
            self.selection_plan_fingerprint,
            name="component selection plan fingerprint",
        )
        components = tuple(self.components)
        if any(not isinstance(item, ResolvedCapabilityComponent) for item in components):
            raise TypeError("Resolved component set requires typed components")
        expected_ordinals = tuple(range(len(components)))
        if tuple(item.selection_ordinal for item in components) != expected_ordinals:
            raise ValueError("Resolved component ordinals must be contiguous")
        fingerprints = tuple(item.admission_fingerprint for item in components)
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("Resolved component set must not repeat an admission")
        _require_exact_version(
            self.resolved_set_version,
            supported=RESOLVED_CAPABILITY_COMPONENT_SET_VERSION,
            name="Resolved Capability Component set",
        )
        object.__setattr__(self, "components", components)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.resolved-capability-component-set/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "components": [component.to_dict() for component in self.components],
            "ownerId": self.owner_id,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "resolvedSetVersion": self.resolved_set_version,
            "scopeId": self.scope_id,
            "selectionPlanFingerprint": self.selection_plan_fingerprint,
        }


class ProductCapabilityComponentResolver:
    """Resolve one complete Product plan against current owner snapshots."""

    def resolve(
        self,
        plan: CapabilityComponentSelectionPlan,
        *,
        definitions: tuple[CapabilityComponentDefinition, ...],
        admissions: tuple[CapabilityComponentAdmission, ...],
        owner_snapshots: tuple[CapabilityComponentOwnerSnapshot, ...],
        now: int,
    ) -> ResolvedCapabilityComponentSet:
        if not isinstance(plan, CapabilityComponentSelectionPlan):
            raise TypeError("Component resolver requires a selection plan")
        _require_nonnegative_integer(now, name="component resolution time")
        definition_by_kind = _index_definitions(definitions)
        snapshot_by_kind = _index_snapshots(owner_snapshots)
        admission_by_fingerprint = _index_admissions(admissions)
        if set(definition_by_kind) != {choice.component_kind for choice in plan.choices}:
            _raise_selection(
                "component_selection_incomplete",
                "Component selection must name every owner Definition exactly once.",
            )
        resolved: list[ResolvedCapabilityComponent] = []
        for choice in plan.choices:
            definition = definition_by_kind[choice.component_kind]
            snapshot = snapshot_by_kind.get(choice.component_kind)
            if snapshot is None:
                _raise_selection(
                    "component_owner_snapshot_missing",
                    "Current component owner snapshot is missing.",
                )
            self._validate_plan_owner(plan, definition)
            self._validate_snapshot(snapshot, definition)
            count = len(choice.admission_fingerprints)
            if count < definition.minimum_count or (
                definition.maximum_count is not None
                and count > definition.maximum_count
            ):
                _raise_selection(
                    "component_selection_cardinality",
                    "Selected component count violates its Definition.",
                )
            for fingerprint in choice.admission_fingerprints:
                admission = admission_by_fingerprint.get(fingerprint)
                if admission is None:
                    _raise_selection(
                        "component_admission_missing",
                        "Selected component admission does not exist.",
                    )
                self._validate_admission(
                    plan,
                    definition,
                    snapshot,
                    admission,
                    now=now,
                )
                resolved.append(
                    _resolver_construct(
                        ResolvedCapabilityComponent,
                        definition=definition,
                        admission=admission,
                        owner_snapshot_fingerprint=snapshot.fingerprint,
                        selection_plan_fingerprint=plan.fingerprint,
                        selection_ordinal=len(resolved),
                        resolved_version=RESOLVED_CAPABILITY_COMPONENT_VERSION,
                    )
                )
        return _resolver_construct(
            ResolvedCapabilityComponentSet,
            product_id=plan.product_id,
            scope_id=plan.scope_id,
            capability_id=plan.capability_id,
            owner_id=plan.owner_id,
            product_policy_revision=plan.product_policy_revision,
            selection_plan_fingerprint=plan.fingerprint,
            components=tuple(resolved),
            resolved_set_version=RESOLVED_CAPABILITY_COMPONENT_SET_VERSION,
        )

    @staticmethod
    def _validate_plan_owner(
        plan: CapabilityComponentSelectionPlan,
        definition: CapabilityComponentDefinition,
    ) -> None:
        if (
            definition.capability_id != plan.capability_id
            or definition.owner_id != plan.owner_id
        ):
            _raise_selection(
                "component_selection_owner_mismatch",
                "Component selection crosses a Capability owner boundary.",
            )

    @staticmethod
    def _validate_snapshot(
        snapshot: CapabilityComponentOwnerSnapshot,
        definition: CapabilityComponentDefinition,
    ) -> None:
        if (
            snapshot.capability_id != definition.capability_id
            or snapshot.owner_id != definition.owner_id
            or snapshot.component_kind != definition.component_kind
            or snapshot.definition_fingerprint != definition.fingerprint
        ):
            _raise_selection(
                "component_owner_snapshot_stale",
                "Component owner snapshot does not match its Definition.",
            )

    @staticmethod
    def _validate_admission(
        plan: CapabilityComponentSelectionPlan,
        definition: CapabilityComponentDefinition,
        snapshot: CapabilityComponentOwnerSnapshot,
        admission: CapabilityComponentAdmission,
        *,
        now: int,
    ) -> None:
        candidate = admission.candidate
        if (
            candidate.definition != definition
            or candidate.product_id != plan.product_id
            or candidate.scope_id != plan.scope_id
            or candidate.product_policy_revision != plan.product_policy_revision
        ):
            _raise_selection(
                "component_admission_scope_mismatch",
                "Component admission does not match the Product selection scope.",
            )
        if (
            admission.owner_snapshot_fingerprint != snapshot.fingerprint
            or admission.owner_policy_revision != snapshot.policy_revision
            or admission.revocation_epoch != snapshot.revocation_epoch
        ):
            _raise_selection(
                "component_admission_owner_stale",
                "Component admission does not match current owner authority.",
            )
        if now < admission.issued_at or now >= admission.expires_at:
            _raise_selection(
                "component_admission_not_current",
                "Component admission is not current.",
            )


def _index_definitions(
    values: tuple[CapabilityComponentDefinition, ...],
) -> dict[str, CapabilityComponentDefinition]:
    indexed: dict[str, CapabilityComponentDefinition] = {}
    for value in values:
        if not isinstance(value, CapabilityComponentDefinition):
            raise TypeError("Component definitions must be typed records")
        if value.component_kind in indexed:
            raise ValueError("Component definitions must not repeat a kind")
        indexed[value.component_kind] = value
    return indexed


def _index_snapshots(
    values: tuple[CapabilityComponentOwnerSnapshot, ...],
) -> dict[str, CapabilityComponentOwnerSnapshot]:
    indexed: dict[str, CapabilityComponentOwnerSnapshot] = {}
    for value in values:
        if not isinstance(value, CapabilityComponentOwnerSnapshot):
            raise TypeError("Component owner snapshots must be typed records")
        if value.component_kind in indexed:
            raise ValueError("Component owner snapshots must not repeat a kind")
        indexed[value.component_kind] = value
    return indexed


def _index_admissions(
    values: tuple[CapabilityComponentAdmission, ...],
) -> dict[str, CapabilityComponentAdmission]:
    indexed: dict[str, CapabilityComponentAdmission] = {}
    for value in values:
        if not isinstance(value, CapabilityComponentAdmission):
            raise TypeError("Component admissions must be typed records")
        fingerprint = value.fingerprint
        if fingerprint in indexed:
            raise ValueError("Component admissions must not repeat")
        indexed[fingerprint] = value
    return indexed


class _PostInitValue(Protocol):
    def __post_init__(self) -> None: ...


_T = TypeVar("_T", bound=_PostInitValue)


def _resolver_construct(record_type: type[_T], **values: object) -> _T:
    value = object.__new__(record_type)
    for name, item in values.items():
        object.__setattr__(value, name, item)
    value.__post_init__()
    return value


def _raise_selection(code: str, message: str) -> Never:
    raise CapabilityComponentSelectionError(message, code=code)


__all__ = [
    "CapabilityComponentSelectionChoice",
    "CapabilityComponentSelectionError",
    "CapabilityComponentSelectionPlan",
    "ProductCapabilityComponentResolver",
    "ResolvedCapabilityComponent",
    "ResolvedCapabilityComponentSet",
]
