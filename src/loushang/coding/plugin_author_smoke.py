"""Disposable, offline Product consumption proof for data Plugin authors."""

from __future__ import annotations

import asyncio
import os
import re
import stat
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from hashlib import sha256
from importlib.metadata import version
from io import StringIO
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
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
from loushang.harness.config.agent import SettingsManager

CodingDataSmokeKind = Literal["skill", "prompt"]

_ID = re.compile(r"[a-z][a-z0-9]*\Z")
_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024


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
    if kind not in {"skill", "prompt"} or _ID.fullmatch(plugin_id) is None:
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
    )
    try:
        with ZipFile(wheel) as archive:
            info = archive.getinfo(member)
            if not 0 < info.file_size <= 1024 * 1024:
                raise _SelectionRefusal("selected Resource document is empty or oversized")
            body = archive.read(info).decode("utf-8")
    except (BadZipFile, KeyError, UnicodeDecodeError) as exc:
        raise _SelectionRefusal("Wheel lacks the requested Resource document") from exc
    if kind == "skill" and body.startswith("---\n"):
        _, separator, body = body.partition("\n---\n")
        if not separator:
            raise _SelectionRefusal("Skill frontmatter is not terminated")
    body = body.strip()
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
        selected = bundle.skills if kind == "skill" else bundle.prompts
        if not any(
            item.name == resource_name and item.source_kind == "external_package"
            for item in selected
        ):
            raise _SelectionRefusal("requested external Resource is absent from new Session")
        invocation = (
            f"/skill:{resource_name} Verify the author package."
            if kind == "skill"
            else f"/{resource_name} Verify the author package."
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
            logical_input = manager.rebuild_model_input(snapshot_id).logical_input
            if not any(expected_body in text for text in _all_text(logical_input)):
                raise RuntimeError("selected Resource body is absent from prepared model input")
        except Exception as exc:
            raise _UseRefusal(str(exc)) from exc
    finally:
        try:
            if session is not None:
                asyncio.run(session.dispose())
        finally:
            registry.unregister_api_adapters(adapter.api)


def _all_text(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _all_text(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _all_text(child)


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


__all__ = ["smoke_coding_data_wheel"]
