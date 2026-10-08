"""Read-only Product inventory of Windows Worker payload attempt directories.

An inventory entry is debt, not evidence that its contents may be launched or
deleted. The future materializer and recovery owner must join its attempt ID
to the Supervisor, native provisioning, Job, and Package lease histories.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_directory_stream_names,
    windows_listdir_at,
    windows_stat_at,
)

_NAME = re.compile(r"worker-payload-([0-9a-f]{32})\Z")
_MAX_ATTEMPTS = 1024


class CodingWindowsWorkerPayloadInventoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPayloadAttemptV1:
    attempt_id: str
    directory_identity: tuple[int, int]


def inspect_coding_windows_product_worker_payload_attempts(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerPayloadAttemptV1, ...]:
    """List every retained payload attempt through the current Product root."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker payload inventory requires a Product owner")
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            result = inspect_windows_worker_payload_stages(
                product.state_root, directory_fd=root
            )
        product.assert_root_gc_authority_current()
        return result


def inspect_windows_worker_payload_stages(
    state_root: Path, *, directory_fd: int
) -> tuple[CodingWindowsWorkerPayloadAttemptV1, ...]:
    """Inventory names and direct directory identities without trusting content."""

    if (
        os.name != "nt"
        or not isinstance(state_root, Path)
        or not state_root.is_absolute()
        or type(directory_fd) is not int
        or directory_fd < 0
    ):
        raise OSError("Windows Worker payload inventory requires a pinned root")
    with WindowsPrivateDirectoryAcl() as acl:
        acl.validate(directory_fd)
        _require_visible_root(state_root, directory_fd)
        if any(
            stream.casefold() != "::$data"
            for stream in windows_directory_stream_names(directory_fd)
        ):
            raise CodingWindowsWorkerPayloadInventoryError(
                "coding_worker_payload_inventory_unsafe"
            )
        names = windows_listdir_at(directory_fd)
        prefixed = tuple(
            name for name in names if name.casefold().startswith("worker-payload-")
        )
        if (
            len(prefixed) > _MAX_ATTEMPTS
            or len({name.casefold() for name in prefixed}) != len(prefixed)
            or any(_NAME.fullmatch(name) is None for name in prefixed)
        ):
            raise CodingWindowsWorkerPayloadInventoryError(
                "coding_worker_payload_inventory_unsafe"
            )
        result = []
        for name in sorted(prefixed):
            match = _NAME.fullmatch(name)
            assert match is not None
            before = windows_stat_at(directory_fd, name)
            stage = open_windows_directory(
                name, dir_fd=directory_fd, share_delete=False, read_control=True
            )
            try:
                # LPAC grants may remain after a crash. Their ACLs need a
                # native recovery decision, so this inventory only observes
                # direct identity and never certifies the stage as clean.
                current = os.fstat(stage)
                if not os.path.samestat(before, current) or any(
                    stream.casefold() != "::$data"
                    for stream in windows_directory_stream_names(stage)
                ):
                    raise CodingWindowsWorkerPayloadInventoryError(
                        "coding_worker_payload_inventory_unsafe"
                    )
                result.append(
                    CodingWindowsWorkerPayloadAttemptV1(
                        attempt_id=match.group(1),
                        directory_identity=(current.st_dev, current.st_ino),
                    )
                )
            finally:
                os.close(stage)
        if set(windows_listdir_at(directory_fd)) != set(names):
            raise CodingWindowsWorkerPayloadInventoryError(
                "coding_worker_payload_inventory_changed"
            )
        _require_visible_root(state_root, directory_fd)
        return tuple(result)


def _require_visible_root(state_root: Path, directory_fd: int) -> None:
    try:
        if not os.path.samestat(os.fstat(directory_fd), state_root.lstat()):
            raise CodingWindowsWorkerPayloadInventoryError(
                "coding_worker_payload_state_root_changed"
            )
    except OSError as exc:
        raise CodingWindowsWorkerPayloadInventoryError(
            "coding_worker_payload_state_root_changed"
        ) from exc


__all__ = [
    "CodingWindowsWorkerPayloadAttemptV1",
    "CodingWindowsWorkerPayloadInventoryError",
    "inspect_coding_windows_product_worker_payload_attempts",
]
