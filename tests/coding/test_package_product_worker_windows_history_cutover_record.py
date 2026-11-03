"""A Windows cutover marker must identify one exact persisted Product base set."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_windows_history_cutover_record import (
    CodingWindowsWorkerHistoryCutoverRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from tests.coding.test_package_product_worker_windows_persisted_bases import (
    _persisted,
)


def test_windows_cutover_record_binds_persisted_checkpoint_and_six_bases(
    tmp_path: Path,
) -> None:
    persisted = _persisted(tmp_path)
    record = CodingWindowsWorkerHistoryCutoverRecordV1.from_persisted_bases(persisted)
    assert record.checkpoint_digest == persisted.checkpoint.record_digest
    assert record.source_snapshot_digest == (
        persisted.checkpoint.source_snapshot.snapshot_digest
    )
    assert record.base_digests == persisted.checkpoint.base_digests
    assert (
        CodingWindowsWorkerHistoryCutoverRecordV1.from_bytes(record.to_bytes())
        == record
    )
    record.require_persisted_bases(persisted)


@pytest.mark.parametrize(
    "change",
    (
        {"checkpointDigest": "0" * 64},
        {"baseDigests": []},
        {"cutoverVersion": True},
        {"unexpected": True},
    ),
)
def test_windows_cutover_record_refuses_changed_identity(
    tmp_path: Path, change: dict[str, object]
) -> None:
    record = CodingWindowsWorkerHistoryCutoverRecordV1.from_persisted_bases(
        _persisted(tmp_path)
    )
    raw = json.loads(record.to_bytes())
    raw.update(change)
    with pytest.raises(ValueError, match="cutover record is invalid"):
        CodingWindowsWorkerHistoryCutoverRecordV1.from_bytes(canonical_json_bytes(raw))


def test_windows_cutover_record_refuses_noncanonical_bytes(tmp_path: Path) -> None:
    record = CodingWindowsWorkerHistoryCutoverRecordV1.from_persisted_bases(
        _persisted(tmp_path)
    )
    raw = record.to_bytes()
    with pytest.raises(ValueError, match="cutover record is invalid"):
        CodingWindowsWorkerHistoryCutoverRecordV1.from_bytes(raw + b" ")


def test_windows_cutover_record_refuses_other_valid_checkpoint(tmp_path: Path) -> None:
    persisted = _persisted(tmp_path)
    record = CodingWindowsWorkerHistoryCutoverRecordV1.from_persisted_bases(persisted)
    revision = "coding-product-backup-types:" + sha256(b"other-topology").hexdigest()
    unsigned = {
        **persisted.checkpoint._unsigned_dict(),
        "backupTopologyRevision": revision,
    }
    changed = replace(
        persisted.checkpoint,
        backup_topology_revision=revision,
        record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
    )
    other = replace(persisted, checkpoint=changed)
    with pytest.raises(ValueError, match="cutover bases changed"):
        record.require_persisted_bases(other)
