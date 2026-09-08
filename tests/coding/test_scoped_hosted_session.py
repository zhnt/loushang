from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.appserver.protocol import (
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionOpenSpecV1,
)
from loushang.appservice import AppServiceV1
from loushang.appservice.client_scope import ScopedAppServiceV1
from loushang.coding.appservice_adapter import CodingHostedSessionV1
from loushang.harness.approval import ApprovalRequest

from .test_hosted_session import _binding


def test_G16_APPROVAL_real_broker_denies_on_disconnect_and_without_controller(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        binding = await _binding(tmp_path)
        hosted = CodingHostedSessionV1(binding)

        class Resolver:
            async def open_session(self, request):
                return hosted

        service = AppServiceV1(product_id="coding", resolver=Resolver())
        owner = ScopedAppServiceV1(service)
        client = owner.open_client_scope()
        mux = await client.create_mux(MuxCreateV1("approval"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await client.attach_mux(MuxAttachV1(selector))
        identity = hosted.identity
        mux = await client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
            product_id=identity.product_id,
            continuity_id=identity.continuity_id,
            session_id=identity.session_id,
            scope=identity.scope,
            scope_fingerprint=identity.scope_fingerprint,
            title="real approval",
        )))
        await client.attach_mux(MuxAttachV1(selector))
        presented = asyncio.Queue()
        hosted.subscribe(lambda event: (
            presented.put_nowait(event)
            if event.kind is SessionEventKindV1.INTERACTION_REQUESTED else None
        ))
        decisions = []
        try:
            old = asyncio.create_task(binding._approval.resolve(ApprovalRequest(
                tool_name="safe-test", arguments={}, action_id="old-action",
            )))
            decisions.append(old)
            await presented.get()
            await client.close()
            assert (await old).disposition == "deny"

            # This calls the real adapter's event subscriber and ApprovalBroker;
            # no fake listener-exception propagation can stand in for denial.
            unowned = await binding._approval.resolve(ApprovalRequest(
                tool_name="safe-test", arguments={}, action_id="unowned-action",
            ))
            assert unowned.disposition == "deny"
            # This extra diagnostic subscriber sees the request; no client was
            # attached to receive it or gain approval authority.
            await presented.get()

            replacement = owner.open_client_scope()
            attachment = await replacement.attach_mux(MuxAttachV1(selector))
            current = asyncio.create_task(binding._approval.resolve(ApprovalRequest(
                tool_name="safe-test", arguments={}, action_id="new-action",
            )))
            decisions.append(current)
            event = await presented.get()
            await replacement.respond_interaction(InteractionRespondV1(
                attachment.attachment_id, attachment.controller_generation,
                mux.members[0].member_id, event.interaction_id,
                InteractionOutcomeV1.APPROVE,
            ))
            assert (await current).disposition == "allow"
        finally:
            await service.close()
            await asyncio.gather(*decisions, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 20))
