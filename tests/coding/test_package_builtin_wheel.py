from __future__ import annotations

import os
import stat
from hashlib import sha256

import pytest

from loushang.coding.package_builtin_wheel import (
    CODING_BASE_PRODUCT_WHEEL_FILENAME,
    build_coding_base_product_wheel,
    prepare_posix_coding_base_product_wheel,
)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source owner")
def test_coding_base_product_wheel_is_private_repeatable_and_pinned(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)

    prepared = prepare_posix_coding_base_product_wheel(source_root)

    assert prepared.path == source_root / CODING_BASE_PRODUCT_WHEEL_FILENAME
    assert prepared.path.read_bytes() == build_coding_base_product_wheel()
    assert prepared.artifact_digest == sha256(prepared.path.read_bytes()).hexdigest()
    assert stat.S_IMODE(prepared.path.stat().st_mode) == 0o600
    assert prepare_posix_coding_base_product_wheel(source_root) == prepared


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source owner")
def test_coding_base_product_wheel_refuses_changed_or_linked_existing_artifact(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    prepared = prepare_posix_coding_base_product_wheel(source_root)
    prepared.path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed on disk"):
        prepare_posix_coding_base_product_wheel(source_root)
    assert prepared.path.read_bytes() == b"changed"

    target = tmp_path / "target"
    target.write_bytes(b"outside")
    prepared.path.unlink()
    prepared.path.symlink_to(target)
    with pytest.raises(OSError):
        prepare_posix_coding_base_product_wheel(source_root)
    assert target.read_bytes() == b"outside"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source owner")
def test_coding_base_product_wheel_refuses_group_writable_source_root(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    source_root.chmod(0o770)

    with pytest.raises(ValueError, match="not private"):
        prepare_posix_coding_base_product_wheel(source_root)
    assert not (source_root / CODING_BASE_PRODUCT_WHEEL_FILENAME).exists()
