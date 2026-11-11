"""Worker-specific physical payload profile, with caller-owned raw descriptors."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages._file_consumption import hash_exact_size
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path

from ._records import (
    _ATTEMPT,
    _MAX_UNMARKED_DEPTH,
    _MAX_UNMARKED_PATH_BYTES,
    EmptyPayloadPlan,
    PayloadMember,
    PayloadPlan,
    PayloadReview,
    PayloadValueTypes,
    complete_fields,
    empty_fields,
    plan_fields,
    unmarked_fields,
)
from ._repair import _FILE_FLAGS as _FILE_FLAGS
from ._repair import RepairJournal, read_repair_file

_DIR_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if os.name == "posix"
    else -1
)
_MARKER = "product-payload.json"
_MAX_MARKER_BYTES = 1024
_EMPTY_REPAIR_PREFIX = "worker-empty-repair-"
_MAX_EMPTY_REPAIR_BYTES = 512
_COMPLETE_REPAIR_PREFIX = "worker-complete-repair-"
_MAX_COMPLETE_REPAIR_BYTES = 2048
_UNMARKED_REPAIR_PREFIX = "worker-unmarked-repair-"
_MAX_UNMARKED_REPAIR_BYTES = 32768


def repair_names(attempt_id: str, prefix: str) -> tuple[str, str]:
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    name = f"{prefix}{attempt_id}.json"
    return name, f".{name}.stage"


@dataclass(slots=True)
class _PayloadRootScope:
    storage: PayloadStorage
    path: Callable[[], Path]
    _descriptor: int = field(init=False)

    def __enter__(self) -> int:
        self._descriptor = os.open(self.path(), _DIR_FLAGS)
        try:
            self.storage._require_private_visible_root(self.path(), self._descriptor)
        except BaseException:
            os.close(self._descriptor)
            raise
        return self._descriptor

    def __exit__(self, _kind: object, _error: object, _traceback: object) -> None:
        os.close(self._descriptor)


@dataclass(frozen=True, slots=True)
class PayloadStorage:
    values: PayloadValueTypes
    error_type: type[RuntimeError]

    def open_root(self, path: Callable[[], Path]) -> _PayloadRootScope:
        """Keep the caller's two path reads and original raw exception behavior."""
        return _PayloadRootScope(self, path)

    @property
    def empty(self) -> RepairJournal[EmptyPayloadPlan]:
        return RepairJournal(
            names=lambda attempt: repair_names(attempt, _EMPTY_REPAIR_PREFIX),
            decode=self.values.decode_empty,
            encode=empty_fields,
            maximum_bytes=_MAX_EMPTY_REPAIR_BYTES,
            error_type=self.error_type,
            raw_error_type=self.error_type,
            error_code="coding_worker_payload_empty_repair_unverified",
            stale_code="coding_worker_payload_debt_plan_stale",
            publication_changed="Worker empty repair publication changed",
            write_message="Worker empty repair intent write made no progress",
        )

    @property
    def complete(self) -> RepairJournal[tuple[PayloadPlan, str]]:
        return RepairJournal(
            names=lambda attempt: repair_names(attempt, _COMPLETE_REPAIR_PREFIX),
            decode=self.values.decode_complete,
            encode=lambda value: complete_fields(*value),
            maximum_bytes=_MAX_COMPLETE_REPAIR_BYTES,
            error_type=self.error_type,
            raw_error_type=self.error_type,
            error_code="coding_worker_payload_complete_repair_unverified",
            stale_code="coding_worker_payload_debt_plan_stale",
            publication_changed="Worker complete repair publication changed",
            write_message="Worker complete repair intent write made no progress",
        )

    @property
    def unmarked(self) -> RepairJournal[PayloadReview]:
        return RepairJournal(
            names=lambda attempt: repair_names(attempt, _UNMARKED_REPAIR_PREFIX),
            decode=self.values.decode_unmarked,
            encode=unmarked_fields,
            maximum_bytes=_MAX_UNMARKED_REPAIR_BYTES,
            error_type=self.error_type,
            raw_error_type=self.error_type,
            error_code="coding_worker_payload_unmarked_repair_unverified",
            stale_code="coding_worker_payload_debt_plan_stale",
            publication_changed="Worker unmarked repair publication changed",
            write_message="Worker unmarked repair intent write made no progress",
            write_maximum=_MAX_UNMARKED_REPAIR_BYTES,
        )

    def _read_repair_file(
        self, root_fd: int, name: str, *, maximum_bytes: int, error_code: str
    ) -> tuple[bytes, os.stat_result]:
        return read_repair_file(
            root_fd,
            name,
            maximum_bytes=maximum_bytes,
            error_code=error_code,
            error_type=self.error_type,
        )

    def _write_payload(self, stage_fd: int, entrypoint: str, body: bytes) -> None:
        relative = canonical_plugin_relative_path(entrypoint)
        if relative.as_posix() != entrypoint or not body:
            raise self.error_type("coding_worker_payload_entrypoint_invalid")
        components = relative.parts
        opened: list[int] = []
        current = stage_fd
        try:
            for component in components[:-1]:
                os.mkdir(component, 0o700, dir_fd=current)
                current = os.open(component, _DIR_FLAGS, dir_fd=current)
                opened.append(current)
            file_fd = os.open(components[-1], _FILE_FLAGS, 0o600, dir_fd=current)
            try:
                write_all(
                    lambda view: os.write(file_fd, view),
                    body,
                    message="Worker payload write made no progress",
                )
                os.fchmod(file_fd, 0o500)
                os.fsync(file_fd)
            finally:
                os.close(file_fd)
            os.fsync(current)
            os.fsync(stage_fd)
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    def _write_marker(self, stage_fd: int, plan: PayloadPlan) -> None:
        body = canonical_json_bytes(plan_fields(plan)) + b"\n"
        descriptor = os.open(_MARKER, _FILE_FLAGS, 0o600, dir_fd=stage_fd)
        try:
            write_all(
                lambda view: os.write(descriptor, view),
                body,
                message="Worker payload marker write made no progress",
            )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(stage_fd)

    def _stage_exists(self, root_fd: int, attempt_id: str) -> bool:
        try:
            os.stat(
                f"worker-payload-{attempt_id}", dir_fd=root_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            return False
        return True

    def _remove_empty_stage(self, root_fd: int, stage_name: str) -> None:
        os.rmdir(stage_name, dir_fd=root_fd)
        os.fsync(root_fd)

    def _verify_debt(self, root_fd: int, attempt_id: str) -> PayloadPlan:
        if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
            raise ValueError("Coding Worker attempt identity is invalid")
        stage_name = f"worker-payload-{attempt_id}"
        try:
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            try:
                self._require_visible_stage(stage_name, root_fd, stage_fd)
                marker_fd = os.open(
                    _MARKER,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=stage_fd,
                )
                try:
                    marker_stat = os.fstat(marker_fd)
                    if (
                        not stat.S_ISREG(marker_stat.st_mode)
                        or stat.S_IMODE(marker_stat.st_mode) != 0o600
                        or marker_stat.st_nlink != 1
                        or marker_stat.st_uid != os.geteuid()
                    ):
                        raise ValueError("Worker payload marker is unsafe")
                    body = os.read(marker_fd, 1025)
                    if len(body) > 1024 or os.read(marker_fd, 1):
                        raise ValueError("Worker payload marker exceeds budget")
                finally:
                    os.close(marker_fd)
                value = json.loads(body)
                fields = {
                    "attemptId",
                    "entrypoint",
                    "payloadDigest",
                    "payloadSize",
                    "receiptFingerprint",
                    "stageDevice",
                    "stageInode",
                    "version",
                }
                if (
                    type(value) is not dict
                    or set(value) != fields
                    or value["version"] != 1
                ):
                    raise ValueError("Worker payload marker is invalid")
                plan = self.values.plan_type(
                    attempt_id=value["attemptId"],
                    entrypoint=value["entrypoint"],
                    payload_digest=value["payloadDigest"],
                    payload_size=value["payloadSize"],
                    receipt_fingerprint=value["receiptFingerprint"],
                    stage_device=value["stageDevice"],
                    stage_inode=value["stageInode"],
                )
                opened = os.fstat(stage_fd)
                if (
                    body != canonical_json_bytes(plan_fields(plan)) + b"\n"
                    or plan.attempt_id != attempt_id
                    or (opened.st_dev, opened.st_ino)
                    != (plan.stage_device, plan.stage_inode)
                ):
                    raise ValueError("Worker payload marker changed")
                self._verify_debt_file(stage_fd, plan)
                self._require_visible_stage(stage_name, root_fd, stage_fd)
                return plan
            finally:
                os.close(stage_fd)
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            raise self.error_type("coding_worker_payload_debt_unverified") from exc

    def _verify_empty_debt(self, root_fd: int, attempt_id: str) -> EmptyPayloadPlan:
        if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
            raise ValueError("Coding Worker attempt identity is invalid")
        stage_name = f"worker-payload-{attempt_id}"
        try:
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            try:
                self._require_visible_stage(stage_name, root_fd, stage_fd)
                stage = os.fstat(stage_fd)
                if (
                    stage.st_uid != os.geteuid()
                    or stat.S_IMODE(stage.st_mode) != 0o700
                    or os.listdir(stage_fd)
                ):
                    raise ValueError("Worker empty payload stage is unsafe")
                return self.values.empty_type(
                    attempt_id=attempt_id,
                    stage_device=stage.st_dev,
                    stage_inode=stage.st_ino,
                )
            finally:
                os.close(stage_fd)
        except (OSError, ValueError, TypeError) as exc:
            raise self.error_type(
                "coding_worker_payload_empty_debt_unverified"
            ) from exc

    def _scan_unmarked_debt(self, root_fd: int, attempt_id: str) -> PayloadReview:
        if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
            raise ValueError("Coding Worker attempt identity is invalid")
        stage_name = f"worker-payload-{attempt_id}"
        stage_fd = -1
        opened: list[int] = []
        try:
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            stage = os.fstat(stage_fd)
            if stage.st_uid != os.geteuid() or stat.S_IMODE(stage.st_mode) != 0o700:
                raise ValueError("Worker unmarked stage is unsafe")
            current = stage_fd
            members: list[PayloadMember] = []
            parts: list[str] = []
            for depth in range(_MAX_UNMARKED_DEPTH + 1):
                names = tuple(os.listdir(current))
                if not names:
                    if not members:
                        raise ValueError("Worker empty stage has a separate review")
                    break
                if len(names) != 1 or names[0] == _MARKER:
                    raise ValueError("Worker unmarked stage is not a single path")
                name = names[0]
                parts.append(name)
                relative = "/".join(parts)
                if (
                    canonical_plugin_relative_path(relative).as_posix() != relative
                    or len(os.fsencode(relative)) > _MAX_UNMARKED_PATH_BYTES
                ):
                    raise ValueError("Worker unmarked path is invalid")
                visible = os.stat(name, dir_fd=current, follow_symlinks=False)
                if stat.S_ISDIR(visible.st_mode):
                    if depth >= _MAX_UNMARKED_DEPTH:
                        raise ValueError("Worker unmarked directory depth exceeded")
                    child = os.open(name, _DIR_FLAGS, dir_fd=current)
                    opened.append(child)
                    metadata = os.fstat(child)
                    if (
                        metadata.st_uid != os.geteuid()
                        or stat.S_IMODE(metadata.st_mode) != 0o700
                        or (metadata.st_dev, metadata.st_ino)
                        != (visible.st_dev, visible.st_ino)
                    ):
                        raise ValueError("Worker unmarked directory changed")
                    members.append(
                        self.values.member_type(
                            relative_path=relative,
                            kind="directory",
                            device=metadata.st_dev,
                            inode=metadata.st_ino,
                            mode=0o700,
                            size=0,
                            digest=None,
                        )
                    )
                    current = child
                    continue
                if not stat.S_ISREG(visible.st_mode):
                    raise ValueError("Worker unmarked member is unsafe")
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current
                )
                try:
                    before = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_uid != os.geteuid()
                        or before.st_nlink != 1
                        or stat.S_IMODE(before.st_mode) not in {0o600, 0o500}
                        or not 0 <= before.st_size <= 16 * 1024 * 1024
                        or (before.st_dev, before.st_ino)
                        != (visible.st_dev, visible.st_ino)
                    ):
                        raise ValueError("Worker unmarked file is unsafe")
                    digest = hash_exact_size(
                        descriptor,
                        before.st_size,
                        truncated="Worker unmarked file was truncated",
                    )
                    after = os.fstat(descriptor)
                    if os.read(descriptor, 1) or (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    ) != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ):
                        raise ValueError("Worker unmarked file changed")
                    members.append(
                        self.values.member_type(
                            relative_path=relative,
                            kind="file",
                            device=before.st_dev,
                            inode=before.st_ino,
                            mode=stat.S_IMODE(before.st_mode),
                            size=before.st_size,
                            digest=digest,
                        )
                    )
                finally:
                    os.close(descriptor)
                break
            else:
                raise ValueError("Worker unmarked stage exceeds depth budget")
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            return self.values.review_type(
                attempt_id=attempt_id,
                stage_device=stage.st_dev,
                stage_inode=stage.st_ino,
                members=tuple(members),
            )
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            raise self.error_type(
                "coding_worker_payload_unmarked_debt_unverified"
            ) from exc
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)
            if stage_fd >= 0:
                os.close(stage_fd)

    @contextmanager
    def _open_unmarked_repair_remainder(
        self,
        root_fd: int,
        stage_fd: int,
        stage_name: str,
        review: PayloadReview,
        *,
        allow_partial: bool,
    ) -> Iterator[tuple[list[tuple[int, str, int]], tuple[int, str, int] | None]]:
        directories: list[tuple[int, str, int]] = []
        leaf: tuple[int, str, int] | None = None
        try:
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            stage = os.fstat(stage_fd)
            if (
                stage.st_uid != os.geteuid()
                or stat.S_IMODE(stage.st_mode) != 0o700
                or (stage.st_dev, stage.st_ino)
                != (review.stage_device, review.stage_inode)
            ):
                raise ValueError("Worker unmarked stage changed")
            current = stage_fd
            count = 0
            for member in review.members:
                name = member.relative_path.rsplit("/", 1)[-1]
                names = set(os.listdir(current))
                if not names:
                    break
                if names != {name}:
                    raise ValueError("Worker unmarked remainder has foreign members")
                visible = os.stat(name, dir_fd=current, follow_symlinks=False)
                if member.kind == "directory":
                    child = os.open(name, _DIR_FLAGS, dir_fd=current)
                    directories.append((current, name, child))
                    opened = os.fstat(child)
                    if (
                        not stat.S_ISDIR(opened.st_mode)
                        or opened.st_uid != os.geteuid()
                        or stat.S_IMODE(opened.st_mode) != member.mode
                        or (opened.st_dev, opened.st_ino)
                        != (visible.st_dev, visible.st_ino)
                        or (opened.st_dev, opened.st_ino)
                        != (member.device, member.inode)
                    ):
                        raise ValueError("Worker unmarked directory changed")
                    current = child
                else:
                    descriptor = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=current,
                    )
                    leaf = (current, name, descriptor)
                    self._verify_unmarked_repair_file(
                        current, name, descriptor, member, visible
                    )
                count += 1
            if count != len(review.members) and not allow_partial:
                raise ValueError("Worker unmarked stage changed before repair intent")
            if (
                count == len(review.members)
                and review.members[-1].kind == "directory"
                and os.listdir(current)
            ):
                raise ValueError("Worker unmarked directory gained a member")
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            yield directories, leaf
        except (OSError, ValueError, TypeError) as exc:
            raise self.error_type("coding_worker_payload_debt_plan_stale") from exc
        finally:
            if leaf is not None:
                os.close(leaf[2])
            for _, _, descriptor in reversed(directories):
                os.close(descriptor)

    def _verify_unmarked_repair_file(
        self,
        parent_fd: int,
        name: str,
        descriptor: int,
        member: PayloadMember,
        visible: os.stat_result,
    ) -> None:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != member.mode
            or before.st_size != member.size
            or (before.st_dev, before.st_ino) != (visible.st_dev, visible.st_ino)
            or (before.st_dev, before.st_ino) != (member.device, member.inode)
        ):
            raise ValueError("Worker unmarked file changed")
        digest = hash_exact_size(
            descriptor, before.st_size, truncated="Worker unmarked file was truncated"
        )
        after = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            digest != member.digest
            or os.read(descriptor, 1)
            or (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError("Worker unmarked file changed")

    def _verify_unmarked_repair_remainder(
        self,
        root_fd: int,
        stage_fd: int,
        stage_name: str,
        review: PayloadReview,
        *,
        allow_partial: bool,
    ) -> None:
        with self._open_unmarked_repair_remainder(
            root_fd, stage_fd, stage_name, review, allow_partial=allow_partial
        ):
            pass

    def _remove_unmarked_repair_remainder(
        self,
        root_fd: int,
        stage_fd: int,
        stage_name: str,
        review: PayloadReview,
        *,
        allow_partial: bool,
    ) -> None:
        with self._open_unmarked_repair_remainder(
            root_fd, stage_fd, stage_name, review, allow_partial=allow_partial
        ) as (directories, leaf):
            if leaf is not None:
                parent, name, descriptor = leaf
                opened = os.fstat(descriptor)
                visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino):
                    raise self.error_type("coding_worker_payload_debt_plan_stale")
                os.unlink(name, dir_fd=parent)
                os.fsync(parent)
            for parent, name, descriptor in reversed(directories):
                opened = os.fstat(descriptor)
                visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (visible.st_dev, visible.st_ino) != (
                    opened.st_dev,
                    opened.st_ino,
                ) or os.listdir(descriptor):
                    raise self.error_type("coding_worker_payload_debt_plan_stale")
                os.rmdir(name, dir_fd=parent)
                os.fsync(parent)
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            if os.listdir(stage_fd):
                raise self.error_type("coding_worker_payload_debt_plan_stale")
            os.rmdir(stage_name, dir_fd=root_fd)
            os.fsync(root_fd)

    def _verify_debt_file(self, stage_fd: int, plan: PayloadPlan) -> None:
        parts = canonical_plugin_relative_path(plan.entrypoint).parts
        current = stage_fd
        opened: list[int] = []
        try:
            for component in parts[:-1]:
                expected = {_MARKER, component} if current == stage_fd else {component}
                if set(os.listdir(current)) != expected:
                    raise ValueError("Worker payload stage has extra members")
                current = os.open(component, _DIR_FLAGS, dir_fd=current)
                opened.append(current)
                directory = os.fstat(current)
                if (
                    directory.st_uid != os.geteuid()
                    or stat.S_IMODE(directory.st_mode) != 0o700
                ):
                    raise ValueError("Worker payload directory is unsafe")
            expected_leaf = {_MARKER, parts[-1]} if current == stage_fd else {parts[-1]}
            if set(os.listdir(current)) != expected_leaf:
                raise ValueError("Worker payload stage has extra members")
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            try:
                metadata = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o500
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_nlink != 1
                    or metadata.st_size != plan.payload_size
                ):
                    raise ValueError("Worker payload file is unsafe")
                digest = hash_exact_size(
                    file_fd,
                    plan.payload_size,
                    truncated="Worker payload file is truncated",
                )
                if os.read(file_fd, 1) or digest != plan.payload_digest:
                    raise ValueError("Worker payload file changed")
            finally:
                os.close(file_fd)
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    def _verify_complete_repair_remainder(
        self,
        root_fd: int,
        stage_fd: int,
        stage_name: str,
        plan: PayloadPlan,
    ) -> None:
        """Accept only a prefix of this owner's leaf, parents, marker deletion."""

        try:
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            stage = os.fstat(stage_fd)
            if (
                (stage.st_dev, stage.st_ino) != (plan.stage_device, plan.stage_inode)
                or stage.st_uid != os.geteuid()
                or stat.S_IMODE(stage.st_mode) != 0o700
            ):
                raise ValueError("Worker complete repair stage changed")
            parts = canonical_plugin_relative_path(plan.entrypoint).parts
            root_members = set(os.listdir(stage_fd))
            if root_members - {_MARKER, parts[0]}:
                raise ValueError("Worker complete repair has extra members")
            if _MARKER not in root_members:
                if root_members:
                    raise ValueError("Worker complete repair marker disappeared early")
                return
            marker, metadata = self._read_repair_file(
                stage_fd,
                _MARKER,
                maximum_bytes=_MAX_MARKER_BYTES,
                error_code="coding_worker_payload_debt_unverified",
            )
            if (
                metadata.st_nlink != 1
                or marker != canonical_json_bytes(plan_fields(plan)) + b"\n"
            ):
                raise ValueError("Worker complete repair marker changed")
            current = stage_fd
            opened: list[int] = []
            try:
                for index, component in enumerate(parts):
                    members = set(os.listdir(current))
                    allowed = (
                        {component, _MARKER} if current == stage_fd else {component}
                    )
                    if members - allowed:
                        raise ValueError("Worker complete repair has extra members")
                    if component not in members:
                        break
                    if index == len(parts) - 1:
                        self._verify_complete_repair_leaf(current, component, plan)
                        break
                    child = os.open(component, _DIR_FLAGS, dir_fd=current)
                    opened.append(child)
                    child_stat = os.fstat(child)
                    visible = os.stat(component, dir_fd=current, follow_symlinks=False)
                    if (
                        child_stat.st_uid != os.geteuid()
                        or stat.S_IMODE(child_stat.st_mode) != 0o700
                        or (child_stat.st_dev, child_stat.st_ino)
                        != (visible.st_dev, visible.st_ino)
                    ):
                        raise ValueError("Worker complete repair directory changed")
                    current = child
            finally:
                for descriptor in reversed(opened):
                    os.close(descriptor)
            self._require_visible_stage(stage_name, root_fd, stage_fd)
        except (OSError, ValueError, TypeError) as exc:
            raise self.error_type("coding_worker_payload_debt_unverified") from exc

    def _verify_complete_repair_leaf(
        self, parent_fd: int, name: str, plan: PayloadPlan
    ) -> None:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
        )
        try:
            opened = os.fstat(descriptor)
            visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o500
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
                or opened.st_size != plan.payload_size
                or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            ):
                raise ValueError("Worker complete repair payload changed")
            digest = hash_exact_size(
                descriptor,
                plan.payload_size,
                truncated="Worker complete repair payload was truncated",
            )
            if os.read(descriptor, 1) or digest != plan.payload_digest:
                raise ValueError("Worker complete repair payload changed")
        finally:
            os.close(descriptor)

    def _remove_verified_stage(
        self,
        root_fd: int,
        stage_fd: int,
        stage_name: str,
        plan: PayloadPlan,
    ) -> None:
        """Remove only the verified stage's members through captured directories."""

        self._require_visible_stage(stage_name, root_fd, stage_fd)
        self._verify_debt_file(stage_fd, plan)
        parts = canonical_plugin_relative_path(plan.entrypoint).parts
        parents = [stage_fd]
        try:
            for component in parts[:-1]:
                parents.append(os.open(component, _DIR_FLAGS, dir_fd=parents[-1]))
            os.unlink(parts[-1], dir_fd=parents[-1])
            os.fsync(parents[-1])
            for index in range(len(parts) - 2, -1, -1):
                os.rmdir(parts[index], dir_fd=parents[index])
                os.fsync(parents[index])
            os.unlink(_MARKER, dir_fd=stage_fd)
            os.fsync(stage_fd)
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            os.rmdir(stage_name, dir_fd=root_fd)
            os.fsync(root_fd)
        finally:
            for descriptor in reversed(parents[1:]):
                os.close(descriptor)

    def _remove_partial_stage(
        self, root_fd: int, stage_fd: int, stage_name: str, entrypoint: str
    ) -> None:
        """Clean a failed write from the original stage without following its name."""

        self._require_visible_stage(stage_name, root_fd, stage_fd)
        parts = canonical_plugin_relative_path(entrypoint).parts
        opened: list[int] = []
        current = stage_fd
        try:
            for component in parts[:-1]:
                allowed = {_MARKER, component} if current == stage_fd else {component}
                visible = set(os.listdir(current))
                if visible - allowed:
                    raise self.error_type("coding_worker_payload_stage_changed")
                if component not in visible:
                    break
                child = os.open(component, _DIR_FLAGS, dir_fd=current)
                directory = os.fstat(child)
                if (
                    directory.st_uid != os.geteuid()
                    or stat.S_IMODE(directory.st_mode) != 0o700
                ):
                    os.close(child)
                    raise self.error_type("coding_worker_payload_stage_changed")
                opened.append(child)
                current = child
            if len(opened) == len(parts) - 1:
                allowed_leaf = (
                    {_MARKER, parts[-1]} if current == stage_fd else {parts[-1]}
                )
                visible = set(os.listdir(current))
                if visible - allowed_leaf:
                    raise self.error_type("coding_worker_payload_stage_changed")
                if parts[-1] in visible:
                    leaf_fd = os.open(
                        parts[-1],
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=current,
                    )
                    try:
                        leaf = os.fstat(leaf_fd)
                        if (
                            not stat.S_ISREG(leaf.st_mode)
                            or leaf.st_uid != os.geteuid()
                            or leaf.st_nlink != 1
                            or stat.S_IMODE(leaf.st_mode) not in {0o600, 0o500}
                        ):
                            raise self.error_type("coding_worker_payload_stage_changed")
                    finally:
                        os.close(leaf_fd)
                    os.unlink(parts[-1], dir_fd=current)
                    os.fsync(current)
            for index in range(len(opened) - 1, -1, -1):
                parent = stage_fd if index == 0 else opened[index - 1]
                os.rmdir(parts[index], dir_fd=parent)
                os.fsync(parent)
            if _MARKER in os.listdir(stage_fd):
                marker_fd = os.open(
                    _MARKER,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=stage_fd,
                )
                try:
                    marker = os.fstat(marker_fd)
                    if (
                        not stat.S_ISREG(marker.st_mode)
                        or marker.st_uid != os.geteuid()
                        or marker.st_nlink != 1
                        or stat.S_IMODE(marker.st_mode) != 0o600
                    ):
                        raise self.error_type("coding_worker_payload_stage_changed")
                finally:
                    os.close(marker_fd)
                os.unlink(_MARKER, dir_fd=stage_fd)
                os.fsync(stage_fd)
            self._require_visible_stage(stage_name, root_fd, stage_fd)
            os.rmdir(stage_name, dir_fd=root_fd)
            os.fsync(root_fd)
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    def _require_private_visible_root(self, path: Path, descriptor: int) -> None:
        opened = os.fstat(descriptor)
        visible = path.lstat()
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) & 0o077
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise self.error_type("coding_worker_payload_root_unsafe")

    def _require_visible_stage(self, name: str, parent_fd: int, stage_fd: int) -> None:
        if stage_fd < 0:
            raise self.error_type("coding_worker_payload_stage_unavailable")
        opened = os.fstat(stage_fd)
        visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) & 0o077
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise self.error_type("coding_worker_payload_stage_changed")
