from __future__ import annotations

from pathlib import Path
from typing import Any

from loushang.harness.resources.loader import (
    DEFAULT_CONTEXT_FILE_NAMES,
    ProfiledResourceLoader,
    ResourceLoaderProfile,
)
from loushang.harness.resources.packages.catalog import (
    summarize_profiled_package_resources,
)
from loushang.harness.resources.packages.materializer import (
    PackageMaterializer,
    PackageSourcePolicy,
)
from loushang.harness.resources.packages.projection import (
    collect_projected_package_entries,
)
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.types import PackageResourceSummary, ResourceBundle

from .plugin_dependency_grants import (
    CoDistributedPluginDependencyGrantResolver,
    coding_arch_default_plugin_root,
    coding_lsp_default_plugin_root,
    coding_plugin_distribution_evidence_resolver,
)

BUILT_IN_RESOURCE_PACKAGE = "loushang.coding.resources"
CODING_CONTEXT_FILE_NAMES = (*DEFAULT_CONTEXT_FILE_NAMES, "CLAUDE.md", "CLAUDE.MD")


def _assemble_coding_system_prompt(
    base_prompt: str | None,
    resource_bundle: ResourceBundle,
) -> str | None:
    from loushang.coding.prompt import assemble_system_prompt

    system_prompt = assemble_system_prompt(
        base_prompt=base_prompt,
        resource_bundle=resource_bundle,
    )
    return system_prompt or None


CODING_RESOURCE_PROFILE = ResourceLoaderProfile(
    built_in_resource_packages=(BUILT_IN_RESOURCE_PACKAGE,),
    context_file_names=CODING_CONTEXT_FILE_NAMES,
    user_resource_roots=(),
    project_resource_mode="legacy",
    system_prompt_assembler=_assemble_coding_system_prompt,
)


class CodingResourceLoader(ProfiledResourceLoader):
    """Shared resource loader bound to Coding content and prompt semantics."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, profile=CODING_RESOURCE_PROFILE, **kwargs)


class CodingPackageMaterializer(PackageMaterializer):
    """Harness package materializer with Coding's package-security policy."""

    def __init__(
        self,
        *,
        security_policy: PackageSourcePolicy | None = None,
        **kwargs: Any,
    ) -> None:
        if security_policy is None:
            from loushang.harness.resources.packages.security import (
                PackageSecurityPolicy,
            )

            security_policy = PackageSecurityPolicy()
        kwargs.setdefault(
            "co_distributed_dependency_grant_resolver",
            CoDistributedPluginDependencyGrantResolver(
                coding_lsp_source=coding_lsp_default_plugin_root(),
                coding_arch_source=coding_arch_default_plugin_root(),
            ),
        )
        kwargs.setdefault(
            "installed_distribution_evidence_resolver",
            coding_plugin_distribution_evidence_resolver(),
        )
        super().__init__(
            security_policy=security_policy,
            **kwargs,
        )


def summarize_coding_package_root(
    package_root: Path,
    cwd: Path,
    package_source: PackageSourceConfig | None,
) -> PackageResourceSummary:
    """Summarize package resources with Coding's loader profile."""

    return summarize_profiled_package_resources(
        package_root,
        cwd,
        package_source,
        profile=CODING_RESOURCE_PROFILE,
    )


def collect_coding_package_entries(**kwargs: Any) -> list[dict[str, object]]:
    """Collect projected package entries with Coding's resource profile."""

    return collect_projected_package_entries(
        **kwargs,
        summary_provider=summarize_coding_package_root,
    )


__all__ = [
    "BUILT_IN_RESOURCE_PACKAGE",
    "CODING_CONTEXT_FILE_NAMES",
    "CODING_RESOURCE_PROFILE",
    "CodingPackageMaterializer",
    "CodingResourceLoader",
    "collect_coding_package_entries",
    "summarize_coding_package_root",
]
