from __future__ import annotations

import os
from pathlib import Path

import pytest

from loushang.coding.package_builtin_wheel import (
    CODING_BASE_PRODUCT_WHEEL_FILENAME,
    inspect_windows_coding_base_product_wheel,
    inspect_windows_coding_capability_product_wheels,
    prepare_windows_coding_base_product_wheel,
    prepare_windows_coding_capability_product_wheels,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    prepare_windows_product_control_root,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")


def test_windows_builtin_product_wheels_publish_replay_and_refuse_tamper(
    tmp_path: Path,
) -> None:
    source = prepare_windows_product_control_root(tmp_path / "product-sources")
    base = prepare_windows_coding_base_product_wheel(source)
    capabilities = prepare_windows_coding_capability_product_wheels(source)

    assert base.path == source / CODING_BASE_PRODUCT_WHEEL_FILENAME
    assert inspect_windows_coding_base_product_wheel(source) == base
    assert prepare_windows_coding_base_product_wheel(source) == base
    assert inspect_windows_coding_capability_product_wheels(source) == capabilities
    assert prepare_windows_coding_capability_product_wheels(source) == capabilities

    base.path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed on disk"):
        inspect_windows_coding_base_product_wheel(source)
    with pytest.raises(ValueError, match="changed on disk"):
        prepare_windows_coding_base_product_wheel(source)
