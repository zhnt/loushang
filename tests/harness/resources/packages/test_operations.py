from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
)
from loushang.harness.resources.packages.operations import (
    PackageOperationsRuntime,
    PackageResourceRefreshOutcome,
    PackageResourceRefreshTransaction,
)
from loushang.harness.resources.packages.settings_mutation import (
    PackageSourceSettingsMutation,
)


class _Materializer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.materialized: list[str] = []
        self.updated: list[str] = []
        self.update_all_calls = 0
        self.removed: list[str] = []
        self.forgotten: list[str] = []
        self.materialize_result: PackageMaterializationRecord | None = None
        self.remove_result: PackageMaterializationRecord | None = None

    async def materialize_remote_source(
        self, source: str
    ) -> PackageMaterializationRecord:
        self.materialized.append(source)
        return self.materialize_result or self._record(source, "installed")

    async def update_remote_source(self, source: str) -> PackageMaterializationRecord:
        self.updated.append(source)
        return self._record(source, "installed")

    async def update_all_remote_sources(self) -> list[PackageMaterializationRecord]:
        self.update_all_calls += 1
        return [self._record("https://example.test/all.git", "installed")]

    def remove_remote_source(self, source: str) -> PackageMaterializationRecord:
        self.removed.append(source)
        return self.remove_result or self._record(source, "remote_registered")

    def forget_remote_source(self, source: str) -> None:
        self.forgotten.append(source)

    def _record(self, source: str, lifecycle: str) -> PackageMaterializationRecord:
        return PackageMaterializationRecord(
            source=source,
            name="pack",
            lifecycle=lifecycle,  # type: ignore[arg-type]
            target_path=self.root / "pack",
        )


def _runtime(
    materializer: _Materializer | None,
    *,
    calls: list[str],
) -> PackageOperationsRuntime:
    def refresh() -> None:
        calls.append("refresh")

    async def prepare() -> None:
        calls.append("prepare")

    def add_source(source: str, scope: str) -> PackageSourceSettingsMutation:
        calls.append(f"add:{scope}:{source}")
        return PackageSourceSettingsMutation(
            source=source,
            scope=scope,
            changed=True,
            restore=lambda: calls.append(f"remove:{scope}:{source}"),
        )

    def remove_source(source: str, scope: str) -> PackageSourceSettingsMutation:
        calls.append(f"remove:{scope}:{source}")
        return PackageSourceSettingsMutation(
            source=source,
            scope=scope,
            changed=True,
            restore=lambda: calls.append(f"add:{scope}:{source}"),
        )

    return PackageOperationsRuntime(
        get_materializer=lambda: materializer,
        add_source=add_source,
        remove_source=remove_source,
        refresh_resources=refresh,
        prepare_updates=prepare,
    )


def test_operations_materialize_local_package_without_materializer(tmp_path) -> None:
    package = tmp_path / "local-pack"
    package.mkdir()
    runtime = _runtime(None, calls=[])

    record = asyncio.run(runtime.materialize(str(package)))

    assert record.lifecycle == "installed"
    assert record.target_path == package.resolve()


def test_operations_install_registers_and_refreshes_only_installed_package(
    tmp_path,
) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)
    runtime = _runtime(materializer, calls=calls)
    source = "https://example.test/pack.git"

    record = asyncio.run(runtime.install(source, scope="project"))

    assert record.lifecycle == "installed"
    assert materializer.materialized == [source]
    assert calls == [f"add:project:{source}", "refresh"]


def test_operations_install_does_not_register_failed_materialization(tmp_path) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)
    materializer.materialize_result = materializer._record(
        "https://example.test/pack.git", "failed"
    )
    runtime = _runtime(materializer, calls=calls)

    record = asyncio.run(
        runtime.install(materializer.materialize_result.source, scope="user")
    )

    assert record.lifecycle == "failed"
    assert calls == []


def test_operations_update_all_prepares_then_refreshes(tmp_path) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)
    runtime = _runtime(materializer, calls=calls)

    records = asyncio.run(runtime.update_all())

    assert [record.source for record in records] == ["https://example.test/all.git"]
    assert materializer.update_all_calls == 1
    assert calls == ["prepare", "refresh"]


def test_operations_uninstall_forgets_remote_source_and_refreshes(tmp_path) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)
    runtime = _runtime(materializer, calls=calls)
    source = "https://example.test/pack.git"

    record = asyncio.run(runtime.uninstall(source, scope="session"))

    assert record.lifecycle == "remote_registered"
    assert materializer.removed == [source]
    assert materializer.forgotten == [source]
    assert calls == [f"remove:session:{source}", "refresh"]


def test_operations_keeps_failed_remote_cleanup_record_after_publication(
    tmp_path,
) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)
    source = "https://example.test/pack.git"
    materializer.remove_result = materializer._record(source, "failed").with_lifecycle(
        "failed",
        error_message="checkout is busy",
    )
    runtime = _runtime(materializer, calls=calls)

    with pytest.raises(RuntimeError, match="checkout is busy"):
        asyncio.run(runtime.uninstall(source, scope="session"))

    assert materializer.removed == [source]
    assert materializer.forgotten == []
    assert calls == [f"remove:session:{source}", "refresh"]


def test_operations_rolls_back_registration_when_refresh_fails(tmp_path) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)

    def fail_refresh() -> None:
        calls.append("refresh")
        raise RuntimeError("Catalog admission failed")

    runtime = PackageOperationsRuntime(
        get_materializer=lambda: materializer,
        add_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"add:{scope}:{source}",
            rollback=f"remove:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        remove_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"remove:{scope}:{source}",
            rollback=f"add:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        refresh_resources=fail_refresh,
    )
    source = "https://example.test/pack.git"

    with pytest.raises(RuntimeError, match="Catalog admission failed"):
        asyncio.run(runtime.install(source, scope="project"))

    assert calls == [
        f"add:project:{source}",
        "refresh",
        f"remove:project:{source}",
    ]


def test_operations_keeps_registration_when_refresh_published_before_failure(
    tmp_path,
) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)

    def fail_after_publication() -> PackageResourceRefreshOutcome:
        calls.append("refresh")
        return PackageResourceRefreshOutcome(
            published=True,
            error=RuntimeError("retirement remains pending"),
        )

    runtime = PackageOperationsRuntime(
        get_materializer=lambda: materializer,
        add_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"add:{scope}:{source}",
            rollback=f"remove:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        remove_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"remove:{scope}:{source}",
            rollback=f"add:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        refresh_resources=fail_after_publication,
    )
    source = "https://example.test/pack.git"

    with pytest.raises(RuntimeError, match="retirement remains pending"):
        asyncio.run(runtime.install(source, scope="project"))

    assert calls == [f"add:project:{source}", "refresh"]


def test_operations_does_not_attribute_unrelated_publication_to_failed_refresh(
    tmp_path,
) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)

    def fail_this_refresh() -> PackageResourceRefreshOutcome:
        calls.append("refresh-after-unrelated-publication")
        return PackageResourceRefreshOutcome(
            published=False,
            error=RuntimeError("this refresh failed before publication"),
        )

    runtime = PackageOperationsRuntime(
        get_materializer=lambda: materializer,
        add_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"add:{scope}:{source}",
            rollback=f"remove:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        remove_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"remove:{scope}:{source}",
            rollback=f"add:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        refresh_resources=fail_this_refresh,
    )
    source = "https://example.test/pack.git"

    with pytest.raises(RuntimeError, match="this refresh failed"):
        asyncio.run(runtime.install(source, scope="project"))

    assert calls == [
        f"add:project:{source}",
        "refresh-after-unrelated-publication",
        f"remove:project:{source}",
    ]


def test_operations_delegates_mutation_and_failed_uninstall_to_refresh_transaction(
    tmp_path,
) -> None:
    calls: list[str] = []
    materializer = _Materializer(tmp_path)
    source = "https://example.test/pack.git"

    async def run_transaction(
        transaction: PackageResourceRefreshTransaction,
    ) -> PackageResourceRefreshOutcome:
        calls.append("transaction-entered")
        mutation = transaction.begin()
        calls.append("refresh-failed-before-publication")
        outcome = PackageResourceRefreshOutcome(
            published=False,
            error=RuntimeError("candidate rejected"),
        )
        transaction.settle(mutation, outcome)
        return outcome

    runtime = PackageOperationsRuntime(
        get_materializer=lambda: materializer,
        add_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"add:{scope}:{source}",
            rollback=f"remove:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        remove_source=lambda source, scope: _settings_mutation(
            calls,
            action=f"remove:{scope}:{source}",
            rollback=f"add:{scope}:{source}",
            source=source,
            scope=scope,
        ),
        refresh_resources=lambda: pytest.fail("transaction port was bypassed"),
        refresh_transaction=run_transaction,
    )

    with pytest.raises(RuntimeError, match="candidate rejected"):
        asyncio.run(runtime.uninstall(source, scope="project"))

    assert calls == [
        "transaction-entered",
        f"remove:project:{source}",
        "refresh-failed-before-publication",
        f"add:project:{source}",
    ]
    assert materializer.removed == []
    assert materializer.forgotten == []


def test_operations_requires_materializer_for_remote_source(tmp_path) -> None:
    runtime = _runtime(None, calls=[])

    with pytest.raises(RuntimeError, match="Package materializer is not available"):
        asyncio.run(runtime.materialize("https://example.test/pack.git"))


def _settings_mutation(
    calls: list[str],
    *,
    action: str,
    rollback: str,
    source: str,
    scope: str,
) -> PackageSourceSettingsMutation:
    calls.append(action)
    return PackageSourceSettingsMutation(
        source=source,
        scope=scope,
        changed=True,
        restore=lambda: calls.append(rollback),
    )
