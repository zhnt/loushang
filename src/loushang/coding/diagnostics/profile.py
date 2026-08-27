"""Coding policy injected into shared diagnostics and observability runtimes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from loushang.foundation.observability.identity import (
    RuntimeIdentityProfile,
    collect_profiled_runtime_identity,
    format_profiled_runtime_identity_text,
)
from loushang.foundation.observability.records import ProblemRecord
from loushang.harness.diagnostics.observability_bridge import (
    diagnostic_source_for_problem,
)
from loushang.harness.diagnostics.runtime_provenance import (
    RuntimeProvenanceContributor,
    RuntimeProvenanceScope,
    StaticRuntimeProvenanceContributor,
    compose_runtime_provenance,
)

CODING_RUNTIME_IDENTITY_PROFILE = RuntimeIdentityProfile(
    package_name="loushang",
    executable_name="loushang",
    title="loushang source info",
    module_file_field="loushang_module_file",
    related_module_file_fields={"coding": "coding_module_file"},
)


def coding_diagnostic_source(record: ProblemRecord):
    if record.source == "config":
        return "model"
    return diagnostic_source_for_problem(record)


def coding_runtime_identity(
    *,
    cwd: str | Path | None = None,
    argv0: str | None = None,
    env: Mapping[str, str] | None = None,
    provenance_scope: RuntimeProvenanceScope = "installation",
    contributors: Sequence[RuntimeProvenanceContributor] = (),
) -> dict[str, object]:
    import loushang
    import loushang.coding as loushang_coding
    import loushang.tui as loushang_tui
    from loushang.foundation.observability.identity import module_file_path
    from loushang.tui.renderer_contract import (
        TUI_RENDERER_CONTRACT_VERSION,
        TUI_RENDERER_ID,
    )

    host_identity = collect_profiled_runtime_identity(
        profile=CODING_RUNTIME_IDENTITY_PROFILE,
        package_module=loushang,
        related_modules={"coding": loushang_coding},
        cwd=cwd,
        argv0=argv0,
        env=env,
    )
    bundled_tui = StaticRuntimeProvenanceContributor(
        component_id=TUI_RENDERER_ID,
        kind="renderer",
        installation_details={
            "availability": "bundled",
            "contract_version": TUI_RENDERER_CONTRACT_VERSION,
            "module_file": module_file_path(loushang_tui),
        },
    )
    return compose_runtime_provenance(
        host_identity,
        contributors=(bundled_tui, *contributors),
        scope=provenance_scope,
    )


def format_coding_runtime_identity_text(
    identity: Mapping[str, object],
) -> str:
    text = format_profiled_runtime_identity_text(
        identity,
        profile=CODING_RUNTIME_IDENTITY_PROFILE,
    )
    lines = [text]
    for key in (
        "loushang_module_file",
        "coding_module_file",
        "provenance_schema_version",
        "provenance_scope",
    ):
        value = identity.get(key)
        lines.append(f"{key}: {'<unknown>' if value is None or value == '' else value}")
    lines.extend(_format_component_lines(identity))
    return "\n".join(lines)


def format_coding_runtime_provenance_text(
    identity: Mapping[str, object],
) -> str:
    lines = ["Runtime provenance:"]
    for key in (
        "package_version",
        "entrypoint",
        "python_executable",
        "module_file",
        "install_mode",
        "launch_mode",
        "source_git_commit",
        "source_git_dirty",
        "provenance_scope",
    ):
        value = identity.get(key)
        lines.append(f"{key}: {'<unknown>' if value is None or value == '' else value}")
    lines.extend(_format_component_lines(identity))
    return "\n".join(lines)


def _format_component_lines(identity: Mapping[str, object]) -> list[str]:
    lines = ["components:"]
    components = identity.get("components")
    if not isinstance(components, Mapping) or not components:
        return [*lines, "  <none>"]
    for component_id in sorted(str(key) for key in components):
        component = components.get(component_id)
        if not isinstance(component, Mapping):
            continue
        lines.append(f"  {component_id}:")
        for key in sorted(str(key) for key in component):
            value = component.get(key)
            lines.append(
                f"    {key}: "
                f"{'<unknown>' if value is None or value == '' else value}"
            )
    return lines


__all__ = [
    "CODING_RUNTIME_IDENTITY_PROFILE",
    "coding_diagnostic_source",
    "coding_runtime_identity",
    "format_coding_runtime_identity_text",
    "format_coding_runtime_provenance_text",
]
