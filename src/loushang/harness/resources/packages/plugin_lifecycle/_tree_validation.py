"""Package-specific values and errors over shared tree observation."""

from __future__ import annotations

from loushang.harness.resources.packages._tree_observation import (
    CollectedTree,
    ExpectedTreeFile,
    TreeDirectoryReadPort,
    TreeEntryObservation,
    TreeFileReadPort,
    TreeObservationError,
)
from loushang.harness.resources.packages._tree_observation import (
    collect_tree as _observe_tree,
)

from ._materialization_shared import IdentityMap
from .tree_transfer import PackageVerifiedTreeEntryV1, PackageVerifiedTreeManifestV1

_ERRORS = {
    "unexpected_directory": "Published Package tree has an unexpected directory",
    "directory_identity": "Published Package directory identity changed",
    "unexpected_file": "Published Package tree has an unexpected file",
    "file_identity": "Published Package file identity changed",
    "file_size_exceeded": "Published Package file exceeds verified size",
    "entry_type": "Published Package tree entry type changed",
    "empty_directory": "Published Package tree contains an empty directory",
    "directory_set": "Published Package directory set changed",
    "file_set": "Published Package file set changed",
}


def collect_tree(
    root: TreeDirectoryReadPort,
    expected: dict[str, PackageVerifiedTreeEntryV1],
    *,
    directory_identities: IdentityMap | None,
    file_identities: IdentityMap | None,
    allow_partial: bool = False,
) -> CollectedTree:
    expected_files: dict[str, ExpectedTreeFile] = dict(expected)
    try:
        return _observe_tree(
            root,
            expected_files,
            directory_identities=directory_identities,
            file_identities=file_identities,
            allow_partial=allow_partial,
        )
    except TreeObservationError as error:
        raise OSError(_ERRORS[error.code]) from None


def validate_tree_contents(
    root: TreeDirectoryReadPort,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: IdentityMap | None,
    file_identities: IdentityMap | None,
) -> tuple[IdentityMap, IdentityMap]:
    expected = {entry.logical_path: entry for entry in manifest.entries}
    observed, observed_directories, observed_files = collect_tree(
        root,
        expected,
        directory_identities=directory_identities,
        file_identities=file_identities,
    )
    if set(observed) != set(expected):
        raise OSError("Published Package tree members changed")
    for logical_path, entry in expected.items():
        byte_count, digest = observed[logical_path]
        if byte_count != entry.byte_count or digest != entry.content_digest:
            raise OSError("Published Package tree content changed")
    return observed_directories, observed_files


__all__ = [
    "CollectedTree",
    "TreeDirectoryReadPort",
    "TreeEntryObservation",
    "TreeFileReadPort",
    "collect_tree",
    "validate_tree_contents",
]
