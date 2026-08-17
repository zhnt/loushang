from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


def test_resource_diagnostic_preserves_neutral_provenance() -> None:
    from loushang.harness.resources.diagnostics import resource_diagnostic

    source_path = Path("/tmp/package/skills/review/SKILL.md")
    metadata: dict[str, object] = {"line": 2}
    diagnostic = resource_diagnostic(
        code="invalid_frontmatter",
        message="Frontmatter must be a mapping.",
        source_path=source_path,
        resource_id="review",
        resource_type="skill",
        source_kind="external_package",
        metadata=metadata,
    )
    metadata["line"] = 3

    assert diagnostic.source_path is source_path
    assert diagnostic.details["source_kind"] == "external_package"
    assert diagnostic.details["metadata"] == {"line": 2}


def test_resource_diagnostic_has_immutable_empty_metadata() -> None:
    from loushang.harness.resources.diagnostics import resource_diagnostic

    diagnostic = resource_diagnostic(
        code="missing_resource", message="Missing resource."
    )

    assert diagnostic.details == {}
    with pytest.raises(TypeError):
        diagnostic.details["path"] = "/tmp/missing"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        diagnostic.code = "changed"  # type: ignore[misc]
