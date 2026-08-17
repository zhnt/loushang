from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TypedDict, cast

from loushang.harness.approval import (
    ApprovalBroker,
    ApprovalDecision,
    ApprovalRequest,
    HeadlessApprovalResolver,
)
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.api import ExtensionContributionAPI
from loushang.harness.extensions.control import resolve_control_contributions
from loushang.harness.extensions.routing import (
    ExtensionRoutePlan,
    ExtensionRouter,
    ResolvedExtensionRoute,
    RouteStep,
)
from loushang.harness.policy import (
    PolicyDecision,
    PolicyEvaluatorChain,
    ToolPolicySubject,
)
from loushang.harness.tools.workspace.policy import enforce_tool_policy


class _ToolState(TypedDict):
    tool_name: str
    arguments: dict[str, object]


def test_product_neutral_control_plane_rewrites_approves_and_executes() -> None:
    presented = asyncio.Event()
    approval_requests: list[ApprovalRequest] = []
    audit_events: list[dict[str, object]] = []
    executed: list[_ToolState] = []

    class Presenter:
        async def present(self, request: ApprovalRequest) -> None:
            approval_requests.append(request)
            presented.set()

    class PublishPolicy:
        def evaluate(self, subject):
            assert isinstance(subject, ToolPolicySubject)
            assert subject.arguments["normalized"] is True
            return PolicyDecision.ask(
                "Publishing requires review",
                code="publish_requires_review",
            )

    broker = ApprovalBroker(fallback=HeadlessApprovalResolver(mode="deny"))
    broker.set_presenter(Presenter())
    api = ExtensionContributionAPI(
        name="publication-controls",
        source_path=Path("/opt/product/extensions/publication-controls.py"),
    )

    def normalize_tool_call(event: _ToolState, context: object) -> _ToolState:
        del context
        return {
            "tool_name": event["tool_name"],
            "arguments": {**event["arguments"], "normalized": True},
        }

    api.on("tool_call", normalize_tool_call, route_id="normalize")
    api.register_policy("publish-review", PublishPolicy())
    api.register_approval("interactive", broker)
    extension = api.build_loaded_extension()

    async def run() -> None:
        diagnostics: list[DiagnosticDraft] = []
        plan = ExtensionRoutePlan.from_extensions(
            [extension],
            diagnostics=diagnostics,
        )
        router = ExtensionRouter(plan, diagnostics=diagnostics)
        initial: _ToolState = {
            "tool_name": "publish",
            "arguments": {"artifact": "quarterly-review.pptx"},
        }

        def reduce_tool_call(
            state: _ToolState,
            result: object,
            route: ResolvedExtensionRoute,
        ) -> RouteStep[_ToolState]:
            del state, route
            return RouteStep(cast(_ToolState, result))

        routed = await router.intercept(
            "tool_call",
            initial,
            event_factory=lambda state, route: state,
            reducer=reduce_tool_call,
            context_factory=lambda loaded: {"extension": loaded.name},
        )
        controls = resolve_control_contributions(
            [extension],
            diagnostics=diagnostics,
        )
        assert controls.selected_approval_record is controls.approval_records[0]

        state = routed.state
        policy = PolicyEvaluatorChain(
            controls.policy_evaluators,
            strategy="most_restrictive",
        )
        enforcement = asyncio.create_task(
            enforce_tool_policy(
                policy,
                tool_name=state["tool_name"],
                arguments=state["arguments"],
                approval_resolver=controls.approval_resolver,
                tool_call_id="publish-1",
                audit_sink=audit_events.append,
            )
        )

        await presented.wait()
        assert not enforcement.done()
        action_id = approval_requests[0].action_id
        assert action_id is not None
        assert broker.resolve_request(action_id, ApprovalDecision.allow())
        await enforcement

        executed.append(state)
        assert diagnostics == []

    asyncio.run(run())

    assert executed == [
        {
            "tool_name": "publish",
            "arguments": {
                "artifact": "quarterly-review.pptx",
                "normalized": True,
            },
        }
    ]
    assert [event["type"] for event in audit_events] == [
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
    ]
    assert audit_events[1]["action_id"] == audit_events[2]["action_id"]
