"""Worker Windows stage byte checks using the original Resources native IO."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages._file_consumption import read_bounded_prefix
from loushang.harness.resources.packages._private_tree_windows import (
    supports_simple_windows_attributes,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.worker.contracts import WorkerRuntimeBindingV1

StageT = TypeVar("StageT")
FileIdentity = tuple[int, int, int, int, int]


class LaunchIntent(Protocol):
    @property
    def attempt_id(self) -> str: ...

    @property
    def owner_id(self) -> str: ...

    @property
    def payload_digest(self) -> str: ...

    @property
    def receipt_fingerprint(self) -> str: ...


def marker_bytes(
    *,
    attempt_id: str,
    entrypoint: str,
    owner_id: str,
    payload_digest: str,
    payload_size: int,
    receipt_fingerprint: str,
    stage_identity: tuple[int, int],
) -> bytes:
    return canonical_json_bytes(
        {
            "attemptId": attempt_id,
            "entrypoint": entrypoint,
            "ownerId": owner_id,
            "payloadDigest": payload_digest,
            "payloadSize": payload_size,
            "receiptFingerprint": receipt_fingerprint,
            "stageDevice": stage_identity[0],
            "stageInode": stage_identity[1],
            "version": 1,
        }
    )


def identity(metadata: os.stat_result) -> FileIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


@dataclass(frozen=True, slots=True)
class WindowsStageInspection:
    intent_type: type[LaunchIntent]
    error_type: type[Exception]
    error_prefix: str
    max_payload_bytes: int
    read_chunk: int
    directory_attributes: int
    file_attributes: int

    def verify_marker(
        self, raw: bytes, *, intent: LaunchIntent, stage_identity: tuple[int, int]
    ) -> tuple[str, int]:
        if type(intent) is not self.intent_type:
            raise self.error_type(self.error_prefix + "_intent_invalid")
        try:
            document = json.loads(raw)
            if (
                type(document) is not dict
                or type(document.get("entrypoint")) is not str
            ):
                raise ValueError("Worker marker shape changed")
            entrypoint = document["entrypoint"]
            if canonical_plugin_relative_path(entrypoint).as_posix() != entrypoint:
                raise ValueError("Worker marker path changed")
            payload_size = self.marker_payload_size(document)
            expected = marker_bytes(
                attempt_id=intent.attempt_id,
                entrypoint=entrypoint,
                owner_id=intent.owner_id,
                payload_digest=intent.payload_digest,
                payload_size=payload_size,
                receipt_fingerprint=intent.receipt_fingerprint,
                stage_identity=stage_identity,
            )
            if raw != expected:
                raise ValueError("Worker marker bytes changed")
            return (entrypoint, payload_size)
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise self.error_type(self.error_prefix + "_marker_changed") from exc

    def marker_payload_size(self, document: dict[str, object]) -> int:
        value = document.get("payloadSize")
        if type(value) is not int or not 0 < value <= self.max_payload_bytes:
            raise ValueError("Worker marker payload size changed")
        return value

    def read_checked_file(
        self,
        parent: int,
        name: str,
        acl: WindowsPrivateDirectoryAcl,
        *,
        maximum_bytes: int,
    ) -> tuple[bytes, FileIdentity]:
        descriptor = open_windows_regular_file_at(
            parent, name, create_new=False, write=False, read_control=True
        )
        try:
            before = self.require_direct(descriptor, acl, directory=False)
            if before[3] > maximum_bytes:
                raise self.error_type(self.error_prefix + "_file_too_large")
            raw = read_bounded_prefix(
                descriptor, maximum_bytes, chunk_size=self.read_chunk
            )
            if (
                len(raw) != before[3]
                or self.require_direct(descriptor, acl, directory=False) != before
                or identity(windows_stat_at(parent, name)) != before
            ):
                raise self.error_type(self.error_prefix + "_file_changed")
            return (bytes(raw), before)
        finally:
            os.close(descriptor)

    def require_direct(
        self, descriptor: int, acl: WindowsPrivateDirectoryAcl, *, directory: bool
    ) -> FileIdentity:
        acl.validate(descriptor)
        metadata = os.fstat(descriptor)
        attributes = getattr(metadata, "st_file_attributes", None)
        streams = (
            windows_directory_stream_names(descriptor)
            if directory
            else windows_regular_file_stream_names(descriptor)
        )
        if (
            not supports_simple_windows_attributes(
                attributes,
                directory=directory,
                file_mask=self.file_attributes,
                directory_mask=self.directory_attributes,
            )
            or metadata.st_nlink != 1
            or (
                not stat.S_ISDIR(metadata.st_mode)
                if directory
                else not stat.S_ISREG(metadata.st_mode)
            )
            or any((stream.casefold() != "::$data" for stream in streams))
        ):
            raise self.error_type(self.error_prefix + "_unsafe_member")
        return identity(metadata)


def require_payload_root(
    state_root: Path,
    descriptor: int,
    *,
    error_type: type[RuntimeError],
    error_prefix: str,
) -> None:
    if not os.path.samestat(os.fstat(descriptor), state_root.lstat()):
        raise error_type(error_prefix + "_state_root_changed")


def require_payload_streams(
    descriptor: int,
    *,
    directory: bool,
    error_type: type[RuntimeError],
    error_prefix: str,
) -> None:
    streams = (
        windows_directory_stream_names(descriptor)
        if directory
        else windows_regular_file_stream_names(descriptor)
    )
    if any((stream.casefold() != "::$data" for stream in streams)):
        raise error_type(error_prefix + "_stream_invalid")


def write_payload_bytes(descriptor: int, body: bytes) -> None:
    write_all(
        lambda chunk: os.write(descriptor, chunk),
        body,
        message="Windows Worker payload write made no progress",
    )


def create_windows_payload_stage(
    *,
    root: int,
    acl: WindowsPrivateDirectoryAcl,
    root_path: Callable[[], Path],
    stage_name: str,
    parts: list[str],
    entrypoint: str,
    body: bytes,
    configuration: PluginLocalWorkerConfiguration,
    attempt_id: str,
    owner_id: str,
    payload_digest: str,
    receipt_fingerprint: str,
    marker_name: str,
    complete: Callable[[WorkerRuntimeBindingV1, tuple[int, int]], StageT],
    error_type: type[RuntimeError],
    error_prefix: str = "worker_payload",
) -> StageT:
    """Create/capture with original root_path reads and live root/ACL/stage.

    root_path and complete may revalidate Product authority. Keep both path
    getter evaluations and run complete synchronously before stage close.
    """
    stage = open_windows_directory(
        stage_name,
        dir_fd=root,
        create_new=True,
        share_delete=False,
        security_descriptor=acl.security_descriptor,
        read_control=True,
    )
    try:
        acl.validate(stage)
        require_payload_streams(
            stage, directory=True, error_type=error_type, error_prefix=error_prefix
        )
        stage_stat = os.fstat(stage)
        stage_identity = (stage_stat.st_dev, stage_stat.st_ino)
        windows_flush_directory(root)
        current = stage
        children: list[int] = []
        try:
            for name in parts[:-1]:
                child = open_windows_directory(
                    name,
                    dir_fd=current,
                    create_new=True,
                    share_delete=False,
                    security_descriptor=acl.security_descriptor,
                    read_control=True,
                )
                children.append(child)
                acl.validate(child)
                require_payload_streams(
                    child,
                    directory=True,
                    error_type=error_type,
                    error_prefix=error_prefix,
                )
                windows_flush_directory(current)
                current = child
            executable = open_windows_regular_file_at(
                current,
                parts[-1],
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
            try:
                acl.validate(executable)
                require_payload_streams(
                    executable,
                    directory=False,
                    error_type=error_type,
                    error_prefix=error_prefix,
                )
                write_payload_bytes(executable, body)
                windows_flush_file(executable)
            finally:
                os.close(executable)
            windows_flush_directory(current)
        finally:
            for child in reversed(children):
                os.close(child)
        marker = marker_bytes(
            attempt_id=attempt_id,
            entrypoint=entrypoint,
            owner_id=owner_id,
            payload_digest=payload_digest,
            payload_size=len(body),
            receipt_fingerprint=receipt_fingerprint,
            stage_identity=stage_identity,
        )
        marker_fd = open_windows_regular_file_at(
            stage,
            marker_name,
            create_new=True,
            write=True,
            security_descriptor=acl.security_descriptor,
            read_control=True,
        )
        try:
            acl.validate(marker_fd)
            require_payload_streams(
                marker_fd,
                directory=False,
                error_type=error_type,
                error_prefix=error_prefix,
            )
            write_payload_bytes(marker_fd, marker)
            windows_flush_file(marker_fd)
        finally:
            os.close(marker_fd)
        windows_flush_directory(stage)
        require_payload_root(
            root_path(), root, error_type=error_type, error_prefix=error_prefix
        )
        if (
            os.fstat(stage).st_dev,
            os.fstat(stage).st_ino,
        ) != stage_identity or not os.path.samestat(
            windows_stat_at(root, stage_name), os.fstat(stage)
        ):
            raise error_type(error_prefix + "_stage_changed")
        runtime = WorkerRuntimeBindingV1.capture(
            package_root=root_path() / stage_name, configuration=configuration
        )
        if (
            runtime.executable_digest != payload_digest
            or runtime.executable_size != len(body)
            or (runtime.cwd_device, runtime.cwd_inode) != stage_identity
        ):
            raise error_type(error_prefix + "_selection_stale")
        return complete(runtime, stage_identity)
    finally:
        os.close(stage)


_InventoryCo = TypeVar("_InventoryCo", covariant=True)


class _PayloadAttemptFactory(Protocol[_InventoryCo]):
    def __call__(
        self, *, attempt_id: str, directory_identity: tuple[int, int]
    ) -> _InventoryCo: ...


def inventory_windows_payload_stages(
    state_root: Path,
    *,
    directory_fd: int,
    record_type: _PayloadAttemptFactory[StageT],
    maximum_attempts: Callable[[], int],
    name_pattern: re.Pattern[str],
    error_type: type[RuntimeError],
    error_prefix: str,
) -> tuple[StageT, ...]:
    """Observe direct stage identities, preserving crash LPAC grants.

    Caller supplies an admitted pinned root. Do not certify child ACLs,
    attributes or contents: this read confers no launch/deletion authority.
    """
    with WindowsPrivateDirectoryAcl() as acl:
        acl.validate(directory_fd)
        _require_inventory_visible_root(
            state_root, directory_fd, error_type=error_type, error_prefix=error_prefix
        )
        if any(
            stream.casefold() != "::$data"
            for stream in windows_directory_stream_names(directory_fd)
        ):
            raise error_type(error_prefix + "_inventory_unsafe")
        names = windows_listdir_at(directory_fd)
        prefixed = tuple(
            name for name in names if name.casefold().startswith("worker-payload-")
        )
        if (
            len(prefixed) > maximum_attempts()
            or len({name.casefold() for name in prefixed}) != len(prefixed)
            or any(name_pattern.fullmatch(name) is None for name in prefixed)
        ):
            raise error_type(error_prefix + "_inventory_unsafe")
        result = []
        for name in sorted(prefixed):
            match = name_pattern.fullmatch(name)
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
                    raise error_type(error_prefix + "_inventory_unsafe")
                result.append(
                    record_type(
                        attempt_id=match.group(1),
                        directory_identity=(current.st_dev, current.st_ino),
                    )
                )
            finally:
                os.close(stage)
        if set(windows_listdir_at(directory_fd)) != set(names):
            raise error_type(error_prefix + "_inventory_changed")
        _require_inventory_visible_root(
            state_root, directory_fd, error_type=error_type, error_prefix=error_prefix
        )
        return tuple(result)


def _require_inventory_visible_root(
    state_root: Path,
    directory_fd: int,
    *,
    error_type: type[RuntimeError],
    error_prefix: str,
) -> None:
    try:
        require_payload_root(
            state_root, directory_fd, error_type=error_type, error_prefix=error_prefix
        )
    except OSError as exc:
        raise error_type(error_prefix + "_state_root_changed") from exc
