"""Coding-owned admission adapter for externally variable runtime capabilities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from loushang.coding.product_plan import CODING_CAPABILITY_PLAN
from loushang.harness.capabilities import (
    CapabilityCompositionRuntime,
    bind_capability_composition_runtime,
)
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.manifest import ExtensionManifest
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

    def bind(self) -> CapabilityCompositionRuntime:
        return bind_capability_composition_runtime(
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

    layers: list[RuntimeProfileLayer] = []
    grants: list[RuntimeProfileLayerGrant] = []
    implementations: list[RuntimeCapabilityImplementation] = []

    for extension in extensions:
        replacements = tuple(extension.runtime_capability_replacements)
        if not replacements:
            continue
        extension_id = _extension_id(extension)
        layer_id = f"extension:{extension_id}"
        layer_priority = max(replacement.priority for replacement in replacements)
        layers.append(
            RuntimeProfileLayer(
                source="extension",
                layer_id=layer_id,
                priority=layer_priority,
                selections=tuple(
                    RuntimeCapabilitySelection(
                        slot=replacement.slot,
                        implementation=_implementation_id(
                            extension_id,
                            replacement,
                        ),
                        implementation_version=replacement.implementation_version,
                        priority=replacement.priority,
                    )
                    for replacement in replacements
                ),
            )
        )
        grants.append(
            RuntimeProfileLayerGrant(
                source="extension",
                layer_id=layer_id,
                allowed_slots=frozenset({SIDE_QUESTION_PROVIDER_SLOT.key}),
                granted_permissions=frozenset(
                    extension.policy.capabilities
                    if extension.policy is not None
                    else ()
                ),
            )
        )
        implementations.extend(
            _runtime_implementation(extension_id, replacement)
            for replacement in replacements
        )

    admission = RuntimeProfileAdmissionPolicy(
        grants=tuple(grants),
        slot_permissions={
            SIDE_QUESTION_PROVIDER_SLOT.key: frozenset(
                {SIDE_QUESTION_RUNTIME_PERMISSION}
            )
        },
    ).admit(CODING_CAPABILITY_PLAN, layers)
    profile = RuntimeProfileResolver().resolve(
        CODING_CAPABILITY_PLAN,
        layers=admission.require_valid(),
    )
    return CodingCapabilityProfileResolution(
        profile=profile,
        implementations=tuple(implementations),
    )


def bind_coding_capability_composition_runtime(
    extension_runtime: ExtensionRunner,
) -> CapabilityCompositionRuntime:
    """Bind Coding's final Session profile after Extension discovery."""

    return resolve_coding_capability_profile(extension_runtime.active_extensions).bind()


def bind_coding_side_question(
    extension_runtime: ExtensionRunner,
) -> LegacySideQuestionBinding:
    """Bind the final Extension-selected side-question factory for one Session."""

    return resolve_coding_capability_profile(
        extension_runtime.active_extensions
    ).bind_side_question()


def _extension_id(extension: LoadedExtension) -> str:
    manifest = extension.manifest
    if isinstance(manifest, ExtensionManifest):
        return manifest.id
    return extension.name


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
    "CodingCapabilityProfileResolution",
    "SIDE_QUESTION_RUNTIME_PERMISSION",
    "bind_coding_capability_composition_runtime",
    "bind_coding_side_question",
    "resolve_coding_capability_profile",
]
