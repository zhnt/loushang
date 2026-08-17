from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_generic_and_extension_names_share_identity() -> None:
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

    assert ContributionDescriptor is ExtensionSurfaceDescriptor
    assert ContributionRegistry is ExtensionInventory
    assert ContributionType is ExtensionSurfaceType
    assert DuplicateContributionKeyError is DuplicateExtensionSurfaceKeyError


def test_contribution_descriptor_preserves_values() -> None:
    from loushang.harness.contributions import ContributionDescriptor
    from loushang.harness.diagnostics.types import DiagnosticDraft

    source_path = Path("/tmp/extensions/review/extension.py")
    diagnostic = DiagnosticDraft(
        code="inactive_surface", message="Surface is inactive."
    )
    descriptor = ContributionDescriptor(
        type="command",
        name="review",
        extension_id="acme.review",
        source_path=source_path,
        active=False,
        priority=20,
        permission_requirements=("filesystem",),
        diagnostics=(diagnostic,),
        metadata={"source": "manifest"},
    )

    assert descriptor.source_path is source_path
    assert descriptor.permission_requirements == ("filesystem",)
    assert descriptor.diagnostics == (diagnostic,)
    assert descriptor.metadata == {"source": "manifest"}
    with pytest.raises(FrozenInstanceError):
        descriptor.name = "changed"  # type: ignore[misc]


def test_contribution_descriptor_preserves_legacy_positional_field_order() -> None:
    from loushang.harness.contributions import ExtensionSurfaceDescriptor
    from loushang.harness.diagnostics.types import DiagnosticDraft

    source_path = Path("/tmp/legacy.py")
    diagnostic = DiagnosticDraft(code="legacy", message="legacy")
    descriptor = ExtensionSurfaceDescriptor(
        "tool",
        "lookup",
        "legacy.extension",
        source_path,
        False,
        7,
        ("filesystem",),
        (diagnostic,),
        {"source": "legacy"},
    )

    assert descriptor.permission_requirements == ("filesystem",)
    assert descriptor.diagnostics == (diagnostic,)
    assert descriptor.metadata == {"source": "legacy"}
    assert descriptor.after == ()
    assert descriptor.before == ()
    assert descriptor.on_error == "skip"


def test_contribution_registry_preserves_order_and_indexes() -> None:
    from loushang.harness.contributions import (
        ContributionDescriptor,
        ContributionRegistry,
    )

    tool = ContributionDescriptor(
        type="tool",
        name="lookup",
        extension_id="acme.review",
        source_path=Path("/tmp/extensions/review.py"),
    )
    command = ContributionDescriptor(
        type="command",
        name="review",
        extension_id="acme.review",
        source_path=Path("/tmp/extensions/review.py"),
    )
    other = ContributionDescriptor(
        type="tool",
        name="search",
        extension_id="acme.search",
        source_path=Path("/tmp/extensions/search.py"),
    )

    registry = ContributionRegistry.from_extensions(
        [
            SimpleNamespace(contributions=[tool, command]),
            SimpleNamespace(surfaces=[other]),
        ]
    )

    assert registry.all() == [tool, command, other]
    assert registry.by_type("tool") == [tool, other]
    assert registry.by_extension("acme.review") == [tool, command]
    assert registry.by_key("command", "review") == [command]
    assert registry.get("tool", "lookup") is tool

    registry.all().clear()
    assert registry.all() == [tool, command, other]


def test_contribution_registry_reports_duplicate_keys() -> None:
    from loushang.harness.contributions import (
        ContributionDescriptor,
        ContributionRegistry,
        DuplicateContributionKeyError,
    )

    first = ContributionDescriptor(
        type="command",
        name="review",
        extension_id="one",
        source_path=Path("/tmp/one.py"),
    )
    second = ContributionDescriptor(
        type="command",
        name="review",
        extension_id="two",
        source_path=Path("/tmp/two.py"),
    )
    registry = ContributionRegistry()
    registry.add(first)
    registry.add(second)

    assert registry.by_key("command", "review") == [first, second]
    with pytest.raises(DuplicateContributionKeyError) as raised:
        registry.get("command", "review")

    error = raised.value
    assert str(error) == "'Duplicate extension surface key: command:review'"
    assert error.surface_type == "command"
    assert error.contribution_type == "command"
    assert error.name == "review"
    assert error.surfaces == [first, second]
    assert error.contributions == [first, second]
