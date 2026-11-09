"""Private-source read policy cannot loosen the existing manifest contract."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages._tree_observation import (
    TreeFileReadPolicy,
    TreeObservationError,
    collect_tree,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _PosixTreeDirectoryReader,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackageVerifiedTreeEntryV1,
)


@pytest.mark.skipif(os.name != "posix", reason="Existing POSIX rooted reader")
@pytest.mark.parametrize("violation", ("extra_bytes", "late_hardlink"))
def test_manifest_retains_its_byte_bound_and_post_read_link_check(
    tmp_path: Path, violation: str
) -> None:
    root = tmp_path / "tree"
    root.mkdir(mode=0o700)
    content = b"private cache"
    file = root / "cache.json"
    file.write_bytes(content)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    native = _PosixTreeDirectoryReader(descriptor)

    class DeclaredSourcePolicy:
        identity = native.identity
        open_directory = native.open_directory

        @contextmanager
        def entries(self):
            with native.entries() as entries:
                yield (
                    replace(
                        entry,
                        read_policy=TreeFileReadPolicy(
                            max_bytes=1024,
                            require_single_link_after_read=False,
                        ),
                    )
                    for entry in entries
                )

        @contextmanager
        def file_reader(self, name):
            with native.file_reader(name) as reader:
                if violation == "late_hardlink":
                    os.link(file, tmp_path / "late-alias")
                yield reader

    expected = PackageVerifiedTreeEntryV1(
        "cache.json",
        sha256(content).hexdigest(),
        1 if violation == "extra_bytes" else len(content),
    )
    try:
        with pytest.raises(TreeObservationError) as caught:
            collect_tree(
                DeclaredSourcePolicy(),
                {expected.logical_path: expected},
                directory_identities=None,
                file_identities=None,
            )
        assert caught.value.code == (
            "file_size_exceeded" if violation == "extra_bytes" else "file_identity"
        )
    finally:
        os.close(descriptor)
