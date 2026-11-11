"""Original full CLI programs over real Desired/Management journals."""

from __future__ import annotations

import hashlib
import json
import secrets
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding.cli import package_worker_native as linux
from loushang.coding.cli import package_worker_windows_candidate as windows
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateLedger,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.plugin_management.updates import (
    PluginManagementUpdateCommandV2,
    PluginUpdateOperationEventV2,
    PluginUpdateOperationResultV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleRequestV2,
)
from loushang.harness.resources.packages.product_handoff import (
    package_product_command_identity,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWorkerAdmissionV1,
)

OBSERVATIONS = json.loads(
    (Path(__file__).parent / "fixtures" / "worker_candidate_update_v1.json").read_text()
)["observations"]
CASES = (
    "fresh",
    "fresh-enabled",
    "retry",
    "retry-enabled",
    "retry-allow",
    "retry-request-absent",
    "retry-request-v1",
    "retry-request-action",
    "retry-request-plugin",
    "retry-request-source",
    "retry-accepted",
    "retry-running",
    "retry-failed",
    "retry-key",
    "retry-expect",
    "retry-from",
    "retry-target",
    "retry-source",
    "retry-state",
    "retry-inventory",
    "missing-selection",
    "multiple-selection",
    "removed",
    "ambiguous-binding",
    "stale",
    "stale-allow",
    "from-mismatch",
    "same-artifact",
    "allow",
    "owner-error",
    "current-error",
    "request-error",
    "operation-error",
    "token-error",
    "factory-error",
    "create-error",
    "activate-error",
    "route-error",
    "route-refused",
    "selection-changed",
    "post-snapshot-error",
    "dispose-error",
    "create-error+unbound-error",
    "route-error+dispose-error",
    "install-existing",
    "enable-existing",
    "disable-existing",
    "remove-existing",
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
        "code": getattr(exc, "code", None),
        "message": str(exc),
        "notes": getattr(exc, "__notes__", []),
        "suppress": exc.__suppress_context__,
        "cause": error_graph(exc.__cause__, seen),
        "context": error_graph(exc.__context__, seen),
    }


def observe(platform, case, root, monkeypatch):
    root.mkdir()
    trace = []
    key = PluginInstallationKeyV1("coding", "workspace", "scope", "workerprobe")
    old = PluginPackageRevisionRefV1(
        "workerprobe", "1", "1" * 64, "4" * 64, "/worker/old.whl"
    )
    new = PluginPackageRevisionRefV1(
        "workerprobe", "2", "2" * 64, "5" * 64, "/worker/update.whl"
    )
    desired = PluginDesiredStateLedger(
        root / "desired.jsonl", instance_id_factory=lambda: "instance"
    )
    management = PluginManagementService(
        desired_state=desired, operation_journal_path=root / "operations.jsonl"
    )

    def step(name, *values):
        trace.append([name, *values])
        if name + "-error" in case.split("+"):
            raise RuntimeError("injected-" + name)

    def mutate(action, state, revision=None, selected_key=key, package=None):
        return management.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    action + ":" + selected_key.scope_id,
                    action + ":" + selected_key.scope_id,
                    desired.snapshot().inventory_revision
                    if revision is None
                    else revision,
                    selected_key,
                    state,
                    package,
                    "actor",
                    "policy",
                ),
            )
        )

    if case != "missing-selection":
        mutate("install", "installed_disabled", package=old)
    if case in ("fresh-enabled", "retry-enabled"):
        mutate("enable", "installed_enabled")
    if case == "removed":
        mutate("remove", "absent")
    if case == "multiple-selection":
        mutate(
            "install",
            "installed_disabled",
            selected_key=replace(key, scope_id="other"),
            package=old,
        )
    expected = desired.snapshot().inventory_revision
    args = Namespace(
        action="candidate-update",
        plugin_id="workerprobe",
        operation_id="update",
        artifact_digest=new.package_content_digest,
        from_artifact_digest=old.package_content_digest,
        expected_inventory_revision=expected,
    )
    facts = PackageClassificationFactsV1(
        tuple(
            PackageClassificationBasisFactV1(
                kind, kind == "explicit_plugin_intent", "test", "1"
            )
            for kind in (
                "explicit_plugin_intent",
                "existing_plugin_binding",
                "existing_plugin_history",
                "independent_non_plugin_authority",
            )
        ),
        "policy",
        1,
    )
    request = PackageLifecycleRequestV2(
        "update",
        "update",
        "coding",
        "scope",
        "workerprobe==2",
        "workerprobe",
        new.package_source_identity,
        "policy",
        "quota",
        "e" * 64,
        facts,
        runtime_admission_request_id="f" * 64,
    )
    if case == "retry-source":
        new = replace(new, package_source_identity="/worker/another.whl")
        request = replace(
            request, canonical_source_identity=new.package_source_identity
        )
    command_id, _ = package_product_command_identity(
        "update", request.request_fingerprint
    )
    update_command = PluginManagementUpdateCommandV2(
        command_id, command_id, expected, key, old, new, "actor", "policy"
    )
    prior = None
    if case.startswith("retry"):
        prior = management.submit(update_command)
        if case == "retry-source":
            new = replace(new, package_source_identity="/worker/another.whl")
            # Keep a valid terminal event whose staged source differs from current binding.
            update_command = replace(
                update_command,
                staged_package_revision=replace(
                    new, package_source_identity="/worker/update.whl"
                ),
            )
            alternate = PluginDesiredStateLedger(root / "alternate-desired.jsonl")
            alternate_service = PluginManagementService(
                desired_state=alternate,
                operation_journal_path=root / "alternate-operations.jsonl",
            )
            alternate_service.submit(
                PluginManagementCommandV1(
                    action="install",
                    mutation=PluginDesiredStateMutationV1(
                        "alt-install",
                        "alt-install",
                        0,
                        key,
                        "installed_disabled",
                        old,
                        "actor",
                        "policy",
                    ),
                )
            )
            prior = alternate_service.submit(update_command)
        if case == "retry-request-absent":
            request = None
        elif case == "retry-request-v1":
            from loushang.harness.resources.packages.plugin_lifecycle.records import (
                PackageLifecycleRequestV1,
            )

            request = PackageLifecycleRequestV1(
                "update",
                "update",
                "coding",
                "scope",
                "workerprobe==2",
                "workerprobe",
                new.package_source_identity,
                "policy",
                "quota",
                "e" * 64,
                facts,
            )
        elif case == "retry-request-action":
            request = replace(request, action="install")
        elif case == "retry-request-plugin":
            request = replace(request, requested_plugin_id="other")
        elif case == "retry-request-source":
            request = replace(request, canonical_source_identity="/worker/other.whl")
        elif case == "retry-accepted":
            prior = PluginUpdateOperationEventV2.accepted(
                journal_revision=1, command=prior.command
            )
        elif case == "retry-running":
            prior = PluginUpdateOperationEventV2.staged(
                journal_revision=2, command=prior.command
            )
        elif case == "retry-failed":
            prior = PluginUpdateOperationEventV2.terminal(
                journal_revision=5,
                command=prior.command,
                migration_fence=prior.migration_fence,
                result=PluginUpdateOperationResultV2.failed(
                    error_code="plugin_update_expected_package_mismatch"
                ),
            )
        elif case == "retry-expect":
            args.expected_inventory_revision += 1
        elif case == "retry-from":
            args.from_artifact_digest = "0" * 64
        elif case == "retry-target":
            args.artifact_digest = "3" * 64
    if case in ("stale", "stale-allow"):
        args.expected_inventory_revision += 7
    if case == "from-mismatch":
        args.from_artifact_digest = "0" * 64
    if case == "same-artifact":
        args.from_artifact_digest = old.package_content_digest
        args.artifact_digest = old.package_content_digest
    if case.endswith("-existing"):
        args.action = "candidate-" + case.removesuffix("-existing")
        new = old
        args.artifact_digest = old.package_content_digest
    binding = PackageProductLocalWheelBindingV1(
        new.package_source_identity,
        "workerprobe==2",
        "workerprobe",
        args.artifact_digest,
        plugin_manifest_path="plugin.json",
        source_trust_class="local-worker-candidate",
        worker_admission=PackageProductLocalWorkerAdmissionV1(
            "query",
            "workerprobe",
            "linux-x86_64" if platform == "linux" else "windows-amd64",
        ),
    )
    snapshots = 0

    def snapshot():
        nonlocal snapshots
        snapshots += 1
        step("snapshot", snapshots)
        if case == "post-snapshot-error" and snapshots == 2:
            raise RuntimeError("injected-post-snapshot")
        result = desired.snapshot()
        if case == "selection-changed" and snapshots == 2:
            return replace(result, installations=())
        if case == "retry-key":
            result = replace(
                result,
                installations=tuple(
                    replace(
                        x,
                        installation_key=replace(x.installation_key, scope_id="other"),
                    )
                    for x in result.installations
                ),
            )
        if case == "retry-state":
            result = replace(
                result,
                installations=tuple(
                    replace(x, selection=replace(x.selection, package_revision=old))
                    for x in result.installations
                ),
            )
        if case == "retry-inventory":
            result = replace(result, inventory_revision=result.inventory_revision + 1)
        return result

    def journal_request(_self, operation_id):
        step("request", operation_id)
        return request

    def operation(operation_id):
        step("operation", operation_id)
        return prior if prior is not None else management.operation(operation_id)

    def submit(command):
        step("submit", command.to_dict())
        return management.submit(command)

    def route(intent, **kwargs):
        step("route", intent.operation_id, intent.action, intent.source, kwargs)
        management.submit(update_command)
        return NS(handled=case != "route-refused", record=NS(lifecycle="installed"))

    runtime = NS(
        activate=lambda: step("activate"),
        lifecycle=NS(route=route),
        dispose_runtime=lambda: step("dispose"),
    )

    def create(request):
        step("create", request.product_id, request.session_id, request.cwd)
        return runtime

    def factory(**kwargs):
        step("factory", {k: str(v) for k, v in kwargs.items()})
        return NS(create=create, dispose_unbound_runtime=lambda: step("unbound"))

    class OptIn:
        def __init__(self, product):
            step("owner")

        def current(self, plugin_id):
            step("current", plugin_id)
            return NS(
                action="allow"
                if case in ("allow", "stale-allow", "retry-allow")
                else "revoke"
            )

    def token(count):
        step("token", count)
        return "f" * (count * 2)

    module = linux if platform == "linux" else windows
    monkeypatch.setattr(
        module,
        "CodingWorkerProductOptInOwner"
        if platform == "linux"
        else "CodingWindowsWorkerProductOptInOwner",
        OptIn,
    )
    monkeypatch.setattr(PackageLifecycleJournal, "request", journal_request)
    monkeypatch.setattr(secrets, "token_hex", token)
    product = NS(
        state_root=root,
        workspace=Path("/workspace"),
        actor_id="actor",
        desired_policy_revision="policy",
        policy=NS(
            bindings=(binding, binding) if case == "ambiguous-binding" else (binding,)
        ),
        desired_state=NS(snapshot=snapshot),
        management=NS(operation=operation, submit=submit),
        factory_for_session=factory,
    )
    try:
        result = module._execute(product, args)
        error = None
    except BaseException as exc:
        result = None
        error = error_graph(exc)
    return {
        "trace": trace,
        "result": result,
        "error": error,
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.glob("*.jsonl")
        },
    }


@pytest.mark.parametrize("platform", ("linux", "windows"))
@pytest.mark.parametrize("case", CASES)
def test_original_candidate_update(platform, case, tmp_path, monkeypatch):
    actual = observe(platform, case, tmp_path / "state", monkeypatch)
    assert actual == OBSERVATIONS[f"{platform}-{case}"]
