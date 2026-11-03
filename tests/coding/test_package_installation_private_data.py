from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import TextPart, UserMessage
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.arch import INSPECT_IMPORT_GRAPH_TOOL_NAME
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.package_installation_private_data import (
    coding_arch_installation_private_data_root,
    coding_arch_session_private_data_root,
    prepare_coding_product_arch_private_data_root,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementCommandV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


def test_arch_private_data_paths_require_exact_installation_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id="coding.arch.default",
    )
    root = coding_arch_installation_private_data_root(layout, key)
    session_root = coding_arch_session_private_data_root(
        layout, key, session_id="session-one"
    )
    assert root.parent == layout.package_root / "installation-private-data"
    assert session_root.parent == root / "sessions"
    assert root == coding_arch_installation_private_data_root(layout, key)
    assert not root.exists()

    foreign = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "0" * 64,
        plugin_id="coding.arch.default",
    )
    with pytest.raises(ValueError, match="Installation key changed"):
        coding_arch_installation_private_data_root(layout, foreign)
    with pytest.raises(ValueError, match="Session identity is invalid"):
        coding_arch_session_private_data_root(layout, key, session_id="")
    assert not root.parent.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product private root")
@pytest.mark.parametrize("base_disabled", (False, True))
def test_product_arch_cache_writes_beneath_exact_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_disabled: bool
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        ControlConfig(capabilities={"coding.arch": "always"}),
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    if base_disabled:
        product = owner.runtime_owner.product_owner
        disabled = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="disable-base-for-arch-private-data",
                    idempotency_key="disable-base-for-arch-private-data",
                    expected_inventory_revision=(
                        product.desired_state.snapshot().inventory_revision
                    ),
                    installation_key=PluginInstallationKeyV1(
                        product_id="coding",
                        installation_scope="workspace",
                        scope_id=lifecycle.scope_id,
                        plugin_id="coding.base",
                    ),
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product.desired_policy_revision,
                ),
            )
        )
        assert disabled.result is not None
        assert disabled.result.disposition == "succeeded"

    async def run_session(session_file: Path | None = None) -> tuple[Path, Path]:
        manager = (
            await SessionManager.new_with_composition(
                session_dir=tmp_path / "session",
                cwd=str(workspace),
                composition_set="coding-architecture",
                persist=True,
            )
            if session_file is None
            else await SessionManager.load(session_file)
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="arch-private-root",
                name="Arch Private Root",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True,
                    input=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=create_services(settings_manager=settings),
            composition_set="coding-architecture",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            await session.prepare_model_call_runtime()
            if session_file is None:
                await manager.append_message(
                    UserMessage(
                        role="user",
                        content=[TextPart(type="text", text="resume Arch cache")],
                        timestamp=0.0,
                    )
                )
            assembly = session._coding_capability_plugin_assembly
            assert assembly is not None
            configuration = next(
                item.configuration
                for item in assembly.selection.plan.effective_configuration_set.entries
                if item.plugin_id == "coding.arch.default"
            )
            private_root = Path(str(configuration["privateDataRoot"]))
            tool = next(
                item
                for item in session.agent.tools
                if item.name == INSPECT_IMPORT_GRAPH_TOOL_NAME
            )
            await tool.execute(
                "installation-arch-cache", {"root": ".", "query": "summary"}
            )
            return private_root, manager.get_session_file()
        finally:
            await session.dispose()

    try:
        private_root, session_file = asyncio.run(run_session())
    finally:
        owner.close()
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = reopened
    try:
        resumed_root, _ = asyncio.run(run_session(session_file))
    finally:
        reopened.close()
    assert resumed_root == private_root
    assert private_root.is_relative_to(
        lifecycle.package_root / "installation-private-data"
    )
    assert stat.S_IMODE(private_root.stat().st_mode) == 0o700
    assert (private_root / "import-facts-v1.json").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product private root")
def test_nonpersistent_product_arch_cache_waits_for_owner_cleanup_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    settings = SettingsManager(
        ControlConfig(capabilities={"coding.arch": "always", "coding.lsp": "disabled"})
    )

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=False,
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="arch-cleanup-retry",
                name="Arch Cleanup Retry",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True,
                    input=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=create_services(settings_manager=settings),
            composition_set="coding-architecture",
        )
        await session.prepare_model_call_runtime()
        assembly = session._coding_capability_plugin_assembly
        assert assembly is not None
        configuration = next(
            item.configuration
            for item in assembly.selection.plan.effective_configuration_set.entries
            if item.plugin_id == "coding.arch.default"
        )
        private_root = Path(str(configuration["privateDataRoot"]))
        tool = next(
            item
            for item in session.agent.tools
            if item.name == INSPECT_IMPORT_GRAPH_TOOL_NAME
        )
        await tool.execute("arch-cleanup-retry", {"root": ".", "query": "summary"})
        assert (private_root / "import-facts-v1.json").is_file()

        generation = next(
            item
            for item in session._capability_owner_generations
            if item.binding.plugin_id == "coding.arch.default"
        )
        failing_lease = generation.value.scope._leases[0]
        release = failing_lease._dispose
        assert release is not None
        attempts = 0

        def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient Product Arch owner cleanup failure")
            return release()

        failing_lease._dispose = fail_once
        with pytest.raises(
            RuntimeError, match="generation disposal remains incomplete"
        ):
            await session.dispose()
        assert attempts == 1
        assert private_root.is_dir()
        await session.dispose()
        assert attempts == 2
        assert not private_root.exists()

    asyncio.run(scenario())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product private root")
def test_arch_private_root_refuses_a_foreign_installation_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    foreign_workspace = tmp_path / "foreign"
    foreign_workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    foreign = resolve_coding_plugin_lifecycle_state_layout(foreign_workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "session", cwd=str(workspace), persist=True
        )
    )
    session_id = manager.get_header().conversation_id
    runtime = owner.factory_for_session(manager).create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id=session_id, cwd=str(workspace)
        )
    )
    try:
        runtime.activate()
        with pytest.raises(ValueError, match="not selected"):
            prepare_coding_product_arch_private_data_root(
                foreign, runtime, session_id=session_id
            )
        assert not (foreign.package_root / "installation-private-data").exists()
        private_root = prepare_coding_product_arch_private_data_root(
            lifecycle, runtime, session_id=session_id
        )
        assert private_root.is_dir()
    finally:
        runtime.dispose_runtime()
        owner.close()
