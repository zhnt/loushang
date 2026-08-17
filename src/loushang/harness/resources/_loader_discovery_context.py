"""Context-file discovery for the resource loader pipeline."""

from __future__ import annotations

from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_types import _SOURCE_LABEL, _SOURCE_SCOPE
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceSourceKind,
)


def _discover_context_descriptors(
    start: Path,
    *,
    user_resource_roots: tuple[Path, ...],
    context_file_names: tuple[str, ...],
) -> tuple[
    list[PromptFragmentDescriptor],
    PromptFragmentDescriptor | None,
    list[DiagnosticDraft],
]:
    descriptors: list[PromptFragmentDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []

    for index, root in enumerate(user_resource_roots):
        if not root.is_dir():
            continue
        descriptor, read_diagnostics = _discover_context_descriptor_from_dir(
            root,
            source_kind="user_global",
            source_root_order=index,
            context_file_names=context_file_names,
        )
        diagnostics.extend(read_diagnostics)
        if descriptor is not None:
            descriptors.append(descriptor)

    project_descriptors: list[PromptFragmentDescriptor] = []
    for index, current in enumerate(reversed(_ancestor_dirs(start))):
        descriptor, read_diagnostics = _discover_context_descriptor_from_dir(
            current,
            source_kind="project_local",
            source_root_order=index,
            context_file_names=context_file_names,
        )
        diagnostics.extend(read_diagnostics)
        if descriptor is not None:
            project_descriptors.append(descriptor)
    descriptors.extend(project_descriptors)
    return descriptors, _nearest_context_descriptor(descriptors), diagnostics


def _ancestor_dirs(start: Path) -> list[Path]:
    current = start if start.is_dir() else start.parent
    dirs: list[Path] = []
    while True:
        dirs.append(current)
        if current.parent == current:
            return dirs
        current = current.parent


def _discover_context_descriptor_from_dir(
    root: Path,
    *,
    source_kind: ResourceSourceKind,
    source_root_order: int,
    context_file_names: tuple[str, ...],
) -> tuple[PromptFragmentDescriptor | None, list[DiagnosticDraft]]:
    for filename in context_file_names:
        candidate = root / filename
        if not candidate.is_file():
            continue
        text, diagnostics = _read_context_file(candidate)
        if text is None:
            return None, diagnostics
        return (
            PromptFragmentDescriptor(
                name=candidate.name,
                source_path=candidate,
                text=text,
                id=_context_descriptor_id(candidate.name, source_kind),
                canonical_name=candidate.name,
                prompt_kind=_context_prompt_kind(candidate.name),
                source_kind=source_kind,
                source_scope=_SOURCE_SCOPE[source_kind],
                source=_SOURCE_LABEL[source_kind],
                source_root=root,
                source_root_order=source_root_order,
            ),
            diagnostics,
        )
    return None, []


def _read_context_file(path: Path) -> tuple[str | None, list[DiagnosticDraft]]:
    try:
        return path.read_text(encoding="utf-8").strip(), []
    except OSError as exc:
        return (
            None,
            [
                resource_diagnostic(
                    code=_context_read_diagnostic_code(path.name),
                    message=f"Failed to read {path.name}: {exc}",
                    source_path=path,
                )
            ],
        )


def _context_prompt_kind(filename: str) -> str:
    return "agents_md" if filename.upper() == "AGENTS.MD" else "claude_md"


def _context_descriptor_id(filename: str, source_kind: ResourceSourceKind) -> str:
    source_prefix = "user" if source_kind == "user_global" else "project"
    context_name = (
        "agents" if _context_prompt_kind(filename) == "agents_md" else "claude"
    )
    return f"{source_prefix}.{context_name}"


def _context_read_diagnostic_code(filename: str) -> str:
    return (
        "unreadable_agents_file"
        if _context_prompt_kind(filename) == "agents_md"
        else "unreadable_claude_file"
    )


def _nearest_context_descriptor(
    descriptors: list[PromptFragmentDescriptor],
) -> PromptFragmentDescriptor | None:
    for descriptor in reversed(descriptors):
        if descriptor.source_kind == "project_local":
            return descriptor
    return descriptors[-1] if descriptors else None
