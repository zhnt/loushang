"""Retained approval rules and their persistent stores.

A retained approval rule (`ApprovalPolicyRule`) records a user's "always
allow" choice from the approval lifecycle; it is not a policy evaluation
rule (`loushang.harness.policy.evaluators.PolicyRule`). See the terminology
conventions in policy-approval-redesign.md section 7.0.
"""


from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from loushang.harness.approval.ports import ApprovalResolver
from loushang.harness.approval.requests import (
    ApprovalGrantProposal,
    ApprovalRequest,
    PolicyAmendmentProposal,
    PolicyAmendmentScope,
    _request_amendment,
    _required_string,
)


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
