"""Coding policy injected into shared diagnostics and observability runtimes."""

from __future__ import annotations

from collections.abc import Mapping
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
) -> dict[str, object]:
    import loushang
    import loushang.coding as loushang_coding

    return collect_profiled_runtime_identity(
        profile=CODING_RUNTIME_IDENTITY_PROFILE,
        package_module=loushang,
        related_modules={"coding": loushang_coding},
        cwd=cwd,
        argv0=argv0,
        env=env,
    )


def format_coding_runtime_identity_text(
    identity: Mapping[str, object],
) -> str:
    return format_profiled_runtime_identity_text(
        identity,
        profile=CODING_RUNTIME_IDENTITY_PROFILE,
    )


__all__ = [
    "CODING_RUNTIME_IDENTITY_PROFILE",
    "coding_diagnostic_source",
    "coding_runtime_identity",
    "format_coding_runtime_identity_text",
]
