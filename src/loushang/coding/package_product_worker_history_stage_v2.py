"""Durable but non-authoritative Worker V2 Product preparation artifacts.

An intent is written before any artifact, so a crash leaves either no change
or a named, resumable V1-only preparation. The Product owner index is separate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_activation_base_v2 import (
    CodingWorkerActivationSemanticBaseV2,
)
from .package_product_worker_history_cutover_v2 import (
    CodingWorkerProductCutoverIndexV2,
    CodingWorkerStreamCutoverV2,
)
from .package_product_worker_history_preflight_v2 import (
    _prepare_coding_product_worker_history_cutover_under_guard,
)
from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from .package_product_worker_history_v2_names import (
    NO_EFFECT_ARCHIVE_NAME,
    PREPARATION_ARTIFACT_NAMES,
    PREPARATION_INTENT_NAME,
    PREPARED_INDEX_NAME,
    PRODUCT_OWNER_INDEX_NAME,
    semantic_base_name,
    stream_cutover_name,
)
from .package_product_worker_no_effect_archive_v2 import (
    CodingWorkerNoEffectArchiveV2,
)
from .package_product_worker_opt_in_base_v2 import (
    CodingWorkerOptInSemanticBaseV2,
)
from .package_product_worker_receipt_base_v2 import (
    CodingWorkerReceiptSemanticBaseV2,
)
from .package_product_worker_start_gate_base_v2 import (
    CodingWorkerStartGateSemanticBaseV2,
)
from .package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorSemanticBaseV2,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_INTENT_BYTES = 8192
_MAX_BASE_BYTES = 128 * 1024 * 1024
_MAX_STREAM_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 4096


class CodingWorkerV2PreparationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ByteBase(Protocol):
    def to_bytes(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class CodingWorkerV2PreparationIntent:
    scope_id: str
    store_id: str
    checkpoint_digest: str
    index_digest: str
    artifact_digests: tuple[tuple[str, str], ...]
    record_digest: str
    version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.checkpoint_digest) is not str
            or _DIGEST.fullmatch(self.checkpoint_digest) is None
            or type(self.index_digest) is not str
            or _DIGEST.fullmatch(self.index_digest) is None
            or type(self.artifact_digests) is not tuple
            or tuple(name for name, _digest in self.artifact_digests)
            not in (
                PREPARATION_ARTIFACT_NAMES,
                (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME),
            )
            or any(
                type(digest) is not str or _DIGEST.fullmatch(digest) is None
                for _name, digest in self.artifact_digests
            )
            or self.artifact_digests[0][1] != self.index_digest
            or type(self.version) is not int
            or self.version != 2
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker V2 preparation intent is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "artifactDigests": [list(item) for item in self.artifact_digests],
            "checkpointDigest": self.checkpoint_digest,
            "indexDigest": self.index_digest,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "version": self.version,
        }

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )
        if len(raw) > _MAX_INTENT_BYTES:
            raise ValueError("Coding Worker V2 preparation intent exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerV2PreparationIntent:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_INTENT_BYTES:
            raise ValueError("Coding Worker V2 preparation intent bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "artifactDigests",
                    "checkpointDigest",
                    "indexDigest",
                    "recordDigest",
                    "scopeId",
                    "storeId",
                    "version",
                }
                or type(value["artifactDigests"]) is not list
            ):
                raise ValueError("Coding Worker V2 preparation intent fields changed")
            intent = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                checkpoint_digest=value["checkpointDigest"],
                index_digest=value["indexDigest"],
                artifact_digests=tuple(
                    tuple(item) if type(item) is list else item
                    for item in value["artifactDigests"]
                ),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if intent.to_bytes() != raw:
                raise ValueError("Coding Worker V2 preparation intent encoding changed")
            return intent
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker V2 preparation intent bytes are invalid"
            ) from exc

    @classmethod
    def from_prepared(
        cls, prepared: CodingWorkerPreparedProductCutoverV2
    ) -> CodingWorkerV2PreparationIntent:
        if type(prepared) is not CodingWorkerPreparedProductCutoverV2:
            raise ValueError("Coding Worker V2 preparation requires typed sources")
        artifacts = _artifact_bytes(prepared)
        digests = tuple((name, sha256(raw).hexdigest()) for name, raw in artifacts)
        index = prepared.index
        unsigned = {
            "artifactDigests": [list(item) for item in digests],
            "checkpointDigest": index.checkpoint_digest,
            "indexDigest": sha256(index.to_bytes()).hexdigest(),
            "scopeId": index.scope_id,
            "storeId": index.store_id,
            "version": 2,
        }
        return cls(
            scope_id=index.scope_id,
            store_id=index.store_id,
            checkpoint_digest=index.checkpoint_digest,
            index_digest=sha256(index.to_bytes()).hexdigest(),
            artifact_digests=digests,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


def _artifact_bytes(
    prepared: CodingWorkerPreparedProductCutoverV2,
) -> tuple[tuple[str, bytes], ...]:
    bases = cast(tuple[_ByteBase, ...], prepared.semantic_bases)
    result: list[tuple[str, bytes]] = [(PREPARED_INDEX_NAME, prepared.index.to_bytes())]
    for stream, base in zip(prepared.streams, bases, strict=True):
        result.append((semantic_base_name(stream.stem), base.to_bytes()))
        result.append((stream_cutover_name(stream.stem), stream.to_bytes()))
    if prepared.no_effect_archive is not None:
        result.append((NO_EFFECT_ARCHIVE_NAME, prepared.no_effect_archive.to_bytes()))
    return tuple(result)


def _optional_bytes(rooted: RootedFile, *, name: str, limit: int) -> bytes | None:
    try:
        return rooted.sibling(name).read_bytes(max_bytes=limit)
    except FileNotFoundError:
        return None


def _artifact_limit(name: str) -> int:
    if name == PREPARED_INDEX_NAME:
        return _MAX_INDEX_BYTES
    return (
        _MAX_BASE_BYTES
        if name.endswith(".base.json") or name == NO_EFFECT_ARCHIVE_NAME
        else _MAX_STREAM_BYTES
    )


def stage_coding_worker_v2_preparation(
    rooted: RootedFile, *, prepared: CodingWorkerPreparedProductCutoverV2
) -> CodingWorkerV2PreparationIntent:
    """Durably stage exact bytes; retries complete only the same intent."""

    intent = CodingWorkerV2PreparationIntent.from_prepared(prepared)
    if (
        _optional_bytes(rooted, name=PRODUCT_OWNER_INDEX_NAME, limit=_MAX_INDEX_BYTES)
        is not None
    ):
        raise CodingWorkerV2PreparationError("coding_worker_v2_owner_already_present")
    existing_intent = _optional_bytes(
        rooted, name=PREPARATION_INTENT_NAME, limit=_MAX_INTENT_BYTES
    )
    if existing_intent is None:
        if any(
            _optional_bytes(rooted, name=name, limit=_artifact_limit(name)) is not None
            for name in (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME)
        ):
            raise CodingWorkerV2PreparationError("coding_worker_v2_orphan_preparation")
        rooted.sibling(PREPARATION_INTENT_NAME).create_new(intent.to_bytes())
    elif existing_intent != intent.to_bytes():
        raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    for name, raw in _artifact_bytes(prepared):
        existing = _optional_bytes(rooted, name=name, limit=_artifact_limit(name))
        if existing is None:
            rooted.sibling(name).create_new(raw)
        elif existing != raw:
            raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    readback = read_coding_worker_v2_preparation(rooted)
    if readback != prepared:
        raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    return intent


def read_coding_worker_v2_preparation(
    rooted: RootedFile,
) -> CodingWorkerPreparedProductCutoverV2 | None:
    """Verify all staged bytes; this never selects V2 as Product authority."""

    raw_intent = _optional_bytes(
        rooted, name=PREPARATION_INTENT_NAME, limit=_MAX_INTENT_BYTES
    )
    if raw_intent is None:
        if any(
            _optional_bytes(rooted, name=name, limit=_artifact_limit(name)) is not None
            for name in (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME)
        ):
            raise CodingWorkerV2PreparationError("coding_worker_v2_orphan_preparation")
        return None
    intent = CodingWorkerV2PreparationIntent.from_bytes(raw_intent)
    archive_named = NO_EFFECT_ARCHIVE_NAME in dict(intent.artifact_digests)
    archive_present = (
        _optional_bytes(rooted, name=NO_EFFECT_ARCHIVE_NAME, limit=_MAX_BASE_BYTES)
        is not None
    )
    if archive_named != archive_present:
        raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    artifacts: dict[str, bytes] = {}
    for name, digest in intent.artifact_digests:
        raw = _optional_bytes(rooted, name=name, limit=_artifact_limit(name))
        if raw is None:
            raise CodingWorkerV2PreparationError(
                "coding_worker_v2_preparation_incomplete"
            )
        if sha256(raw).hexdigest() != digest:
            raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
        artifacts[name] = raw
    index = CodingWorkerProductCutoverIndexV2.from_bytes(artifacts[PREPARED_INDEX_NAME])
    bases = (
        CodingWorkerOptInSemanticBaseV2.from_bytes(
            artifacts[semantic_base_name("worker-opt-in")]
        ),
        CodingWorkerReceiptSemanticBaseV2.from_bytes(
            artifacts[semantic_base_name("worker-activation-receipts")]
        ),
        CodingWorkerActivationSemanticBaseV2.from_bytes(
            artifacts[semantic_base_name("worker-activation-state")]
        ),
        CodingWorkerStartGateSemanticBaseV2.from_bytes(
            artifacts[semantic_base_name("worker-start-gates")]
        ),
        CodingWorkerSupervisorSemanticBaseV2.from_bytes(
            artifacts[semantic_base_name("worker-supervisor")]
        ),
    )
    streams = tuple(
        CodingWorkerStreamCutoverV2.from_bytes(artifacts[stream_cutover_name(stem)])
        for stem in (
            "worker-opt-in",
            "worker-activation-receipts",
            "worker-activation-state",
            "worker-start-gates",
            "worker-supervisor",
        )
    )
    prepared = CodingWorkerPreparedProductCutoverV2(
        index=index,
        streams=streams,
        semantic_bases=bases,
        no_effect_archive=(
            None
            if NO_EFFECT_ARCHIVE_NAME not in artifacts
            else CodingWorkerNoEffectArchiveV2.from_bytes(
                artifacts[NO_EFFECT_ARCHIVE_NAME]
            )
        ),
    )
    if (
        intent.scope_id != index.scope_id
        or intent.store_id != index.store_id
        or intent.checkpoint_digest != index.checkpoint_digest
        or intent.index_digest != sha256(index.to_bytes()).hexdigest()
    ):
        raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    return prepared


def rollback_coding_worker_v2_preparation(rooted: RootedFile) -> bool:
    """Remove only intent-owned bytes while no Product owner index exists."""

    if (
        _optional_bytes(rooted, name=PRODUCT_OWNER_INDEX_NAME, limit=_MAX_INDEX_BYTES)
        is not None
    ):
        raise CodingWorkerV2PreparationError("coding_worker_v2_owner_already_present")
    raw_intent = _optional_bytes(
        rooted, name=PREPARATION_INTENT_NAME, limit=_MAX_INTENT_BYTES
    )
    if raw_intent is None:
        if any(
            _optional_bytes(rooted, name=name, limit=_artifact_limit(name)) is not None
            for name in (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME)
        ):
            raise CodingWorkerV2PreparationError("coding_worker_v2_orphan_preparation")
        return False
    intent = CodingWorkerV2PreparationIntent.from_bytes(raw_intent)
    if (
        NO_EFFECT_ARCHIVE_NAME not in dict(intent.artifact_digests)
        and _optional_bytes(
            rooted, name=NO_EFFECT_ARCHIVE_NAME, limit=_MAX_BASE_BYTES
        )
        is not None
    ):
        raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    targets: list[tuple[str, tuple[int, int]]] = []
    for name, digest in intent.artifact_digests:
        target = rooted.sibling(name)
        try:
            before = target.stat()
            raw = target.read_bytes(max_bytes=_artifact_limit(name))
            after = target.stat()
        except FileNotFoundError:
            continue
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or sha256(raw).hexdigest() != digest:
            raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
        targets.append((name, (after.st_dev, after.st_ino)))
    for name, identity in targets:
        rooted.sibling(name).unlink_owned(identity)
    intent_file = rooted.sibling(PREPARATION_INTENT_NAME)
    before = intent_file.stat()
    if intent_file.read_bytes(max_bytes=_MAX_INTENT_BYTES) != raw_intent:
        raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    after = intent_file.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise CodingWorkerV2PreparationError("coding_worker_v2_preparation_changed")
    intent_file.unlink_owned((after.st_dev, after.st_ino))
    return True


def stage_coding_product_worker_v2_preparation(
    product: PosixLocalWheelProductSessionOwner,
    *,
    first_retained_generations: tuple[int, ...],
) -> CodingWorkerV2PreparationIntent:
    """Prepare and stage under the same Product runtime and GC custody."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 staging requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            prepared = _prepare_coding_product_worker_history_cutover_under_guard(
                product,
                first_retained_generations=first_retained_generations,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                file_io = RootedFileIO(product.state_root, root_fd)
                try:
                    with file_io.bind(
                        product.state_root / PREPARATION_INTENT_NAME, durable=True
                    ) as rooted:
                        result = stage_coding_worker_v2_preparation(
                            rooted, prepared=prepared
                        )
                finally:
                    file_io.cleanup()
            product.assert_root_gc_authority_current()
            return result


def rollback_coding_product_worker_v2_preparation(
    product: PosixLocalWheelProductSessionOwner,
) -> bool:
    """Remove only matching staged bytes while V1 still owns all history."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 rollback requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id):
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                file_io = RootedFileIO(product.state_root, root_fd)
                try:
                    with file_io.bind(
                        product.state_root / PREPARATION_INTENT_NAME, durable=True
                    ) as rooted:
                        result = rollback_coding_worker_v2_preparation(rooted)
                finally:
                    file_io.cleanup()
            product.assert_root_gc_authority_current()
            return result


__all__ = [
    "CodingWorkerV2PreparationError",
    "CodingWorkerV2PreparationIntent",
    "read_coding_worker_v2_preparation",
    "rollback_coding_product_worker_v2_preparation",
    "rollback_coding_worker_v2_preparation",
    "stage_coding_product_worker_v2_preparation",
    "stage_coding_worker_v2_preparation",
]
