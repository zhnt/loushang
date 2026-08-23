from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateLedger,
    PluginLifecycleError,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredSelectionV1,
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginLifecycleCodecError,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def test_plc2_value_records_have_strict_round_trip_wires() -> None:
    package = _package()
    key = _key()
    instance = PluginInstanceRevisionRef(
        instance_id="instance-1",
        plugin_id=key.plugin_id,
        revision=1,
    )
    selection = PluginDesiredSelectionV1(
        desired_state="installed_enabled",
        package_revision=package,
        instance_revision_ref=instance,
    )
    state = PluginInstallationStateV1(
        installation_key=key,
        selection=selection,
        latest_instance_revision_ref=instance,
    )
    mutation = _mutation(
        revision=0,
        state="installed_enabled",
        package=package,
    )
    transition = PluginDesiredStateTransitionV1(
        inventory_revision=1,
        transition_kind="install",
        mutation=mutation,
        previous_state=PluginInstallationStateV1.initial(key),
        committed_state=state,
    )

    values = (
        (PluginPackageRevisionRefV1, package),
        (PluginInstallationKeyV1, key),
        (PluginDesiredSelectionV1, selection),
        (PluginInstallationStateV1, state),
        (PluginDesiredStateMutationV1, mutation),
        (PluginDesiredStateTransitionV1, transition),
    )
    for record_type, value in values:
        assert record_type.from_dict(value.to_dict()) == value

    assert package.to_dict() == {
        "dependencyLockDigest": "2" * 64,
        "packageContentDigest": "1" * 64,
        "packageSourceIdentity": "embedded:coding.base",
        "pluginId": "coding.base",
        "pluginVersion": "1.0.0",
        "schemaVersion": 1,
    }
    assert mutation.to_dict()["approvalReference"] is None
    assert "instanceRevisionRef" not in mutation.to_dict()
    assert len(mutation.digest) == 64


@pytest.mark.parametrize(
    ("decoder", "document_factory", "version_field"),
    [
        (
            PluginPackageRevisionRefV1.from_dict,
            lambda: _package().to_dict(),
            "schemaVersion",
        ),
        (
            PluginInstallationKeyV1.from_dict,
            lambda: _key().to_dict(),
            "schemaVersion",
        ),
        (
            PluginDesiredSelectionV1.from_dict,
            lambda: PluginDesiredSelectionV1.absent().to_dict(),
            "schemaVersion",
        ),
        (
            PluginInstallationStateV1.from_dict,
            lambda: PluginInstallationStateV1.initial(_key()).to_dict(),
            "schemaVersion",
        ),
        (
            PluginDesiredStateMutationV1.from_dict,
            lambda: _mutation(revision=0, state="absent").to_dict(),
            "schemaVersion",
        ),
        (
            PluginDesiredStateTransitionV1.from_dict,
            lambda: _transition().to_dict(),
            "recordVersion",
        ),
    ],
)
def test_plc2_value_records_reject_unknown_fields_and_versions(
    decoder: Callable[[object], object],
    document_factory: Callable[[], dict[str, object]],
    version_field: str,
) -> None:
    document = document_factory()
    unknown = {**document, "unknown": True}
    with pytest.raises(PluginLifecycleCodecError) as caught:
        decoder(unknown)
    assert caught.value.code == "invalid_plugin_lifecycle_record"

    unsupported = {**document, version_field: 2}
    with pytest.raises(PluginLifecycleCodecError) as caught:
        decoder(unsupported)
    assert caught.value.code == "unsupported_plugin_lifecycle_record_version"


def test_ledger_issues_and_replays_installation_epoch_instance_lineage(
    tmp_path: Path,
) -> None:
    issued = iter(("instance-epoch-1", "instance-epoch-2"))
    path = tmp_path / "plugin-desired-state.jsonl"
    ledger = PluginDesiredStateLedger(path, instance_id_factory=lambda: next(issued))
    package = _package()

    assert ledger.snapshot().inventory_revision == 0
    install = ledger.commit(
        _mutation(revision=0, state="installed_disabled", package=package)
    )
    assert install.transition_kind == "install"
    assert install.committed_state.latest_instance_revision_ref is None

    enable = ledger.commit(_mutation(revision=1, state="installed_enabled"))
    first = enable.committed_state.latest_instance_revision_ref
    assert enable.transition_kind == "enable"
    assert first == PluginInstanceRevisionRef(
        instance_id="instance-epoch-1",
        plugin_id="coding.base",
        revision=1,
    )

    disable = ledger.commit(_mutation(revision=2, state="installed_disabled"))
    assert disable.transition_kind == "disable"
    assert disable.committed_state.selection.instance_revision_ref is None
    assert disable.committed_state.latest_instance_revision_ref == first

    reenable = ledger.commit(_mutation(revision=3, state="installed_enabled"))
    second = reenable.committed_state.latest_instance_revision_ref
    assert second == replace(first, revision=2)

    remove = ledger.commit(_mutation(revision=4, state="absent"))
    assert remove.transition_kind == "remove"
    assert remove.committed_state.selection == PluginDesiredSelectionV1.absent()
    assert remove.committed_state.latest_instance_revision_ref == second
    assert remove.previous_state.selection.package_revision == package

    reinstall = ledger.commit(
        _mutation(revision=5, state="installed_disabled", package=package)
    )
    assert reinstall.committed_state.latest_instance_revision_ref is None
    reenable_new_epoch = ledger.commit(_mutation(revision=6, state="installed_enabled"))
    assert reenable_new_epoch.committed_state.latest_instance_revision_ref == (
        PluginInstanceRevisionRef(
            instance_id="instance-epoch-2",
            plugin_id="coding.base",
            revision=1,
        )
    )

    reopened = PluginDesiredStateLedger(path)
    snapshot = reopened.snapshot()
    assert snapshot.inventory_revision == 7
    assert snapshot.installation(_key()) == reenable_new_epoch.committed_state
    assert reopened.transitions() == ledger.transitions()


def test_ledger_exact_retry_is_stable_and_conflicts_fail_before_append(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plugin-desired-state.jsonl"
    factory_calls = 0

    def issue() -> str:
        nonlocal factory_calls
        factory_calls += 1
        return "instance-1"

    ledger = PluginDesiredStateLedger(path, instance_id_factory=issue)
    mutation = _mutation(
        revision=0,
        state="installed_enabled",
        package=_package(),
    )
    committed = ledger.commit(mutation)
    first_bytes = path.read_bytes()

    assert ledger.commit(mutation) == committed
    assert path.read_bytes() == first_bytes
    assert factory_calls == 1

    with pytest.raises(PluginLifecycleError) as caught:
        ledger.commit(replace(mutation, operation_id="operation-other"))
    assert caught.value.code == "plugin_management_idempotency_conflict"
    assert path.read_bytes() == first_bytes

    with pytest.raises(PluginLifecycleError) as caught:
        ledger.commit(replace(mutation, idempotency_key="request-other"))
    assert caught.value.code == "plugin_management_operation_conflict"
    assert path.read_bytes() == first_bytes

    stale = _mutation(
        revision=0,
        state="installed_enabled",
        package=_package(),
        operation=2,
    )
    with pytest.raises(PluginLifecycleError) as caught:
        ledger.commit(stale)
    assert caught.value.code == "plugin_inventory_revision_conflict"
    assert factory_calls == 1
    assert path.read_bytes() == first_bytes


def test_two_ledger_instances_linearize_one_shared_expected_revision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plugin-desired-state.jsonl"
    barrier = Barrier(2)

    def commit(operation: int) -> object:
        barrier.wait()
        return PluginDesiredStateLedger(path).commit(
            _mutation(
                revision=0,
                state="absent",
                operation=operation,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(commit, operation) for operation in (1, 2))
        outcomes: list[object] = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except PluginLifecycleError as exc:
                outcomes.append(exc)

    transitions = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, PluginDesiredStateTransitionV1)
    ]
    failures = [
        outcome for outcome in outcomes if isinstance(outcome, PluginLifecycleError)
    ]
    assert len(transitions) == 1
    assert len(failures) == 1
    assert failures[0].code == "plugin_inventory_revision_conflict"
    assert PluginDesiredStateLedger(path).snapshot().inventory_revision == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_ledger_rejects_unstaged_package_change_and_identity_reuse(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plugin-desired-state.jsonl"
    ledger = PluginDesiredStateLedger(
        path,
        instance_id_factory=lambda: "same-instance",
    )
    ledger.commit(_mutation(revision=0, state="installed_enabled", package=_package()))
    committed_bytes = path.read_bytes()

    with pytest.raises(PluginLifecycleError) as caught:
        ledger.commit(
            _mutation(
                revision=1,
                state="installed_enabled",
                package=replace(_package(), package_content_digest="3" * 64),
                operation=2,
            )
        )
    assert caught.value.code == "plugin_update_requires_staging"
    assert path.read_bytes() == committed_bytes

    ledger.commit(_mutation(revision=1, state="absent", operation=3))
    with pytest.raises(PluginLifecycleError) as caught:
        ledger.commit(
            _mutation(
                revision=2,
                state="installed_enabled",
                package=_package(),
                operation=4,
            )
        )
    assert caught.value.code == "plugin_instance_identity_conflict"
    assert ledger.snapshot().inventory_revision == 2


def test_ledger_repairs_only_incomplete_tail_and_fails_closed_on_chain_corruption(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plugin-desired-state.jsonl"
    ledger = PluginDesiredStateLedger(path)
    transition = ledger.commit(_mutation(revision=0, state="absent"))
    committed_bytes = path.read_bytes()

    with path.open("ab") as handle:
        handle.write(b'{"recordVersion":')
    assert ledger.snapshot().inventory_revision == 1
    assert path.read_bytes() == committed_bytes

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(transition.to_dict(), sort_keys=True) + "\n")
    with pytest.raises(PluginLifecycleError) as caught:
        PluginDesiredStateLedger(path).snapshot()
    assert caught.value.code == "plugin_lifecycle_journal_corrupt"


def _package() -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version="1.0.0",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.base",
    )


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="coding.base",
    )


def _mutation(
    *,
    revision: int,
    state: str,
    package: PluginPackageRevisionRefV1 | None = None,
    operation: int | None = None,
) -> PluginDesiredStateMutationV1:
    sequence = revision + 1 if operation is None else operation
    return PluginDesiredStateMutationV1(
        operation_id=f"operation-{sequence}",
        idempotency_key=f"request-{sequence}",
        expected_inventory_revision=revision,
        installation_key=_key(),
        desired_state=state,  # type: ignore[arg-type]
        package_revision=package,
        actor_id="operator-1",
        policy_revision="policy-1",
    )


def _transition() -> PluginDesiredStateTransitionV1:
    mutation = _mutation(revision=0, state="installed_disabled", package=_package())
    return PluginDesiredStateTransitionV1(
        inventory_revision=1,
        transition_kind="install",
        mutation=mutation,
        previous_state=PluginInstallationStateV1.initial(_key()),
        committed_state=PluginInstallationStateV1(
            installation_key=_key(),
            selection=PluginDesiredSelectionV1(
                desired_state="installed_disabled",
                package_revision=_package(),
                instance_revision_ref=None,
            ),
            latest_instance_revision_ref=None,
        ),
    )
