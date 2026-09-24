"""Coding Session selection over an already fenced Package Product."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductRuntimeFactory,
    PosixLocalWheelProductSessionOwner,
)

from .session_manager import SessionManager


@dataclass(frozen=True, slots=True)
class CodingPosixLocalWheelProductRuntimeOwner:
    """Select the exact Coding Session for a fenced Product owner."""

    product_owner: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_owner, PosixLocalWheelProductSessionOwner)
            or self.product_owner.policy.product_id != "coding"
        ):
            raise ValueError("Coding Package Product owner is required")

    def factory_for_session(
        self, manager: SessionManager
    ) -> PosixLocalWheelProductRuntimeFactory:
        """Bind a live Session to one runtime lease without a legacy route."""

        if not isinstance(manager, SessionManager):
            raise TypeError("Coding Product Session manager is required")
        session_id = manager.get_header().conversation_id
        return self.product_owner.factory_for_session(
            session_id=session_id,
            cwd=Path(manager.get_cwd()),
            runtime_id="coding-session:" + sha256(session_id.encode()).hexdigest(),
        )


__all__ = ["CodingPosixLocalWheelProductRuntimeOwner"]
