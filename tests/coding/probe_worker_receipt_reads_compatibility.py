"""Frozen pre-A167 receipt reads, explicitly invoked local validation.

Seven actual public flows at b720d70aa; controlled IO, witness and verifier
ports, real receipt/configuration/payload DTOs. No capture mode or native
Windows claim. Excluded from default discovery and PR gate expansion.
"""

import asyncio
import gzip
import json
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import SimpleNamespace as NS

import pytest

import loushang.coding.package_product_worker_receipt as p
import loushang.coding.package_product_worker_windows_receipt as w
import loushang.harness.package_product.product_worker_candidate as c
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
)
from tests.harness.worker.test_product_activation import _policy, _receipt

EXPECTED = Path(__file__).parent / "fixtures" / "worker_receipt_reads_v1.json.gz"
FLOWS = {
    "native": (p.CodingWorkerProductReceiptOwner, "current_native_launch_material", 2),
    "linux-payload": (p.CodingWorkerProductReceiptOwner, "current_selected_payload", 4),
    "binding": (p.CodingWorkerProductReceiptOwner, "current_runtime_binding", 2),
    "linux-manifest": (
        p.CodingWorkerProductReceiptOwner,
        "current_selected_manifest",
        1,
    ),
    "windows-manifest": (
        w.CodingWindowsWorkerProductReceiptOwner,
        "current_selected_manifest",
        1,
    ),
    "windows-payload": (
        w.CodingWindowsWorkerProductReceiptOwner,
        "current_selected_payload",
        4,
    ),
    "pair": (
        w.CodingWindowsWorkerProductReceiptOwner,
        "current_payload_and_worker_owner_id",
        2,
    ),
}
PAYLOADS = {"linux-payload", "binding", "windows-payload", "pair"}
NATIVE = {"native", "linux-payload", "binding"}
CASES = []
for flow, (_, _, witnesses) in FLOWS.items():
    scenarios = ["ok", "invalid", "enter-fault", "exit-fault"] + [
        f"witness-{i}" for i in range(1, witnesses + 1)
    ]
    if flow != "native":
        scenarios += [
            "capture-physical",
            "capture-activation",
            "capture-read",
            "capture-unexpected",
            "capture-cancel",
            "pin-mismatch",
            "pin-mutated",
        ]
    if flow in NATIVE:
        scenarios += [
            "reader-none",
            "reader-foreign",
            "profile",
            "native-expected",
            "native-unexpected",
            "catalog",
        ]
    if flow in PAYLOADS:
        scenarios += [
            "candidate",
            "manifest",
            "configuration",
            "body",
            "digest",
            "fingerprint",
            "artifact",
            "constructor",
            "nested-root",
        ]
    if flow in {"linux-payload", "binding"}:
        scenarios += ["platform"]
    if flow == "windows-payload":
        scenarios += ["backend", "backend-catalog"]
    if flow in {"binding", "pair"}:
        scenarios += [
            "decision-none",
            "decision-revoke",
            "decision-invalid",
            "decision-fault",
        ]
    CASES.extend((flow, scenario) for scenario in scenarios)
CASES.extend(
    [
        ("binding", "body+decision-fault"),
        ("binding", "digest+decision-fault"),
        ("native", "catalog+witness-2"),
        ("linux-payload", "native-expected+capture-read"),
        ("linux-payload", "constructor+witness-4"),
        ("windows-payload", "constructor+witness-4"),
        ("pair", "decision-invalid+witness-2"),
    ]
)


def error(exc):
    if exc is None:
        return None
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "code": getattr(exc, "code", None),
        "cause": error(exc.__cause__),
        "context": error(exc.__context__),
        "suppress": exc.__suppress_context__,
    }


@pytest.mark.parametrize("flow,scenario", CASES, ids=[f"{f}:{s}" for f, s in CASES])
def test_flow(monkeypatch, flow, scenario):
    flags = set(scenario.split("+"))
    cls, method, expected_witnesses = FLOWS[flow]
    trace = []
    depth = 0
    witness_calls = 0
    configuration = p.PluginLocalWorkerConfiguration(
        entrypoint="bin/worker", protocol="query", protocol_version=1
    )
    profile = p.CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID
    policy = replace(
        _policy(),
        native_profile_id=profile,
        allowed_native_profile_ids=(profile,),
        worker_configuration_fingerprint=configuration.fingerprint,
    )
    if "profile" in flags:
        policy = _policy()
    receipt = _receipt(policy)
    witness = receipt.authority_witness
    body = b"controlled-worker-body"
    digest = sha256(body).hexdigest()
    candidate = c.WorkerPackageCandidateV1(
        policy.plugin_id,
        "1.0",
        policy.contribution_id,
        "hosting",
        True,
        policy.plugin_revision_digest,
        policy.reservation_fingerprint,
        policy.declaration_fingerprint,
        "f" * 64 if "fingerprint" in flags else configuration.fingerprint,
        "f" * 64 if "digest" in flags else digest,
        len(body),
    )
    root = "nested" if "nested-root" in flags else "."
    snapshot = NS(
        root_ref=NS(
            artifact_digest="f" * 64
            if "artifact" in flags
            else policy.plugin_revision_digest
        ),
        files=()
        if "body" in flags
        else ((("nested/" if root == "nested" else "") + "bin/worker", body),),
    )

    def verified():
        trace.append(["manifest", depth])
        if "manifest" in flags:
            raise RuntimeError("manifest failure")
        return NS(
            root_relative_path=PurePosixPath(root),
            contribution_index=NS(
                items=(
                    NS(
                        worker_configuration=None
                        if "configuration" in flags
                        else configuration
                    ),
                )
            ),
        )

    selected = NS(snapshot=snapshot, verified_manifest=verified)

    @contextmanager
    def guard():
        nonlocal depth
        trace.append(["enter", depth])
        if "enter-fault" in flags:
            raise RuntimeError("enter failure")
        depth += 1
        try:
            yield
        finally:
            depth -= 1
            trace.append(["exit", depth])
            if "exit-fault" in flags:
                raise RuntimeError("exit failure")

    product = NS(gc_gate=NS(guard=guard))
    owner = object.__new__(cls)
    owner._product = product
    owner._selected = object() if "pin-mismatch" in flags else selected

    def capture(plugin_id, **kwargs):
        trace.append(["capture", depth, plugin_id, kwargs])
        faults = {
            "capture-physical": lambda: PackagePhysicalStagingError(
                "physical failure", code="package_artifact_identity_changed"
            ),
            "capture-activation": lambda: p.PackageProductRuntimeActivationError(
                "activation failure", code="controlled"
            ),
            "capture-read": lambda: p.PackageProductRuntimeReadError(
                "read failure", code="controlled"
            ),
            "capture-unexpected": lambda: RuntimeError("capture failure"),
            "capture-cancel": lambda: asyncio.CancelledError("capture cancellation"),
        }
        if flags & faults.keys():
            raise faults[next(iter(flags & faults.keys()))]()
        if "pin-mutated" in flags:
            owner._selected = object()
        return selected

    owner._runtime = NS(capture_selected_plugin_manifest_for=capture)

    def current_witness(self, supplied):
        nonlocal witness_calls
        witness_calls += 1
        trace.append(["witness", depth, witness_calls, supplied is receipt])
        if f"witness-{witness_calls}" in flags or supplied is not receipt:
            return None
        return witness

    monkeypatch.setattr(cls, "current_witness", current_witness)
    closure = NS(
        native_platform="other" if "platform" in flags else "linux-x86_64",
        native_profile_catalog_revision="other"
        if bool(flags & {"catalog", "backend-catalog"})
        else policy.native_profile_catalog_revision,
    )
    material = p.CodingWorkerNativeLaunchMaterialV1(
        launcher_path=Path("/controlled/launcher"), closure=closure
    )
    reader = object.__new__(p.CodingProductInstalledWorkerReleaseReader)
    reader._product_owner = object() if "reader-foreign" in flags else product
    owner._native_closure_reader = None if "reader-none" in flags else reader

    def read_native(self):
        trace.append(["native", depth])
        if "native-expected" in flags:
            raise p.CodingWorkerNativeClosureReadError("native failure")
        if "native-unexpected" in flags:
            raise RuntimeError("native failure")
        return material

    monkeypatch.setattr(
        p.CodingProductInstalledWorkerReleaseReader,
        "current_launch_material",
        read_native,
    )

    def backend(supplied):
        trace.append(["backend", depth, supplied is product])
        if "backend" in flags:
            raise RuntimeError("backend failure")

        def get_closure():
            trace.append(["backend-closure", depth])
            return closure

        return NS(native_closure=get_closure, expectation="backend-expectation")

    monkeypatch.setattr(
        w, "read_coding_windows_worker_installed_backend_release", backend
    )
    opt_in = p.CodingWorkerOptInV1(
        policy.plugin_id,
        policy.contribution_id,
        "hosting",
        policy.plugin_revision_digest,
        "windows-amd64"
        if flow.startswith("windows") or flow == "pair"
        else "linux-x86_64",
        4,
        7,
        True,
    )

    def decision(plugin_id):
        trace.append(["decision", depth, plugin_id])
        if "decision-fault" in flags:
            raise RuntimeError("decision failure")
        if "decision-none" in flags:
            return None
        return NS(
            action="revoke" if "decision-revoke" in flags else "allow",
            opt_in=object() if "decision-invalid" in flags else opt_in,
        )

    owner._opt_in = NS(current=decision)

    def verify(supplied, **kwargs):
        trace.append(["candidate", depth, supplied is selected, kwargs])
        if "candidate" in flags:
            raise c.WorkerPackageCandidateError("controlled_candidate_failure")
        return candidate

    for module in (p, w, c):
        monkeypatch.setattr(
            module, "verify_product_selected_worker_candidate", verify, raising=False
        )
    payload_class = p.CodingWorkerSelectedPayloadV1

    def construct(**kwargs):
        trace.append(["constructor", depth])
        if "constructor" in flags:
            raise RuntimeError("constructor failure")
        return payload_class(**kwargs)

    for module in (p, w):
        monkeypatch.setattr(module, "CodingWorkerSelectedPayloadV1", construct)

    def normalize(value):
        if value is selected:
            return ["selected-identity"]
        if value is material:
            return ["native-identity"]
        if isinstance(value, payload_class):
            assert value.configuration is configuration
            return ["payload", value.body.hex(), value.digest, "configuration-identity"]
        if isinstance(value, tuple):
            return [normalize(v) for v in value]
        return value

    try:
        result = getattr(owner, method)(None if "invalid" in flags else receipt)
        observed = {"result": normalize(result), "error": None}
    except BaseException as exc:
        observed = {"result": None, "error": error(exc)}
    assert depth == 0
    observed["trace"] = trace
    if scenario in {"ok", "nested-root"}:
        assert observed["error"] is None, observed
        assert witness_calls == expected_witnesses
        assert observed["result"] is not None
    else:
        assert observed["error"] is not None, observed
    key = f"{flow}:{scenario}"
    expected = json.loads(gzip.decompress(EXPECTED.read_bytes()))
    assert observed == expected[key]
