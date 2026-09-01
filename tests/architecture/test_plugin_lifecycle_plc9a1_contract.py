from __future__ import annotations

import ast
from pathlib import Path

CONTRACT = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9a1-contract.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
APPLICATION = Path("src/loushang/harness/plugin_management/application.py")
AUTHOR_SDK = Path("src/loushang/plugin/__init__.py")
CLI_BINDING = Path("src/loushang/harness/cli/plugin_management.py")
CLI_LISTING = Path("src/loushang/harness/cli/plugin_listing.py")
CLI_TOGGLES = Path("src/loushang/harness/cli/resource_toggles.py")
CLI_PROFILE = Path("src/loushang/harness/cli/profile.py")
CODING_BINDING = Path("src/loushang/coding/plugin_management_cli.py")
CODING_COMPATIBILITY = Path("src/loushang/coding/plugin_enablement_compatibility.py")
CODING_BOOTSTRAP = Path("src/loushang/coding/bootstrap.py")
CODING_CONTINUITY = Path("src/loushang/coding/continuity_bootstrap.py")
SETTINGS_MANAGER = Path("src/loushang/harness/config/agent/manager.py")
CONFIG_ENGINE = Path("src/loushang/harness/config/engine.py")
CONFIG_RUNTIME = Path("src/loushang/harness/config/runtime.py")
CONFIG_FILE_TRANSACTION = Path("src/loushang/harness/config/_file_transaction.py")
JOURNAL = Path("src/loushang/harness/journal/jsonl.py")
DESIRED_LEDGER = Path("src/loushang/harness/plugin_management/ledger.py")
ENABLEMENT_MIGRATION = Path(
    "src/loushang/harness/plugin_management/enablement_migration.py"
)
CODING_LIFECYCLE = Path("src/loushang/coding/_plugin_lifecycle.py")
WINDOWS_WORKFLOW = Path(".github/workflows/windows-shell-compatibility.yml")
CODING_MANAGEMENT_TEST = Path("tests/coding/test_plugin_management_cli.py")
JOURNAL_TEST = Path("tests/harness/journal/test_jsonl.py")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plc9a1_contract_and_new_owner_sites_are_indexed() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)

    assert index.count("(plugin-lifecycle-plc9a1-contract.md)") == 1
    assert "A1-1, A1-2, and A1-3 are delivered" in contract
    assert "application.py::PluginManagementCommandApplication" in inventory
    assert "application.py::PluginManagementReadModelProjector" in inventory
    assert "application.py::PluginManagementSourceSnapshotV1" in inventory
    assert "enablement_migration.py::PluginEnablementMigrationJournal" in inventory
    assert "enablement_migration.py::PluginEnablementMigrationCoordinator" in inventory
    assert (
        "enablement_migration.py::PluginEnablementCompatibilityProjector" in inventory
    )
    assert (
        "plugin_enablement_compatibility.py::"
        "CodingPluginEnablementCompatibilityWriter" in inventory
    )
    assert "build_coding_plugin_management_cli_binding" in inventory
    assert "bootstrap.py::_create_agent_session" in inventory
    assert "continuity_bootstrap.py::bind_coding_configured_continuity" in inventory


def test_plc9a1_application_is_transport_neutral_and_projection_only() -> None:
    source = _source(APPLICATION)
    imports = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        value.startswith(
            (
                "loushang.coding",
                "loushang.harness.cli",
                "loushang.harness.host.rpc",
                "loushang.harness.config",
            )
        )
        for value in imports
    )
    for forbidden in (
        "PluginDesiredStateLedger(",
        "PluginManagementService(",
        "PluginManager(",
        "append_jsonl_record(",
        "journal_file_lock(",
        ".jsonl",
    ):
        assert forbidden not in source
    assert "class PluginManagementCommandPort(Protocol):" in source
    assert "class PluginManagementQueryPort(Protocol):" in source
    assert "class PluginManagementReadModelProjector:" in source


def test_plc9a1_does_not_widen_the_public_author_sdk() -> None:
    author_sdk = _source(AUTHOR_SDK)
    for symbol in (
        "PluginManagementCommandPort",
        "PluginManagementQueryPort",
        "PluginManagementReadModelProjector",
        "PluginManagementService",
        "PluginDesiredStateLedger",
    ):
        assert symbol not in author_sdk


def test_plc9a1_migration_uses_the_common_command_port_and_no_peer_settings() -> None:
    source = _source(
        Path("src/loushang/harness/plugin_management/enablement_migration.py")
    )

    assert "PluginManagementCommandPort" in source
    assert "PluginManagementApplicationCommandV1(" in source
    for forbidden in (
        "PluginDesiredStateLedger(",
        ".commit(",
        "PluginManager(",
        "SettingsManager(",
        "disabled_plugins =",
        "source.enabled",
    ):
        assert forbidden not in source
    assert "plugin_enablement_migration_epoch_unsupported" in source
    assert "plugin_enablement_legacy_mutation_rejected" in source


def test_plc9a1_contract_keeps_later_authority_out_of_scope() -> None:
    contract = _source(CONTRACT)

    for boundary in (
        "RPC/UI/management SDK transport bindings (PLC9A2)",
        "Plugin-bound\n  Package acquisition (PLC9B)",
        "Worker/remote topologies",
        "artifact GC",
        "private\n  data deletion",
        "(PLC9E)",
    ):
        assert boundary in contract


def test_plc9a1_cli_uses_only_the_common_application_binding() -> None:
    binding = _source(CLI_BINDING)
    listing = _source(CLI_LISTING)
    toggles = _source(CLI_TOGGLES)

    assert "PluginManagementApplicationPorts" in binding
    assert "management.query(" in listing
    assert "PluginManagementApplicationCommandV1(" in toggles
    for source in (binding, listing, toggles):
        for forbidden in (
            "PluginDesiredStateLedger(",
            "PluginManagementService(",
            "PluginResolutionAuthority(",
            "PluginManager(",
        ):
            assert forbidden not in source
    assert '_call(settings_manager, "enable_plugin"' not in toggles
    assert '_call(settings_manager, "disable_plugin"' not in toggles


def test_plc9a1_coding_transport_adapter_does_not_construct_owner_stores() -> None:
    adapter = _source(CODING_BINDING)
    compatibility = _source(CODING_COMPATIBILITY)
    lifecycle = _source(CODING_LIFECYCLE)
    windows_workflow = _source(WINDOWS_WORKFLOW)
    settings = _source(SETTINGS_MANAGER)
    config_engine = _source(CONFIG_ENGINE)
    config_runtime = _source(CONFIG_RUNTIME)
    config_file_transaction = _source(CONFIG_FILE_TRANSACTION)
    journal = _source(JOURNAL)
    coding_management_test = _source(CODING_MANAGEMENT_TEST)
    journal_test = _source(JOURNAL_TEST)
    desired_ledger = _source(DESIRED_LEDGER)
    enablement_migration = _source(ENABLEMENT_MIGRATION)

    for forbidden in (
        "PluginDesiredStateLedger(",
        "PluginEnablementMigrationJournal(",
        "PluginManagementService(",
    ):
        assert forbidden not in adapter
    assert "build_coding_plugin_management_application(" in adapter
    assert "bind_coding_plugin_enablement_compatibility(" in adapter
    assert "class CodingPluginEnablementCompatibilityWriter:" in compatibility
    assert "with _capture_existing_plugin_enablement_state(" in compatibility
    assert "journal_file_lock_at(" in lifecycle
    assert "_read_private_state_file(" in lifecycle
    assert "_capture_existing_plugin_enablement_state_portable(" in lifecycle
    assert "_pin_portable_private_directory_chain(" in lifecycle
    assert "_open_windows_private_directory(" in lifecycle
    assert "read_journal_file_at(" in lifecycle
    assert 'f"{layout.enablement_migration.name}.migration.lock"' in lifecycle
    assert 'f"{layout.desired_state.name}.lock"' in lifecycle
    assert "FILE_FLAG_OPEN_REPARSE_POINT" in _source(CONTRACT)
    assert "FILE_FLAG_BACKUP_SEMANTICS" in _source(CONTRACT)
    assert "file_flag_backup_semantics" in lifecycle
    assert "file_list_directory" in lifecycle
    assert "share_read_write" in lifecycle
    assert "tests/coding/test_plugin_management_cli.py" in windows_workflow
    assert "test_windows_descriptor_relative_read_rejects_reparse_child" in (
        coding_management_test
    )
    assert "test_windows_compatibility_reconcile_survives_full_root_aba" in (
        coding_management_test
    )
    assert r'"entry\0tail"' in journal_test
    assert "file_flag_open_reparse_point" in journal
    assert "NtCreateFile" in journal
    assert "root_directory" in journal
    assert "share_read_write" in journal
    assert 'JournalLoadPolicy(partial_tail="skip")' in desired_ledger
    assert 'JournalLoadPolicy(partial_tail="skip")' in enablement_migration
    assert "bind_plugin_enablement_legacy_mutation_guard" in compatibility
    assert "bind(self, self._assert_legacy_mutation_allowed)" in compatibility
    assert "authority_id" not in compatibility
    assert "LegacyPluginCompatibilityProjectionV1(" in compatibility
    assert "self._legacy_plugin_guard_authority" in settings
    assert "if self._legacy_plugin_guard_authority is not authority" in settings
    assert "_CodingPluginEnablementCompatibilityRegistry" in compatibility
    assert "self.projections[writer.layout] = projection" in compatibility
    assert "with self._config.transaction():" in settings
    assert "config_file_transaction_lock(path)" in config_engine
    assert "entered_transaction" in config_engine
    assert "self._enqueue_publication_unlocked(" in config_engine
    assert "def publish(self, *, _authority: object | None = None)" in config_engine
    assert config_engine.count("self._require_mutation_authority(_authority)") >= 10
    assert "self._config._bind_runtime(self._engine_authority)" in config_runtime
    assert "with self._config.transaction(" in config_runtime
    assert "_authority=self._engine_authority" in config_runtime
    assert 'lock_suffix=".config.lock"' in config_file_transaction
    assert "def build_coding_plugin_management_application(" in lifecycle
    assert "def project_coding_plugin_enablement_compatibility(" in lifecycle
    assert "not _has_trailing_newline(raw)" in journal


def test_plc9a1_documents_and_tests_the_compatibility_floor() -> None:
    contract = _source(CONTRACT)

    for boundary in (
        "minimum fence-aware runtime",
        "direct downgrade to a pre-fence\nbinary is unsupported",
        "plugin_enablement_compatibility_publish_failed",
        "Source-only rows report unknown enablement",
        "`absent` tombstone remains authoritative on restart",
    ):
        assert boundary in contract


def test_plc9a1_all_durable_coding_callers_bind_the_fence() -> None:
    binding = _source(CODING_BINDING)
    bootstrap = _source(CODING_BOOTSTRAP)
    continuity = _source(CODING_CONTINUITY)

    assert "bind_coding_plugin_enablement_compatibility(" in binding
    assert "resolve_coding_plugin_lifecycle_state_layout(" in bootstrap
    assert "bind_coding_plugin_enablement_compatibility(" in bootstrap
    assert continuity.count("bind_coding_plugin_enablement_compatibility(") == 1
    assert continuity.count("compatibility.reconcile()") == 3
    assert continuity.index("compatibility.reconcile()") < continuity.index(
        'existing = getattr(runtime, "_loushang_coding_continuity", None)'
    )
    assert "coding_plugin_compatibility_fence_unavailable" in _source(
        CODING_COMPATIBILITY
    )
    assert "_LAST_READY_STATUS_ATTRIBUTE" in continuity
    assert "_restore_ready_status(runtime, diagnostics_service)" in continuity


def test_plc9a1_preserves_source_aliases_and_package_command_boundary() -> None:
    profile = _source(CLI_PROFILE)
    toggles = _source(CLI_TOGGLES)

    assert '"--add-plugin-source", "--add-plugin"' in profile
    assert '"--remove-plugin-source", "--remove-plugin"' in profile
    assert "add_plugin_sources" in toggles
    assert "remove_plugin_sources" in toggles
    for artifact_action in (
        "materialize_package",
        "install_package",
        "update_package",
        "remove_package",
        "uninstall_package",
    ):
        assert artifact_action not in toggles
