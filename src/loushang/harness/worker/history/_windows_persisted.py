"""Persisted Windows history closure using the original source-bound record family.

These pure proofs neither open Product roots nor publish a cutover marker.
Compatibility adapters bind nominal records; existing Worker methods remain the
only implementation of each stream's reconstruction and decoding.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._base_codec import _BaseWireMethods, _unchanged
from ._windows_c5_base import _WindowsC5BaseMethods
from ._windows_checkpoint import _WindowsHistoryCheckpointMethods
from ._windows_history_join import _WindowsHistoryJoinMethods
from ._windows_launch_intent_base import _WindowsLaunchIntentBaseMethods
from ._windows_opt_in_base import _WindowsOptInBaseMethods
from ._windows_provisioning_base import _WindowsProvisioningBaseMethods
from ._windows_receipt_base import _WindowsReceiptBaseMethods
from ._windows_semantic_contracts import _DIGEST
from ._windows_sources import (
    WINDOWS_WORKER_BASE_FILES,
    WINDOWS_WORKER_HISTORY_CUTOVER_MAX_BYTES,
)
from ._windows_supervisor_base import _WindowsSupervisorBaseMethods


class _WindowsPersistedBasesMethods:
    __slots__ = ()
    _checkpoint_type: ClassVar[type[_WindowsHistoryCheckpointMethods]]
    _join_type: ClassVar[type[_WindowsHistoryJoinMethods]]
    checkpoint: _WindowsHistoryCheckpointMethods
    opt_in: _WindowsOptInBaseMethods
    receipt: _WindowsReceiptBaseMethods
    supervisor: _WindowsSupervisorBaseMethods
    c5: _WindowsC5BaseMethods
    launch_intent: _WindowsLaunchIntentBaseMethods
    native_provisioning: _WindowsProvisioningBaseMethods

    def __post_init__(self) -> None:
        if type(self.checkpoint) is not self._checkpoint_type:
            raise ValueError("Windows Worker persisted bases are invalid")
        source = self.checkpoint.source_snapshot
        bases = (
            ("optIn", self.opt_in, self._join_type._opt_in_type),
            ("receipt", self.receipt, self._join_type._receipt_type),
            (
                "supervisor",
                self.supervisor,
                self._join_type._supervisor_type,
            ),
            ("c5", self.c5, self._join_type._c5_type),
            (
                "launchIntent",
                self.launch_intent,
                self._join_type._launch_intent_type,
            ),
            (
                "nativeProvisioning",
                self.native_provisioning,
                self._join_type._provisioning_type,
            ),
        )
        if (
            any(
                type(base) is not expected
                or base.scope_id != source.scope_id
                or base.store_id != source.store_id
                or base.source_snapshot_digest != source.snapshot_digest
                for _, base, expected in bases
            )
            or self.checkpoint.base_digests
            != tuple((name, base.record_digest) for name, base, _ in bases)
            or self.checkpoint.opt_in_operation_ids != self.opt_in.retired_operation_ids
            or self.checkpoint.receipt_fingerprints
            != self.receipt.retired_receipt_fingerprints
            or self.checkpoint.native_provisioning_attempt_ids
            != self.native_provisioning.attempt_ids
            or not set(self.native_provisioning.attempt_ids).issubset(
                self.c5.known_attempt_ids
            )
            or not set(self.supervisor.retired_attempt_ids).issubset(
                self.launch_intent.intent_attempt_ids
            )
            or not set(self.launch_intent.intent_attempt_ids).issubset(
                self.native_provisioning.attempt_ids
            )
            or not set(self.native_provisioning.attempt_ids).issubset(
                self.checkpoint.attempt_ids
            )
        ):
            raise ValueError("Windows Worker persisted bases are invalid")

    @classmethod
    def _from_retained_bytes(
        cls, checkpoint: _WindowsHistoryCheckpointMethods, raw: tuple[bytes, ...]
    ) -> Self:
        return cast(Callable[..., Self], cls)(
            checkpoint=checkpoint,
            opt_in=cls._join_type._opt_in_type.from_bytes(raw[0]),
            receipt=cls._join_type._receipt_type.from_bytes(raw[1]),
            supervisor=cls._join_type._supervisor_type.from_bytes(raw[2]),
            c5=cls._join_type._c5_type.from_bytes(raw[3]),
            launch_intent=cls._join_type._launch_intent_type.from_bytes(raw[4]),
            native_provisioning=cls._join_type._provisioning_type.from_bytes(raw[5]),
        )


class _WindowsHistoryCutoverMethods(_BaseWireMethods):
    __slots__ = ()
    _persisted_type: ClassVar[type[_WindowsPersistedBasesMethods]]
    _wire_label = "Windows Worker history cutover record"
    _wire_lists = ("baseDigests",)
    _wire_invalid_bytes = _wire_invalid_fields = _wire_invalid_encoding = "is invalid"
    _wire_errors = (KeyError, RecursionError, TypeError, UnicodeError, ValueError)
    _wire_nested_lists = ("baseDigests",)
    _wire_max_bytes = WINDOWS_WORKER_HISTORY_CUTOVER_MAX_BYTES
    scope_id: str
    store_id: str
    checkpoint_digest: str
    source_snapshot_digest: str
    base_digests: tuple[tuple[str, str], ...]
    record_digest: str
    cutover_version: int

    @classmethod
    def _bind_record_schema(cls) -> None:
        cls._wire_schema = RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "base_digests",
                decoder=lambda value: tuple(tuple(item) for item in value),
            ),
        )

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not 0 < len(self.scope_id) <= 128
            or type(self.store_id) is not str
            or not 0 < len(self.store_id) <= 128
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.checkpoint_digest,
                    self.source_snapshot_digest,
                    self.record_digest,
                )
            )
            or type(self.base_digests) is not tuple
            or any(
                type(item) is not tuple or len(item) != 2 for item in self.base_digests
            )
            or tuple(key for key, _ in self.base_digests)
            != tuple(key for key, _ in WINDOWS_WORKER_BASE_FILES)
            or any(
                type(digest) is not str or _DIGEST.fullmatch(digest) is None
                for _, digest in self.base_digests
            )
            or type(self.cutover_version) is not int
            or self.cutover_version != 1
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker history cutover record is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "baseDigests": [list(item) for item in self.base_digests],
            "checkpointDigest": self.checkpoint_digest,
            "cutoverVersion": self.cutover_version,
            "scopeId": self.scope_id,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
        }

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )
        if len(raw) > self._wire_maximum():
            raise ValueError("Windows Worker history cutover record exceeds capacity")
        return raw

    @classmethod
    def _from_persisted_bases(cls, persisted: _WindowsPersistedBasesMethods) -> Self:
        if type(persisted) is not cls._persisted_type:
            raise ValueError("Windows Worker persisted cutover bases are invalid")
        checkpoint = persisted.checkpoint
        source = checkpoint.source_snapshot
        unsigned = {
            "baseDigests": [list(item) for item in checkpoint.base_digests],
            "checkpointDigest": checkpoint.record_digest,
            "cutoverVersion": 1,
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
        }
        return cast(Callable[..., Self], cls)(
            scope_id=source.scope_id,
            store_id=source.store_id,
            checkpoint_digest=checkpoint.record_digest,
            source_snapshot_digest=source.snapshot_digest,
            base_digests=checkpoint.base_digests,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )
