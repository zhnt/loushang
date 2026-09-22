"""Post-stop canonical read through public transcript APIs, never a writer."""

import time
from dataclasses import asdict
from pathlib import Path

from loushang.ai.types import AssistantMessage, TextPart, UserMessage
from loushang.appserver.protocol import SessionIdentityV1
from loushang.coding.hosted_catalog import CODING_HOSTED_COMPATIBILITY_ID
from loushang.harness.transcript import (
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    AgentTranscriptProfile,
    load_agent_transcript_file,
)

from ._lmux_history_recipe import validate_history


def read_history(root: Path, identity: SessionIdentityV1, workspace: Path, *, receipt=None) -> dict:
    """Caller must first settle its original service and local owners.

    root is the explicitly selected private canonical Session root, not a search
    path. Returned text evidence does not prove that lifecycle precondition.
    """
    if type(identity) is not SessionIdentityV1 or identity.product_id != "coding":
        raise ValueError("invalid history Session identity")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid history canonical root")
    path = root / f"hosted-{identity.session_id}.jsonl"
    if path.parent != root or path.is_symlink():
        raise ValueError("invalid history canonical path")
    started = time.perf_counter()
    header, records = load_agent_transcript_file(path, read_only=True, max_bytes=2_097_152)
    hosted = header.metadata.get("coding.hosted")
    if (header.conversation_id != identity.session_id or header.parent_conversation_id is not None
            or header.metadata.get("cwd") != str(workspace)
            or not isinstance(hosted, dict)
            or set(hosted) != {"version", "compatibilityId", "continuityId", "sessionId", "scope", "scopeFingerprint", "operationId"}
            or type(hosted["version"]) is not int or hosted["version"] != 1
            or hosted["compatibilityId"] != CODING_HOSTED_COMPATIBILITY_ID
            or hosted["continuityId"] != identity.continuity_id
            or hosted["sessionId"] != identity.session_id
            or hosted["scope"] != identity.scope.value
            or hosted["scopeFingerprint"] != identity.scope_fingerprint
            or type(hosted["operationId"]) is not str or not hosted["operationId"]):
        raise ValueError("canonical history header differs from authenticated Session")
    previous, seen = None, set()
    for record in records:
        if (record.record_id in seen or record.parent_id != previous
                or record.kind in {CONTEXT_BRANCH_SUMMARY_KIND, CONTEXT_COMPACTION_CHECKPOINT_KIND}):
            raise ValueError("canonical history is not the fixed linear uncompressed chain")
        seen.add(record.record_id)
        previous = record.record_id
    projected = []
    for message in AgentTranscriptProfile.default().replay(records).messages:
        if not isinstance(message, (UserMessage, AssistantMessage)):
            raise ValueError("unexpected history message")
        content = message.content
        if isinstance(content, str):
            text = content
        else:
            if any(type(part) is not TextPart for part in content):
                raise ValueError("non-text history content")
            text = "".join(part.text for part in content)
        projected.append([message.role, text])
    result = validate_history(projected)
    if receipt is not None:
        # Exact inputs to this public read, not an unrelated post-read stat or
        # a claim that a pathname itself proves native file identity.
        receipt.update(started_at=started, completed_at=time.perf_counter(),
                       root=str(root), path=str(path), workspace=str(workspace),
                       identity={**asdict(identity), "scope": identity.scope.value},
                       canonical=dict(result))
    return result
