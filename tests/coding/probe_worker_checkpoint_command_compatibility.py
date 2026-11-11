"""Old checkpoint IO outcomes; Product authority is a declared test substitute."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_history_checkpoint as checkpoint
import loushang.coding.package_product_worker_history_segments as segments
import loushang.coding.package_product_worker_history_stream_snapshot as snapshots
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_commit_v2 import _product

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux checkpoint IO")
CASES = (
    "fresh",
    "duplicate",
    "closure-refused",
    "head-before",
    "append-complete",
    "append-partial",
    "head-after",
    "anchor-after",
    "seal-next",
    "source-tampered",
)
ATTEMPT = "a" * 32
STEM = "worker-history-checkpoints"


def observe_checkpoint(case, root, patch):
    root.chmod(0o700)
    calls = []
    product = _product(root, patch, calls)
    patch.setattr(
        PosixLocalWheelProductSessionOwner,
        "assert_root_gc_authority_current",
        lambda owner: calls.append("current"),
    )
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with RootedFileIO(root, fd) as io:
            for stem in snapshots.CODING_WORKER_HISTORY_STREAM_STEMS:
                with io.bind(root / f"{stem}.jsonl", durable=True) as bound:
                    bound.create_new(b"")
                    segments.initialize_coding_worker_active_head(
                        bound, stem=stem, stream_id=stem
                    )
    finally:
        os.close(fd)
    calls.clear()
    revision = 1

    def review(*args, **kwargs):
        calls.append("review")
        return SimpleNamespace(
            missing_proofs=("test-missing",) if case == "closure-refused" else (),
            receipt_record=SimpleNamespace(
                receipt=SimpleNamespace(fingerprint="b" * 64)
            ),
            worker_backup_references=SimpleNamespace(
                owner_revision="coding-product-backup-types:" + "c" * 64
            ),
            history_stream_snapshots=snapshots.capture_coding_worker_history_streams_under_gc_guard(
                product
            ),
            gc_reservation_revision=revision,
            retained_opt_in_operation_ids=("allow-1",),
            retained_start_gate_attempt_ids=(ATTEMPT,),
            retained_receipt_fingerprints=("b" * 64,),
            opt_in_generation_high_water=(("worker", 1, 0, "allow", "d" * 64),),
            supervisor_epoch_high_water=(("key", 1),),
        )

    patch.setattr(
        checkpoint, "_review_coding_product_worker_history_under_guard", review
    )
    if case in {"duplicate", "seal-next", "source-tampered"}:
        checkpoint.publish_coding_product_worker_history_checkpoint(
            product, attempt_id=ATTEMPT
        )
        calls.clear()
    if case == "seal-next":
        revision = 2
        patch.setattr(checkpoint, "_MAX_ACTIVE_RECORDS", 1)
    if case == "source-tampered":
        (root / "worker-opt-in.jsonl").write_bytes(b"{}\n")

    original_create = RootedFile.create_new
    original_append = RootedFile.append_bytes
    original_atomic = RootedFile.atomic_write
    fired = False

    def create(target, body, **kwargs):
        nonlocal fired
        if case == "head-before" and target._name == STEM + ".head.json":
            fired = True
            raise OSError("pause before first head")
        return original_create(target, body, **kwargs)

    def append(target, body, **kwargs):
        nonlocal fired
        if (
            case in {"append-complete", "append-partial"}
            and target._name == STEM + ".jsonl"
        ):
            fired = True
            original_append(
                target,
                body if case == "append-complete" else body[: len(body) // 2],
                **kwargs,
            )
            raise OSError("append happened; acknowledgement lost")
        return original_append(target, body, **kwargs)

    def atomic(target, body, **kwargs):
        nonlocal fired
        result = original_atomic(target, body, **kwargs)
        expected = (
            STEM + ".head.json"
            if case == "head-after"
            else "worker-history-checkpoint-owner.json"
        )
        if case in {"head-after", "anchor-after"} and target._name == expected:
            fired = True
            raise OSError("publication happened; acknowledgement lost")
        return result

    def describe(action):
        try:
            value = action()
        except Exception as exc:
            errors = []
            while exc is not None:
                errors.append(
                    [type(exc).__name__, str(exc), getattr(exc, "code", None)]
                )
                exc = exc.__cause__
            return {"error": errors}
        values = value if isinstance(value, tuple) else (value,)
        return {"records": [item.to_dict() for item in values]}

    def publish():
        return checkpoint.publish_coding_product_worker_history_checkpoint(
            product, attempt_id=ATTEMPT
        )

    with patch.context() as faults:
        faults.setattr(RootedFile, "create_new", create)
        faults.setattr(RootedFile, "append_bytes", append)
        faults.setattr(RootedFile, "atomic_write", atomic)
        first = describe(publish)
    if case in {
        "head-before",
        "append-complete",
        "append-partial",
        "head-after",
        "anchor-after",
    }:
        assert fired, "the named checkpoint interruption must occur"
    pending = _files(root)
    retry = None
    if case == "append-complete":
        retry = describe(
            lambda: checkpoint.repair_coding_product_worker_history_checkpoint_append(
                product, attempt_id=ATTEMPT
            )
        )
    elif case == "append-partial":
        retry = describe(
            lambda: checkpoint.rollback_coding_product_worker_history_checkpoint_tail(
                product
            )
        )
    elif case in {"head-before", "head-after", "anchor-after"}:
        retry = describe(publish)
    strict = describe(
        lambda: (
            checkpoint.read_coding_product_worker_history_checkpoints_under_gc_guard(
                product
            )
        )
    )
    return dict(
        first=first,
        pending=pending,
        retry=retry,
        strict=strict,
        calls=calls,
        final=_files(root),
    )


def _files(root):
    return {
        p.name: dict(
            size=p.stat().st_size,
            mode=stat.S_IMODE(p.stat().st_mode),
            digest=hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in sorted(root.iterdir())
        if p.is_file()
    }


@pytest.mark.parametrize("case", CASES)
def test_original_checkpoint_commands(case, tmp_path, monkeypatch):
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures/worker_checkpoint_commands_v1.json"
        ).read_text()
    )
    assert observe_checkpoint(case, tmp_path, monkeypatch) == expected[case]


def observe_v2_values(root, patch):
    from tests.coding import test_package_product_worker_history_snapshot_v2 as scenario

    capture = scenario.capture_coding_worker_history_streams_under_gc_guard
    verify = scenario.verify_coding_worker_history_stream_extensions_under_gc_guard
    observations = []

    def captured(*args, **kwargs):
        values = capture(*args, **kwargs)
        observations.append({"snapshots": [value.to_dict() for value in values]})
        return values

    def verified(*args, **kwargs):
        result = verify(*args, **kwargs)
        observations.append({"extension": result})
        return result

    patch.setattr(
        scenario, "capture_coding_worker_history_streams_under_gc_guard", captured
    )
    patch.setattr(
        scenario,
        "verify_coding_worker_history_stream_extensions_under_gc_guard",
        verified,
    )
    scenario.test_v2_snapshot_preserves_old_checkpoint_after_retirement_and_append(
        root, patch
    )
    assert len(observations) == 7
    return observations


def test_original_v2_snapshot_values(tmp_path, monkeypatch):
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures/worker_checkpoint_snapshot_v2.json"
        ).read_text()
    )
    assert observe_v2_values(tmp_path, monkeypatch) == expected
