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
from secrets import token_hex
from time import monotonic

from ._files import (
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
    _check_lock_wait,
)
from .contracts import _HEX32, ManagedContractError, _match

DATABASE_NAME = "registry.sqlite3"
DATABASE_LIMIT = 32 * 1024 * 1024
NORMAL_WATERLINE = 28 * 1024 * 1024
JOURNAL_LIMIT = 34 * 1024 * 1024
AUXILIARY_RESERVE = 8 * 1024 * 1024
CONTROL_RESERVE = 6 * 1024 * 1024
PAGE_SIZE = 4096
_LOCK = "registry.lock"
_APPLICATION_ID = 0x4C4D5558
_VERSION = 14
_TEMPORARY_ID_PREFIX = "74656d7000000000"
_MAX_TEMPORARY_SEQUENCE = 2**63 - 1
_SCHEMA = (
    "CREATE TABLE identity (namespace TEXT PRIMARY KEY NOT NULL, deployment TEXT NOT NULL, "
    "service_admission INTEGER NOT NULL CHECK(service_admission IN (0, 1)), "
    "temporary_high_water INTEGER NOT NULL CHECK(typeof(temporary_high_water)='integer' "
    "AND temporary_high_water BETWEEN 0 AND 9223372036854775807)) WITHOUT ROWID",
    "CREATE TABLE services (service_id TEXT PRIMARY KEY NOT NULL, "
    "product TEXT NOT NULL, workspace TEXT NOT NULL, profile TEXT NOT NULL, "
    "UNIQUE(product, workspace, profile)) WITHOUT ROWID",
    "CREATE TABLE muxes (name TEXT PRIMARY KEY NOT NULL, "
    "service_id TEXT NOT NULL REFERENCES services(service_id), "
    "operation_id TEXT NOT NULL UNIQUE, "
    "FOREIGN KEY(name, service_id, operation_id) "
    "REFERENCES mux_intents(name, service_id, operation_id)) WITHOUT ROWID",
    "CREATE TABLE instances (service_id TEXT PRIMARY KEY NOT NULL REFERENCES services(service_id), "
    "revision INTEGER NOT NULL CHECK(revision>0), instance_id TEXT NOT NULL, "
    "attempt_id TEXT NOT NULL, phase TEXT NOT NULL, stop_requested INTEGER NOT NULL, "
    "process_exited INTEGER NOT NULL, application_cleanup_completed INTEGER NOT NULL, "
    "process_scope_settled INTEGER NOT NULL, native_identity TEXT "
    "CHECK(native_identity IS NULL OR (typeof(native_identity)='text' "
    "AND length(native_identity)<=1024)), trace_application TEXT "
    "CHECK(trace_application IS NULL OR (typeof(trace_application)='text' AND length(trace_application)<=512)), "
    "UNIQUE(service_id, instance_id, attempt_id)) WITHOUT ROWID",
    "CREATE TABLE service_controls (service_id TEXT PRIMARY KEY NOT NULL REFERENCES services(service_id), "
    "record TEXT NOT NULL CHECK(typeof(record)='text' AND length(record)<=4096)) WITHOUT ROWID",
    "CREATE TABLE mux_authorities (operation_id TEXT PRIMARY KEY NOT NULL REFERENCES mux_intents(operation_id), "
    "instance_id TEXT NOT NULL CHECK(typeof(instance_id)='text' AND length(instance_id)=32), "
    "origin_instance_id TEXT NOT NULL CHECK(typeof(origin_instance_id)='text' AND length(origin_instance_id)=32), "
    "authority TEXT NOT NULL CHECK(typeof(authority)='text' AND length(authority)=64), "
    "created_instance_id TEXT, mux_space_id TEXT, "
    "CHECK((created_instance_id IS NULL AND mux_space_id IS NULL) OR "
    "(typeof(created_instance_id)='text' AND length(created_instance_id)=32 "
    "AND typeof(mux_space_id)='text' AND length(mux_space_id) BETWEEN 1 AND 512))) WITHOUT ROWID",
    "CREATE TABLE mux_intents (name TEXT NOT NULL, "
    "service_id TEXT NOT NULL REFERENCES services(service_id), "
    "operation_id TEXT PRIMARY KEY NOT NULL, "
    "UNIQUE(name, service_id, operation_id)) WITHOUT ROWID",
    "CREATE TABLE mux_close_authorities (operation_id TEXT PRIMARY KEY NOT NULL, "
    "creation_operation_id TEXT NOT NULL UNIQUE REFERENCES mux_authorities(operation_id), "
    "instance_id TEXT NOT NULL CHECK(typeof(instance_id)='text' AND length(instance_id)=32), "
    "origin_instance_id TEXT NOT NULL CHECK(typeof(origin_instance_id)='text' AND length(origin_instance_id)=32), "
    "authority TEXT NOT NULL CHECK(typeof(authority)='text' AND length(authority)=64), "
    "phase TEXT CHECK(phase IS NULL OR phase IN ('cleanup_pending', 'closed'))) WITHOUT ROWID",
    "CREATE TABLE service_transitions (service_id TEXT PRIMARY KEY NOT NULL, "
    "instance_id TEXT NOT NULL, attempt_id TEXT NOT NULL, "
    "started_revision INTEGER NOT NULL CHECK(started_revision>0), "
    "previous TEXT CHECK(previous IS NULL OR (typeof(previous)='text' AND length(previous)<=4096)), "
    "FOREIGN KEY(service_id, instance_id, attempt_id) REFERENCES instances(service_id, instance_id, attempt_id) "
    "DEFERRABLE INITIALLY DEFERRED) WITHOUT ROWID",
    "CREATE TABLE storage_allocations (allocation_id TEXT PRIMARY KEY NOT NULL, "
    "service_id TEXT NOT NULL REFERENCES services(service_id), kind TEXT NOT NULL, "
    "scope TEXT NOT NULL, slot INTEGER NOT NULL, capacity INTEGER NOT NULL, "
    "root_key TEXT NOT NULL CHECK(typeof(root_key)='text' AND length(root_key)=64), "
    "root_device INTEGER NOT NULL CHECK(typeof(root_device)='integer' AND root_device>=0), "
    "root_inode INTEGER NOT NULL CHECK(typeof(root_inode)='integer' AND root_inode>0), "
    "file_device INTEGER, file_inode INTEGER, UNIQUE(service_id, kind, scope, slot), "
    "CHECK(typeof(allocation_id)='text' AND length(allocation_id)=32), "
    "CHECK(typeof(slot)='integer' AND typeof(capacity)='integer' AND "
    "((kind='log' AND scope='' AND slot BETWEEN 0 AND 4 AND capacity=10485760) OR "
    "(kind='trace' AND scope='' AND slot BETWEEN 0 AND 1 AND capacity=10485760) OR "
    "(kind='temporary' AND typeof(scope)='text' AND length(scope)=32 AND slot BETWEEN 0 AND 255 "
    "AND capacity BETWEEN 4096 AND 134217728 AND capacity%4096=0))), "
    "CHECK((file_device IS NULL AND file_inode IS NULL) OR "
    "(typeof(file_device)='integer' AND file_device>=0 AND typeof(file_inode)='integer' AND file_inode>0))) WITHOUT ROWID",
    "CREATE TABLE service_aliases (name TEXT PRIMARY KEY NOT NULL, "
    "service_id TEXT NOT NULL UNIQUE REFERENCES services(service_id), "
    "operation_id TEXT NOT NULL UNIQUE CHECK(typeof(operation_id)='text' AND length(operation_id)=32), "
    "CHECK(typeof(name)='text' AND length(name) BETWEEN 1 AND 64)) WITHOUT ROWID",
    "CREATE TABLE storage_creation_origins (allocation_id TEXT PRIMARY KEY NOT NULL "
    "REFERENCES storage_allocations(allocation_id) ON DELETE CASCADE, "
    "origin_id TEXT NOT NULL CHECK(typeof(origin_id)='text' AND length(origin_id)=32 "
    "AND origin_id NOT GLOB '*[^0-9a-f]*')) WITHOUT ROWID",
)
_SCHEMA_ROWS = tuple(sorted((
    ("table", "identity", "identity", _SCHEMA[0]),
    ("table", "services", "services", _SCHEMA[1]),
    ("table", "muxes", "muxes", _SCHEMA[2]),
    ("table", "instances", "instances", _SCHEMA[3]),
    ("table", "service_controls", "service_controls", _SCHEMA[4]),
    ("table", "mux_authorities", "mux_authorities", _SCHEMA[5]),
    ("table", "mux_intents", "mux_intents", _SCHEMA[6]),
    ("table", "mux_close_authorities", "mux_close_authorities", _SCHEMA[7]),
    ("table", "service_transitions", "service_transitions", _SCHEMA[8]),
    ("table", "storage_allocations", "storage_allocations", _SCHEMA[9]),
    ("table", "service_aliases", "service_aliases", _SCHEMA[10]),
    ("table", "storage_creation_origins", "storage_creation_origins", _SCHEMA[11]),
)))


class ManagedDatabase:
    """Short-lived connections, strict schema, no automatic format migration."""

    def __init__(self, root: Path, namespace: str, *, create: bool = False, defer_open: bool = False,
                 exclusive_create: bool = False, create_parents: bool = False,
                 deployment_id: str | None = None, service_admission_required: bool | None = None) -> None:
        if sqlite3.threadsafety == 0:
            raise ManagedStorageError("unsupported")
        if type(defer_open) is not bool:
            raise ManagedStorageError("invalid_record")
        if deployment_id is not None:
            _match(deployment_id, _HEX32)
        if service_admission_required is not None and type(service_admission_required) is not bool:
            raise ManagedContractError()
        self._directory = PrivateManagedDirectory(root, create=create, defer_open=True,
                                                  exclusive_create=exclusive_create,
                                                  create_parents=create_parents)
        self._namespace = namespace
        self._create = create
        self._exclusive_create = exclusive_create
        self._deployment_id = deployment_id
        self._new_deployment_id = deployment_id or token_hex(16)
        self._service_admission_required = service_admission_required
        self._new_service_admission_required = bool(service_admission_required)
        self._file_identity: tuple[int, int] | None = None
        self._lock_identity: tuple[int, int] | None = None
        self._attempted = self._opened = self._closing = False
        self._cleanup_connection: sqlite3.Connection | None = None
        if defer_open:
            return
        try:
            self.open()
        except BaseException as error:
            try:
                self.close()
            except BaseException:
                error.add_note("managed_database_cleanup_incomplete")
            raise

    def open(self, *, deadline: float | None = None, wait_for_lock: bool = False) -> None:
        """Admit once after the caller has retained this container."""
        _check_deadline(deadline)
        _check_lock_wait(wait_for_lock, deadline)
        if self._attempted or self._closing:
            raise ManagedStorageError("closed")
        self._attempted = True
        self._directory.open(deadline=deadline)
        with self._connection(create=self._create, read_only=not self._create, deadline=deadline,
                              wait_for_lock=wait_for_lock):
            pass
        _check_deadline(deadline)
        self._opened = True

    def close(self) -> None:
        with self._directory._mutex:
            self._closing = True
            if self._cleanup_connection is not None:
                try:
                    self._cleanup_connection.close()
                except sqlite3.Error:
                    raise ManagedStorageError("unavailable") from None
                self._cleanup_connection = None
            self._directory.close()

    @property
    def cleanup_pending(self) -> bool:
        return self._cleanup_connection is not None or self._directory.cleanup_pending

    @property
    def deployment_id(self) -> str:
        if not self._opened or self._closing or self._deployment_id is None:
            raise ManagedStorageError("closed")
        return self._deployment_id

    @property
    def service_admission_required(self) -> bool:
        if not self._opened or self._closing or self._service_admission_required is None:
            raise ManagedStorageError("closed")
        return self._service_admission_required

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
        self, *, create: bool = False, read_only: bool = False, deadline: float | None = None,
        wait_for_lock: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        directory = self._directory
        connection = None
        guard = None
        with directory.lock(_LOCK, create=create, deadline=deadline,
                            exclusive_create=create and self._exclusive_create,
                            wait_for_lock=wait_for_lock), directory._operation(deadline=deadline) as parent:
            if self.cleanup_pending:
                raise ManagedStorageError("busy")
            try:
                lock_identity = directory._locks[_LOCK][1]
                if self._lock_identity is not None and self._lock_identity != lock_identity:
                    raise ManagedStorageError("conflict")
                self._admit_files(parent)
                try:
                    if create and self._exclusive_create:
                        guard = directory._open(DATABASE_NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL, create=True)
                    else:
                        guard = directory._open(DATABASE_NAME, os.O_RDONLY if read_only else os.O_RDWR)
                except FileExistsError:
                    raise ManagedStorageError("conflict") from None
                except FileNotFoundError:
                    if not create:
                        raise
                    guard = directory._open(
                        DATABASE_NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL, create=True,
                    )
                identity = directory._validate(os.fstat(guard))
                if self._file_identity is not None and self._file_identity != identity:
                    raise ManagedStorageError("conflict")
                # Root identity remains guarded while SQLite uses the retained
                # directory path. mode=rw prohibits SQLite from inventing a DB.
                mode = "ro" if read_only else "rw"
                uri = f"file:/proc/self/fd/{parent}/{DATABASE_NAME}?mode={mode}"
                # Every connection use/close, including debt retries on another
                # worker thread, is serialized by the directory mutex.
                _check_deadline(deadline)
                connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None,
                                             check_same_thread=False)
                directory._check_named(DATABASE_NAME, identity)
                sql_deadline = monotonic() + 2.0
                if deadline is not None:
                    sql_deadline = min(sql_deadline, deadline)
                connection.set_progress_handler(lambda: int(monotonic() >= sql_deadline), 1000)
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
                    connection.execute("INSERT INTO identity VALUES (?, ?, ?, 0)",
                                       (self._namespace, self._new_deployment_id,
                                        int(self._new_service_admission_required)))
                    connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={_VERSION}")
                    directory._sync_pending.add(parent)
                    connection.commit()
                    os.fsync(parent)
                    directory._sync_pending.discard(parent)
                elif header != (_APPLICATION_ID, _VERSION):
                    raise ManagedStorageError("invalid_record")
                self._validate_schema(connection)
                directory._check_named(DATABASE_NAME, identity)
                directory._check_named(_LOCK, lock_identity)
                self._admit_files(parent)
                _check_deadline(deadline)
                self._file_identity = identity
                self._lock_identity = lock_identity
                yield connection
                directory._check_named(DATABASE_NAME, identity)
                directory._check_named(_LOCK, lock_identity)
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
                        os.close(guard)
                    except OSError:
                        directory._uncertain_closes.add(guard)
                        failed = True
                if failed:
                    if primary is not None:
                        primary.add_note("managed_database_cleanup_incomplete")
                    else:
                        raise ManagedStorageError("unavailable") from None

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE sql IS NOT NULL ORDER BY name LIMIT 13"
        ).fetchall()
        if tuple(sorted(rows)) != _SCHEMA_ROWS:
            raise ManagedStorageError("invalid_record")
        if (connection.execute("SELECT count(*) FROM storage_creation_origins").fetchone()[0] > 4096
                or connection.execute("SELECT 1 FROM storage_creation_origins AS o LEFT JOIN storage_allocations AS a "
                    "ON a.allocation_id=o.allocation_id WHERE a.allocation_id IS NULL OR a.kind!='temporary' "
                    "OR typeof(o.origin_id)!='text' OR length(o.origin_id)!=32 "
                    "OR o.origin_id GLOB '*[^0-9a-f]*' LIMIT 1").fetchone() is not None):
            raise ManagedStorageError("invalid_record")
        identities = connection.execute("SELECT namespace, deployment, service_admission, temporary_high_water "
                                        "FROM identity LIMIT 2").fetchall()
        if len(identities) != 1 or identities[0][0] != self._namespace:
            raise ManagedStorageError("conflict")
        high_water = identities[0][3]
        if type(high_water) is not int or not 0 <= high_water <= _MAX_TEMPORARY_SEQUENCE:
            raise ManagedStorageError("invalid_record")
        if connection.execute(
            "SELECT 1 FROM storage_allocations WHERE "
            "allocation_id GLOB '*[^0-9a-f]*' OR "
            "(kind='temporary' AND (substr(allocation_id,1,16)!=? OR allocation_id<=? OR allocation_id>?)) "
            "OR (kind!='temporary' AND substr(allocation_id,1,16)=?) LIMIT 1",
            (_TEMPORARY_ID_PREFIX, _TEMPORARY_ID_PREFIX + "0" * 16,
             _TEMPORARY_ID_PREFIX + f"{high_water:016x}", _TEMPORARY_ID_PREFIX),
        ).fetchone() is not None:
            raise ManagedStorageError("invalid_record")
        deployment = identities[0][1]
        try:
            _match(deployment, _HEX32)
        except ManagedContractError:
            raise ManagedStorageError("invalid_record") from None
        if self._deployment_id is not None and self._deployment_id != deployment:
            raise ManagedStorageError("conflict")
        self._deployment_id = deployment
        required = identities[0][2]
        if type(required) is not int or required not in (0, 1):
            raise ManagedStorageError("invalid_record")
        if (self._service_admission_required is not None
                and self._service_admission_required != bool(required)):
            raise ManagedStorageError("conflict")
        self._service_admission_required = bool(required)
        if (
            connection.execute("SELECT count(*) FROM services").fetchone()[0] > 128
            or connection.execute("SELECT count(*) FROM service_aliases").fetchone()[0] > 128
            or connection.execute("SELECT count(*) FROM service_transitions").fetchone()[0] > 128
            or connection.execute("SELECT count(*) FROM muxes").fetchone()[0] > 4096
            or connection.execute("SELECT count(*) FROM mux_intents").fetchone()[0] > 4096
            or connection.execute("SELECT count(*) FROM mux_authorities").fetchone()[0] > 4096
            or connection.execute("SELECT count(*) FROM mux_close_authorities").fetchone()[0] > 4096
            or connection.execute("SELECT count(*) FROM storage_allocations").fetchone()[0] > 4096
            or connection.execute("SELECT coalesce(sum(capacity),0) FROM storage_allocations "
                                  "WHERE kind IN ('log','trace')").fetchone()[0] > 200 * 1024 * 1024
            or connection.execute("SELECT coalesce(sum(capacity),0) FROM storage_allocations "
                                  "WHERE kind='temporary'").fetchone()[0] > 512 * 1024 * 1024
            or connection.execute("SELECT 1 FROM storage_allocations WHERE kind='temporary' "
                                  "GROUP BY service_id,scope HAVING sum(capacity)>134217728 LIMIT 1").fetchone() is not None
            or connection.execute("SELECT 1 FROM mux_intents JOIN mux_close_authorities USING(operation_id) LIMIT 1").fetchone() is not None
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
    def transaction(self, *, write: bool = False, deadline: float | None = None,
                    wait_for_lock: bool = False) -> Iterator[sqlite3.Connection]:
        if not self._opened or self._closing:
            raise ManagedStorageError("closed")
        with self._connection(read_only=not write, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
            yield connection
            self._directory._check()
            _check_deadline(deadline)
            connection.commit()

    def admit_growth(self, connection: sqlite3.Connection) -> None:
        """Call after idempotent lookup but before a bounded actual mutation."""
        self._admit_capacity(connection, self._directory._check(),
                             growth=128 * 1024, normal=True)

    def admit_control(self, connection: sqlite3.Connection) -> None:
        """Small existing-instance updates may consume the control headroom."""
        self._admit_capacity(connection, self._directory._check(),
                             growth=16 * 1024, normal=False)
