"""Disposable, offline Product consumption proof for data Plugin authors."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Iterator, Sequence
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

from loushang.ai.provider._offline_adapter import OfflineModelAdapter
from loushang.coding.cli.application import run_cli
from loushang.coding.composition.bootstrap import create_agent_session, create_services
from loushang.coding.package.pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.session.manager import SessionManager
from loushang.coding.ui.plugin_theme import (
    apply_coding_plugin_theme_to_screen,
    parse_coding_plugin_theme_document,
)
from loushang.harness.capabilities.prompt import expand_prompt_template
from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_authoring._offline_smoke import (
    capture_authoring_input,
    hold_authoring_home,
    smoke_worker_candidate_selection,
)
from loushang.harness.plugin_authoring._offline_smoke import (
    record_product_smoke_failure as _failure,
)
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
    """Prove inert native Worker admission and selection in a disposable Product."""

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
    native_platform: Literal["linux-x86_64", "windows-amd64"]
    if sys.platform == "linux" and os.name == "posix":
        native_platform = "linux-x86_64"
    elif sys.platform == "win32" and os.name == "nt":
        native_platform = "windows-amd64"
    else:
        return _failure(report, "artifact", "native_worker_candidate_required")
    if _ID.fullmatch(plugin_id) is None:
        return _failure(report, "artifact", "invalid_profile_identity")
    with _prepare_wheel_smoke(
        wheel_path, report, native_platform=native_platform
    ) as prepared:
        if prepared is None:
            return report
        root, workspace, captured, _ = prepared
        windows = native_platform == "windows-amd64"
        return smoke_worker_candidate_selection(
            report,
            root=root,
            command_prefix=(
                sys.executable,
                "-m",
                "loushang.coding.cli.package_worker_windows_candidate"
                if windows
                else "loushang.coding.cli.package_worker_native",
                "--workspace",
                str(workspace),
                *(("--windows-candidate",) if windows else ()),
            ),
            wheel=captured,
            plugin_id=plugin_id,
            contribution_id=contribution_id,
            owner_id=owner_id,
            native_platform=native_platform,
        )


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
    with _prepare_wheel_smoke(wheel_path, report) as prepared:
        if prepared is None:
            return report
        root, workspace, captured, settings = prepared
        install_error = _run_coding_cli(
            ("--install-package", str(captured), "--package-scope", "project"),
            workspace=workspace,
        )
        if install_error is not None:
            return _failure(
                report,
                "product_admission",
                "product_install_refused",
                install_error,
                root,
            )
        report["productAdmission"] = "passed"
        enable_error = _run_coding_cli(
            ("--enable-plugin", plugin_id), workspace=workspace
        )
        if enable_error is not None:
            return _failure(
                report,
                "product_selection",
                "product_enable_refused",
                enable_error,
                root,
            )
        if kind == "theme":
            settings.set_theme(f"plugin:{resource_name}", scope="project")
        try:
            expected_body = _document_body(
                captured,
                kind=kind,
                plugin_id=plugin_id,
                resource_name=resource_name,
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
                report,
                "product_selection",
                "resource_selection_unproven",
                str(exc),
                root,
            )
        report["productSelection"] = "passed"
        report["productUse"] = "passed"
        report["status"] = "passed"
        return report


class _SelectionRefusal(RuntimeError):
    pass


class _UseRefusal(RuntimeError):
    pass


@contextmanager
def _prepare_wheel_smoke(
    wheel_path: str | Path,
    report: dict[str, object],
    *,
    native_platform: str | None = None,
) -> Iterator[tuple[Path, Path, Path, SettingsManager] | None]:
    try:
        wheel_bytes = _capture_wheel(Path(wheel_path))
    except (OSError, ValueError) as exc:
        _failure(report, "artifact", "wheel_capture_refused", str(exc))
        yield None
        return
    report["artifactSha256"] = sha256(wheel_bytes).hexdigest()
    worker = native_platform is not None
    prefix = "loushang-worker-author-smoke-" if worker else "loushang-author-smoke-"
    with TemporaryDirectory(prefix=prefix) as scratch:
        root = Path(scratch)
        if worker:
            # The native Product route requires a resolved on-disk workspace.
            root = root.resolve(strict=True)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        if worker:
            workspace = workspace.resolve(strict=True)
            artifact_dir = root
        else:
            artifact_dir = root / "artifact"
            artifact_dir.mkdir(mode=0o700)
        captured = artifact_dir / Path(wheel_path).name
        captured.write_bytes(wheel_bytes)
        with hold_authoring_home(root / "home"):
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
                    windows_candidate=native_platform == "windows-amd64",
                )
            except Exception as exc:
                _failure(
                    report, "workspace_setup", "product_cutover_refused", str(exc), root
                )
                yield None
                return
            yield root, workspace, captured, settings


def _capture_wheel(path: Path) -> bytes:
    return capture_authoring_input(
        path,
        maximum_bytes=_MAX_WHEEL_BYTES,
        invalid_input="Wheel must be a regular file within 2 MiB",
        changed_before_read="Wheel changed before capture",
        changed_during_read="Wheel changed during capture",
    )



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
                raise _SelectionRefusal(
                    "selected Resource document is empty or oversized"
                )
            body = archive.read(info).decode("utf-8")
    except (BadZipFile, KeyError, UnicodeDecodeError) as exc:
        raise _SelectionRefusal("Wheel lacks the requested Resource document") from exc
    try:
        if kind != "theme":
            body = strip_frontmatter(body).strip()
            if kind == "prompt":
                body = expand_prompt_template(body, _SMOKE_ARGUMENTS)
    except ValueError as exc:
        raise _SelectionRefusal(
            "requested Resource frontmatter or template is invalid"
        ) from exc
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
    adapter = OfflineModelAdapter(
        f"coding-author-smoke-{token_hex(8)}",
        response_id="author-smoke",
        text="author smoke complete",
    )
    with adapter.registered():
        session = None
        try:
            manager = asyncio.run(
                SessionManager.new(
                    session_dir=session_root, cwd=str(workspace), persist=True
                )
            )
            session = create_agent_session(
                session_manager=manager,
                model=adapter.model(
                    model_id="author-smoke-model",
                    name="Author Smoke Model",
                    endpoint="author-smoke-offline",
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
                raise _SelectionRefusal(
                    "requested external Resource is absent from new Session"
                )
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
            if session is not None:
                asyncio.run(session.dispose())


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



__all__ = ["main", "smoke_coding_data_wheel", "smoke_coding_worker_candidate_wheel"]


if __name__ == "__main__":
    raise SystemExit(main())
