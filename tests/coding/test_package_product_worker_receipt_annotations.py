"""Receipt entry points expose resolvable annotations to SDK introspection."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import get_type_hints

import pytest

from loushang.coding.package_product_worker_receipt import (
    open_coding_selected_worker_receipt_owner,
)
from loushang.coding.package_product_worker_windows_receipt import (
    open_coding_windows_product_selected_worker_receipt_owner,
)


@pytest.mark.parametrize(
    "factory",
    (
        open_coding_selected_worker_receipt_owner,
        open_coding_windows_product_selected_worker_receipt_owner,
    ),
)
def test_receipt_factory_annotations_resolve(factory: Callable[..., object]) -> None:
    hints = get_type_hints(factory)

    assert inspect.isclass(hints["session_manager"])
    assert "return" in hints
    assert hints.keys() - {"return"} <= inspect.signature(factory).parameters.keys()
