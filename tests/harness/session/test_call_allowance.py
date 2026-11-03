from __future__ import annotations

import asyncio

import pytest

from loushang.ai import CallOptions, RetryOptions
from loushang.harness.session.call_allowance import (
    CallAllowanceError,
    ModelCallAllowance,
)


def test_other_product_phases_bound_calls_without_rewriting_call_authority():
    async def scenario():
        seen = []
        response = object()

        async def provider(model, context, options):
            seen.append((model, context, options))
            return response

        allowance = ModelCallAllowance(phase_limits={"assess": 2}, provider_attempts=2,
                                       delegate=provider, total_limit=2, max_output_tokens=16)
        allowance.enter("report-1", "assess")
        class Committer:
            async def commit_prepared_request(self, request):
                raise AssertionError("Only the original provider may commit its request")

        cancellation, committer = object(), Committer()
        options = CallOptions(cancellation=cancellation, prepared_request_committer=committer,
                              retry=RetryOptions(max_attempts=2), max_output_tokens=8)
        assert await allowance.stream("model", "context", options) is response
        actual = seen[0][2]
        assert actual.cancellation is cancellation
        assert actual.prepared_request_committer is committer
        assert actual.retry is options.retry  # Retry policy is independent of output cap.
        assert actual.max_output_tokens == 8
        allowance.leave("report-1")
        allowance.enter("report-1", "assess")
        await allowance.stream("model", "context", options)
        allowance.leave("report-1")
        allowance.enter("report-2", "assess")
        with pytest.raises(CallAllowanceError, match="owner.*exhausted"):
            await allowance.stream("model", "context", options)
        assert allowance.total_calls == 2 and len(seen) == 2 and allowance.fenced

    asyncio.run(scenario())


def test_concurrent_call_is_charged_before_provider_suspends():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        sends = 0

        async def provider(*args):
            nonlocal sends
            sends += 1
            entered.set()
            await release.wait()

        allowance = ModelCallAllowance(phase_limits={"research": 1}, provider_attempts=1, delegate=provider)
        allowance.enter("op", "research")
        running = asyncio.create_task(allowance.stream(None, None))
        await entered.wait()
        try:
            with pytest.raises(CallAllowanceError, match="exhausted"):
                await allowance.stream(None, None)
            assert sends == allowance.calls == allowance.total_calls == 1
        finally:
            release.set()
            await running

    asyncio.run(scenario())


@pytest.mark.parametrize("declared", [False, True])
def test_wrapper_does_not_upgrade_untrusted_transport_conformance(declared):
    from loushang.agent.model_transport import (
        is_prepared_request_conformant,
        prepared_request_conformant,
        require_prepared_request_conformant,
    )

    async def provider(*args):
        return None

    if declared:
        prepared_request_conformant(provider)
    allowance = ModelCallAllowance(phase_limits={"analyze": 1}, provider_attempts=1, delegate=provider)
    assert is_prepared_request_conformant(allowance.stream) is declared
    if declared:
        assert require_prepared_request_conformant(allowance.stream) is allowance.stream
    else:
        with pytest.raises(ValueError, match="durable Product"):
            require_prepared_request_conformant(allowance.stream)
