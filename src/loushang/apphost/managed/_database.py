"""Bounded Linux SQLite transactions for the optional managed registry.

This owner is a same-component friend of the native file owner. SQL never
escapes this package as an application capability. The stable registry lock
serializes cooperating processes; it is not a same-UID adversary boundary.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic

from ._files import (
    ManagedStorageError,
    PrivateManagedDirectory,
    _close_preserving_primary,
)

DATABASE_NAME = "registry.sqlite3"
DATABASE_LIMIT = 32 * 1024 * 1024
NORMAL_WATERLINE = 28 * 1024 * 1024
JOURNAL_LIMIT = 34 * 1024 * 1024
AUXILIARY_RESERVE = 8 * 1024 * 1024
CONTROL_RESERVE = 6 * 1024 * 1024
PAGE_SIZE = 4096
_LOCK = "registry.lock"
_APPLICATION_ID = 0x4C4D5558
_VERSION = 2
_SCHEMA = (
    "CREATE TABLE identity (namespace TEXT PRIMARY KEY NOT NULL) WITHOUT ROWID",
    "CREATE TABLE services (service_id TEXT PRIMARY KEY NOT NULL, "
    "product TEXT NOT NULL, workspace TEXT NOT NULL, profile TEXT NOT NULL, "
    "UNIQUE(product, workspace, profile)) WITHOUT ROWID",
    "CREATE TABLE muxes (name TEXT PRIMARY KEY NOT NULL, "
    "service_id TEXT NOT NULL REFERENCES services(service_id), "
    "operation_id TEXT NOT NULL UNIQUE) WITHOUT ROWID",
    "CREATE TABLE instances (service_id TEXT PRIMARY KEY NOT NULL REFERENCES services(service_id), "
    "revision INTEGER NOT NULL CHECK(revision>0), instance_id TEXT NOT NULL, "
    "attempt_id TEXT NOT NULL, phase TEXT NOT NULL, stop_requested INTEGER NOT NULL, "
    "process_exited INTEGER NOT NULL, application_cleanup_completed INTEGER NOT NULL, "
    "process_scope_settled INTEGER NOT NULL) WITHOUT ROWID",
)
_SCHEMA_ROWS = tuple(sorted((
    ("table", "identity", "identity", _SCHEMA[0]),
    ("table", "services", "services", _SCHEMA[1]),
    ("table", "muxes", "muxes", _SCHEMA[2]),
    ("table", "instances", "instances", _SCHEMA[3]),
)))


class ManagedDatabase:
    """Short-lived connections, strict schema, no automatic format migration."""

    def __init__(self, root: Path, namespace: str, *, create: bool = False) -> None:
        if sqlite3.threadsafety == 0:
            raise ManagedStorageError("unsupported")
        self._directory = PrivateManagedDirectory(root, create=create)
        self._namespace = namespace
        self._cleanup_connection: sqlite3.Connection | None = None
        try:
            with self._connection(create=create, read_only=not create):
                pass
        except BaseException as error:
            try:
                self.close()
            except BaseException:
                error.add_note("managed_database_cleanup_incomplete")
            raise

    def close(self) -> None:
        with self._directory._mutex:
            if self._cleanup_connection is not None:
                try:
                    self._cleanup_connection.close()
                except sqlite3.Error:
                    raise ManagedStorageError("unavailable") from None
                self._cleanup_connection = None
            self._directory.close()

    @property
    def cleanup_pending(self) -> bool:
        return self._cleanup_connection is not None

    def _admit_files(self, parent: int) -> None:
        limits = {_LOCK: 0, DATABASE_NAME: DATABASE_LIMIT,
                  DATABASE_NAME + "-journal": JOURNAL_LIMIT}
        # Enumerate with a bound before SQLite can open any sidecars. Unknown
        # WAL/SHM/temp files are debt, not an invitation to clean or recover them.
        with os.scandir(parent) as entries:
            for index, entry in enumerate(entries):
                if index >= len(limits) or entry.name not in limits:
                    raise ManagedStorageError("invalid_record")
                info = entry.stat(follow_symlinks=False)
                self._directory._validate(info)
                if info.st_size > limits[entry.name]:
                    raise ManagedStorageError("capacity")

    @contextmanager
    def _connection(
        self, *, create: bool = False, read_only: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        directory = self._directory
        connection = None
        guard = None
        with directory.lock(_LOCK, create=create), directory._operation() as parent:
            if self.cleanup_pending:
                raise ManagedStorageError("busy")
            try:
                self._admit_files(parent)
                try:
                    guard = directory._open(DATABASE_NAME, os.O_RDONLY if read_only else os.O_RDWR)
                except FileNotFoundError:
                    if not create:
                        raise
                    guard = directory._open(
                        DATABASE_NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL, create=True,
                    )
                identity = directory._validate(os.fstat(guard))
                # Root identity remains guarded while SQLite uses the retained
                # directory path. mode=rw prohibits SQLite from inventing a DB.
                mode = "ro" if read_only else "rw"
                uri = f"file:/proc/self/fd/{parent}/{DATABASE_NAME}?mode={mode}"
                # Every connection use/close, including debt retries on another
                # worker thread, is serialized by the directory mutex.
                connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None,
                                             check_same_thread=False)
                directory._check_named(DATABASE_NAME, identity)
                deadline = monotonic() + 2.0
                connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16 * 1024)
                connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16 * 1024)
                connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
                connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 32)
                connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 64)
                connection.enable_load_extension(False)
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("PRAGMA temp_store=MEMORY")
                connection.execute("PRAGMA cache_size=-1024")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA synchronous=FULL")
                if connection.execute("PRAGMA journal_mode").fetchone() != ("delete",):
                    raise ManagedStorageError("invalid_record")
                connection.execute("PRAGMA page_size=4096")
                if connection.execute("PRAGMA page_size").fetchone() != (PAGE_SIZE,):
                    raise ManagedStorageError("invalid_record")
                if connection.execute("PRAGMA max_page_count=8192").fetchone() != (8192,):
                    raise ManagedStorageError("capacity")
                connection.execute("PRAGMA journal_size_limit=35651584")
                header = (connection.execute("PRAGMA application_id").fetchone()[0],
                          connection.execute("PRAGMA user_version").fetchone()[0])
                if header == (0, 0) and create:
                    if connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone():
                        raise ManagedStorageError("invalid_record")
                    self._admit_capacity(connection, parent, growth=128 * 1024, normal=True)
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in _SCHEMA:
                        connection.execute(statement)
                    connection.execute("INSERT INTO identity VALUES (?)", (self._namespace,))
                    connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={_VERSION}")
                    connection.commit()
                    os.fsync(parent)
                elif header != (_APPLICATION_ID, _VERSION):
                    raise ManagedStorageError("invalid_record")
                self._validate_schema(connection)
                directory._check_named(DATABASE_NAME, identity)
                self._admit_files(parent)
                yield connection
                directory._check_named(DATABASE_NAME, identity)
                self._admit_files(parent)
            except sqlite3.Error as error:
                code = "busy" if getattr(error, "sqlite_errorcode", 0) in {
                    sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
                } else "unavailable"
                raise ManagedStorageError(code) from None
            finally:
                primary = sys.exception()
                failed = False
                if connection is not None:
                    try:
                        # close rolls back a not-yet-committed transaction.
                        connection.close()
                    except sqlite3.Error:
                        failed = True
                        self._cleanup_connection = connection
                if guard is not None:
                    try:
                        _close_preserving_primary(guard)
                    except ManagedStorageError:
                        failed = True
                if failed:
                    if primary is not None:
                        primary.add_note("managed_database_cleanup_incomplete")
                    else:
                        raise ManagedStorageError("unavailable") from None

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE sql IS NOT NULL ORDER BY name LIMIT 8"
        ).fetchall()
        if tuple(sorted(rows)) != _SCHEMA_ROWS:
            raise ManagedStorageError("invalid_record")
        if connection.execute("SELECT namespace FROM identity LIMIT 2").fetchall() != [
            (self._namespace,),
        ]:
            raise ManagedStorageError("conflict")
        if (
            connection.execute("SELECT count(*) FROM services").fetchone()[0] > 128
            or connection.execute("SELECT count(*) FROM muxes").fetchone()[0] > 4096
            or connection.execute("PRAGMA foreign_key_check").fetchone() is not None
        ):
            raise ManagedStorageError("invalid_record")

    @staticmethod
    def _admit_capacity(
        connection: sqlite3.Connection, parent: int, *, growth: int, normal: bool,
    ) -> None:
        pages = connection.execute("PRAGMA page_count").fetchone()[0]
        allocated = pages * PAGE_SIZE
        if allocated + growth > (NORMAL_WATERLINE if normal else DATABASE_LIMIT):
            raise ManagedStorageError("capacity")
        # Conservatively budget every current page being journaled (including
        # per-page headers), all possible DB growth, auxiliary and control space.
        journal_peak = allocated + pages * 8 + PAGE_SIZE * 4
        if journal_peak > JOURNAL_LIMIT:
            raise ManagedStorageError("capacity")
        usage = os.fstatvfs(parent)
        reserve = CONTROL_RESERVE if normal else 0
        needed = growth + journal_peak + AUXILIARY_RESERVE + reserve
        if usage.f_bavail * usage.f_frsize < needed:
            raise ManagedStorageError("capacity")

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with self._connection(read_only=not write) as connection:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
            yield connection
            self._directory._check()
            connection.commit()

    def admit_growth(self, connection: sqlite3.Connection) -> None:
        """Call after idempotent lookup but before a bounded actual mutation."""
        self._admit_capacity(connection, self._directory._check(),
                             growth=128 * 1024, normal=True)

    def admit_control(self, connection: sqlite3.Connection) -> None:
        """Small existing-instance updates may consume the control headroom."""
        self._admit_capacity(connection, self._directory._check(),
                             growth=16 * 1024, normal=False)
