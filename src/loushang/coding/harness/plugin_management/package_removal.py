"""Coordinate exact Desired State removal and report the observed operation."""

from __future__ import annotations

from loushang.coding.package import product_cli as _binding


def remove_packages(
    layout: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace: _binding.Path,
    plugin_ids: _binding.Sequence[str],
    stdout: _binding.TextIO,
    stderr: _binding.TextIO,
) -> int:
    ports = _binding.build_coding_fenced_product_management_cli_ports(layout)
    current_operation_id: str | None = None
    pending_operation = False
    try:
        for plugin_id in plugin_ids:
            current_operation_id = None
            pending_operation = False
            for _attempt in range(_binding._REMOVAL_MAX_ATTEMPTS):
                projection = ports.queries.snapshot(
                    _binding.PluginManagementQueryV1(
                        correlation_id=f"cli:uninstall-package:{plugin_id}:query",
                        product_id=_binding.CODING_PRODUCT_ID,
                        installation_scope=_binding._REMOVAL_SCOPE,
                        scope_id=layout.scope_id,
                        plugin_ids=(plugin_id,),
                    )
                )
                if len(projection.installations) != 1:
                    raise ValueError(
                        f"Product Plugin Installation is unavailable: {plugin_id}"
                    )
                view = projection.installations[0]
                if view.selected_package_revision is None or view.desired_state not in {
                    "installed_disabled",
                    "installed_enabled",
                }:
                    raise ValueError(f"Product Plugin is not installed: {plugin_id}")
                revision = projection.owner_revisions.desired_state
                identity = _binding.sha256(
                    f"{_binding._REMOVAL_ID_DOMAIN}{layout.scope_id}:{plugin_id}:{revision}".encode()
                ).hexdigest()
                operation_id = f"cli-product-uninstall:{identity}"
                current_operation_id = operation_id
                result = ports.commands.submit(
                    _binding.PluginManagementApplicationCommandV1(
                        correlation_id=f"cli:uninstall-package:{plugin_id}",
                        command=_binding.PluginManagementCommandV1(
                            action="remove",
                            mutation=_binding.PluginDesiredStateMutationV1(
                                operation_id=operation_id,
                                idempotency_key=operation_id,
                                expected_inventory_revision=revision,
                                installation_key=view.installation_key,
                                desired_state="absent",
                                package_revision=None,
                                actor_id=_binding.CODING_CLI_MANAGEMENT_ACTOR_ID,
                                policy_revision=_binding.CODING_CLI_MANAGEMENT_POLICY_REVISION,
                            ),
                        ),
                    )
                )
                operation = result.operation
                if not isinstance(operation, _binding.PluginManagementOperationEventV1):
                    raise RuntimeError(
                        "Product uninstall returned incompatible evidence"
                    )
                terminal = operation.result
                if terminal is not None and terminal.disposition == "succeeded":
                    after = ports.queries.snapshot(
                        _binding.PluginManagementQueryV1(
                            correlation_id=f"cli:uninstall-package:{plugin_id}:after",
                            product_id=_binding.CODING_PRODUCT_ID,
                            installation_scope=_binding._REMOVAL_SCOPE,
                            scope_id=layout.scope_id,
                            plugin_ids=(plugin_id,),
                        )
                    )
                    installed = (
                        after.installations[0]
                        if len(after.installations) == 1
                        else None
                    )
                    _binding._write_uninstall_success(
                        stdout,
                        workspace=workspace,
                        plugin_id=plugin_id,
                        operation_id=operation_id,
                        installed=installed,
                    )
                    break
                error_code = (
                    "plugin_management_operation_incomplete"
                    if terminal is None or terminal.error_code is None
                    else terminal.error_code
                )
                pending_operation = terminal is None
                if error_code != "plugin_inventory_revision_conflict":
                    raise RuntimeError(f"Product uninstall failed: {error_code}")
            else:
                raise RuntimeError("Product uninstall could not linearize")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        if current_operation_id is None:
            _binding._write_cli_error(stderr, error)
        else:
            operation_status = "unknown"
            actor_id: str | None = None
            committed_revision: int | None = None
            try:
                observed = ports.commands.operation(
                    current_operation_id,
                    correlation_id=f"cli:failed-uninstall:{current_operation_id}",
                )
                if observed is not None and isinstance(
                    observed.operation, _binding.PluginManagementOperationEventV1
                ):
                    operation_status = observed.operation.status
                    actor_id = observed.operation.command.mutation.actor_id
                    pending_operation = observed.operation.status != "terminal"
            except (OSError, RuntimeError, ValueError):
                pass
            try:
                transition = _binding.read_coding_fenced_desired_transition(
                    layout, current_operation_id
                )
                if (
                    transition is not None
                    and transition.mutation.desired_state == "absent"
                ):
                    committed_revision = transition.inventory_revision
            except (OSError, RuntimeError, ValueError):
                pass
            _binding._write_uninstall_failure(
                stderr,
                current_operation_id=current_operation_id,
                operation_status=operation_status,
                actor_id=actor_id,
                pending_operation=pending_operation,
                committed_revision=committed_revision,
            )
        return 1
