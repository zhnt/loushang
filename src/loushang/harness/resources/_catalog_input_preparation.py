"""Normalize configured Resource sources into one Catalog input receipt."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from loushang.harness.resources._catalog_input_receipt import (
    CatalogPluginPackageInput,
    ContextFileInputFact,
    LegacyPackageResourceCandidateFact,
    LegacyPackageResourceKind,
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._loader_discovery import (
    _apply_resource_switches,
    _discover_external_package_resources,
)
from loushang.harness.resources._safe_files import (
    ContainedFileCaptureError,
    capture_contained_regular_file,
)
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    SkillDescriptor,
    ThemeDescriptor,
)

_MAX_CONTEXT_PREVIEW_BYTES = 8 * 1024 * 1024


def prepare_resource_catalog_input_receipt(
    *,
    cwd: Path,
    project_resource_root: Path | None,
    package_mounts: tuple[PackageResourceMount, ...],
    catalog_plugin_package_inputs: tuple[CatalogPluginPackageInput, ...],
    user_resource_roots: tuple[Path, ...],
    explicit_user_resource_roots: Collection[Path],
    additional_extension_paths: tuple[Path, ...],
    additional_skill_paths: tuple[Path, ...],
    additional_prompt_template_paths: tuple[Path, ...],
    additional_theme_paths: tuple[Path, ...],
    no_extensions: bool,
    no_skills: bool,
    no_prompt_templates: bool,
    no_themes: bool,
    no_context_files: bool,
    built_in_resource_packages: tuple[str, ...],
    context_file_names: tuple[str, ...],
    work_probe: Callable[[], None] | None = None,
    package_text_byte_budget: int | None = None,
) -> ResourceCatalogInputReceipt:
    """Observe only source facts; never select or publish effective Resources."""

    target = Path(cwd)
    if work_probe is not None:
        work_probe()
    project_context_roots = (
        () if no_context_files else _project_context_roots(target)
    )
    resolved_project_root = project_resource_root or _project_root_from_context(
        target,
        roots=project_context_roots,
        context_file_names=context_file_names,
        work_probe=work_probe,
    )
    external = _apply_resource_switches(
        _discover_external_package_resources(
            package_mounts, work_probe=work_probe, max_text_bytes=package_text_byte_budget,
        ),
        no_prompts=no_prompt_templates,
        no_skills=no_skills,
        no_extensions=no_extensions,
        no_themes=no_themes,
    )
    if work_probe is not None:
        work_probe()
    return ResourceCatalogInputReceipt(
        cwd=target,
        project_resource_root=resolved_project_root,
        project_context_roots=project_context_roots,
        package_mounts=package_mounts,
        package_resource_candidates=_package_resource_candidate_facts(external),
        package_diagnostic_codes=tuple(
            diagnostic.code for diagnostic in external.diagnostics
        ),
        user_resource_roots=user_resource_roots,
        explicit_user_resource_roots=frozenset(explicit_user_resource_roots),
        additional_extension_paths=additional_extension_paths,
        additional_skill_paths=additional_skill_paths,
        additional_prompt_template_paths=additional_prompt_template_paths,
        additional_theme_paths=additional_theme_paths,
        no_extensions=no_extensions,
        no_skills=no_skills,
        no_prompt_templates=no_prompt_templates,
        no_themes=no_themes,
        no_context_files=no_context_files,
        built_in_resource_packages=built_in_resource_packages,
        context_file_names=context_file_names,
        catalog_plugin_package_inputs=catalog_plugin_package_inputs,
        context_file_facts=(
            () if no_context_files else _observe_context_file_facts(
                roots=(*project_context_roots, *user_resource_roots),
                filenames=context_file_names,
                work_probe=work_probe,
            )
        ),
    )


def _observe_context_file_facts(
    *, roots: tuple[Path, ...], filenames: tuple[str, ...],
    work_probe: Callable[[], None] | None = None,
) -> tuple[ContextFileInputFact, ...]:
    """Hash candidate context files without choosing precedence or authority."""

    remaining = _MAX_CONTEXT_PREVIEW_BYTES
    facts: list[ContextFileInputFact] = []
    for root in dict.fromkeys(roots):
        if work_probe is not None:
            work_probe()
        try:
            root_metadata = root.lstat()
            root_available = stat.S_ISDIR(root_metadata.st_mode)
        except OSError:
            root_available = False
        for filename in filenames:
            if work_probe is not None:
                work_probe()
            if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
                raise ValueError("Resource Catalog context filename is invalid")
            if not root_available:
                facts.append(ContextFileInputFact(root, filename, "unavailable"))
                continue
            try:
                metadata = (root / filename).lstat()
            except FileNotFoundError:
                facts.append(ContextFileInputFact(root, filename, "absent"))
                continue
            except OSError:
                facts.append(ContextFileInputFact(root, filename, "unavailable"))
                continue
            if not stat.S_ISREG(metadata.st_mode) or remaining == 0:
                facts.append(ContextFileInputFact(root, filename, "unavailable"))
                continue
            try:
                capture_root = root.parent if root.parent != root else root
                relative_path = (
                    f"{root.name}/{filename}"
                    if capture_root != root else filename
                )
                captured = capture_contained_regular_file(
                    capture_root, relative_path, max_bytes=remaining,
                    read_probe=work_probe,
                )
                root_after = root.lstat()
                file_after = (root / filename).lstat()
            except (ContainedFileCaptureError, OSError):
                facts.append(ContextFileInputFact(root, filename, "unavailable"))
                continue
            if (
                (root_after.st_dev, root_after.st_ino)
                != (root_metadata.st_dev, root_metadata.st_ino)
                or not stat.S_ISDIR(root_after.st_mode)
                or (file_after.st_dev, file_after.st_ino)
                != (captured.device, captured.inode)
                or not stat.S_ISREG(file_after.st_mode)
            ):
                facts.append(ContextFileInputFact(root, filename, "unavailable"))
                continue
            remaining -= len(captured.body)
            facts.append(ContextFileInputFact(
                root, filename, "file",
                content_digest=hashlib.sha256(captured.body).hexdigest(),
                content_length=len(captured.body),
            ))
    return tuple(facts)


def _project_context_roots(start: Path) -> tuple[Path, ...]:
    current = start if start.is_dir() else start.parent
    roots: list[Path] = []
    while True:
        roots.append(current)
        if current.parent == current:
            return tuple(reversed(roots))
        current = current.parent


def _project_root_from_context(
    target: Path,
    *,
    roots: tuple[Path, ...],
    context_file_names: tuple[str, ...],
    work_probe: Callable[[], None] | None = None,
) -> Path:
    matching: list[Path] = []
    for root in roots:
        for filename in context_file_names:
            if work_probe is not None:
                work_probe()
            if (root / filename).is_file():
                matching.append(root)
                break
    if matching:
        return matching[-1]
    return target if target.is_dir() else target.parent


def _package_resource_candidate_facts(
    discovery: object,
) -> tuple[LegacyPackageResourceCandidateFact, ...]:
    return (
        *_package_resource_facts_for("prompt", getattr(discovery, "prompts")),
        *_package_resource_facts_for("skill", getattr(discovery, "skills")),
        *_package_resource_facts_for("extension", getattr(discovery, "extensions")),
        *_package_resource_facts_for("theme", getattr(discovery, "themes")),
    )


def _package_resource_facts_for(
    resource_kind: LegacyPackageResourceKind,
    descriptors: Sequence[
        PromptFragmentDescriptor
        | SkillDescriptor
        | ExtensionDescriptor
        | ThemeDescriptor
    ],
) -> tuple[LegacyPackageResourceCandidateFact, ...]:
    return tuple(
        LegacyPackageResourceCandidateFact(
            resource_kind=resource_kind,
            source_path=descriptor.source_path,
            source_root_order=descriptor.source_root_order,
            package_content_digest=(
                descriptor.revision_ref.content_digest
                if descriptor.revision_ref is not None
                else None
            ),
        )
        for descriptor in descriptors
    )


__all__ = ["prepare_resource_catalog_input_receipt"]
