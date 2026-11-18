"""Closed history names and borrowed source capture; no Product/GC authority."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar, Generic, Self, TypeVar, cast

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages._file_consumption import consume_file
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)
from loushang.harness.worker.history._windows_semantic_contracts import _DIGEST


@dataclass(frozen=True, slots=True)
class WindowsHistoryNames:
    exact: frozenset[str]
    patterns: tuple[re.Pattern[str], ...]

    def require_known(self, names: tuple[str, ...]) -> None:
        for name in names:
            if not name.casefold().startswith(("worker-", ".worker-")):
                continue
            if name not in self.exact and not any(
                pattern.fullmatch(name) is not None for pattern in self.patterns
            ):
                raise ValueError("Windows Worker GC state owner is unrecognized")


_SourceT = TypeVar("_SourceT")


@dataclass(frozen=True, slots=True)
class WindowsHistorySourceCapture(Generic[_SourceT]):
    names: WindowsHistoryNames
    source_file_type: Callable[..., _SourceT]
    non_source_names: frozenset[str]
    base_stage_names: frozenset[str]
    max_files: int
    max_file_bytes: int
    max_total_bytes: int

    @contextmanager
    def capture(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        allow_preparation_stage: bool,
        allow_checkpoint_stage: bool,
        allow_base_stage: bool,
    ) -> Iterator[tuple[tuple[str, ...], tuple[_SourceT, ...]]]:
        before = tuple(windows_listdir_at(root))
        self.names.require_known(before)
        if (
            (
                "worker-history-preparation-v1.json.stage" in before
                and not allow_preparation_stage
            )
            or (
                "worker-history-checkpoint-v1.json.stage" in before
                and not allow_checkpoint_stage
            )
            or (not allow_base_stage and self.base_stage_names.intersection(before))
        ):
            raise ValueError("Windows Worker history stage remains")
        names = tuple(
            sorted(
                name
                for name in before
                if name.casefold().startswith(("worker-", ".worker-"))
                and name not in self.non_source_names
            )
        )
        if any(name.casefold().endswith(".stage") for name in names):
            raise ValueError("Windows Worker history stage remains")
        if len(names) > self.max_files:
            raise ValueError("Windows Worker history inventory exceeds bound")
        files: list[_SourceT] = []
        total = 0
        for name in names:
            descriptor = open_windows_regular_file_at(
                root, name, create_new=False, write=False, read_control=True
            )
            with os.fdopen(descriptor, "rb") as source:
                acl.validate(source.fileno())
                if windows_regular_file_stream_names(source.fileno()) != ("::$DATA",):
                    raise ValueError("Windows Worker history stream changed")
                opened = os.fstat(source.fileno())
                size, digest = consume_file(
                    source,
                    max_bytes=min(self.max_file_bytes, self.max_total_bytes - total),
                    chunk_size=64 * 1024,
                    size_error=lambda: ValueError(
                        "Windows Worker history bytes exceed bound"
                    ),
                )
                total += size
                closed = os.fstat(source.fileno())
                if (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_size,
                    opened.st_mtime_ns,
                    opened.st_ctime_ns,
                ) != (
                    closed.st_dev,
                    closed.st_ino,
                    closed.st_size,
                    closed.st_mtime_ns,
                    closed.st_ctime_ns,
                ) or size != opened.st_size:
                    raise ValueError("Windows Worker history source changed")
                visible = windows_stat_at(root, name)
                if (
                    not os.path.samestat(closed, visible)
                    or visible.st_size != size
                    or visible.st_mtime_ns != closed.st_mtime_ns
                    or visible.st_ctime_ns != closed.st_ctime_ns
                ):
                    raise ValueError("Windows Worker history source changed")
                files.append(
                    self.source_file_type(
                        name=name,
                        size=size,
                        sha256_digest=digest,
                    )
                )
        yield before, tuple(files)
        if set(windows_listdir_at(root)) != set(before):
            raise ValueError("Windows Worker history inventory changed")


WINDOWS_WORKER_HISTORY_CUTOVER_NAME = "worker-history-cutover-v1.json"

WINDOWS_WORKER_BASE_FILES = (
    ("optIn", "worker-history-base-opt-in-v1.json"),
    ("receipt", "worker-history-base-receipt-v1.json"),
    ("supervisor", "worker-history-base-supervisor-v1.json"),
    ("c5", "worker-history-base-c5-v1.json"),
    ("launchIntent", "worker-history-base-launch-intent-v1.json"),
    ("nativeProvisioning", "worker-history-base-native-provisioning-v1.json"),
)

WINDOWS_WORKER_BASE_NAMES = frozenset(name for _, name in WINDOWS_WORKER_BASE_FILES)

WINDOWS_WORKER_BASE_STAGE_NAMES = frozenset(
    name + ".stage" for name in WINDOWS_WORKER_BASE_NAMES
)

WINDOWS_WORKER_RETIREMENT_STEMS = (
    "worker-stage",
    "worker-partial-stage",
    "worker-unlaunched-stage",
    "worker-crash-stage",
)

WINDOWS_WORKER_RETIREMENT_NAME = re.compile(
    r"(?:worker-stage|worker-partial-stage|worker-unlaunched-stage|worker-crash-stage)-(?:retire|root-delete|retired)-"
    r"([0-9a-f]{32})\.json(?:\.stage)?\Z"
)

WINDOWS_WORKER_RETIREMENT_NAME_PREFIXES = tuple(
    stem + "-" for stem in WINDOWS_WORKER_RETIREMENT_STEMS
)

_INTENT = re.compile(r"worker-launch-intent-[0-9a-f]{32}\.json\Z")

_NATIVE = re.compile(r"worker-native-provisioning-[0-9a-f]{32}\.jsonl(?:\.lock)?\Z")

_C5_HEAD = re.compile(r"worker-activation-state\.h[0-9]{8}\.json\Z")

_WINDOWS_HISTORY_EXACT = (
    frozenset(
        {
            "worker-activation-state.jsonl",
            "worker-activation-state.jsonl.lock",
            "worker-supervisor.jsonl",
            "worker-supervisor.jsonl.lock",
            "worker-activation-receipts.jsonl",
            "worker-activation-receipts.jsonl.lock",
            "worker-opt-in.jsonl",
            "worker-opt-in.jsonl.lock",
            "worker-native-release-approvals.jsonl",
            "worker-native-release-approvals.jsonl.lock",
            "worker-native-backend-release-v1.whl",
            "worker-history-preparation-v1.json",
            "worker-history-preparation-v1.json.stage",
            "worker-history-checkpoint-v1.json",
            "worker-history-checkpoint-v1.json.stage",
        }
    )
    | WINDOWS_WORKER_BASE_NAMES
    | WINDOWS_WORKER_BASE_STAGE_NAMES
)

WINDOWS_WORKER_NON_SOURCE_NAMES = (
    frozenset(
        {
            "worker-history-preparation-v1.json",
            "worker-history-preparation-v1.json.stage",
            "worker-history-checkpoint-v1.json",
            "worker-history-checkpoint-v1.json.stage",
        }
    )
    | WINDOWS_WORKER_BASE_NAMES
    | WINDOWS_WORKER_BASE_STAGE_NAMES
)


def windows_worker_history_names() -> WindowsHistoryNames:
    return WindowsHistoryNames(
        _WINDOWS_HISTORY_EXACT,
        (_INTENT, _NATIVE, _C5_HEAD, WINDOWS_WORKER_RETIREMENT_NAME),
    )


class _WindowsHistorySourceFileMethods:
    __slots__ = ()

    @staticmethod
    def _file_limit() -> int:
        raise NotImplementedError

    name: str
    size: int
    sha256_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or not self.name.casefold().startswith(("worker-", ".worker-"))
            or self.name.casefold().endswith(".stage")
            or self.name in WINDOWS_WORKER_NON_SOURCE_NAMES
            or type(self.size) is not int
            or not 0 <= self.size <= self._file_limit()
            or type(self.sha256_digest) is not str
            or _DIGEST.fullmatch(self.sha256_digest) is None
        ):
            raise ValueError("Windows Worker history source file is invalid")
        windows_worker_history_names().require_known((self.name,))

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256_digest}

    @classmethod
    def _from_file_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != {"name", "size", "sha256"}:
            raise ValueError("Windows Worker history source file is invalid")
        return cast(Callable[..., Self], cls)(
            name=value["name"],
            size=value["size"],
            sha256_digest=value["sha256"],
        )


class _WindowsHistorySourceSnapshotMethods:
    __slots__ = ()
    _source_file_type: ClassVar[type[_WindowsHistorySourceFileMethods]]

    @staticmethod
    def _source_limits() -> tuple[int, int, int]:
        raise NotImplementedError

    @classmethod
    def _source_reader(
        cls,
    ) -> WindowsHistorySourceCapture[_WindowsHistorySourceFileMethods]:
        return WindowsHistorySourceCapture(
            windows_worker_history_names(),
            cls._source_file_type,
            WINDOWS_WORKER_NON_SOURCE_NAMES,
            WINDOWS_WORKER_BASE_STAGE_NAMES,
            *cls._source_limits(),
        )

    scope_id: str
    store_id: str
    lease_owner_revision: int
    files: tuple[_WindowsHistorySourceFileMethods, ...]
    snapshot_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 0
            or type(self.files) is not tuple
            or len(self.files) > self._source_limits()[0]
            or any(type(item) is not self._source_file_type for item in self.files)
            or self.files != tuple(sorted(self.files, key=lambda item: item.name))
            or len({item.name.casefold() for item in self.files}) != len(self.files)
            or sum(item.size for item in self.files) > self._source_limits()[2]
            or type(self.snapshot_digest) is not str
            or self.snapshot_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker history source snapshot is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "leaseOwnerRevision": self.lease_owner_revision,
            "files": [item.to_dict() for item in self.files],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "snapshotDigest": self.snapshot_digest}

    @classmethod
    def _from_source_dict(cls, value: object) -> Self:
        if (
            type(value) is not dict
            or set(value)
            != {
                "scopeId",
                "storeId",
                "leaseOwnerRevision",
                "files",
                "snapshotDigest",
            }
            or type(value["files"]) is not list
        ):
            raise ValueError("Windows Worker history source snapshot is invalid")
        return cast(Callable[..., Self], cls)(
            scope_id=value["scopeId"],
            store_id=value["storeId"],
            lease_owner_revision=value["leaseOwnerRevision"],
            files=tuple(
                cls._source_file_type._from_file_dict(item) for item in value["files"]
            ),
            snapshot_digest=value["snapshotDigest"],
        )

    @classmethod
    def _from_files(
        cls,
        *,
        scope_id: str,
        store_id: str,
        lease_owner_revision: int,
        files: tuple[_WindowsHistorySourceFileMethods, ...],
    ) -> Self:
        unsigned = {
            "scopeId": scope_id,
            "storeId": store_id,
            "leaseOwnerRevision": lease_owner_revision,
            "files": [item.to_dict() for item in files],
        }
        return cast(Callable[..., Self], cls)(
            scope_id=scope_id,
            store_id=store_id,
            lease_owner_revision=lease_owner_revision,
            files=files,
            snapshot_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


class _WindowsHistorySettlementMethods:
    __slots__ = ()
    _source_snapshot_type: ClassVar[type[_WindowsHistorySourceSnapshotMethods]]
    _review_kind: ClassVar[str]
    source_snapshot: _WindowsHistorySourceSnapshotMethods
    review_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.source_snapshot) is not self._source_snapshot_type
            or type(self.review_digest) is not str
            or self.review_digest
            != sha256(
                canonical_json_bytes(
                    {
                        "reviewKind": self._review_kind,
                        "sourceSnapshotDigest": self.source_snapshot.snapshot_digest,
                    }
                )
            ).hexdigest()
        ):
            raise ValueError("Windows Worker history settlement review is invalid")

    @classmethod
    def _from_snapshot(
        cls, source_snapshot: _WindowsHistorySourceSnapshotMethods
    ) -> Self:
        return cast(Callable[..., Self], cls)(
            source_snapshot=source_snapshot,
            review_digest=sha256(
                canonical_json_bytes(
                    {
                        "reviewKind": cls._review_kind,
                        "sourceSnapshotDigest": source_snapshot.snapshot_digest,
                    }
                )
            ).hexdigest(),
        )
