"""Seed canonical Hosted history through the real Coding Product owner."""

from __future__ import annotations

from contextlib import AsyncExitStack

from loushang.ai.types import UserMessage
from loushang.apphost import SessionBindingKeyV1
from loushang.coding import hosted_bootstrap
from loushang.coding.hosted_catalog import (
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.hosted_session import CodingRealHostedSessionFactoryV1


async def seed_hosted_history(
    scope: CodingHostedScopeV1,
    text: str,
    *,
    session_id: str | None = None,
) -> None:
    """Use the same Product selection and startup receipt as Hosted resume."""

    catalog = CodingHostedSessionCatalogV1((scope,))
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(catalog.close)
        factory = CodingRealHostedSessionFactoryV1(
            services_factory=lambda cwd: hosted_bootstrap._services(cwd)
        )
        cleanup.push_async_callback(factory.close)
        identities = await catalog.list_identities((scope.discovery_scope,), limit=256)
        matches = tuple(
            projection
            for projection in identities
            if projection.envelope is not None
            and (session_id is None or projection.envelope.session_id == session_id)
        )
        assert len(matches) == 1
        candidate = await catalog.open_candidate(matches[0].reference)
        cleanup.push_async_callback(candidate.close)
        claimed = await candidate.claim()
        cleanup.push_async_callback(claimed.close)
        identity = claimed.opaque_binding.record.identity
        manager = claimed.opaque_binding.manager_for_construction()
        binding = await factory.create_session(
            binding_key=SessionBindingKeyV1(
                identity.product_id, identity.continuity_id, identity.session_id
            ),
            opaque_session_binding=claimed.opaque_binding,
        )
        cleanup.push_async_callback(binding.close)
        await binding.control.prepare_model_call_runtime()
        await manager.append_message(
            UserMessage(role="user", content=text, timestamp=1.0)
        )
