"""Detached planning reads through the original Transcript graph and Blob codec."""

from pathlib import Path
from typing import Any, cast

from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_repository,
    load_agent_transcript_file,
)
from loushang.harness.transcript.model_input import rebuild_model_input
from loushang.harness.transcript.model_input_blobs import SessionModelInputBlobCodec
from loushang.harnesswork.goal import GoalError


class PlanningHistory:
    def __init__(self, root: Path, session_id: str, blobs):
        layout = AgentTranscriptFileLayout(root)
        paths = [
            path
            for path in layout.scan_paths(layout.namespace)
            if layout.key_for_path(layout.namespace, path).conversation_id == session_id
        ]
        if len(paths) != 1:
            raise GoalError("planning Transcript missing or ambiguous")
        header, records = load_agent_transcript_file(paths[0], read_only=True)
        if header.conversation_id != session_id:
            raise GoalError("planning Transcript identity changed")
        self.repository = create_agent_transcript_repository(
            header=header, records=records
        )
        if self.repository.diagnostics:
            raise GoalError("planning Transcript graph incomplete")
        self.codec = SessionModelInputBlobCodec(blobs)

    def get_branch(self, leaf):
        return self.repository.records_to(leaf)

    def rebuild_model_input(self, snapshot_id):
        return rebuild_model_input(
            cast(Any, self.repository), snapshot_id, binary_codec=self.codec
        )
