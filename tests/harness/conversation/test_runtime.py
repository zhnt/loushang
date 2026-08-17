from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest


def _header(conversation_id: str):
    from loushang.harness.conversation import ConversationHeader

    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-13T00:00:00Z",
    )


def _record(
    record_id: str,
    parent_id: str | None,
    payload: str,
    *,
    kind: str = "message",
):
    from loushang.harness.conversation import ConversationRecord

    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=kind,
        payload_version=1,
        created_at="2026-07-13T00:00:00Z",
        payload=payload,
    )


def _repository(*, header=None, records=()):
    from loushang.harness.conversation import ConversationRepository

    return ConversationRepository.create(
        header=header or _header("conversation-1"),
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
    )


def test_conversation_repository_builds_branches_tree_and_folds() -> None:
    from loushang.harness.conversation import (
        FunctionalConversationFolder,
    )

    repository = _repository()
    repository.append(_record("root", None, "one"))
    repository.append(_record("left", "root", "two"))
    repository.branch("root")
    repository.append(_record("right", "root", "three"))

    tree = repository.tree()
    assert len(tree) == 1
    assert tree[0].record.record_id == "root"
    assert [node.record.record_id for node in tree[0].children] == ["left", "right"]
    assert [record.record_id for record in repository.children("root")] == [
        "left",
        "right",
    ]

    folder = FunctionalConversationFolder(
        initial_state=list,
        reducer=lambda state, record: [*state, record.payload],
    )
    assert repository.fold_active(folder) == ["one", "three"]
    assert repository.fold_all(folder) == ["one", "two", "three"]

def test_conversation_repository_forks_only_the_selected_branch() -> None:
    repository = _repository(
        records=(
            _record("root", None, "one"),
            _record("left", "root", "two"),
            _record("right", "root", "three"),
        )
    )

    forked = repository.fork(
        header=_header("forked"),
        leaf_id="left",
    )

    assert forked.header.conversation_id == "forked"
    assert [record.record_id for record in forked.records] == ["root", "left"]
    assert forked.leaf_id == "left"
    assert [record.record_id for record in repository.records] == [
        "root",
        "left",
        "right",
    ]


def test_conversation_repository_builds_deep_tree_without_recursion() -> None:
    depth = 1_500
    records = tuple(
        _record(
            str(index),
            str(index - 1) if index else None,
            str(index),
        )
        for index in range(depth)
    )
    repository = _repository(records=records)

    tree = repository.tree()

    assert len(tree) == 1
    node = tree[0]
    visited = 1
    while node.children:
        assert len(node.children) == 1
        node = node.children[0]
        visited += 1
    assert visited == depth
    assert node.record.record_id == str(depth - 1)


@dataclass(frozen=True)
class _Projection:
    conversation_id: str
    text: str
    message_count: int


def test_conversation_catalog_projects_indexes_and_queries(tmp_path: Path) -> None:
    del tmp_path
    from loushang.harness.conversation import (
        ConversationCatalog,
        ConversationKey,
        ConversationProviderBinding,
        FunctionalConversationProjector,
        MemoryConversationIndex,
        MemoryConversationStore,
        ProjectionQuery,
    )

    projector = FunctionalConversationProjector(
        lambda header, records, leaf_id, locator: _Projection(
            conversation_id=header.conversation_id,
            text=" ".join(record.payload for record in records),
            message_count=len(records),
        )
    )

    def query_items(query, items):
        selected = query.apply(item.projection for item in items)
        by_identity = {id(item.projection): item for item in items}
        return tuple(by_identity[id(projection)] for projection in selected)

    async def scenario() -> None:
        store = MemoryConversationStore(record_id=lambda record: record.record_id)
        namespace = "test"
        for conversation_id, records in (
            ("short", (_record("s1", None, "alpha"),)),
            (
                "long",
                (
                    _record("l1", None, "alpha"),
                    _record("l2", "l1", "beta"),
                ),
            ),
            ("other", (_record("o1", None, "gamma"),)),
        ):
            await store.create(
                ConversationKey(namespace, conversation_id),
                _header(conversation_id),
                records,
                operation_id=f"create:{conversation_id}",
            )
        index = MemoryConversationIndex(query_items=query_items)
        catalog = ConversationCatalog(
            providers=(
                ConversationProviderBinding("memory", namespace, store),
            ),
            projector=projector,
            record_id=lambda record: record.record_id,
            index=index,
            query_items=query_items,
        )

        refreshed = await catalog.refresh()
        assert refreshed.complete
        assert {item.projection.conversation_id for item in refreshed.items} == {
            "long",
            "short",
            "other",
        }
        matches = await catalog.list(
            ProjectionQuery(
                predicate=lambda item: "alpha" in item.text,
                sort_key=lambda item: item.conversation_id,
                limit=1,
            )
        )
        assert [item.projection.conversation_id for item in matches.items] == ["long"]

        other = ConversationKey(namespace, "other")
        await store.delete(
            other,
            expected_revision=1,
            operation_id="delete:other",
        )
        assert len((await catalog.list(ProjectionQuery())).items) == 3
        assert len(
            (await catalog.list(ProjectionQuery(), refresh=True)).items
        ) == 2

    asyncio.run(scenario())


def test_conversation_catalog_projection_failure_policy_is_explicit() -> None:
    from loushang.harness.conversation import (
        ConversationCatalog,
        ConversationKey,
        ConversationProviderBinding,
        FunctionalConversationProjector,
        MemoryConversationIndex,
        MemoryConversationStore,
        ProjectionQuery,
    )

    def project(header, records, leaf_id, locator):
        del records, leaf_id, locator
        if header.conversation_id == "bad":
            raise ValueError("bad projection")
        return header.conversation_id

    def query_items(query, items):
        selected = query.apply(item.projection for item in items)
        by_identity = {id(item.projection): item for item in items}
        return tuple(by_identity[id(projection)] for projection in selected)

    async def scenario() -> None:
        store = MemoryConversationStore()
        namespace = "test"
        await store.create(
            ConversationKey(namespace, "good"),
            _header("good"),
            operation_id="create:good",
        )
        index = MemoryConversationIndex(query_items=query_items)
        catalog = ConversationCatalog(
            providers=(
                ConversationProviderBinding("memory", namespace, store),
            ),
            projector=FunctionalConversationProjector(project),
            record_id=lambda record: record.record_id,
            index=index,
            query_items=query_items,
        )
        first = await catalog.refresh()
        assert first.complete
        assert [item.projection for item in first.items] == ["good"]

        await store.create(
            ConversationKey(namespace, "bad"),
            _header("bad"),
            operation_id="create:bad",
        )
        partial = await catalog.refresh()
        assert not partial.complete
        assert [item.projection for item in partial.items] == ["good"]
        assert partial.diagnostics[0].code == "conversation_projection_failed"
        assert [item.projection for item in await index.query(ProjectionQuery())] == [
            "good"
        ]

    asyncio.run(scenario())


def test_conversation_catalog_disambiguates_same_key_across_providers() -> None:
    from loushang.harness.conversation import (
        ConversationCatalog,
        ConversationKey,
        ConversationProviderBinding,
        FunctionalConversationProjector,
        MemoryConversationStore,
    )

    async def scenario() -> None:
        namespace = "shared"
        key = ConversationKey(namespace, "same-id")
        first = MemoryConversationStore()
        second = MemoryConversationStore()
        await first.create(
            key,
            _header("same-id"),
            operation_id="create:first",
        )
        await second.create(
            key,
            _header("same-id"),
            operation_id="create:second",
        )
        catalog = ConversationCatalog(
            providers=(
                ConversationProviderBinding("first", namespace, first),
                ConversationProviderBinding("second", namespace, second),
            ),
            projector=FunctionalConversationProjector(
                lambda header, records, leaf_id, locator: locator.provider_id
            ),
            record_id=lambda record: record.record_id,
        )

        result = await catalog.scan()

        assert result.complete
        assert {item.locator.provider_id for item in result.items} == {
            "first",
            "second",
        }
        assert {item.locator.key for item in result.items} == {key}

    asyncio.run(scenario())


def test_conversation_contracts_reject_invalid_identity_and_query_limits() -> None:
    from loushang.harness.conversation import (
        CommandExecutionRecord,
        ConversationHeader,
        ProjectionQuery,
    )

    with pytest.raises(ValueError, match="conversation id"):
        ConversationHeader(conversation_id=" ", version=1, created_at="now")
    with pytest.raises(ValueError, match="positive"):
        ConversationHeader(conversation_id="id", version=0, created_at="now")
    with pytest.raises(TypeError, match="command"):
        CommandExecutionRecord(command=1, output="", exit_code=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exit code"):
        CommandExecutionRecord(command="true", output="", exit_code=True)
    with pytest.raises(TypeError, match="cancelled"):
        CommandExecutionRecord(
            command="true",
            output="",
            exit_code=0,
            cancelled=1,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="non-negative"):
        ProjectionQuery(limit=-1)
    with pytest.raises(TypeError, match="integer"):
        ProjectionQuery(limit=True)
    with pytest.raises(TypeError, match="boolean"):
        ProjectionQuery(reverse=1)  # type: ignore[arg-type]

    metadata = {"cwd": "/workspace", "nested": {"tags": ["original"]}}
    record = CommandExecutionRecord(
        command="",
        output="clean",
        exit_code=0,
        metadata=metadata,
    )
    metadata["nested"]["tags"].append("source-mutated")
    assert record.cancelled is False
    assert record.metadata == {
        "cwd": "/workspace",
        "nested": {"tags": ["original"]},
    }
    with pytest.raises(TypeError):
        record.metadata["cwd"] = "/other"  # type: ignore[index]

    nested = record.metadata["nested"]
    assert isinstance(nested, dict)
    nested["tags"].append("mutated")
    assert record.metadata["nested"] == {"tags": ["original"]}

    payload = asdict(record)
    assert type(payload["metadata"]) is dict
    assert json.loads(json.dumps(payload))["metadata"] == payload["metadata"]
