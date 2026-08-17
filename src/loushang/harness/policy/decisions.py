"""Policy verdict values: dispositions, decisions, and contract errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PolicyDisposition = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class PolicyDecision:
    """Product-neutral result from an injected policy evaluator."""

    disposition: PolicyDisposition
    reason: str | None = None
    code: str | None = None

    def __post_init__(self) -> None:
        if self.disposition not in {"allow", "deny", "ask"}:
            raise ValueError(f"Unsupported policy disposition: {self.disposition}")
        if self.reason is not None and not isinstance(self.reason, str):
            raise TypeError("PolicyDecision reason must be a string or None")
        if self.code is not None and not isinstance(self.code, str):
            raise TypeError("PolicyDecision code must be a string or None")

    @classmethod
    def allow(cls) -> PolicyDecision:
        return cls(disposition="allow")

    @classmethod
    def deny(cls, reason: str, *, code: str | None = None) -> PolicyDecision:
        return cls(disposition="deny", reason=reason, code=code)

    @classmethod
    def ask(cls, reason: str, *, code: str | None = None) -> PolicyDecision:
        return cls(disposition="ask", reason=reason, code=code)


class PolicyEvaluationError(RuntimeError):
    """Raised when an injected policy evaluator violates its contract."""
