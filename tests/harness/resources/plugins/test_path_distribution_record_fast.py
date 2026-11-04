"""Wheel RECORD evidence remains fresh while avoiding duplicate path scans."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceError,
    InstalledPythonDistributionEvidenceResolver,
)


def _distribution(root: Path, record: str) -> importlib.metadata.PathDistribution:
    info = root / "sample_dist-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: sample-dist\nVersion: 1.0\n")
    (info / "RECORD").write_text(record)
    return importlib.metadata.PathDistribution(info)


def _resolver(
    installed: importlib.metadata.PathDistribution,
) -> InstalledPythonDistributionEvidenceResolver:
    return InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda _name: (installed,),
        packages_distributions_reader=lambda: {"sample_pkg": ["sample-dist"]},
    )


def _symlink(path: Path, target: Path) -> None:
    try:
        path.symlink_to(target)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable")
        raise


def test_wheel_record_resolves_only_existing_paths_without_files_property(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "sample_pkg.py"
    package.write_text("value = 1\n")
    alias = tmp_path / "alias.py"
    _symlink(alias, package)
    installed = _distribution(
        tmp_path,
        "sample_pkg.py,,\nalias.py,,\nmissing.py,,\n"
        "sample_dist-1.0.dist-info/METADATA,,\n",
    )
    monkeypatch.setattr(
        importlib.metadata.PathDistribution,
        "files",
        property(lambda _self: pytest.fail("wheel RECORD must avoid a second path scan")),
    )

    evidence = _resolver(installed).resolve("sample-dist")
    assert evidence.contains_distribution_path(package)
    assert evidence.contains_distribution_path(alias)
    assert not evidence.contains_distribution_path(tmp_path / "missing.py")
    assert evidence._recorded_paths.count(package.resolve()) == 1


def test_wheel_record_matches_existing_standard_files_for_quoted_names(
    tmp_path: Path,
) -> None:
    package = tmp_path / "sample,pkg.py"
    package.touch()
    alias = tmp_path / "alias.py"
    _symlink(alias, package)
    installed = _distribution(
        tmp_path,
        '"sample,pkg.py",sha256=YWJj,10\nalias.py,,\nmissing.py,,\n',
    )
    expected = tuple(
        sorted(
            {
                located.resolve()
                for path in installed.files or ()
                if (located := Path(installed.locate_file(path))).exists()
            },
            key=str,
        )
    )

    assert _resolver(installed).resolve("sample-dist")._recorded_paths == expected


def test_wheel_record_and_symlink_origins_are_fresh_across_resolutions(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.touch()
    second.touch()
    alias = tmp_path / "alias.py"
    _symlink(alias, first)
    installed = _distribution(tmp_path, "alias.py,,\n")
    resolver = _resolver(installed)

    old = resolver.resolve("sample-dist")
    alias.unlink()
    _symlink(alias, second)
    fresh = resolver.resolve("sample-dist")
    assert old.contains_distribution_path(first)
    assert not old.contains_distribution_path(alias)
    assert fresh.contains_distribution_path(second)

    (tmp_path / "sample_dist-1.0.dist-info" / "RECORD").write_text("first.py,,\n")
    changed = resolver.resolve("sample-dist")
    assert changed.contains_distribution_path(first)
    assert not changed.contains_distribution_path(second)


def test_invalid_wheel_record_keeps_origin_rejection(tmp_path: Path) -> None:
    (tmp_path / "sample_pkg.py").touch()
    installed = _distribution(tmp_path, "sample_pkg.py,,not-an-int\n")
    with pytest.raises(InstalledPythonDistributionEvidenceError) as error:
        _resolver(installed).resolve("sample-dist")
    assert error.value.code == "plugin_dependency_distribution_origin_unverifiable"
