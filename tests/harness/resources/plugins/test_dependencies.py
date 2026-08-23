from __future__ import annotations

import pytest

from loushang.harness.resources.plugins.dependencies import (
    PLUGIN_DEPENDENCY_LOCK_FORMAT,
    PluginDependencyClosureLock,
    lock_plugin_dependency_closure,
)


def test_dependency_closure_lock_is_canonical_and_roundtrips() -> None:
    content_digest = "a" * 64

    lock = lock_plugin_dependency_closure(
        package_content_digest=content_digest,
        installed_distributions=("Zed_Pkg==2.0", "alpha.pkg==1.0"),
    )
    reordered = lock_plugin_dependency_closure(
        package_content_digest=content_digest,
        installed_distributions=("alpha-pkg==1.0", "zed-pkg==2.0"),
    )

    assert lock.format == PLUGIN_DEPENDENCY_LOCK_FORMAT
    assert [item.name for item in lock.python_distributions] == [
        "alpha-pkg",
        "zed-pkg",
    ]
    assert lock == reordered
    assert lock.digest == reordered.digest
    assert PluginDependencyClosureLock.from_dict(lock.to_dict()) == lock


@pytest.mark.parametrize(
    "distributions",
    [
        ("missing-version",),
        ("alpha==",),
        ("alpha==1", "Alpha_Pkg==2", "alpha-pkg==3"),
    ],
)
def test_dependency_closure_lock_rejects_incomplete_or_duplicate_entries(
    distributions: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        lock_plugin_dependency_closure(
            package_content_digest="b" * 64,
            installed_distributions=distributions,
        )
