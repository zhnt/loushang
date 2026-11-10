"""Explicit local differential probe; not a default-discovery PR gate."""

import json
import os
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_runtime as coding
import loushang.harness.package_product.product_local_wheel_runtime as core
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistryError,
)

ORACLE = Path(__file__).parent / "fixtures" / "ordinary_orphan_ordering_v1.jsonl"


@dataclass(frozen=True)
class Lease:
    lease_id: str
    runtime_id: str = "coding-session:abc"
    runtime_epoch: int = 4
    store_root_identity: str = "root"


def run_case(monkeypatch, platform, scenario, fail_at=None):
    trace = []
    remaining = ["a", "b"] if scenario in ("two", "mixed") else ["a"]
    if scenario == "empty":
        remaining.clear()

    def event(name):
        trace.append(name)
        if len(trace) == fail_at:
            raise OSError("injected:" + name)

    @contextmanager
    def scope(name):
        event(name + ":enter")
        try:
            yield
        finally:
            event(name + ":exit")

    leases = {key: Lease(key) for key in remaining}
    if scenario == "foreign":
        leases["a"] = replace(leases["a"], runtime_id="foreign:a")
    if scenario == "epoch":
        leases["a"] = replace(leases["a"], runtime_epoch=5)
    if scenario == "root":
        leases["a"] = replace(leases["a"], store_root_identity="foreign")
    if scenario == "mixed":
        leases["b"] = replace(leases["b"], runtime_id="foreign:b")

    class Registry:
        @property
        def store_id(self):
            event("registry.store_id")
            return "store"

        def review_orphans(self, *, store_id):
            event("review:" + store_id)
            return tuple(leases.values())

        def repair_orphan(self, lease_id, *, validation_guard=None):
            event("repair:" + lease_id)
            if scenario in ("absent", "registry_error"):
                raise PackageEpochRuntimeLeaseRegistryError(
                    "registry failure",
                    code=(
                        "package_epoch_lease_absent"
                        if scenario == "absent"
                        else "other"
                    ),
                )
            value = leases[lease_id]
            if scenario == "changed":
                value = replace(value, runtime_id="coding-session:changed")
            with validation_guard(value) if validation_guard else nullcontext():
                event("commit:" + lease_id)
                remaining.remove(lease_id)

    registry = Registry()

    class Epoch:
        def __init__(self, name):
            self.name = name

        @property
        def registry(self):
            event(self.name + ".registry")
            return registry

        @property
        def cutover_result(self):
            event(self.name + ".fence")
            return SimpleNamespace(
                fence=None
                if scenario == "no_fence"
                else SimpleNamespace(epoch=4, fenced_root_identity="root")
            )

        def assert_current(self):
            event(self.name + ".current")

        def borrow_product_state_root_descriptor(self):
            return scope(self.name + ".borrow")

    class Root:
        def stat(self):
            event("root.stat")
            return SimpleNamespace(
                st_dev=1, st_ino=3 if scenario == "root_changed" else 2
            )

    root = Root()

    class Product:
        epoch_runtime = Epoch("product_epoch")

        @property
        def state_root(self):
            event("product.root")
            return root

        @property
        def policy(self):
            event("product.policy")
            return SimpleNamespace(
                bindings=[
                    SimpleNamespace(
                        source_trust_class="local-worker-candidate"
                        if scenario == "worker_binding"
                        else "builtin"
                    )
                ]
            )

        @property
        def gc_gate(self):
            event("product.gc")
            return self

        def guard(self, *, require_write):
            event("gc.guard:" + str(require_write))
            return scope("gc")

        def assert_root_gc_authority_current(self):
            event("product.current")

    class PosixProduct(Product):
        pass

    class WindowsProduct(Product):
        pass

    class FakeOS:
        O_RDONLY = os.O_RDONLY
        O_DIRECTORY = os.O_DIRECTORY
        O_NOFOLLOW = os.O_NOFOLLOW
        O_CLOEXEC = os.O_CLOEXEC

        @staticmethod
        def open(path, flags):
            assert path is root
            event("os.open:" + str(flags))
            return 71

        @staticmethod
        def fstat(fd):
            assert fd == 71
            event("os.fstat")
            return SimpleNamespace(st_dev=1, st_ino=2)

        @staticmethod
        def listdir(target):
            event("os.listdir:" + ("fd" if target == 71 else "path"))
            return (
                ["WoRkEr-start.jsonl"]
                if scenario == "worker_file"
                else ["normal.jsonl"]
            )

        @staticmethod
        def close(fd):
            assert fd == 71
            event("os.close")

    product = WindowsProduct() if platform == "windows" else PosixProduct()
    owner = SimpleNamespace(
        runtime_owner=SimpleNamespace(product_owner=product),
        epoch_runtime=Epoch("outer_epoch"),
    )

    def describe(error):
        if error is None:
            return None
        return {
            "type": type(error).__name__,
            "message": str(error),
            "code": getattr(error, "code", None),
            "context": describe(error.__context__),
            "cause": describe(error.__cause__),
        }

    outcome = None
    with monkeypatch.context() as patch:
        patch.setattr(coding, "os", FakeOS)
        patch.setattr(core, "os", FakeOS)
        patch.setattr(coding, "PosixLocalWheelProductSessionOwner", PosixProduct)
        patch.setattr(coding, "WindowsLocalWheelProductSessionOwner", WindowsProduct)
        try:
            coding._repair_ordinary_coding_orphan_runtime_leases(owner)
        except BaseException as error:
            outcome = describe(error)
    return {"trace": trace, "outcome": outcome, "remaining": remaining}


RECORDS = [json.loads(line) for line in ORACLE.read_text().splitlines()]


@pytest.mark.parametrize(
    "record", RECORDS, ids=lambda r: f"{r['platform']}-{r['scenario']}-{r['fail_at']}"
)
def test_replay_original(monkeypatch, record):
    assert (
        run_case(monkeypatch, record["platform"], record["scenario"], record["fail_at"])
        == record["expected"]
    )
