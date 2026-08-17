from __future__ import annotations

import pytest

from loushang.harness.capabilities import (
    CapabilityPack,
    compose_capability_packs,
)


def test_capability_packs_use_priority_then_input_order_and_retain_trace() -> None:
    composition = compose_capability_packs(
        (
            CapabilityPack(
                pack_id="extension",
                source="extension",
                priority=100,
                items=("extension-a",),
            ),
            CapabilityPack(
                pack_id="product",
                source="product",
                priority=200,
                items=("product-a", "product-b"),
            ),
            CapabilityPack(
                pack_id="disabled",
                source="oem",
                priority=300,
                items=("not-active",),
                enabled=False,
            ),
        )
    )

    assert composition.items == ("product-a", "product-b", "extension-a")
    assert [(item.pack_id, item.output_index) for item in composition.trace] == [
        ("product", 0),
        ("extension", 2),
    ]


def test_capability_packs_reject_duplicate_source_scoped_pack_ids() -> None:
    with pytest.raises(ValueError, match="unique source and pack ids"):
        compose_capability_packs(
            (
                CapabilityPack("tools", "extension", ("a",)),
                CapabilityPack("tools", "extension", ("b",)),
            )
        )
