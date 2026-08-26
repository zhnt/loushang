"""Content-free durable usage observations for individual provider attempts."""

from __future__ import annotations

from dataclasses import dataclass

MODEL_CALL_ATTEMPT_USAGE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ModelCallAttemptUsage:
    """One partial normalized usage snapshot for a prepared provider attempt."""

    invocation_id: str
    attempt: int
    model_input_snapshot_id: str
    input: int | None = None
    output: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    total_tokens: int | None = None
    terminal: bool = False
    schema_version: int = MODEL_CALL_ATTEMPT_USAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_CALL_ATTEMPT_USAGE_SCHEMA_VERSION:
            raise ValueError("unsupported model call attempt usage schema version")
        for name in ("invocation_id", "model_input_snapshot_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"model call attempt usage {name} must be non-empty")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise TypeError("model call attempt usage attempt must be an integer")
        if self.attempt < 1:
            raise ValueError("model call attempt usage attempt must be positive")
        if not isinstance(self.terminal, bool):
            raise TypeError("model call attempt usage terminal must be boolean")
        present = False
        for name in (
            "input",
            "output",
            "cache_read",
            "cache_write",
            "total_tokens",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            present = True
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"model call attempt usage {name} must be an integer")
            if value < 0:
                raise ValueError(
                    f"model call attempt usage {name} must be non-negative"
                )
        if not present:
            raise ValueError("model call attempt usage must report at least one value")


__all__ = [
    "MODEL_CALL_ATTEMPT_USAGE_SCHEMA_VERSION",
    "ModelCallAttemptUsage",
]
