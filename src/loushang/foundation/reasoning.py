"""Protocol-neutral vocabulary shared by reasoning controls."""

from typing import Literal, get_args

ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh", "max"]
ThinkingLevel = Literal["off", ReasoningEffort]

REASONING_EFFORTS: tuple[ReasoningEffort, ...] = get_args(ReasoningEffort)
THINKING_LEVELS: tuple[ThinkingLevel, ...] = ("off", *REASONING_EFFORTS)
