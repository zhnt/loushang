from __future__ import annotations

import asyncio
import inspect
import json
import shlex
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Never, Protocol, TypeAlias, TypeVar
from uuid import uuid4

from loushang.harness.diagnostics.export import redact_text

T = TypeVar("T")
MaybeAwaitable: TypeAlias = T | Awaitable[T]
ApprovalScope = Literal["once", "session"]
PolicyAmendmentScope = Literal["project", "user"]
ApprovalOutcome = Literal[
    "allow_once",
    "allow_session",
    "allow_project",
    "allow_user",
    "deny",
    "abort",
]


@dataclass(frozen=True, slots=True)
class ApprovalGrantProposal:
    """A Policy-generated capability matcher safe to retain for one session."""

    capability: str
    constraints: tuple[tuple[str, str], ...]
    summary: str = field(compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.capability, str) or not self.capability:
            raise ValueError("grant capability must be a non-empty string")
        if not isinstance(self.summary, str) or not self.summary:
            raise ValueError("grant summary must be a non-empty string")
        constraints = tuple(self.constraints)
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
            for key, value in constraints
        ):
            raise ValueError("grant constraints must contain non-empty string pairs")
        if len({key for key, _value in constraints}) != len(constraints):
            raise ValueError("grant constraint keys must be unique")
        object.__setattr__(self, "constraints", tuple(sorted(constraints)))


@dataclass(frozen=True, slots=True)
class PolicyAmendmentProposal:
    """A Policy-authored persistent rule offered for one explicit scope."""

    scope: PolicyAmendmentScope
    grant: ApprovalGrantProposal

    def __post_init__(self) -> None:
        if self.scope not in {"project", "user"}:
            raise ValueError(f"Unsupported policy amendment scope: {self.scope}")
        if not isinstance(self.grant, ApprovalGrantProposal):
            raise TypeError("policy amendment grant must be an ApprovalGrantProposal")


@dataclass(frozen=True, slots=True)
class ApprovalOption:
    """One Policy-generated choice rendered by an approval client."""

    outcome: ApprovalOutcome
    label: str
    shortcut: str
    tone: Literal["allow", "session", "persistent", "deny"] = "allow"


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    arguments: Mapping[str, Any]
    cwd: str | None = None
    reason: str | None = None
    policy_code: str | None = None
    policy_decision: object | None = None
    action_id: str | None = None
    action_fingerprint: str | None = None
    actor_id: str = "root"
    session_grant: ApprovalGrantProposal | None = None
    policy_amendments: tuple[PolicyAmendmentProposal, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise ValueError("ApprovalRequest tool_name must be a non-empty string")
        _validate_optional_string(self.cwd, "ApprovalRequest cwd")
        _validate_optional_string(self.reason, "ApprovalRequest reason")
        _validate_optional_string(self.policy_code, "ApprovalRequest policy_code")
        _validate_optional_string(self.action_id, "ApprovalRequest action_id")
        _validate_optional_string(
            self.action_fingerprint,
            "ApprovalRequest action_fingerprint",
        )
        if self.action_id == "":
            raise ValueError("ApprovalRequest action_id must not be empty")
        if self.action_fingerprint == "":
            raise ValueError("ApprovalRequest action_fingerprint must not be empty")
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise ValueError("ApprovalRequest actor_id must be a non-empty string")
        if self.session_grant is not None and not isinstance(
            self.session_grant,
            ApprovalGrantProposal,
        ):
            raise TypeError(
                "ApprovalRequest session_grant must be an ApprovalGrantProposal"
            )
        amendments = tuple(self.policy_amendments)
        if any(
            not isinstance(amendment, PolicyAmendmentProposal)
            for amendment in amendments
        ):
            raise TypeError(
                "ApprovalRequest policy_amendments must contain "
                "PolicyAmendmentProposal values"
            )
        scopes = [amendment.scope for amendment in amendments]
        if len(scopes) != len(set(scopes)):
            raise ValueError("ApprovalRequest policy amendment scopes must be unique")
        object.__setattr__(self, "policy_amendments", amendments)
        object.__setattr__(
            self,
            "arguments",
            _freeze_mapping(self.arguments),
        )


@dataclass(frozen=True)
class ApprovalDecision:
    disposition: Literal["allow", "deny", "abort"]
    reason: str | None = None
    scope: ApprovalScope = "once"
    grant_id: str | None = None
    policy_rule_id: str | None = None
    policy_scope: PolicyAmendmentScope | None = None

    def __post_init__(self) -> None:
        if self.disposition not in {"allow", "deny", "abort"}:
            raise ValueError(
                f"Unsupported approval decision disposition: {self.disposition}"
            )
        _validate_optional_string(self.reason, "ApprovalDecision reason")
        if self.scope not in {"once", "session"}:
            raise ValueError(f"Unsupported approval decision scope: {self.scope}")
        _validate_optional_string(self.grant_id, "ApprovalDecision grant_id")
        _validate_optional_string(
            self.policy_rule_id,
            "ApprovalDecision policy_rule_id",
        )
        if self.grant_id == "":
            raise ValueError("ApprovalDecision grant_id must not be empty")
        if self.disposition in {"deny", "abort"} and (
            self.scope != "once"
            or self.grant_id is not None
            or self.policy_rule_id is not None
            or self.policy_scope is not None
        ):
            raise ValueError(
                "denied and aborted approval decisions cannot carry authorization"
            )
        if self.policy_rule_id is not None:
            if self.disposition != "allow":
                raise ValueError("policy authorization requires an allowed decision")
            if self.policy_scope not in {"project", "user"}:
                raise ValueError("policy authorization requires its persistent scope")
            if self.scope != "once" or self.grant_id is not None:
                raise ValueError(
                    "policy authorization is distinct from a session approval grant"
                )
        elif self.policy_scope is not None:
            raise ValueError("policy scope requires a policy rule id")
        if self.scope == "session" and self.grant_id is None:
            raise ValueError("session approval decisions require a grant id")
        if self.scope == "once" and self.grant_id is not None:
            raise ValueError("one-shot approval decisions cannot carry a grant id")

    @classmethod
    def allow(
        cls,
        *,
        scope: ApprovalScope = "once",
        grant_id: str | None = None,
    ) -> "ApprovalDecision":
        return cls(disposition="allow", scope=scope, grant_id=grant_id)

    @classmethod
    def deny(cls, reason: str | None = None) -> "ApprovalDecision":
        return cls(disposition="deny", reason=reason)

    @classmethod
    def abort(cls, reason: str | None = None) -> "ApprovalDecision":
        return cls(disposition="abort", reason=reason)

    @classmethod
    def allow_by_policy(
        cls,
        *,
        rule_id: str,
        scope: PolicyAmendmentScope,
    ) -> "ApprovalDecision":
        return cls(
            disposition="allow",
            policy_rule_id=rule_id,
            policy_scope=scope,
        )


class ApprovalResolver(Protocol):
    def resolve(self, request: ApprovalRequest) -> MaybeAwaitable[ApprovalDecision]: ...


def approval_actor_id(resolver: ApprovalResolver | None) -> str:
    """Return the stable actor bound to a resolver, defaulting to Root."""

    actor_id = getattr(resolver, "actor_id", None)
    return actor_id if isinstance(actor_id, str) and actor_id else "root"


class ApprovalPresenter(Protocol):
    def present(self, request: ApprovalRequest) -> MaybeAwaitable[None]: ...


class ApprovalRequestCollisionError(RuntimeError):
    def __init__(self, action_id: str) -> None:
        super().__init__(
            f"Approval action id was already presented by this broker: {action_id}"
        )
        self.action_id = action_id


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    grant_id: str
    actor_id: str
    proposal: ApprovalGrantProposal
    source_action_id: str


@dataclass(frozen=True, slots=True)
class ApprovalPolicyRule:
    """A persisted Policy amendment, never a replay of raw command text."""

    rule_id: str
    scope: PolicyAmendmentScope
    proposal: ApprovalGrantProposal
    source_action_id: str


class ApprovalPolicyRuleStore(Protocol):
    scope: PolicyAmendmentScope

    def find(self, request: ApprovalRequest) -> ApprovalPolicyRule | None: ...

    def issue(
        self,
        request: ApprovalRequest,
        amendment: PolicyAmendmentProposal,
    ) -> ApprovalPolicyRule: ...

    def revoke(self, rule_id: str) -> bool: ...

    def rules(self) -> tuple[ApprovalPolicyRule, ...]: ...


class InMemoryApprovalPolicyRuleStore:
    """Typed persistent-rule semantics without filesystem persistence."""

    def __init__(self, scope: PolicyAmendmentScope) -> None:
        self.scope = scope
        self._rules: dict[ApprovalGrantProposal, ApprovalPolicyRule] = {}

    def find(self, request: ApprovalRequest) -> ApprovalPolicyRule | None:
        amendment = _request_amendment(request, self.scope)
        if amendment is None:
            return None
        return self._rules.get(amendment.grant)

    def issue(
        self,
        request: ApprovalRequest,
        amendment: PolicyAmendmentProposal,
    ) -> ApprovalPolicyRule:
        if amendment.scope != self.scope:
            raise ValueError(
                f"{amendment.scope} amendment cannot be stored in {self.scope}"
            )
        action_id = request.action_id
        if action_id is None:
            raise ValueError("approval request must have an action id before amending")
        existing = self._rules.get(amendment.grant)
        if existing is not None:
            return existing
        rule = ApprovalPolicyRule(
            rule_id=f"policy-{uuid4().hex}",
            scope=self.scope,
            proposal=amendment.grant,
            source_action_id=action_id,
        )
        self._rules[amendment.grant] = rule
        return rule

    def revoke(self, rule_id: str) -> bool:
        for proposal, rule in tuple(self._rules.items()):
            if rule.rule_id == rule_id:
                self._rules.pop(proposal, None)
                return True
        return False

    def rules(self) -> tuple[ApprovalPolicyRule, ...]:
        return tuple(self._rules.values())


class JsonApprovalPolicyRuleStore(InMemoryApprovalPolicyRuleStore):
    """JSON-backed typed Policy amendments for one project or user scope."""

    def __init__(self, scope: PolicyAmendmentScope, path: str | Path) -> None:
        self.path = Path(path)
        super().__init__(scope)
        self._load()

    def issue(
        self,
        request: ApprovalRequest,
        amendment: PolicyAmendmentProposal,
    ) -> ApprovalPolicyRule:
        rule = super().issue(request, amendment)
        self._persist()
        return rule

    def revoke(self, rule_id: str) -> bool:
        revoked = super().revoke(rule_id)
        if revoked:
            self._persist()
        return revoked

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(
                f"Approval policy payload must be an object: {self.path}"
            )
        raw_rules = payload.get("rules", ())
        if isinstance(raw_rules, str) or not isinstance(raw_rules, (list, tuple)):
            raise ValueError(f"Approval policy rules must be a list: {self.path}")
        for raw in raw_rules:
            if not isinstance(raw, Mapping):
                raise ValueError(f"Approval policy rule must be an object: {self.path}")
            scope = raw.get("scope")
            if scope != self.scope:
                continue
            constraints = raw.get("constraints")
            if not isinstance(constraints, Mapping):
                raise ValueError(
                    f"Approval policy constraints must be an object: {self.path}"
                )
            proposal = ApprovalGrantProposal(
                capability=_required_string(raw.get("capability"), "capability"),
                constraints=tuple(
                    (
                        _required_string(key, "constraint key"),
                        _required_string(value, "constraint value"),
                    )
                    for key, value in constraints.items()
                ),
                summary=_required_string(raw.get("summary"), "summary"),
            )
            rule = ApprovalPolicyRule(
                rule_id=_required_string(raw.get("rule_id"), "rule_id"),
                scope=self.scope,
                proposal=proposal,
                source_action_id=_required_string(
                    raw.get("source_action_id"),
                    "source_action_id",
                ),
            )
            self._rules[proposal] = rule

    def _persist(self) -> None:
        payload = {
                "version": 1,
                "rules": [
                    {
                        "rule_id": rule.rule_id,
                        "scope": rule.scope,
                        "capability": rule.proposal.capability,
                        "constraints": dict(rule.proposal.constraints),
                        "summary": rule.proposal.summary,
                        "source_action_id": rule.source_action_id,
                    }
                    for rule in self.rules()
                ],
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        except BaseException:
            with suppress(FileNotFoundError):
                temp_path.unlink()
            raise


@dataclass(frozen=True, slots=True)
class ApprovalPermission:
    """Safe read model for one pending request or retained session grant."""

    kind: Literal["pending", "session", "project", "user"]
    permission_id: str
    actor_id: str
    capability: str
    summary: str


@dataclass(frozen=True, slots=True)
class ApprovalPermissionsSnapshot:
    """Product-neutral permissions page input without raw tool arguments."""

    pending: tuple[ApprovalPermission, ...] = ()
    grants: tuple[ApprovalPermission, ...] = ()
    project_rules: tuple[ApprovalPermission, ...] = ()
    user_rules: tuple[ApprovalPermission, ...] = ()


class InMemoryApprovalGrantStore:
    """Session-owned grants; disposing the resolver revokes the whole store."""

    def __init__(self) -> None:
        self._grants: dict[
            tuple[str, ApprovalGrantProposal],
            ApprovalGrant,
        ] = {}

    def find(self, request: ApprovalRequest) -> ApprovalGrant | None:
        proposal = request.session_grant
        if proposal is None:
            return None
        return self._grants.get((request.actor_id, proposal))

    def issue(self, request: ApprovalRequest) -> ApprovalGrant:
        proposal = request.session_grant
        if proposal is None:
            raise ValueError("approval request has no safe session grant proposal")
        action_id = request.action_id
        if action_id is None:
            raise ValueError("approval request must have an action id before granting")
        grant = ApprovalGrant(
            grant_id=f"grant-{uuid4().hex}",
            actor_id=request.actor_id,
            proposal=proposal,
            source_action_id=action_id,
        )
        self._grants[(request.actor_id, proposal)] = grant
        return grant

    def revoke(self, grant_id: str) -> bool:
        for key, grant in tuple(self._grants.items()):
            if grant.grant_id == grant_id:
                self._grants.pop(key, None)
                return True
        return False

    def revoke_actor(self, actor_id: str) -> int:
        """Revoke grants owned by one actor without disturbing its siblings."""

        keys = tuple(key for key in self._grants if key[0] == actor_id)
        for key in keys:
            self._grants.pop(key, None)
        return len(keys)

    def clear(self) -> int:
        count = len(self._grants)
        self._grants.clear()
        return count

    def grants(self) -> tuple[ApprovalGrant, ...]:
        return tuple(self._grants.values())


@dataclass(slots=True)
class ActorBoundApprovalResolver:
    """Bind requests and approval lifecycle to one child incarnation."""

    resolver: ApprovalResolver
    actor_id: str
    _session_open: bool = field(default=True, init=False, repr=False)
    _session_close_reason: str = field(
        default="Child agent closed before approval was resolved",
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise ValueError("actor_id must be a non-empty string")

    def preauthorize(
        self,
        request: ApprovalRequest,
    ) -> MaybeAwaitable[ApprovalDecision | None]:
        if not self._session_open:
            return None
        preauthorize = getattr(self.resolver, "preauthorize", None)
        if not callable(preauthorize):
            return None
        return preauthorize(replace(request, actor_id=self.actor_id))

    def resolve(self, request: ApprovalRequest) -> MaybeAwaitable[ApprovalDecision]:
        if not self._session_open:
            return ApprovalDecision.deny(self._session_close_reason)
        return self.resolver.resolve(replace(request, actor_id=self.actor_id))

    def open_session(self) -> None:
        """Open only this actor binding; the root owns the shared resolver."""

        self._session_open = True

    def close_session(
        self,
        reason: str = "Child agent closed before approval was resolved",
    ) -> int:
        """Cancel this actor's pending requests while retaining its grants."""

        self._session_open = False
        self._session_close_reason = reason
        cancel_actor = getattr(self.resolver, "cancel_actor", None)
        if not callable(cancel_actor):
            return 0
        return int(cancel_actor(self.actor_id, reason))

    def end_session(
        self,
        reason: str = "Child agent closed before approval was resolved",
    ) -> int:
        """Release pending requests and retained grants for this incarnation."""

        completed = self.close_session(reason)
        revoke_actor_grants = getattr(self.resolver, "revoke_actor_grants", None)
        if callable(revoke_actor_grants):
            revoke_actor_grants(self.actor_id)
        return completed


@dataclass(frozen=True)
class DenyApprovalResolver:
    def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.deny(
            request.reason or f"Tool {request.tool_name} requires approval"
        )


@dataclass(frozen=True)
class HeadlessApprovalResolver:
    mode: Literal["allow", "deny"] = "deny"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"allow", "deny"}:
            raise ValueError(f"Unsupported headless approval mode: {self.mode}")

    def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        if self.mode == "allow":
            return ApprovalDecision.allow()
        return ApprovalDecision.deny(
            self.reason
            or request.reason
            or f"Tool {request.tool_name} requires approval"
        )


async def resolve_approval(
    resolver: ApprovalResolver | None,
    request: ApprovalRequest,
) -> ApprovalDecision:
    resolved = resolver or DenyApprovalResolver()
    result = resolved.resolve(request)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, ApprovalDecision):
        raise TypeError(
            f"ApprovalResolver returned {type(result).__name__}, expected ApprovalDecision"
        )
    result.__post_init__()
    return result


async def find_approval_grant(
    resolver: ApprovalResolver | None,
    request: ApprovalRequest,
) -> ApprovalDecision | None:
    """Return a validated existing grant without presenting a new request."""

    if resolver is None:
        return None
    preauthorize = getattr(resolver, "preauthorize", None)
    if not callable(preauthorize):
        return None
    result = preauthorize(request)
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return None
    decision = _validate_approval_decision(result)
    is_session_grant = (
        decision.scope == "session" and decision.grant_id is not None
    )
    is_policy_rule = (
        decision.policy_rule_id is not None
        and decision.policy_scope in {"project", "user"}
    )
    if decision.disposition != "allow" or not (
        is_session_grant or is_policy_rule
    ):
        raise ValueError(
            "preauthorized approval must identify a session grant or Policy rule"
        )
    return decision


def approval_request_to_dict(request: ApprovalRequest) -> dict[str, object]:
    """Project a request into mutable JSON-compatible Product data."""

    if not isinstance(request, ApprovalRequest):
        raise TypeError("request must be an ApprovalRequest")
    projection: dict[str, object] = {
        "tool_name": request.tool_name,
        "arguments": _thaw_value(request.arguments),
        "cwd": request.cwd,
        "reason": request.reason,
        "policy_code": request.policy_code,
        "action_id": request.action_id,
        "action": _approval_action(request),
        "risk": request.reason or "Tool call requires approval",
        "environment": "local",
        "grant_summary": (
            request.session_grant.summary
            if request.session_grant is not None
            else None
        ),
    }
    if request.action_fingerprint is not None:
        projection["action_fingerprint"] = request.action_fingerprint
    if request.actor_id != "root":
        projection["actor_id"] = request.actor_id
    projection["approval_options"] = tuple(
        {
            "outcome": option.outcome,
            "label": option.label,
            "shortcut": option.shortcut,
            "tone": option.tone,
        }
        for option in approval_options(request)
    )
    if request.session_grant is not None:
        projection["session_grant"] = {
            "capability": request.session_grant.capability,
            "constraints": dict(request.session_grant.constraints),
            "summary": request.session_grant.summary,
        }
    if request.policy_amendments:
        projection["policy_amendments"] = tuple(
            {
                "scope": amendment.scope,
                "capability": amendment.grant.capability,
                "constraints": dict(amendment.grant.constraints),
                "summary": amendment.grant.summary,
            }
            for amendment in request.policy_amendments
        )
    return projection


def _approval_action(request: ApprovalRequest) -> str:
    command = request.arguments.get("command")
    if isinstance(command, str) and command.strip():
        return _approval_display_text(command)
    if isinstance(command, (tuple, list)) and command and all(
        isinstance(part, str) for part in command
    ):
        return _approval_display_text(shlex.join(command))
    path = request.arguments.get("path")
    if isinstance(path, str) and path.strip():
        return f"{request.tool_name} {_approval_display_text(path)}"
    return f"{request.tool_name} tool call"


def _approval_display_text(value: str) -> str:
    redacted = redact_text(value.strip())
    flattened = " ⏎ ".join(redacted.splitlines())
    safe = "".join(
        character if character.isprintable() else "�"
        for character in flattened
    )
    return safe[:2048]


def configure_persistent_approval_policy(
    resolver: ApprovalResolver | None,
    settings_manager: object | None,
) -> None:
    """Bind standard project and user Policy stores to an approval resolver."""

    setter = getattr(resolver, "set_policy_stores", None)
    if not callable(setter) or settings_manager is None:
        return
    project_base = getattr(settings_manager, "project_base_dir", None)
    global_base = getattr(settings_manager, "global_base_dir", None)
    stores = {}
    if isinstance(project_base, Path):
        stores["project"] = JsonApprovalPolicyRuleStore(
            "project",
            project_base / "approval-policy.json",
        )
    if isinstance(global_base, Path):
        stores["user"] = JsonApprovalPolicyRuleStore(
            "user",
            global_base / "approval-policy.json",
        )
    setter(stores)


def approval_options(request: ApprovalRequest) -> tuple[ApprovalOption, ...]:
    """Build the exact menu Policy permits for this action."""

    options: list[ApprovalOption] = [
        ApprovalOption("allow_once", "Allow this action once", "y"),
    ]
    if request.session_grant is not None:
        options.append(
            ApprovalOption(
                "allow_session",
                request.session_grant.summary,
                "s",
                "session",
            )
        )
    for amendment in request.policy_amendments:
        destination = "this project" if amendment.scope == "project" else "this user"
        options.append(
            ApprovalOption(
                (
                    "allow_project"
                    if amendment.scope == "project"
                    else "allow_user"
                ),
                f"Always allow for {destination}: {amendment.grant.summary}",
                "p" if amendment.scope == "project" else "u",
                "persistent",
            )
        )
    options.append(
        ApprovalOption(
            "deny",
            "Deny and let the agent continue",
            "n",
            "deny",
        )
    )
    return tuple(options)


def ensure_approval_action_id(request: ApprovalRequest) -> ApprovalRequest:
    """Return an immutable request with a correlation id."""

    if request.action_id:
        return request
    return replace(request, action_id=f"approval-{uuid4().hex}")


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


ApprovalPayloadProjector = Callable[[ApprovalRequest], Mapping[str, object]]


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


class _FrozenDict(dict[str, Any]):
    """Immutable dict snapshot that remains compatible with serializers."""

    def _immutable(self, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise TypeError("frozen mapping does not support mutation")

    def __setitem__(self, key: str, value: Any) -> Never:
        self._immutable(key, value)

    def __delitem__(self, key: str) -> Never:
        self._immutable(key)

    def clear(self) -> Never:
        self._immutable()

    def pop(self, key: str, default: Any = None) -> Never:
        self._immutable(key, default)

    def popitem(self) -> Never:
        self._immutable()

    def setdefault(self, key: str, default: Any = None) -> Never:
        self._immutable(key, default)

    def update(self, *args: Any, **kwargs: Any) -> Never:
        self._immutable(*args, **kwargs)

    def __ior__(self, other: object) -> Never:
        self._immutable(other)

    def __reduce__(self) -> tuple[type[_FrozenDict], tuple[dict[str, Any]]]:
        return type(self), (dict(self),)

    def __deepcopy__(self, memo: dict[int, Any]) -> _FrozenDict:
        copied = type(self)(
            {deepcopy(key, memo): deepcopy(value, memo) for key, value in self.items()}
        )
        memo[id(self)] = copied
        return copied


def _freeze_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(values, Mapping):
        raise TypeError("ApprovalRequest arguments must be a mapping")
    return _FrozenDict(
        {
            _require_string_key(key): _freeze_value(value)
            for key, value in values.items()
        }
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict(
            {
                _require_string_key(key): _freeze_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(
        "ApprovalRequest argument values must be JSON-compatible mappings, "
        "sequences, strings, numbers, booleans, or null"
    )


def _thaw_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value


def _validate_optional_string(value: object, field_name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _request_amendment(
    request: ApprovalRequest,
    scope: PolicyAmendmentScope,
) -> PolicyAmendmentProposal | None:
    return next(
        (
            amendment
            for amendment in request.policy_amendments
            if amendment.scope == scope
        ),
        None,
    )


def _require_string_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("ApprovalRequest argument mapping keys must be strings")
    return key


def _validate_approval_decision(decision: object) -> ApprovalDecision:
    if not isinstance(decision, ApprovalDecision):
        raise TypeError("decision must be an ApprovalDecision")
    decision.__post_init__()
    return decision


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


__all__ = [
    "ActorBoundApprovalResolver",
    "ApprovalBroker",
    "ApprovalDecision",
    "ApprovalGrant",
    "ApprovalGrantProposal",
    "ApprovalOption",
    "ApprovalOutcome",
    "ApprovalPolicyRule",
    "ApprovalPolicyRuleStore",
    "ApprovalPermission",
    "ApprovalPermissionsSnapshot",
    "ApprovalScope",
    "ApprovalPresenter",
    "ApprovalRequest",
    "ApprovalRequestCollisionError",
    "ApprovalResolver",
    "approval_actor_id",
    "DenyApprovalResolver",
    "HeadlessApprovalResolver",
    "InMemoryApprovalGrantStore",
    "InMemoryApprovalPolicyRuleStore",
    "InteractiveApprovalResolver",
    "JsonApprovalPolicyRuleStore",
    "MaybeAwaitable",
    "PolicyAmendmentProposal",
    "PolicyAmendmentScope",
    "ApprovalPayloadProjector",
    "approval_options",
    "approval_request_to_dict",
    "configure_persistent_approval_policy",
    "ensure_approval_action_id",
    "find_approval_grant",
    "resolve_approval",
]
