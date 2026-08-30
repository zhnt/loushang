from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

import pytest

import loushang.coding._base_plugin as base_plugin_module
import loushang.coding._plugin_lifecycle as plugin_lifecycle_module
from loushang.ai.model import Capabilities, Model
from loushang.coding._base_plugin import (
    CodingBasePluginAssemblyError,
    coding_base_plugin_root,
    prepare_managed_coding_base_plugin_assembly,
)
from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleError,
    build_coding_plugin_lifecycle,
    package_revision_ref,
    resolve_coding_plugin_lifecycle_state_layout,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementCommandV1,
    PluginManagementUpdateCommandV2,
)
from loushang.harness.resources.plugins import (
    PluginResolutionAuthority,
    PluginSource,
)
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)


def _materializer(root: Path) -> CodingPackageMaterializer:
    return CodingPackageMaterializer(
        install_root=root / "packages",
        plugin_revision_root=root / "revisions",
    )


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _lifecycle(root: Path):
    lifecycle = build_coding_plugin_lifecycle(
        resolve_ephemeral_coding_plugin_lifecycle_state_layout(
            root / "state",
            cwd=root / "workspace",
        )
    )
    lifecycle.reconcile_retirements()
    lifecycle.complete_startup_recovery()
    return lifecycle


def _copy_base(root: Path, name: str) -> Path:
    target = root / name
    shutil.copytree(coding_base_plugin_root(), target)
    return target


def _platform_paths(root: Path) -> PlatformPaths:
    return PlatformPaths(
        home=root,
        data=root / "data",
        state=root / "state",
        cache=root / "cache",
        runtime=root / "runtime",
        temporary=root / "tmp",
    )


def _package_ref(plugin_id: str = "coding.base"):
    return package_revision_ref(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        package_source_identity=f"embedded:{plugin_id}",
    )


_TEST_OWNER_CONTRIBUTIONS = (
    ("commands.session", ("coding.standard",)),
    ("resources.prompt", ("prompt-standard",)),
    ("resources.skill", ("skill-standard",)),
    ("tools.workspace", ("coding.builtin",)),
)


def _disable_or_remove(lifecycle, *, action: str) -> object:
    key = lifecycle.installation_key("coding.base")
    snapshot = lifecycle.desired.snapshot()
    desired_state = "installed_disabled" if action == "disable" else "absent"
    event = lifecycle.management.submit(
        PluginManagementCommandV1(
            action=action,
            mutation=PluginDesiredStateMutationV1(
                operation_id=f"test-{action}:{snapshot.inventory_revision}",
                idempotency_key=f"test-{action}:{snapshot.inventory_revision}",
                expected_inventory_revision=snapshot.inventory_revision,
                installation_key=key,
                desired_state=desired_state,
                package_revision=None,
                actor_id="test:operator",
                policy_revision="test-policy-v1",
                approval_reference="test",
            ),
        )
    )
    assert event.result is not None
    assert event.result.disposition == "succeeded"
    return event


def _managed_base(
    root: Path,
    *,
    session_id: str,
    materializer: CodingPackageMaterializer,
    lifecycle,
):
    return prepare_managed_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id=session_id,
        package_materializer=materializer,
        lifecycle=lifecycle,
    )


def test_first_party_default_uses_management_once_and_replays_without_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_base(tmp_path, "mutable-base")
    monkeypatch.setattr(base_plugin_module, "coding_base_plugin_root", lambda: source)
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)

    first = _managed_base(
        tmp_path,
        session_id="managed-1",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    assert first is not None
    key = lifecycle.installation_key("coding.base")
    state = lifecycle.desired.snapshot().installation(key)
    assert state.selection.desired_state == "installed_enabled"
    assert len(lifecycle.desired.transitions()) == 2
    assert first.plan_seed.plan.context.instance_revision_refs == (
        state.selection.instance_revision_ref,
    )
    pinned_root = first.package.root
    shutil.rmtree(source)

    second = _managed_base(
        tmp_path,
        session_id="managed-2",
        materializer=_materializer(tmp_path),
        lifecycle=_lifecycle(tmp_path),
    )
    assert second is not None
    try:
        assert len(lifecycle.desired.transitions()) == 2
        assert second.package.root == pinned_root
        assert second.binding.source == str(source.resolve())
        assert second.package.revision_handle.closed is False
        assert second.evaluate_management_change().disposition == "no_change"
    finally:
        second.close()
        first.close()


def test_first_party_default_resumes_its_own_crash_interrupted_install(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    package = _package_ref()
    event = lifecycle.management.submit(
        PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id="coding-default-crash-install",
                idempotency_key="coding-default-crash-install",
                expected_inventory_revision=0,
                installation_key=key,
                desired_state="installed_disabled",
                package_revision=package,
                actor_id="product:coding",
                policy_revision="coding-plugin-lifecycle-v1",
                approval_reference="coding-first-party-default",
            ),
        )
    )
    assert event.result is not None
    assert event.result.disposition == "succeeded"

    _lifecycle(tmp_path).bootstrap_first_party_default(key, package)

    state = lifecycle.desired.snapshot().installation(key)
    assert state.selection.desired_state == "installed_enabled"
    assert state.selection.package_revision == package
    assert len(lifecycle.desired.transitions()) == 2


def test_first_party_default_never_overrides_operator_remove_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    package = _package_ref()
    original = type(lifecycle)._submit_default
    raced = False

    def race(self, submitted_key, **kwargs):
        nonlocal raced
        if self is lifecycle and kwargs["action"] == "install" and not raced:
            raced = True
            install = self.management.submit(
                PluginManagementCommandV1(
                    action="install",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="operator-install",
                        idempotency_key="operator-install",
                        expected_inventory_revision=0,
                        installation_key=key,
                        desired_state="installed_disabled",
                        package_revision=package,
                        actor_id="test:operator",
                        policy_revision="test-policy-v1",
                        approval_reference="test",
                    ),
                )
            )
            assert install.result is not None
            assert install.result.disposition == "succeeded"
            _disable_or_remove(self, action="remove")
        return original(self, submitted_key, **kwargs)

    monkeypatch.setattr(type(lifecycle), "_submit_default", race)
    lifecycle.bootstrap_first_party_default(key, package)

    state = lifecycle.desired.snapshot().installation(key)
    assert state.selection.desired_state == "absent"
    assert len(lifecycle.desired.transitions()) == 2


def test_first_party_default_retries_unrelated_inventory_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    package = _package_ref()
    original = type(lifecycle)._submit_default
    raced = False

    def race(self, submitted_key, **kwargs):
        nonlocal raced
        if self is lifecycle and kwargs["action"] == "install" and not raced:
            raced = True
            snapshot = self.desired.snapshot()
            other_key = self.installation_key("coding.other")
            event = self.management.submit(
                PluginManagementCommandV1(
                    action="install",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="other-install",
                        idempotency_key="other-install",
                        expected_inventory_revision=snapshot.inventory_revision,
                        installation_key=other_key,
                        desired_state="installed_disabled",
                        package_revision=_package_ref("coding.other"),
                        actor_id="test:operator",
                        policy_revision="test-policy-v1",
                        approval_reference="test",
                    ),
                )
            )
            assert event.result is not None
            assert event.result.disposition == "succeeded"
        return original(self, submitted_key, **kwargs)

    monkeypatch.setattr(type(lifecycle), "_submit_default", race)
    lifecycle.bootstrap_first_party_default(key, package)

    assert lifecycle.desired.snapshot().installation(
        key
    ).selection.desired_state == "installed_enabled"
    assert len(lifecycle.desired.transitions()) == 3


def test_concurrent_sessions_share_exact_activation_but_not_live_lease(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    barrier = threading.Barrier(2)

    def acquire(sequence: int):
        current = _lifecycle(tmp_path)
        barrier.wait()
        return current.acquire_session(
            key,
            session_id=f"session-{sequence}",
            lease_attempt_id=f"attempt-{sequence}",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = tuple(executor.map(acquire, (1, 2)))
    try:
        assert leases[0].instance_revision_ref == leases[1].instance_revision_ref
        assert leases[0].family.family_id != leases[1].family.family_id
        assert len(lifecycle.instances.snapshot().open_families) == 3
    finally:
        leases[0].close()
        leases[1].close()


def test_same_session_resume_is_process_exclusive_and_retryable(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    first = lifecycle.acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-first",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    contender = _lifecycle(tmp_path)

    with pytest.raises(CodingPluginLifecycleError) as caught:
        contender.acquire_session(
            key,
            session_id="shared-conversation",
            lease_attempt_id="attempt-concurrent",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        )

    assert caught.value.code == "coding_plugin_session_already_active"
    assert len(lifecycle.instances.snapshot().open_families) == 2
    first.close()

    resumed = contender.acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-after-close",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    resumed.close()


def test_same_session_owner_reenters_until_its_last_process_lease_closes(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    owner_id = "session-manager:shared"
    first = lifecycle.acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-first",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        session_owner_id=owner_id,
    )
    second = _lifecycle(tmp_path).acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-second",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        session_owner_id=owner_id,
    )
    lease_path = plugin_lifecycle_module._session_owner_lease_path(
        lifecycle.layout,
        session_id="shared-conversation",
    )
    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        state = plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES[lease_path]
        assert state.owner_id == owner_id
        assert state.references == 2

    first.close()
    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        assert (
            plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES[
                lease_path
            ].references
            == 1
        )
    with pytest.raises(CodingPluginLifecycleError) as caught:
        _lifecycle(tmp_path).acquire_session(
            key,
            session_id="shared-conversation",
            lease_attempt_id="attempt-contender",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
            session_owner_id="session-manager:other",
        )
    assert caught.value.code == "coding_plugin_session_already_active"

    second.close()
    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        assert lease_path not in plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES
    resumed = _lifecycle(tmp_path).acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-after-close",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        session_owner_id="session-manager:other",
    )
    resumed.close()


def test_concurrent_last_session_close_linearizes_exact_retirement(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    leases = tuple(
        lifecycle.acquire_session(
            key,
            session_id=f"session-{sequence}",
            lease_attempt_id=f"attempt-{sequence}",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        )
        for sequence in (1, 2)
    )
    for sequence, lease in enumerate(leases, start=1):
        receipt = OwnerGenerationRetirementReceipt(
            owner_reference=f"owner:session-{sequence}",
            owner_generation_reference=f"generation:session-{sequence}",
            retirement_handle=f"retirement:session-{sequence}",
            contribution_ids=("coding.standard",),
        )
        lease.publish_owner_generations((receipt,))
        lease.retire_owner_generations((receipt,))

    _disable_or_remove(lifecycle, action="disable")
    lifecycle.reconcile_retirements()
    barrier = threading.Barrier(2)

    def close(lease) -> None:
        barrier.wait()
        lease.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(close, leases))

    selected_ref = leases[0].instance_revision_ref
    retired = lifecycle.instances.snapshot().instance(selected_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    [intent] = lifecycle.management_retirement_intents()
    completed = lifecycle.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert completed is not None
    assert completed.state == "succeeded"
    assert completed.plan is not None
    assert len(completed.plan.targets) == 2
    assert len(completed.latest_outcomes) == 2


def test_public_lease_publish_writes_prepared_evidence_first(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    lease = lifecycle.acquire_session(
        key,
        session_id="write-ahead-session",
        lease_attempt_id="write-ahead-attempt",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    receipt = OwnerGenerationRetirementReceipt(
        owner_reference="owner:write-ahead",
        owner_generation_reference="generation:write-ahead",
        retirement_handle="retirement:write-ahead",
        contribution_ids=("coding.standard",),
    )

    lease.publish_owner_generations((receipt,))

    evidence = lifecycle.owner_evidence.family(lease.family.family_id)
    assert evidence is not None
    assert evidence.publication_state == "published"
    assert len(
        lifecycle.layout.owner_generation_evidence.read_text(
            encoding="utf-8"
        ).splitlines()
    ) == 2
    lease.retire_owner_generations((receipt,))
    lease.close()


@pytest.mark.parametrize("publish_owner_evidence", [False, True])
def test_startup_lock_fault_injection_requires_positive_orphan_evidence(
    tmp_path: Path,
    publish_owner_evidence: bool,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "state",
        cwd=tmp_path / "workspace",
    )
    old_startup = f"old-startup-{publish_owner_evidence}"
    old = build_coding_plugin_lifecycle(layout, startup_id=old_startup)
    old.reconcile_retirements()
    old.complete_startup_recovery()
    key = old.installation_key("coding.base")
    old.bootstrap_first_party_default(key, _package_ref())
    lease = old.acquire_session(
        key,
        session_id="crashed-session",
        lease_attempt_id="crashed-attempt",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    receipt = OwnerGenerationRetirementReceipt(
        owner_reference="owner:crashed-session",
        owner_generation_reference="generation:crashed-session",
        retirement_handle="retirement:crashed-session",
        contribution_ids=("coding.standard",),
    )
    if publish_owner_evidence:
        lease.publish_owner_generations((receipt,))

    recovered = build_coding_plugin_lifecycle(
        layout,
        startup_id=f"new-startup-{publish_owner_evidence}",
    )
    recovered.reconcile_retirements()
    assert recovered.instances.snapshot().family(lease.family.family_id) is not None

    # Narrow unit-level fault injection for both owner-evidence branches.  The
    # product-level tests below kill a real child process and prove the OS lock
    # transition without reaching into this process-local registry.
    old_lease_path = plugin_lifecycle_module._startup_lease_path(
        layout,
        startup_id=old_startup,
    )
    with plugin_lifecycle_module._PROCESS_STARTUP_LEASES_LOCK:
        old_process_lease = plugin_lifecycle_module._PROCESS_STARTUP_LEASES.pop(
            old_lease_path
        )
    old_process_lease.__exit__(None, None, None)

    recovered.reconcile_retirements()

    assert recovered.instances.snapshot().family(lease.family.family_id) is None
    family_evidence = recovered.owner_evidence.family(lease.family.family_id)
    if publish_owner_evidence:
        assert family_evidence is not None
        assert family_evidence.retired is True
        assert family_evidence.retirement_outcome_reference == (
            "coding-session-process-exit-confirmed:"
            f"{old_startup}:{lease.family.family_id}"
        )
    else:
        assert family_evidence is None

    _disable_or_remove(recovered, action="disable")
    recovered.reconcile_retirements()
    retired = recovered.instances.snapshot().instance(lease.instance_revision_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    [intent] = recovered.management_retirement_intents()
    retirement_set = recovered.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert retirement_set is not None
    assert retirement_set.state == "succeeded"
    assert retirement_set.plan is not None
    assert len(retirement_set.plan.targets) == int(publish_owner_evidence)


def _start_plugin_lifecycle_child(
    tmp_path: Path,
    *,
    mode: str,
) -> tuple[subprocess.Popen[str], dict[str, object], Path]:
    helper = Path(__file__).parent / "fixtures" / "plugin_lifecycle_child.py"
    marker = tmp_path / "owner-publication-crash.json"
    process = subprocess.Popen(
        (
            sys.executable,
            str(helper),
            mode,
            str(tmp_path / "loushang-home"),
            str(tmp_path / "workspace"),
            str(tmp_path / "sessions"),
            str(marker),
        ),
        cwd=Path(__file__).parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    with ThreadPoolExecutor(max_workers=1) as executor:
        handshake = executor.submit(process.stdout.readline)
        try:
            line = handshake.result(timeout=20)
        except FutureTimeoutError:
            _stop_plugin_lifecycle_child(process)
            pytest.fail("Plugin lifecycle child handshake timed out")
    if not line:
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.wait(timeout=20)
        pytest.fail(
            f"Plugin lifecycle child exited before publishing state: {stderr}"
        )
    return process, json.loads(line), marker


def _stop_plugin_lifecycle_child(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=20)


def test_same_session_owner_lease_rejects_another_process_until_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    process, child_state, _marker = _start_plugin_lifecycle_child(
        tmp_path,
        mode="hold",
    )
    lifecycle = build_coding_plugin_lifecycle(
        resolve_coding_plugin_lifecycle_state_layout(workspace)
    )
    key = lifecycle.installation_key("coding.base")
    try:
        with pytest.raises(CodingPluginLifecycleError) as caught:
            lifecycle.acquire_session(
                key,
                session_id=str(child_state["sessionId"]),
                lease_attempt_id="attempt-while-child-live",
                owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
                session_owner_id="parent-runtime",
            )
        assert caught.value.code == "coding_plugin_session_already_active"

        process.kill()
        assert process.wait(timeout=20) != 0
        resumed = lifecycle.acquire_session(
            key,
            session_id=str(child_state["sessionId"]),
            lease_attempt_id="attempt-after-child-exit",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
            session_owner_id="parent-runtime",
        )
        resumed.close()
    finally:
        _stop_plugin_lifecycle_child(process)


def test_real_process_death_preserves_live_family_then_recovers_exact_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    process, child_state, _marker = _start_plugin_lifecycle_child(
        tmp_path,
        mode="hold",
    )
    family_id = str(child_state["familyId"])
    try:
        recovered = build_coding_plugin_lifecycle(layout)
        recovered.reconcile_retirements()
        assert recovered.instances.snapshot().family(family_id) is not None

        process.kill()
        assert process.wait(timeout=20) != 0
        recovered.reconcile_retirements()

        assert recovered.instances.snapshot().family(family_id) is None
        family_evidence = recovered.owner_evidence.family(family_id)
        assert family_evidence is not None
        assert family_evidence.retired is True
        assert len(family_evidence.receipts) == 3
        _disable_or_remove(recovered, action="disable")
        recovered.reconcile_retirements()
        [intent] = recovered.management_retirement_intents()
        retirement_set = recovered.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert retirement_set is not None
        assert retirement_set.state == "succeeded"
        assert retirement_set.plan is not None
        assert len(retirement_set.plan.targets) == 3
    finally:
        _stop_plugin_lifecycle_child(process)


def test_hard_crash_after_owner_commit_recovers_prepared_exact_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    process, child_state, marker = _start_plugin_lifecycle_child(
        tmp_path,
        mode="crash_during_owner_publication",
    )
    family_id = str(child_state["familyId"])
    try:
        exit_code = process.wait(timeout=20)
        assert process.stderr is not None
        stderr = process.stderr.read()
        assert exit_code == 83, stderr
        marker_payload = json.loads(marker.read_text(encoding="utf-8"))
        assert marker_payload == {"familyId": family_id, "receiptCount": 3}

        recovered = build_coding_plugin_lifecycle(layout)
        recovered.reconcile_retirements()

        assert recovered.instances.snapshot().family(family_id) is None
        family_evidence = recovered.owner_evidence.family(family_id)
        assert family_evidence is not None
        assert family_evidence.publication_state == "retired"
        assert len(family_evidence.receipts) == 3
        _disable_or_remove(recovered, action="disable")
        recovered.reconcile_retirements()
        [intent] = recovered.management_retirement_intents()
        retirement_set = recovered.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert retirement_set is not None
        assert retirement_set.state == "succeeded"
        assert retirement_set.plan is not None
        assert len(retirement_set.plan.targets) == 3
    finally:
        _stop_plugin_lifecycle_child(process)


def test_workspace_lifecycle_uses_state_and_data_authorities_independent_of_session_scope(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    alias = tmp_path / "workspace-alias"
    alias.symlink_to(workspace, target_is_directory=True)
    first_paths = _platform_paths(tmp_path / "user-a")
    second_paths = _platform_paths(tmp_path / "user-b")

    first = resolve_coding_plugin_lifecycle_state_layout(
        workspace,
        platform_paths=first_paths,
    )
    canonical_alias = resolve_coding_plugin_lifecycle_state_layout(
        alias,
        platform_paths=first_paths,
    )
    other_user = resolve_coding_plugin_lifecycle_state_layout(
        workspace,
        platform_paths=second_paths,
    )
    other_workspace = resolve_coding_plugin_lifecycle_state_layout(
        tmp_path / "other-workspace",
        platform_paths=first_paths,
    )

    assert canonical_alias.scope_id == first.scope_id
    assert canonical_alias.root == first.root
    assert canonical_alias.package_root == first.package_root
    assert first.root.is_relative_to(first_paths.state)
    assert first.package_root.is_relative_to(first_paths.data)
    assert other_user.scope_id == first.scope_id
    assert other_user.root != first.root
    assert other_user.package_root != first.package_root
    assert other_workspace.scope_id != first.scope_id


def test_persisted_session_rejects_noncanonical_base_package_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        )
        with pytest.raises(CodingBasePluginAssemblyError) as caught:
            create_agent_session(
                session_manager=manager,
                model=_model(),
                services=services,
                package_materializer=_materializer(tmp_path / "session-authority"),
            )
        assert caught.value.code == "coding_base_package_authority_mismatch"

    asyncio.run(scenario())


def test_production_package_replay_crosses_session_save_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    source = _copy_base(tmp_path, "mutable-production-base")
    monkeypatch.setattr(base_plugin_module, "coding_base_plugin_root", lambda: source)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "cwd-sessions",
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        first_base = first._coding_base_plugin_assembly
        assert first_base is not None
        first_lease = first_base.management_lease
        assert first_lease is not None
        pinned_root = first_base.package.root
        pinned_ref = first_lease.instance_revision_ref
        shutil.rmtree(source)

        second_manager = await SessionManager.new(
            session_dir=tmp_path / "user-global-sessions",
            cwd=str(workspace),
            persist=True,
        )
        second = create_agent_session(
            session_manager=second_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        second_base = second._coding_base_plugin_assembly
        assert second_base is not None
        second_lease = second_base.management_lease
        assert second_lease is not None
        assert second_base.package.root == pinned_root
        assert second_lease.instance_revision_ref == pinned_ref
        await second.dispose()
        await first.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("corruption", "expected_code"),
    (
        ("missing_binding", "coding_base_binding_replay_unavailable"),
        ("missing_revision", "coding_base_revision_replay_unavailable"),
        ("tampered_revision", "coding_base_revision_replay_integrity_failed"),
        (
            "dependency_mismatch",
            "coding_base_binding_replay_invalid",
        ),
        ("selected_revision_mismatch", "coding_base_selected_revision_mismatch"),
    ),
)
def test_public_base_replay_fails_closed_without_leaking_a_session_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    expected_code: str,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import CodingPackageMaterializer
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)

    def services():
        return create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        )

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-first",
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=services(),
        )
        first_base = first._coding_base_plugin_assembly
        assert first_base is not None
        first_lease = first_base.management_lease
        assert first_lease is not None
        selected = first_lease.package_revision
        await first.dispose()

        lifecycle = build_coding_plugin_lifecycle(layout)
        families_before = lifecycle.instances.snapshot().open_families
        if corruption == "selected_revision_mismatch":
            key = lifecycle.installation_key("coding.base")
            snapshot = lifecycle.desired.snapshot()
            update = lifecycle.management.submit(
                PluginManagementUpdateCommandV2(
                    operation_id="public-replay-selection-mismatch",
                    idempotency_key="public-replay-selection-mismatch",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=key,
                    expected_package_revision=selected,
                    staged_package_revision=package_revision_ref(
                        plugin_id=selected.plugin_id,
                        plugin_version="invalid-selected-version",
                        package_content_digest=selected.package_content_digest,
                        dependency_lock_digest=selected.dependency_lock_digest,
                        package_source_identity=(
                            selected.package_source_identity
                        ),
                    ),
                    actor_id="test:operator",
                    policy_revision="test-policy-v1",
                    approval_reference="test",
                )
            )
            assert update.result is not None
            assert update.result.disposition == "restart_required"
        elif corruption in {"missing_binding", "dependency_mismatch"}:
            payload = json.loads(layout.package_lockfile.read_text(encoding="utf-8"))
            bindings = payload["pluginBindings"]
            if corruption == "missing_binding":
                payload["pluginBindings"] = []
                payload["pluginBindingHeads"] = []
            else:
                [binding] = [
                    item for item in bindings if item["pluginId"] == "coding.base"
                ]
                binding["dependencyLockDigest"] = "0" * 64
            layout.package_lockfile.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        else:
            revision_root = (
                layout.plugin_revision_root
                / "sha256"
                / selected.package_content_digest
            )
            if corruption == "missing_revision":
                revision_root.rename(revision_root.with_suffix(".missing"))
            else:
                prompt = revision_root / "prompts" / "standard.md"
                prompt.chmod(0o600)
                prompt.write_text("tampered immutable revision", encoding="utf-8")

        monkeypatch.setattr(
            base_plugin_module,
            "coding_base_plugin_root",
            lambda: (_ for _ in ()).throw(
                AssertionError("durable replay must not inspect mutable source")
            ),
        )
        reopened_handles = []
        reopen = CodingPackageMaterializer.reopen_plugin_package

        def capture_reopen(self, binding):
            package = reopen(self, binding)
            reopened_handles.append(package.revision_handle)
            return package

        monkeypatch.setattr(
            CodingPackageMaterializer,
            "reopen_plugin_package",
            capture_reopen,
        )
        failed_services = services()
        failed_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-failed",
            cwd=str(workspace),
            persist=True,
        )
        with pytest.raises(CodingBasePluginAssemblyError) as caught:
            create_agent_session(
                session_manager=failed_manager,
                model=_model(),
                services=failed_services,
            )

        assert caught.value.code == expected_code
        family_ids_before = {family.family_id for family in families_before}
        family_ids_after = {
            family.family_id
            for family in lifecycle.instances.snapshot().open_families
        }
        assert family_ids_after <= family_ids_before
        if corruption == "selected_revision_mismatch":
            assert len(reopened_handles) == 1
            assert reopened_handles[0].closed is True
        else:
            assert reopened_handles == []
        diagnostics = failed_services.diagnostics_service.get_diagnostics(
            phase="startup",
            source="bootstrap",
            code=expected_code,
        )
        assert len(diagnostics) == 1
        assert diagnostics[0].session_id == (
            failed_manager.get_header().conversation_id
        )
        assert diagnostics[0].details == {
            "check": "coding_base_exact_replay",
            "ok": False,
        }

    asyncio.run(scenario())


def test_nonpersistent_transcript_honors_configured_durable_product_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    global_settings = tmp_path / "settings" / "settings.json"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-a",
            cwd=str(workspace),
            persist=False,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"}),
                    global_settings_path=global_settings,
                )
            ),
        )
        assert first._coding_base_plugin_assembly is not None
        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action="disable")
        lifecycle.reconcile_retirements()

        second_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-b",
            cwd=str(workspace),
            persist=False,
        )
        second = create_agent_session(
            session_manager=second_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"}),
                    global_settings_path=global_settings,
                )
            ),
        )
        assert second._coding_base_plugin_assembly is None
        await second.dispose()
        await first.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("action", "reason"),
    (("disable", "plugin_disabled"), ("remove", "plugin_removed")),
)
def test_explicit_disable_or_remove_never_self_heals_and_pins_active_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    reason: str,
) -> None:
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    active = _managed_base(
        tmp_path,
        session_id=f"active-{action}",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    assert active is not None
    active_ref = active.management_lease.instance_revision_ref
    active_handle = active.package.revision_handle
    _disable_or_remove(lifecycle, action=action)

    change = active.evaluate_management_change()
    assert change is not None
    assert change.disposition == "restart_required"
    assert change.reason == reason
    assert change.diagnostic_details()["restartRequired"] is True
    monkeypatch.setattr(
        base_plugin_module,
        "coding_base_plugin_root",
        lambda: (_ for _ in ()).throw(AssertionError("source must not be scanned")),
    )
    replacement = _managed_base(
        tmp_path,
        session_id=f"new-{action}",
        materializer=materializer,
        lifecycle=_lifecycle(tmp_path),
    )
    assert replacement is None
    assert active_handle.closed is False
    assert len(lifecycle.desired.transitions()) == 3
    active.close()
    assert active_handle.closed is True
    retired = lifecycle.instances.snapshot().instance(active_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    intent = next(
        item
        for item in lifecycle.management_retirement_intents()
        if item.instance_revision_ref == active_ref
    )
    retirement_set = lifecycle.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert retirement_set is not None
    assert retirement_set.state == "succeeded"
    assert retirement_set.plan is not None
    assert len(retirement_set.latest_outcomes) == len(retirement_set.plan.targets)
    retention = lifecycle.packages.snapshot().package(retired.package_revision)
    assert retention is not None
    assert retention.nonretired_instances == ()
    assert retention.open_cleanup_ids == ()


def test_retirement_waits_for_every_session_owner_generation(
    tmp_path: Path,
) -> None:
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    first = _managed_base(
        tmp_path,
        session_id="retirement-first",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    second = _managed_base(
        tmp_path,
        session_id="retirement-second",
        materializer=materializer,
        lifecycle=_lifecycle(tmp_path),
    )
    assert first is not None
    assert second is not None
    old_ref = first.management_lease.instance_revision_ref
    assert second.management_lease.instance_revision_ref == old_ref
    _disable_or_remove(lifecycle, action="disable")

    first.close()

    draining = lifecycle.instances.snapshot().instance(old_ref)
    assert draining is not None
    assert draining.state == "DRAINING"
    assert len(draining.open_family_ids) == 2

    second.close()

    retired = lifecycle.instances.snapshot().instance(old_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    [intent] = lifecycle.management_retirement_intents()
    retirement_set = lifecycle.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert retirement_set is not None
    assert retirement_set.state == "succeeded"
    assert retirement_set.plan is not None
    # These low-level assemblies never publish a Session runtime, so there are
    # no real owner generations to retire.  Lifecycle must not manufacture the
    # historical four static owner targets.
    assert retirement_set.plan.targets == ()
    assert retirement_set.latest_outcomes == ()


def test_update_selects_new_revision_while_old_session_remains_pinned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_source = _copy_base(tmp_path, "base-v1")
    monkeypatch.setattr(
        base_plugin_module,
        "coding_base_plugin_root",
        lambda: original_source,
    )
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    active = _managed_base(
        tmp_path,
        session_id="update-old",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    assert active is not None
    old_root = active.package.root
    old_ref = active.management_lease.instance_revision_ref
    key = lifecycle.installation_key("coding.base")
    expected = lifecycle.desired.snapshot().installation(key).selection.package_revision
    assert expected is not None

    updated_source = _copy_base(tmp_path, "base-v2")
    manifest_path = updated_source / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "2.0.0"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    updated_runtime = authority.publish_runtime(
        (authority.inspect(PluginSource(path=updated_source)),),
        binding_store=materializer,
    )
    [updated_package] = updated_runtime.packages
    [updated_binding] = updated_runtime.bindings
    staged = package_revision_ref(
        plugin_id=updated_package.manifest.name,
        plugin_version=updated_package.manifest.version,
        package_content_digest=updated_package.content_digest,
        dependency_lock_digest=updated_package.dependency_lock.digest,
        package_source_identity=updated_binding.source_identity,
    )
    updated_runtime.close()
    snapshot = lifecycle.desired.snapshot()
    update_event = lifecycle.management.submit(
        PluginManagementUpdateCommandV2(
            operation_id="test-update",
            idempotency_key="test-update",
            expected_inventory_revision=snapshot.inventory_revision,
            installation_key=key,
            expected_package_revision=expected,
            staged_package_revision=staged,
            actor_id="test:operator",
            policy_revision="test-policy-v1",
            approval_reference="test",
        )
    )
    assert update_event.result is not None
    assert update_event.result.disposition == "restart_required"
    shutil.rmtree(updated_source)

    replacement = _managed_base(
        tmp_path,
        session_id="update-new",
        materializer=_materializer(tmp_path),
        lifecycle=_lifecycle(tmp_path),
    )
    assert replacement is not None
    try:
        assert replacement.package.content_digest == staged.package_content_digest
        assert replacement.package.root != old_root
        assert replacement.management_lease.instance_revision_ref.revision == (
            old_ref.revision + 1
        )
        assert active.package.root == old_root
        assert active.package.revision_handle.closed is False
        change = active.evaluate_management_change()
        assert change is not None
        assert change.disposition == "restart_required"
        assert change.reason == "plugin_updated"
    finally:
        replacement.close()
        active.close()
    retired = lifecycle.instances.snapshot().instance(old_ref)
    assert retired is not None
    assert retired.state == "RETIRED"


def test_public_update_replays_deleted_source_into_model_input_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"
    original_source = _copy_base(tmp_path, "public-base-v1")
    monkeypatch.setattr(
        base_plugin_module,
        "coding_base_plugin_root",
        lambda: original_source,
    )

    async def scenario() -> None:
        services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        )
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=services,
        )
        await active.prepare_model_call_runtime()
        active_base = active._coding_base_plugin_assembly
        assert active_base is not None
        old_ref = active_base.management_lease.instance_revision_ref
        layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
        lifecycle = build_coding_plugin_lifecycle(layout)
        key = lifecycle.installation_key("coding.base")
        expected = lifecycle.desired.snapshot().installation(
            key
        ).selection.package_revision
        assert expected is not None

        # Advance the exact same configured checkout.  The lock must retain v1
        # even though the mutable source now presents v2.
        updated_source = original_source
        manifest_path = updated_source / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "2.0.0"
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        marker = "PLC6 public immutable replay marker"
        (updated_source / "prompts" / "standard.md").write_text(
            marker,
            encoding="utf-8",
        )
        materializer = CodingPackageMaterializer(
            install_root=layout.package_install_root,
            lockfile_path=layout.package_lockfile,
            plugin_revision_root=layout.plugin_revision_root,
        )
        authority = PluginResolutionAuthority()
        updated_runtime = authority.publish_runtime(
            (authority.inspect(PluginSource(path=updated_source)),),
            binding_store=materializer,
        )
        [updated_package] = updated_runtime.packages
        [updated_binding] = updated_runtime.bindings
        staged = package_revision_ref(
            plugin_id=updated_package.manifest.name,
            plugin_version=updated_package.manifest.version,
            package_content_digest=updated_package.content_digest,
            dependency_lock_digest=updated_package.dependency_lock.digest,
            package_source_identity=updated_binding.source_identity,
        )
        updated_runtime.close()

        precutover_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        precutover = create_agent_session(
            session_manager=precutover_manager,
            model=_model(),
            services=services,
        )
        precutover_base = precutover._coding_base_plugin_assembly
        assert precutover_base is not None
        assert precutover_base.package.content_digest == (
            expected.package_content_digest
        )
        assert precutover_base.binding.source_identity == (
            expected.package_source_identity
        )
        await precutover.dispose()

        snapshot = lifecycle.desired.snapshot()
        update = lifecycle.management.submit(
            PluginManagementUpdateCommandV2(
                operation_id="public-test-update",
                idempotency_key="public-test-update",
                expected_inventory_revision=snapshot.inventory_revision,
                installation_key=key,
                expected_package_revision=expected,
                staged_package_revision=staged,
                actor_id="test:operator",
                policy_revision="test-policy-v1",
                approval_reference="test",
            )
        )
        assert update.result is not None
        assert update.result.disposition == "restart_required"
        shutil.rmtree(updated_source)

        replay_store = CodingPackageMaterializer(
            install_root=layout.package_install_root,
            lockfile_path=layout.package_lockfile,
            plugin_revision_root=layout.plugin_revision_root,
        )
        old_binding = replay_store.get_plugin_binding_by_revision(
            expected.package_source_identity,
            content_digest=expected.package_content_digest,
            dependency_lock_digest=expected.dependency_lock_digest,
        )
        assert old_binding is not None
        reopened_old = replay_store.reopen_plugin_package(old_binding)
        try:
            assert reopened_old.manifest.version == expected.plugin_version
            assert reopened_old.content_digest == expected.package_content_digest
        finally:
            reopened_old.revision_handle.close()
        monkeypatch.setattr(
            base_plugin_module,
            "coding_base_plugin_root",
            lambda: (_ for _ in ()).throw(
                AssertionError("updated source must not be rescanned")
            ),
        )
        await active.dispose()

        replacement_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        replacement = create_agent_session(
            session_manager=replacement_manager,
            model=_model(),
            services=services,
        )
        replacement_base = replacement._coding_base_plugin_assembly
        assert replacement_base is not None
        assert replacement_base.package.content_digest == staged.package_content_digest
        assert replacement_base.binding.source == str(updated_source.resolve())

        await replacement.prepare_model_call_runtime()

        assert marker in replacement.agent.system_prompt
        assert len(replacement._capability_owner_generations) == 2
        replacement_inputs = replacement._capability_composition_inputs
        assert replacement_inputs is not None
        replacement_lease = replacement_base.management_lease
        assert replacement_lease is not None
        replacement_ref = replacement_lease.instance_revision_ref
        assert all(
            admission.candidate.instance_revision_ref == replacement_ref
            and admission.candidate.package_content_digest
            == staged.package_content_digest
            and admission.candidate.dependency_lock_digest
            == staged.dependency_lock_digest
            and admission.candidate.package_source_identity
            == staged.package_source_identity
            for admission in (
                replacement_inputs.product_composition.catalog_admissions
            )
        )
        owner_registrations = {
            (item.surface, item.public_key, item.owner_id)
            for item in replacement.get_effective_runtime_view().registrations
            if item.surface in {"tool", "session_command_pack"}
        }
        assert (
            "session_command_pack",
            "harness.session.standard",
            "commands.session",
        ) in owner_registrations
        assert (
            "tool",
            "bash",
            "tools.workspace",
        ) in owner_registrations
        await replacement.dispose()
        retired = lifecycle.instances.snapshot().instance(old_ref)
        assert retired is not None
        assert retired.state == "RETIRED"

    asyncio.run(scenario())


def test_public_session_dispose_then_resume_reacquires_a_fresh_live_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        await first_manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="resume lifecycle")],
                timestamp=0.0,
            )
        )
        session_file = first_manager.get_session_file()
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await first.prepare_model_call_runtime()
        first_base = first._coding_base_plugin_assembly
        assert first_base is not None
        first_lease = first_base.management_lease
        assert first_lease is not None
        first_family_id = first_lease.family.family_id
        selected_ref = first_lease.instance_revision_ref
        await first.dispose()

        resumed_manager = await SessionManager.load(session_file)
        assert (
            resumed_manager.get_header().conversation_id
            == first_manager.get_header().conversation_id
        )
        resumed = create_agent_session(
            session_manager=resumed_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        resumed_base = resumed._coding_base_plugin_assembly
        assert resumed_base is not None
        resumed_lease = resumed_base.management_lease
        assert resumed_lease is not None
        assert resumed_lease.instance_revision_ref == selected_ref
        assert resumed_lease.family.family_id != first_family_id
        await resumed.prepare_model_call_runtime()
        assert resumed.get_tool_definition("bash") is not None
        assert len(resumed._capability_owner_generations) >= 2
        resumed_inputs = resumed._capability_composition_inputs
        assert resumed_inputs is not None
        selected_package = resumed_lease.package_revision
        assert all(
            admission.candidate.instance_revision_ref == selected_ref
            and admission.candidate.package_content_digest
            == selected_package.package_content_digest
            and admission.candidate.dependency_lock_digest
            == selected_package.dependency_lock_digest
            and admission.candidate.package_source_identity
            == selected_package.package_source_identity
            for admission in resumed_inputs.product_composition.catalog_admissions
        )
        await resumed.dispose()

    asyncio.run(scenario())


def test_production_bootstrap_disable_keeps_active_generation_and_omits_new_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assert active._coding_base_plugin_assembly is not None
        active_lease = active._coding_base_plugin_assembly.management_lease
        assert active_lease is not None
        active_ref = active_lease.instance_revision_ref
        active_family_id = active_lease.family.family_id
        before_tools = tuple(active.get_active_tool_names())

        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action="disable")
        with pytest.raises(
            CodingBasePluginAssemblyError,
            match="requires restart",
        ):
            await active.refresh_resources()
        records = [
            item
            for item in active.get_session_diagnostics()
            if item.code == "coding_base_management_restart_required"
        ]
        assert len(records) == 1
        assert records[0].details["restartRequired"] is True
        assert records[0].details["reason"] == "plugin_disabled"
        assert tuple(active.get_active_tool_names()) == before_tools
        assert active._coding_base_plugin_assembly.package.revision_handle.closed is False

        second_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        replacement = create_agent_session(
            session_manager=second_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        assert replacement._coding_base_plugin_assembly is None
        assert replacement._capability_composition_inputs is None
        assert "Use tools as needed" not in replacement.agent.system_prompt
        await replacement.prepare_model_call_runtime()
        assert {"bash", "read", "write"}.isdisjoint(
            replacement.get_active_tool_names()
        )
        await replacement.dispose()
        await active.dispose()
        retired = lifecycle.instances.snapshot().instance(active_ref)
        assert retired is not None
        assert retired.state == "RETIRED"
        [intent] = lifecycle.management_retirement_intents()
        retirement_set = lifecycle.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert retirement_set is not None
        assert retirement_set.state == "succeeded"
        assert retirement_set.plan is not None
        assert len(retirement_set.plan.targets) == 3
        assert {
            target.contribution_ids for target in retirement_set.plan.targets
        } == {
            ("coding.builtin",),
            ("coding.standard",),
            ("prompt-standard", "skill-standard"),
        }
        assert all(
            outcome.owner_outcome_reference
            == f"coding-session-disposed:{active_family_id}"
            for outcome in retirement_set.latest_outcomes
        )

    asyncio.run(scenario())


def test_retirement_preserves_distinct_exact_generations_for_two_live_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import Counter

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        )
        sessions = []
        for sequence in (1, 2):
            manager = await SessionManager.new(
                session_dir=tmp_path / "sessions",
                cwd=str(workspace),
                persist=True,
            )
            session = create_agent_session(
                session_manager=manager,
                model=_model(),
                services=services,
            )
            await session.prepare_model_call_runtime()
            sessions.append(session)

        leases = tuple(
            session._coding_base_plugin_assembly.management_lease
            for session in sessions
            if session._coding_base_plugin_assembly is not None
        )
        assert len(leases) == 2
        assert all(lease is not None for lease in leases)
        first_lease, second_lease = leases
        assert first_lease is not None
        assert second_lease is not None
        assert first_lease.instance_revision_ref == second_lease.instance_revision_ref
        assert first_lease.family.family_id != second_lease.family.family_id
        selected_ref = first_lease.instance_revision_ref

        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action="disable")
        lifecycle.reconcile_retirements()

        await sessions[0].dispose()
        draining = lifecycle.instances.snapshot().instance(selected_ref)
        assert draining is not None
        assert draining.state == "DRAINING"
        [intent] = lifecycle.management_retirement_intents()
        collecting = lifecycle.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert collecting is not None
        assert collecting.plan is None

        await sessions[1].dispose()
        retired = lifecycle.instances.snapshot().instance(selected_ref)
        assert retired is not None
        assert retired.state == "RETIRED"
        completed = lifecycle.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert completed is not None
        assert completed.state == "succeeded"
        assert completed.plan is not None
        assert len(completed.plan.targets) == 6
        assert Counter(
            target.contribution_ids for target in completed.plan.targets
        ) == Counter(
            {
                ("coding.builtin",): 2,
                ("coding.standard",): 2,
                ("prompt-standard", "skill-standard"): 2,
            }
        )
        assert len(
            {
                (
                    target.owner_reference,
                    target.owner_generation_reference,
                    target.retirement_handle,
                )
                for target in completed.plan.targets
            }
        ) == 6
        assert {
            outcome.owner_outcome_reference
            for outcome in completed.latest_outcomes
        } == {
            f"coding-session-disposed:{first_lease.family.family_id}",
            f"coding-session-disposed:{second_lease.family.family_id}",
        }

    asyncio.run(scenario())


@pytest.mark.parametrize("owner_id", ["commands.session", "tools.workspace"])
def test_owner_cleanup_failure_keeps_session_family_retryable_until_exact_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_id: str,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assembly = active._coding_base_plugin_assembly
        assert assembly is not None
        lease = assembly.management_lease
        assert lease is not None
        family_id = lease.family.family_id
        ref = lease.instance_revision_ref
        tool_generation = next(
            generation
            for generation in active._capability_owner_generations
            if generation.binding.plugin_id == "coding.base"
            and generation.binding.owner_id == owner_id
        )
        registration_scope = tool_generation.value.scope
        failing_lease = registration_scope._leases[0]
        original_disposer = failing_lease._dispose
        assert original_disposer is not None
        attempts = 0

        def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient exact owner cleanup failure")
            return original_disposer()

        failing_lease._dispose = fail_once
        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action="disable")
        lifecycle.reconcile_retirements()

        with pytest.raises(
            RuntimeError,
            match="generation disposal remains incomplete",
        ):
            await active.dispose()

        evidence = lifecycle.owner_evidence.family(family_id)
        assert evidence is not None
        assert evidence.retired is False
        draining = lifecycle.instances.snapshot().instance(ref)
        assert draining is not None
        assert draining.state == "DRAINING"
        assert family_id in draining.open_family_ids
        [intent] = lifecycle.management_retirement_intents()
        collecting = lifecycle.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert collecting is not None
        assert collecting.plan is None

        await active.dispose()

        assert attempts == 2
        evidence = lifecycle.owner_evidence.family(family_id)
        assert evidence is not None
        assert evidence.retired is True
        retired = lifecycle.instances.snapshot().instance(ref)
        assert retired is not None
        assert retired.state == "RETIRED"
        completed = lifecycle.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert completed is not None
        assert completed.state == "succeeded"
        assert completed.plan is not None
        assert len(completed.plan.targets) == 3

    asyncio.run(scenario())


def test_management_family_close_failure_retries_after_host_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assembly = active._coding_base_plugin_assembly
        assert assembly is not None
        management_lease = assembly.management_lease
        assert management_lease is not None
        family_id = management_lease.family.family_id
        selected_ref = management_lease.instance_revision_ref
        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action="disable")
        lifecycle.reconcile_retirements()

        original_close = type(management_lease).close
        attempts = 0

        def fail_once(candidate) -> None:
            nonlocal attempts
            if candidate is management_lease:
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("transient family close failure")
            original_close(candidate)

        monkeypatch.setattr(type(management_lease), "close", fail_once)

        with pytest.raises(RuntimeError, match="transient family close failure"):
            await active.dispose()

        evidence = lifecycle.owner_evidence.family(family_id)
        assert evidence is not None
        assert evidence.retired is True
        draining = lifecycle.instances.snapshot().instance(selected_ref)
        assert draining is not None
        assert draining.state == "DRAINING"
        assert family_id in draining.open_family_ids
        assert assembly._closed is False
        assert assembly._runtime_closed is True
        assert assembly._management_released is False
        assert assembly._state_cleaned is False
        assert assembly.package.revision_handle.closed is True

        await active.dispose()

        assert attempts == 2
        assert assembly._closed is True
        assert assembly._management_released is True
        assert assembly._state_cleaned is True
        retired = lifecycle.instances.snapshot().instance(selected_ref)
        assert retired is not None
        assert retired.state == "RETIRED"

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_phase", ("runtime", "state"))
def test_cleanup_failure_orders_runtime_before_and_state_after_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assembly = active._coding_base_plugin_assembly
        assert assembly is not None
        management_lease = assembly.management_lease
        assert management_lease is not None
        lifecycle = management_lease.lifecycle
        selected_ref = management_lease.instance_revision_ref
        _disable_or_remove(lifecycle, action="disable")
        lifecycle.reconcile_retirements()
        attempts = 0

        if failure_phase == "runtime":
            original_close = type(assembly.runtime).close

            def fail_runtime_once(candidate) -> None:
                nonlocal attempts
                if candidate is assembly.runtime:
                    attempts += 1
                    if attempts == 1:
                        raise RuntimeError("transient package runtime cleanup failure")
                original_close(candidate)

            monkeypatch.setattr(type(assembly.runtime), "close", fail_runtime_once)
            expected = "transient package runtime cleanup failure"
        else:

            def fail_state_once() -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("transient package state cleanup failure")

            assembly.state_cleanup = fail_state_once
            assembly._state_cleaned = False
            expected = "transient package state cleanup failure"

        with pytest.raises(RuntimeError, match=expected):
            await active.dispose()

        interrupted = lifecycle.instances.snapshot().instance(selected_ref)
        assert interrupted is not None
        if failure_phase == "runtime":
            assert interrupted.state == "DRAINING"
            assert management_lease.family.family_id in interrupted.open_family_ids
            assert assembly._management_released is False
            assert lifecycle.packages.snapshot().cleanup_tasks == ()
        else:
            assert interrupted.state == "RETIRED"
            assert management_lease.family.family_id not in interrupted.open_family_ids
            assert assembly._management_released is True
            [cleanup] = lifecycle.packages.snapshot().cleanup_tasks
            assert cleanup.state == "succeeded"

        await active.dispose()

        assert attempts == 2
        retired = lifecycle.instances.snapshot().instance(selected_ref)
        assert retired is not None
        assert retired.state == "RETIRED"
        [cleanup] = lifecycle.packages.snapshot().cleanup_tasks
        assert cleanup.state == "succeeded"

    asyncio.run(scenario())


def test_ephemeral_public_session_releases_family_before_removing_state_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loushang.coding.bootstrap as bootstrap_module
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original_temporary_cleanup = bootstrap_module.TemporaryDirectory.cleanup

    def cleanup_only_after_startup_lease_release(temporary_state) -> None:
        temporary_root = Path(temporary_state.name)
        with plugin_lifecycle_module._PROCESS_STARTUP_LEASES_LOCK:
            assert all(
                not lease_path.is_relative_to(temporary_root)
                for lease_path in plugin_lifecycle_module._PROCESS_STARTUP_LEASES
            )
        original_temporary_cleanup(temporary_state)

    monkeypatch.setattr(
        bootstrap_module.TemporaryDirectory,
        "cleanup",
        cleanup_only_after_startup_lease_release,
    )

    async def scenario() -> None:
        with plugin_lifecycle_module._PROCESS_STARTUP_LEASES_LOCK:
            original_lease_count = len(
                plugin_lifecycle_module._PROCESS_STARTUP_LEASES
            )

        for sequence in range(3):
            manager = await SessionManager.new(
                session_dir=tmp_path / f"sessions-{sequence}",
                cwd=str(workspace),
                persist=False,
            )
            session = create_agent_session(
                session_manager=manager,
                model=_model(),
                services=create_services(
                    settings_manager=SettingsManager(
                        ControlConfig(capabilities={"coding.lsp": "disabled"})
                    )
                ),
            )
            await session.prepare_model_call_runtime()
            assembly = session._coding_base_plugin_assembly
            assert assembly is not None
            lease = assembly.management_lease
            assert lease is not None
            lifecycle = lease.lifecycle
            ephemeral_root = lifecycle.layout.root
            startup_lease_path = plugin_lifecycle_module._startup_lease_path(
                lifecycle.layout,
                startup_id=lifecycle.startup_id,
            )
            assert ephemeral_root.exists()
            with plugin_lifecycle_module._PROCESS_STARTUP_LEASES_LOCK:
                assert startup_lease_path in (
                    plugin_lifecycle_module._PROCESS_STARTUP_LEASES
                )

            await session.dispose()

            assert assembly._closed is True
            assert assembly._runtime_closed is True
            assert assembly._management_released is True
            assert assembly._state_cleaned is True
            assert ephemeral_root.exists() is False
            with plugin_lifecycle_module._PROCESS_STARTUP_LEASES_LOCK:
                assert startup_lease_path not in (
                    plugin_lifecycle_module._PROCESS_STARTUP_LEASES
                )
                assert (
                    len(plugin_lifecycle_module._PROCESS_STARTUP_LEASES)
                    == original_lease_count
                )

    asyncio.run(scenario())


def test_owner_evidence_publication_failure_retries_before_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        assembly = active._coding_base_plugin_assembly
        assert assembly is not None
        management_lease = assembly.management_lease
        assert management_lease is not None
        original_publish = type(management_lease).publish_owner_generations
        attempts = 0

        def fail_once(candidate, receipts) -> None:
            nonlocal attempts
            if candidate is management_lease:
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("transient owner evidence publication failure")
            original_publish(candidate, receipts)

        monkeypatch.setattr(
            type(management_lease),
            "publish_owner_generations",
            fail_once,
        )

        with pytest.raises(
            RuntimeError,
            match="transient owner evidence publication failure",
        ):
            await active.prepare_model_call_runtime()

        assert active._coding_base_owner_retirement_receipts
        assert active._coding_base_owner_generations_published is False
        prepared = management_lease.lifecycle.owner_evidence.family(
            management_lease.family.family_id
        )
        assert prepared is not None
        assert prepared.publication_state == "prepared"

        await active.prepare_model_call_runtime()

        assert attempts == 2
        assert active._coding_base_owner_generations_published is True
        evidence = management_lease.lifecycle.owner_evidence.family(
            management_lease.family.family_id
        )
        assert evidence is not None
        assert evidence.retired is False
        assert evidence.publication_state == "published"
        await active.dispose()
        retired = management_lease.lifecycle.owner_evidence.family(
            management_lease.family.family_id
        )
        assert retired is not None
        assert retired.retired is True

    asyncio.run(scenario())


def test_reconciliation_resumes_after_plan_commit_before_owner_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.plugin_management import PluginRetirementSetLedger

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assembly = active._coding_base_plugin_assembly
        assert assembly is not None
        management_lease = assembly.management_lease
        assert management_lease is not None
        lifecycle = management_lease.lifecycle
        selected_ref = management_lease.instance_revision_ref

        observer = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(observer, action="disable")
        observer.reconcile_retirements()

        original_record_outcome = PluginRetirementSetLedger.record_outcome
        attempts = 0

        def fail_once(candidate, outcome):
            nonlocal attempts
            attempts += 1
            if candidate is lifecycle.retirement_sets and attempts == 1:
                raise RuntimeError("crash after exact plan commit")
            return original_record_outcome(candidate, outcome)

        monkeypatch.setattr(
            PluginRetirementSetLedger,
            "record_outcome",
            fail_once,
        )

        with pytest.raises(RuntimeError, match="crash after exact plan commit"):
            await active.dispose()

        [intent] = observer.management_retirement_intents()
        interrupted = observer.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert interrupted is not None
        assert interrupted.state == "retiring"
        assert interrupted.plan is not None
        assert len(interrupted.plan.targets) == 3
        assert interrupted.latest_outcomes == ()
        draining = observer.instances.snapshot().instance(selected_ref)
        assert draining is not None
        assert draining.state == "DRAINING"

        recovered = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        recovered.reconcile_retirements()
        assert attempts == 4
        completed = recovered.retirement_sets.snapshot().retirement_set(
            intent.retirement_id
        )
        assert completed is not None
        assert completed.state == "succeeded"
        assert len(completed.latest_outcomes) == 3
        retired = recovered.instances.snapshot().instance(selected_ref)
        assert retired is not None
        assert retired.state == "RETIRED"
        await active.dispose()

    asyncio.run(scenario())


def test_reconciliation_resumes_after_direct_host_handoff_released_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.plugin_management import PluginPackageLifecycleLedger

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assembly = active._coding_base_plugin_assembly
        assert assembly is not None
        management_lease = assembly.management_lease
        assert management_lease is not None
        lifecycle = management_lease.lifecycle
        selected_ref = management_lease.instance_revision_ref
        observer = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(observer, action="disable")
        observer.reconcile_retirements()

        original_handoff = PluginPackageLifecycleLedger.handoff_cleanup_and_release
        crashed = False

        def crash_after_handoff(candidate, *args, **kwargs):
            nonlocal crashed
            task = original_handoff(candidate, *args, **kwargs)
            if candidate is lifecycle.packages and not crashed:
                crashed = True
                raise RuntimeError("crash after direct-host handoff")
            return task

        monkeypatch.setattr(
            PluginPackageLifecycleLedger,
            "handoff_cleanup_and_release",
            crash_after_handoff,
        )

        with pytest.raises(RuntimeError, match="crash after direct-host handoff"):
            await active.dispose()

        interrupted = observer.instances.snapshot().instance(selected_ref)
        assert interrupted is not None
        assert interrupted.state == "DRAINING"
        assert interrupted.open_family_ids == ()
        [cleanup] = observer.packages.snapshot().cleanup_tasks
        assert cleanup.state == "pending"
        assert cleanup.task.source_family.lease_kind == "direct_host"

        recovered = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        recovered.reconcile_retirements()

        retired = recovered.instances.snapshot().instance(selected_ref)
        assert retired is not None
        assert retired.state == "RETIRED"
        [completed_cleanup] = recovered.packages.snapshot().cleanup_tasks
        assert completed_cleanup.state == "succeeded"
        await active.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ("disable", "remove"))
def test_production_bootstrap_preserves_lsp_only_when_base_is_unselected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.lsp import (
        DOCUMENT_OUTLINE_TOOL_NAME,
        INSPECT_SYMBOL_TOOL_NAME,
        LspServerDefinition,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.sandbox import SandboxSettings

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").touch()
    (workspace / "main.py").write_text(
        "target = 1\nprint(target)\n",
        encoding="utf-8",
    )
    method_log = workspace / "lsp-methods.log"
    fake_lsp_server = (
        Path(__file__).parent / "lsp" / "fixtures" / "fake_lsp_server.py"
    )
    session_dir = tmp_path / "sessions"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        assert first._coding_base_plugin_assembly is not None
        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action=action)
        await first.dispose()

        replacement_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        replacement = create_agent_session(
            session_manager=replacement_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={"coding.lsp": "always"},
                        sandbox=SandboxSettings(enabled=False),
                    )
                )
            ),
            lsp_definitions=(
                LspServerDefinition(
                    id="python-test",
                    command=(sys.executable, str(fake_lsp_server)),
                    language_extensions={"python": (".py",)},
                    root_markers=("pyproject.toml",),
                    environment={"LOUSHANG_FAKE_LSP_LOG": str(method_log)},
                    startup_timeout_seconds=3,
                    request_timeout_seconds=3,
                    shutdown_timeout_seconds=3,
                ),
            ),
        )
        assert replacement._coding_base_plugin_assembly is None
        lsp_assembly = replacement._coding_lsp_plugin_assembly
        assert lsp_assembly is not None
        assert lsp_assembly.selection.plan.selected_plugin_ids == (
            "coding.lsp.default",
        )
        inputs = replacement._capability_composition_inputs
        assert inputs is not None
        assert {
            (item.plugin_id, item.contribution_id)
            for item in inputs.product_composition.catalog_admissions
        } == {("coding.lsp.default", "coding-lsp-tools")}
        assert "Use tools as needed" not in replacement.agent.system_prompt

        await replacement.prepare_model_call_runtime()

        active_tools = set(replacement.get_active_tool_names())
        assert {DOCUMENT_OUTLINE_TOOL_NAME, INSPECT_SYMBOL_TOOL_NAME}.issubset(
            active_tools
        )
        assert {"bash", "edit", "find", "grep", "ls", "read", "write"}.isdisjoint(
            active_tools
        )
        assert "session" not in {item.name for item in replacement.list_commands()}
        assert len(replacement._capability_owner_generations) == 1
        registrations = replacement.get_effective_runtime_view().registrations
        assert {
            (item.surface, item.public_key)
            for item in registrations
            if item.surface in {"tool", "session_command_pack"}
        } == {
            ("tool", DOCUMENT_OUTLINE_TOOL_NAME),
            ("tool", INSPECT_SYMBOL_TOOL_NAME),
        }
        materialized = {tool.name: tool for tool in replacement.agent.tools}
        result = await materialized[INSPECT_SYMBOL_TOOL_NAME].execute(
            f"lsp-only-{action}",
            {"path": "main.py", "line": 2, "character": 7},
        )
        assert result.details["server_id"] == "python-test"
        assert result.details["count"] == 1
        assert result.details["items"][0]["path"] == "main.py"
        await replacement.dispose()
        assert replacement._capability_owner_generations == ()
        assert method_log.read_text(encoding="utf-8").splitlines() == [
            "initialize",
            "initialized",
            "textDocument/didOpen",
            "textDocument/definition",
            "shutdown",
            "exit",
        ]

    asyncio.run(scenario())
