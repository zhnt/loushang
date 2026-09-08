"""Explicit native ownership of one private local endpoint-record directory."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from secrets import token_bytes, token_hex

from ._local_record_files import _RecordFiles, _RecordLeaseFiles
from ._local_record_values import (
    MAX_LOCAL_RECORD_BYTES,
    LocalConnectionRecordV1,
    LocalRecordError,
    LocalRecordErrorCodeV1,
    LocalRecordScopeV1,
    decode_connection_record,
    encode_connection_record,
    require_endpoint,
)


class LocalConnectionDirectoryV1:
    """Own exact-root files and reservations, including failed-attempt cleanup."""

    def __init__(self, root: Path) -> None:
        try:
            canonical = root.resolve() if isinstance(root, Path) else None
        except (OSError, RuntimeError):
            raise ValueError("local record root cannot be admitted") from None
        if (
            not isinstance(root, Path) or not root.is_absolute()
            or root != canonical or root == root.parent
            or (os.name == "nt" and (len(root.drive) != 2 or root.drive[1] != ":"))
        ):
            raise ValueError("local record root must be an admitted canonical local Path")
        self._root = root
        self._files: _RecordFiles | None = None
        self._leases: dict[str, LocalEndpointReservationV1] = {}
        self._closed = False

    def _prepare(self, *, create: bool) -> _RecordFiles:
        if self._closed:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLOSED)
        if self._files is None:
            if os.name == "nt":
                from ._windows_local_record import _WindowsRecordFiles
                self._files = _WindowsRecordFiles(self._root)
            else:
                from ._posix_local_record import _PosixRecordFiles
                self._files = _PosixRecordFiles(self._root)
        self._files.prepare(create=create)
        return self._files

    def acquire(self, endpoint: str) -> LocalEndpointReservationV1:
        require_endpoint(endpoint)
        try:
            files = self._prepare(create=True)
            if endpoint in self._leases:
                raise LocalRecordError(LocalRecordErrorCodeV1.LOCKED)
            reservation = LocalEndpointReservationV1(self, endpoint, files)
            self._leases[endpoint] = reservation
            try:
                reservation._files.acquire()
            except BaseException:
                reservation.close()
                raise
            return reservation
        except OSError:
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE) from None

    def read(self, endpoint: str) -> LocalConnectionRecordV1:
        require_endpoint(endpoint)
        try:
            files = self._prepare(create=False)
            snapshot = files.read(sha256(endpoint.encode()).hexdigest() + ".json")
            if snapshot is None:
                raise LocalRecordError(LocalRecordErrorCodeV1.NOT_FOUND)
            record = decode_connection_record(snapshot.payload)
            if record.endpoint != endpoint:
                raise LocalRecordError(LocalRecordErrorCodeV1.CORRUPT)
            return record
        except FileNotFoundError:
            raise LocalRecordError(LocalRecordErrorCodeV1.NOT_FOUND) from None
        except OSError:
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE) from None

    def close(self) -> None:
        self._closed = True
        failed = False
        for lease in tuple(self._leases.values()):
            try:
                lease.close()
            except (OSError, LocalRecordError):
                failed = True
        if not self._leases and self._files is not None:
            try:
                self._files.close()
            except (OSError, LocalRecordError):
                failed = True
            else:
                self._files = None
        if failed:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE)


class LocalEndpointReservationV1:
    """One stable OS lock; only its exact published file identity is retired."""

    def __init__(self, directory: LocalConnectionDirectoryV1, endpoint: str, files: _RecordFiles) -> None:
        self._directory = directory
        self._endpoint = endpoint
        self._files = _RecordLeaseFiles(files, sha256(endpoint.encode()).hexdigest())
        self._instance = token_hex(16)
        self._key = token_bytes(32)
        self._record: LocalConnectionRecordV1 | None = None
        self._published = False
        self._closed = False

    def publish(
        self, *, application_id: str, product_id: str, port: int,
        scopes: tuple[LocalRecordScopeV1, ...],
        session_discovery: bool = False,
    ) -> LocalConnectionRecordV1:
        if self._closed or self._directory._closed:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLOSED)
        record = LocalConnectionRecordV1(
            endpoint=self._endpoint, application_id=application_id, product_id=product_id,
            instance=self._instance, port=port, scopes=scopes, key=self._key,
            session_discovery=session_discovery,
        )
        if self._published or (self._record is not None and self._record != record):
            raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)
        self._record = record
        try:
            old = self._files.files.read(self._files.record_name)
            if old is not None:
                retained = decode_connection_record(old.payload)
                if retained.endpoint != self._endpoint:
                    raise LocalRecordError(LocalRecordErrorCodeV1.CORRUPT)
            self._files.publish(encode_connection_record(record), None if old is None else old.identity)
        except OSError:
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE) from None
        self._published = True
        return record

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._files.close()
        except (OSError, LocalRecordError):
            raise LocalRecordError(LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE) from None
        self._closed = True
        self._directory._leases.pop(self._endpoint, None)


__all__ = [
    "LocalConnectionDirectoryV1", "LocalConnectionRecordV1", "LocalEndpointReservationV1",
    "LocalRecordError", "LocalRecordErrorCodeV1", "LocalRecordScopeV1",
    "MAX_LOCAL_RECORD_BYTES", "decode_connection_record", "encode_connection_record",
]
