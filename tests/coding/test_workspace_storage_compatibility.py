from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import TextPart, UserMessage
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.control import SettingsManager
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
)
from loushang.coding.session_manager import SessionManager


def _model() -> Model:
    return Model(
        id="compatibility-test",
        name="Compatibility test",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            input=("text",), context_window=128000, max_tokens=4096
        ),
    )


@pytest.mark.parametrize("legacy_input", ("settings", "package_v4"))
def test_ordinary_upgrade_reopens_legacy_workspace_and_transcript(
    tmp_path: Path,
    legacy_input: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    project_settings = workspace / ".loushang" / "settings.json"
    if legacy_input == "settings":
        project_settings.parent.mkdir()
        project_settings.write_text('{"disabled_plugins":["coding.arch.default"]}')
    else:
        layout.package_root.mkdir(parents=True)
        # Frozen deployed v4 shape: do not generate the historical format with
        # the current writer, which could hide an incompatible format change.
        layout.package_lockfile.write_text(
            '{"version":4,"packages":[],"pluginBindings":[],"pluginBindingHeads":[]}'
        )
    services = create_services(
        settings_manager=SettingsManager(
            global_settings_path=tmp_path / "global-settings.json",
            project_settings_path=project_settings,
        )
    )

    async def scenario() -> None:
        first_manager = await SessionManager.new_with_composition(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            services=services,
            model=_model(),
        )
        try:
            await first.prepare_model_call_runtime()
            assert first.package_product_binding_id is None
            tools = first.get_active_tool_names()
            assert "read" in tools
            await first_manager.append_message(
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="keep this history")],
                    timestamp=0.0,
                )
            )
        finally:
            await first.dispose()

        transcript = first_manager.get_session_file()
        assert transcript is not None
        before = transcript.read_bytes()
        for _ in range(2):
            manager = await SessionManager.load(transcript)
            reopened = create_agent_session(
                session_manager=manager,
                services=services,
                model=_model(),
            )
            try:
                await reopened.prepare_model_call_runtime()
                assert reopened.package_product_binding_id is None
                assert reopened.get_active_tool_names() == tools
                assert transcript.read_bytes().startswith(before)
            finally:
                await reopened.dispose()

    asyncio.run(scenario())
    epoch = resolve_coding_package_epoch_layout(layout)
    assert not (epoch.control_root / "epoch.jsonl").exists()
    assert json.loads(layout.package_lockfile.read_text())["version"] == 4
    if legacy_input == "settings":
        assert json.loads(project_settings.read_text())["disabled_plugins"] == [
            "coding.arch.default"
        ]


def test_legacy_resume_observes_selected_storage_and_rejects_cutover(
    tmp_path: Path,
) -> None:
    layout = resolve_coding_plugin_lifecycle_state_layout(tmp_path)
    layout.package_root.mkdir(parents=True)
    layout.package_lockfile.write_text('{"version":4,"packages":[]}')
    selection = CodingFencedProductApplicationSelection()
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    admissions = []
    try:
        with pytest.raises(RuntimeError, match="unavailable"):
            selection.resume_epoch_fingerprint(tmp_path)
        fingerprint = selection.prepare_resume_epoch(
            tmp_path,
            require_current_admission=lambda: admissions.append(True),
        )
        assert len(admissions) >= 2
        assert len(fingerprint) == 64
        assert selection.resume_epoch_fingerprint(tmp_path) == fingerprint
        assert {
            path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
        } == before
        epoch = resolve_coding_package_epoch_layout(layout)
        epoch.control_root.mkdir(parents=True)
        journal = epoch.control_root / "epoch.jsonl"
        journal.write_bytes(b"an external cutover must invalidate the old selection\n")
        with pytest.raises(RuntimeError, match="storage epoch changed"):
            selection.resume_epoch_fingerprint(tmp_path)
        assert (
            journal.read_bytes()
            == b"an external cutover must invalidate the old selection\n"
        )
    finally:
        selection.close()
    with pytest.raises(RuntimeError, match="unavailable"):
        selection.resume_epoch_fingerprint(tmp_path)
