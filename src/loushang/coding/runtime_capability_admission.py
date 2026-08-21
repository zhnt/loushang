"""Coding-owned admission adapter for externally variable runtime capabilities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from loushang.coding.product_plan import CODING_CAPABILITY_PLAN
from loushang.harness.capabilities import (
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
)
from loushang.harness.capabilities.composition_runtime import (
    RESOURCE_CAPABILITY_SLOT_KEYS,
    resource_capability_profile,
)
from loushang.harness.capabilities.effective_runtime import (
    runtime_profile_fingerprint,
)
from loushang.harness.extensions.agent import ExtensionRunner
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

SIDE_QUESTION_RUNTIME_PERMISSION = SIDE_QUESTION_PROVIDER_SLOT.key


@dataclass(frozen=True)
class CodingCapabilityProfileResolution:
    """Pure resolved profile plus the Product-approved executable factories."""

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


def resolve_coding_capability_profile(
    extensions: Iterable[LoadedExtension],
) -> CodingCapabilityProfileResolution:
    """Admit active Coding Extension replacements and resolve one final profile."""

    extension_tuple = tuple(extensions)
    declaration_snapshot = ExtensionCapabilityDeclarationSnapshot.from_extensions(
        extension_tuple
    )
    profile = _resolve_coding_declaration_snapshot(declaration_snapshot)
    implementations: list[RuntimeCapabilityImplementation] = []

    for extension in extension_tuple:
        replacements = tuple(extension.runtime_capability_replacements)
        if not replacements:
            continue
        extension_id = _extension_id(extension)
        implementations.extend(
            _runtime_implementation(extension_id, replacement)
            for replacement in replacements
        )

    return CodingCapabilityProfileResolution(
        profile=profile,
        implementations=tuple(implementations),
    )


@dataclass(frozen=True)
class CodingExtensionDeclarationPreflight:
    """Re-run Coding's pure admission before a live Extension generation swap."""

    baseline_profile: ResolvedRuntimeProfile

    def __post_init__(self) -> None:
        baseline_resources = resource_capability_profile(self.baseline_profile)
        extension_owned_slots = tuple(
            capability.slot.key
            for capability in baseline_resources.capabilities
            if any(
                selection.source == "extension" for selection in capability.selections
            )
        )
        if extension_owned_slots:
            raise ValueError(
                "Coding does not support an initially mounted Extension-owned "
                "resource Provider: " + ", ".join(extension_owned_slots)
            )

    def __call__(self, candidate: ExtensionCapabilityDeclarationSnapshot) -> None:
        try:
            candidate_profile = _resolve_coding_declaration_snapshot(candidate)
        except Exception as error:
            changed_slots = _graph_slots_from_resolution_error(error)
            if changed_slots:
                baseline_graph_input = _graph_profile_for_slots(
                    self.baseline_profile,
                    changed_slots,
                )
                raise ExtensionGraphProviderRestartRequiredError(
                    capability_ids=_graph_capability_ids(changed_slots),
                    changed_slots=changed_slots,
                    baseline_fingerprint=runtime_profile_fingerprint(
                        baseline_graph_input.snapshot()
                    ),
                    candidate_fingerprint=candidate.fingerprint,
                    candidate_fingerprint_kind="extension_declaration",
                ) from error
            raise
        baseline_side_question = _side_question_profile(self.baseline_profile)
        candidate_side_question = _side_question_profile(candidate_profile)
        if (
            _has_extension_selection(baseline_side_question)
            or _has_extension_selection(candidate_side_question)
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


def _resolve_coding_declaration_snapshot(
    snapshot: ExtensionCapabilityDeclarationSnapshot,
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
                        implementation=(
                            f"extension:{extension_id}:{item.slot}:{item.name}"
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
                allowed_slots=frozenset({SIDE_QUESTION_PROVIDER_SLOT.key}),
                granted_permissions=frozenset(next(iter(permission_sets))),
            )
        )
    admission = RuntimeProfileAdmissionPolicy(
        grants=tuple(grants),
        slot_permissions={
            SIDE_QUESTION_PROVIDER_SLOT.key: frozenset(
                {SIDE_QUESTION_RUNTIME_PERMISSION}
            )
        },
    ).admit(CODING_CAPABILITY_PLAN, layers)
    return RuntimeProfileResolver().resolve(
        CODING_CAPABILITY_PLAN,
        layers=admission.require_valid(),
    )


def _graph_slots_from_resolution_error(error: Exception) -> tuple[str, ...]:
    diagnostics = getattr(error, "diagnostics", ())
    return tuple(
        sorted(
            {
                slot
                for item in diagnostics
                if isinstance((slot := getattr(item, "slot", None)), str)
                and slot
                in {
                    *RESOURCE_CAPABILITY_SLOT_KEYS,
                    SIDE_QUESTION_PROVIDER_SLOT.key,
                }
            }
        )
    )


def _graph_capability_ids(changed_slots: tuple[str, ...]) -> tuple[str, ...]:
    capability_ids: list[str] = []
    if any(slot in RESOURCE_CAPABILITY_SLOT_KEYS for slot in changed_slots):
        capability_ids.append("harness.resources")
    if SIDE_QUESTION_PROVIDER_SLOT.key in changed_slots:
        capability_ids.append("harness.session")
    return tuple(capability_ids)


def _graph_profile_for_slots(
    profile: ResolvedRuntimeProfile,
    changed_slots: tuple[str, ...],
) -> ResolvedRuntimeProfile:
    graph_slots: set[str] = set()
    if any(slot in RESOURCE_CAPABILITY_SLOT_KEYS for slot in changed_slots):
        graph_slots.update(RESOURCE_CAPABILITY_SLOT_KEYS)
    if SIDE_QUESTION_PROVIDER_SLOT.key in changed_slots:
        graph_slots.add(SIDE_QUESTION_PROVIDER_SLOT.key)
    return ResolvedRuntimeProfile(
        product_id=profile.product_id,
        capabilities=tuple(
            capability
            for capability in profile.capabilities
            if capability.slot.key in graph_slots
        ),
        schema_version=profile.schema_version,
    )


def _side_question_profile(
    profile: ResolvedRuntimeProfile,
) -> ResolvedRuntimeProfile:
    return ResolvedRuntimeProfile(
        product_id=profile.product_id,
        capabilities=tuple(
            capability
            for capability in profile.capabilities
            if capability.slot.key == SIDE_QUESTION_PROVIDER_SLOT.key
        ),
        schema_version=profile.schema_version,
    )


def _has_extension_selection(profile: ResolvedRuntimeProfile) -> bool:
    return any(
        selection.source == "extension"
        for capability in profile.capabilities
        for selection in capability.selections
    )


def bind_coding_side_question(
    extension_runtime: ExtensionRunner,
) -> LegacySideQuestionBinding:
    """Bind the final Extension-selected side-question factory for one Session."""

    return resolve_coding_capability_profile(
        extension_runtime.active_extensions
    ).bind_side_question()


def _extension_id(extension: LoadedExtension) -> str:
    return extension_declaration_id(extension)


def _implementation_id(
    extension_id: str,
    replacement: RegisteredRuntimeCapabilityReplacement,
) -> str:
    return f"extension:{extension_id}:{replacement.slot}:{replacement.name}"


def _runtime_implementation(
    extension_id: str,
    replacement: RegisteredRuntimeCapabilityReplacement,
) -> RuntimeCapabilityImplementation:
    create = replacement.create
    dispose = replacement.dispose

    def create_provider_factory(
        _selection: RuntimeCapabilitySelection,
        _context: object | None,
    ) -> object:
        value = create()
        if not callable(getattr(value, "bind", None)):
            raise TypeError(
                "Extension side-question replacement must create a Provider factory"
            )
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
        implementation=_implementation_id(extension_id, replacement),
        implementation_version=replacement.implementation_version,
        create=create_provider_factory,
        dispose=dispose_provider_factory if dispose is not None else None,
    )


__all__ = [
    "CodingExtensionDeclarationPreflight",
    "CodingCapabilityProfileResolution",
    "SIDE_QUESTION_RUNTIME_PERMISSION",
    "bind_coding_side_question",
    "resolve_coding_capability_profile",
]
