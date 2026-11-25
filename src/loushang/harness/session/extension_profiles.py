"""Resolve Extension Profile declarations and check graph refresh compatibility."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass

from loushang.harness.capabilities.composition_runtime import (
    RESOURCE_CAPABILITY_SLOT_KEYS,
    StagedResourceCompositionCandidate,
    resource_capability_profile,
    stage_resource_composition_candidate,
)
from loushang.harness.capabilities.effective_runtime import runtime_profile_fingerprint
from loushang.harness.extensions.declarations import (
    ExtensionCapabilityDeclarationSnapshot,
    ExtensionGraphProviderRestartRequiredError,
    ExtensionRuntimeCapabilityDeclaration,
    extension_declaration_id,
)
from loushang.harness.extensions.types import (
    LoadedExtension,
    RegisteredRuntimeCapabilityReplacement,
)
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    ProductRuntimePlan,
    ResolvedRuntimeProfile,
    RuntimeCapabilityImplementation,
    RuntimeCapabilitySelection,
    RuntimeProfileAdmissionPolicy,
    RuntimeProfileLayer,
    RuntimeProfileLayerGrant,
    RuntimeProfileResolver,
)
from loushang.harness.session.legacy_side_question import (
    LegacySideQuestionBinding,
    bind_legacy_side_question,
)

_SIDE_QUESTION_SLOTS = frozenset({SIDE_QUESTION_PROVIDER_SLOT.key})
_GRAPH_SLOT_GROUPS = (
    ("harness.resources", RESOURCE_CAPABILITY_SLOT_KEYS),
    ("harness.session", _SIDE_QUESTION_SLOTS),
)
_GRAPH_SLOTS = RESOURCE_CAPABILITY_SLOT_KEYS | _SIDE_QUESTION_SLOTS


@dataclass(frozen=True)
class SessionExtensionProfileResolution:
    """One admitted profile and its matching executable factories."""

    profile: ResolvedRuntimeProfile
    implementations: tuple[RuntimeCapabilityImplementation, ...]

    def bind(self) -> StagedResourceCompositionCandidate:
        return stage_resource_composition_candidate(
            self.profile,
            additional_implementations=self.implementations,
        )

    def bind_side_question(self) -> LegacySideQuestionBinding:
        return bind_legacy_side_question(
            self.profile,
            additional_implementations=self.implementations,
        )


def prepare_session_resource_candidate(
    default_profile: ResolvedRuntimeProfile | None = None,
    *,
    candidate: StagedResourceCompositionCandidate | None = None,
    resolution: SessionExtensionProfileResolution | None = None,
) -> StagedResourceCompositionCandidate:
    """Finish a borrowed candidate or stage the Session's admitted resources."""
    if candidate is not None:
        if resolution is not None:
            candidate.select_final_profile(resolution.profile)
        return candidate
    if resolution is not None:
        return resolution.bind()
    if default_profile is None:
        raise ValueError("Session construction requires a resource profile")
    return stage_resource_composition_candidate(default_profile)


def prepare_extension_profile(
    extensions: Iterable[LoadedExtension],
    plan: ProductRuntimePlan,
    slot_permissions: Mapping[str, frozenset[str]],
    *,
    factory_error: str,
) -> tuple[ResolvedRuntimeProfile, tuple[RuntimeCapabilityImplementation, ...]]:
    """Admit declarations before preparing executable factory bindings."""
    extension_tuple = tuple(extensions)
    declaration_snapshot = ExtensionCapabilityDeclarationSnapshot.from_extensions(
        extension_tuple
    )
    profile = _resolve_declarations(declaration_snapshot, plan, slot_permissions)
    implementations: list[RuntimeCapabilityImplementation] = []

    for extension in extension_tuple:
        replacements = tuple(extension.runtime_capability_replacements)
        if not replacements:
            continue
        extension_id = extension_declaration_id(extension)
        implementations.extend(
            _runtime_implementation(
                extension_id, replacement, factory_error=factory_error
            )
            for replacement in replacements
        )

    return profile, tuple(implementations)


def require_supported_resource_baseline(
    baseline_profile: ResolvedRuntimeProfile, *, product_label: str
) -> None:
    baseline_resources = resource_capability_profile(baseline_profile)
    extension_owned_slots = tuple(
        capability.slot.key
        for capability in baseline_resources.capabilities
        if any(selection.source == "extension" for selection in capability.selections)
    )
    if extension_owned_slots:
        raise ValueError(
            f"{product_label} does not support an initially mounted Extension-owned "
            "resource Provider: " + ", ".join(extension_owned_slots)
        )


def require_compatible_declaration_change(
    baseline_profile: ResolvedRuntimeProfile,
    candidate: ExtensionCapabilityDeclarationSnapshot,
    plan: ProductRuntimePlan,
    slot_permissions: Mapping[str, frozenset[str]],
) -> None:
    """Check whether refreshing Extension declarations requires a graph restart."""
    try:
        candidate_profile = _resolve_declarations(candidate, plan, slot_permissions)
    except Exception as error:
        changed_slots = _graph_slots_from_resolution_error(error)
        if changed_slots:
            groups = tuple(
                (capability_id, slots)
                for capability_id, slots in _GRAPH_SLOT_GROUPS
                if not slots.isdisjoint(changed_slots)
            )
            baseline_graph_input = _project_profile(
                baseline_profile, {slot for _, slots in groups for slot in slots}
            )
            raise ExtensionGraphProviderRestartRequiredError(
                capability_ids=tuple(capability_id for capability_id, _ in groups),
                changed_slots=changed_slots,
                baseline_fingerprint=runtime_profile_fingerprint(
                    baseline_graph_input.snapshot()
                ),
                candidate_fingerprint=candidate.fingerprint,
                candidate_fingerprint_kind="extension_declaration",
            ) from error
        raise
    baseline_side_question = _project_profile(baseline_profile, _SIDE_QUESTION_SLOTS)
    candidate_side_question = _project_profile(candidate_profile, _SIDE_QUESTION_SLOTS)
    if _has_extension_selection(baseline_side_question) or _has_extension_selection(
        candidate_side_question
    ):
        baseline_side_fingerprint = runtime_profile_fingerprint(
            baseline_side_question.snapshot()
        )
        candidate_side_fingerprint = runtime_profile_fingerprint(
            candidate_side_question.snapshot()
        )
        if baseline_side_fingerprint != candidate_side_fingerprint:
            raise ExtensionGraphProviderRestartRequiredError(
                capability_ids=("harness.session",),
                changed_slots=(SIDE_QUESTION_PROVIDER_SLOT.key,),
                baseline_fingerprint=baseline_side_fingerprint,
                candidate_fingerprint=candidate_side_fingerprint,
            )


def _resolve_declarations(
    snapshot: ExtensionCapabilityDeclarationSnapshot,
    plan: ProductRuntimePlan,
    slot_permissions: Mapping[str, frozenset[str]],
) -> ResolvedRuntimeProfile:
    declarations_by_extension: dict[
        str, list[ExtensionRuntimeCapabilityDeclaration]
    ] = {}
    for declaration in snapshot.declarations:
        declarations_by_extension.setdefault(declaration.extension_id, []).append(
            declaration
        )
    layers: list[RuntimeProfileLayer] = []
    grants: list[RuntimeProfileLayerGrant] = []
    allowed_slots = frozenset(slot_permissions)
    for extension_id in sorted(declarations_by_extension):
        declarations = declarations_by_extension[extension_id]
        permission_sets = {item.granted_permissions for item in declarations}
        if len(permission_sets) != 1:
            raise ValueError(
                "one Extension identity cannot carry conflicting capability grants"
            )
        layer_id = f"extension:{extension_id}"
        layers.append(
            RuntimeProfileLayer(
                source="extension",
                layer_id=layer_id,
                priority=max(item.priority for item in declarations),
                selections=tuple(
                    RuntimeCapabilitySelection(
                        slot=item.slot,
                        implementation=_implementation_id(
                            extension_id, item.slot, item.name
                        ),
                        implementation_version=item.implementation_version,
                        priority=item.priority,
                    )
                    for item in declarations
                ),
            )
        )
        grants.append(
            RuntimeProfileLayerGrant(
                source="extension",
                layer_id=layer_id,
                allowed_slots=allowed_slots,
                granted_permissions=frozenset(next(iter(permission_sets))),
            )
        )
    admission = RuntimeProfileAdmissionPolicy(
        grants=tuple(grants),
        slot_permissions=slot_permissions,
    ).admit(plan, layers)
    return RuntimeProfileResolver().resolve(
        plan,
        layers=admission.require_valid(),
    )


def _graph_slots_from_resolution_error(error: Exception) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                slot
                for item in getattr(error, "diagnostics", ())
                if isinstance((slot := getattr(item, "slot", None)), str)
                and slot in _GRAPH_SLOTS
            }
        )
    )


def _project_profile(
    profile: ResolvedRuntimeProfile, slots: Set[str]
) -> ResolvedRuntimeProfile:
    return ResolvedRuntimeProfile(
        product_id=profile.product_id,
        capabilities=tuple(
            capability
            for capability in profile.capabilities
            if capability.slot.key in slots
        ),
        schema_version=profile.schema_version,
    )


def _has_extension_selection(profile: ResolvedRuntimeProfile) -> bool:
    return any(
        selection.source == "extension"
        for capability in profile.capabilities
        for selection in capability.selections
    )


def _implementation_id(extension_id: str, slot: str, name: str) -> str:
    return f"extension:{extension_id}:{slot}:{name}"


def _runtime_implementation(
    extension_id: str,
    replacement: RegisteredRuntimeCapabilityReplacement,
    *,
    factory_error: str,
) -> RuntimeCapabilityImplementation:
    create = replacement.create
    dispose = replacement.dispose

    def create_provider_factory(
        _selection: RuntimeCapabilitySelection,
        _context: object | None,
    ) -> object:
        value = create()
        if not callable(getattr(value, "bind", None)):
            raise TypeError(factory_error)
        return value

    def dispose_provider_factory(
        value: object,
        _context: object | None,
    ) -> None:
        if dispose is None:
            return None
        return dispose(value)

    return RuntimeCapabilityImplementation(
        slot=replacement.slot,
        implementation=_implementation_id(
            extension_id, replacement.slot, replacement.name
        ),
        implementation_version=replacement.implementation_version,
        create=create_provider_factory,
        dispose=dispose_provider_factory if dispose is not None else None,
    )
