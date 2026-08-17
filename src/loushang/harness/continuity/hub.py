"""Bounded federation over already admitted continuity Providers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loushang.harness.continuity.composition import ExperienceComposition
from loushang.harness.continuity.provider import (
    ContinuityDeletionProvider,
    ContinuityProvider,
    PreparedActivationLease,
)
from loushang.harness.continuity.types import (
    ContinuityDiagnostic,
    ContinuityIndexState,
    ContinuityPage,
    ContinuityPreview,
    ContinuityQuery,
    ContinuitySummary,
    ContinuityTarget,
    ProviderPage,
    ProviderPageState,
    ProviderQuery,
)

_CURSOR_SCHEMA_VERSION = 1
_MAX_CURSOR_BYTES = 32_768
_INDEX_STATE_RANK: dict[ContinuityIndexState, int] = {
    "fresh": 0,
    "unknown": 1,
    "stale": 2,
    "rebuilding": 3,
    "unavailable": 4,
}


class InvalidContinuityCursor(ValueError):
    """Raised when a composite cursor is malformed or belongs to another query."""


@dataclass(frozen=True)
class _ProviderCursor:
    cursor: str | None
    index_generation: str | None
    query_snapshot: str | None


@dataclass(frozen=True)
class _QueryResult:
    provider: ContinuityProvider
    page: ProviderPage | None
    diagnostic: ContinuityDiagnostic | None


class ContinuityHub:
    """Query, merge, preview, and route admitted Providers without Domain imports."""

    def __init__(
        self,
        composition: ExperienceComposition,
        *,
        cursor_secret: bytes | None = None,
        provider_timeout: float = 5.0,
        concurrency_limit: int = 8,
        cursor_ttl: float = 900.0,
    ) -> None:
        if provider_timeout <= 0:
            raise ValueError("provider_timeout must be positive")
        if concurrency_limit < 1:
            raise ValueError("concurrency_limit must be at least 1")
        if cursor_ttl <= 0:
            raise ValueError("cursor_ttl must be positive")
        self._composition = composition
        self._providers = {
            bound.provider.descriptor.provider_id: bound.provider
            for bound in composition.continuity_providers
        }
        self._cursor_secret = cursor_secret or secrets.token_bytes(32)
        self._provider_timeout = provider_timeout
        self._concurrency_limit = concurrency_limit
        self._cursor_ttl = cursor_ttl
        self._composition_fingerprint = self._fingerprint_composition(composition)

    @property
    def composition(self) -> ExperienceComposition:
        return self._composition

    async def query(self, request: ContinuityQuery) -> ContinuityPage:
        providers = self._select_providers(request)
        query_hash = self._query_hash(request)
        previous = self._decode_cursor(
            request.cursor,
            query_hash=query_hash,
            provider_ids=tuple(
                provider.descriptor.provider_id for provider in providers
            ),
        )
        semaphore = asyncio.Semaphore(self._concurrency_limit)

        async def query_provider(provider: ContinuityProvider) -> _QueryResult:
            provider_id = provider.descriptor.provider_id
            provider_cursor = previous.get(
                provider_id,
                _ProviderCursor(None, None, None),
            )
            provider_request = ProviderQuery(
                text=request.text,
                sort_id=request.sort_id,
                descending=request.descending,
                limit=request.page_size,
                cursor=provider_cursor.cursor,
            )
            try:
                async with semaphore:
                    page = await asyncio.wait_for(
                        provider.query(provider_request),
                        timeout=self._provider_timeout,
                    )
                self._validate_provider_page(provider, page)
                return _QueryResult(provider=provider, page=page, diagnostic=None)
            except Exception as exc:
                return _QueryResult(
                    provider=provider,
                    page=None,
                    diagnostic=ContinuityDiagnostic(
                        code="continuity_provider_query_failed",
                        message=str(exc) or type(exc).__name__,
                        provider_id=provider_id,
                    ),
                )

        results = await asyncio.gather(*(query_provider(item) for item in providers))
        diagnostics: list[ContinuityDiagnostic] = []
        pages: dict[str, ProviderPage] = {}
        states: dict[str, ProviderPageState] = {}
        restart_diagnostics: list[ContinuityDiagnostic] = []
        for result in results:
            provider_id = result.provider.descriptor.provider_id
            if result.diagnostic is not None:
                diagnostics.append(result.diagnostic)
                continue
            assert result.page is not None
            expected = previous.get(provider_id)
            if (
                expected is not None
                and expected.index_generation is not None
                and (
                    expected.index_generation != result.page.index_generation
                    or expected.query_snapshot != result.page.query_snapshot
                )
            ):
                restart_diagnostics.append(
                    ContinuityDiagnostic(
                        code="continuity_cursor_snapshot_changed",
                        message=(
                            "The provider index generation or query snapshot changed; "
                            "restart this query."
                        ),
                        provider_id=provider_id,
                    )
                )
                continue
            pages[provider_id] = result.page
            diagnostics.extend(result.page.diagnostics)
            states[provider_id] = ProviderPageState(
                index_state=result.page.index_state,
                index_generation=result.page.index_generation,
                query_snapshot=result.page.query_snapshot,
                diagnostic=(
                    result.page.diagnostics[0] if result.page.diagnostics else None
                ),
            )

        if restart_diagnostics:
            diagnostics.extend(restart_diagnostics)
            return ContinuityPage(
                items=(),
                next_cursor=None,
                provider_diagnostics=tuple(diagnostics),
                partial=True,
                ordering_complete=False,
                provider_states=states,
                aggregate_index_state=self._aggregate_index_state(states),
                restart_required=True,
            )

        candidates: list[tuple[ContinuitySummary, str]] = []
        for provider_id, page in pages.items():
            candidates.extend((item.summary, item.after_cursor) for item in page.items)
        candidates.sort(
            key=lambda item: self._summary_sort_key(
                item[0],
                sort_id=request.sort_id,
                descending=request.descending,
            )
        )
        emitted = candidates[: request.page_size]

        next_provider_states = dict(previous)
        emitted_provider_ids: set[str] = set()
        for summary, after_cursor in emitted:
            provider_id = summary.target.provider_id
            page = pages[provider_id]
            next_provider_states[provider_id] = _ProviderCursor(
                cursor=after_cursor,
                index_generation=page.index_generation,
                query_snapshot=page.query_snapshot,
            )
            emitted_provider_ids.add(provider_id)
        for provider_id, page in pages.items():
            if provider_id not in next_provider_states:
                next_provider_states[provider_id] = _ProviderCursor(
                    cursor=None,
                    index_generation=page.index_generation,
                    query_snapshot=page.query_snapshot,
                )

        partial = bool(diagnostics and any(result.page is None for result in results))
        has_unconsumed = len(candidates) > len(emitted)
        has_more = has_unconsumed or any(
            page.has_more and provider_id in emitted_provider_ids
            for provider_id, page in pages.items()
        )
        next_cursor = None
        if has_more and not partial:
            next_cursor = self._encode_cursor(
                query_hash=query_hash,
                provider_ids=tuple(
                    provider.descriptor.provider_id for provider in providers
                ),
                provider_states=next_provider_states,
            )
        return ContinuityPage(
            items=tuple(summary for summary, _cursor in emitted),
            next_cursor=next_cursor,
            provider_diagnostics=tuple(diagnostics),
            partial=partial,
            ordering_complete=not partial,
            provider_states=states,
            aggregate_index_state=self._aggregate_index_state(states),
        )

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        provider = self._provider_for_target(target)
        return await asyncio.wait_for(
            provider.preview(target),
            timeout=self._provider_timeout,
        )

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> PreparedActivationLease:
        provider = self._provider_for_target(target)
        return await asyncio.wait_for(
            provider.prepare(target),
            timeout=self._provider_timeout,
        )

    async def delete(self, target: ContinuityTarget) -> bool:
        """Delete a target only when its owning Provider explicitly supports it."""

        provider = self._provider_for_target(target)
        if not isinstance(provider, ContinuityDeletionProvider):
            raise RuntimeError("The selected continuity item cannot be deleted")
        return await asyncio.wait_for(
            provider.delete(target),
            timeout=self._provider_timeout,
        )

    def _select_providers(
        self,
        request: ContinuityQuery,
    ) -> tuple[ContinuityProvider, ...]:
        if request.provider_ids:
            unknown = set(request.provider_ids) - set(self._providers)
            if unknown:
                raise ValueError(
                    "unknown continuity provider IDs: " + ", ".join(sorted(unknown))
                )
            candidates = tuple(
                self._providers[provider_id] for provider_id in request.provider_ids
            )
        else:
            candidates = tuple(self._providers.values())
        if request.domain_ids:
            selected_domains = set(request.domain_ids)
            candidates = tuple(
                provider
                for provider in candidates
                if selected_domains.intersection(provider.descriptor.domain_ids)
            )
        unsupported = tuple(
            provider.descriptor.provider_id
            for provider in candidates
            if request.sort_id not in provider.descriptor.supported_sorts
        )
        if unsupported:
            raise ValueError(
                f"sort {request.sort_id!r} is not supported by Providers: "
                + ", ".join(unsupported)
            )
        return candidates

    def _validate_provider_page(
        self,
        provider: ContinuityProvider,
        page: ProviderPage,
    ) -> None:
        if not isinstance(page, ProviderPage):
            raise TypeError("continuity providers must return ProviderPage values")
        descriptor = provider.descriptor
        provider_domains = set(descriptor.domain_ids)
        for item in page.items:
            summary = item.summary
            if summary.target.provider_id != descriptor.provider_id:
                raise ValueError("provider returned a target owned by another provider")
            if not set(summary.domain_ids).issubset(provider_domains):
                raise ValueError("provider returned a summary for an undeclared Domain")

    def _provider_for_target(self, target: ContinuityTarget) -> ContinuityProvider:
        try:
            return self._providers[target.provider_id]
        except KeyError as exc:
            raise ValueError(
                f"unknown continuity provider ID: {target.provider_id}"
            ) from exc

    @staticmethod
    def _summary_sort_key(
        summary: ContinuitySummary,
        *,
        sort_id: str,
        descending: bool,
    ) -> tuple[int, float, str, str]:
        raw = summary.updated_at if sort_id == "updated" else summary.created_at
        if raw is None:
            return (1, 0.0, summary.target.opaque_id, summary.target.provider_id)
        timestamp = _parse_timestamp(raw)
        sort_value = -timestamp if descending else timestamp
        return (
            0,
            sort_value,
            summary.target.opaque_id,
            summary.target.provider_id,
        )

    def _query_hash(self, request: ContinuityQuery) -> str:
        payload = {
            "text": request.text,
            "provider_ids": list(request.provider_ids),
            "domain_ids": list(request.domain_ids),
            "sort_id": request.sort_id,
            "descending": request.descending,
            "page_size": request.page_size,
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()

    @staticmethod
    def _fingerprint_composition(composition: ExperienceComposition) -> str:
        providers: list[dict[str, Any]] = []
        for bound in composition.continuity_providers:
            descriptor = bound.provider.descriptor
            providers.append(
                {
                    "provider_id": descriptor.provider_id,
                    "experience_id": descriptor.experience_id,
                    "domain_ids": list(descriptor.domain_ids),
                    "implementation_version": descriptor.implementation_version,
                    "profile_version": descriptor.profile_version,
                    "source": bound.provenance.source,
                    "layer_id": bound.provenance.layer_id,
                    "implementation": (bound.provenance.selection.implementation),
                }
            )
        payload = {
            "experience_id": composition.experience.experience_id,
            "providers": providers,
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()

    def _encode_cursor(
        self,
        *,
        query_hash: str,
        provider_ids: tuple[str, ...],
        provider_states: dict[str, _ProviderCursor],
    ) -> str:
        payload = {
            "v": _CURSOR_SCHEMA_VERSION,
            "exp": int(time.time() + self._cursor_ttl),
            "query": query_hash,
            "composition": self._composition_fingerprint,
            "providers": list(provider_ids),
            "states": {
                provider_id: {
                    "cursor": state.cursor,
                    "generation": state.index_generation,
                    "snapshot": state.query_snapshot,
                }
                for provider_id, state in provider_states.items()
                if provider_id in provider_ids
            },
        }
        encoded_payload = _urlsafe_encode(_canonical_json(payload))
        signature = hmac.new(
            self._cursor_secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_urlsafe_encode(signature)}"

    def _decode_cursor(
        self,
        cursor: str | None,
        *,
        query_hash: str,
        provider_ids: tuple[str, ...],
    ) -> dict[str, _ProviderCursor]:
        if cursor is None:
            return {}
        if len(cursor.encode("utf-8")) > _MAX_CURSOR_BYTES:
            raise InvalidContinuityCursor("continuity cursor is too large")
        try:
            encoded_payload, encoded_signature = cursor.split(".", maxsplit=1)
            signature = _urlsafe_decode(encoded_signature)
            expected_signature = hmac.new(
                self._cursor_secret,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected_signature):
                raise InvalidContinuityCursor("continuity cursor signature is invalid")
            payload = json.loads(_urlsafe_decode(encoded_payload))
        except InvalidContinuityCursor:
            raise
        except Exception as exc:
            raise InvalidContinuityCursor("continuity cursor is malformed") from exc
        if not isinstance(payload, dict) or payload.get("v") != _CURSOR_SCHEMA_VERSION:
            raise InvalidContinuityCursor("continuity cursor schema is unsupported")
        if payload.get("exp", 0) < int(time.time()):
            raise InvalidContinuityCursor("continuity cursor has expired")
        if payload.get("query") != query_hash:
            raise InvalidContinuityCursor(
                "continuity cursor belongs to a different query"
            )
        if payload.get("composition") != self._composition_fingerprint:
            raise InvalidContinuityCursor(
                "continuity cursor belongs to a different Experience composition"
            )
        if payload.get("providers") != list(provider_ids):
            raise InvalidContinuityCursor(
                "continuity cursor belongs to a different Provider set"
            )
        raw_states = payload.get("states")
        if not isinstance(raw_states, dict):
            raise InvalidContinuityCursor("continuity cursor states are malformed")
        states: dict[str, _ProviderCursor] = {}
        for provider_id, raw_state in raw_states.items():
            if provider_id not in provider_ids or not isinstance(raw_state, dict):
                raise InvalidContinuityCursor(
                    "continuity cursor contains an invalid Provider state"
                )
            values = (
                raw_state.get("cursor"),
                raw_state.get("generation"),
                raw_state.get("snapshot"),
            )
            if any(
                value is not None and not isinstance(value, str) for value in values
            ):
                raise InvalidContinuityCursor(
                    "continuity cursor Provider state is malformed"
                )
            states[provider_id] = _ProviderCursor(*values)
        return states

    @staticmethod
    def _aggregate_index_state(
        states: dict[str, ProviderPageState],
    ) -> ContinuityIndexState:
        if not states:
            return "unavailable"
        return max(
            (state.index_state for state in states.values()),
            key=_INDEX_STATE_RANK.__getitem__,
        )


def _parse_timestamp(value: str) -> float:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("continuity timestamps must use RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("continuity timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc).timestamp()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


__all__ = ["ContinuityHub", "InvalidContinuityCursor"]
