from __future__ import annotations

from pathlib import Path


def test_coding_source_info_paths_preserve_harness_owner_identity() -> None:
    from loushang.harness.extensions.agent import SourceInfo as ExtensionSourceInfo
    from loushang.harness.resources.source import SourceInfo as HarnessSourceInfo
    from loushang.harness.resources.source import create_source_info

    assert ExtensionSourceInfo is HarnessSourceInfo
    assert HarnessSourceInfo.__module__ == "loushang.harness.resources.source"

    command_info = create_source_info(Path("/tmp/project/prompts/review.md"))
    extension_info = ExtensionSourceInfo(path=Path("/tmp/project/extensions/demo.py"))

    assert command_info.path == "/tmp/project/prompts/review.md"
    assert extension_info.path == Path("/tmp/project/extensions/demo.py")


def test_resource_diagnostic_factory_returns_canonical_diagnostic_draft() -> None:
    from loushang.harness.diagnostics import DiagnosticDraft as ExportedDiagnosticDraft
    from loushang.harness.diagnostics.types import DiagnosticDraft
    from loushang.harness.resources.diagnostics import resource_diagnostic

    draft = resource_diagnostic(code="invalid_skill", message="Invalid skill.")

    assert ExportedDiagnosticDraft is DiagnosticDraft
    assert type(draft) is DiagnosticDraft
    assert DiagnosticDraft.__module__ == "loushang.harness.diagnostics.types"
