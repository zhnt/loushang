"""Fresh declared-package evidence must not scan unrelated installations."""

import importlib.metadata
import sys
from dataclasses import dataclass, replace
from importlib.abc import MetaPathFinder
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceResolver,
)
from tests.harness.resources.plugins.test_distribution_evidence import _FakeDistribution


@dataclass(frozen=True)
class DeclaredDistribution(_FakeDistribution):
    declared: str | None = "sample_pkg"

    def read_text(self, filename):
        if filename == "top_level.txt":
            return self.declared
        return super().read_text(filename)


def installation(tmp_path):
    path = tmp_path / "sample_pkg.py"
    path.write_text("", encoding="utf-8")
    return DeclaredDistribution(tmp_path, "sample-dist", "1.0", (Path(path.name),))


def test_default_declared_lookup_does_not_enumerate_unrelated_distributions(
    tmp_path, monkeypatch
):
    installed = installation(tmp_path)
    calls = []

    def discover(**kwargs):
        calls.append(kwargs)
        assert kwargs == {"name": "sample-dist"}, "unrelated global enumeration"
        return (installed,)

    monkeypatch.setattr(importlib.metadata, "distributions", discover)
    evidence = InstalledPythonDistributionEvidenceResolver().resolve("sample-dist")
    assert evidence.top_level_packages == ("sample_pkg",)
    assert calls == [{"name": "sample-dist"}]


@pytest.mark.parametrize("declared", [None, "", "  ", "not.valid"])
def test_missing_or_invalid_declaration_uses_original_global_reader(
    tmp_path, monkeypatch, declared
):
    installed = replace(installation(tmp_path), declared=declared)
    calls = []

    def discover(**kwargs):
        calls.append(kwargs)
        return (installed,)

    monkeypatch.setattr(importlib.metadata, "distributions", discover)
    evidence = InstalledPythonDistributionEvidenceResolver().resolve("sample-dist")
    assert {} in calls
    assert evidence.top_level_packages == (
        () if declared == "not.valid" else ("sample_pkg",)
    )


def test_all_candidate_versions_contribute_and_each_call_reads_fresh(
    tmp_path, monkeypatch
):
    installed = installation(tmp_path)
    candidates = [installed, replace(installed, version="2.0", declared="other_pkg")]
    monkeypatch.setattr(
        importlib.metadata, "distributions", lambda **kwargs: tuple(candidates)
    )
    resolver = InstalledPythonDistributionEvidenceResolver()
    assert resolver.resolve(
        "sample-dist", expected_version="1.0"
    ).top_level_packages == (
        "other_pkg",
        "sample_pkg",
    )
    candidates[1] = replace(candidates[1], declared="changed_pkg")
    assert resolver.resolve(
        "sample-dist", expected_version="1.0"
    ).top_level_packages == (
        "changed_pkg",
        "sample_pkg",
    )


def test_custom_mapping_reader_is_not_bypassed(tmp_path):
    installed = installation(tmp_path)
    calls = []

    def packages():
        calls.append(True)
        return {"custom_pkg": ["sample-dist"]}

    resolver = InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda name: (installed,),
        packages_distributions_reader=packages,
    )
    assert resolver.resolve("sample-dist").top_level_packages == ("custom_pkg",)
    assert calls == [True]


def test_custom_metadata_finder_retains_unfiltered_mapping_authority(
    tmp_path, monkeypatch
):
    installed = installation(tmp_path)
    calls = []

    class NamedOnlyFinder(MetaPathFinder):
        def find_distributions(self, context):
            calls.append(context.name)
            return (installed,) if context.name == "sample-dist" else ()

    monkeypatch.setattr(sys, "meta_path", [NamedOnlyFinder(), *sys.meta_path])
    evidence = InstalledPythonDistributionEvidenceResolver().resolve("sample-dist")
    assert evidence.top_level_packages == ()
    assert "sample-dist" in calls and None in calls


def test_custom_distributions_reader_alone_uses_global_mapping(tmp_path, monkeypatch):
    installed = installation(tmp_path)
    monkeypatch.setattr(importlib.metadata, "distributions", lambda **kwargs: ())
    resolver = InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda name: (installed,),
    )
    assert resolver.resolve("sample-dist").top_level_packages == ()


def test_custom_packages_reader_alone_is_authoritative(tmp_path, monkeypatch):
    installed = installation(tmp_path)
    monkeypatch.setattr(
        importlib.metadata, "distributions", lambda **kwargs: (installed,)
    )
    resolver = InstalledPythonDistributionEvidenceResolver(
        packages_distributions_reader=lambda: {"custom_pkg": ["sample-dist"]},
    )
    assert resolver.resolve("sample-dist").top_level_packages == ("custom_pkg",)
