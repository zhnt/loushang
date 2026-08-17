from __future__ import annotations

from dataclasses import replace

from loushang.harness.contributions import (
    ContributionDescriptor,
    ContributionRegistry,
    ContributionType,
    DuplicateContributionKeyError,
    DuplicateExtensionSurfaceKeyError,
    ExtensionInventory,
    ExtensionSurfaceDescriptor,
    ExtensionSurfaceType,
)


def surfaces_from_loaded_extension(
    extension: object,
) -> tuple[ExtensionSurfaceDescriptor, ...]:
    extension_id = _extension_id(extension)
    source_path = getattr(extension, "entry_path", None) or getattr(
        extension, "source_path"
    )
    surfaces: list[ExtensionSurfaceDescriptor] = []

    manifest = getattr(extension, "manifest", None)
    if manifest is not None:
        surfaces.extend(
            ExtensionSurfaceDescriptor(
                type="command",
                name=command.name,
                extension_id=extension_id,
                source_path=source_path,
                metadata={"source": "manifest"},
            )
            for command in manifest.commands
        )
        surfaces.extend(
            ExtensionSurfaceDescriptor(
                type="tool",
                name=tool.name,
                extension_id=extension_id,
                source_path=source_path,
                metadata={"source": "manifest"},
            )
            for tool in manifest.tools
        )
        surfaces.extend(
            ExtensionSurfaceDescriptor(
                type="hook",
                name=hook.event,
                extension_id=extension_id,
                source_path=source_path,
                metadata={"source": "manifest", "kind": hook.kind},
            )
            for hook in manifest.hooks
        )

    surfaces.extend(
        ExtensionSurfaceDescriptor(
            type="command",
            name=name,
            extension_id=extension_id,
            source_path=source_path,
            metadata={"source": "runtime"},
        )
        for name in getattr(extension, "commands", {})
    )
    surfaces.extend(
        ExtensionSurfaceDescriptor(
            type="tool",
            name=tool.name,
            extension_id=extension_id,
            source_path=source_path,
            metadata={"source": "runtime"},
        )
        for tool in getattr(extension, "tool_definitions", ())
    )
    registrations = tuple(getattr(extension, "handler_registrations", ()))
    if registrations:
        surfaces.extend(
            ExtensionSurfaceDescriptor(
                type="hook",
                name=registration.event_name,
                extension_id=extension_id,
                source_path=source_path,
                priority=registration.priority,
                after=registration.after,
                before=registration.before,
                on_error=registration.on_error,
                metadata={
                    "source": "runtime",
                    "route_id": registration.local_route_id,
                },
            )
            for registration in registrations
        )
    else:
        surfaces.extend(
            ExtensionSurfaceDescriptor(
                type="hook",
                name=event_name,
                extension_id=extension_id,
                source_path=source_path,
                metadata={"source": "runtime"},
            )
            for event_name in getattr(extension, "hooks", {})
        )
    surfaces.extend(
        replace(
            contribution.descriptor,
            extension_id=extension_id,
            source_path=source_path,
        )
        for contribution in getattr(extension, "control_contributions", ())
    )
    surfaces.extend(
        ExtensionSurfaceDescriptor(
            type="runtime_capability",
            name=replacement.name,
            extension_id=extension_id,
            source_path=source_path,
            priority=replacement.priority,
            permission_requirements=(replacement.slot,),
            metadata={
                "source": "runtime",
                "slot": replacement.slot,
                "implementationVersion": replacement.implementation_version,
            },
        )
        for replacement in getattr(extension, "runtime_capability_replacements", ())
    )
    return tuple(surfaces)


def _extension_id(extension: object) -> str:
    manifest = getattr(extension, "manifest", None)
    if manifest is not None:
        return manifest.id
    return str(getattr(extension, "name"))


contributions_from_loaded_extension = surfaces_from_loaded_extension

__all__ = [
    "ContributionDescriptor",
    "ContributionRegistry",
    "ContributionType",
    "DuplicateContributionKeyError",
    "DuplicateExtensionSurfaceKeyError",
    "ExtensionInventory",
    "ExtensionSurfaceDescriptor",
    "ExtensionSurfaceType",
    "contributions_from_loaded_extension",
    "surfaces_from_loaded_extension",
]
