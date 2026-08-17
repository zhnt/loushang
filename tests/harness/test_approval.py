from __future__ import annotations

import asyncio


def test_approval_decision_helpers_cover_allow_and_deny() -> None:
    from loushang.harness.approval import ApprovalDecision

    assert ApprovalDecision.allow() == ApprovalDecision(
        disposition="allow", reason=None
    )
    assert ApprovalDecision.deny("blocked") == ApprovalDecision(
        disposition="deny", reason="blocked"
    )


def test_approval_decision_rejects_invalid_disposition() -> None:
    import pytest

    from loushang.harness.approval import ApprovalDecision

    with pytest.raises(ValueError, match="Unsupported approval decision disposition"):
        ApprovalDecision(disposition="prompt")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="reason"):
        ApprovalDecision(disposition="deny", reason=object())  # type: ignore[arg-type]


def test_resolve_approval_defaults_to_deny() -> None:
    from loushang.harness.approval import ApprovalRequest, resolve_approval

    decision = asyncio.run(
        resolve_approval(
            None,
            ApprovalRequest(
                tool_name="write",
                arguments={"path": "x"},
                reason="needs approval",
            ),
        )
    )

    assert decision.disposition == "deny"
    assert decision.reason == "needs approval"


def test_resolve_approval_rejects_invalid_resolver_result() -> None:
    import pytest

    from loushang.harness.approval import ApprovalRequest, resolve_approval

    class InvalidResolver:
        def resolve(self, request):
            del request
            return object()

    with pytest.raises(TypeError, match="ApprovalResolver returned object"):
        asyncio.run(
            resolve_approval(
                InvalidResolver(),
                ApprovalRequest(tool_name="write", arguments={}),
            )
        )


def test_headless_approval_resolver_can_allow() -> None:
    from loushang.harness.approval import ApprovalRequest, HeadlessApprovalResolver

    decision = HeadlessApprovalResolver(mode="allow").resolve(
        ApprovalRequest(tool_name="read", arguments={})
    )

    assert decision.disposition == "allow"


def test_headless_approval_resolver_rejects_invalid_mode() -> None:
    import pytest

    from loushang.harness.approval import HeadlessApprovalResolver

    with pytest.raises(ValueError, match="Unsupported headless approval mode"):
        HeadlessApprovalResolver(mode="prompt")  # type: ignore[arg-type]


def test_approval_request_accepts_opaque_policy_context() -> None:
    from loushang.harness.approval import ApprovalRequest

    policy_decision = object()
    request = ApprovalRequest(
        tool_name="bash",
        arguments={"command": "git push"},
        policy_decision=policy_decision,
    )

    assert request.policy_decision is policy_decision


def test_approval_request_snapshots_arguments() -> None:
    import pytest

    from loushang.harness.approval import ApprovalRequest

    edits = [{"oldText": "before", "newText": "after"}]
    arguments = {"path": "before.txt", "edits": edits}
    request = ApprovalRequest(tool_name="write", arguments=arguments)
    arguments["path"] = "after.txt"
    edits[0]["newText"] = "changed"

    assert request.arguments["path"] == "before.txt"
    assert request.arguments["edits"][0]["newText"] == "after"  # type: ignore[index]
    with pytest.raises(TypeError):
        request.arguments["edits"][0]["newText"] = "forbidden"  # type: ignore[index]


def test_approval_request_rejects_invalid_fields_and_mutable_leaf_values() -> None:
    import pytest

    from loushang.harness.approval import ApprovalRequest

    with pytest.raises(ValueError, match="tool_name"):
        ApprovalRequest(tool_name="", arguments={})
    with pytest.raises(TypeError, match="cwd"):
        ApprovalRequest(tool_name="write", arguments={}, cwd=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="action_id"):
        ApprovalRequest(tool_name="write", arguments={}, action_id="")
    with pytest.raises(TypeError, match="JSON-compatible"):
        ApprovalRequest(
            tool_name="write",
            arguments={"payload": bytearray(b"mutable")},
        )
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        ApprovalRequest(
            tool_name="write",
            arguments={"nested": {1: "numeric", "1": "string"}},
        )


def test_approval_request_snapshot_supports_standard_serializers() -> None:
    import json
    import pickle
    from copy import deepcopy
    from dataclasses import asdict

    from loushang.harness.approval import ApprovalRequest

    request = ApprovalRequest(
        tool_name="write",
        arguments={"path": "notes.txt", "options": {"lines": [1, 2]}},
        action_id="approval-serializable",
    )

    copied = deepcopy(request)
    restored = pickle.loads(pickle.dumps(request))
    projected = asdict(request)

    assert copied == request
    assert restored == request
    assert projected["arguments"] == request.arguments
    assert json.loads(json.dumps(projected))["arguments"]["path"] == "notes.txt"


def test_approval_request_public_projection_is_mutable_and_detached() -> None:
    from loushang.harness.approval import (
        ApprovalRequest,
        approval_request_to_dict,
    )

    request = ApprovalRequest(
        tool_name="edit",
        arguments={"edits": [{"oldText": "before", "newText": "after"}]},
    )

    projected = approval_request_to_dict(request)
    arguments = projected["arguments"]
    assert isinstance(arguments, dict)
    edits = arguments["edits"]
    assert isinstance(edits, list)
    edits[0]["newText"] = "projected mutation"

    assert request.arguments["edits"][0]["newText"] == "after"  # type: ignore[index]


def test_resolve_approval_revalidates_mutated_decision_fields() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalDecision,
        ApprovalRequest,
        resolve_approval,
    )

    malformed = ApprovalDecision.allow()
    object.__setattr__(malformed, "reason", object())

    class Resolver:
        def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
            del request
            return malformed

    with pytest.raises(TypeError, match="reason"):
        asyncio.run(
            resolve_approval(
                Resolver(),
                ApprovalRequest(tool_name="write", arguments={}),
            )
        )


def test_approval_broker_revalidates_all_terminal_decisions() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        HeadlessApprovalResolver,
    )

    malformed = ApprovalDecision.allow()
    object.__setattr__(malformed, "reason", object())

    operations = (
        lambda broker: broker.resolve_request("missing", malformed),
        lambda broker: broker.cancel_request("missing", malformed),
        lambda broker: broker.cancel_all(malformed),
        lambda broker: broker.dispose(malformed),
    )
    for operation in operations:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
        with pytest.raises(TypeError, match="reason"):
            operation(broker)


def test_ensure_approval_action_id_is_idempotent() -> None:
    from loushang.harness.approval import (
        ApprovalRequest,
        ensure_approval_action_id,
    )

    request = ApprovalRequest(tool_name="write", arguments={})
    prepared = ensure_approval_action_id(request)

    assert prepared.action_id is not None
    assert ensure_approval_action_id(prepared) is prepared


def test_approval_broker_presents_and_correlates_result() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    class Presenter:
        def __init__(self, broker: ApprovalBroker) -> None:
            self.broker = broker
            self.requests: list[ApprovalRequest] = []

        def present(self, request: ApprovalRequest) -> None:
            self.requests.append(request)
            assert request.action_id is not None
            assert self.broker.resolve_request(
                request.action_id, ApprovalDecision.allow()
            )

    async def run() -> tuple[ApprovalDecision, tuple[ApprovalRequest, ...]]:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="deny"),
        )
        presenter = Presenter(broker)
        broker.set_presenter(presenter)
        decision = await broker.resolve(
            ApprovalRequest(tool_name="write", arguments={"path": "x"})
        )
        return decision, tuple(presenter.requests)

    decision, requests = asyncio.run(run())

    assert decision == ApprovalDecision.allow()
    assert len(requests) == 1


def test_approval_broker_rejects_duplicate_pending_action_id() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalRequest,
        ApprovalRequestCollisionError,
        HeadlessApprovalResolver,
    )

    presented = asyncio.Event()

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            presented.set()

    async def run() -> None:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
        broker.set_presenter(Presenter())
        request = ApprovalRequest(
            tool_name="write",
            arguments={},
            action_id="approval-shared",
        )
        first = asyncio.create_task(broker.resolve(request))
        await presented.wait()
        with pytest.raises(ApprovalRequestCollisionError):
            await broker.resolve(request)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert broker.pending_requests() == ()

    asyncio.run(run())


def test_approval_broker_rejects_pending_collision_after_presenter_unbind() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        ApprovalRequestCollisionError,
        HeadlessApprovalResolver,
    )

    presented = asyncio.Event()

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            presented.set()

    async def run() -> None:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="allow"))
        broker.set_presenter(Presenter())
        request = ApprovalRequest(
            tool_name="write",
            arguments={},
            action_id="approval-shared",
        )
        first = asyncio.create_task(broker.resolve(request))
        await presented.wait()
        broker.set_presenter(None)

        with pytest.raises(ApprovalRequestCollisionError):
            await broker.resolve(request)

        assert (
            await broker.resolve(
                ApprovalRequest(
                    tool_name="read",
                    arguments={},
                    action_id="approval-distinct",
                )
            )
            == ApprovalDecision.allow()
        )
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

    asyncio.run(run())


def test_approval_broker_rejects_reuse_after_cancellation_and_late_result() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        ApprovalRequestCollisionError,
        HeadlessApprovalResolver,
    )

    presented = asyncio.Event()

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            del request
            presented.set()

    async def run() -> None:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
        broker.set_presenter(Presenter())
        request = ApprovalRequest(
            tool_name="write",
            arguments={},
            action_id="approval-reused",
        )
        first = asyncio.create_task(broker.resolve(request))
        await presented.wait()
        assert broker.cancel_all(ApprovalDecision.deny("session replaced")) == 1
        assert await first == ApprovalDecision.deny("session replaced")

        with pytest.raises(ApprovalRequestCollisionError):
            await broker.resolve(request)
        assert not broker.resolve_request(
            "approval-reused",
            ApprovalDecision.allow(),
        )
        assert broker.pending_requests() == ()
        assert broker.dispose(ApprovalDecision.deny("disposed")) == 0
        assert (await broker.resolve(request)).disposition == "deny"

    asyncio.run(run())


def test_approval_broker_cleans_up_presenter_failure_and_caller_cancellation() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    class BrokenPresenter:
        def present(self, request: ApprovalRequest) -> None:
            del request
            raise RuntimeError("presentation failed")

    async def run() -> None:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
        broker.set_presenter(BrokenPresenter())
        with pytest.raises(RuntimeError, match="presentation failed"):
            await broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        assert broker.pending_requests() == ()

        presented = asyncio.Event()
        dismissed: list[str | None] = []

        class WaitingPresenter:
            async def present(self, request: ApprovalRequest) -> None:
                del request
                presented.set()

            def dismiss(self, request: ApprovalRequest) -> None:
                dismissed.append(request.action_id)

        broker.set_presenter(WaitingPresenter())
        task = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="edit", arguments={}))
        )
        await presented.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert broker.pending_requests() == ()
        assert len(dismissed) == 1

    asyncio.run(run())


def test_approval_broker_timeout_uses_validated_fallback() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
    )

    dismissed: list[str | None] = []

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            del request

        def dismiss(self, request: ApprovalRequest) -> None:
            dismissed.append(request.action_id)

    class AsyncFallback:
        async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
            del request
            return ApprovalDecision.allow()

    async def run() -> tuple[ApprovalDecision, tuple[ApprovalRequest, ...]]:
        broker = ApprovalBroker(
            fallback=AsyncFallback(),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        decision = await broker.resolve(
            ApprovalRequest(
                tool_name="write",
                arguments={},
                action_id="approval-timeout-dismiss",
            )
        )
        return decision, broker.pending_requests()

    decision, pending = asyncio.run(run())

    assert decision == ApprovalDecision.allow()
    assert pending == ()
    assert dismissed == ["approval-timeout-dismiss"]


def test_approval_broker_timeout_preserves_caller_cancellation_from_presenter() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    resolution: asyncio.Task[object] | None = None

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            try:
                await asyncio.Event().wait()
            finally:
                assert resolution is not None
                resolution.cancel()

    async def run() -> None:
        nonlocal resolution
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        resolution = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        with pytest.raises(asyncio.CancelledError):
            await resolution
        assert broker.pending_requests() == ()

    asyncio.run(run())


def test_approval_broker_does_not_wait_for_async_dismissal() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    dismiss_started = asyncio.Event()
    dismiss_release = asyncio.Event()

    class Presenter:
        def __init__(self, broker: ApprovalBroker) -> None:
            self.broker = broker

        def present(self, request: ApprovalRequest) -> None:
            assert request.action_id is not None
            assert self.broker.resolve_request(
                request.action_id,
                ApprovalDecision.allow(),
            )

        async def dismiss(self, request: ApprovalRequest) -> None:
            del request
            dismiss_started.set()
            try:
                await dismiss_release.wait()
            except asyncio.CancelledError:
                await dismiss_release.wait()

    async def run() -> None:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
        broker.set_presenter(Presenter(broker))
        resolved = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await dismiss_started.wait()
        try:
            assert resolved.done()
            assert await resolved == ApprovalDecision.allow()
        finally:
            dismiss_release.set()
            await asyncio.sleep(0)

    asyncio.run(run())


def test_approval_broker_ignores_sync_dismissal_cancellation() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    class Presenter:
        def __init__(self, broker: ApprovalBroker) -> None:
            self.broker = broker

        def present(self, request: ApprovalRequest) -> None:
            assert request.action_id is not None
            assert self.broker.resolve_request(
                request.action_id,
                ApprovalDecision.allow(),
            )

        def dismiss(self, request: ApprovalRequest) -> None:
            del request
            raise asyncio.CancelledError

    async def run() -> ApprovalDecision:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
        broker.set_presenter(Presenter(broker))
        return await broker.resolve(ApprovalRequest(tool_name="write", arguments={}))

    assert asyncio.run(run()) == ApprovalDecision.allow()


def test_approval_broker_timeout_after_async_presenter_uses_fallback() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request

    async def run() -> tuple[ApprovalDecision, tuple[ApprovalRequest, ...]]:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        decision = await broker.resolve(
            ApprovalRequest(tool_name="write", arguments={})
        )
        return decision, broker.pending_requests()

    decision, pending = asyncio.run(run())

    assert decision == ApprovalDecision.allow()
    assert pending == ()


def test_approval_broker_dispose_overrides_blocked_timeout_fallback() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
    )

    fallback_started = asyncio.Event()
    fallback_cancelled = asyncio.Event()
    release_fallback = asyncio.Event()

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            del request

    class BlockingFallback:
        async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
            del request
            fallback_started.set()
            try:
                await release_fallback.wait()
            except asyncio.CancelledError:
                fallback_cancelled.set()
                await release_fallback.wait()
            return ApprovalDecision.allow()

    async def run() -> tuple[ApprovalDecision, int]:
        broker = ApprovalBroker(
            fallback=BlockingFallback(),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        resolution = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await fallback_started.wait()
        pending_requests = broker.pending_requests()
        assert len(pending_requests) == 1
        action_id = pending_requests[0].action_id
        assert action_id is not None
        assert not broker.resolve_request(action_id, ApprovalDecision.allow())
        completed = broker.dispose(ApprovalDecision.deny("session closed"))
        try:
            decision = await asyncio.wait_for(resolution, timeout=0.2)
            assert broker.pending_requests() == ()
            await fallback_cancelled.wait()
            return decision, completed
        finally:
            release_fallback.set()
            await asyncio.sleep(0)

    decision, completed = asyncio.run(run())

    assert decision == ApprovalDecision.deny("session closed")
    assert completed == 1


def test_approval_broker_rejects_late_ui_result_after_timeout() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
    )

    fallback_started = asyncio.Event()
    release_fallback = asyncio.Event()

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            del request

    class BlockingFallback:
        async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
            del request
            fallback_started.set()
            await release_fallback.wait()
            return ApprovalDecision.deny("fallback denied")

    async def run() -> ApprovalDecision:
        broker = ApprovalBroker(
            fallback=BlockingFallback(),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        resolution = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await fallback_started.wait()
        request = broker.pending_requests()[0]
        assert request.action_id is not None
        assert not broker.resolve_request(
            request.action_id,
            ApprovalDecision.allow(),
        )
        release_fallback.set()
        return await resolution

    assert asyncio.run(run()) == ApprovalDecision.deny("fallback denied")


def test_approval_broker_propagates_presenter_timeout_error() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            raise TimeoutError("presenter internal timeout")

    async def run() -> None:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
            timeout_seconds=1,
        )
        broker.set_presenter(Presenter())
        with pytest.raises(TimeoutError, match="presenter internal timeout"):
            await broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        assert broker.pending_requests() == ()

    asyncio.run(run())


def test_approval_broker_timeout_does_not_wait_for_cancel_resistant_presenter() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presentation_cancelled = asyncio.Event()
    release_presenter = asyncio.Event()

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                presentation_cancelled.set()
                await release_presenter.wait()

    async def run() -> ApprovalDecision:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        resolution = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await presentation_cancelled.wait()
        await asyncio.sleep(0.01)
        try:
            assert resolution.done()
            return await resolution
        finally:
            release_presenter.set()
            await asyncio.sleep(0)

    assert asyncio.run(run()) == ApprovalDecision.allow()


def test_approval_broker_redismisses_cancel_resistant_late_presentation() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presentation_cancelled = asyncio.Event()
    release_presenter = asyncio.Event()
    events: list[str] = []

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                presentation_cancelled.set()
                await release_presenter.wait()
                events.append("presented-after-cancel")

        def dismiss(self, request: ApprovalRequest) -> None:
            del request
            events.append("dismissed")

    async def run() -> ApprovalDecision:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        decision = await broker.resolve(
            ApprovalRequest(tool_name="write", arguments={})
        )
        await presentation_cancelled.wait()
        assert events == ["dismissed"]
        release_presenter.set()
        for _ in range(10):
            if events == [
                "dismissed",
                "presented-after-cancel",
                "dismissed",
            ]:
                break
            await asyncio.sleep(0)
        return decision

    assert asyncio.run(run()) == ApprovalDecision.allow()
    assert events == ["dismissed", "presented-after-cancel", "dismissed"]


def test_approval_broker_redismisses_late_presentation_that_reraises_cancel() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presentation_cancelled = asyncio.Event()
    release_presenter = asyncio.Event()
    events: list[str] = []

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                presentation_cancelled.set()
                await release_presenter.wait()
                events.append("presented-after-cancel")
                raise

        def dismiss(self, request: ApprovalRequest) -> None:
            del request
            events.append("dismissed")

    async def run() -> None:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
            timeout_seconds=0.001,
        )
        broker.set_presenter(Presenter())
        await broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        await presentation_cancelled.wait()
        assert events == ["dismissed"]
        release_presenter.set()
        for _ in range(10):
            if events == [
                "dismissed",
                "presented-after-cancel",
                "dismissed",
            ]:
                break
            await asyncio.sleep(0)

    asyncio.run(run())

    assert events == ["dismissed", "presented-after-cancel", "dismissed"]


def test_approval_broker_dispose_completes_pending_and_uses_fallback_afterward() -> (
    None
):
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presented = asyncio.Event()

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            presented.set()

    async def run() -> tuple[ApprovalDecision, ApprovalDecision, int, int]:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
        )
        broker.set_presenter(Presenter())
        pending = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await presented.wait()
        completed = broker.dispose(ApprovalDecision.deny("session closed"))
        duplicate_dispose = broker.dispose(ApprovalDecision.deny("ignored"))
        first = await pending
        after = await broker.resolve(ApprovalRequest(tool_name="read", arguments={}))
        return first, after, completed, duplicate_dispose

    first, after, completed, duplicate_dispose = asyncio.run(run())

    assert first == ApprovalDecision.deny("session closed")
    assert after == ApprovalDecision.allow()
    assert completed == 1
    assert duplicate_dispose == 0


def test_approval_broker_dispose_interrupts_pending_async_presentation() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presenting = asyncio.Event()
    presentation_cancelled = asyncio.Event()

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            del request
            presenting.set()
            try:
                await asyncio.Event().wait()
            finally:
                presentation_cancelled.set()

    async def run() -> ApprovalDecision:
        broker = ApprovalBroker(
            fallback=HeadlessApprovalResolver(mode="allow"),
        )
        broker.set_presenter(Presenter())
        pending = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await presenting.wait()
        assert broker.dispose(ApprovalDecision.deny("session closed")) == 1
        decision = await pending
        await presentation_cancelled.wait()
        return decision

    assert asyncio.run(run()) == ApprovalDecision.deny("session closed")


def test_approval_broker_resolves_concurrent_requests_independently() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presented = asyncio.Event()
    requests: list[ApprovalRequest] = []

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            requests.append(request)
            if len(requests) == 2:
                presented.set()

    async def run() -> tuple[ApprovalDecision, ApprovalDecision]:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
        broker.set_presenter(Presenter())
        first = asyncio.create_task(
            broker.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="approval-first",
                )
            )
        )
        second = asyncio.create_task(
            broker.resolve(
                ApprovalRequest(
                    tool_name="publish",
                    arguments={},
                    action_id="approval-second",
                )
            )
        )
        await presented.wait()

        assert broker.cancel_request(
            "approval-first", ApprovalDecision.deny("cancelled")
        )
        assert not second.done()
        assert broker.resolve_request("approval-second", ApprovalDecision.allow())
        decisions = await asyncio.gather(first, second)
        assert broker.pending_requests() == ()
        return decisions[0], decisions[1]

    first, second = asyncio.run(run())

    assert first == ApprovalDecision.deny("cancelled")
    assert second == ApprovalDecision.allow()


def test_approval_broker_can_be_reused_across_sequential_event_loops() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            assert request.action_id is not None
            assert broker.resolve_request(request.action_id, ApprovalDecision.allow())

    broker.set_presenter(Presenter())

    async def resolve(tool_name: str) -> ApprovalDecision:
        return await broker.resolve(ApprovalRequest(tool_name=tool_name, arguments={}))

    assert asyncio.run(resolve("write")) == ApprovalDecision.allow()
    assert asyncio.run(resolve("publish")) == ApprovalDecision.allow()


def test_approval_broker_wrong_loop_dispose_does_not_poison_owner_cleanup() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            del request

    broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="allow"))
    broker.set_presenter(Presenter())
    owner_loop = asyncio.new_event_loop()

    async def start_request() -> asyncio.Task[ApprovalDecision]:
        task = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await asyncio.sleep(0)
        return task

    pending = owner_loop.run_until_complete(start_request())

    async def dispose_on_wrong_loop() -> None:
        broker.dispose(ApprovalDecision.deny("wrong loop"))

    with pytest.raises(RuntimeError, match="owning event loop"):
        asyncio.run(dispose_on_wrong_loop())

    async def dispose_on_owner_loop() -> ApprovalDecision:
        assert broker.dispose(ApprovalDecision.deny("owner cleanup")) == 1
        return await pending

    try:
        decision = owner_loop.run_until_complete(dispose_on_owner_loop())
    finally:
        if not pending.done():
            pending.cancel()
            owner_loop.run_until_complete(
                asyncio.gather(pending, return_exceptions=True)
            )
        owner_loop.close()

    assert decision == ApprovalDecision.deny("owner cleanup")


def test_approval_broker_invalid_dispose_decision_does_not_poison_cleanup() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presented = asyncio.Event()

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            del request
            presented.set()

    async def run() -> ApprovalDecision:
        broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="allow"))
        broker.set_presenter(Presenter())
        pending = asyncio.create_task(
            broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await presented.wait()
        with pytest.raises(TypeError, match="ApprovalDecision"):
            broker.dispose(object())  # type: ignore[arg-type]
        assert broker.dispose(ApprovalDecision.deny("valid cleanup")) == 1
        return await pending

    assert asyncio.run(run()) == ApprovalDecision.deny("valid cleanup")


def test_approval_broker_unknown_and_late_results_do_not_mutate_state() -> None:
    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        HeadlessApprovalResolver,
    )

    broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))

    assert not broker.resolve_request("missing", ApprovalDecision.allow())
    assert not broker.cancel_request("missing", ApprovalDecision.deny("late"))


def test_approval_broker_rejects_presenter_rebind_after_disposal() -> None:
    import pytest

    from loushang.harness.approval import (
        ApprovalBroker,
        ApprovalDecision,
        ApprovalRequest,
        HeadlessApprovalResolver,
    )

    presented = False

    class Presenter:
        def present(self, request: ApprovalRequest) -> None:
            nonlocal presented
            del request
            presented = True

    broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
    assert broker.dispose(ApprovalDecision.deny("closed")) == 0
    broker.set_presenter(None)
    with pytest.raises(RuntimeError, match="disposed"):
        broker.set_presenter(Presenter())

    decision = asyncio.run(
        broker.resolve(ApprovalRequest(tool_name="write", arguments={}))
    )
    assert decision.disposition == "deny"
    assert not presented


def test_approval_request_projects_only_policy_admitted_session_option() -> None:
    from loushang.harness.approval import (
        ApprovalGrantProposal,
        ApprovalRequest,
        approval_request_to_dict,
    )

    ordinary = approval_request_to_dict(
        ApprovalRequest(tool_name="bash", arguments={"command": "rm -rf build"})
    )
    proposal = ApprovalGrantProposal(
        capability="git.publish_refs",
        constraints=(
            ("remote", "origin"),
            ("repository", "/workspace/project"),
            ("refspecs", '["main"]'),
            ("force", "false"),
        ),
        summary="Publish main to origin from this repository",
    )
    reusable = approval_request_to_dict(
        ApprovalRequest(
            tool_name="bash",
            arguments={"command": "git push origin main"},
            session_grant=proposal,
        )
    )

    assert tuple(
        option["outcome"] for option in ordinary["approval_options"]
    ) == ("allow_once", "deny")
    assert tuple(
        option["outcome"] for option in reusable["approval_options"]
    ) == ("allow_once", "allow_session", "deny")
    assert reusable["session_grant"] == {
        "capability": "git.publish_refs",
        "constraints": {
            "force": "false",
            "refspecs": '["main"]',
            "remote": "origin",
            "repository": "/workspace/project",
        },
        "summary": "Publish main to origin from this repository",
    }


def test_interactive_approval_session_grant_reuses_exact_semantics_for_one_actor() -> (
    None
):
    from dataclasses import replace

    from loushang.harness.approval import (
        ApprovalGrantProposal,
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    proposal = ApprovalGrantProposal(
        capability="git.publish_refs",
        constraints=(
            ("repository", "/workspace/project"),
            ("remote", "origin"),
            ("refspecs", '["main"]'),
            ("force", "false"),
        ),
        summary="Publish main to origin from this repository",
    )

    async def run() -> None:
        presented = asyncio.Event()
        payloads: list[dict[str, object]] = []
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )

        def present(payload: dict[str, object]) -> None:
            payloads.append(payload)
            presented.set()

        resolver.set_request_presenter(present)
        first = ApprovalRequest(
            tool_name="bash",
            arguments={"command": "git push origin main"},
            action_id="approval-first",
            action_fingerprint="a" * 64,
            actor_id="/root#1",
            session_grant=proposal,
        )
        pending = asyncio.create_task(resolver.resolve(first))
        await presented.wait()

        assert await resolver.handle_result(
            "approval-first",
            approved=True,
            scope="session",
        )
        decision = await pending
        assert decision.disposition == "allow"
        assert decision.scope == "session"
        assert decision.grant_id is not None
        assert tuple(
            option["outcome"] for option in payloads[0]["approval_options"]
        ) == ("allow_once", "allow_session", "deny")

        reused = await resolver.resolve(
            replace(
                first,
                arguments={"command": "git push --porcelain origin main"},
                action_id="approval-second",
                action_fingerprint="b" * 64,
            )
        )
        assert reused == decision
        assert len(payloads) == 1
        assert resolver.preauthorize(
            replace(first, action_id="other-actor", actor_id="/root/child#1")
        ) is None
        assert resolver.preauthorize(
            replace(
                first,
                action_id="other-ref",
                session_grant=replace(
                    proposal,
                    constraints=(
                        ("repository", "/workspace/project"),
                        ("remote", "origin"),
                        ("refspecs", '["release"]'),
                        ("force", "false"),
                    ),
                ),
            )
        ) is None

        resolver.close_session("presenter detached")
        resolver.open_session()
        assert resolver.preauthorize(first) == decision

        snapshot = resolver.permissions_snapshot()
        assert [item.permission_id for item in snapshot.grants] == [
            decision.grant_id
        ]
        assert decision.grant_id is not None
        assert resolver.revoke_grant(decision.grant_id)
        assert resolver.preauthorize(first) is None

        resolver.end_session("session replaced")
        assert resolver.grant_store.grants() == ()
        assert resolver.preauthorize(first) is None
        resolver.dispose()

    asyncio.run(run())


def test_persistent_policy_amendment_survives_restart_and_matches_typed_scope(
    tmp_path,
) -> None:
    from dataclasses import replace

    from loushang.harness.approval import (
        ApprovalGrantProposal,
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
        JsonApprovalPolicyRuleStore,
        PolicyAmendmentProposal,
    )

    proposal = ApprovalGrantProposal(
        capability="git.publish_refs",
        constraints=(
            ("repository", "/workspace/project"),
            ("remote", "origin"),
            ("force", "false"),
        ),
        summary="Publish non-force refs to origin from this repository",
    )
    request = ApprovalRequest(
        tool_name="bash",
        arguments={"command": "git push origin main"},
        action_id="approval-persist",
        actor_id="/root/worker#1",
        session_grant=proposal,
        policy_amendments=(
            PolicyAmendmentProposal(scope="project", grant=proposal),
        ),
    )
    path = tmp_path / "project-policy.json"

    async def approve() -> None:
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny"),
            policy_stores={
                "project": JsonApprovalPolicyRuleStore("project", path)
            },
        )
        resolver.set_request_presenter(lambda _payload: presented.set())
        pending = asyncio.create_task(resolver.resolve(request))
        await presented.wait()
        assert await resolver.handle_result(
            "approval-persist",
            outcome="allow_project",
        )
        decision = await pending
        assert decision.policy_scope == "project"
        assert decision.policy_rule_id is not None
        assert len(resolver.permissions_snapshot().project_rules) == 1
        resolver.dispose()

    asyncio.run(approve())

    restarted = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny"),
        policy_stores={
            "project": JsonApprovalPolicyRuleStore("project", path)
        },
    )
    reused = restarted.preauthorize(
        replace(request, action_id="approval-restart", actor_id="root")
    )
    assert reused is not None
    assert reused.policy_scope == "project"
    changed = replace(
        proposal,
        constraints=(
            ("repository", "/workspace/project"),
            ("remote", "upstream"),
            ("force", "false"),
        ),
    )
    assert restarted.preauthorize(
        replace(
            request,
            action_id="approval-changed-boundary",
            session_grant=changed,
            policy_amendments=(
                PolicyAmendmentProposal(scope="project", grant=changed),
            ),
        )
    ) is None


def test_abort_approval_is_distinct_from_deny_and_aborts_active_session() -> None:
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )
    from loushang.harness.permissions import permission_profile_snapshot
    from loushang.harness.session.agent_adapter import AgentSessionAdapterMixin
    from loushang.harness.session.approval_interaction import (
        AgentSessionApprovalRuntime,
    )

    class Session(AgentSessionAdapterMixin):
        def __init__(self, resolver: InteractiveApprovalResolver) -> None:
            self.aborted = False

            async def dispatch_event(_event: object) -> None:
                return None

            self._approval_runtime = AgentSessionApprovalRuntime(
                resolver=resolver,
                get_permission_profile_snapshot=lambda: permission_profile_snapshot(
                    "standard"
                ),
                set_permission_profile=lambda _profile_id, *, scope: None,
                dispatch_event=dispatch_event,
                abort=self.abort,
            )

        def abort(self) -> None:
            self.aborted = True

    async def run(outcome: str) -> tuple[str, bool]:
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )
        resolver.set_request_presenter(lambda _payload: presented.set())
        session = Session(resolver)
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="bash",
                    arguments={"command": "rm -r /tmp/example"},
                    action_id=f"approval-{outcome}",
                )
            )
        )
        await presented.wait()
        assert await session.handle_screen_approval(
            {
                "action_id": f"approval-{outcome}",
                "outcome": outcome,
            }
        )
        return (await pending).disposition, session.aborted

    assert asyncio.run(run("deny")) == ("deny", False)
    assert asyncio.run(run("abort")) == ("abort", True)


def test_interactive_approval_rejects_session_scope_without_policy_proposal() -> (
    None
):
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    async def run() -> None:
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )
        resolver.set_request_presenter(lambda _payload: presented.set())
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="bash",
                    arguments={"command": "rm -rf build"},
                    action_id="approval-delete",
                )
            )
        )
        await presented.wait()

        assert not await resolver.handle_result(
            "approval-delete",
            approved=True,
            scope="session",
        )
        assert await resolver.handle_result(
            "approval-delete",
            approved=True,
            scope="once",
        )
        assert (await pending).scope == "once"
        assert resolver.grant_store.grants() == ()

    asyncio.run(run())


def test_interactive_approval_coalesces_concurrent_matching_capabilities() -> None:
    from dataclasses import replace

    from loushang.harness.approval import (
        ApprovalDecision,
        ApprovalGrantProposal,
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    async def run() -> None:
        presented = asyncio.Event()
        payloads: list[dict[str, object]] = []
        proposal = ApprovalGrantProposal(
            capability="git.publish_refs",
            constraints=(
                ("repository", "/workspace/project"),
                ("remote", "origin"),
                ("force", "false"),
            ),
            summary="Publish non-force refs to origin from this repository",
        )
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )

        def present(payload: dict[str, object]) -> None:
            payloads.append(payload)
            presented.set()

        resolver.set_request_presenter(present)
        first = ApprovalRequest(
            tool_name="bash",
            arguments={"command": "git push origin main"},
            action_id="push-main",
            actor_id="/root#1",
            session_grant=proposal,
        )
        first_task = asyncio.create_task(resolver.resolve(first))
        await presented.wait()
        second_task = asyncio.create_task(
            resolver.resolve(
                replace(
                    first,
                    arguments={"command": "git push origin release"},
                    action_id="push-release",
                )
            )
        )
        await asyncio.sleep(0)

        assert len(payloads) == 1
        assert len(resolver.permissions_snapshot().pending) == 1
        assert await resolver.handle_result("push-main", approved=True)
        assert await first_task == ApprovalDecision.allow()
        assert await second_task == ApprovalDecision.allow()

    asyncio.run(run())


def test_interactive_approval_can_represent_a_dismissed_pending_request() -> None:
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    async def run() -> None:
        presented = asyncio.Event()
        payloads: list[dict[str, object]] = []
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )

        def present(payload: dict[str, object]) -> None:
            payloads.append(payload)
            presented.set()

        resolver.set_request_presenter(present)
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="bash",
                    arguments={"command": "rm -rf build"},
                    action_id="delete-build",
                    reason="Filesystem content would be deleted",
                )
            )
        )
        await presented.wait()

        snapshot = resolver.permissions_snapshot()
        assert [item.permission_id for item in snapshot.pending] == ["delete-build"]
        assert await resolver.represent_request("delete-build")
        assert len(payloads) == 2
        assert await resolver.handle_result("delete-build", approved=False)
        assert (await pending).disposition == "deny"
        assert not await resolver.represent_request("delete-build")

    asyncio.run(run())


def test_actor_bound_resolver_releases_only_its_child_incarnation() -> None:
    from dataclasses import replace

    from loushang.harness.approval import (
        ActorBoundApprovalResolver,
        ApprovalGrantProposal,
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
        resolve_approval,
    )

    async def run() -> None:
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )
        resolver.set_request_presenter(lambda _payload: presented.set())
        child_a = ActorBoundApprovalResolver(
            resolver=resolver,
            actor_id="/root/reviewer-a#1",
        )
        child_b = ActorBoundApprovalResolver(
            resolver=resolver,
            actor_id="/root/reviewer-b#1",
        )
        proposal = ApprovalGrantProposal(
            capability="git.publish_refs",
            constraints=(("remote", "origin"),),
            summary="Publish non-force refs to origin",
        )
        request_a = ApprovalRequest(
            tool_name="bash",
            arguments={"command": "git push origin main"},
            action_id="grant-a",
            session_grant=proposal,
        )
        request_b = ApprovalRequest(
            tool_name="bash",
            arguments={"command": "git push origin main"},
            action_id="grant-b",
            session_grant=proposal,
        )
        grant_a = resolver.grant_store.issue(
            replace(request_a, actor_id=child_a.actor_id)
        )
        grant_b = resolver.grant_store.issue(
            replace(request_b, actor_id=child_b.actor_id)
        )

        pending_a = asyncio.create_task(
            resolve_approval(
                child_a,
                ApprovalRequest(
                    tool_name="bash",
                    arguments={"command": "rm -rf build"},
                    action_id="pending-a",
                ),
            )
        )
        await presented.wait()
        presented.clear()
        pending_b = asyncio.create_task(
            resolve_approval(
                child_b,
                ApprovalRequest(
                    tool_name="bash",
                    arguments={"command": "rm -rf dist"},
                    action_id="pending-b",
                ),
            )
        )
        await presented.wait()

        assert child_a.end_session("reviewer-a closed") == 1
        assert (await pending_a).disposition == "deny"
        assert (await pending_a).reason == "reviewer-a closed"
        snapshot = resolver.permissions_snapshot()
        assert [item.actor_id for item in snapshot.pending] == [child_b.actor_id]
        assert [item.permission_id for item in snapshot.grants] == [grant_b.grant_id]
        assert resolver.grant_store.find(
            replace(request_a, actor_id=child_a.actor_id)
        ) is None
        assert resolver.grant_store.find(
            replace(request_b, actor_id=child_b.actor_id)
        ) == grant_b
        assert grant_a.grant_id != grant_b.grant_id

        assert await resolver.handle_result("pending-b", approved=True)
        assert (await pending_b).disposition == "allow"
        denied_after_close = await resolve_approval(
            child_a,
            ApprovalRequest(
                tool_name="bash",
                arguments={"command": "git push origin release"},
                action_id="late-a",
            ),
        )
        assert denied_after_close.disposition == "deny"
        assert denied_after_close.reason == "reviewer-a closed"

    asyncio.run(run())
