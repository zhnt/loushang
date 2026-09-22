"""Private family membership facts retained by TranscriptStoreAdmission.

No Session database, migration authority, background work, or independent close
owner. Every descriptor below belongs to the calling admission's lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from secrets import token_hex
from typing import TYPE_CHECKING, Any

from loushang.harness.journal._rooted_io import RootedFileIO

from .store_admission import (
    TranscriptStoreBinding,
    _identity,
    _missing,
    _StoreRoot,
    _unique,
    _WitnessLease,
)
from .writer_lease import TranscriptWriterError

if TYPE_CHECKING:
    from .store_admission import TranscriptStoreAdmission

_VERSION = "transcript-store-family/v1"
_MEMBER = "transcript-store-admission/v2"
_MAX_MEMBERS = 128
_MAX_STATE = 512
_MAX_BYTES = 131072


class _SharedFamily:
    def __init__(self, admission: TranscriptStoreAdmission, state_root: Path) -> None:
        self.admission = admission
        self.data_root = admission.root.parent
        self.key = hashlib.sha256(f"{_VERSION}\0{os.geteuid()}\0{self.data_root}".encode()).hexdigest()
        self.root = state_root / f"family-{self.key}"
        self._existing = _WitnessLease(self.root, _VERSION, self.key, create_lock=False)
        self._fresh = _WitnessLease(self.root, _VERSION, self.key, create_root=True, exclusive_root=True)
        self._data_existing = _StoreRoot(self.data_root, _VERSION, self.key)
        self._data_fresh = _StoreRoot(self.data_root, _VERSION, self.key, create_root=True, exclusive_root=True)
        self._state = _StoreRoot(state_root, _VERSION, self.key)
        self._assets = _StoreRoot(self.data_root / "session-assets", _VERSION, self.key)
        self._locks = _StoreRoot(self.data_root / "session-assets/.locks", _VERSION, self.key)
        self._writers = _StoreRoot(self.data_root / ".session-blob-writers", _VERSION, self.key)
        self._data: _StoreRoot | None = None
        self._lease: _WitnessLease | None = None
        self._io: RootedFileIO | None = None
        self._record: dict[str, Any] | None = None
        self._probes: list[tuple[RootedFileIO, _StoreRoot]] = []

    @property
    def present(self) -> bool:
        return not _missing(self.root)

    @property
    def _owners(self):
        return (self._assets, self._locks, self._writers, self._data_existing, self._data_fresh,
                self._state, self._existing, self._fresh)

    @property
    def cleanup_pending(self) -> bool:
        return (any(item.cleanup_pending for item in self._owners) or bool(self._io and self._io.cleanup_pending)
                or any(port.cleanup_pending for port, _ in self._probes))

    def _freshness(self) -> None:
        """No unbounded inference or adoption of an unrecognized old family."""
        if not _missing(self.data_root):
            self._data = self._data_existing
            self._data.acquire()
            port = RootedFileIO(self.data_root, self._data._fds["root"])
            self._probes.append((port, self._data))
            try:
                names, complete = port.scan_names(limit=_MAX_MEMBERS + 3)
                if names or not complete:
                    raise TranscriptWriterError("conflict")
            finally:
                port.cleanup()
        self.inspect_state_evidence(allow_legacy=False)

    def inspect_state_evidence(self, *, allow_legacy: bool) -> None:
        """Never discard a surviving v2 member merely because its family vanished."""
        if not _missing(self._state._root):
            self._state.acquire()
            port = RootedFileIO(self._state._root, self._state._fds["root"])
            self._probes.append((port, self._state))
            try:
                names, complete = port.scan_names(limit=_MAX_STATE)
                if not complete:
                    raise TranscriptWriterError("unavailable")
                families, members = {}, []
                for name in names:
                    # v1 protects its exact member key, not an inferred global
                    # mapping of every future path to a vanished parent.
                    raw = json.loads(port.read_bytes(self._state._root / name / "admission.json", max_bytes=_MAX_BYTES),
                                     object_pairs_hook=_unique)
                    if name.startswith("family-"):
                        self._validate_record(raw)
                        if name != "family-" + raw["family"]:
                            raise TranscriptWriterError("conflict")
                        if raw["incarnation"] in families:
                            raise TranscriptWriterError("conflict")
                        families[raw["incarnation"]] = {key: value["id"] for key, value in raw["members"].items()}
                        if raw["data_path"] == str(self.data_root):
                            raise TranscriptWriterError("conflict")
                    elif type(raw) is dict and raw.get("version") == _MEMBER:
                        members.append((name, raw))
                    elif type(raw) is dict and raw.get("version") == "transcript-store-admission/v1":
                        self._validate_legacy_evidence(port, name, raw)
                        if name == self.admission._key:
                            raise TranscriptWriterError("conflict")
                        if (not allow_legacy and self._data is not None
                                and raw["parent"] == list(self._data.binding().root_identity)):
                            raise TranscriptWriterError("conflict")
                        # This neither enrolls the old store nor grants access
                        # to its data. All v2 evidence still must pair below.
                    else:
                        raise TranscriptWriterError("conflict")
                for name, record in members:
                    family = families.get(record.get("family"))
                    member = family.get(name) if family is not None else None
                    if member is None or member != record.get("member") or record.get("store") != name:
                        raise TranscriptWriterError("conflict")
            finally:
                port.cleanup()

    @staticmethod
    def _validate_legacy_evidence(port: RootedFileIO, name: str, record: dict[str, Any]) -> None:
        version = "transcript-store-admission/v1"
        if (set(record) != {"version", "store", "operation", "phase", "witness", "lock", "root", "parent"}
                or record["version"] != version or not _hex(name, 64) or record["store"] != name
                or not _hex(record["operation"], 32) or record["phase"] != "initialized"):
            raise TranscriptWriterError("conflict")
        for field in ("witness", "lock", "root", "parent"):
            _require_identity(record[field])
        lock_name = hashlib.sha256(json.dumps([version, name], ensure_ascii=True).encode()).hexdigest() + ".lock"
        with port.directory() as state:
            witness = state.child(name)
            status = witness.stat()
            lock = witness.child(".store-admission-locks").file(lock_name).stat()
            reread = json.loads(witness.file("admission.json").read_bytes(max_bytes=4096), object_pairs_hook=_unique)
            if (reread != record or record["witness"] != [status.st_dev, status.st_ino]
                    or record["lock"] != [lock.st_dev, lock.st_ino]):
                raise TranscriptWriterError("conflict")

    def _read(self) -> dict[str, Any]:
        assert self._io is not None and self._lease is not None
        self._lease.check_binding(owner_id=_VERSION, authority_id=self.key)
        record = json.loads(self._io.read_bytes(self.root / "admission.json", max_bytes=_MAX_BYTES),
                            object_pairs_hook=_unique)
        self._validate_record(record)
        if (record["family"] != self.key or record["data_path"] != str(self.data_root)
                or record["witness"] != list(_identity(self._lease._fds["root"]))
                or record["lock"] != list(_identity(self._lease._fds["lock"]))):
            raise TranscriptWriterError("conflict")
        return record

    @staticmethod
    def _validate_record(record: Any) -> None:
        if (type(record) is not dict or set(record) != {"version", "family", "incarnation", "phase", "revision",
                "data_path", "witness", "lock", "data", "shared", "members"}
                or record["version"] != _VERSION or not _hex(record["family"], 64)
                or not _hex(record["incarnation"], 32) or type(record["phase"]) is not str
                or record["phase"] not in {"initializing", "initialized"}
                or type(record["revision"]) is not int or not 0 <= record["revision"] <= 2**63 - 1
                or type(record["data_path"]) is not str or len(record["data_path"]) > 4096
                or not Path(record["data_path"]).is_absolute()
                or ".." in Path(record["data_path"]).parts or str(Path(record["data_path"])) != record["data_path"]
                or type(record["members"]) is not dict or len(record["members"]) > _MAX_MEMBERS):
            raise TranscriptWriterError("conflict")
        expected_key = hashlib.sha256(f"{_VERSION}\0{os.geteuid()}\0{record['data_path']}".encode()).hexdigest()
        if expected_key != record["family"]:
            raise TranscriptWriterError("conflict")
        for name in ("witness", "lock"):
            _require_identity(record[name])
        if record["phase"] == "initializing":
            if record["data"] is not None or record["shared"] is not None or record["members"]:
                raise TranscriptWriterError("conflict")
            return
        _require_identity(record["data"])
        if type(record["shared"]) is not list or len(record["shared"]) != 3:
            raise TranscriptWriterError("conflict")
        for identity in record["shared"]:
            _require_identity(identity)
        if len({tuple(value) for value in [record["data"], *record["shared"]]}) != 4:
            raise TranscriptWriterError("conflict")
        names, identifiers = set(), set()
        roots = {tuple(value) for value in [record["data"], *record["shared"]]}
        for key, member in record["members"].items():
            if (not _hex(key, 64) or type(member) is not dict
                    or set(member) != {"name", "id", "phase", "root", "witness", "lock"}
                    or not _hex(member["id"], 32) or type(member["phase"]) is not str
                    or member["phase"] not in {"initializing", "initialized"}
                    or type(member["name"]) is not str or not member["name"] or len(member["name"].encode()) > 255
                    or member["name"] in {".", "..", "session-assets", ".session-blob-writers"}
                    or any(c in member["name"] for c in ("/", "\\", "\0"))
                    or member["name"] in names or member["id"] in identifiers):
                raise TranscriptWriterError("conflict")
            member_key = hashlib.sha256(
                f"transcript-store-admission/v1\0{os.geteuid()}\0{Path(record['data_path']) / member['name']}".encode(),
            ).hexdigest()
            if key != member_key:
                raise TranscriptWriterError("conflict")
            names.add(member["name"])
            identifiers.add(member["id"])
            for name in ("root", "witness", "lock"):
                if member["phase"] == "initializing":
                    if member[name] is not None:
                        raise TranscriptWriterError("conflict")
                else:
                    _require_identity(member[name])
            if member["phase"] == "initialized":
                identity = tuple(member["root"])
                if identity in roots:
                    raise TranscriptWriterError("conflict")
                roots.add(identity)

    def _write(self) -> None:
        assert self._io is not None and self._record is not None and self._lease is not None
        self._validate_record(self._record)
        payload = json.dumps(self._record, separators=(",", ":")).encode()
        if len(payload) > _MAX_BYTES:
            raise TranscriptWriterError("capacity")
        self._lease.check_binding(owner_id=_VERSION, authority_id=self.key)
        self._io.atomic_write(self.root / "admission.json", payload)
        if self._read() != self._record:
            raise TranscriptWriterError("conflict")

    def open(self, *, inspect_only: bool) -> TranscriptStoreBinding | None:
        admission = self.admission
        existing = self.present
        if not existing:
            if inspect_only or not admission._may_create():
                raise TranscriptWriterError("unavailable")
            self._freshness()
        elif _missing(self.root / "admission.json"):
            raise TranscriptWriterError("incomplete")
        self._lease = self._existing if existing else self._fresh
        self._lease.acquire()
        if self._lease._canonical != self.root:
            raise TranscriptWriterError("conflict")
        self._io = RootedFileIO(self.root, self._lease._fds["root"])
        if existing:
            self._record = self._read()
            if self._record["phase"] != "initialized":
                raise TranscriptWriterError("incomplete")
            self._data = self._data_existing
            self._data.acquire()
        else:
            self._record = dict(version=_VERSION, family=self.key, incarnation=token_hex(16), phase="initializing",
                                revision=0, data_path=str(self.data_root), witness=list(_identity(self._lease._fds["root"])),
                                lock=list(_identity(self._lease._fds["lock"])), data=None, shared=None, members={})
            self._write()
            if self._data is None:
                self._data = self._data_fresh
                self._data.acquire()
        assert self._data is not None
        self._assets.acquire_child(self._data, create=not existing)
        self._locks.acquire_child(self._assets, create=not existing)
        self._writers.acquire_child(self._data, create=not existing)
        for item in (self._assets, self._locks, self._writers):
            item._validate_directory(item._fds["root"], private=True)
        data_id = self._data.binding().root_identity
        shared = (self._assets.binding().root_identity, self._locks.binding().root_identity,
                  self._writers.binding().root_identity)
        if existing:
            if self._record["data"] != list(data_id) or self._record["shared"] != [list(value) for value in shared]:
                raise TranscriptWriterError("conflict")
        else:
            self._record.update(phase="initialized", data=list(data_id), shared=[list(value) for value in shared])
            self._write()
        member = self._record["members"].get(admission._key)
        if member is None:
            if not _missing(admission.root) or not _missing(admission.witness_root):
                raise TranscriptWriterError("conflict")
            if inspect_only:
                return None
            if not admission._may_create():
                raise TranscriptWriterError("unavailable")
            if len(self._record["members"]) >= _MAX_MEMBERS or self._record["revision"] > 2**63 - 3:
                raise TranscriptWriterError("capacity")
            member = dict(name=admission.root.name, id=token_hex(16), phase="initializing", root=None, witness=None, lock=None)
            self._record["members"][admission._key] = member
            self._record["revision"] += 1
            self._write()
            admission._witness = admission._fresh
            admission._witness.acquire()
            if admission._witness._canonical != admission.witness_root:
                raise TranscriptWriterError("conflict")
            admission._io = RootedFileIO(admission.witness_root, admission._witness._fds["root"])
            record = admission._record()
            record.update(version=_MEMBER, family=self._record["incarnation"], member=member["id"])
            admission._write(record)
            if not admission._may_create():
                raise TranscriptWriterError("unavailable")
            admission._open_store(create=True)
            assert admission._store is not None
            physical = admission._store.binding()
            record.update(phase="initialized", root=list(physical.root_identity), parent=list(data_id))
            admission._write(record)
            member.update(phase="initialized", root=record["root"], witness=record["witness"], lock=record["lock"])
            self._record["revision"] += 1
            self._write()
        else:
            if member["phase"] != "initialized" or member["name"] != admission.root.name:
                raise TranscriptWriterError("incomplete")
            if _missing(admission.witness_root / "admission.json"):
                raise TranscriptWriterError("incomplete")
            admission._witness = admission._existing
            admission._witness.acquire()
            if admission._witness._canonical != admission.witness_root:
                raise TranscriptWriterError("conflict")
            admission._io = RootedFileIO(admission.witness_root, admission._witness._fds["root"])
            record = admission._read()
            admission._open_store(create=False)
            assert admission._store is not None
            physical = admission._store.binding()
            if (record["phase"] != "initialized" or member["root"] != list(physical.root_identity)
                    or record["root"] != member["root"] or record["parent"] != list(data_id)
                    or record["witness"] != member["witness"] or record["lock"] != member["lock"]):
                raise TranscriptWriterError("conflict")
        return TranscriptStoreBinding(physical.root_identity, data_id, self._record["incarnation"], member["id"], shared)

    def validate_member(self, record: dict[str, Any]) -> dict[str, Any]:
        admission = self.admission
        if self._record is None or admission._witness is None:
            raise TranscriptWriterError("conflict")
        member = self._record["members"].get(admission._key)
        if (set(record) != {"version", "store", "operation", "phase", "witness", "lock", "root", "parent", "family", "member"}
                or record["version"] != _MEMBER or record["store"] != admission._key or not _hex(record["operation"], 32)
                or member is None or record["family"] != self._record["incarnation"] or record["member"] != member["id"]
                or type(record["phase"]) is not str or record["phase"] not in {"initializing", "initialized"}
                or record["witness"] != list(_identity(admission._witness._fds["root"]))
                or record["lock"] != list(_identity(admission._witness._fds["lock"]))):
            raise TranscriptWriterError("conflict")
        for name in ("root", "parent"):
            if record["phase"] == "initializing":
                if record[name] is not None:
                    raise TranscriptWriterError("conflict")
            else:
                _require_identity(record[name])
        return record

    def check(self) -> None:
        assert self._data is not None and self.admission._store is not None
        binding = self.admission._binding
        record = self._read()
        if self._record is None or record["incarnation"] != self._record["incarnation"]:
            raise TranscriptWriterError("conflict")
        self._record = record
        for item in (self._assets, self._locks, self._writers):
            item._validate_directory(item._fds["root"], private=True)
        own = self.admission._read()
        member = record["members"].get(self.admission._key)
        if (binding is None or member is None or member["phase"] != "initialized"
                or member["id"] != binding.member_id or member["root"] != list(binding.root_identity)
                or own["phase"] != "initialized" or own["root"] != member["root"]
                or own["witness"] != member["witness"] or own["lock"] != member["lock"]
                or self.admission._store.binding().root_identity != binding.root_identity
                or self._data.binding().root_identity != binding.parent_identity
                or record["data"] != list(binding.parent_identity)
                or record["shared"] != [list(value) for value in binding.shared_identities or ()]
                or tuple(item.binding().root_identity for item in (self._assets, self._locks, self._writers)) != binding.shared_identities):
            raise TranscriptWriterError("conflict")

    def release_locks(self) -> None:
        if self._io is not None:
            self._io.cleanup()
        self._existing.close()
        self._fresh.close()
        self._state.close()  # Freshness scanning is complete; this is not a handoff pin.

    def close(self) -> None:
        failures = []
        for port, _ in self._probes:
            try:
                port.cleanup()
            except Exception as error:
                failures.append(error)
        if self._io is not None:
            try:
                self._io.cleanup()
            except Exception as error:
                failures.append(error)
        for owner in self._owners:
            if any(parent is owner and port.cleanup_pending for port, parent in self._probes):
                continue
            if owner in (self._existing, self._fresh) and self._io is not None and self._io.cleanup_pending:
                continue
            try:
                owner.close()
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]


def _hex(value: Any, length: int) -> bool:
    return type(value) is str and len(value) == length and all(c in "0123456789abcdef" for c in value)


def _require_identity(value: Any) -> None:
    if (type(value) is not list or len(value) != 2
            or any(type(item) is not int or not 0 <= item < 2**64 for item in value) or value[1] == 0):
        raise TranscriptWriterError("conflict")
