from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.coding.session_manager import SessionManager


def test_G14_PRODUCT_header_metadata_is_immutable_and_survives_canonical_reopen(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        raw = {"coding.hosted": {"continuityId": "continuity-1"}}
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            additional_header_metadata=raw,
            defer_materialization=False,
        )
        try:
            raw["coding.hosted"]["continuityId"] = "changed"
            await manager.append_session_info("hosted")
            path = manager.session_file
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()
        restored = await SessionManager.open(path)
        try:
            assert restored.header.metadata["coding.hosted"] == {
                "continuityId": "continuity-1"
            }
        finally:
            await restored.dispose_runtime_profile()

    asyncio.run(scenario())


def test_G14_PRODUCT_metadata_cannot_override_reserved_product_header(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="reserved header metadata"):
            await SessionManager.new(
                session_dir=tmp_path,
                cwd=str(tmp_path),
                additional_header_metadata={"cwd": "untrusted"},
            )
        assert not tuple(tmp_path.glob("*.jsonl"))

    asyncio.run(scenario())
