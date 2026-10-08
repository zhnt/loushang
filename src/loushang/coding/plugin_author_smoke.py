"""Disposable, offline Product consumption proof for data Plugin authors."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import contextmanager
from hashlib import sha256
from importlib.metadata import version
from io import StringIO
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Literal
from zipfile import BadZipFile, ZipFile

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import ProviderRequest
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.cli.application import run_cli
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.session_manager import SessionManager
from loushang.coding.ui.plugin_theme import (
    apply_coding_plugin_theme_to_screen,
    parse_coding_plugin_theme_document,
)
from loushang.harness.capabilities.prompt import expand_prompt_template
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.frontmatter import strip_frontmatter

CodingDataSmokeKind = Literal["skill", "prompt", "theme"]

_ID = re.compile(r"[a-z][a-z0-9]*\Z")
_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_SMOKE_ARGUMENTS = "Verify the author package."


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="loushang-coding-plugin-smoke",
        description="Check a Wheel in a disposable offline Coding Product.",
    )
    parser.add_argument("wheel_file")
    parser.add_argument(
        "--kind", choices=("skill", "prompt", "theme", "worker"), required=True
    )
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--resource-name")
    parser.add_argument("--contribution-id")
    parser.add_argument("--owner-id")
    args = parser.parse_args(argv)
    if args.kind == "worker":
        if args.resource_name is not None:
            parser.error("--resource-name is for data Resources only")
        if args.contribution_id is None or args.owner_id is None:
            parser.error("Worker smoke requires --contribution-id and --owner-id")
        report = smoke_coding_worker_candidate_wheel(
            args.wheel_file,
            plugin_id=args.plugin_id,
            contribution_id=args.contribution_id,
            owner_id=args.owner_id,
        )
    else:
        if args.resource_name is None:
            parser.error("Data Resource smoke requires --resource-name")
        if args.contribution_id is not None or args.owner_id is not None:
            parser.error("--contribution-id and --owner-id are for Worker only")
        report = smoke_coding_data_wheel(
            args.wheel_file,
            kind=args.kind,
            plugin_id=args.plugin_id,
            resource_name=args.resource_name,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


def smoke_coding_worker_candidate_wheel(
    wheel_path: str | Path,
    *,
    plugin_id: str,
    contribution_id: str,
    owner_id: str,
) -> dict[str, object]:
    """Prove inert Linux Worker admission and selection in a disposable Product."""

    report: dict[str, object] = {
        "status": "failed",
        "smokeProfile": "coding-worker-candidate-selection-v1",
        "artifactSha256": None,
        "productAdmission": "not_checked",
        "productSelection": "not_checked",
        "nativeRelease": "not_checked",
        "productUse": "not_checked",
        "workspace": "disposable",
    }
    if not sys.platform.startswith("linux") or os.name != "posix":
        return _failure(report, "artifact", "linux_worker_candidate_required")
    if _ID.fullmatch(plugin_id) is None:
        return _failure(report, "artifact", "invalid_profile_identity")
    try:
        wheel_bytes = _capture_wheel(Path(wheel_path))
    except (OSError, ValueError) as exc:
        return _failure(report, "artifact", "wheel_capture_refused", str(exc))
    report["artifactSha256"] = sha256(wheel_bytes).hexdigest()

    with TemporaryDirectory(prefix="loushang-worker-author-smoke-") as scratch:
        root = Path(scratch)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        captured = root / Path(wheel_path).name
        captured.write_bytes(wheel_bytes)
        with _temporary_home(root / "home"):
            layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
            settings = SettingsManager(
                global_settings_path=root / "global-settings.json",
                project_settings_path=workspace / ".loushang" / "settings.json",
            )
            try:
                cutover_and_bootstrap_coding_package_product(
                    layout,
                    settings,
                    workspace=workspace,
                    namespace_id=token_hex(32),
                    runtime_version=version("loushang"),
                    runtime_protocol_epoch=2,
                )
            except Exception as exc:
                return _failure(
                    report, "workspace_setup", "product_cutover_refused", str(exc), root
                )
            try:
                capture = _run_worker_candidate_command(
                    workspace,
                    "candidate-capture",
                    "--wheel",
                    str(captured),
                    "--contribution-id",
                    contribution_id,
                    "--owner-id",
                    owner_id,
                    "--native-platform",
                    "linux-x86_64",
                )
                binding = capture["workerCandidateBinding"]
                if not isinstance(binding, dict) or binding.get("pluginId") != plugin_id:
                    raise ValueError("Captured Worker identity differs from request")
                digest = binding["artifactDigest"]
                if digest != report["artifactSha256"]:
                    raise ValueError("Captured Worker differs from the author Wheel")
                installed = _run_worker_candidate_command(
                    workspace,
                    "candidate-install",
                    "--plugin-id",
                    plugin_id,
                    "--artifact-digest",
                    digest,
                    "--operation-id",
                    "author-smoke-install",
                )
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                return _failure(
                    report, "product_admission", "worker_candidate_admission_refused",
                    str(exc), root,
                )
            report["productAdmission"] = "passed"
            try:
                install_result = installed["candidateInstall"]
                if not isinstance(install_result, dict):
                    raise ValueError("Product install result is unavailable")
                revision = install_result["inventoryRevision"]
                if type(revision) is not int:
                    raise ValueError("Product inventory revision is unavailable")
                _run_worker_candidate_command(
                    workspace,
                    "candidate-enable",
                    "--plugin-id",
                    plugin_id,
                    "--artifact-digest",
                    digest,
                    "--operation-id",
                    "author-smoke-enable",
                    "--expected-inventory-revision",
                    str(revision),
                )
                status = _run_worker_candidate_command(
                    workspace, "candidate-status", "--plugin-id", plugin_id
                )
                selection = status["candidateSelection"]
                if (
                    not isinstance(selection, dict)
                    or selection.get("stage") != "observed_in_read"
                    or status.get("snapshotStatus") != "partial_evidence"
                    or status.get("candidateOptInAlignment") != "not_allowed"
                ):
                    raise ValueError("Selected Worker was not observed in Product")
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                return _failure(
                    report, "product_selection", "worker_candidate_selection_refused",
                    str(exc), root,
                )
            report["productSelection"] = "passed"
            report["selectedPluginVersion"] = selection["pluginVersion"]
            report["status"] = "passed"
            return report


def _run_worker_candidate_command(
    workspace: Path, action: str, *arguments: str
) -> dict[str, object]:
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_worker_native",
            "--workspace",
            str(workspace),
            action,
            *arguments,
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip()[-1000:] or "Worker command refused")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise ValueError("Worker command returned an invalid Product result")
    return result


class _OfflineAdapter:
    def __init__(self) -> None:
        self.api = f"coding-author-smoke-{token_hex(8)}"

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [serialize_message(item) for item in request.context.messages],
                "model": request.model.id,
            },
        )

    async def invoke_prepared_raw(
        self, request: ProviderRequest, prepared: PreparedModelRequest
    ) -> AsyncIterator[RawPart]:
        del request
        prepared.payload_for_transport()
        yield {"type": "response_start", "response_id": "author-smoke"}
        yield {"type": "text_delta", "text": "author smoke complete"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}

    async def invoke_raw(
        self, request: ProviderRequest
    ) -> AsyncIterator[RawPart]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part


def smoke_coding_data_wheel(
    wheel_path: str | Path,
    *,
    kind: CodingDataSmokeKind,
    plugin_id: str,
    resource_name: str,
) -> dict[str, object]:
    """Install and consume one exact Wheel in a disposable POSIX B workspace.

    This is a Product test journey, not an admission receipt for the caller's
    real workspace. The offline adapter never sends a model request to a network.
    """

    report: dict[str, object] = {
        "status": "failed",
        "artifactSha256": None,
        "productAdmission": "not_checked",
        "productSelection": "not_checked",
        "productUse": "not_checked",
        "modelTransport": "offline",
        "workspace": "disposable",
    }
    if os.name != "posix":
        return _failure(report, "artifact", "ordinary_posix_product_required")
    if kind not in {"skill", "prompt", "theme"} or _ID.fullmatch(plugin_id) is None:
        return _failure(report, "artifact", "invalid_profile_identity")
    if _NAME.fullmatch(resource_name) is None:
        return _failure(report, "artifact", "invalid_resource_name")
    try:
        wheel_bytes = _capture_wheel(Path(wheel_path))
    except (OSError, ValueError) as exc:
        return _failure(report, "artifact", "wheel_capture_refused", str(exc))
    report["artifactSha256"] = sha256(wheel_bytes).hexdigest()

    with TemporaryDirectory(prefix="loushang-author-smoke-") as scratch:
        root = Path(scratch)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        artifact_dir = root / "artifact"
        artifact_dir.mkdir(mode=0o700)
        captured = artifact_dir / Path(wheel_path).name
        captured.write_bytes(wheel_bytes)
        with _temporary_home(root / "home"):
            layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
            settings = SettingsManager(
                global_settings_path=root / "global-settings.json",
                project_settings_path=workspace / ".loushang" / "settings.json",
            )
            try:
                cutover_and_bootstrap_coding_package_product(
                    layout,
                    settings,
                    workspace=workspace,
                    namespace_id=token_hex(32),
                    runtime_version=version("loushang"),
                    runtime_protocol_epoch=2,
                )
            except Exception as exc:
                return _failure(
                    report, "workspace_setup", "product_cutover_refused", str(exc), root
                )

            install_error = _run_coding_cli(
                ("--install-package", str(captured), "--package-scope", "project"),
                workspace=workspace,
            )
            if install_error is not None:
                return _failure(
                    report, "product_admission", "product_install_refused", install_error, root
                )
            report["productAdmission"] = "passed"
            enable_error = _run_coding_cli(
                ("--enable-plugin", plugin_id), workspace=workspace
            )
            if enable_error is not None:
                return _failure(
                    report, "product_selection", "product_enable_refused", enable_error, root
                )
            if kind == "theme":
                settings.set_theme(f"plugin:{resource_name}", scope="project")
            try:
                expected_body = _document_body(
                    captured, kind=kind, plugin_id=plugin_id, resource_name=resource_name
                )
                _prove_new_session_use(
                    workspace=workspace,
                    settings=settings,
                    session_root=root / "sessions",
                    kind=kind,
                    resource_name=resource_name,
                    expected_body=expected_body,
                )
            except _SelectionRefusal as exc:
                return _failure(
                    report, "product_selection", "resource_not_selected", str(exc), root
                )
            except _UseRefusal as exc:
                report["productSelection"] = "passed"
                return _failure(
                    report, "product_use", "resource_use_unproven", str(exc), root
                )
            except Exception as exc:
                return _failure(
                    report, "product_selection", "resource_selection_unproven", str(exc), root
                )
            report["productSelection"] = "passed"
            report["productUse"] = "passed"
            report["status"] = "passed"
            return report


class _SelectionRefusal(RuntimeError):
    pass


class _UseRefusal(RuntimeError):
    pass


def _capture_wheel(path: Path) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_WHEEL_BYTES:
        raise ValueError("Wheel must be a regular file within 2 MiB")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev, opened.st_ino, opened.st_size
        ) != (before.st_dev, before.st_ino, before.st_size):
            raise ValueError("Wheel changed before capture")
        body = stream.read(_MAX_WHEEL_BYTES + 1)
        after = os.fstat(stream.fileno())
    if not 0 < len(body) <= _MAX_WHEEL_BYTES or (
        opened.st_dev, opened.st_ino, opened.st_size,
        opened.st_mtime_ns, opened.st_ctime_ns,
    ) != (
        after.st_dev, after.st_ino, after.st_size,
        after.st_mtime_ns, after.st_ctime_ns,
    ):
        raise ValueError("Wheel changed during capture")
    return body


@contextmanager
def _temporary_home(path: Path) -> Iterator[None]:
    prior = os.environ.get("LOUSHANG_HOME")
    path.mkdir(mode=0o700)
    os.environ["LOUSHANG_HOME"] = str(path)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("LOUSHANG_HOME", None)
        else:
            os.environ["LOUSHANG_HOME"] = prior


def _run_coding_cli(args: tuple[str, ...], *, workspace: Path) -> str | None:
    stderr = StringIO()
    try:
        result = asyncio.run(
            run_cli(
                list(args),
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    if result != 0:
        return stderr.getvalue().strip()[-1000:] or f"Coding CLI returned {result}"
    return None


def _document_body(
    wheel: Path, *, kind: CodingDataSmokeKind, plugin_id: str, resource_name: str
) -> str:
    member = (
        f"{plugin_id}/skills/{resource_name}/SKILL.md"
        if kind == "skill"
        else f"{plugin_id}/prompts/{resource_name}.md"
        if kind == "prompt"
        else f"{plugin_id}/themes/{resource_name}.json"
    )
    try:
        with ZipFile(wheel) as archive:
            info = archive.getinfo(member)
            if not 0 < info.file_size <= 1024 * 1024:
                raise _SelectionRefusal("selected Resource document is empty or oversized")
            body = archive.read(info).decode("utf-8")
    except (BadZipFile, KeyError, UnicodeDecodeError) as exc:
        raise _SelectionRefusal("Wheel lacks the requested Resource document") from exc
    try:
        if kind != "theme":
            body = strip_frontmatter(body).strip()
            if kind == "prompt":
                body = expand_prompt_template(body, _SMOKE_ARGUMENTS)
    except ValueError as exc:
        raise _SelectionRefusal("requested Resource frontmatter or template is invalid") from exc
    if not body:
        raise _SelectionRefusal("selected Resource document has no body")
    return body


def _prove_new_session_use(
    *,
    workspace: Path,
    settings: SettingsManager,
    session_root: Path,
    kind: CodingDataSmokeKind,
    resource_name: str,
    expected_body: str,
) -> None:
    adapter = _OfflineAdapter()
    registry = get_default_api_registry()
    registry.register_api_adapter(adapter, source_id=adapter.api)
    session = None
    try:
        manager = asyncio.run(
            SessionManager.new(session_dir=session_root, cwd=str(workspace), persist=True)
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="author-smoke-model",
                name="Author Smoke Model",
                provider="test",
                endpoint="author-smoke-offline",
                api=adapter.api,
                base_url="https://provider.invalid/v1",
                auth=Auth(kind="none"),
                capabilities=Capabilities(
                    input=("text",),
                    output=("text",),
                    context_window=128000,
                    stream=True,
                    tool_use=True,
                ),
            ),
            services=create_services(settings_manager=settings),
            composition_set="coding-standard",
        )
        bundle = session.resource_bundle
        if bundle is None:
            raise _SelectionRefusal("new Session has no Resource bundle")
        selected = (
            bundle.skills
            if kind == "skill"
            else bundle.prompts
            if kind == "prompt"
            else bundle.themes
        )
        if not any(
            item.name == resource_name and item.source_kind == "external_package"
            for item in selected
        ):
            raise _SelectionRefusal("requested external Resource is absent from new Session")
        if kind == "theme":
            try:
                expected_tokens = parse_coding_plugin_theme_document(expected_body)
                app = SimpleNamespace(transcript_theme=None, welcome_theme=None)
                current = SimpleNamespace(
                    settings_manager=settings, resource_bundle=bundle
                )
                apply_coding_plugin_theme_to_screen(app, current)
                for token, style in expected_tokens.items():
                    resolver = (
                        app.welcome_theme
                        if token.startswith("welcome.")
                        else app.transcript_theme
                    )
                    applied = resolver.resolve(token)
                    if any(applied.get(key) != value for key, value in style.items()):
                        raise RuntimeError(f"Screen did not apply Theme token {token}")
            except Exception as exc:
                raise _UseRefusal(str(exc)) from exc
            return
        invocation = (
            f"/skill:{resource_name} {_SMOKE_ARGUMENTS}"
            if kind == "skill"
            else f"/{resource_name} {_SMOKE_ARGUMENTS}"
        )
        try:
            asyncio.run(session.prompt(invocation))
            snapshots = [
                entry
                for entry in manager.get_entries()
                if entry.kind == "model.input.prepared"
            ]
            if len(snapshots) != 1:
                raise RuntimeError(
                    "new Session did not persist exactly one prepared model input"
                )
            snapshot_id = getattr(snapshots[0].payload, "snapshot_id", None)
            if not isinstance(snapshot_id, str):
                raise RuntimeError("prepared model input has no snapshot ID")
            rebuilt = manager.rebuild_model_input(snapshot_id)
            for surface in (rebuilt.logical_input, rebuilt.prepared_payload):
                user_text = tuple(_user_message_text(surface))
                if not any(expected_body in text for text in user_text):
                    raise RuntimeError(
                        "selected Resource body is absent from prepared user message"
                    )
                if any(invocation in text for text in user_text):
                    raise RuntimeError(
                        "raw slash invocation remained in prepared user message"
                    )
        except Exception as exc:
            raise _UseRefusal(str(exc)) from exc
    finally:
        try:
            if session is not None:
                asyncio.run(session.dispose())
        finally:
            registry.unregister_api_adapters(adapter.api)


def _user_message_text(logical_input: object) -> Iterator[str]:
    if not isinstance(logical_input, dict):
        return
    messages = logical_input.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    value = part.get("text")
                    if isinstance(value, str):
                        yield value


def _failure(
    report: dict[str, object],
    stage: str,
    code: str,
    detail: str | None = None,
    scratch_root: Path | None = None,
) -> dict[str, object]:
    report["failedStage"] = stage
    report["errorCode"] = code
    if stage in {"product_admission", "product_selection", "product_use"}:
        key = {
            "product_admission": "productAdmission",
            "product_selection": "productSelection",
            "product_use": "productUse",
        }[stage]
        report[key] = "failed"
    if detail:
        report["detail"] = (
            detail.replace(str(scratch_root), "<disposable-workspace>")
            if scratch_root is not None
            else detail
        )[:1000]
    return report


__all__ = ["main", "smoke_coding_data_wheel", "smoke_coding_worker_candidate_wheel"]


if __name__ == "__main__":
    raise SystemExit(main())
