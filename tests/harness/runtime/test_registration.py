from __future__ import annotations

import asyncio
import gc
import weakref

import pytest

from loushang.harness.runtime import (
    RegistrationDisposalResult,
    RegistrationIdentity,
    RegistrationLease,
    RegistrationOwner,
    RegistrationScope,
)


def _owner(owner_id: str = "extension:alpha") -> RegistrationOwner:
    return RegistrationOwner(
        owner_kind="extension",
        owner_id=owner_id,
        runtime_id="runtime:test",
        generation=1,
    )


def test_registration_lease_removes_only_its_exact_same_name_entry() -> None:
    owner = _owner()
    first_identity = RegistrationIdentity.create(
        surface="tool",
        public_key="search",
    )
    second_identity = RegistrationIdentity.create(
        surface="tool",
        public_key="search",
    )
    entries = {
        first_identity.registration_id: "first",
        second_identity.registration_id: "second",
    }
    calls: list[str] = []

    def lease_for(identity: RegistrationIdentity) -> RegistrationLease:
        def remove() -> RegistrationDisposalResult:
            calls.append(identity.registration_id)
            if entries.pop(identity.registration_id, None) is None:
                return RegistrationDisposalResult(state="already_removed")
            return RegistrationDisposalResult(state="removed")

        return RegistrationLease(owner=owner, identity=identity, dispose=remove)

    first = lease_for(first_identity)
    second = lease_for(second_identity)

    async def scenario() -> None:
        assert await first.dispose() == RegistrationDisposalResult(state="removed")
        assert entries == {second_identity.registration_id: "second"}
        assert await first.dispose() == RegistrationDisposalResult(
            state="already_removed"
        )
        assert await second.dispose() == RegistrationDisposalResult(state="removed")

    asyncio.run(scenario())

    assert first_identity.registration_id != second_identity.registration_id
    assert calls == [
        first_identity.registration_id,
        second_identity.registration_id,
    ]


def test_registration_scope_rejects_a_lease_owned_by_another_owner() -> None:
    scope = RegistrationScope(_owner("extension:alpha"))
    foreign = RegistrationLease(
        owner=_owner("extension:beta"),
        identity=RegistrationIdentity.create(surface="tool", public_key="search"),
        dispose=lambda: None,
    )

    with pytest.raises(ValueError, match="owner"):
        scope.add(foreign)

    assert foreign.state == "active"


def test_registration_scope_rejects_a_duplicate_exact_identity() -> None:
    owner = _owner()
    identity = RegistrationIdentity.create(surface="tool", public_key="search")
    scope = RegistrationScope(owner)
    scope.add(RegistrationLease(owner=owner, identity=identity, dispose=lambda: None))
    duplicate = RegistrationIdentity(
        surface=identity.surface,
        registration_id=identity.registration_id,
        public_key="renamed-search",
    )

    with pytest.raises(ValueError, match="identity"):
        scope.add(
            RegistrationLease(
                owner=owner,
                identity=duplicate,
                dispose=lambda: None,
            )
        )


def test_registration_scope_activates_staged_leases_and_rolls_back_partial_commit() -> (
    None
):
    owner = _owner()
    events: list[str] = []

    first = RegistrationLease(
        owner=owner,
        identity=RegistrationIdentity.create(surface="tool", public_key="first"),
        dispose=lambda: None,
        activate=lambda: events.append("activate:first"),
        deactivate=lambda: events.append("deactivate:first"),
    )

    def fail_second_activation() -> None:
        events.append("activate:second")
        raise RuntimeError("activation failed")

    second = RegistrationLease(
        owner=owner,
        identity=RegistrationIdentity.create(surface="tool", public_key="second"),
        dispose=lambda: None,
        activate=fail_second_activation,
        deactivate=lambda: events.append("deactivate:second"),
    )
    scope = RegistrationScope(owner)
    scope.add(first)
    scope.add(second)

    with pytest.raises(RuntimeError, match="activation failed"):
        scope.commit()

    assert scope.state == "open"
    assert first.state == "staged"
    assert second.state == "staged"
    assert events == [
        "activate:first",
        "activate:second",
        "deactivate:second",
        "deactivate:first",
    ]


def test_dispose_linearizes_lease_and_scope_state_before_cleanup_task_runs() -> None:
    owner = _owner()

    async def scenario() -> None:
        release = asyncio.Event()

        async def remove() -> None:
            await release.wait()

        lease = RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="entry",
            ),
            dispose=remove,
        )
        scope = RegistrationScope(owner)
        scope.add(lease)

        disposing = asyncio.create_task(scope.dispose())
        await asyncio.sleep(0)

        assert scope.state == "disposing"
        assert lease.state == "active"
        with pytest.raises(RuntimeError, match="committed"):
            scope.commit()

        await asyncio.sleep(0)
        assert lease.state == "disposing"
        release.set()
        await disposing

    asyncio.run(scenario())


def test_registration_scope_disposes_in_reverse_and_continues_after_failure() -> None:
    owner = _owner()
    calls: list[str] = []
    scope = RegistrationScope(owner)

    def add(name: str, *, fail: bool = False) -> None:
        def remove() -> None:
            calls.append(name)
            if fail:
                raise RuntimeError(f"cannot remove {name}")

        scope.add(
            RegistrationLease(
                owner=owner,
                identity=RegistrationIdentity.create(
                    surface="test",
                    public_key=name,
                ),
                dispose=remove,
            )
        )

    add("first")
    add("second", fail=True)
    add("third")
    scope.commit()

    report = asyncio.run(scope.dispose())

    assert calls == ["third", "second", "first"]
    assert [outcome.identity.public_key for outcome in report.outcomes] == [
        "third",
        "second",
        "first",
    ]
    assert [outcome.result.state for outcome in report.outcomes] == [
        "removed",
        "failed_retryable",
        "removed",
    ]
    assert report.has_failures is True
    assert scope.state == "failed_retryable"


def test_registration_scope_dispose_is_idempotent_after_success() -> None:
    owner = _owner()
    calls = 0
    scope = RegistrationScope(owner)

    def remove() -> None:
        nonlocal calls
        calls += 1

    lease = scope.add(
        RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="entry",
            ),
            dispose=remove,
        )
    )
    scope.commit()

    async def scenario() -> None:
        first = await scope.dispose()
        second = await scope.dispose()
        assert second is first
        assert await lease.dispose() == RegistrationDisposalResult(
            state="already_removed"
        )

    asyncio.run(scenario())

    assert calls == 1
    assert scope.state == "disposed"


def test_registration_lease_retries_only_a_retryable_failure() -> None:
    attempts = 0

    def remove() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary removal failure")

    lease = RegistrationLease(
        owner=_owner(),
        identity=RegistrationIdentity.create(
            surface="test",
            public_key="entry",
        ),
        dispose=remove,
    )

    async def scenario() -> None:
        first = await lease.dispose()
        assert first.state == "failed_retryable"
        assert first.diagnostic_code == "registration_disposer_failed"
        assert lease.state == "failed_retryable"

        assert await lease.dispose() == RegistrationDisposalResult(state="removed")
        assert await lease.dispose() == RegistrationDisposalResult(
            state="already_removed"
        )

    asyncio.run(scenario())

    assert attempts == 2


def test_concurrent_lease_waiters_share_cleanup_when_one_is_cancelled() -> None:
    calls = 0

    async def scenario() -> None:
        nonlocal calls
        started = asyncio.Event()
        release = asyncio.Event()

        async def remove() -> None:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()

        lease = RegistrationLease(
            owner=_owner(),
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="entry",
            ),
            dispose=remove,
        )
        first = asyncio.create_task(lease.dispose())
        second = asyncio.create_task(lease.dispose())
        await started.wait()
        first.cancel("first waiter cancelled")
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == RegistrationDisposalResult(state="removed")

    asyncio.run(scenario())

    assert calls == 1


def test_scope_retry_reexecutes_only_retryable_disposer() -> None:
    owner = _owner()
    calls: list[str] = []
    retry_attempts = 0

    def remove_retryable() -> None:
        nonlocal retry_attempts
        retry_attempts += 1
        calls.append("retryable")
        if retry_attempts == 1:
            raise RuntimeError("retry later")

    def remove_terminal() -> RegistrationDisposalResult:
        calls.append("terminal")
        return RegistrationDisposalResult(
            state="failed_terminal",
            diagnostic_code="permanent_failure",
        )

    scope = RegistrationScope(owner)
    scope.add(
        RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="success",
            ),
            dispose=lambda: calls.append("success"),
        )
    )
    scope.add(
        RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="terminal",
            ),
            dispose=remove_terminal,
        )
    )
    scope.add(
        RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="retryable",
            ),
            dispose=remove_retryable,
        )
    )
    scope.commit()

    async def scenario() -> None:
        first = await scope.dispose()
        assert [outcome.result.state for outcome in first.outcomes] == [
            "failed_retryable",
            "failed_terminal",
            "removed",
        ]
        second = await scope.dispose()
        assert [outcome.result.state for outcome in second.outcomes] == [
            "removed",
            "failed_terminal",
            "already_removed",
        ]
        assert scope.state == "failed_terminal"
        assert await scope.dispose() is second

    asyncio.run(scenario())

    assert calls == ["retryable", "terminal", "success", "retryable"]


def test_registration_lease_releases_terminal_disposer_capture() -> None:
    class Registry:
        def remove(self) -> None:
            return None

    registry = Registry()
    retained = weakref.ref(registry)
    lease = RegistrationLease(
        owner=_owner(),
        identity=RegistrationIdentity.create(
            surface="test",
            public_key="entry",
        ),
        dispose=registry.remove,
    )

    asyncio.run(lease.dispose())
    del registry
    gc.collect()

    assert retained() is None


def test_synchronous_disposer_self_cancellation_is_retryable_and_scope_continues() -> (
    None
):
    owner = _owner()
    calls: list[str] = []
    scope = RegistrationScope(owner)
    scope.add(
        RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="first",
            ),
            dispose=lambda: calls.append("first"),
        )
    )

    def cancel_current_disposer() -> None:
        calls.append("cancel")
        task = asyncio.current_task()
        assert task is not None
        task.cancel("disposer self-cancelled")

    cancelling = scope.add(
        RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="test",
                public_key="cancelling",
            ),
            dispose=cancel_current_disposer,
        )
    )
    scope.commit()

    report = asyncio.run(scope.dispose())

    assert calls == ["cancel", "first"]
    assert [outcome.result.state for outcome in report.outcomes] == [
        "failed_retryable",
        "removed",
    ]
    assert cancelling.state == "failed_retryable"
    assert scope.state == "failed_retryable"


def test_registration_scope_finishes_cleanup_before_propagating_cancellation() -> None:
    owner = _owner()
    calls: list[str] = []

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        scope = RegistrationScope(owner)

        async def remove_second() -> None:
            calls.append("second:start")
            started.set()
            await release.wait()
            calls.append("second:end")

        scope.add(
            RegistrationLease(
                owner=owner,
                identity=RegistrationIdentity.create(
                    surface="test",
                    public_key="first",
                ),
                dispose=lambda: calls.append("first"),
            )
        )
        scope.add(
            RegistrationLease(
                owner=owner,
                identity=RegistrationIdentity.create(
                    surface="test",
                    public_key="second",
                ),
                dispose=remove_second,
            )
        )
        scope.commit()

        disposing = asyncio.create_task(scope.dispose())
        await started.wait()
        disposing.cancel()
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await disposing

        assert scope.state == "disposed"

    asyncio.run(scenario())

    assert calls == ["second:start", "second:end", "first"]


def test_uncommitted_registration_scope_rolls_back_on_context_exit() -> None:
    owner = _owner()
    calls: list[str] = []

    async def scenario() -> None:
        async with RegistrationScope(owner) as scope:
            scope.add(
                RegistrationLease(
                    owner=owner,
                    identity=RegistrationIdentity.create(
                        surface="test",
                        public_key="entry",
                    ),
                    dispose=lambda: calls.append("removed"),
                )
            )

        assert scope.state == "disposed"

    asyncio.run(scenario())

    assert calls == ["removed"]


def test_registration_scope_rolls_back_admission_exactly_in_reverse_order() -> None:
    owner = _owner()
    calls: list[str] = []
    scope = RegistrationScope(owner)
    for name in ("first", "second"):
        scope.add(
            RegistrationLease(
                owner=owner,
                identity=RegistrationIdentity.create(
                    surface="test",
                    public_key=name,
                ),
                dispose=lambda: pytest.fail("async disposer must not run"),
                rollback=lambda name=name: calls.append(name),
            )
        )

    report = scope.rollback_admission()

    assert calls == ["second", "first"]
    assert [outcome.result.state for outcome in report.outcomes] == [
        "removed",
        "removed",
    ]
    assert scope.state == "disposed"
