from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from loushang.harness.continuity import (
    CallbackPreparedActivationLease,
    ContinuityHub,
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuityProviderDescriptor,
    ContinuityQuery,
    ContinuitySummary,
    ContinuityTarget,
    ExperienceComposition,
    ExperienceDescriptor,
    InvalidContinuityCursor,
    ProviderPage,
    ProviderPageItem,
    ProviderQuery,
)
from loushang.harness.continuity.composition import BoundContinuityProvider
from loushang.harness.runtime import (
    ProductRuntimePlan,
    ResolvedRuntimeSelection,
    RuntimeCapabilitySelection,
    RuntimeProfileResolver,
)

_NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


def _summary(provider_id: str, item: str, age: int) -> ContinuitySummary:
    timestamp = (_NOW - timedelta(minutes=age)).isoformat()
    return ContinuitySummary(
        target=ContinuityTarget(
            provider_id=provider_id,
            opaque_id=item,
            revision=f"rev-{item}",
        ),
        domain_ids=(provider_id.split(".", maxsplit=1)[0],),
        primary_domain_id=provider_id.split(".", maxsplit=1)[0],
        title=item,
        updated_at=timestamp,
        created_at=timestamp,
        excerpt=f"Summary for {item}",
    )


@dataclass
class _Provider:
    provider_id: str
    summaries: tuple[ContinuitySummary, ...]
    generation: str = "generation-1"
    snapshot: str = "snapshot-1"
    fail: bool = False
    requests: list[ProviderQuery] = field(default_factory=list)

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        domain = self.provider_id.split(".", maxsplit=1)[0]
        return ContinuityProviderDescriptor(
            provider_id=self.provider_id,
            experience_id="studio",
            domain_ids=(domain,),
            primary_domain_id=domain,
            label=self.provider_id,
            supported_sorts=("updated", "created"),
        )

    async def query(self, request: ProviderQuery) -> ProviderPage:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("provider offline")
        start = int(request.cursor or 0)
        end = min(start + request.limit, len(self.summaries))
        return ProviderPage(
            items=tuple(
                ProviderPageItem(summary=summary, after_cursor=str(index + 1))
                for index, summary in enumerate(
                    self.summaries[start:end],
                    start=start,
                )
            ),
            has_more=end < len(self.summaries),
            index_state="fresh",
            index_generation=self.generation,
            query_snapshot=self.snapshot,
        )

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        return ContinuityPreview(
            target=target,
            revision=target.revision,
            heading=target.opaque_id,
            sections=(ContinuityPreviewSection(kind="text", text="portable preview"),),
        )

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> CallbackPreparedActivationLease:
        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=lambda: target.opaque_id,
        )


def _hub(
    *providers: _Provider,
    cursor_ttl: float = 900.0,
) -> ContinuityHub:
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(product_id="studio", slots=())
    )
    bound = tuple(
        BoundContinuityProvider(
            provider=provider,
            provenance=ResolvedRuntimeSelection(
                selection=RuntimeCapabilitySelection(
                    slot="continuity.provider_packs",
                    implementation=f"test-{index}",
                    implementation_version=1,
                ),
                source="product",
                layer_id="product:studio",
                layer_priority=0,
            ),
        )
        for index, provider in enumerate(providers)
    )
    return ContinuityHub(
        ExperienceComposition(
            experience=ExperienceDescriptor(
                experience_id="studio",
                label="Studio",
                domain_ids=tuple(
                    dict.fromkeys(
                        provider.provider_id.split(".", maxsplit=1)[0]
                        for provider in providers
                    )
                ),
            ),
            capability_profile=profile,
            continuity_providers=bound,
        ),
        cursor_secret=b"test-secret",
        cursor_ttl=cursor_ttl,
    )


def test_federated_keyset_paging_does_not_skip_unemitted_items() -> None:
    asyncio.run(_federated_keyset_paging_does_not_skip_unemitted_items())


async def _federated_keyset_paging_does_not_skip_unemitted_items() -> None:
    coding = _Provider(
        "coding.sessions",
        (
            _summary("coding.sessions", "coding-10", 0),
            _summary("coding.sessions", "coding-08", 2),
            _summary("coding.sessions", "coding-06", 4),
        ),
    )
    design = _Provider(
        "design.canvases",
        (
            _summary("design.canvases", "design-09", 1),
            _summary("design.canvases", "design-07", 3),
            _summary("design.canvases", "design-05", 5),
        ),
    )
    hub = _hub(coding, design)
    cursor: str | None = None
    seen: list[str] = []

    while True:
        page = await hub.query(ContinuityQuery(page_size=2, cursor=cursor))
        seen.extend(item.target.opaque_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == [
        "coding-10",
        "design-09",
        "coding-08",
        "design-07",
        "coding-06",
        "design-05",
    ]
    assert [request.cursor for request in coding.requests] == [None, "1", "2"]
    assert [request.cursor for request in design.requests] == [None, "1", "2"]


def test_failed_provider_marks_page_partial_and_withholds_canonical_cursor() -> None:
    asyncio.run(_failed_provider_marks_page_partial_and_withholds_canonical_cursor())


async def _failed_provider_marks_page_partial_and_withholds_canonical_cursor() -> None:
    coding = _Provider(
        "coding.sessions",
        (_summary("coding.sessions", "coding-1", 0),),
    )
    design = _Provider(
        "design.canvases",
        (_summary("design.canvases", "design-1", 1),),
        fail=True,
    )

    page = await _hub(coding, design).query(ContinuityQuery(page_size=1))

    assert [item.target.opaque_id for item in page.items] == ["coding-1"]
    assert page.partial is True
    assert page.ordering_complete is False
    assert page.next_cursor is None
    assert page.provider_diagnostics[0].provider_id == "design.canvases"


def test_provider_generation_change_returns_explicit_restart() -> None:
    asyncio.run(_provider_generation_change_returns_explicit_restart())


async def _provider_generation_change_returns_explicit_restart() -> None:
    coding = _Provider(
        "coding.sessions",
        (
            _summary("coding.sessions", "coding-2", 0),
            _summary("coding.sessions", "coding-1", 1),
        ),
    )
    hub = _hub(coding)
    first = await hub.query(ContinuityQuery(page_size=1))
    assert first.next_cursor is not None
    coding.generation = "generation-2"

    second = await hub.query(ContinuityQuery(page_size=1, cursor=first.next_cursor))

    assert second.restart_required is True
    assert second.next_cursor is None
    assert second.items == ()
    assert second.provider_diagnostics[-1].code == (
        "continuity_cursor_snapshot_changed"
    )


def test_cursor_is_bound_to_query_and_composition() -> None:
    asyncio.run(_cursor_is_bound_to_query_and_composition())


async def _cursor_is_bound_to_query_and_composition() -> None:
    provider = _Provider(
        "coding.sessions",
        (
            _summary("coding.sessions", "coding-2", 0),
            _summary("coding.sessions", "coding-1", 1),
        ),
    )
    hub = _hub(provider)
    first = await hub.query(ContinuityQuery(page_size=1))
    assert first.next_cursor is not None

    with pytest.raises(InvalidContinuityCursor, match="different query"):
        await hub.query(
            ContinuityQuery(
                text="changed",
                page_size=1,
                cursor=first.next_cursor,
            )
        )

    design = _Provider(
        "design.canvases",
        (_summary("design.canvases", "design-1", 2),),
    )
    with pytest.raises(InvalidContinuityCursor, match="Experience composition"):
        await _hub(provider, design).query(
            ContinuityQuery(page_size=1, cursor=first.next_cursor)
        )


def test_cursor_expiry_is_explicit(monkeypatch) -> None:
    provider = _Provider(
        "coding.sessions",
        (
            _summary("coding.sessions", "coding-2", 0),
            _summary("coding.sessions", "coding-1", 1),
        ),
    )
    now = [1000.0]
    monkeypatch.setattr(
        "loushang.harness.continuity.hub.time.time",
        lambda: now[0],
    )
    hub = _hub(provider, cursor_ttl=1.0)

    async def scenario() -> None:
        first = await hub.query(ContinuityQuery(page_size=1))
        assert first.next_cursor is not None
        now[0] = 1002.0
        with pytest.raises(InvalidContinuityCursor, match="expired"):
            await hub.query(ContinuityQuery(page_size=1, cursor=first.next_cursor))

    asyncio.run(scenario())


def test_preview_and_prepare_route_only_by_provider_qualified_target() -> None:
    asyncio.run(_preview_and_prepare_route_only_by_provider_qualified_target())


async def _preview_and_prepare_route_only_by_provider_qualified_target() -> None:
    provider = _Provider(
        "coding.sessions",
        (_summary("coding.sessions", "coding-1", 0),),
    )
    hub = _hub(provider)
    target = provider.summaries[0].target

    preview = await hub.preview(target)
    lease = await hub.prepare(target)

    assert preview.heading == "coding-1"
    assert await lease.consume() == "coding-1"
    with pytest.raises(ValueError, match="unknown continuity provider"):
        await hub.preview(ContinuityTarget(provider_id="other.sessions", opaque_id="1"))
