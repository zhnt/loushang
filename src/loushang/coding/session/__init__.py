"""Public Session values resolved without eager Session construction imports."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING
from typing import Any as _Any

_EXPORTS = {
    'AgentSession': ('loushang.coding.session.agent_session', 'AgentSession'),
    'AgentSessionState': ('loushang.harness.session.inspection', 'AgentSessionState'),
    'CompactionDecision': ('loushang.harness.transcript', 'CompactionDecision'),
    'ContextUsage': ('loushang.harness.session.inspection', 'ContextUsage'),
    'ContextUsageSnapshot': ('loushang.harness.transcript', 'ContextUsageSnapshot'),
    'ModelSelection': ('loushang.ai.model', 'ModelSelection'),
    'RunState': ('loushang.harness.runtime.types', 'RunState'),
    'SessionStats': ('loushang.harness.session.inspection', 'SessionStats'),
    'TokenUsageTotals': ('loushang.harness.session.inspection', 'TokenUsageTotals'),
    'TreeNavigationResult': ('loushang.harness.transcript', 'TranscriptNavigationResult'),
}

if TYPE_CHECKING:
    from loushang.ai.model import ModelSelection
    from loushang.coding.session.agent_session import AgentSession
    from loushang.harness.runtime.types import RunState
    from loushang.harness.session.inspection import (
        AgentSessionState,
        ContextUsage,
        SessionStats,
        TokenUsageTotals,
    )
    from loushang.harness.transcript import CompactionDecision, ContextUsageSnapshot
    from loushang.harness.transcript import (
        TranscriptNavigationResult as TreeNavigationResult,
    )
else:
    del TYPE_CHECKING


def __getattr__(name: str) -> _Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(_import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


__all__ = ['AgentSession', 'AgentSessionState', 'CompactionDecision', 'ContextUsage', 'ContextUsageSnapshot', 'ModelSelection', 'RunState', 'SessionStats', 'TokenUsageTotals', 'TreeNavigationResult']
