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
from functools import partial
from importlib.metadata import version
from io import StringIO
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from typing import Literal

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
    _SelectionRefusal,
    _UseRefusal,
    hold_authoring_wheel,
    prove_prepared_authoring_resource_use,
    read_authoring_wheel_document,
    require_authoring_resource_selection,
    smoke_data_plugin_use,
    smoke_worker_candidate_selection,
)
from loushang.harness.plugin_authoring._offline_smoke import (
    record_product_smoke_failure as _failure,
)
from loushang.harness.resources.frontmatter import strip_frontmatter
from loushang.harness.session._cleanup import hold_authoring_session

CodingDataSmokeKind = Literal["skill", "prompt", "theme"]

_ID = re.compile(r"[a-z][a-z0-9]*\Z")
_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
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
        def prove_resource_use() -> None:
            expected_body = _document_body(
                captured, kind=kind, plugin_id=plugin_id, resource_name=resource_name,
            )
            asyncio.run(
                _prove_new_session_use(
                    workspace=workspace,
                    settings=settings,
                    session_root=root / "sessions",
                    kind=kind,
                    resource_name=resource_name,
                    expected_body=expected_body,
                )
            )

        return smoke_data_plugin_use(
            report,
            root=root,
            wheel=captured,
            plugin_id=plugin_id,
            run_cli=partial(_run_coding_cli, workspace=workspace),
            prove_resource_use=prove_resource_use,
            after_enable=(
                partial(settings.set_theme, f"plugin:{resource_name}", scope="project")
                if kind == "theme" else None
            ),
        )


@contextmanager
def _prepare_wheel_smoke(
    wheel_path: str | Path,
    report: dict[str, object],
    *,
    native_platform: str | None = None,
) -> Iterator[tuple[Path, Path, Path, SettingsManager] | None]:
    with hold_authoring_wheel(
        wheel_path, report, native_worker=native_platform is not None,
    ) as prepared:
        if prepared is None:
            yield None
            return
        root, workspace, captured = prepared
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
    body = read_authoring_wheel_document(wheel, member)
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


async def _prove_new_session_use(
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
    async with hold_authoring_session(
        adapter.registered(),
        SessionManager,
        lambda manager: create_agent_session(
            session_manager=manager,
            model=adapter.model(
                model_id="author-smoke-model",
                name="Author Smoke Model",
                endpoint="author-smoke-offline",
            ),
            services=create_services(settings_manager=settings),
            composition_set="coding-standard",
        ),
        workspace=workspace,
        session_dir=session_root,
    ) as (manager, session):
        bundle = require_authoring_resource_selection(
            session.resource_bundle, kind=kind, name=resource_name
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
        command = f"/skill:{resource_name}" if kind == "skill" else f"/{resource_name}"
        invocation = f"{command} {_SMOKE_ARGUMENTS}"
        try:
            await session.prompt(invocation)
            prove_prepared_authoring_resource_use(
                manager, invocation=invocation, expected_body=expected_body,
            )
        except Exception as exc:
            raise _UseRefusal(str(exc)) from exc


__all__ = ["main", "smoke_coding_data_wheel", "smoke_coding_worker_candidate_wheel"]


if __name__ == "__main__":
    raise SystemExit(main())
