"""Fixed original custody trace: actual coordination/Wheel, controlled authority/native IO ports.

No Windows ACL, Job, native handles, real approval journal, or Task.cancel claim.
Receipt write is a controlled atomic port response, not a second IO engine.
"""

from __future__ import annotations

import asyncio
import dataclasses
import gzip
import importlib
import importlib.metadata
import importlib.util
import json
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_worker_windows_backend_release as release
from loushang.coding import (
    package_product_worker_windows_installed_backend as installed,
)
from loushang.coding import (
    package_product_worker_windows_native_approval_owner as approval_owner,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalDecisionV1 as Decision,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeReleaseReviewV1 as Review,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner as Product,
)
from loushang.hosting import windows_backend_material as hosting
from tests.coding.probe_windows_stage_capture_compatibility import error_data
from tests.coding.test_package_windows_backend_release import _backend_wheel

_CORE_NAME = "loushang.harness.package_product._windows_worker_backend_release"
custody = (
    importlib.import_module(_CORE_NAME)
    if importlib.util.find_spec(_CORE_NAME) is not None
    else None
)

HERE = Path(__file__).parent
FIXED = HERE / "fixtures/windows_backend_custody_runtime_v1.json.gz"


def plain(value):
    if type(value) is Product:
        return {"controlled_product": "actual_product_class_instance"}
    if dataclasses.is_dataclass(value):
        return {
            "type": type(value).__module__ + "." + type(value).__qualname__,
            "fields": {
                f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)
            },
        }
    if isinstance(value, (list, tuple)):
        return [plain(x) for x in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": sha256(value).hexdigest()}
    return value


def spec(name, route, **data):
    return name, {"route": route, **data}


CASES = [
    spec("material-success", "material"),
    spec("review-success", "review"),
    spec("current-approved", "current"),
    spec("current-absent", "current", decision="absent"),
    spec("current-revoked", "current", decision="revoke"),
    spec("install-fresh", "install"),
    spec("install-existing-equal", "install", published="equal"),
    spec("install-existing-different", "install", published="different"),
    spec("install-exact-stage-retry", "install", staged="equal"),
    spec("install-partial-stage-refused", "install", staged="partial"),
    spec("install-both-refused", "install", published="equal", staged="equal"),
    spec("install-wrong-review", "install", wrong_review=True),
    spec("install-no-approval", "install", decision="absent"),
    spec("install-revoked-approval", "install", decision="revoke"),
    spec("install-other-approval", "install", decision="other"),
    spec("install-generation-drift", "install", generation_drift=True),
    spec("install-write-pre-error-retry", "install", write_mode="pre", retry=True),
    spec("install-write-post-error-retry", "install", write_mode="post", retry=True),
    spec(
        "install-postpublish-read-error-retry",
        "install",
        faults={"receipt.read#2": "OSError"},
        retry=True,
    ),
    spec(
        "install-postpublish-approval-error-retry",
        "install",
        faults={"journal.read#2": "ApprovalError"},
        retry=True,
    ),
    spec(
        "install-postpublish-ctor-error-retry",
        "install",
        faults={"ctor.Installed#1": "ValueError"},
        retry=True,
    ),
    spec("read-success", "read", published="equal"),
    spec("read-absent", "read"),
    spec("read-unpublished-stage", "read", staged="equal"),
    spec("read-both", "read", published="equal", staged="equal"),
    spec("read-no-approval", "read", published="equal", decision="absent"),
    spec("read-revoked", "read", published="equal", decision="revoke"),
    spec("reader-repeat-current", "reader", published="equal"),
    spec("reader-revoke-second", "reader", published="equal", revoke_second=True),
    spec("admission-material-platform", "material", platform="posix"),
    spec("admission-read-platform", "read", platform="posix"),
    spec("admission-install-product", "install", product_id="foreign"),
    spec("admission-material-trust", "material", trust="unknown"),
    spec("install-empty-input", "install", wheel_input="empty"),
    spec("install-review-type", "install", review_input=7),
]
for number in (1, 2, 3):
    CASES.append(
        spec(
            f"material-image-{number}-error",
            "material",
            faults={f"image.capture#{number}": "OSError"},
        )
    )
for name, point in (
    ("installed-members", "material.members#1"),
    ("loaded-sources", "material.sources#1"),
    ("candidate-ctor", "ctor.Candidate#1"),
    ("review-ctor", "ctor.Review#1"),
    ("material-ctor", "ctor.Material#1"),
    ("wheel-inspect", "wheel.inspect#1"),
    ("version", "version#1"),
):
    CASES.append(
        spec(f"material-{name}-error", "material", faults={point: "ValueError"})
    )
for kind in (
    "ReceiptError",
    "ApprovalError",
    "WheelError",
    "ImportError",
    "OSError",
    "TypeError",
    "ValueError",
    "RuntimeError",
    "CancelledError",
    "KeyboardInterrupt",
    "StopIteration",
):
    CASES.append(
        spec(
            "read-error-" + kind,
            "read",
            published="equal",
            faults={"receipt.read#1": kind},
        )
    )
for route in ("material", "install", "read", "current"):
    for point in ("gc.enter#1", "gc.exit#1", "root.assert#1"):
        CASES.append(
            spec(
                f"{route}-{point}-error",
                route,
                published="equal",
                faults={point: "ValueError"},
            )
        )
for route in ("install", "read", "current"):
    CASES.append(
        spec(
            f"{route}-epoch-exit-error",
            route,
            published="equal",
            faults={"epoch.exit#1": "ValueError"},
        )
    )
CASES.extend(
    [
        spec(
            "material-body-and-gc-error",
            "material",
            faults={"material.members#1": "OSError", "gc.exit#1": "ValueError"},
        ),
        spec(
            "read-body-epoch-and-gc-error",
            "read",
            published="equal",
            faults={
                "receipt.read#1": "OSError",
                "epoch.exit#1": "TypeError",
                "gc.exit#1": "ValueError",
            },
        ),
        spec(
            "current-body-and-epoch-error",
            "current",
            faults={"journal.read#1": "OSError", "epoch.exit#1": "ValueError"},
        ),
        spec(
            "install-postpublish-epoch-error-retry",
            "install",
            faults={"epoch.exit#2": "ValueError"},
            retry=True,
        ),
        spec(
            "install-postpublish-final-root-error-retry",
            "install",
            faults={"root.assert#8": "ValueError"},
            retry=True,
        ),
        spec(
            "install-postpublish-final-gc-error-retry",
            "install",
            faults={"gc.exit#4": "ValueError"},
            retry=True,
        ),
        spec(
            "read-installed-ctor-error",
            "read",
            published="equal",
            faults={"ctor.Installed#1": "ValueError"},
        ),
        spec(
            "read-approval-ctor-error",
            "read",
            published="equal",
            faults={"ctor.ApprovalOwner#1": "TypeError"},
        ),
        spec(
            "current-journal-ctor-error",
            "current",
            faults={"journal.ctor#1": "OSError"},
        ),
    ]
)


def observe(data, monkeypatch):
    trace, active, calls = [], [], {}
    wheel = _backend_wheel()
    image = hosting.WindowsPythonHostImagesV1("a" * 64, "b" * 64)
    inert = release.inspect_coding_windows_worker_backend_candidate(
        loushang_wheel=wheel,
        python_executable_sha256=image.python_executable_sha256,
        python_runtime_dll_sha256=image.python_runtime_dll_sha256,
    )
    review = Review.create(
        scope_id="scope", product_policy_revision="policy-1", approval=inert.approval
    )
    state = {
        "published": wheel
        if data.get("published") == "equal"
        else b"foreign"
        if data.get("published")
        else None,
        "staged": wheel
        if data.get("staged") == "equal"
        else wheel[:4]
        if data.get("staged")
        else None,
        "decision": data.get("decision", "approve"),
    }

    def tap(label, *arguments):
        calls[label] = calls.get(label, 0) + 1
        key = f"{label}#{calls[label]}"
        trace.append([key, plain(arguments), list(active)])
        kind = data.get("faults", {}).get(key)
        if kind:
            types = {
                "ReceiptError": installed.CodingWindowsPrivateReceiptError,
                "ApprovalError": installed.CodingWorkerNativeApprovalError,
                "WheelError": installed.PackageWheelVerificationError,
                "ImportError": ImportError,
                "OSError": OSError,
                "ValueError": ValueError,
                "TypeError": TypeError,
                "RuntimeError": RuntimeError,
                "CancelledError": asyncio.CancelledError,
                "KeyboardInterrupt": KeyboardInterrupt,
                "StopIteration": StopIteration,
            }
            if kind == "WheelError":
                raise types[kind](
                    key, code="controlled_wheel_error", stage="inspecting"
                )
            raise types[kind](key)

    @contextmanager
    def scope(name, **kwargs):
        tap(name + ".enter", kwargs)
        active.append(name)
        try:
            yield 91 if name == "epoch" else frozenset()
        finally:
            try:
                tap(name + ".exit")
            finally:
                assert active.pop() == name

    def root():
        tap("state_root")
        return Path("/controlled-product")

    product = Product.__new__(Product)
    object.__setattr__(
        product,
        "policy",
        NS(
            product_id=data.get("product_id", "coding"),
            bindings=(
                NS(source_trust_class=data.get("trust", "local-worker-candidate")),
            ),
            project_scope_id="scope",
            authority_revision="policy-1",
        ),
    )
    object.__setattr__(
        product, "gc_gate", NS(guard=lambda **kwargs: scope("gc", **kwargs))
    )
    object.__setattr__(
        product,
        "epoch_runtime",
        NS(
            prepare_product_state_root=root,
            borrow_product_state_root_descriptor=lambda: scope("epoch"),
        ),
    )
    monkeypatch.setattr(
        Product, "assert_root_gc_authority_current", lambda self: tap("root.assert")
    )
    for module in (release, installed, approval_owner):
        if hasattr(module, "os"):
            monkeypatch.setattr(module, "os", NS(name=data.get("platform", "nt")))

    def images():
        tap("image.capture")
        return image

    effects = custody if custody is not None else release
    monkeypatch.setattr(effects, "capture_windows_python_host_images", images)
    monkeypatch.setattr(hosting, "capture_windows_python_host_images", images)
    monkeypatch.setattr(
        hosting,
        "verify_windows_loushang_installed_package_members",
        lambda members: tap("material.members", members),
    )
    monkeypatch.setattr(
        hosting,
        "verify_windows_lpac_loaded_backend_sources",
        lambda members: tap("material.sources", members),
    )
    monkeypatch.setattr(hosting, "os", NS(name="nt"))
    original_version = effects.version
    original_inspect = effects.inspect_package_wheel_bytes

    def version(name):
        tap("version", name)
        return original_version(name)

    def inspect(body, **kwargs):
        tap("wheel.inspect", body, kwargs)
        return original_inspect(body, **kwargs)

    monkeypatch.setattr(effects, "version", version)
    monkeypatch.setattr(effects, "inspect_package_wheel_bytes", inspect)
    original_zip = effects.zipfile.ZipFile

    class TracedZip(original_zip):
        def __enter__(self):
            result = super().__enter__()
            tap("zip.enter")
            active.append("zip")
            return result

        def __exit__(self, *arguments):
            try:
                return super().__exit__(*arguments)
            finally:
                try:
                    tap("zip.exit")
                finally:
                    assert active.pop() == "zip"

    monkeypatch.setattr(effects.zipfile, "ZipFile", TracedZip)

    for actual, label in (
        (release.CodingWindowsWorkerBackendCandidateV1, "Candidate"),
        (Review, "Review"),
        (release.CodingWindowsWorkerBackendMaterialReviewV1, "Material"),
        (installed.CodingWindowsWorkerInstalledBackendV1, "Installed"),
        (approval_owner.CodingWindowsWorkerNativeApprovalOwner, "ApprovalOwner"),
    ):
        original_init = actual.__init__

        def init(self, *args, _init=original_init, _label=label, **kwargs):
            tap("ctor." + _label, args, kwargs)
            _init(self, *args, **kwargs)

        monkeypatch.setattr(actual, "__init__", init)

    class Journal:
        def __init__(self, path, *, scope_id):
            tap("journal.ctor", str(path), scope_id)

        def _read_records(self, *, directory_fd):
            tap("journal.read", directory_fd)
            if state["decision"] == "absent":
                return ()
            generation = (
                2 if data.get("generation_drift") and calls["journal.read"] >= 2 else 1
            )
            return (
                Decision.create(
                    journal_revision=1,
                    scope_id="scope",
                    operation_id="approval",
                    generation=generation,
                    action="revoke" if state["decision"] == "revoke" else "approve",
                    approval=None
                    if state["decision"] == "revoke"
                    else dataclasses.replace(inert.approval, launcher_sha256="c" * 64)
                    if state["decision"] == "other"
                    else inert.approval,
                ),
            )

        def current(self, *, directory_fd):
            events = self._read_records(directory_fd=directory_fd)
            return events[-1] if events else None

    monkeypatch.setattr(
        approval_owner, "CodingWindowsWorkerNativeApprovalJournal", Journal
    )

    def read_receipt(path, *, maximum_bytes, allow_unpublished_stage=False):
        tap("receipt.read", str(path), maximum_bytes, allow_unpublished_stage)
        if state["staged"] is not None and (
            state["published"] is not None or not allow_unpublished_stage
        ):
            raise installed.CodingWindowsPrivateReceiptError("controlled stage refusal")
        return state["published"]

    def write_receipt(path, payload, *, maximum_bytes):
        tap("receipt.write", str(path), payload, maximum_bytes)
        if state["staged"] is not None and state["staged"] != payload:
            raise installed.CodingWindowsPrivateReceiptError(
                "controlled conflicting stage"
            )
        if data.get("write_mode") == "pre" and calls["receipt.write"] == 1:
            state["staged"] = payload[:4]
            raise OSError("controlled write left partial stage")
        state["published"], state["staged"] = payload, None
        if data.get("write_mode") == "post" and calls["receipt.write"] == 1:
            raise OSError("controlled write published then failed")

    if hasattr(installed, "read_windows_private_receipt"):
        monkeypatch.setattr(installed, "read_windows_private_receipt", read_receipt)
    if hasattr(installed, "write_windows_private_receipt"):
        monkeypatch.setattr(installed, "write_windows_private_receipt", write_receipt)
    if hasattr(installed, "_receipt_io"):
        io_type = type(installed._receipt_io)
        monkeypatch.setattr(
            io_type,
            "read_private_receipt",
            lambda self, *args, **kwargs: read_receipt(*args, **kwargs),
        )
        monkeypatch.setattr(
            io_type,
            "write_private_receipt",
            lambda self, *args, **kwargs: write_receipt(*args, **kwargs),
        )

    def operation():
        route = data["route"]
        if route == "material":
            return release.inspect_coding_windows_worker_backend_material(
                product, loushang_wheel=wheel
            )
        if route == "review":
            return release.review_coding_windows_worker_backend_release(
                product, loushang_wheel=wheel
            )
        if route == "current":
            return approval_owner.CodingWindowsWorkerNativeApprovalOwner(
                product
            ).current()
        if route == "install":
            return installed.install_coding_windows_worker_backend_release(
                product,
                loushang_wheel=b"" if data.get("wheel_input") == "empty" else wheel,
                review_id=data.get(
                    "review_input",
                    "wrong" if data.get("wrong_review") else review.review_id,
                ),
            )
        if route == "reader":
            reader = installed.CodingWindowsWorkerInstalledBackendReader(product)
            first = reader.current_closure()
            if data.get("revoke_second"):
                state["decision"] = "revoke"
            return (
                first,
                reader.gc_gate is product.gc_gate,
                reader.product_owner is product,
                reader.current_closure(),
            )
        return installed.read_coding_windows_worker_installed_backend_release(product)

    results = []
    for _ in range(2 if data.get("retry") else 1):
        try:
            results.append({"result": plain(operation()), "error": None})
        except BaseException as error:
            results.append({"result": None, "error": error_data(error)})
        trace.append(["operation.finished", plain(state), list(active)])
    assert active == []
    return {"results": results, "trace": trace, "state": plain(state), "active": active}


@pytest.mark.parametrize("name,data", CASES, ids=[name for name, _ in CASES])
def test_original_windows_backend_custody(name, data, monkeypatch):
    actual = observe(data, monkeypatch)
    successes = {
        "material-success",
        "review-success",
        "current-approved",
        "current-absent",
        "current-revoked",
        "install-fresh",
        "install-existing-equal",
        "install-exact-stage-retry",
        "read-success",
        "reader-repeat-current",
    }
    assert (actual["results"][0]["error"] is None) == (name in successes), (
        name,
        actual["results"],
    )
    assert set(data.get("faults", {})) <= {entry[0] for entry in actual["trace"]}
    expected = json.loads(gzip.decompress(FIXED.read_bytes()))[name]
    assert json.dumps(actual, sort_keys=True, ensure_ascii=False) == json.dumps(
        expected, sort_keys=True, ensure_ascii=False
    )
