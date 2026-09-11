"""CLI grammar exports without eager application/runtime imports."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING
from typing import Any as _Any

if TYPE_CHECKING:
    from loushang.coding.cli.args import CliArgs as CliArgs
    from loushang.coding.cli.args import parse_args as parse_args

__all__ = ["CliArgs", "parse_args"]


def __getattr__(name: str) -> _Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module("loushang.coding.cli.args"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
