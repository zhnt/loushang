"""Bounded, pathless discovery presentation over an optional borrowed port."""

from __future__ import annotations

from collections.abc import Callable

from loushang.appserver.client import SessionDiscoveryClientV1
from loushang.appserver.protocol import (
    AppServiceError,
    SessionAvailabilityV1,
    SessionCompatibilityV1,
    SessionDiscoveryCandidateV1,
    SessionIdentityV1,
    SessionListResultV1,
    SessionListV1,
    SessionOpenSpecV1,
    SessionScopeV1,
)
from loushang.tui.cell_width import truncate_to_width
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.input import InputEvent

from ._shell_screen import safe_text
from ._shell_tasks import ShellActions


class SessionPickerV1:
    """One visible page, one in-flight query and one coalesced pending query.

    Listing is observational. Selection only forwards a canonical identity to
    the existing member-open path, which must revalidate admission and storage.
    """

    def __init__(
        self,
        client: SessionDiscoveryClientV1 | None,
        *,
        actions: ShellActions,
        product_id: str,
        scopes: dict[SessionScopeV1, str],
        select: Callable[[SessionOpenSpecV1], None],
    ) -> None:
        self._client, self._actions, self._select = client, actions, select
        self._product_id, self._scopes = product_id, dict(scopes)
        self.scope = next(iter(scopes))
        self.visible = False
        self.page: SessionListResultV1 | None = None
        self.selected: SessionIdentityV1 | None = None
        self.status = ""
        self._generation = 0
        self._pending: tuple[int, SessionListV1] | None = None
        self._running = self._closed = False

    def open(self, scope: str | None = None) -> None:
        if self._closed:
            raise ValueError("picker closed")
        selected = (
            self.scope
            if scope is None
            else SessionScopeV1("user_home" if scope == "global" else scope)
        )
        if selected not in self._scopes:
            raise ValueError("scope unavailable")
        self.visible, self.scope = True, selected
        self._query()

    def dismiss(self) -> None:
        self.visible = False
        self._generation += 1
        self._pending = self.page = self.selected = None

    def close(self) -> None:
        self._closed = True
        self.dismiss()

    def _query(self, continuation: str | None = None) -> None:
        self._generation += 1
        self.page = self.selected = None
        if self._client is None:
            self.status = (
                "discovery_unavailable: explicit identity /resume remains available"
            )
            return
        self.status = "loading"
        self._pending = (
            self._generation,
            SessionListV1(
                self._product_id,
                self.scope,
                self._scopes[self.scope],
                limit=32,
                continuation=continuation,
            ),
        )
        if not self._running:
            try:
                self._actions.submit(self._run)
            except BaseException:
                self._pending = None
                self.status = "query_not_started: r refresh"
                raise
            self._running = True

    async def _run(self) -> None:
        assert self._client is not None
        try:
            while self._pending is not None and not self._closed:
                generation, request = self._pending
                self._pending = None
                try:
                    page = await self._client.list_sessions(request)
                    if (
                        type(page) is not SessionListResultV1
                        or (page.product_id, page.scope, page.scope_fingerprint)
                        != (
                            request.product_id,
                            request.scope,
                            request.scope_fingerprint,
                        )
                        or len(page.candidates) > request.limit
                    ):
                        raise ValueError("invalid discovery response")
                except Exception as error:
                    if generation == self._generation and self.visible:
                        self.status = (
                            error.code.value
                            if isinstance(error, AppServiceError)
                            else "discovery_failed"
                        ) + ": r refresh; no automatic retry"
                    continue
                if generation != self._generation or not self.visible:
                    continue
                self.page = page
                self.selected = page.candidates[0].identity if page.candidates else None
                self.status = (
                    "incomplete: observed rows are unverified, selection disabled"
                    if not page.complete
                    else "empty"
                    if not page.candidates
                    else "select a saved Session"
                )
        finally:
            self._running = False

    def handle(self, event: InputEvent) -> bool:
        if not self.visible:
            return False
        if event.kind == "text":
            # InputReader coalesces adjacent text. Preserve key intent across
            # chunk boundaries, but never interpret bracketed paste as commands.
            for command in event.text:
                if command == "r":
                    self._query()
                elif command == "n" and self.page and self.page.continuation:
                    self._query(self.page.continuation)
            return True
        key = event.key if event.kind == "key" else ""
        if key in {"esc", "escape"}:
            self.dismiss()
        elif key in {"tab", "shift+tab"}:
            scopes = tuple(self._scopes)
            offset = 1 if key == "tab" else -1
            self.scope = scopes[(scopes.index(self.scope) + offset) % len(scopes)]
            self._query()
        elif (
            key in {"up", "down", "home", "end"} and self.page and self.page.candidates
        ):
            identities = [row.identity for row in self.page.candidates]
            index = (
                identities.index(self.selected) if self.selected in identities else 0
            )
            index = (
                0
                if key == "home"
                else len(identities) - 1
                if key == "end"
                else max(
                    0, min(len(identities) - 1, index + (1 if key == "down" else -1))
                )
            )
            self.selected = identities[index]
        elif key == "enter" and self.page and self.page.complete:
            row = next(
                (row for row in self.page.candidates if row.identity == self.selected),
                None,
            )
            if row is not None and self._available(row):
                identity = row.identity
                self._select(
                    SessionOpenSpecV1(
                        identity.product_id,
                        identity.continuity_id,
                        identity.scope,
                        identity.scope_fingerprint,
                        row.title,
                        identity.session_id,
                    )
                )
                self.dismiss()
        return True

    @staticmethod
    def _available(row: SessionDiscoveryCandidateV1) -> bool:
        return (
            row.compatibility is SessionCompatibilityV1.COMPATIBLE
            and row.availability is SessionAvailabilityV1.AVAILABLE
        )

    def render(self, constraints: RenderConstraints) -> RenderResult:
        rows = [
            f"Sessions | {self.scope.value} | Tab scope, r refresh, n next, Esc back",
            self.status,
        ]
        if self.page is not None:
            page = self.page
            if page.omitted_count or not page.omitted_count_exact:
                rows[1] += (
                    f"; omitted {'=' if page.omitted_count_exact else '>='}{page.omitted_count}"
                )
            candidates = page.candidates
            selected = next(
                (
                    i
                    for i, row in enumerate(candidates)
                    if row.identity == self.selected
                ),
                0,
            )
            capacity = max(0, constraints.max_height - len(rows))
            start = max(0, selected - max(0, capacity - 1))
            for row in candidates[start : start + capacity]:
                title = " ".join(safe_text(row.title).split())
                state = (
                    ""
                    if self._available(row)
                    else f" [{row.compatibility.value}/{row.availability.value}]"
                )
                rows.append(
                    f"{'>' if row.identity == self.selected else ' '} {title}{state}"
                )
        return RenderResult.from_lines(
            tuple(
                RenderLine(truncate_to_width(row, max_width=constraints.width))
                for row in rows[: constraints.max_height]
            ),
            constraints=constraints,
        )
