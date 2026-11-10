"""Native Windows custody for inert Coding Worker opt-in decisions.

The caller supplies the Product-pinned state-root descriptor and holds its GC
gate. This journal persists decisions; it cannot derive selection or issue a
Worker activation receipt.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from loushang.harness.worker.history._windows_record_journals import WindowsOptInRecords

from .package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
    _decode_coding_worker_opt_in_history,
)
from .package_product_worker_policy import CodingWorkerOptInV1

_NAME = "worker-opt-in.jsonl"
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_MAX_EVENTS = 4096
_MAX_BYTES = 32 * 1024 * 1024


class CodingWindowsWorkerOptInJournal(
    WindowsOptInRecords[CodingWorkerOptInDecisionV1, CodingWorkerOptInV1]
):
    """Strict append-only decisions under one Product-pinned Windows root."""

    _name = _NAME
    _label = "Windows Worker opt-in"
    _scope_pattern = _OPAQUE
    _failure = staticmethod(
        lambda code: CodingWorkerOptInJournalError("coding_worker_opt_in_" + code)
    )
    _decoder = staticmethod(
        lambda raw, *, path, scope_id: _decode_coding_worker_opt_in_history(
            raw, path=path, scope_id=scope_id
        )
    )
    _max_bytes = staticmethod(lambda: _MAX_BYTES)
    _max_events = staticmethod(lambda: _MAX_EVENTS)
    _append_error = "Windows Worker opt-in append made no progress"
    _root_error = "Windows Worker opt-in requires a pinned Product root"
    _record_type = CodingWorkerOptInDecisionV1
    _opt_in_type = CodingWorkerOptInV1

    @property
    def path(self) -> Path:
        return self._path

    def current(
        self, plugin_id: str, *, directory_fd: int
    ) -> CodingWorkerOptInDecisionV1 | None:
        self._require_plugin_id(plugin_id)
        events = self.history_read_only(directory_fd=directory_fd)
        return self._latest(events, plugin_id)

    def history_read_only(
        self, *, directory_fd: int
    ) -> tuple[CodingWorkerOptInDecisionV1, ...]:
        "Read every retained operation without creating a journal or lock."
        return self._read_records(directory_fd=directory_fd)

    def change(
        self,
        *,
        directory_fd: int,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        action: Literal["allow", "revoke"],
        opt_in: CodingWorkerOptInV1 | None,
    ) -> CodingWorkerOptInDecisionV1:
        return self._change(
            directory_fd=directory_fd,
            plugin_id=plugin_id,
            operation_id=operation_id,
            expected_generation=expected_generation,
            action=action,
            opt_in=opt_in,
        )

    @staticmethod
    def _require_plugin_id(plugin_id: str) -> None:
        if (
            not isinstance(plugin_id, str)
            or len(plugin_id) > 128
            or _IDENTIFIER.fullmatch(plugin_id) is None
        ):
            raise ValueError("Windows Worker opt-in Plugin id is invalid")


__all__ = ["CodingWindowsWorkerOptInJournal"]
