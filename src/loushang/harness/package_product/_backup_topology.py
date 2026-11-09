"""Durable closed-backup topology custody for Package Product owners.

Product data supplies the expected wire, history fence and diagnostics. The
existing epoch, RootedFileIO and Windows receipt owners retain all IO authority.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)


def read_backup_topology(
    *,
    state_root: Path,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    | PackageProductWindowsFencedRuntimeOwner,
    expected: bytes,
    create_if_new: bool,
    file_name: str,
    maximum_bytes: int,
    maximum_inventory: int,
    blocking_history_prefix: str,
    label: str,
    absent_message: str,
    windows_receipts: WindowsPrivateReceiptIO,
) -> bytes:
    """Read, or durably publish and reread, one exact topology under its epoch."""
    epoch_runtime.assert_current()
    path = state_root / file_name
    if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
        from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
            windows_listdir_at,
        )

        with epoch_runtime.borrow_product_state_root_descriptor() as root:
            raw = windows_receipts.read_private_receipt(
                path,
                maximum_bytes=maximum_bytes,
                allow_unpublished_stage=create_if_new,
            )
            if raw is None:
                if not create_if_new or any(
                    name.casefold().startswith(blocking_history_prefix)
                    for name in windows_listdir_at(root)
                ):
                    raise ValueError(absent_message)
                windows_receipts.write_private_receipt(
                    path, expected, maximum_bytes=maximum_bytes
                )
                raw = windows_receipts.read_private_receipt(
                    path, maximum_bytes=maximum_bytes
                )
    elif isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        metadata = state_root.lstat()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        with closing_descriptor(os.open(state_root, flags)) as root_fd:
            opened = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
            ):
                raise ValueError(f"{label} state root changed")
            with RootedFileIO(state_root, root_fd) as io:
                with io.bind(path, durable=True) as rooted:
                    try:
                        raw = rooted.read_bytes(max_bytes=maximum_bytes)
                    except FileNotFoundError:
                        names, complete = rooted.scan_sibling_names(
                            limit=maximum_inventory
                        )
                        if (
                            not create_if_new
                            or not complete
                            or any(
                                name.startswith(blocking_history_prefix)
                                for name in names
                            )
                        ):
                            raise ValueError(absent_message) from None
                        rooted.create_new(expected)
                        raw = rooted.read_bytes(max_bytes=maximum_bytes)
    else:
        raise TypeError(f"{label} requires a Product epoch")
    epoch_runtime.assert_current()
    if raw != expected:
        raise ValueError(f"{label} changed")
    return raw
