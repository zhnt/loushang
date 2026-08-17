"""Complete-once approval broker and interactive resolver."""


from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Any

from loushang.harness.approval.grants import (
    ApprovalPermission,
    ApprovalPermissionsSnapshot,
    InMemoryApprovalGrantStore,
)
from loushang.harness.approval.ports import (
    ApprovalPayloadProjector,
    ApprovalPresenter,
    ApprovalResolver,
)
from loushang.harness.approval.requests import (
    ApprovalDecision,
    ApprovalGrantProposal,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalRequestCollisionError,
    ApprovalScope,
    PolicyAmendmentScope,
    _request_amendment,
    _validate_approval_decision,
    approval_request_to_dict,
    ensure_approval_action_id,
)
from loushang.harness.approval.resolvers import resolve_approval
from loushang.harness.approval.rules import ApprovalPolicyRuleStore


@dataclass
class _PendingApproval:
    request: ApprovalRequest
    future: asyncio.Future[ApprovalDecision] = field(compare=False, repr=False)
    accepting_presenter_results: bool = field(default=True, compare=False)

class ApprovalBroker:
    """Event-loop-confined lifecycle manager for interactive approvals."""

    def __init__(
        self,
        *,
        fallback: ApprovalResolver,
        timeout_seconds: float | None = None,
    ) -> None:
        if fallback is self:
            raise ValueError("ApprovalBroker cannot use itself as fallback")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._fallback = fallback
        self._timeout_seconds = timeout_seconds
        self._presenter: ApprovalPresenter | None = None
        self._pending: dict[str, _PendingApproval] = {}
        self._presented_action_ids: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._disposed = False

    def set_presenter(self, presenter: ApprovalPresenter | None) -> None:
        if self._disposed and presenter is not None:
            raise RuntimeError("ApprovalBroker is disposed")
        self._presenter = presenter

    def pending_requests(self) -> tuple[ApprovalRequest, ...]:
        return tuple(pending.request for pending in self._pending.values())

    def pending_request(self, action_id: str) -> ApprovalRequest | None:
        pending = self._pending.get(action_id)
        return pending.request if pending is not None else None

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        request = ensure_approval_action_id(request)
        action_id = request.action_id
        assert action_id is not None
        if action_id in self._pending:
            raise ApprovalRequestCollisionError(action_id)
        if self._disposed or self._presenter is None:
            return await resolve_approval(self._fallback, request)
        if action_id in self._presented_action_ids:
            raise ApprovalRequestCollisionError(action_id)

        loop = self._capture_loop()
        future: asyncio.Future[ApprovalDecision] = loop.create_future()
        pending = _PendingApproval(request=request, future=future)
        self._presented_action_ids.add(action_id)
        self._pending[action_id] = pending
        presenter = self._presenter
        assert presenter is not None
        try:
            waiter = self._present_and_wait(
                presenter,
                request,
                future,
            )
            if self._timeout_seconds is None:
                return await waiter
            waiter_task = asyncio.create_task(waiter)
            try:
                done, _ = await asyncio.wait(
                    (waiter_task,),
                    timeout=self._timeout_seconds,
                )
                if waiter_task in done:
                    return waiter_task.result()
                pending.accepting_presenter_results = False
                await _cancel_child_task(waiter_task)
                if future.done():
                    return future.result()
                return await self._resolve_fallback_or_pending_decision(
                    request,
                    future,
                )
            finally:
                if not waiter_task.done():
                    await _cancel_child_task(waiter_task)
        finally:
            current = self._pending.get(action_id)
            if current is pending:
                self._pending.pop(action_id, None)
            if not future.done():
                future.cancel()
            _dismiss_presented_request(presenter, request)

    async def _present_and_wait(
        self,
        presenter: ApprovalPresenter,
        request: ApprovalRequest,
        future: asyncio.Future[ApprovalDecision],
    ) -> ApprovalDecision:
        presented = presenter.present(request)
        if not inspect.isawaitable(presented):
            return await asyncio.shield(future)

        presentation_task = asyncio.ensure_future(presented)
        try:
            done, _ = await asyncio.wait(
                (presentation_task, future),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if presentation_task in done:
                await presentation_task
                return await asyncio.shield(future)
            return future.result()
        finally:
            if not presentation_task.done():
                _cancel_detached_presentation(
                    presentation_task,
                    presenter=presenter,
                    request=request,
                )

    async def _resolve_fallback_or_pending_decision(
        self,
        request: ApprovalRequest,
        future: asyncio.Future[ApprovalDecision],
    ) -> ApprovalDecision:
        fallback_task = asyncio.create_task(resolve_approval(self._fallback, request))
        try:
            done, _ = await asyncio.wait(
                (fallback_task, future),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if future in done:
                if fallback_task in done:
                    with suppress(asyncio.CancelledError, Exception):
                        fallback_task.result()
                return future.result()
            return fallback_task.result()
        finally:
            if not fallback_task.done():
                _cancel_detached_task(fallback_task)

    def resolve_request(
        self,
        action_id: str,
        decision: ApprovalDecision,
    ) -> bool:
        _validate_approval_decision(decision)
        self._require_loop_if_pending()
        pending = self._pending.get(action_id)
        if (
            pending is None
            or not pending.accepting_presenter_results
            or pending.future.done()
        ):
            return False
        pending.future.set_result(decision)
        return True

    def cancel_request(
        self,
        action_id: str,
        decision: ApprovalDecision,
    ) -> bool:
        _validate_approval_decision(decision)
        self._require_loop_if_pending()
        pending = self._pending.get(action_id)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(decision)
        return True

    def cancel_all(self, decision: ApprovalDecision) -> int:
        _validate_approval_decision(decision)
        self._require_loop_if_pending()
        completed = 0
        for pending in tuple(self._pending.values()):
            if pending.future.done():
                continue
            pending.future.set_result(decision)
            completed += 1
        return completed

    def cancel_actor(self, actor_id: str, decision: ApprovalDecision) -> int:
        """Resolve pending requests for one actor without touching siblings."""

        _validate_approval_decision(decision)
        self._require_loop_if_pending()
        completed = 0
        for pending in tuple(self._pending.values()):
            if (
                pending.request.actor_id != actor_id
                or pending.future.done()
            ):
                continue
            pending.future.set_result(decision)
            completed += 1
        return completed

    def dispose(self, decision: ApprovalDecision) -> int:
        _validate_approval_decision(decision)
        if self._disposed:
            return 0
        self._require_loop_if_pending()
        self._disposed = True
        self._presenter = None
        completed = self.cancel_all(decision)
        self._presented_action_ids.clear()
        return completed

    def _capture_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            if self._pending:
                raise RuntimeError("ApprovalBroker cannot be used across event loops")
            self._loop = loop
        return loop

    def _require_loop_if_pending(self) -> None:
        if not self._pending:
            return
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            raise RuntimeError(
                "ApprovalBroker must be resolved on its owning event loop"
            )

@dataclass(frozen=True)
class _CallbackApprovalPresenter(ApprovalPresenter):
    callback: Callable[[dict[str, object]], Awaitable[None] | None]
    payload_projector: ApprovalPayloadProjector
    dismiss_callback: Callable[[str], Awaitable[None] | None] | None = None

    async def present(self, request: ApprovalRequest) -> None:
        payload = dict(self.payload_projector(request))
        result = self.callback(payload)
        if inspect.isawaitable(result):
            await result

    def dismiss(self, request: ApprovalRequest) -> Awaitable[None] | None:
        if self.dismiss_callback is None or request.action_id is None:
            return None
        return self.dismiss_callback(request.action_id)

@dataclass
class InteractiveApprovalResolver:
    """Reusable callback-backed approval lifecycle over :class:`ApprovalBroker`."""

    fallback: ApprovalResolver
    timeout_seconds: float | None = None
    payload_projector: ApprovalPayloadProjector = approval_request_to_dict
    grant_store: InMemoryApprovalGrantStore = field(
        default_factory=InMemoryApprovalGrantStore
    )
    policy_stores: Mapping[
        PolicyAmendmentScope,
        ApprovalPolicyRuleStore,
    ] = field(default_factory=dict)
    _broker: ApprovalBroker = field(init=False, repr=False)
    _request_presenter: Callable[[dict[str, object]], Awaitable[None] | None] | None = (
        field(default=None, init=False, repr=False)
    )
    _request_dismisser: Callable[[str], Awaitable[None] | None] | None = field(
        default=None, init=False, repr=False
    )
    _session_open: bool = field(default=True, init=False, repr=False)
    _session_close_reason: str = field(
        default="Session closed before approval was resolved",
        init=False,
        repr=False,
    )
    _coalesced: dict[
        tuple[str, ApprovalGrantProposal],
        asyncio.Task[ApprovalDecision],
    ] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        stores = dict(self.policy_stores)
        for scope, store in stores.items():
            if scope not in {"project", "user"} or store.scope != scope:
                raise ValueError("approval Policy store scope does not match its key")
        self.policy_stores = stores
        self._broker = ApprovalBroker(
            fallback=self.fallback,
            timeout_seconds=self.timeout_seconds,
        )

    def set_request_presenter(
        self,
        presenter: Callable[[dict[str, object]], Awaitable[None] | None] | None,
        *,
        dismisser: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        if presenter is None and dismisser is not None:
            raise ValueError("dismisser requires a request presenter")
        self._broker.set_presenter(
            _CallbackApprovalPresenter(presenter, self.payload_projector, dismisser)
            if presenter is not None
            else None
        )
        self._request_presenter = presenter
        self._request_dismisser = dismisser

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        if not self._session_open:
            return ApprovalDecision.deny(self._session_close_reason)
        request = replace(
            request,
            policy_amendments=tuple(
                amendment
                for amendment in request.policy_amendments
                if amendment.scope in self.policy_stores
            ),
        )
        granted = self.preauthorize(request)
        if granted is not None:
            return granted
        proposal = request.session_grant or next(
            (
                amendment.grant
                for amendment in request.policy_amendments
            ),
            None,
        )
        if proposal is None:
            return await self._broker.resolve(request)
        key = (request.actor_id, proposal)
        task = self._coalesced.get(key)
        if task is None:
            task = asyncio.create_task(self._broker.resolve(request))
            self._coalesced[key] = task

            def remove(completed: asyncio.Task[ApprovalDecision]) -> None:
                if self._coalesced.get(key) is completed:
                    self._coalesced.pop(key, None)

            task.add_done_callback(remove)
        return await asyncio.shield(task)

    def preauthorize(self, request: ApprovalRequest) -> ApprovalDecision | None:
        grant = self.grant_store.find(request)
        if grant is not None:
            return ApprovalDecision.allow(scope="session", grant_id=grant.grant_id)
        for scope in ("project", "user"):
            store = self.policy_stores.get(scope)
            if store is None:
                continue
            rule = store.find(request)
            if rule is not None:
                return ApprovalDecision.allow_by_policy(
                    rule_id=rule.rule_id,
                    scope=rule.scope,
                )
        return None

    def set_policy_stores(
        self,
        stores: Mapping[PolicyAmendmentScope, ApprovalPolicyRuleStore],
    ) -> None:
        """Bind persistent Policy storage before presenting approval requests."""

        if self._broker.pending_requests():
            raise RuntimeError("cannot replace Policy stores while approvals are pending")
        normalized = dict(stores)
        for scope, store in normalized.items():
            if scope not in {"project", "user"} or store.scope != scope:
                raise ValueError("approval Policy store scope does not match its key")
        self.policy_stores = normalized

    def open_session(self) -> None:
        self._session_open = True

    def permissions_snapshot(self) -> ApprovalPermissionsSnapshot:
        pending = tuple(
            ApprovalPermission(
                kind="pending",
                permission_id=request.action_id or "",
                actor_id=request.actor_id,
                capability=(
                    request.session_grant.capability
                    if request.session_grant is not None
                    else request.tool_name
                ),
                summary=(
                    request.session_grant.summary
                    if request.session_grant is not None
                    else request.reason
                    or f"{request.tool_name} requires approval"
                ),
            )
            for request in self._broker.pending_requests()
            if request.action_id is not None
        )
        grants = tuple(
            ApprovalPermission(
                kind="session",
                permission_id=grant.grant_id,
                actor_id=grant.actor_id,
                capability=grant.proposal.capability,
                summary=grant.proposal.summary,
            )
            for grant in self.grant_store.grants()
        )
        persistent = {
            scope: tuple(
                ApprovalPermission(
                    kind=scope,
                    permission_id=rule.rule_id,
                    actor_id="policy",
                    capability=rule.proposal.capability,
                    summary=rule.proposal.summary,
                )
                for rule in store.rules()
            )
            for scope, store in self.policy_stores.items()
        }
        return ApprovalPermissionsSnapshot(
            pending=pending,
            grants=grants,
            project_rules=persistent.get("project", ()),
            user_rules=persistent.get("user", ()),
        )

    async def represent_request(self, action_id: str) -> bool:
        """Present one still-pending request again after its panel was dismissed."""

        if not self._session_open or self._request_presenter is None:
            return False
        request = self._broker.pending_request(action_id)
        if request is None:
            return False
        presented = self._request_presenter(dict(self.payload_projector(request)))
        if inspect.isawaitable(presented):
            await presented
        return True

    def represent_pending_requests(self) -> int:
        """Replay unresolved requests after the presentation channel is replaced."""

        if not self._session_open or self._request_presenter is None:
            return 0
        presented = 0
        for request in self._broker.pending_requests():
            try:
                result = self._request_presenter(
                    dict(self.payload_projector(request))
                )
            except (asyncio.CancelledError, Exception):
                continue
            if inspect.isawaitable(result):
                task = asyncio.ensure_future(result)
                task.add_done_callback(_consume_detached_result)
            presented += 1
        return presented

    def revoke_grant(self, grant_id: str) -> bool:
        return self.grant_store.revoke(grant_id)

    def revoke_policy_rule(self, rule_id: str) -> bool:
        return any(store.revoke(rule_id) for store in self.policy_stores.values())

    def cancel_actor(
        self,
        actor_id: str,
        reason: str = "Child agent closed before approval was resolved",
    ) -> int:
        """Cancel pending requests owned by one child incarnation."""

        return self._broker.cancel_actor(
            actor_id,
            ApprovalDecision.deny(reason),
        )

    def revoke_actor_grants(self, actor_id: str) -> int:
        """Revoke retained grants owned by one child incarnation."""

        return self.grant_store.revoke_actor(actor_id)

    async def handle_result(
        self,
        action_id: str,
        *,
        outcome: ApprovalOutcome | None = None,
        approved: bool | None = None,
        reason: str | None = None,
        scope: ApprovalScope = "once",
    ) -> bool:
        if outcome is None:
            outcome = (
                "allow_session"
                if approved and scope == "session"
                else "allow_once"
                if approved
                else "deny"
            )
        if outcome not in {
            "allow_once",
            "allow_session",
            "allow_project",
            "allow_user",
            "deny",
            "abort",
        }:
            raise ValueError(f"Unsupported approval outcome: {outcome}")
        if scope not in {"once", "session"}:
            raise ValueError(f"Unsupported approval scope: {scope}")
        request = self._broker.pending_request(action_id)
        if request is None:
            return False
        grant = None
        policy_rule = None
        if outcome == "allow_session":
            if request.session_grant is None:
                return False
            grant = self.grant_store.issue(request)
            decision = ApprovalDecision.allow(
                scope="session",
                grant_id=grant.grant_id if grant is not None else None,
            )
        elif outcome in {"allow_project", "allow_user"}:
            amendment_scope: PolicyAmendmentScope = (
                "project" if outcome == "allow_project" else "user"
            )
            amendment = _request_amendment(request, amendment_scope)
            store = self.policy_stores.get(amendment_scope)
            if amendment is None or store is None:
                return False
            policy_rule = store.issue(request, amendment)
            decision = ApprovalDecision.allow_by_policy(
                rule_id=policy_rule.rule_id,
                scope=policy_rule.scope,
            )
        elif outcome == "allow_once":
            decision = ApprovalDecision.allow()
        elif outcome == "abort":
            decision = ApprovalDecision.abort(reason)
        else:
            decision = ApprovalDecision.deny(reason)
        accepted = self._broker.resolve_request(action_id, decision)
        if not accepted and grant is not None:
            self.grant_store.revoke(grant.grant_id)
        if not accepted and policy_rule is not None:
            store = self.policy_stores.get(policy_rule.scope)
            if store is not None:
                store.revoke(policy_rule.rule_id)
        return accepted

    def close_session(
        self,
        reason: str = "Session closed before approval was resolved",
    ) -> int:
        """Close the current presentation channel without revoking session grants."""

        self._session_open = False
        self._session_close_reason = reason
        return self._broker.cancel_all(ApprovalDecision.deny(reason))

    def end_session(
        self,
        reason: str = "Session closed before approval was resolved",
    ) -> int:
        """Close one Product session and revoke grants owned by that session."""

        completed = self.close_session(reason)
        self.grant_store.clear()
        return completed

    def dispose(
        self, reason: str = "Session closed before approval was resolved"
    ) -> int:
        decision = ApprovalDecision.deny(reason)
        self._session_open = False
        self._session_close_reason = reason
        self._broker.set_presenter(None)
        self._request_presenter = None
        self._request_dismisser = None
        completed = self._broker.dispose(decision)
        self.grant_store.clear()
        return completed

def _cancel_detached_task(task: asyncio.Future[Any]) -> None:
    task.cancel()
    task.add_done_callback(_consume_detached_result)

async def _cancel_child_task(task: asyncio.Future[Any]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise

def _cancel_detached_presentation(
    task: asyncio.Future[Any],
    *,
    presenter: ApprovalPresenter,
    request: ApprovalRequest,
) -> None:
    task.cancel()

    def _finish_presentation(completed: asyncio.Future[Any]) -> None:
        _consume_detached_result(completed)
        _dismiss_presented_request(presenter, request)

    task.add_done_callback(_finish_presentation)

def _dismiss_presented_request(
    presenter: ApprovalPresenter,
    request: ApprovalRequest,
) -> None:
    try:
        dismiss = getattr(presenter, "dismiss", None)
        if not callable(dismiss):
            return
        result = dismiss(request)
        if inspect.isawaitable(result):
            task = asyncio.ensure_future(result)
            task.add_done_callback(_consume_detached_result)
    except asyncio.CancelledError:
        return
    except Exception:
        return

def _consume_detached_result(completed: asyncio.Future[Any]) -> None:
    with suppress(asyncio.CancelledError, Exception):
        completed.result()
