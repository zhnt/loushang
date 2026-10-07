"""V2 retained reader verifies owner and deletion debt before replay."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_history_deletion_v2 import (
    CodingWorkerV2DeletionLedger,
)
from loushang.coding.package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from loushang.coding.package_product_worker_history_read_v2 import (
    CodingWorkerV2ReadError,
    read_coding_worker_v2_retained_history,
    verify_coding_worker_v2_precommit_history,
)
from loushang.coding.package_product_worker_history_segments import (
    _head_bytes,
    _head_name,
    _segment_name,
    commit_coding_worker_active_segment,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
)
from loushang.coding.package_product_worker_history_stage_v2 import (
    stage_coding_worker_v2_preparation,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from loushang.coding.package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
    PRODUCT_OWNER_INDEX_NAME,
)
from loushang.coding.package_product_worker_opt_in import _opt_in_line
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from tests.coding.test_package_product_worker_history_prepared_v2 import _sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.coding.test_package_product_worker_opt_in_base_v2 import _allow


def _write_sources(rooted: RootedFile) -> CodingWorkerPreparedProductCutoverV2:
    checkpoints, anchor, histories = _sources()
    prepared = CodingWorkerPreparedProductCutoverV2.from_v1_histories(
        checkpoints=checkpoints,
        anchor=anchor,
        histories=histories,
        first_retained_generations=(1, 1, 1, 1, 1),
    )
    for stem, history in zip(
        CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
    ):
        assert history.manifest is not None
        rooted.sibling(stem + ".segments.json").create_new(history.manifest.to_bytes())
        for generation, raw in enumerate(history.segments):
            rooted.sibling(_segment_name(stem, generation)).create_new(raw)
            rooted.sibling(_head_name(stem, generation)).create_new(
                _head_bytes(stem, generation, raw)
            )
    checkpoint_raw = b"".join(
        canonical_json_bytes(item.to_dict()) + b"\n" for item in checkpoints
    )
    rooted.sibling("worker-history-checkpoints.jsonl").create_new(checkpoint_raw)
    rooted.sibling("worker-history-checkpoints.head.json").create_new(
        _head_bytes("worker-history-checkpoints", 0, checkpoint_raw)
    )
    rooted.sibling("worker-history-checkpoint-owner.json").create_new(anchor.to_bytes())
    stage_coding_worker_v2_preparation(rooted, prepared=prepared)
    return prepared


def test_v2_reader_replays_five_streams_and_requires_exact_deletion_ledger(
    tmp_path: Path,
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        with pytest.raises(CodingWorkerV2ReadError, match="owner_absent"):
            read_coding_worker_v2_retained_history(rooted, stem="worker-supervisor")
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        for stream in prepared.streams:
            result = read_coding_worker_v2_retained_history(rooted, stem=stream.stem)
            assert result.last_revision == stream.total_revision
            assert result.active_generation == stream.active_generation

        rooted.sibling(_segment_name("worker-supervisor", 0)).unlink()
        rooted.sibling(_head_name("worker-supervisor", 0)).unlink()
        with pytest.raises(CodingWorkerV2ReadError, match="retained_segment_missing"):
            read_coding_worker_v2_retained_history(rooted, stem="worker-supervisor")
        ledger = CodingWorkerV2DeletionLedger.from_prepared(prepared)
        assert CodingWorkerV2DeletionLedger.from_bytes(ledger.to_bytes()) == ledger
        rooted.sibling(DELETION_LEDGER_NAME).create_new(ledger.to_bytes())
        result = read_coding_worker_v2_retained_history(
            rooted, stem="worker-supervisor"
        )
        assert result.last_revision == prepared.streams[4].total_revision


def test_precommit_reader_requires_all_five_exact_sources_before_owner(
    tmp_path: Path,
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        for stream in prepared.streams:
            proof = verify_coding_worker_v2_precommit_history(
                rooted, stem=stream.stem, prepared=prepared
            )
            assert proof.last_revision == stream.total_revision
        with pytest.raises(CodingWorkerV2ReadError, match="owner_absent"):
            read_coding_worker_v2_retained_history(rooted, stem="worker-opt-in")

        stem = "worker-activation-state"
        rooted.sibling(_head_name(stem, 1)).atomic_write(b"{}")
        with pytest.raises(CodingWorkerV2ReadError, match="active_head_changed"):
            verify_coding_worker_v2_precommit_history(
                rooted, stem=stem, prepared=prepared
            )
        original = _sources()[2][2].active_raw
        rooted.sibling(_head_name(stem, 1)).atomic_write(_head_bytes(stem, 1, original))
        rooted.sibling(DELETION_LEDGER_NAME).create_new(
            CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
        )
        with pytest.raises(CodingWorkerV2ReadError, match="precommit_deletion_debt"):
            verify_coding_worker_v2_precommit_history(
                rooted, stem=stem, prepared=prepared
            )
        rooted.sibling(DELETION_LEDGER_NAME).unlink()
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        with pytest.raises(CodingWorkerV2ReadError, match="owner_already_present"):
            verify_coding_worker_v2_precommit_history(
                rooted, stem=stem, prepared=prepared
            )


def test_v2_reader_refuses_changed_manifest_and_active_head(
    tmp_path: Path,
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        stem = "worker-supervisor"
        active_head = rooted.sibling(_head_name(stem, 1))
        active_head.atomic_write(b"{}")
        with pytest.raises(CodingWorkerV2ReadError, match="active_head_changed"):
            read_coding_worker_v2_retained_history(rooted, stem=stem)
        original_active = _sources()[2][4].active_raw
        active_head.atomic_write(_head_bytes(stem, 1, original_active))
        changed_active = b" " + original_active[1:]
        rooted.sibling(_segment_name(stem, 1)).atomic_write(changed_active)
        active_head.atomic_write(_head_bytes(stem, 1, changed_active))
        with pytest.raises(CodingWorkerV2ReadError, match="cutover_prefix_changed"):
            read_coding_worker_v2_retained_history(rooted, stem=stem)
        rooted.sibling(_segment_name(stem, 1)).atomic_write(original_active)
        active_head.atomic_write(_head_bytes(stem, 1, original_active))
        manifest = _sources()[2][4].manifest
        assert manifest is not None
        changed = replace(
            manifest,
            sealed=(replace(manifest.sealed[0], digest="0" * 64),),
        )
        rooted.sibling(stem + ".segments.json").atomic_write(changed.to_bytes())
        with pytest.raises(CodingWorkerV2ReadError, match="manifest_changed"):
            read_coding_worker_v2_retained_history(rooted, stem=stem)


def test_v2_reader_follows_committed_append_and_later_rotation(
    tmp_path: Path,
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        stem = "worker-opt-in"
        active = rooted.sibling(_segment_name(stem, 1))
        previous = active.read_bytes(max_bytes=32 * 1024 * 1024)
        line = _opt_in_line(
            _allow(
                plugin_id="plugin-b",
                revision=5,
                generation=2,
                kill=0,
                operation="allow-b2",
            )
        )
        active.append_bytes(line)
        commit_coding_worker_active_segment(
            rooted,
            stem=stem,
            stream_id=stem,
            generation=1,
            previous_raw=previous,
            appended_line=line,
        )
        assert (
            read_coding_worker_v2_retained_history(rooted, stem=stem).last_revision == 5
        )
        history = read_coding_worker_segmented_history(
            rooted, stem=stem, stream_id=stem, max_segment_bytes=32 * 1024 * 1024
        )
        seal_coding_worker_active_segment(
            rooted,
            stem=stem,
            stream_id=stem,
            history=history,
            last_revision=5,
        )
        rotated = read_coding_worker_v2_retained_history(rooted, stem=stem)
        assert rotated.active_generation == 2
        assert rotated.last_revision == 5
        ledger = CodingWorkerV2DeletionLedger.from_prepared(prepared)
        rooted.sibling(DELETION_LEDGER_NAME).create_new(ledger.to_bytes())
        rooted.sibling(_segment_name(stem, 0)).unlink()
        rooted.sibling(_head_name(stem, 0)).unlink()
        assert (
            read_coding_worker_v2_retained_history(rooted, stem=stem).last_revision == 5
        )
