"""Launch HarnessGUI against an isolated real AppHost for desktop acceptance.

This is an opt-in, visible Windows acceptance helper. It does not invoke a
model, install a gate, or reuse a developer's existing AppHost records.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

from loushang.agent import synthetic_model_transport
from loushang.ai.model import Capabilities, Model
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
    AppErrorCodeV1,
    AppServiceError,
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
DEFAULT_GUI_EXE = ROOT / "gui/src-tauri/target/release/harness-gui.exe"
GUI_MUX = "gui-desktop-acceptance"
PEER_MUX = "desktop-acceptance-peer"


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
async def forbidden_stream(*args, **kwargs):
    raise AssertionError("desktop acceptance must not invoke a model")
    yield  # pragma: no cover -- preserve the streaming interface


@dataclass
class AcceptanceRuntime:
    attempt: object
    app: object
    local: HostedLocalRuntimeV1
    directory: LocalConnectionDirectoryV1
    owner: LocalAppClientConnectionV1
    execution: object
    peer: object


async def create_runtime(root: Path) -> AcceptanceRuntime:
    launch = CodingHostedLaunchV1(
        root, root / "app", "gui.desktop.acceptance", root / "cwd", root / "home"
    )
    generation = token_hex(16)
    catalog = CodingHostedSessionCatalogV1(launch.scopes)
    execution = create_coding_execution_service_binding(launch.application_id)
    foreground = CodingForegroundHostedApplicationRequestV1(
        activation=HostedApplicationActivationV1(),
        generation_id=generation,
        product_version="installed-gui-desktop-acceptance",
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
            stream_fn=forbidden_stream,
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
    app = await attempt.open()
    directory = LocalConnectionDirectoryV1(root / "connection")
    local = HostedLocalRuntimeV1(
        app,
        directory,
        "workspace",
        session_execution=True,
        scopes=tuple(LocalRecordScopeV1(s.scope, s.fingerprint) for s in launch.scopes),
    )
    owner = LocalAppClientConnectionV1(directory, "workspace")
    try:
        await local.start()
        await owner.start()
        scope = launch.scopes[0]
        for name in (GUI_MUX, PEER_MUX):
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
                MuxDetachV1(
                    initial.attachment_id,
                    initial.controller_generation,
                )
            )
        peer = await owner.client.attach_mux(MuxAttachV1(MuxSelectorV1(name=PEER_MUX)))
        return AcceptanceRuntime(attempt, app, local, directory, owner, execution, peer)
    except BaseException:
        await owner.close()
        await local.close()
        await attempt.close()
        raise


async def close_runtime(runtime: AcceptanceRuntime) -> None:
    await runtime.owner.close()
    await runtime.local.close()
    assert not runtime.local.cleanup_pending
    await runtime.attempt.close()


async def assert_peer_is_usable(runtime: AcceptanceRuntime) -> None:
    assert runtime.owner.execution_client is not None
    await runtime.owner.execution_client.snapshot_execution_session(
        SessionSnapshotRequestV1(
            runtime.peer.attachment_id,
            runtime.peer.controller_generation,
            runtime.peer.mux_space.members[0].member_id,
        ),
        runtime.execution.service_instance_id,
    )
    assert runtime.local.accepting


async def assert_gui_detached(runtime: AcceptanceRuntime) -> int:
    observer = runtime.app.open_client_scope()
    attached = None
    try:
        async with asyncio.timeout(5):
            while attached is None:
                try:
                    attached = await observer.attach_mux(
                        MuxAttachV1(MuxSelectorV1(name=GUI_MUX))
                    )
                except AppServiceError as error:
                    if error.code is not AppErrorCodeV1.ALREADY_ATTACHED:
                        raise
                    await asyncio.sleep(0.02)
        generation = attached.controller_generation
        await observer.detach_mux(
            MuxDetachV1(attached.attachment_id, attached.controller_generation)
        )
        return generation
    finally:
        await observer.close()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


async def run(args: argparse.Namespace, root: Path) -> None:
    runtime = await create_runtime(root)
    evidence = args.evidence_dir.resolve()
    gui = None
    result: dict[str, object] = {
        "status": "running",
        "muxName": GUI_MUX,
        "peerMuxName": PEER_MUX,
        "serviceInstanceId": runtime.execution.service_instance_id,
    }
    write_json(evidence / "launch.json", result)
    try:
        await assert_peer_is_usable(runtime)
        print(
            "\nReal AppHost is ready. Starting the visible HarnessGUI window.",
            flush=True,
        )
        print("Manual acceptance checklist:", flush=True)
        print(
            "  [ ] Header/sidebar show Live AppHost · read-only (not fixture data)",
            flush=True,
        )
        print("  [ ] The real Coding Session projection loads", flush=True)
        print(
            f"      (native mux selection: {GUI_MUX!r}; not exposed to the WebView)",
            flush=True,
        )
        print(
            "  [ ] Composer, Send/Interrupt and fixture playback are disabled",
            flush=True,
        )
        print("  [ ] Workspace/Changes/Tasks/Subagents remain unavailable", flush=True)
        print(
            "  [ ] Normal/maximized resize does not cover transcript or composer",
            flush=True,
        )
        print(
            "Close the HarnessGUI window when visual inspection is complete.\n",
            flush=True,
        )
        gui = await asyncio.create_subprocess_exec(
            str(args.gui_exe.resolve()),
            "--loushang-app-record-root",
            str((root / "connection").resolve()),
            "--loushang-mux-name",
            GUI_MUX,
            cwd=str(ROOT),
        )
        return_code = await gui.wait()
        if return_code != 0:
            raise RuntimeError(f"HarnessGUI exited with code {return_code}")
        generation = await assert_gui_detached(runtime)
        await assert_peer_is_usable(runtime)
        result.update(
            status="passed",
            guiExitCode=return_code,
            detachedControllerGeneration=str(generation),
            sharedAppHostStillAccepting=runtime.local.accepting,
            peerSnapshotAfterGuiExit=True,
        )
        write_json(evidence / "result.json", result)
        print("Desktop lifecycle acceptance passed:", flush=True)
        print("  GUI exited cleanly and released its mux controller", flush=True)
        print("  shared AppHost remained accepting", flush=True)
        print("  independent peer Session remained snapshot-readable", flush=True)
        print(f"Evidence: {evidence / 'result.json'}", flush=True)
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(evidence / "result.json", result)
        raise
    finally:
        if gui is not None and gui.returncode is None:
            gui.terminate()
            try:
                await asyncio.wait_for(gui.wait(), 5)
            except TimeoutError:
                gui.kill()
                await gui.wait()
        await close_runtime(runtime)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gui-exe",
        type=Path,
        default=DEFAULT_GUI_EXE,
        help="release HarnessGUI executable to launch",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=ROOT / "gui/test-results/live-apphost-desktop",
        help="directory for non-secret launch/result evidence",
    )
    return parser.parse_args()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This desktop acceptance launcher requires Windows")
    parsed = parse_args()
    if not parsed.gui_exe.is_file():
        raise SystemExit(
            f"HarnessGUI executable not found: {parsed.gui_exe}\n"
            "Build it first with: pnpm --dir gui run build"
        )
    with tempfile.TemporaryDirectory(prefix="gui-desktop-acceptance-") as temporary:
        asyncio.run(run(parsed, Path(temporary).resolve()))
