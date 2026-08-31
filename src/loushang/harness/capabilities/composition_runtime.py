"""Standard runtime binding for Product capability composition.

This module binds the Product-selected mechanisms for resource activation,
prompt sections, skill activation, and capability packs.  Product plans own
which mechanisms they select and the values they pass to them; this module
owns only the neutral factories and their configuration contracts.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from pathlib import PurePath
from threading import Lock
from typing import Any, Literal, Protocol, TypeVar, cast

from loushang.harness._owner_generation_authority import (
    _OWNER_CANDIDATE_FACTORIES,
    _OWNER_GENERATION_ATTACHMENTS,
    _is_owner_candidate_factory_recorded,
    _is_owner_generation_factory_recorded,
    _OwnerCandidateFactoryIdentity,
    _OwnerCandidateFactoryRecord,
    _OwnerGenerationAttachmentReceipt,
    _OwnerGenerationAttachmentRecord,
    _rollback_owner_generation_attachment,
)
from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposer,
    CapabilityPackComposition,
)
from loushang.harness.capabilities.prompt import PromptSectionComposer
from loushang.harness.resources.activation import (
    ResourceActivation,
    ResourceActivationRuntime,
    SkillActivationRuntime,
)
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import (
    COMMAND_PACKS_SLOT,
    PROMPT_SECTIONS_SLOT,
    RESOURCE_RUNTIME_SLOT,
    SIDE_QUESTION_PROVIDER_SLOT,
    SKILL_ACTIVATION_SLOT,
    TOOL_PACKS_SLOT,
    OwnerGenerationRetirementReceipt,
    ProductRuntimePlan,
    ResolvedRuntimeProfile,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeCapabilitySelection,
    RuntimeProfileBinder,
    RuntimeProfileBinding,
    RuntimeProfileSource,
    SessionSideQuestionProviderFactory,
    SideQuestionProviderFactory,
    standard_capability_composition_slots,
)

RESOURCE_ACTIVATION_IMPLEMENTATION = "harness.resource_activation"
PROMPT_SECTIONS_IMPLEMENTATION = "harness.prompt_sections"
DISABLED_SKILL_ACTIVATION_IMPLEMENTATION = "harness.disabled_skill_activation"
ORDERED_CAPABILITY_PACKS_IMPLEMENTATION = "harness.ordered_capability_packs"
AGENT_SIDE_QUESTION_IMPLEMENTATION = "harness.agent_side_question"
CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION = 1
RESOURCE_CAPABILITY_SLOT_KEYS = frozenset(
    {
        RESOURCE_RUNTIME_SLOT.key,
        PROMPT_SECTIONS_SLOT.key,
        SKILL_ACTIVATION_SLOT.key,
        TOOL_PACKS_SLOT.key,
        COMMAND_PACKS_SLOT.key,
    }
)

T = TypeVar("T")
TValue = TypeVar("TValue")


class _PreparedResourceOwnerGeneration(Protocol):
    """Typing-only lifecycle seam for the candidate-owned Catalog generation.

    The concrete implementation lives below ``resource_catalog``.  Keeping
    the interface here prevents the Capability layer from importing Resource
    source implementations. Runtime authority comes from the external exact
    factory-identity registry, never from this structural interface.
    """

    provider_binding_fingerprint: str

    @property
    def ownership_state(self) -> str: ...

    @property
    def catalog_snapshot(self) -> object: ...

    @property
    def catalog_projection(self) -> object: ...

    @property
    def _skill_status_projection(self) -> object: ...

    def load_handle(self, identity: Any) -> Any: ...

    async def load(self, handle: Any) -> Any: ...

    def _construct_skill_catalog_consumer(
        self,
        *,
        include_status: bool,
    ) -> object: ...

    def _borrows_extension_source_lease(self, source: object) -> bool: ...

    def _begin_graph_construction(self) -> None: ...

    def _commit_graph_ownership(self) -> None: ...

    def _restore_root_ownership(self) -> None: ...

    async def dispose_root_owned(self) -> None: ...

    async def _dispose_graph_owned(self) -> None: ...

    def retirement_receipt(
        self,
        *,
        contribution_ids: tuple[str, ...],
    ) -> OwnerGenerationRetirementReceipt: ...


@dataclass(frozen=True, slots=True)
class ResourceCatalogGenerationCapture:
    """Exact Resource owner-generation view minted by its mounted Capability."""

    _generation: _PreparedResourceOwnerGeneration

    @property
    def snapshot(self) -> object:
        return self._generation.catalog_snapshot

    @property
    def projection(self) -> object:
        return self._generation.catalog_projection

    @property
    def skill_status_projection(self) -> object:
        return self._generation._skill_status_projection

    def load_handle(self, identity: object) -> object:
        return self._generation.load_handle(identity)

    async def load(self, handle: object) -> object:
        return await self._generation.load(handle)

    def _construct_skill_catalog_consumer(self, *, include_status: bool) -> object:
        """Delegate atomic consumer construction to the exact Resource owner."""

        return self._generation._construct_skill_catalog_consumer(
            include_status=include_status,
        )


class ResourceOwnerGenerationRetirementError(RuntimeError):
    """Retryable cleanup debt for replaced Resource owner generations."""

    def __init__(self, diagnostic_codes: tuple[str, ...]) -> None:
        self.diagnostic_codes = tuple(sorted(set(diagnostic_codes)))
        super().__init__(
            "Resource owner generation retirement remains pending: "
            + ", ".join(self.diagnostic_codes)
        )


def standard_capability_composition_plan(
    *,
    product_id: str,
    allowed_sources: frozenset[RuntimeProfileSource] = frozenset({"product"}),
    slot_allowed_sources: Mapping[str, frozenset[RuntimeProfileSource]] | None = None,
    prompt_separator: str = "\n\n",
    strip_prompt_sections: bool = True,
) -> ProductRuntimePlan:
    """Declare the standard composition mechanisms for one Product."""

    source_overrides = dict(slot_allowed_sources or {})
    unknown_overrides = source_overrides.keys() - {
        slot.key for slot in standard_capability_composition_slots()
    }
    if unknown_overrides:
        raise ValueError(
            "unknown capability-composition source override: "
            + ", ".join(sorted(unknown_overrides))
        )
    slots = tuple(
        replace(
            slot,
            allowed_sources=source_overrides.get(slot.key, allowed_sources),
        )
        for slot in standard_capability_composition_slots()
    )
    return ProductRuntimePlan(
        product_id=product_id,
        slots=slots,
        defaults=(
            RuntimeCapabilitySelection(
                slot=RESOURCE_RUNTIME_SLOT.key,
                implementation=RESOURCE_ACTIVATION_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=PROMPT_SECTIONS_SLOT.key,
                implementation=PROMPT_SECTIONS_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
                config={
                    "separator": prompt_separator,
                    "stripSections": strip_prompt_sections,
                },
            ),
            RuntimeCapabilitySelection(
                slot=SKILL_ACTIVATION_SLOT.key,
                implementation=DISABLED_SKILL_ACTIVATION_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=TOOL_PACKS_SLOT.key,
                implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=COMMAND_PACKS_SLOT.key,
                implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=SIDE_QUESTION_PROVIDER_SLOT.key,
                implementation=AGENT_SIDE_QUESTION_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
        ),
    )


@dataclass
class _CapabilityCompositionCandidate:
    binding: RuntimeProfileBinding
    binder: RuntimeProfileBinder
    profile: ResolvedRuntimeProfile
    ownership: Literal[
        "root_owned",
        "graph_constructing",
        "graph_owned",
        "retiring",
        "disposed",
    ] = "root_owned"
    owner_generation: _PreparedResourceOwnerGeneration | None = None
    retired_owner_generations: list[_PreparedResourceOwnerGeneration] = field(
        default_factory=list
    )
    retirement_owner: Literal["root", "graph"] | None = None


@dataclass(frozen=True, slots=True)
class _StagedResourceCandidateFactoryRecord:
    """Resource-specific facts pinned outside caller-reachable candidates."""

    candidate_ref: Callable[[], object | None]
    identity: _OwnerCandidateFactoryIdentity
    candidate_state: _CapabilityCompositionCandidate
    binding: RuntimeProfileBinding
    binder: RuntimeProfileBinder
    binder_registry: RuntimeCapabilityRegistry
    binder_implementations: object
    binder_implementation_items: tuple[tuple[object, object], ...]
    binder_implementation_facts: tuple[tuple[object, ...], ...]
    binder_bind_sync: object
    binder_instance_keys: tuple[str, ...]
    profile: ResolvedRuntimeProfile
    binding_context: object | None
    binding_context_fact: object
    binding_profile: ResolvedRuntimeProfile
    binding_state: Any
    binding_runtime_bindings: object
    binding_state_fact: tuple[object, ...]
    binding_bound: Any
    binding_bound_fact: object
    resource_profile_json: object
    binding_profile_json: object
    custody: _StagedResourceCandidateCustody


@dataclass(slots=True)
class _StagedResourceCandidateCustody:
    """Caller-inaccessible owner custody retained across facade drift."""

    current: _PreparedResourceOwnerGeneration | None
    retired: list[_PreparedResourceOwnerGeneration]
    ownership: Literal[
        "root_owned",
        "graph_constructing",
        "graph_owned",
        "retiring",
        "disposed",
    ]
    retirement_owner: Literal["root", "graph"] | None
    binding_cleanup_started: bool


_STAGED_RESOURCE_CANDIDATE_FACTORIES: dict[
    int, _StagedResourceCandidateFactoryRecord
] = {}
_STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES: dict[int, int] = {}


def _runtime_implementation_facts(
    items: tuple[tuple[object, object], ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            key,
            implementation,
            getattr(implementation, "slot", None),
            getattr(implementation, "implementation", None),
            getattr(implementation, "implementation_version", None),
            getattr(implementation, "create", None),
            getattr(implementation, "dispose", None),
        )
        for key, implementation in items
    )


def _binding_bound_fact(bound: object) -> object:
    if not isinstance(bound, Mapping):
        raise TypeError("Resource candidate binding map is invalid")
    return tuple(
        sorted(
            (
                key,
                tuple(
                    (
                        entry,
                        _freeze_candidate_factory_fact(
                            getattr(entry, "resolved", None)
                        ),
                        _runtime_implementation_facts(
                            ((key, getattr(entry, "implementation", None)),)
                        )[0],
                        id(getattr(entry, "value", None)),
                    )
                    for entry in entries
                ),
            )
            for key, entries in bound.items()
        )
    )


def _binding_state_fact(state: object) -> tuple[object, ...]:
    bindings = getattr(state, "bindings", None)
    values = getattr(bindings, "values", None)
    if not isinstance(values, Mapping):
        raise TypeError("Resource candidate live binding state is invalid")
    return (
        getattr(state, "generation", None),
        bindings,
        getattr(bindings, "profile", None),
        tuple(
            sorted(
                (
                    key,
                    (
                        tuple(id(item) for item in value)
                        if isinstance(value, tuple)
                        else id(value)
                    ),
                )
                for key, value in values.items()
            )
        ),
    )


def _freeze_candidate_factory_fact(value: object) -> object:
    return _freeze_candidate_factory_value(value, active=set())


def _freeze_candidate_factory_value(value: object, *, active: set[int]) -> object:
    if value is None or type(value) in {bool, int, float, str, bytes}:
        return value
    if isinstance(value, PurePath):
        return ("path", type(value), str(value))
    if isinstance(value, Enum):
        return ("enum", type(value), value.value)
    identity = id(value)
    if identity in active:
        raise ValueError("Resource candidate facts contain a cycle")
    if isinstance(value, Mapping):
        active.add(identity)
        try:
            return (
                "mapping",
                tuple(
                    sorted(
                        (
                            _freeze_candidate_factory_value(key, active=active),
                            _freeze_candidate_factory_value(item, active=active),
                        )
                        for key, item in value.items()
                    )
                ),
            )
        finally:
            active.remove(identity)
    if isinstance(value, (tuple, list)):
        active.add(identity)
        try:
            return (
                type(value).__name__,
                tuple(
                    _freeze_candidate_factory_value(item, active=active)
                    for item in value
                ),
            )
        finally:
            active.remove(identity)
    if isinstance(value, (set, frozenset)):
        active.add(identity)
        try:
            return (
                type(value).__name__,
                tuple(
                    sorted(
                        (
                            _freeze_candidate_factory_value(item, active=active)
                            for item in value
                        ),
                        key=repr,
                    )
                ),
            )
        finally:
            active.remove(identity)
    if is_dataclass(value) and not isinstance(value, type):
        active.add(identity)
        try:
            return (
                "dataclass",
                type(value),
                tuple(
                    (
                        item.name,
                        _freeze_candidate_factory_value(
                            getattr(value, item.name), active=active
                        ),
                    )
                    for item in fields(value)
                ),
            )
        finally:
            active.remove(identity)
    try:
        attributes = vars(value)
    except TypeError:
        return ("identity", type(value), identity)
    active.add(identity)
    try:
        return (
            "object",
            type(value),
            _freeze_candidate_factory_value(attributes, active=active),
        )
    finally:
        active.remove(identity)


def _is_staged_resource_candidate_factory_recorded(candidate: object) -> bool:
    if not _is_owner_candidate_factory_recorded(candidate):
        return False
    identity = getattr(candidate, "_owner_candidate_factory_identity", None)
    record = (
        _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(id(identity))
        if type(identity) is _OwnerCandidateFactoryIdentity
        else None
    )
    state = getattr(
        candidate,
        "_StagedResourceCompositionCandidate__candidate",
        None,
    )
    registry = getattr(getattr(state, "binder", None), "_registry", None)
    implementations = getattr(registry, "_implementations", None)
    implementation_items = (
        tuple(sorted(implementations.items(), key=lambda item: repr(item[0])))
        if isinstance(implementations, Mapping)
        else ()
    )
    binding = getattr(state, "binding", None)
    if (
        record is None
        or record.identity is not identity
        or record.candidate_ref() is not candidate
        or state is not record.candidate_state
        or not isinstance(state, _CapabilityCompositionCandidate)
        or state.binding is not record.binding
        or state.binder is not record.binder
        or registry is not record.binder_registry
        or implementations is not record.binder_implementations
        or not isinstance(implementations, Mapping)
        or len(implementations) != len(record.binder_implementation_items)
        or any(
            implementations.get(key) is not implementation
            for key, implementation in record.binder_implementation_items
        )
        or _runtime_implementation_facts(implementation_items)
        != record.binder_implementation_facts
        or getattr(type(state.binder), "bind_sync", None)
        is not record.binder_bind_sync
        or tuple(sorted(vars(state.binder))) != record.binder_instance_keys
        or state.profile is not record.profile
        or getattr(state.binding, "_context", object())
        is not record.binding_context
        or getattr(state.binding, "_state", None) is not record.binding_state
        or getattr(state.binding._state, "bindings", None)
        is not record.binding_runtime_bindings
        or getattr(state.binding, "_bound", None) is not record.binding_bound
        or getattr(state.binding, "_closed", None) is not False
        or state.owner_generation is not record.custody.current
        or state.ownership != record.custody.ownership
        or state.retirement_owner != record.custody.retirement_owner
        or len(state.retired_owner_generations) != len(record.custody.retired)
        or any(
            current is not expected
            for current, expected in zip(
                state.retired_owner_generations,
                record.custody.retired,
                strict=True,
            )
        )
    ):
        return False
    try:
        binding_context_fact = _freeze_candidate_factory_fact(
            state.binding._context
        )
        binding_bound_fact = _binding_bound_fact(state.binding._bound)
        binding_state_fact = _binding_state_fact(state.binding._state)
        resource_profile_json = resource_capability_profile(
            state.profile
        ).snapshot().to_json()
        binding_profile_json = state.binding.profile.snapshot().to_json()
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False
    return bool(
        binding is record.binding
        and binding_context_fact == record.binding_context_fact
        and binding_bound_fact == record.binding_bound_fact
        and binding_state_fact == record.binding_state_fact
        and resource_profile_json == record.resource_profile_json
        and binding_profile_json == record.binding_profile_json
    )


def _recorded_staged_resource_candidate_cleanup_state(
    candidate: object,
) -> _CapabilityCompositionCandidate | None:
    """Repair and return the original state solely for retryable cleanup."""

    identity_id = _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(id(candidate))
    record = (
        _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(identity_id)
        if identity_id is not None
        else None
    )
    if record is None or record.candidate_ref() is not candidate:
        return None
    with _RESOURCE_OWNER_GENERATION_REPLACEMENT_LOCK:
        replacement = _RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER.get(
            id(candidate)
        )
        if replacement is not None and replacement.owner is candidate:
            if (
                record.custody.current is replacement.current
                and all(
                    item is not replacement.previous
                    for item in record.custody.retired
                )
            ):
                record.custody.retired.append(replacement.previous)
            _RESOURCE_OWNER_GENERATION_REPLACEMENTS.pop(
                id(replacement.token), None
            )
            _RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER.pop(
                id(candidate), None
            )
    state = record.candidate_state
    state.binding = record.binding
    state.binder = record.binder
    state.profile = record.profile
    state.owner_generation = record.custody.current
    state.retired_owner_generations = list(record.custody.retired)
    state.ownership = record.custody.ownership
    state.retirement_owner = record.custody.retirement_owner
    vars(record.binder).clear()
    record.binder._registry = record.binder_registry
    setattr(record.binder_registry, "_implementations", record.binder_implementations)
    for fact in record.binder_implementation_facts:
        _, implementation, slot, key, version, create, dispose = fact
        object.__setattr__(implementation, "slot", slot)
        object.__setattr__(implementation, "implementation", key)
        object.__setattr__(implementation, "implementation_version", version)
        object.__setattr__(implementation, "create", create)
        object.__setattr__(implementation, "dispose", dispose)
    record.binding._profile = record.binding_profile
    record.binding._context = record.binding_context
    record.binding._state = record.binding_state
    record.binding._bound = record.binding_bound
    if (
        record.custody.ownership not in {"retiring", "disposed"}
        and not record.custody.binding_cleanup_started
    ):
        record.binding_state._bindings = record.binding_runtime_bindings
        record.binding_state._generation = record.binding_state_fact[0]
        record.binding._closed = False
        record.binding._dispose_task = None
        record.binding._async_disposal_pending = None
        record.binding._sync_disposal_pending = None
    setattr(candidate, "_StagedResourceCompositionCandidate__candidate", state)
    return state


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class _ResourceOwnerGenerationReplacementToken:
    """Opaque external-ledger identity for one replacement transaction."""

    def __init__(self) -> None:
        raise TypeError("Resource owner replacements are candidate-minted")


@dataclass(slots=True)
class _ResourceOwnerGenerationReplacementRecord:
    token: _ResourceOwnerGenerationReplacementToken
    owner: StagedResourceCompositionCandidate
    previous: _PreparedResourceOwnerGeneration
    current: _PreparedResourceOwnerGeneration


_RESOURCE_OWNER_GENERATION_REPLACEMENTS: dict[
    int, _ResourceOwnerGenerationReplacementRecord
] = {}
_RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER: dict[
    int, _ResourceOwnerGenerationReplacementRecord
] = {}
_RESOURCE_OWNER_GENERATION_REPLACEMENT_LOCK = Lock()


@dataclass(frozen=True, slots=True, init=False)
class ResourceOwnerGenerationReplacement:
    """Open no-await replacement transaction for one mounted Resource owner."""

    _token: _ResourceOwnerGenerationReplacementToken

    def __init__(self) -> None:
        raise TypeError("Resource owner replacements are candidate-minted")

    def commit(self) -> None:
        _resolve_resource_owner_generation_replacement(self._token, commit=True)

    def rollback(self) -> None:
        _resolve_resource_owner_generation_replacement(self._token, commit=False)


def _reserve_resource_owner_generation_replacement(
    *,
    owner: StagedResourceCompositionCandidate,
    previous: _PreparedResourceOwnerGeneration,
    current: _PreparedResourceOwnerGeneration,
) -> ResourceOwnerGenerationReplacement:
    token = object.__new__(_ResourceOwnerGenerationReplacementToken)
    token_id = id(token)
    record = _ResourceOwnerGenerationReplacementRecord(
        token=token,
        owner=owner,
        previous=previous,
        current=current,
    )
    with _RESOURCE_OWNER_GENERATION_REPLACEMENT_LOCK:
        identity_id = _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(id(owner))
        factory = (
            _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(identity_id)
            if identity_id is not None
            else None
        )
        if (
            factory is None
            or factory.candidate_ref() is not owner
            or factory.candidate_state.owner_generation is not previous
            or factory.candidate_state.ownership != "graph_owned"
            or factory.custody.current is not previous
            or factory.custody.ownership != "graph_owned"
        ):
            raise RuntimeError(
                "Resource owner generation changed before replacement reservation"
            )
        existing = _RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER.get(id(owner))
        if existing is not None and existing.owner is owner:
            raise RuntimeError("Resource generation replacement is already open")
        _RESOURCE_OWNER_GENERATION_REPLACEMENTS[token_id] = record
        _RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER[id(owner)] = record
    replacement = object.__new__(ResourceOwnerGenerationReplacement)
    object.__setattr__(replacement, "_token", token)
    return replacement


def _resolve_resource_owner_generation_replacement(
    token: _ResourceOwnerGenerationReplacementToken,
    *,
    commit: bool,
) -> None:
    with _RESOURCE_OWNER_GENERATION_REPLACEMENT_LOCK:
        record = (
            _RESOURCE_OWNER_GENERATION_REPLACEMENTS.get(id(token))
            if type(token) is _ResourceOwnerGenerationReplacementToken
            else None
        )
        if record is None or record.token is not token:
            raise RuntimeError("Resource generation replacement is already resolved")
        if not _is_staged_resource_candidate_factory_recorded(record.owner):
            raise TypeError("Resource generation replacement lost owner authority")
        if commit:
            record.owner._commit_owner_generation_replacement(
                previous=record.previous,
                current=record.current,
            )
        else:
            record.owner._rollback_owner_generation_replacement(
                previous=record.previous,
                current=record.current,
            )
        _RESOURCE_OWNER_GENERATION_REPLACEMENTS.pop(id(token), None)
        if _RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER.get(id(record.owner)) is record:
            _RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER.pop(id(record.owner), None)


@dataclass(frozen=True)
class _RootOwnedResourceCapabilityHandles:
    """Private bootstrap-only views into one root-owned candidate."""

    _runtime: StagedResourceCompositionCandidate

    def _require_root(self) -> StagedResourceCompositionCandidate:
        if self._runtime.ownership_state != "root_owned":
            raise RuntimeError("Resource bootstrap handles are no longer root-owned")
        return self._runtime

    @property
    def skill_activation(self) -> SkillActivationRuntime:
        return self._require_root().skill_activation

    def activate_resources(self, bundle: ResourceBundle | None) -> ResourceActivation:
        return self._require_root().activate_resources(bundle)

    @property
    def prompt_section_composer(self) -> PromptSectionComposer:
        return self._require_root().prompt_section_composer

    @property
    def tool_pack_composer(self) -> CapabilityPackComposer:
        return self._require_root().tool_pack_composer

    @property
    def resource_catalog_snapshot(self) -> object:
        runtime = self._require_root()
        return runtime._require_prepared_owner_generation().catalog_snapshot

    @property
    def resource_catalog_projection(self) -> object:
        runtime = self._require_root()
        return runtime._require_prepared_owner_generation().catalog_projection

    @property
    def _resource_skill_status_projection(self) -> object:
        runtime = self._require_root()
        generation = runtime._require_prepared_owner_generation()
        return generation._skill_status_projection

    def dispose(self) -> None:
        self._runtime.dispose()


class StagedResourceCompositionCandidate:
    """Staged resource mechanisms with exactly one transferable owner.

    Synchronous Product bootstrap owns the candidate initially.  The Session
    Capability graph may claim that same candidate exactly once; after the
    claim, this object is only a compatibility view and the graph owns release.
    No Product content, Extension object, or handler callback enters the
    binding.
    """

    def __init__(
        self,
        *,
        binding: RuntimeProfileBinding,
        _binder: RuntimeProfileBinder,
        _profile: ResolvedRuntimeProfile,
    ) -> None:
        self.__candidate = _CapabilityCompositionCandidate(
            binding=binding,
            binder=_binder,
            profile=_profile,
        )
        self._owner_candidate_factory_identity: (
            _OwnerCandidateFactoryIdentity | None
        ) = None

    @property
    def binding(self) -> RuntimeProfileBinding:
        """Compatibility read view; lifecycle ownership stays in the candidate."""

        return self.__candidate.binding

    @property
    def _binder(self) -> RuntimeProfileBinder:
        """Compatibility-only test seam for the private Provider binder."""

        return self.__candidate.binder

    @property
    def profile(self) -> ResolvedRuntimeProfile:
        current_resources = {
            capability.slot.key: capability
            for capability in self.binding.profile.capabilities
        }
        return ResolvedRuntimeProfile(
            product_id=self.__candidate.profile.product_id,
            capabilities=tuple(
                current_resources.get(capability.slot.key, capability)
                for capability in self.__candidate.profile.capabilities
            ),
            schema_version=self.__candidate.profile.schema_version,
        )

    @property
    def ownership_state(self) -> str:
        """Return the redacted handoff state used by lifecycle tests."""

        return self.__candidate.ownership

    @property
    def has_prepared_owner_generation(self) -> bool:
        return self.__candidate.owner_generation is not None

    @property
    def prepared_owner_generation_state(self) -> str | None:
        generation = self.__candidate.owner_generation
        return None if generation is None else generation.ownership_state

    @property
    def resource_owner_generation_binding_fingerprint(self) -> str | None:
        generation = self.__candidate.owner_generation
        if generation is None:
            return None
        return generation.provider_binding_fingerprint

    def resource_owner_generation_retirement_receipt(
        self,
        *,
        contribution_ids: tuple[str, ...],
    ) -> OwnerGenerationRetirementReceipt:
        receipt = self._require_prepared_owner_generation().retirement_receipt(
            contribution_ids=contribution_ids,
        )
        if not isinstance(receipt, OwnerGenerationRetirementReceipt):
            raise TypeError("Resource owner generation retirement receipt is invalid")
        return receipt

    def _assert_can_attach_prepared_owner_generation(self) -> None:
        if self.__candidate.ownership != "root_owned":
            raise RuntimeError(
                "Only a root-owned Resource candidate can prepare an owner generation"
            )
        if self.__candidate.owner_generation is not None:
            raise RuntimeError(
                "Resource candidate already has a prepared owner generation"
            )
        if not _is_staged_resource_candidate_factory_recorded(self):
            raise TypeError("Resource candidate is not staging-factory-recorded")

    def _attach_prepared_owner_generation(
        self,
        generation: object,
    ) -> _OwnerGenerationAttachmentReceipt:
        """Take exclusive root custody of one unpublished owner generation."""

        self._assert_can_attach_prepared_owner_generation()
        if not _is_owner_generation_factory_recorded(generation):
            raise TypeError("Resource candidate requires a prepared owner generation")
        prepared = cast(_PreparedResourceOwnerGeneration, generation)
        if prepared.ownership_state != "root_owned":
            raise RuntimeError("Prepared owner generation is not root-owned")
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        if factory is None or factory.candidate_ref() is not self:
            raise TypeError("Resource candidate lost its exact factory custody")
        self.__candidate.owner_generation = prepared
        factory.custody.current = prepared
        receipt = object.__new__(_OwnerGenerationAttachmentReceipt)
        receipt_id = id(receipt)

        def discard_candidate(
            reference: weakref.ReferenceType[StagedResourceCompositionCandidate],
        ) -> None:
            current = _OWNER_GENERATION_ATTACHMENTS.get(receipt_id)
            if current is not None and current.candidate_ref is reference:
                _OWNER_GENERATION_ATTACHMENTS.pop(receipt_id, None)

        def discard_owner(
            reference: weakref.ReferenceType[_PreparedResourceOwnerGeneration],
        ) -> None:
            current = _OWNER_GENERATION_ATTACHMENTS.get(receipt_id)
            if current is not None and current.owner_ref is reference:
                _OWNER_GENERATION_ATTACHMENTS.pop(receipt_id, None)

        try:
            _OWNER_GENERATION_ATTACHMENTS[receipt_id] = (
                _OwnerGenerationAttachmentRecord(
                    candidate_ref=weakref.ref(self, discard_candidate),
                    owner_ref=weakref.ref(prepared, discard_owner),
                    receipt=receipt,
                    state="attached",
                )
            )
        except BaseException:
            self.__candidate.owner_generation = None
            factory.custody.current = None
            raise
        return receipt

    def _detach_failed_prepared_owner_generation(
        self,
        generation: object,
        receipt: _OwnerGenerationAttachmentReceipt,
    ) -> bool:
        """Rollback a root-owned attachment whose downstream enrollment failed."""

        current = self.__candidate.owner_generation
        if current is not generation:
            return False
        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Resource owner attachment rollback lost exact custody")
        _rollback_owner_generation_attachment(
            receipt,
            candidate=self,
            owner=generation,
        )
        self.__candidate.owner_generation = None
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        if factory is None or factory.candidate_ref() is not self:
            raise TypeError("Resource candidate lost its exact factory custody")
        factory.custody.current = None
        return True

    def _require_prepared_owner_generation(
        self,
    ) -> _PreparedResourceOwnerGeneration:
        generation = self.__candidate.owner_generation
        if generation is None:
            raise RuntimeError("Resource candidate has no prepared owner generation")
        return generation

    def capture_resource_catalog_generation(self) -> ResourceCatalogGenerationCapture:
        """Capture the exact current generation without exposing replacement rights."""

        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return ResourceCatalogGenerationCapture(
            self._require_prepared_owner_generation()
        )

    def stage_refresh_successor(self) -> StagedResourceCompositionCandidate:
        """Create one root-owned successor with identical Resource mechanisms."""

        if not _is_staged_resource_candidate_factory_recorded(self):
            raise TypeError("Resource refresh requires a staging-factory candidate")
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Only a mounted Resource candidate may stage refresh")
        profile = self.__candidate.profile
        binder = self.__candidate.binder
        binding = binder.bind_sync(
            resource_capability_profile(profile),
            context=self.binding._context,
        )
        try:
            successor = StagedResourceCompositionCandidate(
                binding=binding,
                _binder=binder,
                _profile=profile,
            )
        except BaseException as exc:
            _dispose_unpublished_resource_binding(binder, binding, exc)
            raise
        identity = object.__new__(_OwnerCandidateFactoryIdentity)
        identity_id = id(identity)
        candidate_id = id(successor)
        candidate_ref = weakref.ref(
            successor,
            _candidate_factory_discard_callback(
                identity_id=identity_id,
                candidate_id=candidate_id,
            ),
        )
        try:
            record = _build_staged_resource_candidate_factory_record(
                candidate_ref=candidate_ref,
                identity=identity,
                candidate_state=successor.__candidate,
                binder=binder,
                binding=binding,
                profile=profile,
            )
            _OWNER_CANDIDATE_FACTORIES[identity_id] = _OwnerCandidateFactoryRecord(
                candidate_ref=candidate_ref,
                identity=identity,
            )
            _STAGED_RESOURCE_CANDIDATE_FACTORIES[identity_id] = record
            _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES[candidate_id] = identity_id
            successor._owner_candidate_factory_identity = identity
            return successor
        except BaseException as exc:
            _rollback_candidate_factory_publication(
                identity_id=identity_id,
                candidate_id=candidate_id,
            )
            _dispose_unpublished_resource_binding(binder, binding, exc)
            raise

    def _claim_refresh_successor(self) -> None:
        """Mark a fully prepared successor as owned by the mounted graph slot."""

        if not _is_staged_resource_candidate_factory_recorded(self):
            raise TypeError("Resource refresh claim requires its exact staged successor")
        self._begin_graph_construction()
        self._commit_graph_ownership()

    def begin_owner_generation_replacement(
        self,
        successor: StagedResourceCompositionCandidate,
    ) -> ResourceOwnerGenerationReplacement:
        """Swap one prepared successor in a synchronous rollback-capable window."""

        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError(
                "Resource generation replacement requires graph ownership"
            )
        if not isinstance(successor, StagedResourceCompositionCandidate):
            raise TypeError("Resource generation successor is invalid")
        if not (
            _is_staged_resource_candidate_factory_recorded(self)
            and _is_staged_resource_candidate_factory_recorded(successor)
        ):
            raise TypeError("Resource generation replacement requires exact candidates")
        if successor.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource generation successor is not graph-owned")
        expected = resource_capability_profile(self.profile).snapshot().to_json()
        actual = resource_capability_profile(successor.profile).snapshot().to_json()
        if actual != expected:
            raise RuntimeError("Resource generation successor changes mechanisms")
        previous = self._require_prepared_owner_generation()
        current = successor._require_prepared_owner_generation()
        previous_catalog_generation = getattr(
            previous.catalog_snapshot,
            "catalog_generation",
            None,
        )
        current_catalog_generation = getattr(
            current.catalog_snapshot,
            "catalog_generation",
            None,
        )
        if (
            not isinstance(previous_catalog_generation, int)
            or isinstance(previous_catalog_generation, bool)
            or not isinstance(current_catalog_generation, int)
            or isinstance(current_catalog_generation, bool)
            or current_catalog_generation != previous_catalog_generation + 1
        ):
            raise ValueError("Resource Catalog successor generation is not monotonic")
        owner_factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        successor_factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(successor._owner_candidate_factory_identity)
        )
        if (
            owner_factory is None
            or owner_factory.candidate_ref() is not self
            or owner_factory.custody.current is not previous
            or successor_factory is None
            or successor_factory.candidate_ref() is not successor
            or successor_factory.custody.current is not current
        ):
            raise TypeError("Resource generation replacement lost exact custody")
        replacement = _reserve_resource_owner_generation_replacement(
            owner=self,
            previous=previous,
            current=current,
        )
        try:
            successor_factory.custody.binding_cleanup_started = True
            successor.__candidate.binder.dispose_sync(successor.binding)
            successor.__candidate.owner_generation = None
            successor.__candidate.ownership = "disposed"
            successor_factory.custody.current = None
            successor_factory.custody.ownership = "disposed"
            self.__candidate.owner_generation = current
            owner_factory.custody.current = current
        except BaseException:
            with _RESOURCE_OWNER_GENERATION_REPLACEMENT_LOCK:
                record = _RESOURCE_OWNER_GENERATION_REPLACEMENTS.get(
                    id(replacement._token)
                )
                if record is not None and record.owner is self:
                    _RESOURCE_OWNER_GENERATION_REPLACEMENTS.pop(
                        id(replacement._token), None
                    )
                    _RESOURCE_OWNER_GENERATION_REPLACEMENTS_BY_OWNER.pop(
                        id(self), None
                    )
            raise
        return replacement

    def _commit_owner_generation_replacement(
        self,
        *,
        previous: _PreparedResourceOwnerGeneration,
        current: _PreparedResourceOwnerGeneration,
    ) -> None:
        if self.__candidate.owner_generation is not current:
            raise RuntimeError("Resource generation replacement lost current custody")
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        if factory is None or factory.custody.current is not current:
            raise RuntimeError("Resource generation replacement lost recorded custody")
        self.__candidate.retired_owner_generations.append(previous)
        factory.custody.retired.append(previous)

    def _rollback_owner_generation_replacement(
        self,
        *,
        previous: _PreparedResourceOwnerGeneration,
        current: _PreparedResourceOwnerGeneration,
    ) -> None:
        if self.__candidate.owner_generation is not current:
            raise RuntimeError("Resource generation replacement lost current custody")
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        if factory is None or factory.custody.current is not current:
            raise RuntimeError("Resource generation replacement lost recorded custody")
        self.__candidate.owner_generation = previous
        self.__candidate.retired_owner_generations.append(current)
        factory.custody.current = previous
        factory.custody.retired.append(current)

    async def retire_replaced_owner_generations(self) -> tuple[str, ...]:
        """Retire every detached generation whose exact source leases have drained."""

        state = _recorded_staged_resource_candidate_cleanup_state(self)
        if state is None:
            state = self.__candidate
        identity_id = _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(id(self))
        factory = (
            _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(identity_id)
            if identity_id is not None
            else None
        )
        pending = (
            list(factory.custody.retired)
            if factory is not None and factory.candidate_ref() is self
            else list(state.retired_owner_generations)
        )
        remaining: list[_PreparedResourceOwnerGeneration] = []
        diagnostic_codes: list[str] = []
        for index, generation in enumerate(pending):
            try:
                await generation._dispose_graph_owned()
            except BaseException as exc:
                codes = getattr(exc, "diagnostic_codes", None)
                if not isinstance(codes, tuple) or any(
                    not isinstance(code, str) or not code for code in codes
                ):
                    state.retired_owner_generations = [
                        *remaining,
                        generation,
                        *pending[index + 1 :],
                    ]
                    if factory is not None:
                        factory.custody.retired = list(
                            state.retired_owner_generations
                        )
                    raise
                diagnostic_codes.extend(codes)
                remaining.append(generation)
        state.retired_owner_generations = remaining
        if factory is not None:
            factory.custody.retired = list(remaining)
        return tuple(sorted(set(diagnostic_codes)))

    async def dispose_refresh_successor(self) -> tuple[str, ...]:
        """Dispose a staged successor without granting whole-graph authority."""

        state = _recorded_staged_resource_candidate_cleanup_state(self)
        if state is None:
            state = self.__candidate
        if state.ownership == "disposed":
            return ()
        await self._dispose_graph_owned_async()
        return ()

    def _borrows_prepared_extension_source_lease(self, source: object) -> bool:
        """Prove exact borrowed-lease identity to the joint construction root."""

        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Resource candidate is not root-owned")
        generation = self._require_prepared_owner_generation()
        return generation._borrows_extension_source_lease(source)

    @property
    def resource_catalog_snapshot(self) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return self._require_prepared_owner_generation().catalog_snapshot

    @property
    def resource_catalog_projection(self) -> object:
        if self.__candidate.ownership not in {"root_owned", "graph_owned"}:
            raise RuntimeError("Resource Catalog generation is not retained")
        return self._require_prepared_owner_generation().catalog_projection

    @property
    def _resource_skill_status_projection(self) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return self._require_prepared_owner_generation()._skill_status_projection

    def resource_load_handle(self, identity: object) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return self._require_prepared_owner_generation().load_handle(identity)

    async def load_resource(self, handle: object) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return await self._require_prepared_owner_generation().load(handle)

    def _root_owned_handles(self) -> _RootOwnedResourceCapabilityHandles:
        """Return the focused private handles used only during bootstrap."""

        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Resource candidate is not root-owned")
        return _RootOwnedResourceCapabilityHandles(self)

    def select_final_profile(self, profile: ResolvedRuntimeProfile) -> None:
        """Attach final immutable selection facts without rebuilding resources.

        The resource projection must be identical to the already-constructed
        bootstrap candidate.  A changed resource mechanism requires a future
        graph replacement contract and therefore fails closed in this slice.
        """

        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Only a root-owned resource candidate can be selected")
        if not _is_staged_resource_candidate_factory_recorded(self):
            raise TypeError("Resource selection requires its exact staged candidate")
        expected = self.binding.profile.snapshot().to_json()
        actual = resource_capability_profile(profile).snapshot().to_json()
        if actual != expected:
            raise RuntimeError(
                "Final resource mechanism selections differ from the staged candidate"
            )
        identity = self._owner_candidate_factory_identity
        record = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(id(identity))
        if record is None or record.candidate_ref() is not self:
            raise TypeError("Resource selection lost exact candidate authority")
        self.__candidate.profile = profile
        _STAGED_RESOURCE_CANDIDATE_FACTORIES[id(identity)] = replace(
            record,
            profile=profile,
            resource_profile_json=actual,
        )

    def _begin_graph_construction(self) -> None:
        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Resource candidate is not available for graph claim")
        if not _is_staged_resource_candidate_factory_recorded(self):
            raise TypeError("Resource graph claim requires its exact staged candidate")
        generation = self.__candidate.owner_generation
        if generation is not None:
            generation._begin_graph_construction()
        self.__candidate.ownership = "graph_constructing"
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        assert factory is not None
        factory.custody.ownership = "graph_constructing"

    def _commit_graph_ownership(self) -> None:
        if self.__candidate.ownership != "graph_constructing":
            raise RuntimeError("Resource candidate graph claim was not started")
        if not _is_staged_resource_candidate_factory_recorded(self):
            raise TypeError("Resource graph claim requires its exact staged candidate")
        generation = self.__candidate.owner_generation
        if generation is not None:
            generation._commit_graph_ownership()
        self.__candidate.ownership = "graph_owned"
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        assert factory is not None
        factory.custody.ownership = "graph_owned"

    def _restore_root_ownership(self) -> None:
        if self.__candidate.ownership != "graph_constructing":
            raise RuntimeError("Resource candidate graph claim is not in progress")
        generation = self.__candidate.owner_generation
        if generation is not None:
            generation._restore_root_ownership()
        self.__candidate.ownership = "root_owned"
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            id(self._owner_candidate_factory_identity)
        )
        assert factory is not None
        factory.custody.ownership = "root_owned"

    def _dispose_graph_owned(self) -> None:
        state = _recorded_staged_resource_candidate_cleanup_state(self)
        if state is None:
            state = self.__candidate
        if state.owner_generation is not None:
            raise RuntimeError(
                "Prepared Resource owner generation requires asynchronous disposal"
            )
        if state.ownership == "disposed":
            return
        if state.ownership != "graph_owned":
            raise RuntimeError(
                "Graph cannot dispose a resource candidate it does not own"
            )
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(id(self), -1)
        )
        if factory is not None:
            factory.custody.binding_cleanup_started = True
        state.binder.dispose_sync(state.binding)
        state.ownership = "disposed"
        if factory is not None:
            factory.custody.ownership = "disposed"

    async def _dispose_graph_owned_async(self) -> None:
        state = _recorded_staged_resource_candidate_cleanup_state(self)
        if state is None:
            state = self.__candidate
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(id(self), -1)
        )
        generation = state.owner_generation
        if generation is None and not state.retired_owner_generations:
            self._dispose_graph_owned()
            return
        if state.ownership == "disposed":
            return
        if state.ownership == "graph_owned":
            state.ownership = "retiring"
            state.retirement_owner = "graph"
            if factory is not None:
                factory.custody.ownership = "retiring"
                factory.custody.retirement_owner = "graph"
        elif not (
            state.ownership == "retiring"
            and state.retirement_owner == "graph"
        ):
            raise RuntimeError(
                "Graph cannot dispose a Resource candidate it does not own"
            )
        if (
            generation is not None
            and generation not in state.retired_owner_generations
        ):
            state.retired_owner_generations.append(generation)
            if factory is not None:
                factory.custody.retired.append(generation)
        codes = await self.retire_replaced_owner_generations()
        if codes:
            raise ResourceOwnerGenerationRetirementError(codes)
        if factory is not None:
            factory.custody.binding_cleanup_started = True
        state.binder.dispose_sync(state.binding)
        state.ownership = "disposed"
        state.retirement_owner = None
        if factory is not None:
            factory.custody.ownership = "disposed"
            factory.custody.retirement_owner = None

    def apply_skill_activation(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle:
        return self.skill_activation.apply(bundle, disabled_skills)

    def activate_resources(self, bundle: ResourceBundle | None) -> ResourceActivation:
        return self.resource_runtime.activate(bundle)

    def compose_prompt_sections(self) -> PromptSectionComposer:
        return self.prompt_section_composer

    def compose_tool_packs(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return self.tool_pack_composer.compose(packs)

    def compose_command_packs(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return self.command_pack_composer.compose(packs)

    @property
    def resource_runtime(self) -> ResourceActivationRuntime:
        return _require_value(
            self.binding.value(RESOURCE_RUNTIME_SLOT.key),
            ResourceActivationRuntime,
            RESOURCE_RUNTIME_SLOT.key,
        )

    @property
    def skill_activation(self) -> SkillActivationRuntime:
        return _require_value(
            self.binding.value(SKILL_ACTIVATION_SLOT.key),
            SkillActivationRuntime,
            SKILL_ACTIVATION_SLOT.key,
        )

    @property
    def prompt_section_composer(self) -> PromptSectionComposer:
        return _require_value(
            self.binding.value(PROMPT_SECTIONS_SLOT.key),
            PromptSectionComposer,
            PROMPT_SECTIONS_SLOT.key,
        )

    @property
    def tool_pack_composer(self) -> CapabilityPackComposer:
        return _require_value(
            self.binding.value(TOOL_PACKS_SLOT.key),
            CapabilityPackComposer,
            TOOL_PACKS_SLOT.key,
        )

    @property
    def command_pack_composer(self) -> CapabilityPackComposer:
        return _require_value(
            self.binding.value(COMMAND_PACKS_SLOT.key),
            CapabilityPackComposer,
            COMMAND_PACKS_SLOT.key,
        )

    def dispose(self) -> None:
        """Dispose only while the construction root still owns the candidate."""

        state = _recorded_staged_resource_candidate_cleanup_state(self)
        if state is None:
            state = self.__candidate
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(id(self), -1)
        )
        if state.ownership == "disposed":
            return
        if state.owner_generation is not None:
            raise RuntimeError(
                "Prepared Resource owner generation requires dispose_root_owned()"
            )
        if state.ownership == "graph_owned":
            return
        if state.ownership == "graph_constructing":
            raise RuntimeError("Resource candidate ownership transfer is in progress")
        if factory is not None:
            factory.custody.binding_cleanup_started = True
        state.binder.dispose_sync(state.binding)
        state.ownership = "disposed"
        if factory is not None:
            factory.custody.ownership = "disposed"

    async def dispose_root_owned(self) -> None:
        """Retire the complete staged candidate before Graph adoption."""

        state = _recorded_staged_resource_candidate_cleanup_state(self)
        if state is None:
            state = self.__candidate
        factory = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(
            _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(id(self), -1)
        )
        generation = state.owner_generation
        if generation is None:
            self.dispose()
            return
        if state.ownership == "disposed":
            return
        if state.ownership == "root_owned":
            state.ownership = "retiring"
            state.retirement_owner = "root"
            if factory is not None:
                factory.custody.ownership = "retiring"
                factory.custody.retirement_owner = "root"
        elif not (
            state.ownership == "retiring"
            and state.retirement_owner == "root"
        ):
            raise RuntimeError(
                "Construction root cannot dispose a Resource candidate it does not own"
            )
        await generation.dispose_root_owned()
        if factory is not None:
            factory.custody.binding_cleanup_started = True
        state.binder.dispose_sync(state.binding)
        state.ownership = "disposed"
        state.retirement_owner = None
        if factory is not None:
            factory.custody.ownership = "disposed"
            factory.custody.retirement_owner = None


class ResourceCandidateSealingCleanupError(RuntimeError):
    """A failed candidate seal whose unpublished binding still needs cleanup."""

    def __init__(
        self,
        *,
        primary_error: BaseException,
        cleanup_error: BaseException,
        binder: RuntimeProfileBinder,
        binding: RuntimeProfileBinding,
    ) -> None:
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error
        self._binder: RuntimeProfileBinder | None = binder
        self._binding: RuntimeProfileBinding | None = binding
        self._cleanup_lock = Lock()
        super().__init__(
            "Resource candidate sealing failed and unpublished binding cleanup "
            f"remains pending: {type(cleanup_error).__name__}: {cleanup_error}"
        )

    @property
    def cleanup_pending(self) -> bool:
        """Whether the exact unpublished binding still has retryable cleanup debt."""

        return self._binding is not None

    def retry_cleanup(self) -> None:
        """Retry disposal of the exact unpublished binding; successful calls are idempotent."""

        with self._cleanup_lock:
            binder = self._binder
            binding = self._binding
            if binder is None or binding is None:
                return
            try:
                binder.dispose_sync(binding)
            except BaseException as exc:
                self.cleanup_error = exc
                raise
            self._binder = None
            self._binding = None


def _dispose_unpublished_resource_binding(
    binder: RuntimeProfileBinder,
    binding: RuntimeProfileBinding,
    primary_error: BaseException,
) -> None:
    """Dispose or raise a stable owner for retryable candidate cleanup debt."""

    try:
        binder.dispose_sync(binding)
    except BaseException as cleanup_error:
        raise ResourceCandidateSealingCleanupError(
            primary_error=primary_error,
            cleanup_error=cleanup_error,
            binder=binder,
            binding=binding,
        ) from primary_error


def _candidate_factory_discard_callback(
    *,
    identity_id: int,
    candidate_id: int,
) -> Callable[[weakref.ReferenceType[StagedResourceCompositionCandidate]], None]:
    """Build weakref cleanup without retaining the candidate itself."""

    def discard(
        reference: weakref.ReferenceType[StagedResourceCompositionCandidate],
    ) -> None:
        neutral = _OWNER_CANDIDATE_FACTORIES.get(identity_id)
        if neutral is not None and neutral.candidate_ref is reference:
            _OWNER_CANDIDATE_FACTORIES.pop(identity_id, None)
        resource = _STAGED_RESOURCE_CANDIDATE_FACTORIES.get(identity_id)
        if resource is not None and resource.candidate_ref is reference:
            _STAGED_RESOURCE_CANDIDATE_FACTORIES.pop(identity_id, None)
        if _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(candidate_id) == identity_id:
            _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.pop(candidate_id, None)

    return discard


def _build_staged_resource_candidate_factory_record(
    *,
    candidate_ref: Callable[[], object | None],
    identity: _OwnerCandidateFactoryIdentity,
    candidate_state: _CapabilityCompositionCandidate,
    binder: RuntimeProfileBinder,
    binding: RuntimeProfileBinding,
    profile: ResolvedRuntimeProfile,
) -> _StagedResourceCandidateFactoryRecord:
    """Freeze a candidate record without minting or publishing authority."""

    registry = binder._registry
    implementations = registry._implementations
    implementation_items = tuple(
        sorted(implementations.items(), key=lambda item: repr(item[0]))
    )
    return _StagedResourceCandidateFactoryRecord(
        candidate_ref=candidate_ref,
        identity=identity,
        candidate_state=candidate_state,
        binding=binding,
        binder=binder,
        binder_registry=registry,
        binder_implementations=implementations,
        binder_implementation_items=implementation_items,
        binder_implementation_facts=_runtime_implementation_facts(
            implementation_items
        ),
        binder_bind_sync=type(binder).bind_sync,
        binder_instance_keys=tuple(sorted(vars(binder))),
        profile=profile,
        binding_context=binding._context,
        binding_context_fact=_freeze_candidate_factory_fact(binding._context),
        binding_profile=binding.profile,
        binding_state=binding._state,
        binding_runtime_bindings=binding._state.bindings,
        binding_state_fact=_binding_state_fact(binding._state),
        binding_bound=binding._bound,
        binding_bound_fact=_binding_bound_fact(binding._bound),
        resource_profile_json=resource_capability_profile(profile).snapshot().to_json(),
        binding_profile_json=binding.profile.snapshot().to_json(),
        custody=_StagedResourceCandidateCustody(
            current=None,
            retired=[],
            ownership="root_owned",
            retirement_owner=None,
            binding_cleanup_started=False,
        ),
    )


def _rollback_candidate_factory_publication(
    *,
    identity_id: int,
    candidate_id: int,
) -> None:
    """Remove only a canonical path's partially published candidate records."""

    _OWNER_CANDIDATE_FACTORIES.pop(identity_id, None)
    _STAGED_RESOURCE_CANDIDATE_FACTORIES.pop(identity_id, None)
    if _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.get(candidate_id) == identity_id:
        _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES.pop(candidate_id, None)


def stage_resource_composition_candidate(
    profile: ResolvedRuntimeProfile,
    *,
    context: object | None = None,
    additional_implementations: Iterable[RuntimeCapabilityImplementation] = (),
) -> StagedResourceCompositionCandidate:
    """Synchronously bind standard capability-composition implementations."""

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            implementation
            for implementation in (
                *standard_capability_composition_implementations(),
                *tuple(additional_implementations),
            )
            if implementation.slot in RESOURCE_CAPABILITY_SLOT_KEYS
        )
    )
    resource_profile = resource_capability_profile(profile)
    binding = binder.bind_sync(resource_profile, context=context)
    try:
        candidate = StagedResourceCompositionCandidate(
            binding=binding,
            _binder=binder,
            _profile=profile,
        )
    except BaseException as exc:
        _dispose_unpublished_resource_binding(binder, binding, exc)
        raise
    identity = object.__new__(_OwnerCandidateFactoryIdentity)
    identity_id = id(identity)
    candidate_id = id(candidate)
    candidate_ref = weakref.ref(
        candidate,
        _candidate_factory_discard_callback(
            identity_id=identity_id,
            candidate_id=candidate_id,
        ),
    )
    state = cast(
        _CapabilityCompositionCandidate,
        getattr(candidate, "_StagedResourceCompositionCandidate__candidate"),
    )
    try:
        record = _build_staged_resource_candidate_factory_record(
            candidate_ref=candidate_ref,
            identity=identity,
            candidate_state=state,
            binder=binder,
            binding=binding,
            profile=profile,
        )
        _OWNER_CANDIDATE_FACTORIES[identity_id] = _OwnerCandidateFactoryRecord(
            candidate_ref=candidate_ref,
            identity=identity,
        )
        _STAGED_RESOURCE_CANDIDATE_FACTORIES[identity_id] = record
        _STAGED_RESOURCE_CANDIDATE_FACTORY_IDENTITIES[candidate_id] = identity_id
        candidate._owner_candidate_factory_identity = identity
        return candidate
    except BaseException as exc:
        _rollback_candidate_factory_publication(
            identity_id=identity_id,
            candidate_id=candidate_id,
        )
        _dispose_unpublished_resource_binding(binder, binding, exc)
        raise


def standard_capability_composition_implementations() -> tuple[
    RuntimeCapabilityImplementation, ...
]:
    """Return the first-party standard composition implementations.

    These mechanisms are intentionally closed over exact configuration shapes.
    Product policy such as resource roots, disabled selectors, and conflict
    resolution remains outside the selected mechanism.
    """

    return (
        RuntimeCapabilityImplementation(
            slot=RESOURCE_RUNTIME_SLOT.key,
            implementation=RESOURCE_ACTIVATION_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_resource_runtime,
        ),
        RuntimeCapabilityImplementation(
            slot=PROMPT_SECTIONS_SLOT.key,
            implementation=PROMPT_SECTIONS_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_prompt_section_composer,
        ),
        RuntimeCapabilityImplementation(
            slot=SKILL_ACTIVATION_SLOT.key,
            implementation=DISABLED_SKILL_ACTIVATION_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_skill_activation_runtime,
        ),
        RuntimeCapabilityImplementation(
            slot=TOOL_PACKS_SLOT.key,
            implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_capability_pack_composer,
        ),
        RuntimeCapabilityImplementation(
            slot=COMMAND_PACKS_SLOT.key,
            implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_capability_pack_composer,
        ),
        RuntimeCapabilityImplementation(
            slot=SIDE_QUESTION_PROVIDER_SLOT.key,
            implementation=AGENT_SIDE_QUESTION_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_agent_side_question_provider_factory,
        ),
    )


def resource_capability_profile(
    profile: ResolvedRuntimeProfile,
) -> ResolvedRuntimeProfile:
    """Project the private resource mechanism selections from one full Profile."""

    capabilities = tuple(
        capability
        for capability in profile.capabilities
        if capability.slot.key in RESOURCE_CAPABILITY_SLOT_KEYS
    )
    present = {capability.slot.key for capability in capabilities}
    missing = RESOURCE_CAPABILITY_SLOT_KEYS - present
    if missing:
        raise ValueError(
            "resource capability profile is missing slots: "
            + ", ".join(sorted(missing))
        )
    return ResolvedRuntimeProfile(
        product_id=profile.product_id,
        capabilities=capabilities,
        schema_version=profile.schema_version,
    )


def _create_resource_runtime(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> ResourceActivationRuntime:
    del context
    _require_exact_config(selection, expected=set())
    return ResourceActivationRuntime()


def _create_prompt_section_composer(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> PromptSectionComposer:
    del context
    config = _require_exact_config(
        selection,
        expected={"separator", "stripSections"},
    )
    separator = config["separator"]
    strip_sections = config["stripSections"]
    if not isinstance(separator, str) or type(strip_sections) is not bool:
        raise TypeError(
            "prompt section configuration requires a string separator and bool "
            "stripSections"
        )
    return PromptSectionComposer(separator=separator, strip_sections=strip_sections)


def _create_skill_activation_runtime(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> SkillActivationRuntime:
    del context
    _require_exact_config(selection, expected=set())
    return SkillActivationRuntime()


def _create_capability_pack_composer(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> CapabilityPackComposer:
    del context
    _require_exact_config(selection, expected=set())
    return CapabilityPackComposer()


def _create_agent_side_question_provider_factory(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> SideQuestionProviderFactory:
    del context
    _require_exact_config(selection, expected=set())
    return SessionSideQuestionProviderFactory()


def _require_exact_config(
    selection: RuntimeCapabilitySelection,
    *,
    expected: set[str],
) -> Mapping[str, object]:
    config = selection.config
    if set(config) != expected:
        expected_keys = ", ".join(sorted(expected)) or "no keys"
        actual_keys = ", ".join(sorted(config)) or "no keys"
        raise ValueError(
            f"{selection.implementation} configuration must contain "
            f"{expected_keys}; received {actual_keys}"
        )
    return config


def _require_value(
    value: object | tuple[object, ...],
    expected_type: type[TValue],
    slot: str,
) -> TValue:
    if isinstance(value, tuple):
        if len(value) != 1:
            raise TypeError(
                "standard capability runtime requires one selected implementation: "
                f"{slot}"
            )
        value = value[0]
    if not isinstance(value, expected_type):
        raise TypeError(f"selected capability implementation is invalid: {slot}")
    return value


__all__ = [
    "AGENT_SIDE_QUESTION_IMPLEMENTATION",
    "CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION",
    "ResourceCandidateSealingCleanupError",
    "StagedResourceCompositionCandidate",
    "DISABLED_SKILL_ACTIVATION_IMPLEMENTATION",
    "ORDERED_CAPABILITY_PACKS_IMPLEMENTATION",
    "PROMPT_SECTIONS_IMPLEMENTATION",
    "RESOURCE_CAPABILITY_SLOT_KEYS",
    "RESOURCE_ACTIVATION_IMPLEMENTATION",
    "stage_resource_composition_candidate",
    "resource_capability_profile",
    "standard_capability_composition_plan",
    "standard_capability_composition_implementations",
]
