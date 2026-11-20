"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import lifecycle as _binding


def build_lifecycle(
    layout: _binding.CodingPluginLifecycleStateLayout,
    *,
    startup_id: str | None,
    security_acceptances: _binding.PluginInstanceSecurityRetirementJournal | None,
) -> _binding.CodingPluginLifecycle:
    if not isinstance(layout, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_001"])
    resolved_startup_id = startup_id or _binding._CODING_PLUGIN_RUNTIME_BOOT_ID
    owns_process_startup_lease = _binding._hold_process_startup_lease(
        layout,
        startup_id=resolved_startup_id,
    )
    try:
        if not owns_process_startup_lease:
            _binding._prepare_private_state_layout(layout)
        core = _binding.bind_plugin_management_core(
            gc_reservations_path=layout.package_gc_reservations,
            desired_state_path=layout.desired_state,
            operation_journal_path=layout.management_operations,
            retirement_intents_path=layout.retirement_intents,
            retirement_sets_path=layout.retirement_sets,
            migration_journal_path=layout.enablement_migration,
        )
        gc_reservations = core.gc_reservations
        desired = core.desired
        retirement_sets = core.retirement_sets
        management = core.management
        enablement_journal = core.migration_journal
        enablement_journal.assert_runtime_compatible(
            supported_migration_epoch=1,
            runtime_version=_binding.version(
                _binding._RUNTIME_PROGRAM_VALUES["distribution_name"]
            ),
        )
        management.recover()
        enablement_migrations = _binding.PluginEnablementMigrationCoordinator(
            journal=enablement_journal,
            desired_state=desired,
            commands=_binding.PluginManagementCommandApplication(management),
            runtime_version=_binding.version(
                _binding._RUNTIME_PROGRAM_VALUES["distribution_name"]
            ),
        )
        runtime = _binding.bind_plugin_runtime_ledgers(
            core,
            instance_runtime_path=layout.instance_runtime,
            package_lifecycle_path=layout.package_lifecycle,
            startup_id=resolved_startup_id,
            security_acceptances=security_acceptances,
        )
        security = runtime.security
        instances = runtime.instances
        packages = runtime.packages
        owner_evidence = _binding.CodingOwnerGenerationEvidenceLedger(
            layout.owner_generation_evidence
        )
        return _binding.CodingPluginLifecycle(
            layout=layout,
            startup_id=resolved_startup_id,
            desired=desired,
            management=management,
            enablement_migrations=enablement_migrations,
            instances=instances,
            retirement_sets=retirement_sets,
            packages=packages,
            _gc_reservations=gc_reservations,
            security=security,
            owner_evidence=owner_evidence,
            _owns_process_startup_lease=owns_process_startup_lease,
        )
    except BaseException:
        if owns_process_startup_lease:
            _binding._release_process_startup_lease(
                layout,
                startup_id=resolved_startup_id,
            )
        raise


def build_management_application(
    layout: _binding.CodingPluginLifecycleStateLayout,
    *,
    source: _binding.PluginSourceProjectionSourcePort | None,
    read_only: bool,
) -> _binding.PluginManagementApplicationPorts:
    """Compose command/query ports without acquiring a Product runtime lease."""

    if not isinstance(layout, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_001"])
    owns_process_startup_lease = (
        not read_only
        and (_binding.sys.platform.startswith("linux") or _binding.os.name == "nt")
        and _binding._hold_process_startup_lease(
            layout,
            startup_id=_binding._CODING_PLUGIN_RUNTIME_BOOT_ID,
        )
    )
    try:
        if not read_only and not owns_process_startup_lease:
            _binding._prepare_private_state_layout(layout)
        load_policy = (
            _binding.JournalLoadPolicy(partial_tail="raise", create_lock=False)
            if read_only
            else None
        )
        core = _binding.bind_plugin_management_core(
            gc_reservations_path=layout.package_gc_reservations,
            desired_state_path=layout.desired_state,
            operation_journal_path=layout.management_operations,
            retirement_intents_path=layout.retirement_intents,
            retirement_sets_path=layout.retirement_sets,
            migration_journal_path=layout.enablement_migration,
            load_policy=load_policy,
        )
        desired = core.desired
        retirement_sets = core.retirement_sets
        management = core.management
        migrations = core.migration_journal
        migrations.assert_runtime_compatible(
            supported_migration_epoch=1,
            runtime_version=_binding.version(
                _binding._RUNTIME_PROGRAM_VALUES["distribution_name"]
            ),
        )
        if not read_only:
            management.recover()
        runtime = _binding.bind_plugin_runtime_ledgers(
            core,
            instance_runtime_path=layout.instance_runtime,
            package_lifecycle_path=layout.package_lifecycle,
            startup_id=_binding._CODING_PLUGIN_RUNTIME_BOOT_ID,
        )
        instances = runtime.instances
        packages = runtime.packages
        return _binding.PluginManagementApplicationPorts(
            commands=_binding.PluginManagementCommandApplication(management),
            queries=_binding.PluginManagementReadModelProjector(
                desired_state=desired,
                operations=management,
                migrations=migrations,
                source=source,
                instances=instances,
                packages=packages,
                retirement=retirement_sets,
            ),
        )
    except BaseException:
        if owns_process_startup_lease:
            _binding._release_process_startup_lease(
                layout, startup_id=_binding._CODING_PLUGIN_RUNTIME_BOOT_ID
            )
        raise
