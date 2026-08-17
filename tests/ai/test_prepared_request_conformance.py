from __future__ import annotations

import asyncio

from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.prepared_request_conformance import (
    run_prepared_request_barrier_conformance,
)


class _Committer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[PreparedModelRequest] = []

    async def commit_prepared_request(self, request: PreparedModelRequest) -> None:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("commit unavailable")


def test_reusable_conformance_probe_observes_commit_before_transport() -> None:
    committer = _Committer()

    report = asyncio.run(run_prepared_request_barrier_conformance(committer))

    assert report.events == ("commit:started", "commit:completed", "transport")
    assert report.commit_completed
    assert report.transport_calls == 1
    assert report.error is None
    assert committer.requests == list(report.prepared_requests)


def test_reusable_conformance_probe_proves_failure_blocks_transport() -> None:
    committer = _Committer(fail=True)

    report = asyncio.run(run_prepared_request_barrier_conformance(committer))

    assert report.events == ("commit:started",)
    assert not report.commit_completed
    assert report.transport_calls == 0
    assert report.error is not None
