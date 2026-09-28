"""Read one named logical Model Input component on a selected transcript path."""

from __future__ import annotations

from collections.abc import Sequence

from loushang.foundation.json import JSONValue
from loushang.harness.transcript.kinds import (
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
)
from loushang.harness.transcript.model_input_types import (
    ModelInputComponent,
    ModelInputIntegrityError,
    ModelInputSnapshot,
    hash_model_input_json,
    thaw_model_input_json,
)
from loushang.harness.transcript.model_input_v2 import ModelInputV2Resolver
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    ModelInputMappingRootNode,
    ModelInputSnapshotV2,
)
from loushang.harness.transcript.types import AgentTranscriptRecord


class ModelInputLogicalComponentReader:
    """Reuse one ancestry index while inspecting historical snapshot roots."""

    def __init__(self, records: Sequence[AgentTranscriptRecord]) -> None:
        self._records = tuple(records)
        self._resolver = ModelInputV2Resolver(self._records)

    def read(
        self,
        snapshot_record: AgentTranscriptRecord,
        name: str,
    ) -> JSONValue | None:
        position = self._resolver.position_of(snapshot_record.record_id)
        if position is None or self._records[position] is not snapshot_record:
            raise ModelInputIntegrityError("Model Input snapshot is outside selected ancestry")
        if snapshot_record.kind != MODEL_INPUT_PREPARED_KIND:
            raise ModelInputIntegrityError("Model Input snapshot has the wrong record kind")
        snapshot = snapshot_record.payload
        if isinstance(snapshot, ModelInputSnapshot):
            if snapshot_record.payload_version != 1:
                raise ModelInputIntegrityError("Model Input snapshot uses the wrong version")
            reference = next(
                (item for item in snapshot.logical_components if item.name == name),
                None,
            )
            if reference is None:
                return None
            component_position = self._resolver.position_of(reference.record_id)
            if component_position is None or component_position >= position:
                raise ModelInputIntegrityError(
                    "Model Input component is outside snapshot ancestry"
                )
            component_record = self._records[component_position]
            component = component_record.payload
            if (
                component_record.kind != MODEL_INPUT_COMPONENT_KIND
                or component_record.payload_version != 1
                or not isinstance(component, ModelInputComponent)
            ):
                raise ModelInputIntegrityError(
                    "Model Input component reference targets the wrong fact"
                )
            if (
                component.content_hash != reference.content_hash
                or hash_model_input_json(
                    component.content, name="selected Model Input component"
                )
                != reference.content_hash
            ):
                raise ModelInputIntegrityError("Model Input component hash changed")
            return thaw_model_input_json(component.content)
        if isinstance(snapshot, ModelInputSnapshotV2):
            if snapshot_record.payload_version != MODEL_INPUT_V2_PAYLOAD_VERSION:
                raise ModelInputIntegrityError("Model Input snapshot uses the wrong version")
            root = self._resolver.validate_reference(
                snapshot.logical_root,
                owner_position=position,
            ).node
            if not isinstance(root, ModelInputMappingRootNode):
                raise ModelInputIntegrityError(
                    "Model Input logical root targets the wrong node"
                )
            entry = next((item for item in root.entries if item.name == name), None)
            if entry is None:
                return None
            root_position = self._resolver.position_of(snapshot.logical_root.record_id)
            if root_position is None:
                raise ModelInputIntegrityError("Model Input logical root is unavailable")
            if entry.value.node_kind == "sequence_tail":
                values, _hash = self._resolver.resolve_sequence_reference(
                    entry.value,
                    owner_position=root_position,
                )
                return values
            return self._resolver.resolve_value_reference(
                entry.value,
                owner_position=root_position,
            )
        raise ModelInputIntegrityError("Model Input snapshot payload is invalid")


__all__ = ["ModelInputLogicalComponentReader"]
