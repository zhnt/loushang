"""Explicit original A81 values/API/wire observations; no capture mode."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import enum
import hashlib
import importlib
import inspect
import json
import pickle
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.types import UserMessage
from loushang.coding.adapters import _goal_delegation as delegation
from loushang.coding.adapters import _goal_execution_context as choices
from loushang.coding.adapters import _goal_planning_work as planning
from loushang.coding.adapters import _goal_repository as repository
from loushang.coding.adapters import goal
from loushang.harness.artifacts.references import SessionBlobRef
from loushang.harness.multiagent import AgentPath, AgentRef, ForkTier
from loushang.harness.transcript import AGENT_MESSAGE_KIND, AgentTranscriptRecord
from loushang.harnesswork.goal.records import canonical, plain
from loushang.harnesswork.types import WorkOperation

CASES = (
    "api",
    "choice-fresh",
    "choice-reuse",
    "choice-inherit",
    "policy-default",
    "view-permissive",
    "choice-reuse-missing",
    "choice-fresh-target",
    "choice-inherit-empty-tier",
    "choice-allow-empty-int",
    "choice-reason-control",
    "policy-invalid-limits",
    "prepare-fresh",
    "prepare-inherit",
    "prepare-default",
    "prepare-reuse",
    "prepare-independent",
    "confirm-revision-changed",
    "confirm-bool-revision",
    "confirm-float-revision",
    "confirm-unknown-mode",
    "confirm-missing-field",
    "report-valid",
    "report-wrong-authority",
    "report-invalid-role",
    "report-put-failure",
    "report-read-failure",
    "report-publish-failure",
)
REJECTED = {
    **{
        name: ("loushang.harnesswork.goal.records.GoalError",)
        for name in (
            "choice-reuse-missing",
            "choice-fresh-target",
            "choice-inherit-empty-tier",
            "choice-allow-empty-int",
            "policy-invalid-limits",
        )
    },
    "report-wrong-authority": (
        "loushang.coding.adapters._work_evidence.EvidenceReplayError",
    ),
    "report-invalid-role": (
        "loushang.coding.adapters._work_evidence.EvidenceReplayError",
    ),
    "report-put-failure": ("builtins.OSError",),
    "report-read-failure": ("builtins.OSError",),
    "report-publish-failure": ("builtins.RuntimeError",),
}
MODULES = (delegation, choices, planning, repository, goal)


def fq(value):
    return f"{value.__module__}.{value.__qualname__}"


def freeze(value):
    if isinstance(value, enum.Enum):
        return {"enum": fq(type(value)), "value": value.value}
    if isinstance(value, bytes):
        return {
            "base64": base64.b64encode(value).decode(),
            "sha256": hashlib.sha256(value).hexdigest(),
            "length": len(value),
        }
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "class": fq(type(value)),
            "fields": {
                f.name: freeze(getattr(value, f.name))
                for f in dataclasses.fields(value)
            },
        }
    if isinstance(value, Mapping):
        return {str(k): freeze(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [freeze(v) for v in value]
    if isinstance(value, (str, int, bool, float)) or value is None:
        return value
    return {"type": fq(type(value))}


def exception(error, seen=None):
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": fq(type(error))}
    seen.add(id(error))
    return {
        "type": fq(type(error)),
        "args": freeze(error.args),
        "notes": list(getattr(error, "__notes__", ())),
        "suppress": error.__suppress_context__,
        "cause": exception(error.__cause__, seen) if error.__cause__ else None,
        "context": exception(error.__context__, seen) if error.__context__ else None,
    }


def dtype(value):
    cls = type(value)
    fields = []
    for f in dataclasses.fields(value):
        fields.append(
            {
                "name": f.name,
                "annotation": str(f.type),
                "init": f.init,
                "repr": f.repr,
                "compare": f.compare,
                "default": "<MISSING>"
                if f.default is dataclasses.MISSING
                else freeze(f.default),
                "factory": "<MISSING>"
                if f.default_factory is dataclasses.MISSING
                else fq(f.default_factory),
            }
        )
    restored = pickle.loads(pickle.dumps(value))
    return {
        "class": fq(cls),
        "constructor": str(inspect.signature(cls)),
        "own_annotations": {
            k: str(v) for k, v in cls.__dict__.get("__annotations__", {}).items()
        },
        "fields": fields,
        "frozen": cls.__dataclass_params__.frozen,
        "slots": list(cls.__dict__.get("__slots__", ())),
        "has_dict": hasattr(value, "__dict__"),
        "values": freeze(value),
        "pickle_class": fq(type(restored)),
        "pickle_equal": restored == value,
    }


def api():
    rows = {}
    for cls in (
        choices.SessionChoice,
        choices.SessionExecutionPolicy,
        delegation.ExecutionContextView,
        delegation.DelegatedSessions,
        delegation.DelegatedWork,
        goal.CodingGoal,
        repository._RepositoryGoal,
    ):
        row = {
            "class": fq(cls),
            "constructor": str(inspect.signature(cls)),
            "own_annotations": {
                k: str(v) for k, v in cls.__dict__.get("__annotations__", {}).items()
            },
            "methods": {},
        }
        for name in dir(cls):
            if name.startswith("_"):
                continue
            value = inspect.getattr_static(cls, name)
            fn = value.fget if isinstance(value, property) else getattr(cls, name)
            if inspect.isfunction(fn) or inspect.ismethod(fn):
                row["methods"][name] = {
                    "signature": str(inspect.signature(fn)),
                    "annotations": {
                        k: str(v) for k, v in getattr(fn, "__annotations__", {}).items()
                    },
                }
        rows[fq(cls)] = row
    for name in ("open_repository_goal",):
        fn = getattr(repository, name)
        rows[name] = {
            "function": fq(fn),
            "signature": str(inspect.signature(fn)),
            "annotations": {k: str(v) for k, v in fn.__annotations__.items()},
        }
    return {
        "api": rows,
        "wire": {
            "KEY": delegation.KEY,
            "WORKER": delegation.WORKER,
            "MAPPER": choices.MAPPER,
            "OPERATION_KIND": choices.OPERATION_KIND,
            "ROLE": choices.ROLE,
            "TOOLS": list(choices.TOOLS),
        },
    }


def child_ref():
    return AgentRef(AgentPath.parse("/root/child-fixed"), 3)


class RecordedBlobs:
    def __init__(self, session_id="parent-fixed", failure=None):
        self.session_id, self.failure = session_id, failure
        self.trace = []
        self.content = {}

    def put_bytes(self, body, **metadata):
        self.trace.append({"put": {"bytes": freeze(body), "metadata": metadata}})
        if self.failure == "put":
            raise OSError("controlled report put failure")
        sha = hashlib.sha256(body).hexdigest()
        ref = SessionBlobRef(
            self.session_id,
            sha,
            metadata["logical_name"],
            metadata["kind"],
            metadata["media_type"],
            "private",
            len(body),
            sha,
            1.0,
            metadata["source"],
        )
        self.content[sha] = body
        return ref

    def read_bytes(self, ref):
        self.trace.append({"read": ref.manifest_entry()})
        if self.failure == "read":
            raise OSError("controlled report read failure")
        return self.content[ref.sha256]


async def prepared(case, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    model = Model(
        id="fixed-model",
        provider="offline",
        api="offline-values",
        endpoint="offline",
        base_url="https://unused.invalid",
        auth=Auth(kind="none"),
        capabilities=Capabilities(
            input=("text",),
            output=("text",),
            context_window=128000,
            max_tokens=4096,
            stream=True,
            tool_use=True,
        ),
    )
    message = AgentTranscriptRecord(
        record_id="message-1",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-11-10T00:00:00Z",
        payload=UserMessage(
            role="user", content="fixed inherited input", timestamp=1.0
        ),
    )
    manager = SimpleNamespace(
        header=SimpleNamespace(conversation_id="parent-fixed"),
        get_leaf_id=lambda: "message-1",
        get_branch=lambda mark: [message],
    )
    parent = SimpleNamespace(
        agent=SimpleNamespace(model=model),
        session_id="parent-fixed",
        session_manager=manager,
    )
    owner = SimpleNamespace(
        workspace=workspace,
        data_root=tmp_path / "data",
        _session=parent,
        _allowance=SimpleNamespace(fenced=False),
        _work=SimpleNamespace(
            get_run_for_operation=lambda operation: SimpleNamespace(status="completed")
        ),
    )
    choice = (
        choices.SessionChoice("inherit", tier=ForkTier.last(1))
        if case == "prepare-inherit"
        else choices.SessionChoice("reuse", target=child_ref())
        if case == "prepare-reuse"
        else None
        if case == "prepare-default"
        else choices.SessionChoice("fresh")
    )
    profile = SimpleNamespace(
        execution_policy=choices.SessionExecutionPolicy(choice),
        system_prompt="fixed-system",
    )
    family = delegation.DelegatedSessions(
        owner, profile, RecordedBlobs(), None, "store-fixed", None
    )
    child = delegation._ChildRuntime(
        None, SimpleNamespace(step=None), family, child_ref()
    )
    child.session = SimpleNamespace(
        agent=SimpleNamespace(model=model),
        session_id="child-fixed",
        pending_message_count=0,
        is_streaming=False,
    )
    child.origin = "origin-fixed"
    child.last_operation = "prior-fixed"
    child.last_round = 2
    family.children[child.ref] = child
    record = SimpleNamespace(status="completed", round_id=2)
    get = family.control.registry.get
    operation = WorkOperation(
        "operation-fixed",
        "original-kind",
        "parent-fixed",
        "coding",
        {"keep": {"nested": [1, 2]}},
    )
    basis = SimpleNamespace(
        identity={
            "goal_id": "goal-fixed",
            "revision": 2,
            "epoch": 3,
            "fingerprint": "a" * 64,
        }
    )
    spec = SimpleNamespace(method_id="method-fixed", plan_id="plan-fixed")
    turn = SimpleNamespace(step_id="repair", text="fixed repair instruction")
    try:
        with patch.object(
            family.control.registry,
            "get",
            lambda ref: record if ref == child.ref else get(ref),
        ):
            selected, work, frozen = family.prepare(basis, operation, spec, turn)
            before = freeze(frozen)
            if case == "prepare-independent":
                selected.payload[delegation.KEY]["history"]["diagnostics"].append(
                    "operation-only"
                )
                work.frozen["history"]["diagnostics"].append("work-only")
                return {
                    "operation": freeze(selected),
                    "work": freeze(work.frozen),
                    "returned": freeze(frozen),
                    "original_operation": freeze(operation),
                    "before": before,
                    "distinct": selected.payload[delegation.KEY] is not work.frozen
                    and work.frozen is not frozen,
                }
            if case.startswith("confirm-"):
                altered = plain(frozen)
                if case == "confirm-revision-changed":
                    altered["selection_revision"] = family.revision + 1
                elif case == "confirm-bool-revision":
                    altered["selection_revision"] = False
                elif case == "confirm-float-revision":
                    altered["selection_revision"] = 0.0
                elif case == "confirm-unknown-mode":
                    altered["mode"] = "unknown-original-mode"
                elif case == "confirm-missing-field":
                    del altered["mode"]
                return {
                    "confirm": family.confirm(altered),
                    "frozen": before,
                    "altered": freeze(altered),
                    "selection_revision": family.revision,
                }
            return {
                "operation": freeze(selected),
                "frozen": before,
                "work_class": fq(type(work)),
                "choice": freeze(work.choice),
                "work_frozen": freeze(work.frozen),
                "canonical_wire": freeze(plain(frozen) and canonical(frozen).encode()),
                "view": freeze(family.views()),
                "confirm": family.confirm(frozen),
            }
    finally:
        await family.close()


def report(case):
    blobs = RecordedBlobs(
        session_id="other-fixed"
        if case == "report-wrong-authority"
        else "parent-fixed",
        failure="put"
        if case == "report-put-failure"
        else "read"
        if case == "report-read-failure"
        else None,
    )
    published = []

    def publish(fact):
        blobs.trace.append({"publish": freeze(fact)})
        if case == "report-publish-failure":
            raise RuntimeError("controlled report publish failure")
        published.append(fact)

    context = SimpleNamespace(run_id="run-fixed", step_id="repair", publish=publish)
    value = {
        "version": 1,
        "operation_id": "operation-fixed",
        "run_id": "run-fixed",
        "session_id": "parent-fixed",
        "context": {"mode": "fresh", "selection_revision": 0},
        "child_ref": choices.ref_data(child_ref()),
        "child_session_id": "child-fixed",
        "origin_operation_id": "origin-fixed",
        "round_id": 2,
        "terminal": "completed",
    }
    try:
        _publish_actual_core_report(
            blobs,
            context,
            value,
            role="" if case == "report-invalid-role" else choices.ROLE,
            session_id="parent-fixed",
        )
        return {"report": value, "trace": blobs.trace, "facts": freeze(published)}
    except BaseException as error:
        return {
            "error": exception(error),
            "report": value,
            "trace": blobs.trace,
            "facts": freeze(published),
        }


def observe(case, tmp_path):
    try:
        if case == "api":
            result = api()
        elif case == "choice-fresh":
            result = dtype(choices.SessionChoice("fresh"))
        elif case == "choice-reuse":
            result = dtype(choices.SessionChoice("reuse", target=child_ref()))
        elif case == "choice-inherit":
            result = dtype(
                choices.SessionChoice(
                    "inherit", tier=ForkTier.last(2), reason="bounded reuse"
                )
            )
        elif case == "policy-default":
            result = dtype(choices.SessionExecutionPolicy())
        elif case == "view-permissive":
            result = dtype(
                delegation.ExecutionContextView(
                    child_ref(), "", "unknown-status", True, None
                )
            )
        elif case == "choice-reuse-missing":
            result = choices.SessionChoice("reuse")
        elif case == "choice-fresh-target":
            result = choices.SessionChoice("fresh", target=child_ref())
        elif case == "choice-inherit-empty-tier":
            result = choices.SessionChoice("inherit")
        elif case == "choice-allow-empty-int":
            result = choices.SessionChoice("fresh", allow_empty=1)
        elif case == "choice-reason-control":
            result = choices.SessionChoice("fresh", reason="invalid\nreason")
        elif case == "policy-invalid-limits":
            result = choices.SessionExecutionPolicy(limits=None)
        elif case.startswith(("prepare-", "confirm-")):
            result = asyncio.run(prepared(case, tmp_path))
        else:
            result = report(case)
        observed = {"result": freeze(result)}
    except BaseException as error:
        observed = {"error": exception(error)}
    error = observed.get("error") or observed.get("result", {}).get("error")
    accepted = REJECTED.get(case)
    assert bool(error) == bool(accepted), (case, observed)
    if accepted:
        assert error["type"] in accepted, (case, observed)
    return observed


@pytest.mark.parametrize("case", CASES)
def test_original_goal_delegation_values(case, tmp_path):
    expected = _fixed_values()
    assert observe(case, tmp_path) == expected["observations"][case]


_FIXED_VALUES_SHA256 = (
    "25c66871f162a94a72f16f8805fe6f6c9c437ab4030f1b8beb208a9510e64c1a"
)


def _fixed_values():
    raw = (
        Path(__file__).parent / "fixtures/goal_delegation_values_v1.json"
    ).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _FIXED_VALUES_SHA256
    return json.loads(raw)


def _publish_actual_core_report(blobs, context, value, *, role, session_id):
    family = delegation.DelegatedSessions.__new__(delegation.DelegatedSessions)
    family.blobs = blobs
    assert (
        family._publish_report.__func__.__module__
        == "loushang.harnesswork.integrations.delegation"
    )
    # Bind the old one-role argument to both declared Product value seams.
    with (
        patch.object(delegation, "ROLE", role),
        patch.object(family, "_report_role", role),
    ):
        with patch.object(
            planning,
            "publish_report",
            side_effect=AssertionError("legacy publisher must not execute"),
        ):
            family._publish_report(context, value, session_id)


def test_portable_fixture_and_actual_module_origins():
    assert len(_fixed_values()["observations"]) == len(CASES) == 28
    package = importlib.import_module("loushang")
    root = Path(package.__file__).resolve().parent
    names = [module.__name__ for module in MODULES]
    names += [
        "loushang.harnesswork.integrations.delegation",
        "loushang.harness.session.multiagent",
    ]
    for name in names:
        module = importlib.import_module(name)
        expected = root / Path(*name.split(".")[1:]).with_suffix(".py")
        assert Path(module.__file__).resolve() == expected.resolve(), name
