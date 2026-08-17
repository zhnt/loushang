from __future__ import annotations

from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_package_policy import (
    _count_package_descriptors,
    _count_package_diagnostics,
    _filter_package_descriptors,
    _normalize_package_roots,
    _normalize_package_source_filters,
    _package_root_diagnostic,
)
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.types import PromptFragmentDescriptor


def _prompt(root: Path, filename: str) -> PromptFragmentDescriptor:
    return PromptFragmentDescriptor(
        name=Path(filename).stem,
        source_path=root / "prompts" / filename,
        text=filename,
        id=filename,
        canonical_name=filename,
        source_kind="external_package",
        source_scope="package",
        source_root=root,
    )


def test_package_policy_normalizes_roots_and_filter_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = PackageSourceConfig(source="packages/review")

    roots = _normalize_package_roots(("packages/review", Path("packages/debug")))
    filters = _normalize_package_source_filters({"packages/review": config})

    assert roots == (
        (tmp_path / "packages" / "review").resolve(),
        (tmp_path / "packages" / "debug").resolve(),
    )
    assert filters == {(tmp_path / "packages" / "review").resolve(): config}
    assert _normalize_package_roots(None) == ()
    assert _normalize_package_source_filters(None) == {}


def test_package_policy_applies_include_and_override_patterns(tmp_path: Path) -> None:
    root = tmp_path / "review-pack"
    review = _prompt(root, "review.md")
    debug = _prompt(root, "debug.md")
    descriptors = [review, debug]

    assert _filter_package_descriptors(
        descriptors,
        root=root,
        patterns=("prompts/*.md",),
    ) == descriptors
    assert _filter_package_descriptors(
        descriptors,
        root=root,
        patterns=("*.md", "!debug.md", "+debug.md", "-review.md"),
    ) == [debug]
    assert _filter_package_descriptors(
        descriptors,
        root=root,
        patterns=(),
    ) == []
    assert _filter_package_descriptors(
        descriptors,
        root=root,
        patterns=None,
    ) == descriptors


def test_package_policy_counts_only_owned_descriptors_and_diagnostics(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "review-pack").resolve()
    inside = _prompt(root, "review.md")
    outside = _prompt(tmp_path / "other-pack", "debug.md")
    inside_diagnostic = DiagnosticDraft(
        code="inside",
        message="inside",
        source_path=root / "extensions" / "README.txt",
    )
    root_diagnostic = _package_root_diagnostic(
        "empty_package_root",
        "Package root contains no loadable resources.",
        root,
    )
    outside_diagnostic = DiagnosticDraft(
        code="outside",
        message="outside",
        source_path=tmp_path / "other-pack" / "README.txt",
    )
    unscoped_diagnostic = DiagnosticDraft(code="unscoped", message="unscoped")

    assert _count_package_descriptors((inside, outside), root) == 1
    assert (
        _count_package_diagnostics(
            (
                inside_diagnostic,
                root_diagnostic,
                outside_diagnostic,
                unscoped_diagnostic,
            ),
            root,
        )
        == 2
    )
    assert root_diagnostic.source_path == root
    assert root_diagnostic.details == {
        "resource_type": "package",
        "source_kind": "external_package",
        "metadata": {"package_root": str(root)},
    }
