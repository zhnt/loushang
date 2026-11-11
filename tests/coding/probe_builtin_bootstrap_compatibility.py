"""Fixed original observations; explicit local execution, no CI route."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

import loushang.coding.package_product_runtime as module
from loushang.harness.plugin_management.records import (
    PluginDesiredSelectionV1,
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

FIXTURE = Path(__file__).parent / "fixtures" / "builtin_bootstrap_v1.json"
BASES = (
    "absent",
    "enabled",
    "disabled",
    "operator-disabled",
    "removed",
    "install-refused",
    "missing-handoff",
    "enable-refused",
    "selection-changed",
    "wrong-actor",
    "wrong-command",
    "no-enable",
    "disabled-no-enable",
    "factory-error",
    "create-error",
    "activate-error",
    "route-error",
    "lookup-error",
    "dispose-error",
    "create-error+unbound-error",
    "route-error+dispose-error",
    "snapshot-error",
    "transitions-error",
    "submit-error",
)
COMPLETE = (
    "completed",
    "operator-disabled",
    "incomplete",
    "wrong-actor",
    "wrong-command",
    "lookup-error",
    "transitions-error",
)


def error_graph(exc, seen=None):
    if exc is None:
        return None
    seen = {} if seen is None else seen
    if id(exc) in seen:
        return {"ref": seen[id(exc)]}
    seen[id(exc)] = len(seen)
    return {
        "id": seen[id(exc)],
        "type": type(exc).__name__,
        "message": str(exc),
        "notes": getattr(exc, "__notes__", []),
        "suppress": exc.__suppress_context__,
        "cause": error_graph(exc.__cause__, seen),
        "context": error_graph(exc.__context__, seen),
    }


def observe(case, completed, monkeypatch):
    trace = []
    records = []
    current = {}
    snapshots = 0
    plugin_ids = ("coding.base", "coding.lsp.default", "coding.arch.default")

    def step(name, *values):
        trace.append([name, *values])
        if name + "-error" in case:
            raise RuntimeError("injected-" + name)

    def key(plugin):
        return PluginInstallationKeyV1("coding", "workspace", "scope", plugin)

    def state(plugin, status):
        ref = PluginPackageRevisionRefV1(plugin, "1.0", "a" * 64, "b" * 64, "source")
        instance = PluginInstanceRevisionRef("instance:" + plugin, plugin, 1)
        if status == "absent":
            return PluginInstallationStateV1.initial(key(plugin))
        enabled = status == "installed_enabled"
        return PluginInstallationStateV1(
            key(plugin),
            PluginDesiredSelectionV1(status, ref, instance if enabled else None),
            instance if enabled else None,
        )

    def add_install(plugin):
        before = state(plugin, "absent")
        after = state(plugin, "installed_disabled")
        mutation = PluginDesiredStateMutationV1(
            "command:" + plugin,
            "install:" + plugin,
            len(records),
            key(plugin),
            "installed_disabled",
            after.selection.package_revision,
            "actor" if case != "wrong-actor" else "operator",
            "policy",
        )
        records.append(
            PluginDesiredStateTransitionV1(
                len(records) + 1, "install", mutation, before, after
            )
        )
        current[plugin] = after

    def add_enable(plugin):
        before = current[plugin]
        after = state(plugin, "installed_enabled")
        mutation = PluginDesiredStateMutationV1(
            "coding-builtin-bootstrap-enable:old",
            "enable:" + plugin,
            len(records),
            key(plugin),
            "installed_enabled",
            None,
            "actor" if case != "wrong-actor" else "operator",
            "policy",
        )
        records.append(
            PluginDesiredStateTransitionV1(
                len(records) + 1, "enable", mutation, before, after
            )
        )
        current[plugin] = after

    if completed:
        for plugin in plugin_ids:
            add_install(plugin)
            if case != "incomplete":
                add_enable(plugin)
            if case == "operator-disabled":
                current[plugin] = state(plugin, "installed_disabled")
    elif case in (
        "disabled",
        "operator-disabled",
        "disabled-no-enable",
        "wrong-actor",
        "wrong-command",
    ):
        add_install(plugin_ids[0])
        if case == "operator-disabled":
            add_enable(plugin_ids[0])
            current[plugin_ids[0]] = state(plugin_ids[0], "installed_disabled")
    elif case == "enabled":
        current[plugin_ids[0]] = state(plugin_ids[0], "installed_enabled")
    elif case == "removed":
        current[plugin_ids[0]] = state(plugin_ids[0], "absent")

    def installation(k):
        step("installation", k.to_dict())
        return current.get(k.plugin_id, state(k.plugin_id, "absent"))

    def snapshot():
        nonlocal snapshots
        snapshots += 1
        step("snapshot", snapshots)
        if case == "selection-changed" and snapshots == 2:
            current[plugin_ids[0]] = state(plugin_ids[0], "absent")
        return NS(
            installation=installation,
            installations=tuple(current.values()),
            inventory_revision=len(records),
        )

    def transitions():
        step("transitions")
        return tuple(records)

    def lookup(**kwargs):
        step("lookup", kwargs)
        if case == "missing-handoff":
            return None
        return ("wrong:" if case == "wrong-command" else "command:") + kwargs[
            "plugin_id"
        ]

    def route(intent, **kwargs):
        step("route", intent.operation_id, intent.action, intent.source, kwargs)
        if case == "install-refused":
            return NS(
                handled=False, record=NS(lifecycle="failed", failure_code="refused")
            )
        add_install(plugin_ids[0])
        return NS(
            handled=True,
            record=NS(lifecycle="installed"),
            evidence=NS(operation_id=intent.operation_id),
        )

    def submit(command):
        step("submit", command.action, command.mutation.to_dict())
        if case == "enable-refused":
            return NS(result=NS(disposition="failed"))
        add_enable(plugin_ids[0])
        return NS(result=NS(disposition="succeeded"))

    binding = NS(
        activate=lambda: step("activate"),
        lifecycle=NS(route=route),
        dispose_runtime=lambda: step("dispose"),
    )

    def create(request):
        step("create", request.product_id, request.session_id, request.cwd)
        return binding

    def factory(**kwargs):
        step("factory", {k: str(v) for k, v in kwargs.items()})
        return NS(create=create, dispose_unbound_runtime=lambda: step("unbound"))

    product = NS(
        desired_state=NS(snapshot=snapshot, transitions=transitions),
        policy=NS(
            project_scope_id="scope",
            bindings=(NS(plugin_id=plugin_ids[0], source_identity="source"),),
        ),
        settled_install_command_id=lookup,
        factory_for_session=factory,
        workspace=Path("/workspace"),
        actor_id="actor",
        desired_policy_revision="policy",
        management=NS(submit=submit),
    )
    owner = NS(
        runtime_owner=NS(product_owner=product),
        epoch_runtime=NS(registry=NS(store_id="store")),
    )
    monkeypatch.setattr(secrets, "token_hex", lambda count: "f" * (count * 2))
    functions = vars(module)
    try:
        if completed:
            result = functions["_fresh_coding_builtin_bootstrap_completed"](owner)
        else:
            result = functions["_bootstrap_coding_builtin_plugin"](
                owner, plugin_ids[0], enable="no-enable" not in case
            )
    except BaseException as exc:
        result = error_graph(exc)
    return {
        "trace": trace,
        "result": result,
        "records": [item.to_dict() for item in records],
    }


@pytest.mark.parametrize(
    "completed,case", [(False, c) for c in BASES] + [(True, c) for c in COMPLETE]
)
def test_fixed_original(completed, case, monkeypatch):
    actual = observe(case, completed, monkeypatch)
    expected = json.loads(FIXTURE.read_text())[f"{completed}-{case}"]
    assert actual == expected
