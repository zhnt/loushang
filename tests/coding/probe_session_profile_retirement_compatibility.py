"""Explicit fixed Session profile retirement over controlled effect owners."""

from __future__ import annotations

import asyncio
import gzip
import json
import types
from pathlib import Path

import pytest

from loushang.coding._base_plugin import CodingBasePluginAssembly
from loushang.coding._capability_plugin_composition import (
    CodingCapabilityPluginCompositionAssembly,
)
from loushang.coding.session.agent_session import AgentSession
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
    RegistrationDisposalResult,
)
from loushang.harness.session.agent_product import AgentProductSession
from loushang.harness.session.plugin_lifecycle._publication import _OwnerPublication

EXPECTED = Path(__file__).parent / "fixtures" / "session_profile_retirement_v1.json.gz"


class InputError(OSError):
    __module__ = "__a176_input__"


class InputBase(BaseException):
    __module__ = "__a176_input__"


def error_value(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "message": str(error),
        "notes": list(getattr(error, "__notes__", ())),
        "code": getattr(error, "code", None),
        "cause": error_value(error.__cause__, seen.copy()),
        "context": error_value(error.__context__, seen.copy()),
        "suppress": error.__suppress_context__,
    }


READS = (
    "_deferred_lsp_slot",
    "_deferred_lsp_management_cleanup",
    "_coding_worker_turn_tool_lease",
    "_coding_base_plugin_assembly",
    "_coding_base_owner_publication",
    "_coding_capability_plugin_assembly",
    "_coding_capability_owner_publication",
    "_capability_graph_runtime",
    "_capability_owner_generations",
    "_pending_capability_components",
    "_sandbox_runtime",
)
FAULTS = (
    "child.close",
    "management.cleanup",
    "worker.state",
    "worker.dispose",
    "parent.close",
    "base.management_lease",
    "basepub.receipts",
    "basepub.retired",
    "basepub.retire",
    "cap.close",
    "cap.runtime.close",
    "cap.state.cleanup",
    "cappub.retire",
    "cappub.prepared",
    "graph.closed",
    "graph.pending",
    "owners.bool",
    "components.bool",
    "cap.confirm",
    "cap.release",
    "cap.management.close",
    "cap.private",
    "cap.private.cleanup",
    "base.close",
    "base.runtime.close",
    "base.management.close",
    "base.state.cleanup",
    "sandbox.close",
)
CASES = {
    "success": {},
    "all-absent": {
        "child": False,
        "worker": False,
        "base": False,
        "cap": False,
        "sandbox": False,
    },
    "without-child": {"child": False},
    "without-worker": {"worker": False},
    "staged-worker": {"staged": True},
    "staged-rollback-fault": {"staged": True, "faults": ["worker.rollback"]},
    "worker-invalid": {"worker_result": "failed_retryable"},
    "worker-invalid-no-diagnostic": {
        "worker_result": "failed_terminal",
        "no_diagnostic": True,
    },
    "base-no-lease": {"base_lease": False},
    "base-no-publication": {"base_publication": False},
    "base-empty-receipts": {"base_empty": True},
    "base-already-retired": {"base_retired": True},
    "base-unprepared": {"base_prepared": False},
    "without-base": {"base": False},
    "without-cap": {"cap": False},
    "cap-no-publication": {"cap_publication": False},
    "cap-empty-receipts": {"cap_empty": True},
    "cap-unprepared": {"cap_prepared": False},
    "graph-not-closed": {"graph_closed": False},
    "graph-pending": {"graph_pending": True},
    "owners-remain": {"owners": True},
    "components-remain": {"components": True},
    "all-qualification-debts": {
        "graph_closed": False,
        "graph_pending": True,
        "owners": True,
        "components": True,
    },
    "late-parent-method": {"replace_parent_during_worker": True},
    "late-replacement": {"replace_after_parent": True},
    "late-qualification": {"change_after_publication": True},
    "parent-error-shortcircuit": {
        "faults": ["parent.close"],
        "forbidden": [
            "base.management_lease",
            "basepub.receipts",
            "basepub.retired",
            "cappub.prepared",
            "graph.closed",
            "owners.bool",
        ],
    },
    "no-lease-shortcircuit": {
        "base_lease": False,
        "forbidden": ["basepub.receipts", "basepub.retired"],
    },
    "empty-receipts-shortcircuit": {
        "base_empty": True,
        "forbidden": ["basepub.retired"],
    },
    "no-pub-shortcircuit": {"cap_publication": False, "forbidden": ["cappub.prepared"]},
    "worker-baseexception": {"faults": ["worker.dispose"], "error_type": "base"},
    "parent-baseexception": {"faults": ["parent.close"], "error_type": "base"},
    "tail-multiple-errors": {
        "faults": [
            "worker.dispose",
            "parent.close",
            "cap.close",
            "base.close",
            "sandbox.close",
        ]
    },
    "parent-tail-errors": {
        "faults": ["parent.close", "cap.close", "base.close", "sandbox.close"]
    },
    "cap-base-sandbox-errors": {"faults": ["cap.close", "base.close", "sandbox.close"]},
    "retire-base-sandbox-errors": {
        "faults": ["basepub.retire", "base.close", "sandbox.close"]
    },
    "management-baseexception": {
        "faults": ["management.cleanup"],
        "error_type": "base",
    },
}
for label in FAULTS:
    CASES["fault:" + label] = {"faults": [label]}
    CASES["retry:" + label] = {"faults": [label], "retry": True}
for name in READS:
    CASES["read-fault:" + name] = {"faults": ["read:" + name]}
for label in ("set:_lsp_access", "set:_coding_lsp_plugin_capture"):
    CASES["fault:" + label] = {"faults": [label]}
CASES["second-access-set-fault"] = {"faults": ["set:_lsp_access"], "fault_at": 2}
CASES["second-graph-read-fault"] = {
    "faults": ["read:_capability_graph_runtime"],
    "fault_at": 2,
}
CASES["second-sandbox-read-fault"] = {
    "faults": ["read:_sandbox_runtime"],
    "fault_at": 2,
}
for phase in ("child.close", "worker.dispose", "parent.close", "sandbox.close"):
    CASES["cancel:" + phase] = {"cancel_at": phase}
for phase in ("cap.close", "cap.confirm", "cap.release", "cap.private", "base.close"):
    CASES["self-cancel:" + phase] = {"self_cancel_at": phase}
CASES["retry-child-cancel"] = {"cancel_at": "child.close", "retry": True}
CASES["retry-worker-cancel"] = {"cancel_at": "worker.dispose", "retry": True}


async def observe(case, monkeypatch):
    config = CASES[case]
    trace, counts, errors = [], {}, {}
    flags = {
        "child_closed": False,
        "management_cleaned": False,
        "sandbox_closed": False,
        "parent_closed": False,
    }
    entered, release = asyncio.Event(), asyncio.Event()
    enabled = False
    attempt = 0
    created = {}
    scopes = {"base_closing": False}

    def mark(label, data=None):
        if not enabled:
            return
        count = counts[label] = counts.get(label, 0) + 1
        trace.append([label, count, data])
        if label in config.get("forbidden", ()):
            raise AssertionError("forbidden fact read: " + label)
        if label == config.get("self_cancel_at") and count == 1:
            assert asyncio.current_task().cancel("self:" + label)
            trace.append(["cancel-request", label])
        if label in config.get("faults", ()) and count == config.get("fault_at", 1):
            cls = InputBase if config.get("error_type") == "base" else InputError
            error = cls("injected:" + label)
            errors[label] = error
            raise error

    async def phase(label):
        mark(label)
        if label == config.get("cancel_at") and counts[label] == 1:
            entered.set()
            await release.wait()
        await asyncio.sleep(0)

    class Session(AgentSession):
        def __getattribute__(self, name):
            if name in READS:
                mark("read:" + name)
            return super().__getattribute__(name)

        def __setattr__(self, name, value):
            if name in ("_coding_lsp_plugin_capture", "_lsp_access"):
                mark("set:" + name, "none" if value is None else "sentinel")
            super().__setattr__(name, value)

    session = object.__new__(Session)

    class Closeable:
        def __init__(self, label):
            self.label = label

        def close(self):
            mark(self.label)

    class Child:
        async def close(self):
            await phase("child.close")
            flags["child_closed"] = True

    class Sandbox:
        async def close(self):
            await phase("sandbox.close")
            flags["sandbox_closed"] = True

    class Worker:
        @property
        def state(self):
            mark("worker.state")
            return "staged" if config.get("staged") else "active"

        def result(self):
            state = (
                config.get("worker_result", "removed") if attempt == 0 else "removed"
            )
            if config.get("no_diagnostic") and state != "removed":
                return types.SimpleNamespace(state=state, diagnostic_code=None)
            return RegistrationDisposalResult(
                state=state,
                diagnostic_code=None if state == "removed" else "input_worker_failure",
            )

        def rollback_registration(self):
            mark("worker.rollback")
            return self.result()

        async def dispose(self):
            await phase("worker.dispose")
            if config.get("replace_parent_during_worker"):

                async def replacement_parent(owner):
                    assert owner is session
                    await phase("replacement-parent.close")
                    flags["parent_closed"] = True

                monkeypatch.setattr(
                    AgentProductSession,
                    "_dispose_session_runtime_profile",
                    replacement_parent,
                )
            return self.result()

    class BoolFacts:
        def __init__(self, label, value):
            self.label, self.value = label, value

        def __bool__(self):
            mark(self.label)
            return self.value

    class Graph:
        @property
        def is_closed(self):
            mark("graph.closed")
            return config.get("graph_closed", True)

        @property
        def has_pending_retirements(self):
            mark("graph.pending")
            return config.get("graph_pending", False)

    class Base(CodingBasePluginAssembly):
        def __getattribute__(self, name):
            if name == "management_lease":
                mark(
                    "base.close.management_lease"
                    if scopes["base_closing"]
                    else "base.management_lease"
                )
            return super().__getattribute__(name)

    class Cap(CodingCapabilityPluginCompositionAssembly):
        pass

    base_original = CodingBasePluginAssembly.close
    cap_methods = {
        name: getattr(CodingCapabilityPluginCompositionAssembly, name)
        for name in (
            "close",
            "confirm_runtime_retirement",
            "release_management",
            "cleanup_private_state",
        )
    }

    def base_close(obj):
        mark(obj._probe_label + ".close")
        previous = scopes["base_closing"]
        scopes["base_closing"] = True
        try:
            return base_original(obj)
        finally:
            scopes["base_closing"] = previous

    monkeypatch.setattr(Base, "close", base_close)
    for method, label in [
        ("close", "close"),
        ("confirm_runtime_retirement", "confirm"),
        ("release_management", "release"),
        ("cleanup_private_state", "private"),
    ]:

        def wrapper(obj, _method=method, _label=label, **kwargs):
            mark(obj._probe_label + "." + _label, kwargs or None)
            return cap_methods[_method](obj, **kwargs)

        monkeypatch.setattr(Cap, method, wrapper)

    def make_base(label="base"):
        obj = object.__new__(Base)
        obj._probe_label = label
        obj.runtime = Closeable(label + ".runtime.close")
        obj.management_lease = (
            Closeable(label + ".management.close")
            if config.get("base_lease", True)
            else None
        )
        obj.state_cleanup = lambda: mark(label + ".state.cleanup")
        for attr in (
            "_runtime_closed",
            "_management_released",
            "_state_cleaned",
            "_closed",
        ):
            setattr(obj, attr, False)
        return obj

    def make_cap(label="cap"):
        obj = object.__new__(Cap)
        obj._probe_label = label
        obj.runtime = Closeable(label + ".runtime.close")
        obj.management_leases = {"one": Closeable(label + ".management.close")}
        obj.management_state_cleanup = lambda: mark(label + ".management.cleanup")
        obj.state_cleanup = lambda: mark(label + ".state.cleanup")
        obj.private_state_cleanup = lambda: mark(label + ".private.cleanup")
        for attr in (
            "_runtime_closed",
            "_management_released",
            "_state_cleaned",
            "_private_state_cleaned",
            "_runtime_retired",
            "_closed",
        ):
            setattr(obj, attr, False)
        return obj

    class Target:
        def __init__(self, label):
            self.label = label

        def prepare_owner_generations(self, receipts):
            mark(self.label + ".prepare-target", [r.to_dict() for r in receipts])

        def retire_owner_generations(self, receipts):
            mark(self.label + ".retire-target", [r.to_dict() for r in receipts])

    class Publication(_OwnerPublication):
        @property
        def receipts(self):
            mark(self.label + ".receipts")
            return super().receipts

        @property
        def retired(self):
            mark(self.label + ".retired")
            return super().retired

        @property
        def prepared(self):
            mark(self.label + ".prepared")
            return super().prepared

        def retire_after_graph(self):
            mark(self.label + ".retire")
            if config.get("change_after_publication") and self.label == "basepub":
                session._capability_owner_generations = BoolFacts("owners.bool", True)
            return super().retire_after_graph()

    def pub(label):
        receipt = OwnerGenerationRetirementReceipt(
            label + ".owner", label + ".generation", label + ".handle", ("a", "b")
        )
        empty = config.get("base_empty" if label == "basepub" else "cap_empty", False)
        obj = Publication(Target(label), lambda *args: (), ())
        obj.label = label
        obj._receipts = () if empty else (receipt,)
        obj._prepared = config.get(
            "base_prepared" if label == "basepub" else "cap_prepared", True
        )
        obj._retired = (
            config.get("base_retired", False) if label == "basepub" else False
        )
        return obj

    base, cap = make_base(), make_cap()
    basepub, cappub = pub("basepub"), pub("cappub")
    session._deferred_lsp_slot = Child() if config.get("child", True) else None

    def management():
        mark("management.cleanup")
        flags["management_cleaned"] = True

    session._deferred_lsp_management_cleanup = management
    session._coding_worker_turn_tool_lease = (
        Worker() if config.get("worker", True) else None
    )
    session._coding_base_plugin_assembly = base if config.get("base", True) else None
    session._coding_base_owner_publication = (
        basepub if config.get("base_publication", True) else None
    )
    session._coding_capability_plugin_assembly = (
        cap if config.get("cap", True) else None
    )
    session._coding_capability_owner_publication = (
        cappub if config.get("cap_publication", True) else None
    )
    session._capability_graph_runtime = Graph()
    session._capability_owner_generations = BoolFacts(
        "owners.bool", config.get("owners", False)
    )
    session._pending_capability_components = BoolFacts(
        "components.bool", config.get("components", False)
    )
    session._sandbox_runtime = Sandbox() if config.get("sandbox", True) else None
    access, capture = object(), object()
    session._lsp_access, session._coding_lsp_plugin_capture = access, capture
    original_refs = {name: object.__getattribute__(session, name) for name in READS}

    async def parent(owner):
        assert owner is session
        await phase("parent.close")
        flags["parent_closed"] = True
        if config.get("replace_after_parent"):
            replacement = make_base("replacement-base")
            session._coding_base_plugin_assembly = replacement
            session._coding_capability_plugin_assembly = make_cap("replacement-cap")
            created["base"] = replacement

    monkeypatch.setattr(AgentProductSession, "_dispose_session_runtime_profile", parent)
    enabled = True

    def retained():
        return {
            "access": object.__getattribute__(session, "_lsp_access") is access,
            "capture": object.__getattribute__(session, "_coding_lsp_plugin_capture")
            is capture,
            "refs": {
                name: object.__getattribute__(session, name) is value
                for name, value in original_refs.items()
            },
            "base_flags": {
                name: getattr(base, name)
                for name in (
                    "_runtime_closed",
                    "_management_released",
                    "_state_cleaned",
                    "_closed",
                )
            },
            "cap_flags": {
                name: getattr(cap, name)
                for name in (
                    "_runtime_closed",
                    "_management_released",
                    "_state_cleaned",
                    "_private_state_cleaned",
                    "_runtime_retired",
                    "_closed",
                )
            },
            "publication": {
                "base": [basepub._prepared, basepub._retired],
                "cap": [cappub._prepared, cappub._retired],
            },
            "effects": dict(flags),
        }

    snapshots, outputs = [], []
    for attempt in range(2 if config.get("retry") else 1):
        caught = None
        try:
            if config.get("cancel_at") and attempt == 0:
                task = asyncio.create_task(session._dispose_session_runtime_profile())
                assert await asyncio.wait_for(entered.wait(), 3) is True
                assert task.cancel("caller:" + config["cancel_at"])
                release.set()
                try:
                    await task
                except BaseException as exc:
                    caught = exc
            elif config.get("self_cancel_at"):
                task = asyncio.create_task(session._dispose_session_runtime_profile())
                try:
                    await task
                except BaseException as exc:
                    caught = exc
            else:
                await session._dispose_session_runtime_profile()
        except BaseException as exc:
            caught = exc
        outputs.append(
            {
                "error": error_value(caught),
                "same_injected": next(
                    (label for label, value in errors.items() if caught is value), None
                ),
            }
        )
        snapshots.append(retained())
    # Reachability/type assertions are part of the original freeze, not inferred from a green capture.
    for label in config.get("faults", ()):
        assert label in errors, ("fault not reached", label, trace)
    for label in config.get("forbidden", ()):
        assert counts.get(label, 0) == 0
    if config.get("cancel_at") or config.get("self_cancel_at"):
        assert outputs[0]["error"]["type"] == "asyncio.exceptions.CancelledError", (
            outputs
        )
    if case == "late-parent-method":
        assert counts.get("parent.close", 0) == 0
        assert counts.get("replacement-parent.close", 0) == 1
    if case == "parent-error-shortcircuit":
        assert counts.get("base.close.management_lease", 0) == 2
    if case == "success":
        assert outputs[0]["error"] is None
        assert not snapshots[0]["access"] and not snapshots[0]["capture"]
    if case == "fault:child.close" or case == "cancel:child.close":
        assert (
            counts.get("parent.close", 0) == 0
            and snapshots[0]["access"]
            and snapshots[0]["capture"]
        )
    if case in ("fault:management.cleanup", "management-baseexception"):
        assert (
            counts.get("parent.close", 0) == 0
            and not snapshots[0]["access"]
            and snapshots[0]["capture"]
        )
    if config.get("retry"):
        assert outputs[1]["error"] is None, outputs
    return {
        "outputs": outputs,
        "snapshots": snapshots,
        "trace": trace,
        "counts": counts,
        "actual_classes": [
            type(base).__mro__[1].__module__ + "." + type(base).__mro__[1].__qualname__,
            type(cap).__mro__[1].__module__ + "." + type(cap).__mro__[1].__qualname__,
        ],
        "receipt": basepub._receipts[0].to_dict() if basepub._receipts else None,
    }


@pytest.mark.parametrize("case", CASES)
def test_profile_retirement(case, monkeypatch):
    observed = json.loads(json.dumps(asyncio.run(observe(case, monkeypatch))))
    assert observed == json.loads(gzip.decompress(EXPECTED.read_bytes()))[case]
