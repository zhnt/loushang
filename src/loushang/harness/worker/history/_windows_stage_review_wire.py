"""Wire traversal for the existing four Windows stage-review record formats.

Fixed schema traversal and semantic evidence proofs share the existing Worker
owner. Concrete records retain nominal fields, wire/fingerprint Profile and
public errors. No method acquires Product or native mutation authority.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.worker.history._base_codec import _unchanged
from loushang.harness.worker.history._windows_recovery import WindowsRecoveryAttemptV1
from loushang.harness.worker.history._windows_semantic_contracts import (
    _ATTEMPT,
    _DIGEST,
    _LaunchIntentFacts,
    launch_matches_intent,
    native_matches_intent,
    no_effect_history_matches,
)

WINDOWS_STAGE_REVIEW_MAX_BYTES = 32768


class _WindowsStageReviewWireMethods:
    __slots__ = ()
    _fingerprint_domain: ClassVar[bytes]
    _record_kind: ClassVar[str]
    _record_error: ClassVar[type[Exception]]
    _record_error_code: ClassVar[str]
    _record_schema: ClassVar[RecordSchema]

    @classmethod
    def _record_maximum(cls) -> int:
        return WINDOWS_STAGE_REVIEW_MAX_BYTES

    @classmethod
    def _bind_record_schema(cls) -> None:
        cls._record_schema = RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "directory_identities",
                decoder=lambda values: tuple((p, tuple(i)) for p, i in values),
            ),
            *(
                RecordField(
                    name,
                    decoder=lambda v: None if v is None else tuple(v),
                )
                for name in ("stage_identity", "marker_identity", "executable_identity")
                if name != "marker_identity" or cls._record_kind != "partial"
            ),
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > cls._record_maximum():
            raise cls._record_error(cls._record_error_code)
        kind = cls._record_kind
        label = {
            "full": "Windows Worker stage review",
            "crash": "Windows Worker crash stage review",
            "partial": "Windows Worker partial-stage review",
            "reserved": "Windows Worker reserved review",
        }[kind]
        detail = label.removesuffix(" review") if kind == "crash" else label
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value) != cls._record_schema.keys | {"version"}
                or value["version"] != 1
            ):
                suffix = "shape changed" if kind == "crash" else "fields changed"
                raise ValueError(f"{label} {suffix}")
            directories = value["directoryIdentities"]
            invalid_directories = type(directories) is not list or any(
                type(item) is not list or len(item) != 2 or type(item[1]) is not list
                for item in directories
            )
            identities = ("stageIdentity", "markerIdentity", "executableIdentity")
            if kind in {"full", "crash"}:
                if invalid_directories:
                    raise ValueError(f"{detail} directories changed")
                for name in identities:
                    if type(value[name]) is not list:
                        raise ValueError(f"{detail} identity changed")
            elif kind == "reserved":
                if invalid_directories or any(
                    type(value[n]) is not list for n in identities
                ):
                    raise ValueError(
                        "Windows Worker reserved review identities changed"
                    )
            else:
                if invalid_directories or type(value["stageIdentity"]) is not list:
                    raise ValueError("Windows Worker partial-stage identities changed")
                executable = value["executableIdentity"]
                if executable is not None and type(executable) is not list:
                    raise ValueError(
                        "Windows Worker partial-stage file identity changed"
                    )
            record = cls._record_schema.decode(cast(Callable[..., Self], cls), value)
            if record.to_bytes() != raw:
                suffix = "bytes changed" if kind == "partial" else "encoding changed"
                raise ValueError(f"{detail} {suffix}")
            return record
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise cls._record_error(cls._record_error_code) from error

    _from_record_bytes = from_bytes

    def to_bytes(self) -> bytes:
        return canonical_json_bytes({**self._record_schema.encode(self), "version": 1})

    @property
    def fingerprint(self) -> str:
        return sha256(self._fingerprint_domain + self.to_bytes()).hexdigest()

    @classmethod
    def _payload_maximum(cls) -> int:
        return 16 * 1024 * 1024


FileIdentity = tuple[int, int, int, int, int]


def _valid_identity(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 5
        and all(type(item) is int and item >= 0 for item in value)
        and value[1] > 0
        and value[2] == 1
    )


def _valid_directories(
    directories: tuple[tuple[str, FileIdentity], ...],
) -> bool:
    for index, member in enumerate(directories):
        if (
            type(member) is not tuple
            or len(member) != 2
            or not _valid_identity(member[1])
        ):
            return False
        path = member[0]
        if type(path) is not str:
            return False
        try:
            canonical = canonical_plugin_relative_path(path)
        except ValueError:
            return False
        if canonical.as_posix() != path or len(canonical.parts) != index + 1:
            return False
        if index and "/".join(canonical.parts[:-1]) != directories[index - 1][0]:
            return False
    return True


class _WindowsCompleteStageReviewMethods(_WindowsStageReviewWireMethods):
    __slots__ = ()
    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    native_revision: int
    supervisor_revision: int
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_relative_path(self.entrypoint)
        except ValueError as exc:
            raise ValueError(
                "Windows Worker stage review entrypoint is invalid"
            ) from exc
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (self.intent_fingerprint, self.executable_digest)
            )
            or any(
                type(value) is not int or value < 1
                for value in (
                    self.lease_owner_revision,
                    self.native_revision,
                    self.supervisor_revision,
                )
            )
            or path.as_posix() != self.entrypoint
            or not _valid_identity(self.stage_identity)
            or not _valid_identity(self.marker_identity)
            or not _valid_identity(self.executable_identity)
            or self.executable_identity[3] < 1
            or self.executable_identity[3] > self._payload_maximum()
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) != len(path.parts) - 1
            or any(
                type(item) is not tuple
                or len(item) != 2
                or item[0] != "/".join(path.parts[: index + 1])
                or not _valid_identity(item[1])
                for index, item in enumerate(self.directory_identities)
            )
        ):
            raise ValueError("Windows Worker stage review is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "directoryIdentities": [
                [path, list(identity)] for path, identity in self.directory_identities
            ],
            "entrypoint": self.entrypoint,
            "executableDigest": self.executable_digest,
            "executableIdentity": list(self.executable_identity),
            "intentFingerprint": self.intent_fingerprint,
            "leaseOwnerRevision": self.lease_owner_revision,
            "markerIdentity": list(self.marker_identity),
            "nativeRevision": self.native_revision,
            "stageIdentity": list(self.stage_identity),
            "supervisorRevision": self.supervisor_revision,
            "version": 1,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


class _WindowsCrashStageReviewMethods(_WindowsStageReviewWireMethods):
    __slots__ = ()
    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    repaired_lease_id: str
    lease_repair_revision: int
    native_revision: int
    supervisor_revision: int | None
    native_spec_fingerprint: str
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_relative_path(self.entrypoint)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Windows Worker crash stage entrypoint is invalid"
            ) from exc
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.intent_fingerprint,
                    self.native_spec_fingerprint,
                    self.executable_digest,
                )
            )
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or type(self.repaired_lease_id) is not str
            or _DIGEST.fullmatch(self.repaired_lease_id) is None
            or type(self.lease_repair_revision) is not int
            or not 1 <= self.lease_repair_revision < self.lease_owner_revision
            or type(self.native_revision) is not int
            or self.native_revision < 1
            or (
                self.supervisor_revision is not None
                and (
                    type(self.supervisor_revision) is not int
                    or self.supervisor_revision < 1
                )
            )
            or path.as_posix() != self.entrypoint
            or not _valid_identity(self.stage_identity)
            or not _valid_identity(self.marker_identity)
            or not _valid_identity(self.executable_identity)
            or not 0 < self.executable_identity[3] <= 16 * 1024 * 1024
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) != len(path.parts) - 1
            or any(
                type(item) is not tuple
                or len(item) != 2
                or item[0] != "/".join(path.parts[: index + 1])
                or not _valid_identity(item[1])
                for index, item in enumerate(self.directory_identities)
            )
        ):
            raise ValueError("Windows Worker crash stage review is invalid")


class _WindowsPartialStageReviewMethods(_WindowsStageReviewWireMethods):
    __slots__ = ()
    attempt_id: str
    lease_owner_revision: int
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    entrypoint: str | None
    executable_identity: FileIdentity | None
    executable_digest: str | None

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or not _valid_identity(self.stage_identity)
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) > self._depth_maximum()
            or not _valid_directories(self.directory_identities)
            or (self.entrypoint is None) != (self.executable_identity is None)
            or (self.entrypoint is None) != (self.executable_digest is None)
        ):
            raise ValueError("Windows Worker partial-stage review is invalid")
        if self.entrypoint is not None:
            try:
                path = canonical_plugin_relative_path(self.entrypoint)
            except ValueError as exc:
                raise ValueError(
                    "Windows Worker partial-stage entrypoint is invalid"
                ) from exc
            parent = "/".join(path.parts[:-1])
            last_directory = (
                self.directory_identities[-1][0] if self.directory_identities else ""
            )
            if (
                path.as_posix() != self.entrypoint
                or parent != last_directory
                or not _valid_identity(self.executable_identity)
                or (
                    self.executable_identity is not None
                    and self.executable_identity[3] > self._payload_maximum()
                )
                or type(self.executable_digest) is not str
                or _DIGEST.fullmatch(self.executable_digest) is None
            ):
                raise ValueError("Windows Worker partial-stage file is invalid")

    @classmethod
    def _depth_maximum(cls) -> int:
        return 16


class _WindowsReservedStageReviewMethods(_WindowsStageReviewWireMethods):
    __slots__ = ()
    _attempt_type: ClassVar[type[WindowsRecoveryAttemptV1]]
    _intent_type: ClassVar[type[_LaunchIntentFacts]]
    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    native_revision: int
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str
    entrypoint: str

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_relative_path(self.entrypoint)
        except ValueError as exc:
            raise ValueError("Windows Worker reserved entrypoint is invalid") from exc
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (self.intent_fingerprint, self.executable_digest)
            )
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or type(self.native_revision) is not int
            or self.native_revision not in (1, 2)
            or path.as_posix() != self.entrypoint
            or not _valid_identity(self.stage_identity)
            or not _valid_identity(self.marker_identity)
            or not _valid_identity(self.executable_identity)
            or not 0 < self.executable_identity[3] <= self._payload_maximum()
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) != len(path.parts) - 1
            or any(
                type(member) is not tuple
                or len(member) != 2
                or member[0] != "/".join(path.parts[: index + 1])
                or not _valid_identity(member[1])
                for index, member in enumerate(self.directory_identities)
            )
        ):
            raise ValueError("Windows Worker reserved review is invalid")

    @classmethod
    def _require_no_effect_candidate(
        cls,
        attempt: WindowsRecoveryAttemptV1,
        intent: _LaunchIntentFacts,
        *,
        settled: bool,
        history_error: str,
    ) -> None:
        if (
            type(attempt) is not cls._attempt_type
            or type(intent) is not cls._intent_type
            or attempt.attempt_id != intent.attempt_id
            or attempt.observed_debts
            != (_SETTLED_DEBTS if settled else _RESERVED_DEBTS)
            or attempt.payload_directory_identity != intent.stage_identity
            or not no_effect_history_matches(attempt, settled=settled)
            or not native_matches_intent(attempt, intent)
            or not launch_matches_intent(attempt, intent)
            or attempt.launch_stage_identity != intent.stage_identity
        ):
            raise cls._record_error(history_error)


_RESERVED_DEBTS = (
    "payload_retained",
    "launch_intent_retained",
    "native_unsettled",
    "supervisor_history_missing",
)
_SETTLED_DEBTS = (
    "payload_retained",
    "launch_intent_retained",
    "supervisor_history_missing",
)


def windows_worker_reserved_settled_document(
    current: Mapping[str, object],
    *,
    expected_review: _WindowsReservedStageReviewMethods,
    error_type: type[RuntimeError],
    history_error: str,
) -> dict[str, object]:
    if (
        type(current) is not dict
        or current.get("attemptId") != expected_review.attempt_id
        or current.get("phase") != "reserved"
        or (type(current.get("stateRevision")) is not int)
        or (current["stateRevision"] != expected_review.native_revision)
        or (current.get("witness") is not None)
    ):
        raise error_type(history_error)
    return {**current, "phase": "settled", "stateRevision": 2, "witness": None}
