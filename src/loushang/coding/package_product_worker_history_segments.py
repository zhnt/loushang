"""Compatibility imports for the Worker history storage now owned by Harness."""

from loushang.harness.worker._segmented_history import *  # noqa: F403
from loushang.harness.worker._segmented_history import (
    __all__ as __all__,
)
from loushang.harness.worker._segmented_history import (
    _head_bytes as _head_bytes,
)
from loushang.harness.worker._segmented_history import (
    _head_name as _head_name,
)
from loushang.harness.worker._segmented_history import (
    _segment_name as _segment_name,
)
from loushang.harness.worker._segmented_history import (
    append_coding_worker_active_record as append_coding_worker_active_record,
)
