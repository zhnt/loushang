"""Worker stage member deletion; Product root-intent IO remains with its owner."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages._file_consumption import read_bounded_prefix
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_delete_open_entry,
    windows_flush_directory,
    windows_listdir_at,
    windows_stat_at,
)

from ._windows_stage_io import FileIdentity, LaunchIntent, WindowsStageInspection


class DirectoryProof(Protocol):
    @property
    def attempt_id(self) -> str: ...
    @property
    def stage_identity(self) -> FileIdentity: ...
    @property
    def directory_identities(self) -> tuple[tuple[str, FileIdentity], ...]: ...


class CompleteStageProof(DirectoryProof, Protocol):
    @property
    def entrypoint(self) -> str: ...
    @property
    def marker_identity(self) -> FileIdentity: ...
    @property
    def executable_identity(self) -> FileIdentity: ...
    @property
    def executable_digest(self) -> str: ...


class PartialStageProof(DirectoryProof, Protocol):
    @property
    def entrypoint(self) -> str | None: ...
    @property
    def executable_identity(self) -> FileIdentity | None: ...
    @property
    def executable_digest(self) -> str | None: ...


def close_opened(opened: list[int]) -> None:
    for descriptor in reversed(opened):
        os.close(descriptor)


def open_existing_parent(
    stage: int,
    parts: list[str],
    review: DirectoryProof,
    acl: WindowsPrivateDirectoryAcl,
    inspection: WindowsStageInspection,
    changed: Callable[[], Exception],
) -> tuple[int, list[int]] | None:
    current = stage
    opened: list[int] = []
    try:
        for index, name in enumerate(parts):
            if name not in windows_listdir_at(current):
                close_opened(opened)
                return None
            child = open_windows_directory(
                name, dir_fd=current, share_delete=False, read_control=True
            )
            opened.append(child)
            if (
                inspection.require_direct(child, acl, directory=True)[:2]
                != review.directory_identities[index][1][:2]
            ):
                raise changed()
            current = child
        return current, opened
    except BaseException:
        close_opened(opened)
        raise


@dataclass(frozen=True, slots=True)
class WindowsStageRetirement:
    inspection: WindowsStageInspection
    error_type: type[Exception]
    error_prefix: str

    @contextmanager
    def stage(
        self, root: int, review: DirectoryProof
    ) -> Iterator[tuple[int | None, WindowsPrivateDirectoryAcl]]:
        stage_name = "worker-payload-" + review.attempt_id
        with WindowsPrivateDirectoryAcl() as acl:
            self.inspection.require_direct(root, acl, directory=True)
            try:
                stage = open_windows_directory(
                    stage_name, dir_fd=root, share_delete=False, read_control=True
                )
            except FileNotFoundError:
                yield None, acl
                return
            try:
                yield stage, acl
            finally:
                os.close(stage)
            self.delete_directory_if_empty(root, stage_name, review.stage_identity, acl)

    @contextmanager
    def complete(
        self, root: int, review: CompleteStageProof, intent: LaunchIntent
    ) -> Iterator[int | None]:
        with self.stage(root, review) as (stage, acl):
            if stage is None:
                yield None
                return
            self.require_remaining_subset(stage, review, intent, acl)
            parts = review.entrypoint.split("/")
            parent = self.open_parent(stage, parts[:-1], review, acl)
            if parent is not None:
                descriptor, opened = parent
                try:
                    self.delete_file_if_present(
                        descriptor,
                        parts[-1],
                        review.executable_identity,
                        review.executable_digest,
                        acl,
                    )
                finally:
                    close_opened(opened)
            for depth in range(len(parts) - 1, 0, -1):
                prefix = parts[: depth - 1]
                parent = self.open_parent(stage, prefix, review, acl)
                if parent is None:
                    continue
                descriptor, opened = parent
                try:
                    identity = review.directory_identities[depth - 1][1]
                    self.delete_directory_if_empty(
                        descriptor, parts[depth - 1], identity, acl
                    )
                finally:
                    close_opened(opened)
            self.delete_file_if_present(
                stage,
                "worker-payload.json",
                review.marker_identity,
                None,
                acl,
                intent=intent,
                stage_identity=review.stage_identity[:2],
                expected_entrypoint=review.entrypoint,
                expected_payload_size=review.executable_identity[3],
            )
            yield stage

    def open_parent(
        self,
        stage: int,
        parts: list[str],
        review: DirectoryProof,
        acl: WindowsPrivateDirectoryAcl,
    ) -> tuple[int, list[int]] | None:
        return open_existing_parent(
            stage,
            parts,
            review,
            acl,
            self.inspection,
            lambda: self.error_type(self.error_prefix + "_directory_changed"),
        )

    def require_remaining_subset(
        self,
        stage: int,
        review: CompleteStageProof,
        intent: LaunchIntent,
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        if (
            self.inspection.require_direct(stage, acl, directory=True)[:2]
            != review.stage_identity[:2]
        ):
            raise self.error_type(self.error_prefix + "_stage_changed")
        parts = review.entrypoint.split("/")
        if not set(windows_listdir_at(stage)) <= {"worker-payload.json", parts[0]}:
            raise self.error_type(self.error_prefix + "_extra_member")
        if "worker-payload.json" in windows_listdir_at(stage):
            marker, identity = self.inspection.read_checked_file(
                stage, "worker-payload.json", acl, maximum_bytes=1024
            )
            marker_entrypoint, payload_size = self.inspection.verify_marker(
                marker, intent=intent, stage_identity=review.stage_identity[:2]
            )
            if (
                identity != review.marker_identity
                or marker_entrypoint != review.entrypoint
                or payload_size != review.executable_identity[3]
            ):
                raise self.error_type(self.error_prefix + "_marker_changed")
        current = stage
        opened: list[int] = []
        try:
            for index, name in enumerate(parts[:-1]):
                if name not in windows_listdir_at(current):
                    return
                child = open_windows_directory(
                    name, dir_fd=current, share_delete=False, read_control=True
                )
                opened.append(child)
                if (
                    self.inspection.require_direct(child, acl, directory=True)[:2]
                    != review.directory_identities[index][1][:2]
                ):
                    raise self.error_type(self.error_prefix + "_directory_changed")
                if not set(windows_listdir_at(child)) <= {parts[index + 1]}:
                    raise self.error_type(self.error_prefix + "_extra_member")
                current = child
            if parts[-1] in windows_listdir_at(current):
                body, identity = self.inspection.read_checked_file(
                    current, parts[-1], acl, maximum_bytes=16 * 1024 * 1024
                )
                if (
                    identity != review.executable_identity
                    or sha256(body).hexdigest() != review.executable_digest
                ):
                    raise self.error_type(self.error_prefix + "_payload_changed")
            elif windows_listdir_at(current):
                raise self.error_type(self.error_prefix + "_extra_member")
        finally:
            close_opened(opened)

    def delete_file_if_present(
        self,
        parent: int,
        name: str,
        expected: tuple[int, int, int, int, int],
        digest: str | None,
        acl: WindowsPrivateDirectoryAcl,
        *,
        intent: LaunchIntent | None = None,
        stage_identity: tuple[int, int] | None = None,
        expected_entrypoint: str | None = None,
        expected_payload_size: int | None = None,
    ) -> None:
        if name not in windows_listdir_at(parent):
            return
        descriptor = open_windows_deletion_entry_at(parent, name, directory=False)
        try:
            if (
                self.inspection.require_direct(descriptor, acl, directory=False)
                != expected
            ):
                raise self.error_type(self.error_prefix + "_file_changed")
            raw = self.read_exact(descriptor, expected[3])
            if digest is None:
                if intent is None or stage_identity is None:
                    raise self.error_type(self.error_prefix + "_marker_unbound")
                entrypoint, payload_size = self.inspection.verify_marker(
                    raw, intent=intent, stage_identity=stage_identity
                )
                if (
                    entrypoint != expected_entrypoint
                    or payload_size != expected_payload_size
                ):
                    raise self.error_type(self.error_prefix + "_marker_changed")
            elif sha256(raw).hexdigest() != digest:
                raise self.error_type(self.error_prefix + "_payload_changed")
            if (
                self.inspection.require_direct(descriptor, acl, directory=False)
                != expected
                or self.file_identity_at(parent, name) != expected
            ):
                raise self.error_type(self.error_prefix + "_file_changed")
            self.delete_open_stage_entry(descriptor, expected=expected, directory=False)
        finally:
            os.close(descriptor)
        windows_flush_directory(parent)

    def delete_directory_if_empty(
        self,
        parent: int,
        name: str,
        expected: tuple[int, int, int, int, int],
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        if name not in windows_listdir_at(parent):
            return
        descriptor = open_windows_deletion_entry_at(parent, name, directory=True)
        try:
            current = self.inspection.require_direct(descriptor, acl, directory=True)
            if (
                current[:2] != expected[:2]
                or self.file_identity_at(parent, name) != current
                or windows_listdir_at(descriptor)
            ):
                raise self.error_type(self.error_prefix + "_directory_changed")
            self.delete_open_stage_entry(descriptor, expected=current, directory=True)
        finally:
            os.close(descriptor)
        windows_flush_directory(parent)

    def read_exact(self, descriptor: int, size: int) -> bytes:
        if size < 0:
            raise self.error_type(self.error_prefix + "_file_changed")
        raw = read_bounded_prefix(
            descriptor, size, chunk_size=self.inspection.read_chunk
        )
        if len(raw) != size:
            raise self.error_type(self.error_prefix + "_file_changed")
        return raw

    def file_identity_at(
        self, parent: int, name: str
    ) -> tuple[int, int, int, int, int]:
        metadata = windows_stat_at(parent, name)
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
        )

    def delete_open_stage_entry(
        self,
        descriptor: int,
        *,
        expected: tuple[int, int, int, int, int],
        directory: bool,
    ) -> None:
        """Bridge Product's link-count identity to the native API's mode identity."""

        metadata = os.fstat(descriptor)
        if (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
        ) != expected:
            raise self.error_type(self.error_prefix + "_file_changed")
        windows_delete_open_entry(
            descriptor,
            expected_identity=(
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
            ),
            directory=directory,
        )


@dataclass(frozen=True, slots=True)
class PartialWindowsStageRetirement:
    deletion: WindowsStageRetirement
    error_type: type[Exception]
    error_prefix: str

    @contextmanager
    def partial(self, root: int, review: PartialStageProof) -> Iterator[int | None]:
        with self.deletion.stage(root, review) as (stage, acl):
            if stage is None:
                yield None
                return
            self.require_remaining_subset(stage, review, acl)
            if review.entrypoint is not None:
                assert review.executable_identity is not None
                assert review.executable_digest is not None
                parts = review.entrypoint.split("/")
                parent = self.open_parent(stage, parts[:-1], review, acl)
                if parent is not None:
                    descriptor, opened = parent
                    try:
                        self.deletion.delete_file_if_present(
                            descriptor,
                            parts[-1],
                            review.executable_identity,
                            review.executable_digest,
                            acl,
                        )
                    finally:
                        close_opened(opened)
            for index in range(len(review.directory_identities) - 1, -1, -1):
                path, identity = review.directory_identities[index]
                parts = path.split("/")
                parent = self.open_parent(stage, parts[:-1], review, acl)
                if parent is None:
                    continue
                descriptor, opened = parent
                try:
                    self.deletion.delete_directory_if_empty(
                        descriptor, parts[-1], identity, acl
                    )
                finally:
                    close_opened(opened)
            yield stage

    def open_parent(
        self,
        stage: int,
        parts: list[str],
        review: DirectoryProof,
        acl: WindowsPrivateDirectoryAcl,
    ) -> tuple[int, list[int]] | None:
        return open_existing_parent(
            stage,
            parts,
            review,
            acl,
            self.deletion.inspection,
            lambda: self.error_type(self.error_prefix + "_directory_changed"),
        )

    def require_remaining_subset(
        self,
        stage: int,
        review: PartialStageProof,
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        if (
            self.deletion.inspection.require_direct(stage, acl, directory=True)[:2]
            != review.stage_identity[:2]
        ):
            raise self.error_type(self.error_prefix + "_stage_changed")
        first_name = (
            review.directory_identities[0][0]
            if review.directory_identities
            else review.entrypoint
        )
        names = set(windows_listdir_at(stage))
        if (
            any(name.casefold() == "worker-payload.json" for name in names)
            or (first_name is None and names)
            or (first_name is not None and not names <= {first_name.split("/")[0]})
        ):
            raise self.error_type(self.error_prefix + "_extra_member")
        current = stage
        opened: list[int] = []
        try:
            for index, (path, identity) in enumerate(review.directory_identities):
                name = path.split("/")[-1]
                if name not in windows_listdir_at(current):
                    return
                child = open_windows_directory(
                    name, dir_fd=current, share_delete=False, read_control=True
                )
                opened.append(child)
                if (
                    self.deletion.inspection.require_direct(child, acl, directory=True)[
                        :2
                    ]
                    != identity[:2]
                ):
                    raise self.error_type(self.error_prefix + "_directory_changed")
                next_name = (
                    review.directory_identities[index + 1][0].split("/")[-1]
                    if index + 1 < len(review.directory_identities)
                    else (
                        review.entrypoint.split("/")[-1]
                        if review.entrypoint is not None
                        else None
                    )
                )
                child_names = set(windows_listdir_at(child))
                if (next_name is None and child_names) or (
                    next_name is not None and not child_names <= {next_name}
                ):
                    raise self.error_type(self.error_prefix + "_extra_member")
                current = child
            if review.entrypoint is not None:
                assert review.executable_identity is not None
                assert review.executable_digest is not None
                name = review.entrypoint.split("/")[-1]
                if name in windows_listdir_at(current):
                    raw, identity = self.deletion.inspection.read_checked_file(
                        current, name, acl, maximum_bytes=16 * 1024 * 1024
                    )
                    if (
                        identity != review.executable_identity
                        or sha256(raw).hexdigest() != review.executable_digest
                    ):
                        raise self.error_type(self.error_prefix + "_file_changed")
                elif windows_listdir_at(current):
                    raise self.error_type(self.error_prefix + "_extra_member")
        finally:
            close_opened(opened)
