from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict

import pytest

from loushang.harness.conversation.types import ConversationHeader, ConversationRecord


def record(identity, metadata=None):
    return ConversationRecord(
        record_id=identity,
        parent_id=None,
        kind="probe",
        payload_version=1,
        created_at="now",
        payload={"text": "hello"},
        metadata={} if metadata is None else metadata,
    )


def test_empty_metadata_remains_readonly_and_json_snapshots_are_detached():
    source = {}
    first = record("first", source)
    second = record("second", source)
    source["later"] = ["draft"]
    assert dict(first.metadata) == dict(second.metadata) == {}
    with pytest.raises(TypeError):
        first.metadata["draft"] = True
    copied = deepcopy(first.metadata)
    copied["draft"] = [1]
    snapshot = asdict(first)
    snapshot["metadata"]["draft"] = [2]
    assert asdict(second)["metadata"] == {}
    assert dict(first.metadata) == {}


def test_custom_mapping_length_does_not_skip_its_metadata_values():
    class CustomMetadata(Mapping):
        def __len__(self):
            return 0

        def __iter__(self):
            return iter(("owner",))

        def __getitem__(self, name):
            if name != "owner":
                raise KeyError(name)
            return {"items": [1]}

    item = record("custom", CustomMetadata())
    assert dict(item.metadata) == {"owner": {"items": [1]}}
    copied = item.metadata["owner"]
    copied["items"].append(2)
    assert item.metadata["owner"] == {"items": [1]}


@pytest.mark.parametrize("kind", ["header", "record"])
def test_batch_deepcopy_preserves_metadata_ownership(kind):
    def make(identity):
        if kind == "header":
            return ConversationHeader(
                conversation_id=identity, version=1, created_at="now"
            )
        return record(identity)

    source = [make("first"), make("second")]
    cloned = deepcopy(source)
    cloned[0].metadata["draft"] = ["changed"]
    assert "draft" not in cloned[1].metadata
    assert all(not item.metadata for item in source)
