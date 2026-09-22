"""Opt-in Windows Rust client / real Coding AppHost integration, no model calls."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from secrets import token_hex

from loushang.agent import synthetic_model_transport
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostShutdownBudgetV1,
)
from loushang.apphost.application import HostedApplicationActivationV1
from loushang.apphost.continuity import HostedApplicationContinuityActivationV1
from loushang.apphost.local import HostedLocalRuntimeV1
from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
)
from loushang.appservice.continuity_file import JsonFileApplicationContinuityStoreV1
from loushang.appservice.discovery_ports import HostedSessionDiscoveryScopeV1
from loushang.coding.bootstrap import create_services
from loushang.coding.hosted_application import (
    CODING_HOSTED_APPLICATION_PROFILE_ID,
    CodingForegroundHostedApplicationRequestV1,
)
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.coding.hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedCandidateValidatorV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.hosted_continuity import (
    CodingHostedContinuityRequestV1,
    create_coding_hosted_continuity_attempt,
)
from loushang.coding.hosted_execution import create_coding_execution_service_binding
from loushang.coding.hosted_session import CodingRealHostedSessionFactoryV1
from loushang.harness.config.agent import SettingsManager

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"
EXE = CRATE / "target/debug/connection_probe.exe"
SNAPSHOT_EXE = CRATE / "target/debug/snapshot_probe.exe"
EVENT_EXE = CRATE / "target/debug/event_probe.exe"
CONTROL_EXE = CRATE / "target/debug/control_probe.exe"


class InstalledPin:
    def __init__(self, identity):
        self._identity = identity

    @property
    def identity(self):
        return self._identity

    async def close(self):
        pass


class InstalledSource:
    """Explicit pin to process-local installed code; no hot replacement."""

    def __init__(self, identity):
        self.identity = identity

    async def acquire_pin(self):
        return InstalledPin(self.identity)


@synthetic_model_transport
async def deterministic_stream(*args, **kwargs):
    message = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="real AppHost event round")],
        api="anthropic-messages",
        endpoint="anthropic-messages",
        provider="faux",
        model="no-network",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0,
    )
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    stream.push({"type": "done", "reason": "stop", "message": message})
    return stream


async def probe(root, *, succeeds, watch=False):
    process = await asyncio.create_subprocess_exec(
        str(EXE),
        str(root),
        "5000",
        "1500" if watch else "-1",
        "--watch" if watch else "--attach",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if succeeds:
        assert process.returncode == 0, (stdout, stderr)
        assert stdout.startswith(
            b"watch stopped; detached; connection closed;"
            if watch
            else b"attachment snapshots verified; detached; connection closed;"
        )
        assert not stderr
    else:
        assert process.returncode == 1 and not stdout
        assert stderr == b"connection probe failed\n"


async def initial_snapshot(root):
    process = await asyncio.create_subprocess_exec(
        str(SNAPSHOT_EXE),
        str(root),
        "5000",
        "gui-fixture",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
    assert process.returncode == 0 and not stderr, (stdout, stderr)
    snapshot = json.loads(stdout)
    encoded = stdout.decode("utf-8")
    assert "attachmentId" not in encoded
    assert "controllerGeneration" not in encoded
    return snapshot


async def event_round(root, trigger):
    process = await asyncio.create_subprocess_exec(
        str(EVENT_EXE),
        str(root),
        "5000",
        "gui-fixture",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        initial = json.loads(await asyncio.wait_for(process.stdout.readline(), 8))
        assert initial["type"] == "initial"
        await trigger()
        rounds = []
        async with asyncio.timeout(8):
            while True:
                round_value = json.loads(await process.stdout.readline())
                assert round_value["type"] == "round"
                rounds.append(round_value["payload"])
                if any(
                    event.get("source", {}).get("kind") == "turn_completed"
                    for member in round_value["payload"]["members"]
                    for event in member["events"]
                ):
                    break
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        assert process.returncode == 0 and not stdout and not stderr, (stdout, stderr)
        return initial["payload"], rounds
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def control_round(root, session_id):
    process = await asyncio.create_subprocess_exec(
        str(CONTROL_EXE),
        str(root),
        "5000",
        "gui-fixture",
        session_id,
        "gui-native-control",
        "submit through the desktop control bridge",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        line = await asyncio.wait_for(process.stdout.readline(), 8)
        if not line:
            stdout, stderr = await process.communicate()
            raise AssertionError((process.returncode, stdout, stderr))
        control = json.loads(line)
        assert control == {"accepted": True, "reason": None, "type": "control"}, control
        rounds = []
        async with asyncio.timeout(8):
            while True:
                value = json.loads(await process.stdout.readline())
                assert value["type"] == "round"
                rounds.append(value["payload"])
                if any(
                    event.get("source", {}).get("kind") == "turn_completed"
                    for member in value["payload"]["members"]
                    for event in member["events"]
                ):
                    break
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        assert process.returncode == 0 and not stdout and not stderr, (stdout, stderr)
        return rounds
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def run(root):
    launch = CodingHostedLaunchV1(
        root, root / "app", "gui.integration", root / "cwd", root / "home"
    )
    generation = token_hex(16)
    catalog = CodingHostedSessionCatalogV1(launch.scopes)
    execution = create_coding_execution_service_binding(launch.application_id)
    foreground = CodingForegroundHostedApplicationRequestV1(
        activation=HostedApplicationActivationV1(),
        generation_id=generation,
        product_version="installed-gui-integration",
        compatibility_id=CODING_HOSTED_COMPATIBILITY_ID,
        product_admission_source=InstalledSource(
            AdmissionIdentityV1(
                generation, AppHostAdmissionSubjectKind.PRODUCT, "coding"
            )
        ),
        profile_admission_source=InstalledSource(
            AdmissionIdentityV1(
                generation,
                AppHostAdmissionSubjectKind.PROFILE,
                CODING_HOSTED_APPLICATION_PROFILE_ID,
            )
        ),
        candidate_validator=CodingHostedCandidateValidatorV1(),
        sessions=catalog,
        admitted_scopes=tuple(
            HostedSessionDiscoveryScopeV1("coding", scope.scope, scope.fingerprint)
            for scope in launch.scopes
        ),
        session_factory=CodingRealHostedSessionFactoryV1(
            services_factory=lambda cwd: create_services(
                settings_manager=SettingsManager(
                    global_settings_path=root / "settings.json",
                    project_settings_path=cwd / ".loushang/settings.json",
                )
            ),
            model=Model(
                id="no-network",
                name="No network",
                provider="faux",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    input=("text",), context_window=128000, max_tokens=4096
                ),
            ),
            stream_fn=deterministic_stream,
            tools=[],
        ),
        execution=execution,
        shutdown_budget=AppHostShutdownBudgetV1(10, 5),
    )
    attempt = create_coding_hosted_continuity_attempt(
        CodingHostedContinuityRequestV1(
            activation=HostedApplicationContinuityActivationV1(),
            foreground=foreground,
            application_id=launch.application_id,
            owner_epoch=token_hex(16),
            store=JsonFileApplicationContinuityStoreV1(launch.application_root),
        )
    )
    local = None
    connections = []
    try:
        app = await attempt.open()
        directory = LocalConnectionDirectoryV1(root / "connection")
        local = HostedLocalRuntimeV1(
            app,
            directory,
            "workspace",
            session_execution=True,
            scopes=tuple(
                LocalRecordScopeV1(s.scope, s.fingerprint) for s in launch.scopes
            ),
        )
        await local.start()
        owner = LocalAppClientConnectionV1(directory, "workspace")
        connections.append(owner)
        await owner.start()
        scope = launch.scopes[0]
        for name in ("gui-fixture", "mux-peer"):
            await owner.client.create_mux(MuxCreateV1(name))
            initial = await owner.client.attach_mux(
                MuxAttachV1(MuxSelectorV1(name=name))
            )
            await owner.client.open_member(
                MuxMemberOpenV1(
                    MuxSelectorV1(name=name),
                    SessionOpenSpecV1(
                        "coding", token_hex(16), scope.scope, scope.fingerprint, name
                    ),
                )
            )
            initial = await owner.client.attach_mux(
                MuxAttachV1(MuxSelectorV1(name=name))
            )
            await owner.client.detach_mux(
                MuxDetachV1(initial.attachment_id, initial.controller_generation)
            )
        peer = await owner.client.attach_mux(
            MuxAttachV1(MuxSelectorV1(name="mux-peer"))
        )
        await probe(root / "connection", succeeds=True)
        published = await initial_snapshot(root / "connection")
        assert published["serviceInstanceId"] == execution.service_instance_id
        assert published["muxSpace"]["name"] == "gui-fixture"
        assert len(published["sessions"]) == 1
        assert (
            published["sessions"][0]["source"]["source"]["identity"]["sessionId"]
            == published["muxSpace"]["members"][0]["session"]["sessionId"]
        )
        assert local.accepting
        # A distinct mux controller remains usable after Rust detached/closed.
        assert owner.execution_client is not None
        await owner.execution_client.snapshot_execution_session(
            SessionSnapshotRequestV1(
                peer.attachment_id,
                peer.controller_generation,
                peer.mux_space.members[0].member_id,
            ),
            execution.service_instance_id,
        )
        print(
            "Real AppHost: Rust snapshot/detach and independent mux passed", flush=True
        )
        async def trigger_turn():
            application = app._application
            service = application._service
            assert service is not None and len(service._sessions) == 2
            session = next(
                value
                for value in service._sessions.values()
                if value.identity.session_id
                == published["sessions"][0]["source"]["source"]["identity"]["sessionId"]
            )
            registry = service._execution_registry
            assert registry is not None and session._execution is not None
            record = registry.submit(
                session._execution,
                "publish one deterministic event round",
                "gui-event-round",
            )
            await registry.wait(session._execution, record)

        initial, rounds = await event_round(root / "connection", trigger_turn)
        round_value = rounds[-1]
        assert initial["connectionEpoch"] == "1"
        assert all(value["connectionEpoch"] == "1" for value in rounds)
        assert [value["sequence"] for value in rounds] == [
            str(index) for index in range(1, len(rounds) + 1)
        ]
        assert round_value["serviceInstanceId"] == execution.service_instance_id
        assert round_value["muxSpaceId"] == published["muxSpace"]["muxSpaceId"]
        assert any(member["events"] for member in round_value["members"])
        assert int(round_value["sessions"][0]["source"]["source"]["cursor"]) >= int(
            initial["sessions"][0]["source"]["source"]["cursor"]
        )
        kinds = {
            event["source"]["kind"]
            for value in rounds
            for member in value["members"]
            for event in member["events"]
            if "source" in event
        }
        assert "turn_started" in kinds and "turn_completed" in kinds
        assert "attachmentId" not in json.dumps(round_value)
        assert "controllerGeneration" not in json.dumps(round_value)
        assert local.accepting
        print(
            "Real AppHost: validated event round and authoritative snapshot passed",
            flush=True,
        )
        gui_session_id = published["sessions"][0]["source"]["source"]["identity"][
            "sessionId"
        ]
        controlled = await control_round(root / "connection", gui_session_id)
        controlled_kinds = {
            event["source"]["kind"]
            for value in controlled
            for member in value["members"]
            for event in member["events"]
            if "source" in event
        }
        assert {"user_message", "assistant_message", "turn_completed"} <= controlled_kinds
        print(
            "Real AppHost: desktop submit reached Coding AgentSession and streamed back",
            flush=True,
        )
        competing = LocalAppClientConnectionV1(directory, "workspace")
        connections.append(competing)
        await competing.start()
        held = await competing.client.attach_mux(
            MuxAttachV1(MuxSelectorV1(name="gui-fixture"))
        )
        await probe(root / "connection", succeeds=False)
        assert competing.execution_client is not None
        await competing.execution_client.snapshot_execution_session(
            SessionSnapshotRequestV1(
                held.attachment_id,
                held.controller_generation,
                held.mux_space.members[0].member_id,
            ),
            execution.service_instance_id,
        )
        await competing.client.detach_mux(
            MuxDetachV1(held.attachment_id, held.controller_generation)
        )
        await probe(root / "connection", succeeds=True)
        assert local.accepting
        print(
            "Real AppHost: controller conflict and subsequent reacquisition passed",
            flush=True,
        )
        await probe(root / "connection", succeeds=True, watch=True)
        assert local.accepting
        print("Real AppHost: continuous idle reads stopped and detached", flush=True)
        held = await competing.client.attach_mux(
            MuxAttachV1(MuxSelectorV1(name="gui-fixture"))
        )
        await competing.close()  # No detach: server owns disconnect cleanup.
        recovered = None
        async with asyncio.timeout(5):
            from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

            observer = app.open_client_scope()
            try:
                while recovered is None:
                    try:
                        recovered = await observer.attach_mux(
                            MuxAttachV1(MuxSelectorV1(name="gui-fixture"))
                        )
                    except AppServiceError as error:
                        if error.code is not AppErrorCodeV1.ALREADY_ATTACHED:
                            raise
                        await asyncio.sleep(0.01)
                assert recovered.controller_generation > held.controller_generation
                await observer.detach_mux(
                    MuxDetachV1(
                        recovered.attachment_id, recovered.controller_generation
                    )
                )
            finally:
                await observer.close()
        await probe(root / "connection", succeeds=True)
        assert local.accepting
        print(
            "Real AppHost: disconnect releases ownership without stopping shared host",
            flush=True,
        )
    finally:
        for connection in reversed(connections):
            await connection.close()
        if local is not None:
            await local.close()
            assert not local.cleanup_pending
        await attempt.close()
    print("Real AppHost: explicit owner shutdown settled", flush=True)


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This native integration requires Windows")
    subprocess.run(
        [
            str(Path.home() / ".cargo/bin/cargo.exe"),
            "+1.98.1",
            "build",
            "--locked",
            "--offline",
            "--manifest-path",
            str(CRATE / "Cargo.toml"),
            "--bin",
            "connection_probe",
            "--bin",
            "snapshot_probe",
            "--bin",
            "event_probe",
            "--bin",
            "control_probe",
        ],
        check=True,
        cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="gui-real-apphost-") as temporary:
        asyncio.run(asyncio.wait_for(run(Path(temporary).resolve()), 45))
