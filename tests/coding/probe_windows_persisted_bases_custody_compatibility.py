"""Old-first complete persisted reader; typed codecs, controlled native/read ports."""

from __future__ import annotations

import builtins
import dataclasses
import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_legacy_windows_receipt as receipt_module
import loushang.coding.package_product_worker_windows_history_cutover_record as cutover_module
import loushang.coding.package_product_worker_windows_persisted_bases as code
import loushang.harness.package_product._worker_windows_attempt as core
import loushang.harness.resources.packages._private_receipts_windows as receipt_io_module
from loushang.coding.package_product_backup_types import (
    CodingWorkerBackupReferenceObservationV1,
)
from loushang.coding.package_product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    _coding_windows_worker_desired_history_digest,
)
from loushang.coding.package_product_worker_windows_package_references import (
    CodingWindowsWorkerPackageReferenceReviewV1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.worker.history._windows_sources import WindowsHistoryNames
from tests.coding.probe_windows_live_stage_verification_compatibility import (
    Trace,
    error_data,
)
from tests.coding.test_package_product_worker_windows_history_join import _empty_read

EXPECTED = (
    Path(__file__).parent / "fixtures" / "windows_persisted_bases_custody_v1.json.gz"
)
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Linux controlled Windows receipt/authority IO; no Kernel or cold-loader claim",
)


def seed():
    desired = PluginDesiredStateSnapshotV1(inventory_revision=0, installations=())
    semantic = replace(
        _empty_read(),
        desired_inventory_revision=0,
        desired_history_digest=_coding_windows_worker_desired_history_digest(
            desired, ()
        ),
        desired_snapshot=desired,
        desired_transitions=(),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    topology = CodingWorkerBackupReferenceObservationV1(
        attempt_id="0" * 32,
        owner_revision="coding-product-backup-types:"
        + hashlib.sha256(b"topology").hexdigest(),
        worker_backup_supported=False,
        references=(),
    )
    review = CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
        prepared,
        semantic,
        quiescence=PackageWindowsRuntimeQuiescenceV1(
            store_id="store-a", owner_revision=1, active_runtime_lease_ids=()
        ),
        backup_topology=topology,
    )
    checkpoint = code.CodingWindowsWorkerHistoryCheckpointV1.from_guarded_read(
        prepared, semantic, review, ()
    )
    joined = CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(
        prepared, semantic
    )
    result = code.CodingWindowsWorkerPersistedBasesV1(
        checkpoint=checkpoint,
        opt_in=joined.opt_in,
        receipt=joined.receipt,
        supervisor=joined.supervisor,
        c5=joined.c5,
        launch_intent=joined.launch_intent,
        native_provisioning=joined.native_provisioning,
    )
    cutover = (
        cutover_module.CodingWindowsWorkerHistoryCutoverRecordV1.from_persisted_bases(
            result
        )
    )
    files = {
        code._CHECKPOINT_NAME: checkpoint.to_bytes(),
        code.WINDOWS_WORKER_HISTORY_CUTOVER_NAME: cutover.to_bytes(),
    }
    fields = (
        "opt_in",
        "receipt",
        "supervisor",
        "c5",
        "launch_intent",
        "native_provisioning",
    )
    files.update(
        {
            name: getattr(result, field).to_bytes()
            for (_, name), field in zip(code.WINDOWS_WORKER_BASE_FILES, fields)
        }
    )
    return result, files


def value(item):
    if dataclasses.is_dataclass(item):
        return dict(
            type=f"{type(item).__module__}.{type(item).__qualname__}",
            fields={
                f.name: value(getattr(item, f.name)) for f in dataclasses.fields(item)
            },
        )
    if isinstance(item, (tuple, list)):
        return [value(x) for x in item]
    if isinstance(item, (set, frozenset)):
        return sorted(value(x) for x in item)
    return item


def observe(spec, monkeypatch):
    seeded, files = seed()
    trace = Trace(spec.get("faults", ()))
    reads = Counter()
    scopes = set()
    root_reads = 0
    scans = 0
    root = 55
    require_cutover = spec.get("cutover", False)
    names = [
        code._CHECKPOINT_NAME,
        *(name for _, name in code.WINDOWS_WORKER_BASE_FILES),
    ]
    if require_cutover or spec.get("marker_present"):
        names.append(code.WINDOWS_WORKER_HISTORY_CUTOVER_NAME)
    if spec.get("no_marker"):
        names.remove(code.WINDOWS_WORKER_HISTORY_CUTOVER_NAME)
    if spec.get("duplicate_marker"):
        names.append(code.WINDOWS_WORKER_HISTORY_CUTOVER_NAME)
    if spec.get("extra"):
        names.append(spec["extra"])
    missing = spec.get("missing")
    if missing:
        files[missing] = None
    if spec.get("corrupt"):
        files[spec["corrupt"]] = b"{}"
    original_lstat = Path.lstat
    original_import = builtins.__import__
    original_names = WindowsHistoryNames.require_known
    original_ctor = code.CodingWindowsWorkerPersistedBasesV1.__init__
    classes = [
        code.CodingWindowsWorkerHistoryCheckpointV1,
        code.CodingWindowsWorkerOptInSemanticBaseV1,
        code.CodingWindowsWorkerReceiptSemanticBaseV1,
        code.CodingWindowsWorkerSupervisorSemanticBaseV1,
        code.CodingWindowsWorkerC5SemanticBaseV1,
        code.CodingWindowsWorkerLaunchIntentSemanticBaseV1,
        code.CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
        cutover_module.CodingWindowsWorkerHistoryCutoverRecordV1,
    ]
    original_decoders = [(cls, cls.from_bytes) for cls in classes]
    original_validate = (
        cutover_module.CodingWindowsWorkerHistoryCutoverRecordV1.require_persisted_bases
    )

    def event(*row):
        trace.append(list(row))

    class Scope:
        def __init__(self, name, result=None):
            self.name, self.result = name, result

        def __enter__(self):
            event(self.name + "-enter")
            scopes.add(self.name)
            return self.result

        def __exit__(self, _type, error, _tb):
            event(self.name + "-exit", error_data(error))
            scopes.remove(self.name)

    def quiescence(**kwargs):
        event("quiescence-request", kwargs)
        return Scope(
            "quiescence",
            SimpleNamespace(
                active_runtime_lease_ids=("active",) if spec.get("active") else ()
            ),
        )

    def guard(**kwargs):
        event("gc-request", kwargs)
        return Scope("gc")

    def current(self):
        event("current")

    def state_root(self):
        nonlocal root_reads
        root_reads += 1
        event("root-path", root_reads)
        return Path("/product-state")

    product = object.__new__(WindowsLocalWheelProductSessionOwner)
    object.__setattr__(
        product,
        "policy",
        SimpleNamespace(product_id="foreign" if spec.get("foreign") else "coding"),
    )
    object.__setattr__(
        product,
        "epoch_runtime",
        SimpleNamespace(
            registry=SimpleNamespace(
                store_id="store-a", exclusive_runtime_quiescence=quiescence
            ),
            borrow_product_state_root_descriptor=lambda: Scope("root", root),
        ),
    )
    object.__setattr__(product, "gc_gate", SimpleNamespace(guard=guard))

    class Acl:
        def __init__(self):
            event("acl-construct")

        def __enter__(self):
            event("acl-enter")
            scopes.add("acl")
            return self

        def __exit__(self, _type, error, _tb):
            event("acl-exit", error_data(error))
            scopes.remove("acl")

        def validate(self, fd):
            assert fd == root
            event("acl-validate")

    def fstat(fd):
        assert fd == root
        event("fstat")
        return SimpleNamespace(
            st_dev=1, st_ino=10, st_file_attributes=16, st_mode=0o40700
        )

    def lstat(path, *args, **kwargs):
        if str(path) != "/product-state":
            return original_lstat(path, *args, **kwargs)
        event("lstat", root_reads)
        return SimpleNamespace(
            st_dev=1, st_ino=99 if spec.get("root_changed") == root_reads else 10
        )

    def listdir(fd):
        nonlocal scans
        assert fd == root
        scans += 1
        event("listdir", scans)
        return (
            tuple(reversed(names))
            if spec.get("names_changed") and scans == 2
            else tuple(names)
        )

    def attributes(self, metadata, *, directory):
        assert self is receipt_module._receipt_io and directory
        event("attributes")
        return original_attributes(metadata, directory=directory)

    def streams(self, fd):
        assert self is receipt_module._receipt_io and fd == root
        event("streams")
        return original_streams(fd)

    original_attributes = receipt_module._receipt_io._require_simple_attributes
    original_streams = receipt_module._receipt_io._require_no_named_directory_streams

    def read_file(self, fd, acl, name, *, maximum_bytes):
        assert self is receipt_module._receipt_io and fd == root and type(acl) is Acl
        reads[name] += 1
        raw = files[name]
        if spec.get("changed") == name and reads[name] == 2:
            raw = b"changed-after-initial-read"
        event(
            "read-file",
            name,
            maximum_bytes,
            reads[name],
            None if raw is None else hashlib.sha256(raw).hexdigest(),
        )
        return raw

    def known(self, seen):
        event("known-names", list(seen))
        return original_names(self, seen)

    def construct(self, **kwargs):
        event("result-construct")
        return original_ctor(self, **kwargs)

    def decode(cls, original):
        def call(_cls, raw):
            event("decode", cls.__name__, hashlib.sha256(raw).hexdigest())
            return original(raw)

        return classmethod(call)

    def validate(self, result):
        event("cutover-validate")
        return original_validate(self, result)

    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if name.endswith("package_product_worker_windows_history_cutover_record"):
            event("cutover-binding")
        return original_import(name, globals, locals, fromlist, level)

    outcome, error = None, None
    with monkeypatch.context() as patch:
        fake_os = SimpleNamespace(
            name="posix" if spec.get("platform") else "nt", fstat=fstat, path=os.path
        )
        for module in (code, core):
            patch.setattr(module, "os", fake_os)
            if hasattr(module, "WindowsPrivateDirectoryAcl"):
                patch.setattr(module, "WindowsPrivateDirectoryAcl", Acl)
            if hasattr(module, "windows_listdir_at"):
                patch.setattr(module, "windows_listdir_at", listdir)
        if hasattr(code, "_read_file"):
            patch.setattr(
                code,
                "_read_file",
                lambda *args, **kw: read_file(receipt_module._receipt_io, *args, **kw),
            )
        if hasattr(code, "_require_simple_attributes"):
            patch.setattr(
                code,
                "_require_simple_attributes",
                lambda *args, **kw: attributes(receipt_module._receipt_io, *args, **kw),
            )
        if hasattr(code, "_require_no_named_directory_streams"):
            patch.setattr(
                code,
                "_require_no_named_directory_streams",
                lambda *args, **kw: streams(receipt_module._receipt_io, *args, **kw),
            )
        patch.setattr(WindowsPrivateReceiptIO, "_read_file", read_file)
        patch.setattr(WindowsPrivateReceiptIO, "_require_simple_attributes", attributes)
        patch.setattr(
            WindowsPrivateReceiptIO, "_require_no_named_directory_streams", streams
        )
        patch.setattr(
            receipt_io_module, "windows_directory_stream_names", lambda fd: ("::$DATA",)
        )
        patch.setattr(WindowsHistoryNames, "require_known", known)
        patch.setattr(
            WindowsLocalWheelProductSessionOwner, "state_root", property(state_root)
        )
        patch.setattr(
            WindowsLocalWheelProductSessionOwner,
            "assert_root_gc_authority_current",
            current,
        )
        patch.setattr(Path, "lstat", lstat)
        patch.setattr(code.CodingWindowsWorkerPersistedBasesV1, "__init__", construct)
        for cls, original in original_decoders:
            patch.setattr(cls, "from_bytes", decode(cls, original))
        patch.setattr(
            cutover_module.CodingWindowsWorkerHistoryCutoverRecordV1,
            "require_persisted_bases",
            validate,
        )
        patch.setattr(builtins, "__import__", importing)
        try:
            if spec.get("under"):
                outcome = (
                    code._read_coding_windows_worker_persisted_bases_under_gc_guard(
                        product, spec.get("root", root), require_cutover=require_cutover
                    )
                )
            elif require_cutover:
                outcome = code.read_coding_windows_worker_persisted_cutover(product)
            else:
                outcome = code.read_coding_windows_worker_persisted_bases(product)
        except BaseException as caught:
            error = error_data(caught)
    assert trace.fired == [
        [f["event"], f.get("occurrence", 1)] for f in spec.get("faults", ())
    ], (spec, trace.fired, trace)
    failure = any(
        spec.get(key)
        for key in (
            "faults",
            "missing",
            "corrupt",
            "changed",
            "root_changed",
            "names_changed",
            "active",
            "foreign",
            "platform",
            "extra",
            "duplicate_marker",
            "marker_present",
            "no_marker",
        )
    ) or ("root" in spec and (type(spec["root"]) is not int or spec["root"] < 0))
    if failure:
        assert error is not None and outcome is None, (spec, error, trace)
    else:
        assert error is None and outcome is not None and not scopes, (
            spec,
            error,
            trace,
        )
        actual = (
            outcome[1]
            if require_cutover and not spec.get("under")
            else outcome[0]
            if spec.get("under")
            else outcome
        )
        assert (
            type(actual) is code.CodingWindowsWorkerPersistedBasesV1
            and actual == seeded
        )
    return dict(
        trace=list(trace),
        fired=trace.fired,
        error=error,
        result=value(outcome),
        pending_scopes=sorted(scopes),
        reads=dict(reads),
        root_reads=root_reads,
    )


def source_guard():
    root = Path(__file__).resolve().parents[2]
    for module, relative in (
        (code, "src/loushang/coding/package_product_worker_windows_persisted_bases.py"),
        (core, "src/loushang/harness/package_product/_worker_windows_attempt.py"),
    ):
        assert Path(module.__file__).resolve() == root / relative


_ROWS = json.loads(gzip.decompress(EXPECTED.read_bytes()))


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row["spec"]["name"])
def test_replay(row, monkeypatch):
    source_guard()
    assert json.dumps(observe(row["spec"], monkeypatch), sort_keys=True) == json.dumps(
        row["result"], sort_keys=True
    )
