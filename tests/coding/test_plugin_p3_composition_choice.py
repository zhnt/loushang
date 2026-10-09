from __future__ import annotations

import asyncio
import json
import sys
from importlib.metadata import version
from io import StringIO
from types import SimpleNamespace

import pytest

from loushang.ai.types import TextPart, UserMessage
from loushang.coding._capability_plugin_composition import (
    CodingCapabilityPluginCompositionError,
)
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding._tool_authority import (
    CODING_ARCH_EXACT_OWNER_TOOL_NAMES,
    CODING_LSP_EXACT_OWNER_TOOL_NAMES,
)
from loushang.coding.bootstrap import (
    create_agent_session,
    create_agent_session_runtime,
    create_services,
)
from loushang.coding.cli import application
from loushang.coding.cli.args import parse_args
from loushang.coding.cli.composition_choice import resolve_cli_composition_choice
from loushang.coding.cli.package_cutover import main as cutover_cli_main
from loushang.coding.composition_provenance import (
    CODING_COMPOSITION_HEADER_KEY,
    composition_header_metadata,
    pinned_composition_plan,
    startup_composition_record,
)
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementCommandV1,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript.types import ExtensionData


@pytest.mark.parametrize(
    ("explicit", "capabilities", "expected"),
    [
        ("coding-minimal", {"coding.arch": "always"}, "coding-minimal"),
        ("coding-standard", {"coding.arch": "always"}, "coding-standard"),
        ("coding-architecture", {}, "coding-architecture"),
        (None, {"coding.arch": "disabled"}, "coding-architecture"),
        (None, {}, "coding-standard"),
    ],
)
def test_cli_composition_choice_precedence(
    explicit: str | None, capabilities: dict[str, str], expected: str
) -> None:
    assert resolve_cli_composition_choice(explicit, capabilities) == expected


def test_cli_exposes_new_session_choice_separately_from_preview_only_choice() -> None:
    default = parse_args([])
    selected = parse_args(["--composition-set", "coding-minimal"])
    preview = parse_args(
        ["--preview-current-plugins", "--preview-composition-set", "coding-architecture"]
    )

    assert default.composition_set is None
    assert default.preview_composition_set is None
    assert selected.composition_set == "coding-minimal"
    assert selected.preview_composition_set is None
    assert preview.composition_set is None
    assert preview.preview_composition_set == "coding-architecture"


def test_cli_composition_choice_rejects_unknown_set() -> None:
    with pytest.raises(ValueError, match="Unsupported Coding composition set"):
        resolve_cli_composition_choice("user-profile", {})


def test_materialized_direct_session_pins_composition_before_header(tmp_path) -> None:
    async def journey() -> None:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            composition_set="coding-standard",
            defer_materialization=False,
        )
        try:
            assert manager.is_persisted()
            assert pinned_composition_plan(manager.get_header().metadata) is (
                resolve_coding_composition_set("coding-standard")
            )
            assert manager.bind_new_composition_plan(
                resolve_coding_composition_set("coding-standard")
            ) is resolve_coding_composition_set("coding-standard")
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(journey())


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (["--composition-set", "coding-minimal"], "coding-minimal"),
        ([], "coding-architecture"),
    ],
)
def test_preview_uses_start_precedence_and_separates_requested_plan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    extra: list[str],
    expected: str,
) -> None:
    class Query:
        def configured_capabilities(self) -> dict[str, str]:
            return {"coding.arch": "disabled"}

    monkeypatch.setattr(
        application, "bind_coding_current_preview_query", lambda *_a, **_k: Query()
    )
    monkeypatch.setattr(
        application,
        "format_plugin_current_preview",
        lambda _query, request: json.dumps(
            {"compositionSetId": request.composition_set_id, "compiledPluginIds": []}
        ),
    )
    out, err = StringIO(), StringIO()
    result = application._run_coding_current_preview_cli(
        parse_args(["--preview-current-plugins", *extra]),
        project_root=tmp_path,
        workspace_guard=lambda: None,
        stdout=out,
        stderr=err,
    )

    assert result == 0, err.getvalue()
    document = json.loads(out.getvalue())
    assert document["compositionSetId"] == expected
    assert document["requestedComposition"]["setId"] == expected
    assert document["requestedComposition"]["planFingerprint"] == (
        resolve_coding_composition_set(expected).fingerprint
    )
    assert document["compiledPluginIds"] == []


def test_preview_rejects_settings_drift_before_publishing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Query:
        reads = 0

        def configured_capabilities(self) -> dict[str, str]:
            self.reads += 1
            return {} if self.reads == 1 else {"coding.arch": "disabled"}

    monkeypatch.setattr(
        application, "bind_coding_current_preview_query", lambda *_a, **_k: Query()
    )
    monkeypatch.setattr(
        application,
        "format_plugin_current_preview",
        lambda _query, _request: json.dumps({"compiledPluginIds": []}),
    )
    out, err = StringIO(), StringIO()
    result = application._run_coding_current_preview_cli(
        parse_args(["--preview-current-plugins"]),
        project_root=tmp_path,
        workspace_guard=lambda: None,
        stdout=out,
        stderr=err,
    )
    assert result == 1
    assert out.getvalue() == ""
    assert "plugin_preview_settings_stale" in err.getvalue()


@pytest.mark.parametrize(
    "set_id", ["coding-minimal", "coding-standard", "coding-architecture"]
)
def test_session_header_pins_canonical_composition_plan(set_id: str) -> None:
    plan = resolve_coding_composition_set(set_id)
    metadata = composition_header_metadata(plan)

    assert pinned_composition_plan(metadata) is plan
    metadata[CODING_COMPOSITION_HEADER_KEY]["planFingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="plan has changed"):
        pinned_composition_plan(metadata)
    with pytest.raises(ValueError, match="malformed"):
        pinned_composition_plan({CODING_COMPOSITION_HEADER_KEY: None})


def test_new_session_persists_choice_and_resume_refuses_an_explicit_switch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "home" / "data" / "sessions"

    async def journey() -> None:
        created_runtime = create_agent_session_runtime(
            session_dir=session_dir, composition_set="coding-minimal"
        )
        try:
            session = await created_runtime.create_session(cwd=str(workspace))
            assert pinned_composition_plan(
                session.session_manager.get_header().metadata
            ) is resolve_coding_composition_set("coding-minimal")
            startup = startup_composition_record(session.session_manager.get_entries())
            assert startup is not None
            assert startup["setId"] == "coding-minimal"
            assert startup["planFingerprint"] == (
                resolve_coding_composition_set("coding-minimal").fingerprint
            )
            assert session._get_builtin_session_info()["coding_composition"] == {
                "set_id": "coding-minimal",
                "plan_fingerprint": startup["planFingerprint"],
                "startup": startup,
            }
            await session.session_manager.append_message(
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="p3-regression")],
                    timestamp=0.0,
                )
            )
            session_file = session.get_session_file()
            assert session_file is not None and session_file.is_file()
        finally:
            await created_runtime.dispose_session_runtime()

        resumed_runtime = create_agent_session_runtime(session_dir=session_dir)
        try:
            resumed = await resumed_runtime.restore_session(session_file)
            assert pinned_composition_plan(
                resumed.session_manager.get_header().metadata
            ) is resolve_coding_composition_set("coding-minimal")
            assert startup_composition_record(resumed.session_manager.get_entries()) == startup
        finally:
            await resumed_runtime.dispose_session_runtime()

        switched_runtime = create_agent_session_runtime(
            session_dir=session_dir, composition_set="coding-architecture"
        )
        try:
            with pytest.raises(ValueError, match="pinned to coding-minimal; requested coding-architecture"):
                await switched_runtime.restore_session(session_file)
        finally:
            await switched_runtime.dispose_session_runtime()

    asyncio.run(journey())


def test_direct_session_api_seals_choice_before_first_persisted_input(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def journey() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=True
        )
        session = create_agent_session(
            session_manager=manager, composition_set="coding-minimal"
        )
        assert pinned_composition_plan(manager.get_header().metadata) is (
            resolve_coding_composition_set("coding-minimal")
        )
        with pytest.raises(ValueError, match="startup is not prepared"):
            await manager.append_message(
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="too-early")],
                    timestamp=0.0,
                )
            )
        await session.prepare_model_call_runtime()
        await manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="direct-p3")],
                timestamp=0.0,
            )
        )
        session_file = manager.get_session_file()
        assert session_file is not None and session_file.is_file()
        await session.dispose()
        restored = await SessionManager.load(session_file)
        resumed_session = create_agent_session(session_manager=restored)
        assert pinned_composition_plan(restored.get_header().metadata) is (
            resolve_coding_composition_set("coding-minimal")
        )
        await resumed_session.dispose()

    asyncio.run(journey())


def test_sealed_legacy_transcript_without_provenance_refuses_reinterpretation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def journey() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=True
        )
        await manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="legacy-p3")],
                timestamp=0.0,
            )
        )
        with pytest.raises(ValueError, match="no proven composition choice"):
            create_agent_session(
                session_manager=manager, composition_set="coding-architecture"
            )

    asyncio.run(journey())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(version=True),
        lambda value: value.update(ownerGenerations="forged"),
        lambda value: value.update(secret="unreviewed"),
        lambda value: value.update(catalogSelectionFingerprint="invalid"),
    ],
)
def test_startup_receipt_rejects_malformed_or_extra_evidence(mutation) -> None:
    record = {
        "version": 1,
        "setId": "coding-minimal",
        "planFingerprint": resolve_coding_composition_set("coding-minimal").fingerprint,
        "productPolicyRevision": None,
        "catalogSelectionFingerprint": None,
        "selectedRevisions": [],
        "ownerGenerations": [],
    }
    mutation(record)
    entry = SimpleNamespace(
        payload=ExtensionData(
            extension_type="coding.composition-startup/v1", data=record
        )
    )
    with pytest.raises(ValueError, match="startup"):
        startup_composition_record([entry])


def test_concurrent_prepare_writes_only_one_startup_receipt(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def journey() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=True
        )
        session = create_agent_session(
            session_manager=manager, composition_set="coding-minimal"
        )
        original = manager.append_custom_entry
        entered = asyncio.Event()
        release = asyncio.Event()

        async def delayed_append(custom_type: str, data: object | None = None) -> str:
            entered.set()
            await release.wait()
            return await original(custom_type, data)

        monkeypatch.setattr(manager, "append_custom_entry", delayed_append)
        first = asyncio.create_task(session.prepare_model_call_runtime())
        await entered.wait()
        second = asyncio.create_task(session.prepare_model_call_runtime())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        assert len(
            [
                entry
                for entry in manager.get_entries()
                if isinstance(entry.payload, ExtensionData)
                and entry.payload.extension_type == "coding.composition-startup/v1"
            ]
        ) == 1
        await session.dispose()

    asyncio.run(journey())


def test_schema_valid_foreign_startup_cannot_unlock_user_input(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def journey() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=True
        )
        session = create_agent_session(
            session_manager=manager, composition_set="coding-minimal"
        )
        foreign = resolve_coding_composition_set("coding-standard")
        await manager.append_custom_entry(
            "coding.composition-startup/v1",
            {
                "version": 1,
                "setId": foreign.set_id,
                "planFingerprint": foreign.fingerprint,
                "productPolicyRevision": None,
                "catalogSelectionFingerprint": None,
                "selectedRevisions": [],
                "ownerGenerations": [],
            },
        )
        with pytest.raises(ValueError, match="differs from its header"):
            manager.mark_composition_startup_prepared()
        with pytest.raises(ValueError, match="startup is not prepared"):
            await manager.append_message(
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="must not commit")],
                    timestamp=0.0,
                )
            )
        await session.dispose()

    asyncio.run(journey())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fenced Product route")
@pytest.mark.parametrize(
    ("set_id", "capabilities", "expected_plugins"),
    [
        ("coding-minimal", {"coding.arch": "always"}, set()),
        ("coding-standard", {"coding.lsp": "always"}, {"coding.base", "coding.lsp.default"}),
        (
            "coding-architecture",
            {"coding.lsp": "always", "coding.arch": "always"},
            {"coding.base", "coding.lsp.default", "coding.arch.default"},
        ),
        (
            "coding-architecture",
            {"coding.lsp": "disabled", "coding.arch": "disabled"},
            {"coding.base"},
        ),
    ],
)
def test_fenced_product_startup_records_effective_selection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    set_id: str,
    capabilities: dict[str, str],
    expected_plugins: set[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_root = workspace / "skills" / "review"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\nReview carefully.\n",
        encoding="utf-8",
    )
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()

    async def journey() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=True
        )
        session = create_agent_session(
            session_manager=manager,
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities=capabilities)
                )
            ),
            composition_set=set_id,
        )
        try:
            await session.prepare_model_call_runtime()
            record = startup_composition_record(manager.get_entries())
            assert record is not None
            assert record["setId"] == set_id
            assert isinstance(record["catalogSelectionFingerprint"], str)
            assert {item["pluginId"] for item in record["selectedRevisions"]} == (
                expected_plugins
            )
            tools = {item.name for item in session.get_all_tools()}
            assert ({"bash", "read"} <= tools) == ("coding.base" in expected_plugins)
            assert (set(CODING_LSP_EXACT_OWNER_TOOL_NAMES) <= tools) == (
                "coding.lsp.default" in expected_plugins
            )
            assert (set(CODING_ARCH_EXACT_OWNER_TOOL_NAMES) <= tools) == (
                "coding.arch.default" in expected_plugins
            )
            skills = session._skill_catalog_consumer
            assert skills is not None
            assert "review" in {item.name for item in skills.list_effective_skills()}
            command = await session.execute_command_async("session", "")
            if "coding.base" in expected_plugins:
                assert command is not None
                assert command.result["session"]["coding_composition"]["startup"] == record
            else:
                assert command is None
            await manager.append_message(
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="p3 product resume")],
                    timestamp=0.0,
                )
            )
        finally:
            await session.dispose()

        if set_id == "coding-standard":
            session_file = manager.get_session_file()
            assert session_file is not None
            restored = await SessionManager.load(session_file)
            same = create_agent_session(
                session_manager=restored,
                services=create_services(
                    settings_manager=SettingsManager(
                        ControlConfig(capabilities=capabilities)
                    )
                ),
            )
            try:
                await same.prepare_model_call_runtime()
                assert startup_composition_record(restored.get_entries()) == record
            finally:
                await same.dispose()

            changed = await SessionManager.load(session_file)
            changed_session = create_agent_session(
                session_manager=changed,
                services=create_services(
                    settings_manager=SettingsManager(
                        ControlConfig(
                            capabilities=capabilities, disabled_skills=("review",)
                        )
                    )
                ),
            )
            try:
                with pytest.raises(ValueError, match="effective composition changed"):
                    await changed_session.prepare_model_call_runtime()
            finally:
                await changed_session.dispose()

    asyncio.run(journey())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fenced Product route")
def test_cli_builder_starts_explicit_minimal_and_inferred_architecture(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()
    services = create_services(
        settings_manager=SettingsManager(
            ControlConfig(capabilities={"coding.arch": "disabled"})
        )
    )

    async def journey() -> None:
        for extra, expected in (
            (["--composition-set", "coding-minimal"], "coding-minimal"),
            ([], "coding-architecture"),
        ):
            session_parent = tmp_path / "home" / "data" / expected
            session_dir = session_parent / "sessions"
            for directory in (
                tmp_path / "home",
                tmp_path / "home" / "data",
                session_parent,
                session_dir,
            ):
                directory.mkdir(exist_ok=True, mode=0o700)
                directory.chmod(0o700)
            runtime = application.default_runtime_builder(
                args=parse_args(extra),
                cwd=workspace,
                session_dir=session_dir,
                services=services,
                tool_registry=WorkspaceToolRegistry(),
            )
            try:
                session = await runtime.create_session(cwd=str(workspace))
                assert pinned_composition_plan(
                    session.session_manager.get_header().metadata
                ) is resolve_coding_composition_set(expected)
                startup = startup_composition_record(
                    session.session_manager.get_entries()
                )
                assert startup is not None
                assert startup["setId"] == expected
            finally:
                await runtime.dispose_session_runtime()

        drift_parent = tmp_path / "home" / "data" / "drift"
        drift_dir = drift_parent / "sessions"
        drift_parent.mkdir(mode=0o700)
        drift_dir.mkdir(mode=0o700)
        drift_services = create_services(settings_manager=SettingsManager(ControlConfig()))
        runtime = application.default_runtime_builder(
            args=parse_args([]),
            cwd=workspace,
            session_dir=drift_dir,
            services=drift_services,
            tool_registry=WorkspaceToolRegistry(),
        )
        try:
            drift_services.settings_manager.update_settings(
                scope="session", capabilities={"coding.arch": "disabled"}
            )
            with pytest.raises(ValueError, match="settings changed before Session startup"):
                await runtime.create_session(cwd=str(workspace))
            assert not list(drift_dir.glob("*.jsonl"))
        finally:
            await runtime.dispose_session_runtime()

    asyncio.run(journey())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fenced Product route")
def test_disabled_base_keeps_capability_and_catalog_evidence_exact(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_root = workspace / "skills" / "review"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\nReview carefully.\n",
        encoding="utf-8",
    )
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()
    owner = open_coding_fenced_product_application_owner(
        resolve_coding_plugin_lifecycle_state_layout(workspace),
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = owner.runtime_owner.product_owner
        inventory = product.desired_state.snapshot()
        base = next(
            item
            for item in inventory.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        changed = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="p3:disable-base",
                    idempotency_key="p3:disable-base",
                    expected_inventory_revision=inventory.inventory_revision,
                    installation_key=base.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product.desired_policy_revision,
                ),
            )
        )
        assert changed.result is not None
        assert changed.result.disposition == "succeeded"
    finally:
        owner.close()

    async def journey() -> None:
        for set_id, expected in (
            ("coding-standard", {"coding.lsp.default"}),
            ("coding-architecture", {"coding.lsp.default", "coding.arch.default"}),
        ):
            manager = await SessionManager.new(
                session_dir=tmp_path / set_id, cwd=str(workspace), persist=True
            )
            session = create_agent_session(
                session_manager=manager,
                services=create_services(
                    settings_manager=SettingsManager(
                        ControlConfig(
                            capabilities={"coding.lsp": "always", "coding.arch": "always"}
                        )
                    )
                ),
                composition_set=set_id,
            )
            try:
                await session.prepare_model_call_runtime()
                record = startup_composition_record(manager.get_entries())
                assert record is not None
                assert {item["pluginId"] for item in record["selectedRevisions"]} == expected
                assert session._coding_base_product_compilation is None
                assert not {"bash", "read", "write"} & {
                    item.name for item in session.get_all_tools()
                }
                assert set(CODING_LSP_EXACT_OWNER_TOOL_NAMES) <= {
                    item.name for item in session.get_all_tools()
                }
                assert (
                    set(CODING_ARCH_EXACT_OWNER_TOOL_NAMES)
                    <= {item.name for item in session.get_all_tools()}
                ) == (set_id == "coding-architecture")
                skills = session._skill_catalog_consumer
                assert skills is not None
                assert "review" in {item.name for item in skills.list_effective_skills()}
            finally:
                await session.dispose()

        manager = await SessionManager.new(
            session_dir=tmp_path / "stale", cwd=str(workspace), persist=True
        )
        stale = create_agent_session(
            session_manager=manager,
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "always"})
                )
            ),
            composition_set="coding-standard",
        )
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            inventory = product.desired_state.snapshot()
            lsp = next(
                item
                for item in inventory.installations
                if item.installation_key.plugin_id == "coding.lsp.default"
            )
            changed = product.management.submit(
                PluginManagementCommandV1(
                    action="disable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="p3:disable-lsp",
                        idempotency_key="p3:disable-lsp",
                        expected_inventory_revision=inventory.inventory_revision,
                        installation_key=lsp.installation_key,
                        desired_state="installed_disabled",
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert changed.result is not None
            assert changed.result.disposition == "succeeded"
            with pytest.raises(
                CodingCapabilityPluginCompositionError,
                match="requires restart",
            ):
                await stale.prepare_model_call_runtime()
            assert startup_composition_record(manager.get_entries()) is None
        finally:
            await stale.dispose()
            owner.close()

    asyncio.run(journey())
