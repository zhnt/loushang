"""Cancellation-safe joins for tasks whose effects outlive their caller."""

from __future__ import annotations

from typing import TypeVar

from loushang.foundation._owned_tasks import (
    _join_failure_first,
)

T = TypeVar("T")


_await_cancellation_atomic = _join_failure_first


__all__: list[str] = []
