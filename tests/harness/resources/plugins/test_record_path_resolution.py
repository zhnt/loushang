"""RECORD batching preserves the existing origin snapshot and fresh later reads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceResolver,
)
from tests.harness.resources.plugins.test_distribution_evidence import _FakeDistribution


def resolver(root, paths):
    distribution = _FakeDistribution(root, "sample", "1", tuple(paths))
    return InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda _: (distribution,),
        packages_distributions_reader=lambda: {"sample": ["sample"]},
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX lexical fast path only")
def test_plain_record_paths_do_not_repeat_full_ancestor_resolution(
    tmp_path, monkeypatch
):
    tmp_path = tmp_path.resolve()
    directory = tmp_path / "a" / "b" / "sample"
    directory.mkdir(parents=True)
    paths = [directory / f"module_{index}.py" for index in range(20)]
    for path in paths:
        path.touch()
    expected = tuple(sorted((path.resolve() for path in paths), key=str))
    calls = []
    original = Path.resolve

    def traced(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", traced)
    value = resolver(tmp_path, paths).resolve("sample")
    assert value._recorded_paths == expected
    assert len(calls) < len(paths) // 2


def symlink(path, target, *, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable")
        raise


@pytest.mark.parametrize(
    "kind", ["leaf", "parent", "parent-dotdot", "missing", "nondirectory"]
)
def test_complex_paths_keep_pathlib_resolve_semantics(tmp_path, kind):
    actual = tmp_path / "actual"
    actual.mkdir()
    target = actual / "item.py"
    target.touch()
    if kind == "leaf":
        path = tmp_path / "alias.py"
        symlink(path, target)
    elif kind in {"parent", "parent-dotdot"}:
        parent = tmp_path / "alias"
        symlink(parent, actual, directory=True)
        path = parent / ("../item.py" if kind == "parent-dotdot" else "item.py")
    elif kind == "missing":
        path = tmp_path / "missing" / "item.py"
    else:
        path = target / "child.py"
    expected = path.resolve()
    value = resolver(tmp_path, [target, path]).resolve("sample")
    assert value._recorded_paths == tuple(sorted({target.resolve(), expected}, key=str))


def test_origin_is_fresh_across_resolutions_and_use(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "mod.py").touch()
    (second / "mod.py").touch()
    alias = tmp_path / "sample"
    symlink(alias, first, directory=True)
    source = resolver(tmp_path, [alias / "mod.py"])
    old = source.resolve("sample")
    alias.unlink()
    symlink(alias, second, directory=True)
    assert not old.contains_distribution_path(alias / "mod.py")
    new = source.resolve("sample")
    assert new.contains_distribution_path(alias / "mod.py")
    assert new._recorded_paths != old._recorded_paths


def test_recorded_missing_path_is_retained_but_not_usable(tmp_path):
    path = tmp_path / "missing.py"
    evidence = resolver(tmp_path, [path]).resolve("sample")
    assert evidence._recorded_paths == (path.resolve(),)
    assert not evidence.contains_distribution_path(path)


def test_locator_replaces_higher_ancestor_without_changing_descendant_inode(tmp_path):
    tmp_path = tmp_path.resolve()
    parent = tmp_path / "a"
    directory = parent / "b"
    directory.mkdir(parents=True)
    (directory / "one.py").touch()
    (directory / "two.py").touch()
    moved = tmp_path / "moved"

    class MovingDistribution(_FakeDistribution):
        def locate_file(self, item):
            if str(item) == "two.py":
                parent.rename(moved)
                symlink(parent, moved, directory=True)
            return directory / item

    distribution = MovingDistribution(
        tmp_path, "sample", "1", (Path("one.py"), Path("two.py"))
    )
    source = InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda _: (distribution,),
        packages_distributions_reader=lambda: {"sample": ["sample"]},
    )
    evidence = source.resolve("sample")
    assert set(evidence._recorded_paths) == {
        directory / "one.py",
        moved / "b" / "two.py",
    }


def test_relative_locator_and_duplicate_records_preserve_resolution(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    path = Path("sample") / "mod.py"
    path.parent.mkdir()
    path.touch()
    source = resolver(Path("."), [path, path])
    evidence = source.resolve("sample")
    assert evidence._recorded_paths == (path.resolve(),)
    assert evidence.allows_import_origin("sample", (path.parent,))
