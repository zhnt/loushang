"""Private compatibility names for Product-owned Worker history access."""

from loushang.harness.package_product._worker_history_access import (
    PosixProductWorkerHistoryAccess as _PosixProductWorkerHistoryAccess,
)
from loushang.harness.package_product._worker_history_access import (
    WindowsProductWorkerHistoryAccess as _WindowsProductWorkerHistoryAccess,
)

_CodingHistoryAccess = _PosixProductWorkerHistoryAccess
_CodingWindowsHistoryAccess = _WindowsProductWorkerHistoryAccess
