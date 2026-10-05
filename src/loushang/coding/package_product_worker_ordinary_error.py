"""Platform-neutral failure contract for explicit ordinary Worker selection."""

from __future__ import annotations


class CodingWorkerOrdinaryBootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


__all__ = ["CodingWorkerOrdinaryBootstrapError"]
