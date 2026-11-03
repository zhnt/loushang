"""Bounded request-delivery presentation, independent of execution state."""

from dataclasses import dataclass
from typing import Literal

RequestDeliveryState = Literal["pending", "acknowledged", "unknown"]


@dataclass(frozen=True, slots=True)
class ConversationRequestPresentation:
    operation: Literal["submit", "steer", "follow_up", "interrupt"]
    state: RequestDeliveryState

    def __post_init__(self) -> None:
        if self.operation not in {"submit", "steer", "follow_up", "interrupt"} or self.state not in {
            "pending", "acknowledged", "unknown",
        }:
            raise ValueError("invalid request presentation")

    @property
    def message(self) -> str:
        suffix = "; result unconfirmed, no retry" if self.state == "unknown" else ""
        return f"{self.operation}: request_{self.state}{suffix}"


__all__ = ["ConversationRequestPresentation", "RequestDeliveryState"]
