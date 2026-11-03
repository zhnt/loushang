"""Publish a complete witness before granting any data-creation authority.

Private adaptation of the original retained lease and rooted I/O. A staging
directory has no database identity until its no-replace publication succeeds.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
from collections.abc import Callable
from secrets import token_hex

from loushang.harness.journal._directory_lease import DirectoryWriterLease
from loushang.harness.journal._rooted_io import RootedFileIO

from .writer_lease import TranscriptStoreAdmissionError, TranscriptWriterError

_STAGE_PREFIX = ".admission-stage-"


def is_unpublished_stage(name: str) -> bool:
    suffix = name.removeprefix(_STAGE_PREFIX)
    return (
        name.startswith(_STAGE_PREFIX)
        and len(suffix) == 32
        and all(c in "0123456789abcdef" for c in suffix)
    )


def _rename_noreplace(parent: int, source: str, target: str) -> None:
    function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if function is None:
        raise OSError(errno.ENOTSUP, "atomic admission publication unavailable")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(parent, os.fsencode(source), parent, os.fsencode(target), 1) != 0:
        number = ctypes.get_errno() or errno.EIO
        raise OSError(number, os.strerror(number), target)


class AdmissionWitnessLease(DirectoryWriterLease):
    _error_type = TranscriptWriterError
    _lock_directory = ".store-admission-locks"
    _hash_domain = "transcript-store-admission/v1"

    def __init__(
        self, *args, initial_record_factory: Callable[[], dict] | None = None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.initial_record_factory = initial_record_factory
        self.initial_record: dict | None = None
        self._publication_io: RootedFileIO | None = None

    @property
    def cleanup_pending(self) -> bool:
        return super().cleanup_pending or bool(
            self._publication_io and self._publication_io.cleanup_pending
        )

    def acquire(self) -> None:
        if self.initial_record_factory is None:
            super().acquire()
            return
        self._enter()
        target = self._root
        try:
            if self._attempted or self._closing:
                raise self._error_type("closed")
            self._root = target.with_name(_STAGE_PREFIX + token_hex(16))
            super().acquire()
            assert self._canonical == self._root
            self._fds["publication_parent"] = os.open(
                target.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            parent = self._fds["publication_parent"]
            self._validate_root_parent(parent)
            if not os.path.samestat(
                os.fstat(self._fds["root"]),
                os.stat(self._root.name, dir_fd=parent, follow_symlinks=False),
            ):
                raise self._error_type("conflict")
            self.initial_record = self.initial_record_factory()
            self._publication_io = RootedFileIO(self._root, self._fds["root"])
            self._publication_io.atomic_write(
                self._root / "admission.json", json.dumps(self.initial_record).encode()
            )
            self._publication_io.cleanup()
            self.check_binding(owner_id=self._owner_id, authority_id=self._authority_id)
            self._sync_pending.update(
                ("root", "directory", "lock", "publication_parent")
            )
            self._sync_root_parents()
            # The rename may take effect without returning an acknowledgement.
            self._sync_pending.add("publication_parent")
            _rename_noreplace(parent, self._root.name, target.name)
            self._root = self._canonical = target
            self._sync_root_parents()
            self.check_binding(owner_id=self._owner_id, authority_id=self._authority_id)
        except FileExistsError:
            raise TranscriptStoreAdmissionError(
                "conflict",
                stage="publish_witness",
                record_path=target / "admission.json",
            ) from None
        except OSError as error:
            raise TranscriptStoreAdmissionError(
                "unavailable",
                stage="publish_witness",
                record_path=target / "admission.json",
            ) from error
        finally:
            self._mutex.release()

    def close(self) -> None:
        if self._publication_io is not None:
            self._publication_io.cleanup()
        super().close()
