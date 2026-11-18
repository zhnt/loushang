"""Fixed pre-A165 kill-switch transactions, explicitly invoked local validation.

Original real receipt methods at 2afde2ce1, valid Code records, controlled GC and
journal effects. No capture mode, default PR discovery or native Windows claim.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import package_product_worker_receipt as posix
from loushang.coding import package_product_worker_windows_receipt as windows
from loushang.coding.package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from loushang.coding.package_product_worker_policy import CodingWorkerOptInV1

EXPECTED = Path(__file__).parent / "fixtures" / "worker_kill_switch_v1.json.gz"
SCOPE = "workspace:" + "a" * 64
PLUGIN = "example.worker"
CASES = (
    "valid",
    "absent",
    "replay",
    "stale-allow",
    "stale-revoke",
    "guard-enter-fail",
    "root-fail",
    "current-fail",
    "canonical-fail",
    "hash-fail",
    "mutation-fail",
    "mutation-cancel",
    "mutation-after-write-retry",
    "exit-after-write-retry",
    "exit-after-error",
    "lookup-before-generation",
    "invalid-none",
    "invalid-true",
    "invalid-false",
    "invalid-float",
    "invalid-string",
    "invalid-negative",
    "invalid-int-subclass",
)


def graph(error):
    seen = {}

    def visit(value):
        if value is None:
            return None
        if id(value) in seen:
            return {"ref": seen[id(value)]}
        index = len(seen)
        seen[id(value)] = index
        return {
            "id": index,
            "type": type(value).__module__ + "." + type(value).__qualname__,
            "args": list(value.args),
            "notes": getattr(value, "__notes__", []),
            "suppress": value.__suppress_context__,
            "cause": visit(value.__cause__),
            "context": visit(value.__context__),
        }

    return visit(error)


def observe(platform, case, monkeypatch):
    events = []
    depth = 0
    exits = 0
    module, owner_type = (
        (posix, posix.CodingWorkerProductReceiptOwner)
        if platform == "posix"
        else (windows, windows.CodingWindowsWorkerProductReceiptOwner)
    )
    native = "linux-x86_64" if platform == "posix" else "windows-amd64"

    def decision(action="allow", kill=2, generation=3, operation="initial"):
        opt_in = (
            None
            if action == "revoke"
            else CodingWorkerOptInV1(
                plugin_id=PLUGIN,
                contribution_id="query",
                owner_id="coding.query",
                artifact_digest="b" * 64,
                native_platform=native,
                owner_selection_generation=generation,
                kill_switch_generation=kill,
                require_worker=False,
            )
        )
        return CodingWorkerOptInDecisionV1.create(
            journal_revision=generation,
            scope_id=SCOPE,
            plugin_id=PLUGIN,
            operation_id=operation,
            generation=generation,
            kill_switch_generation=kill,
            action=action,
            opt_in=opt_in,
        )

    initial = decision()
    if case == "absent":
        initial = None
    if case == "replay":
        initial = decision("revoke", 3, 4)
    if case == "stale-allow":
        initial = decision(kill=3)
    if case == "stale-revoke":
        initial = decision("revoke", 2, 4)

    class DecisionWithFault:
        action = "allow"
        kill_switch_generation = 2

        @property
        def generation(self):
            events.append(["generation-getter"])
            raise ValueError("generation getter fault")

    if case == "lookup-before-generation":
        initial = DecisionWithFault()
    state = {"decision": initial, "writes": 0}

    class Guard:
        def __enter__(self):
            nonlocal depth
            events.append(["enter", depth])
            if case == "guard-enter-fail":
                raise PermissionError("guard denied")
            depth += 1

        def __exit__(self, exc_type, exc, tb):
            nonlocal depth, exits
            events.append(
                ["exit", depth, None if exc_type is None else exc_type.__name__]
            )
            depth -= 1
            exits += 1
            if exits == 1 and case in ("exit-after-write-retry", "exit-after-error"):
                raise OSError("guard exit failure")

    class Gate:
        def guard(self, **kwargs):
            events.append(["guard", kwargs])
            return Guard()

    def root_current():
        events.append(["root-current", depth])
        assert depth == 1
        if case == "root-fail":
            raise OSError("root changed")

    class Journal:
        def __getattribute__(self, name):
            if name in ("change", "revoke") and case == "lookup-before-generation":
                events.append(["mutation-lookup", name])
                raise AttributeError("mutation lookup fault")
            return object.__getattribute__(self, name)

        def current(self, plugin_id):
            events.append(["current", plugin_id, depth])
            assert depth == 1
            if case == "current-fail":
                raise OSError("current read failure")
            return state["decision"]

        def mutation(self, kind, kwargs):
            events.append([kind, kwargs, depth])
            assert depth == 1
            if case in ("mutation-fail", "exit-after-error"):
                raise OSError("mutation failure")
            if case == "mutation-cancel":
                raise asyncio.CancelledError("mutation cancelled")
            state["writes"] += 1
            next_record = decision("revoke", 3, 4, kwargs["operation_id"])
            state["decision"] = next_record
            if case == "mutation-after-write-retry" and state["writes"] == 1:
                raise OSError("failure after committed record")
            return next_record

        def change(self, **kwargs):
            return self.mutation("change", kwargs)

        def revoke(self, **kwargs):
            return self.mutation("revoke", kwargs)

    execution_globals = owner_type._latch_kill_switch.__globals__
    canonical = execution_globals["canonical_json_bytes"]
    sha = execution_globals["sha256"]

    def encode(value):
        events.append(["canonical", value, depth])
        if case == "canonical-fail":
            raise ValueError("canonical failure")
        return canonical(value)

    def digest(value):
        events.append(["hash", value.hex(), depth])
        if case == "hash-fail":
            raise ValueError("hash failure")
        return sha(value)

    monkeypatch.setitem(execution_globals, "canonical_json_bytes", encode)
    monkeypatch.setitem(execution_globals, "sha256", digest)
    owner = object.__new__(owner_type)
    owner._product = SimpleNamespace(
        gc_gate=Gate(),
        assert_root_gc_authority_current=root_current,
        policy=SimpleNamespace(project_scope_id=SCOPE),
    )
    owner._selected = SimpleNamespace(
        snapshot=SimpleNamespace(installation_key=SimpleNamespace(plugin_id=PLUGIN))
    )
    owner._opt_in = Journal()

    class IntSubclass(int):
        pass

    expected = {
        "invalid-none": None,
        "invalid-true": True,
        "invalid-false": False,
        "invalid-float": 2.0,
        "invalid-string": "2",
        "invalid-negative": -1,
        "invalid-int-subclass": IntSubclass(2),
    }.get(case, 2)
    results = []
    for _ in range(2 if case.endswith("-retry") else 1):
        try:
            results.append(
                {"return": owner.latch_kill_switch(expected_generation=expected)}
            )
        except BaseException as error:
            results.append({"error": graph(error)})
    final = state["decision"]
    assert depth == 0
    return {
        "events": events,
        "results": results,
        "writes": state["writes"],
        "record": final.to_dict()
        if isinstance(final, CodingWorkerOptInDecisionV1)
        else None,
    }


@pytest.mark.parametrize("platform", ["posix", "windows"])
@pytest.mark.parametrize("case", CASES)
def test_original_kill_switch(platform, case, monkeypatch):
    key = platform + ":" + case
    assert (
        observe(platform, case, monkeypatch)
        == json.loads(gzip.decompress(EXPECTED.read_bytes()))[key]
    )
