from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class _Projection:
    projection_id: str
    updated_at: int
    source_path: Path


def _index(path: Path):
    from loushang.harness.conversation import (
        FunctionalProjectionCodec,
        JsonProjectionIndex,
    )

    return JsonProjectionIndex(
        path,
        version=2,
        items_key="projections",
        codec=FunctionalProjectionCodec(
            encoder=lambda item: {
                "id": item.projection_id,
                "updated_at": item.updated_at,
                "source_path": str(item.source_path),
            },
            decoder=lambda value: _Projection(
                projection_id=str(value["id"]),
                updated_at=int(value["updated_at"]),
                source_path=Path(str(value["source_path"])),
            ),
        ),
        is_current=lambda item: item.source_path.exists(),
        sort_key=lambda item: item.updated_at,
        reverse=True,
        generated_at=lambda: "2026-07-13T00:00:00Z",
    )


def test_projection_index_round_trip_sort_and_refresh(tmp_path: Path) -> None:
    source_a = tmp_path / "a.jsonl"
    source_b = tmp_path / "b.jsonl"
    source_a.touch()
    source_b.touch()
    index = _index(tmp_path / "index.json")

    written = index.write(
        (
            _Projection("a", 1, source_a),
            _Projection("b", 2, source_b),
        )
    )

    assert [item.projection_id for item in written] == ["b", "a"]
    assert index.load().projections == written
    payload = json.loads(index.path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["generated_at"] == "2026-07-13T00:00:00Z"

    source_b.unlink()
    snapshot = index.load()
    assert snapshot.stale is True
    assert [item.projection_id for item in snapshot.projections] == ["a"]

    rebuilt = index.load_or_refresh(lambda: (_Projection("fresh", 3, source_a),))
    assert [item.projection_id for item in rebuilt] == ["fresh"]


def test_projection_index_preserves_corrupt_payload(tmp_path: Path) -> None:
    index = _index(tmp_path / "index.json")
    index.path.write_text("{not-json}", encoding="utf-8")

    snapshot = index.load()

    assert snapshot.stale is True
    assert snapshot.projections == ()
    assert not index.path.exists()
    assert len(list(tmp_path.glob("index.json.corrupt-*"))) == 1


def test_projection_index_skips_invalid_items_and_marks_snapshot_stale(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    source.touch()
    index = _index(tmp_path / "index.json")
    index.path.write_text(
        json.dumps(
            {
                "version": 2,
                "projections": [
                    {
                        "id": "ok",
                        "updated_at": 1,
                        "source_path": str(source),
                    },
                    {"id": "broken"},
                ],
            }
        ),
        encoding="utf-8",
    )

    snapshot = index.load()

    assert snapshot.stale is True
    assert [item.projection_id for item in snapshot.projections] == ["ok"]


@pytest.mark.requires_host_runtime
def test_revision_aware_json_index_rejects_stale_upsert_and_late_recreation(
    tmp_path: Path,
) -> None:
    from loushang.harness.conversation import (
        ConversationKey,
        ConversationLocator,
        FunctionalProjectionCodec,
        IndexedProjection,
        JsonConversationIndex,
    )

    def query_items(query: str, items):
        return tuple(
            item for item in items if query.lower() in item.projection.projection_id
        )

    index = JsonConversationIndex(
        tmp_path / "conversation-index.json",
        version=1,
        codec=FunctionalProjectionCodec(
            encoder=lambda item: {
                "id": item.projection_id,
                "updated_at": item.updated_at,
                "source_path": str(item.source_path),
            },
            decoder=lambda value: _Projection(
                projection_id=str(value["id"]),
                updated_at=int(value["updated_at"]),
                source_path=Path(str(value["source_path"])),
            ),
        ),
        query_items=query_items,
    )
    locator = ConversationLocator(
        "provider-1",
        ConversationKey("coding", "session-1"),
    )

    async def scenario() -> None:
        current = IndexedProjection(
            locator,
            2,
            _Projection("current", 2, tmp_path / "current.jsonl"),
        )
        stale = IndexedProjection(
            locator,
            1,
            _Projection("stale", 1, tmp_path / "stale.jsonl"),
        )
        assert await index.upsert(current)
        assert not await index.upsert(stale)
        assert (await index.get(locator)) == current

        assert await index.delete(locator, through_revision=2)
        assert await index.get(locator) is None
        assert not await index.upsert(current)
        newer = IndexedProjection(
            locator,
            3,
            _Projection("newer", 3, tmp_path / "newer.jsonl"),
        )
        assert await index.upsert(newer)
        assert [item.projection.projection_id for item in await index.query("new")] == [
            "newer"
        ]
        before_replace = await index.query_snapshot("")
        assert before_replace.index_state == "fresh"
        assert before_replace.index_generation != "unavailable"
        assert before_replace.query_snapshot.endswith(":3")

        await index.replace((newer,))
        after_replace = await index.query_snapshot("")
        assert after_replace.index_generation != before_replace.index_generation
        assert after_replace.query_snapshot.endswith(":0")

    asyncio.run(scenario())
