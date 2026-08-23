from __future__ import annotations

from loushang.harness.plugin_authoring.import_realm import (
    PluginImportRealm,
    PluginImportRealmError,
)

from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
)


def test_import_realm_commits_one_compatible_locked_closure() -> None:
    realm = PluginImportRealm(import_realm_id_factory=lambda: "1" * 32)
    dependency_lock = _lock(("example-runtime", "1.0"))

    realm.preflight(
        host_boot_id="2" * 32,
        dependency_lock=dependency_lock,
    )
    lease = realm.reserve(
        host_boot_id="2" * 32,
        execution_use_id="3" * 48,
        dependency_lock=dependency_lock,
    )
    result = realm.execute(lease, lambda: "evaluated")
    realm.commit(lease)

    assert result == "evaluated"
    assert realm.snapshot().to_dict() == {
        "activeExecutionUseId": None,
        "hostBootId": "2" * 32,
        "importRealmId": "1" * 32,
        "lockedDistributions": [
            {"name": "example-runtime", "version": "1.0"},
        ],
        "state": "clean",
    }


def test_import_realm_rejects_busy_and_conflicting_closures() -> None:
    realm = PluginImportRealm(import_realm_id_factory=lambda: "1" * 32)
    first_lock = _lock(("example-runtime", "1.0"))
    first = realm.reserve(
        host_boot_id="2" * 32,
        execution_use_id="3" * 48,
        dependency_lock=first_lock,
    )

    try:
        realm.preflight(
            host_boot_id="2" * 32,
            dependency_lock=first_lock,
        )
    except PluginImportRealmError as exc:
        assert exc.code == "plugin_import_realm_busy"
    else:
        raise AssertionError("busy import realm was accepted")
    realm.cancel(first)

    committed = realm.reserve(
        host_boot_id="2" * 32,
        execution_use_id="4" * 48,
        dependency_lock=first_lock,
    )
    realm.execute(committed, lambda: None)
    realm.commit(committed)

    try:
        realm.preflight(
            host_boot_id="2" * 32,
            dependency_lock=_lock(("example-runtime", "2.0")),
        )
    except PluginImportRealmError as exc:
        assert exc.code == "plugin_import_dependency_conflict"
    else:
        raise AssertionError("conflicting dependency closure was accepted")


def test_import_exception_pollutes_realm_and_blocks_new_reservations() -> None:
    realm = PluginImportRealm(import_realm_id_factory=lambda: "1" * 32)
    dependency_lock = _lock()
    lease = realm.reserve(
        host_boot_id="2" * 32,
        execution_use_id="3" * 48,
        dependency_lock=dependency_lock,
    )

    try:
        realm.execute(lease, _raise_definition_failure)
    except RuntimeError as exc:
        assert str(exc) == "definition secret detail"
    else:
        raise AssertionError("definition failure was swallowed")

    snapshot = realm.snapshot()
    assert snapshot.state == "polluted"
    assert snapshot.active_execution_use_id is None
    try:
        realm.preflight(
            host_boot_id="2" * 32,
            dependency_lock=dependency_lock,
        )
    except PluginImportRealmError as exc:
        assert exc.code == "plugin_import_realm_polluted"
    else:
        raise AssertionError("polluted import realm was accepted")


def _lock(
    *distributions: tuple[str, str],
) -> PluginDependencyClosureLock:
    return PluginDependencyClosureLock(
        package_content_digest="4" * 64,
        python_distributions=tuple(
            PluginPythonDistributionLock(name=name, version=version)
            for name, version in distributions
        ),
    )


def _raise_definition_failure() -> None:
    raise RuntimeError("definition secret detail")
