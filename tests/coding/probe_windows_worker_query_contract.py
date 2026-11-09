"""Read-only query contracts with controlled Windows leaves.

The real-descriptor payload probe is POSIX-only. These tests do not certify
Windows ACLs, native containment or Product admission.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import package_product_worker_windows_orphan_review as orphan
from loushang.coding import package_product_worker_windows_payload_inventory as payload
from loushang.coding import (
    package_product_worker_windows_recovery_inventory as recovery,
)
from loushang.coding import (
    package_product_worker_windows_stage_retirement as retirement,
)
from loushang.harness.package_product import _worker_windows_attempt as product_queries
from loushang.harness.worker.payload import _windows_stage_io as stage_io

_ATTEMPT = "a" * 32


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX descriptor probe with controlled Windows IO"
)
@pytest.mark.parametrize(
    "case,code",
    [
        ("normal", None),
        ("root-stream", "inventory_unsafe"),
        ("stage-stream", "inventory_unsafe"),
        ("invalid-name", "inventory_unsafe"),
        ("casefold-duplicate", "inventory_unsafe"),
        ("capacity", "inventory_unsafe"),
        ("identity", "inventory_unsafe"),
        ("relist", "inventory_changed"),
        ("root-error", "state_root_changed"),
        ("constructor", None),
        ("body-and-close", None),
    ],
)
def test_payload_inventory_keeps_handle_and_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: str | None
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    name = "worker-payload-" + _ATTEMPT
    (root / name).mkdir()
    (root / "other").mkdir()
    events: list[str] = []
    stage_descriptors: list[int] = []
    acl_active = False
    root_error = OSError("root disappeared")
    record_error = RuntimeError("record failed")
    close_error = OSError("close failed")
    root_type = type(root)

    class UnavailableRoot(root_type):
        def lstat(self):
            raise root_error

    @contextmanager
    def acl():
        nonlocal acl_active
        acl_active = True
        events.append("acl.enter")
        try:
            yield SimpleNamespace(validate=lambda _fd: events.append("acl.root"))
        finally:
            acl_active = False
            events.append("acl.exit")

    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    listing_count = 0

    def listdir(fd):
        nonlocal listing_count
        assert fd == root_fd
        listing_count += 1
        events.append("list")
        names = os.listdir(fd)
        if case == "invalid-name":
            names.append("worker-payload-foreign")
        if case == "casefold-duplicate":
            names.append(name.upper())
        if case == "relist" and listing_count == 2:
            names.append("unrelated-new-name")
        return tuple(names)

    def open_directory(child, **kwargs):
        assert kwargs == dict(dir_fd=root_fd, share_delete=False, read_control=True)
        descriptor = os.open(child, os.O_RDONLY | os.O_DIRECTORY, dir_fd=root_fd)
        stage_descriptors.append(descriptor)
        events.append("stage.open")
        return descriptor

    def close_stage(descriptor):
        assert descriptor in stage_descriptors
        events.append("stage.close")
        os.close(descriptor)
        if case == "body-and-close":
            raise close_error

    original_record = payload.CodingWindowsWorkerPayloadAttemptV1

    def record(**kwargs):
        assert acl_active and len(stage_descriptors) == 1
        metadata = os.fstat(stage_descriptors[0])
        assert kwargs == dict(
            attempt_id=_ATTEMPT,
            directory_identity=(metadata.st_dev, metadata.st_ino),
        )
        events.append("record")
        if case in {"constructor", "body-and-close"}:
            raise record_error
        return original_record(**kwargs)

    monkeypatch.setattr(payload, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(payload, "CodingWindowsWorkerPayloadAttemptV1", record)
    if case == "capacity":
        monkeypatch.setattr(payload, "_MAX_ATTEMPTS", 0)
    monkeypatch.setattr(stage_io, "WindowsPrivateDirectoryAcl", acl)
    monkeypatch.setattr(stage_io, "windows_listdir_at", listdir)
    monkeypatch.setattr(stage_io, "open_windows_directory", open_directory)
    monkeypatch.setattr(
        stage_io,
        "windows_stat_at",
        lambda fd, child: os.stat(
            "other" if case == "identity" else child,
            dir_fd=fd,
            follow_symlinks=False,
        ),
    )
    monkeypatch.setattr(
        stage_io,
        "windows_directory_stream_names",
        lambda fd: (
            (":hidden:$DATA",)
            if (case == "root-stream" and fd == root_fd)
            or (case == "stage-stream" and fd != root_fd)
            else ("::$DATA",)
        ),
    )
    monkeypatch.setattr(
        stage_io, "os", SimpleNamespace(fstat=os.fstat, path=os.path, close=close_stage)
    )
    try:
        selected_root = UnavailableRoot(root) if case == "root-error" else root
        if code is not None:
            with pytest.raises(
                payload.CodingWindowsWorkerPayloadInventoryError
            ) as caught:
                payload.inspect_windows_worker_payload_stages(
                    selected_root, directory_fd=root_fd
                )
            assert caught.value.code == "coding_worker_payload_" + code
            if case == "root-error":
                assert caught.value.__cause__ is root_error
        elif case in {"constructor", "body-and-close"}:
            with pytest.raises((RuntimeError, OSError)) as caught:
                payload.inspect_windows_worker_payload_stages(
                    root, directory_fd=root_fd
                )
            assert caught.value is (
                close_error if case == "body-and-close" else record_error
            )
            if case == "body-and-close":
                assert close_error.__context__ is record_error
        else:
            result = payload.inspect_windows_worker_payload_stages(
                root, directory_fd=root_fd
            )
            assert len(result) == 1 and type(result[0]) is original_record
            assert events == [
                "acl.enter",
                "acl.root",
                "list",
                "stage.open",
                "record",
                "stage.close",
                "list",
                "acl.exit",
            ]
        assert not acl_active and events[-1] == "acl.exit"
        assert events.count("stage.close") == len(stage_descriptors)
        assert (
            events.count("acl.root") == 1
        )  # The child ACL is deliberately not certified.
        for descriptor in stage_descriptors:
            with pytest.raises(OSError):
                os.fstat(descriptor)
        os.fstat(root_fd)  # The inventory borrows but does not close the caller's root.
    finally:
        os.close(root_fd)


@pytest.mark.parametrize(
    "case", ["normal", "no-job", "native-error", "no-fence", "stale"]
)
def test_orphan_join_retains_read_order_and_native_error(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    events: list[str] = []
    native_error = OSError("native observer unavailable")
    stale_error = ValueError("stale root")
    receipt = SimpleNamespace(
        receipt=SimpleNamespace(
            fingerprint="b" * 64,
            policy=SimpleNamespace(product_runtime_id="runtime"),
        )
    )
    attempt = recovery.CodingWindowsWorkerRecoveryAttemptV1(
        _ATTEMPT,
        None,
        None,
        None,
        None,
        None,
        None,
        launch_receipt_fingerprint="b" * 64,
        native_job_name=None if case == "no-job" else "job",
    )
    lease = SimpleNamespace(runtime_id="runtime")
    fence = (
        None
        if case == "no-fence"
        else SimpleNamespace(epoch=7, fenced_root_identity="root")
    )

    @contextmanager
    def borrow():
        events.append("root.enter")
        try:
            yield 41
        finally:
            events.append("root.exit")

    def current():
        events.append("current")
        if case == "stale" and events.count("current") == 2:
            raise stale_error

    product = SimpleNamespace(
        assert_root_gc_authority_current=current,
        state_root=Path("/query-state"),
        policy=SimpleNamespace(project_scope_id="scope"),
        epoch_runtime=SimpleNamespace(
            borrow_product_state_root_descriptor=borrow,
            cutover_result=SimpleNamespace(fence=fence),
        ),
    )

    def inventory(actual):
        assert actual is product
        events.append("inventory")
        return (attempt,)

    def journal(path, *, scope_id):
        assert path == Path("/query-state/worker-activation-receipts.jsonl")
        assert scope_id == "scope"
        events.append("journal")

        def records(*, directory_fd):
            assert directory_fd == 41
            events.append("receipts")
            return (receipt,)

        return SimpleNamespace(records=records)

    def observe(job):
        assert job == "job"
        events.append("native")
        if case == "native-error":
            raise native_error
        return True

    monkeypatch.setattr(
        orphan, "_inspect_windows_worker_recovery_inventory_under_gc_guard", inventory
    )
    monkeypatch.setattr(orphan, "CodingWindowsWorkerReceiptJournal", journal)
    monkeypatch.setattr(orphan, "observe_windows_worker_job_absent", observe)
    prefix = ["current", "inventory", "journal", "root.enter", "receipts", "root.exit"]
    if case in {"native-error", "no-fence", "stale"}:
        with pytest.raises((OSError, ValueError)) as caught:
            orphan._review_under_gc_guard(
                product, attempt_id=_ATTEMPT, orphans=(lease,)
            )
        if case == "native-error":
            assert caught.value is native_error
            assert events == prefix + ["current", "native"]
            monkeypatch.setattr(recovery, "observe_windows_worker_job_absent", observe)
            assert recovery._observe_native_job_absence("job") is None
        elif case == "stale":
            assert caught.value is stale_error
            assert events == prefix + ["current"]
        else:
            assert str(caught.value) == "Windows Worker Product fence is unavailable"
            assert events == prefix
    else:
        review = orphan._review_under_gc_guard(
            product, attempt_id=_ATTEMPT, orphans=(lease,)
        )
        assert type(review) is orphan.CodingWindowsWorkerOrphanRuntimeReviewV1
        assert review.attempt is attempt and review.receipt_record is receipt
        assert review.orphan_leases == (lease,)
        assert (review.runtime_epoch, review.store_root_identity) == (7, "root")
        assert review.native_job_absent is (None if case == "no-job" else True)
        assert events == prefix + ["current"] + ([] if case == "no-job" else ["native"])


@pytest.mark.parametrize("case", ["direct-error", "root-error", "identity"])
def test_retirement_root_keeps_distinct_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    root_type = type(root)
    root_error = OSError("root disappeared")
    direct_error = RuntimeError("stage review root rejected")
    events: list[str] = []

    class UnavailableRoot(root_type):
        def lstat(self):
            raise root_error

    @contextmanager
    def borrow():
        events.append("root.enter")
        try:
            yield 41
        finally:
            events.append("root.exit")

    @contextmanager
    def acl():
        events.append("acl.enter")
        try:
            yield object()
        finally:
            events.append("acl.exit")

    def direct(*_args, **kwargs):
        assert kwargs == dict(directory=True)
        events.append("direct")
        if case == "direct-error":
            raise direct_error

    product = SimpleNamespace(
        assert_root_gc_authority_current=lambda: events.append("current"),
        state_root=UnavailableRoot(root) if case == "root-error" else root,
        epoch_runtime=SimpleNamespace(borrow_product_state_root_descriptor=borrow),
    )
    monkeypatch.setattr(product_queries, "WindowsPrivateDirectoryAcl", acl)
    monkeypatch.setattr(
        product_queries,
        "os",
        SimpleNamespace(
            fstat=lambda _fd: object(),
            path=SimpleNamespace(samestat=lambda *_args: False),
        ),
    )
    monkeypatch.setattr(
        retirement, "_inspection", lambda: SimpleNamespace(require_direct=direct)
    )
    with pytest.raises((RuntimeError, OSError)) as caught:
        retirement._inspect_retirement_attempt_ids_under_gc_guard(product)
    if case == "identity":
        assert type(caught.value) is retirement.CodingWindowsWorkerStageRetirementError
        assert caught.value.code == "coding_worker_stage_retirement_root_changed"
    else:
        assert caught.value is (direct_error if case == "direct-error" else root_error)
    assert events == [
        "current",
        "root.enter",
        "acl.enter",
        "direct",
        "acl.exit",
        "root.exit",
    ]


@pytest.mark.parametrize("kind", ["payload", "native"])
@pytest.mark.parametrize("case", ["normal", "read-error", "stale"])
def test_payload_and_native_share_original_gc_read_program(
    monkeypatch: pytest.MonkeyPatch, kind: str, case: str
) -> None:
    events: list[str] = []
    read_error = OSError("inventory read failed")
    stale_error = ValueError("final root changed")
    facts = (object(),)

    @contextmanager
    def guard():
        events.append("gc.enter")
        try:
            yield
        finally:
            events.append("gc.exit")

    @contextmanager
    def borrow():
        events.append("root.enter")
        try:
            yield 41
        finally:
            events.append("root.exit")

    class Product:
        policy = SimpleNamespace(product_id="coding")
        gc_gate = SimpleNamespace(guard=guard)
        epoch_runtime = SimpleNamespace(borrow_product_state_root_descriptor=borrow)

        @property
        def state_root(self):
            events.append("path")
            return Path("/query-state")

        def assert_root_gc_authority_current(self):
            events.append("current")
            if case == "stale" and events.count("current") == 2:
                raise stale_error

    def inspect(state_root, *, directory_fd):
        assert state_root == Path("/query-state") and directory_fd == 41
        assert events == ["gc.enter", "current", "root.enter", "path"]
        events.append("read")
        if case == "read-error":
            raise read_error
        return facts

    if kind == "payload":
        module = payload
        target = payload.inspect_coding_windows_product_worker_payload_attempts
        leaf = "inspect_windows_worker_payload_stages"
    else:
        from loushang.coding import (
            package_product_worker_windows_provisioning as native,
        )

        module = native
        target = native.inspect_coding_windows_product_worker_provisioning_attempts
        leaf = "inspect_windows_worker_provisioning_attempts"
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(module, "WindowsLocalWheelProductSessionOwner", Product)
    monkeypatch.setattr(module, leaf, inspect)
    if case == "normal":
        assert target(Product()) is facts
    else:
        with pytest.raises((OSError, ValueError)) as caught:
            target(Product())
        assert caught.value is (read_error if case == "read-error" else stale_error)
    assert events == [
        "gc.enter",
        "current",
        "root.enter",
        "path",
        "read",
        "root.exit",
    ] + ([] if case == "read-error" else ["current"]) + ["gc.exit"]
