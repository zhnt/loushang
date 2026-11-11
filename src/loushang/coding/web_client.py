"""Browser adapter over the existing authenticated AppHost client contracts.

Owns connections, never Product execution. No credentials leave this adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from secrets import token_hex

from loushang.appserver.execution.codec import encode_response as encode_execution
from loushang.appserver.execution.model import ExecutionResponseV1
from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    AppResponseV1,
    AppServiceError,
    MuxAttachV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    SessionModelSelectV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    encode_response,
)


def app_value(value):
    return json.loads(encode_response(AppResponseV1("web", value)))["result"]


def execution_value(value):
    return json.loads(encode_execution(ExecutionResponseV1("web", value)))["result"]


class WebHostClient:
    def __init__(self, root: Path, mux_name: str | None = None, *, workspace_scope=None):
        self.directory = LocalConnectionDirectoryV1(root)
        self.connection = LocalAppClientConnectionV1(
            self.directory, "workspace", expected_product_id="coding"
        )
        self.selector = None if mux_name is None else MuxSelectorV1(name=mux_name)
        self.workspace_scope = workspace_scope
        self.attachment = None
        self.lock = asyncio.Lock()
        self.epoch = "1"

    async def start(self):
        try:
            await self.connection.start()
            if self.connection.execution_client is None:
                raise ValueError("execution_unavailable")
            if self.selector is None:
                return
            await self.attach()
            if not self.attachment.mux_space.members:
                continuity = (
                    "gui-default-"
                    + hashlib.sha256(
                        self.attachment.mux_space.mux_space_id.encode()
                    ).hexdigest()
                )
                await self.create({"title": "New Session"}, continuity)
        except BaseException:
            await self.close()
            raise

    async def close(self):
        await self.connection.close()
        self.directory.close()

    async def attach(self):
        self.attachment = await self.connection.client.attach_mux(
            MuxAttachV1(self.selector)
        )

    def control(self, session_id):
        member = next(
            item
            for item in self.attachment.mux_space.members
            if item.session.session_id == session_id
        )
        return SessionSnapshotRequestV1(
            self.attachment.attachment_id,
            self.attachment.controller_generation,
            member.member_id,
        )

    async def create(self, value, continuity=None):
        source = value.get("sourceSessionId")
        if source:
            identity = next(
                m.session
                for m in self.attachment.mux_space.members
                if m.session.session_id == source
            )
            scope, fingerprint = identity.scope, identity.scope_fingerprint
        else:
            if self.workspace_scope is None:
                raise ValueError("workspace_not_selected")
            scope, fingerprint = (
                SessionScopeV1(self.workspace_scope["scope"]),
                self.workspace_scope["scopeFingerprint"],
            )
        continuity = continuity or "gui-new-" + token_hex(16)
        mux = await self.connection.client.open_member(
            MuxMemberOpenV1(
                self.selector,
                SessionOpenSpecV1(
                    "coding",
                    continuity,
                    scope,
                    fingerprint,
                    value.get("title", "New Session"),
                ),
            )
        )
        await self.attach()
        return {
            "sessionId": next(
                m.session.session_id
                for m in mux.members
                if m.session.continuity_id == continuity
            )
        }

    async def snapshot(self):
        mux = await self.connection.client.read_mux(MuxReadV1(self.selector))
        if mux.revision != self.attachment.mux_space.revision:
            await self.attach()
        execution = self.connection.execution_client
        sessions = []
        for member in self.attachment.mux_space.members:
            snapshot = await execution.snapshot_execution_session(
                self.control(member.session.session_id), execution.service_instance_id
            )
            value = execution_value(snapshot)
            # The desktop bridge encodes source counters as decimal strings.
            for key in ("cursor", "revision"):
                value["source"]["source"][key] = str(value["source"]["source"][key])
            sessions.append(value)
        value = app_value(self.attachment.mux_space)
        value["revision"] = str(value["revision"])
        for member in value["members"]:
            member["position"] = str(member["position"])
        return {
            "connectionEpoch": self.epoch,
            "serviceInstanceId": execution.service_instance_id,
            "muxSpace": value,
            "sessions": sessions,
        }

    async def call(self, action, value):
        async with self.lock:
            if action == "snapshot":
                # Reacquire after other clients change the controller or membership.
                try:
                    return await self.snapshot()
                except AppServiceError as error:
                    if error.code.value not in {
                        "stale_attachment",
                        "attachment_lagged",
                        "snapshot_required",
                    }:
                        raise
                    await self.attach()
                    return await self.snapshot()
            if action == "create":
                return await self.create(value)
            control = self.control(value["sessionId"])
            execution = self.connection.execution_client
            if action == "submit":
                try:
                    record = await execution.submit_execution(
                        control,
                        execution.service_instance_id,
                        value["submissionId"],
                        value["text"],
                    )
                except AppServiceError as error:
                    reason = error.code.value
                    if reason in {"service_closed", "cleanup_incomplete"}:
                        reason = "submission_outcome_unknown"
                    return {
                        "accepted": False,
                        "submissionId": value["submissionId"],
                        "reason": reason,
                    }
                except (OSError, TimeoutError):
                    return {
                        "accepted": False,
                        "submissionId": value["submissionId"],
                        "reason": "submission_outcome_unknown",
                    }
                return {
                    "accepted": True,
                    "submissionId": record.submission_id,
                    "executionId": record.state.execution_id,
                }
            if action == "interrupt":
                await execution.interrupt_execution(
                    control, execution.service_instance_id, value["executionId"]
                )
                return {"accepted": True}
            if action == "models":
                return app_value(
                    await self.connection.client.list_session_models(control)
                )
            if action == "select-model":
                return app_value(
                    await self.connection.client.select_session_model(
                        SessionModelSelectV1(
                            control.attachment_id,
                            control.controller_generation,
                            control.member_id,
                            value["modelId"],
                            value.get("thinkingLevel"),
                        )
                    )
                )
            raise ValueError("unknown_operation")
