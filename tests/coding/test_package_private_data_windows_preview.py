"""Portable policy cases for the Windows Arch read-only snapshot boundary."""

from __future__ import annotations

import pytest

from loushang.coding.package_private_data_windows_preview import (
    _require_simple_windows_attributes,
)


@pytest.mark.parametrize(
    ("attributes", "directory"),
    (
        (0x00000020, False),  # ordinary archive file
        (0x00000080, False),  # normal file
        (0x00000010, True),  # ordinary directory
        (0x00000010 | 0x00002000, True),  # nonindexed directory
    ),
)
def test_windows_arch_preview_admits_plain_attributes(
    attributes: int, directory: bool
) -> None:
    _require_simple_windows_attributes(attributes, directory=directory)


@pytest.mark.parametrize(
    ("attributes", "directory"),
    (
        (0, False),
        (0x00000010, False),
        (0x00000020, True),
        (0x00000020 | 0x00000002, False),  # hidden
        (0x00000020 | 0x00000200, False),  # sparse
        (0x00000010 | 0x00000800, True),  # compressed
        (0x00000020 | 0x00004000, False),  # encrypted
        (0x00000010 | 0x00400000, True),  # recall on access
    ),
)
def test_windows_arch_preview_refuses_unadmitted_attributes(
    attributes: int, directory: bool
) -> None:
    with pytest.raises(ValueError, match="attributes are unsupported"):
        _require_simple_windows_attributes(attributes, directory=directory)
