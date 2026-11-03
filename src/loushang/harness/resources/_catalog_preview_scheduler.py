"""Priority dispatch for bounded Resource preview work, without authority."""

from __future__ import annotations

import heapq
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import count
from typing import Literal

CatalogPreviewPriority = Literal["foreground", "background"]


@dataclass(order=True)
class _Pending:
    priority: int
    sequence: int
    operation: Callable[[], None] = field(compare=False)


class CatalogPreviewExecutor:
    """Pick foreground work before queued previews on the original two slots.

    Resource scopes still own admission limits, read pins, budgets and actual
    completion. A dispatch Future is not proof that any particular job ran.
    Already running work is not interrupted or restarted by promotion.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="resource-preview")
        self._lock = threading.Lock()
        self._sequence = count()
        self._pending: list[_Pending] = []

    def submit(
        self, operation: Callable[[], None], *, priority: CatalogPreviewPriority = "background",
    ) -> Future[None]:
        if priority not in ("foreground", "background"):
            raise ValueError("invalid Catalog preview priority")
        with self._lock:
            work = _Pending(0 if priority == "foreground" else 1, next(self._sequence), operation)
            heapq.heappush(self._pending, work)
        try:
            return self._executor.submit(self._run_next)
        except BaseException:
            # submit can fail after queue admission. Remove only this pending
            # operation; an unknown dispatch callback may still serve a peer.
            with self._lock:
                self._pending = [item for item in self._pending if item is not work]
                heapq.heapify(self._pending)
            raise

    def promote(self, operation: Callable[[], None]) -> None:
        with self._lock:
            for item in self._pending:
                if item.operation is operation:
                    item.priority = 0
                    heapq.heapify(self._pending)
                    return

    def _run_next(self) -> None:
        with self._lock:
            if not self._pending:
                return
            work = heapq.heappop(self._pending)
        work.operation()
