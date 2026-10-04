"""Native Windows custody for inert Coding Worker opt-in decisions.

The caller supplies the Product-pinned state-root descriptor and holds its GC
gate. This journal persists decisions; it cannot derive selection or issue a
Worker activation receipt.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import BinaryIO, Literal

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import journal_file_lock_at
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_regular_file_stream_names,
    windows_stat_at,
)

from .package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
    _decode_coding_worker_opt_in_history,
)
from .package_product_worker_policy import CodingWorkerOptInV1

_NAME = "worker-opt-in.jsonl"
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_MAX_EVENTS = 4096
_MAX_BYTES = 32 * 1024 * 1024


class CodingWindowsWorkerOptInJournal:
    """Strict append-only decisions under one Product-pinned Windows root."""

    def __init__(self, path: Path, *, scope_id: str) -> None:
        if not isinstance(path, Path) or not path.is_absolute() or path.name != _NAME:
            raise ValueError("Windows Worker opt-in path is invalid")
        if (
            not isinstance(scope_id, str)
            or len(scope_id) > 128
            or _OPAQUE.fullmatch(scope_id) is None
        ):
            raise ValueError("Windows Worker opt-in scope is invalid")
        self._path = path
        self._scope_id = scope_id

    @property
    def path(self) -> Path:
        return self._path

    def current(
        self, plugin_id: str, *, directory_fd: int
    ) -> CodingWorkerOptInDecisionV1 | None:
        self._require_plugin_id(plugin_id)
        self._require_root(directory_fd)
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(directory_fd)
            self._assert_visible_root(directory_fd)
            lock_name = _NAME + ".lock"
            try:
                self._validate_lock(directory_fd, acl)
            except FileNotFoundError:
                try:
                    windows_stat_at(directory_fd, _NAME)
                except FileNotFoundError:
                    self._assert_visible_root(directory_fd)
                    return None
                raise CodingWorkerOptInJournalError(
                    "coding_worker_opt_in_lock_missing"
                ) from None
            with journal_file_lock_at(directory_fd, lock_name, "shared"):
                initialized = self._validate_lock(directory_fd, acl)
                raw = self._read_raw(directory_fd, acl)
                if raw is None:
                    if initialized:
                        raise CodingWorkerOptInJournalError(
                            "coding_worker_opt_in_orphan_lock"
                        )
                    self._assert_visible_root(directory_fd)
                    return None
                if not initialized:
                    raise CodingWorkerOptInJournalError(
                        "coding_worker_opt_in_lock_corrupt"
                    )
                events = self._decode(raw)
            self._assert_visible_root(directory_fd)
            return next(
                (event for event in reversed(events) if event.plugin_id == plugin_id),
                None,
            )

    def change(
        self,
        *,
        directory_fd: int,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        action: Literal["allow", "revoke"],
        opt_in: CodingWorkerOptInV1 | None,
    ) -> CodingWorkerOptInDecisionV1:
        self._require_plugin_id(plugin_id)
        if (
            not isinstance(operation_id, str)
            or len(operation_id) > 128
            or _OPAQUE.fullmatch(operation_id) is None
            or type(expected_generation) is not int
            or expected_generation < 0
            or action not in {"allow", "revoke"}
            or (action == "allow" and not isinstance(opt_in, CodingWorkerOptInV1))
            or (action == "revoke" and opt_in is not None)
        ):
            raise ValueError("Windows Worker opt-in command is invalid")
        self._require_root(directory_fd)
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(directory_fd)
            self._assert_visible_root(directory_fd)
            self._prepare_lock(directory_fd, acl)
            with journal_file_lock_at(
                directory_fd, _NAME + ".lock", "exclusive"
            ) as lock_handle:
                initialized = self._validate_lock(directory_fd, acl)
                raw = self._read_raw(directory_fd, acl)
                if (raw is None and initialized) or (
                    raw is not None and not initialized
                ):
                    raise CodingWorkerOptInJournalError(
                        "coding_worker_opt_in_lock_corrupt"
                    )
                events = () if raw is None else self._decode(raw)
                replay = next(
                    (event for event in events if event.operation_id == operation_id),
                    None,
                )
                if replay is not None:
                    if (
                        replay.plugin_id != plugin_id
                        or replay.action != action
                        or replay.opt_in != opt_in
                        or replay.generation != expected_generation + 1
                    ):
                        raise CodingWorkerOptInJournalError(
                            "coding_worker_opt_in_operation_conflict"
                        )
                    self._assert_visible_root(directory_fd)
                    return replay
                previous = next(
                    (
                        event
                        for event in reversed(events)
                        if event.plugin_id == plugin_id
                    ),
                    None,
                )
                generation = 0 if previous is None else previous.generation
                if generation != expected_generation:
                    raise CodingWorkerOptInJournalError("coding_worker_opt_in_stale")
                if action == "revoke" and previous is None:
                    raise CodingWorkerOptInJournalError("coding_worker_opt_in_absent")
                kill = 0 if previous is None else previous.kill_switch_generation
                if action == "revoke":
                    kill += 1
                if action == "allow" and (
                    opt_in is None
                    or opt_in.plugin_id != plugin_id
                    or opt_in.owner_selection_generation != generation + 1
                    or opt_in.kill_switch_generation != kill
                ):
                    raise CodingWorkerOptInJournalError(
                        "coding_worker_opt_in_generation_invalid"
                    )
                if len(events) >= _MAX_EVENTS:
                    raise CodingWorkerOptInJournalError("coding_worker_opt_in_capacity")
                decision = CodingWorkerOptInDecisionV1.create(
                    journal_revision=len(events) + 1,
                    scope_id=self._scope_id,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    generation=generation + 1,
                    kill_switch_generation=kill,
                    action=action,
                    opt_in=opt_in,
                )
                line = canonical_json_bytes(decision.to_dict()) + b"\n"
                if len(raw or b"") + len(line) > _MAX_BYTES:
                    raise CodingWorkerOptInJournalError("coding_worker_opt_in_capacity")
                if not initialized:
                    self._mark_lock_initialized(lock_handle)
                self._append(directory_fd, acl, expected=raw, line=line)
                self._assert_visible_root(directory_fd)
                return decision

    def _prepare_lock(self, directory_fd: int, acl: WindowsPrivateDirectoryAcl) -> None:
        lock_name = _NAME + ".lock"
        try:
            windows_stat_at(directory_fd, lock_name)
        except FileNotFoundError:
            try:
                windows_stat_at(directory_fd, _NAME)
            except FileNotFoundError:
                pass
            else:
                raise CodingWorkerOptInJournalError(
                    "coding_worker_opt_in_lock_missing"
                ) from None
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                lock_name,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                lock_name,
                create_new=False,
                write=True,
                read_control=True,
            )
            created = False
        else:
            created = True
        try:
            acl.validate(descriptor)
            self._require_plain_stream(descriptor)
            if created:
                if os.write(descriptor, b"\0") != 1:
                    raise OSError("Windows Worker opt-in lock write failed")
                windows_flush_file(descriptor)
            elif os.fstat(descriptor).st_size != 1:
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_lock_corrupt")
        finally:
            os.close(descriptor)
        if created:
            windows_flush_directory(directory_fd)

    def _validate_lock(
        self, directory_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> bool:
        descriptor = open_windows_regular_file_at(
            directory_fd,
            _NAME + ".lock",
            create_new=False,
            write=False,
            read_control=True,
        )
        try:
            acl.validate(descriptor)
            self._require_plain_stream(descriptor)
            if os.fstat(descriptor).st_size != 1:
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_lock_corrupt")
            state = os.read(descriptor, 1)
            if state not in {b"\0", b"\1"}:
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_lock_corrupt")
            return state == b"\1"
        finally:
            os.close(descriptor)

    @staticmethod
    def _mark_lock_initialized(handle: BinaryIO) -> None:
        """Publish history intent before the first append; crashes then fail closed."""

        handle.seek(0)
        if handle.read(1) != b"\0":
            raise CodingWorkerOptInJournalError("coding_worker_opt_in_lock_corrupt")
        handle.seek(0)
        if handle.write(b"\1") != 1:
            raise OSError("Windows Worker opt-in lock commit failed")
        handle.flush()
        windows_flush_file(handle.fileno())

    def _read_raw(
        self, directory_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> bytes | None:
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                _NAME,
                create_new=False,
                write=False,
                read_control=True,
            )
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            acl.validate(source.fileno())
            self._require_plain_stream(source.fileno())
            return source.read(_MAX_BYTES + 1)

    def _append(
        self,
        directory_fd: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        expected: bytes | None,
        line: bytes,
    ) -> None:
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                _NAME,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                _NAME,
                create_new=False,
                write=True,
                read_control=True,
            )
            created = False
        else:
            created = True
        with os.fdopen(descriptor, "r+b") as output:
            acl.validate(output.fileno())
            self._require_plain_stream(output.fileno())
            observed = output.read(_MAX_BYTES + 1)
            if (created and (expected is not None or observed)) or (
                not created and observed != expected
            ):
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_changed")
            output.seek(0, os.SEEK_END)
            remaining = memoryview(line)
            while remaining:
                written = output.write(remaining)
                if written is None or written <= 0:
                    raise OSError("Windows Worker opt-in append made no progress")
                remaining = remaining[written:]
            output.flush()
            windows_flush_file(output.fileno())
        if created:
            windows_flush_directory(directory_fd)

    def _decode(self, raw: bytes) -> tuple[CodingWorkerOptInDecisionV1, ...]:
        if not raw or len(raw) > _MAX_BYTES or not raw.endswith(b"\n"):
            raise CodingWorkerOptInJournalError("coding_worker_opt_in_corrupt")
        try:
            events = _decode_coding_worker_opt_in_history(
                raw, path=self._path, scope_id=self._scope_id
            )
            if raw != b"".join(
                canonical_json_bytes(event.to_dict()) + b"\n" for event in events
            ):
                raise ValueError("Windows Worker opt-in bytes changed")
            return events
        except (UnicodeError, ValueError) as exc:
            raise CodingWorkerOptInJournalError("coding_worker_opt_in_corrupt") from exc

    def _assert_visible_root(self, directory_fd: int) -> None:
        try:
            if not os.path.samestat(os.fstat(directory_fd), self._path.parent.lstat()):
                raise CodingWorkerOptInJournalError(
                    "coding_worker_opt_in_state_root_changed"
                )
        except OSError as exc:
            raise CodingWorkerOptInJournalError(
                "coding_worker_opt_in_state_root_changed"
            ) from exc

    @staticmethod
    def _require_root(directory_fd: int) -> None:
        if os.name != "nt" or type(directory_fd) is not int or directory_fd < 0:
            raise OSError("Windows Worker opt-in requires a pinned Product root")

    @staticmethod
    def _require_plugin_id(plugin_id: str) -> None:
        if (
            not isinstance(plugin_id, str)
            or len(plugin_id) > 128
            or _IDENTIFIER.fullmatch(plugin_id) is None
        ):
            raise ValueError("Windows Worker opt-in Plugin id is invalid")

    @staticmethod
    def _require_plain_stream(descriptor: int) -> None:
        if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
            raise CodingWorkerOptInJournalError("coding_worker_opt_in_stream_invalid")


__all__ = ["CodingWindowsWorkerOptInJournal"]
