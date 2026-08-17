from __future__ import annotations

from types import ModuleType

from loushang.harness.sdk_surface import (
    check_sdk_surface_compatibility,
    get_sdk_surface_snapshot,
)


def _product_module() -> ModuleType:
    module = ModuleType("example_product")

    def create_product(*, plan, ports):
        return plan, ports

    module.create_product = create_product
    module.__all__ = ("create_product",)
    return module


def test_sdk_surface_inspection_accepts_product_entry_contracts() -> None:
    module = _product_module()

    snapshot = get_sdk_surface_snapshot(
        module,
        entry_names=("create_product",),
    )
    report = check_sdk_surface_compatibility(
        module,
        entry_names=("create_product",),
        required_exports=("create_product",),
        required_entry_signatures={
            "create_product": ("plan", "ports"),
        },
    )

    assert snapshot.entry_signatures == {
        "create_product": ("plan", "ports"),
    }
    assert snapshot.missing_exports == ()
    assert report.ok


def test_sdk_surface_inspection_reports_broken_product_exports() -> None:
    module = _product_module()
    module.__all__ = ("create_product", "missing")

    report = check_sdk_surface_compatibility(
        module,
        required_exports=("missing",),
    )

    assert report.missing_exports == ("missing",)
    assert report.broken_exports == ("missing",)
