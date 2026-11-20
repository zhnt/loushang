"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import cast

from loushang.coding.package import product_runtime as _binding


def open_product_state(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner
    | _binding.PackageProductWindowsFencedRuntimeOwner,
    *,
    before_recovery: _binding.Callable[[], None] | None,
    require_current_admission: _binding.Callable[[], None] | None,
) -> _binding.CodingPackageProductStateOwners:
    """Open durable Product owners only for this workspace's fenced Store."""

    if not isinstance(lifecycle, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_001"])
    if not isinstance(
        epoch_runtime,
        (
            _binding.PackageProductPosixFencedRuntimeOwner,
            _binding.PackageProductWindowsFencedRuntimeOwner,
        ),
    ):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_002"])
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_003"])
    _binding._require_current_coding_product_admission(require_current_admission)
    if before_recovery is not None:
        before_recovery()
    state_root = epoch_runtime.prepare_product_state_root()
    _binding._require_current_coding_product_admission(require_current_admission)
    if before_recovery is not None:
        before_recovery()
    state_metadata = state_root.lstat()
    epoch_runtime.assert_current()
    gate = _binding.PluginPackageGcReservationJournal(
        state_root / _binding._RUNTIME_PROGRAM_VALUES["value_004"],
        parent_identity=(state_metadata.st_dev, state_metadata.st_ino),
    )
    _binding._require_current_coding_product_admission(require_current_admission)
    _binding.ensure_coding_product_backup_types(
        state_root=state_root,
        scope_id=lifecycle.scope_id,
        epoch_runtime=epoch_runtime,
        gc_gate=gate,
        before_load=before_recovery,
        require_current_admission=require_current_admission,
    )
    desired = _binding.PluginDesiredStateLedger(
        state_root / _binding._RUNTIME_PROGRAM_VALUES["value_005"], gc_gate=gate
    )
    management = _binding.PluginManagementService(
        desired_state=desired,
        operation_journal_path=state_root
        / _binding._RUNTIME_PROGRAM_VALUES["value_009"],
    )
    management.recover(
        before_replay=before_recovery,
        require_current_admission=require_current_admission,
    )
    bindings = _binding.PluginPackageGcBindingJournal(
        state_root / _binding._RUNTIME_PROGRAM_VALUES["value_006"]
    )
    worker_opt_in = _binding.CodingWorkerOptInJournal(
        state_root / _binding._RUNTIME_PROGRAM_VALUES["value_007"],
        scope_id=lifecycle.scope_id,
        gc_gate=gate,
        store_id=epoch_runtime.registry.store_id,
    )
    private_data_confirmation = _binding.PluginPrivateDataConfirmationJournal(
        state_root / _binding._RUNTIME_PROGRAM_VALUES["value_008"]
    )
    private_data_deletion = _binding.CodingArchPrivateDataDeletionJournal(state_root)
    epoch_runtime.assert_current()
    return _binding.CodingPackageProductStateOwners(
        state_root=state_root,
        gc_gate=gate,
        desired_state=desired,
        management=management,
        gc_bindings=bindings,
        worker_opt_in=worker_opt_in,
        private_data_confirmation=private_data_confirmation,
        private_data_deletion=private_data_deletion,
    )


def open_application(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace: _binding.Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    worker_candidates: bool,
    windows_candidate: bool,
    require_current_admission: _binding.Callable[[], None] | None,
) -> _binding.CodingFencedProductApplicationOwner:
    """Reopen the exact B fence and bind all first-party Coding Packages."""

    if type(worker_candidates) is not bool:
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_010"])
    if type(windows_candidate) is not bool:
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_011"])
    if _binding.os.name == "nt" and not windows_candidate:
        raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_012"])
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    epoch_owner_type = (
        _binding.PackageProductWindowsFencedRuntimeOwner
        if _binding.os.name == "nt"
        else _binding.PackageProductPosixFencedRuntimeOwner
    )
    _binding._require_current_coding_product_admission(require_current_admission)
    epoch_runtime = epoch_owner_type.open(**epoch.fenced_runtime_open_kwargs())
    try:
        state = _binding.open_coding_package_product_state(
            lifecycle,
            epoch_runtime,
            require_current_admission=require_current_admission,
        )
        _binding._require_current_coding_product_admission(require_current_admission)
        runtime_owner = _binding.open_coding_builtin_product_runtime_owner(
            lifecycle,
            epoch_runtime,
            state,
            workspace=workspace,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            worker_candidates=worker_candidates,
        )
        return _binding.CodingFencedProductApplicationOwner(
            epoch_runtime, runtime_owner
        )
    except BaseException as error:
        try:
            epoch_runtime.close()
        except BaseException:
            error.add_note(_binding._RUNTIME_PROGRAM_VALUES["value_013"])
        raise


def open_runtime(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    epoch_runtime: _binding.PackageProductPosixFencedRuntimeOwner
    | _binding.PackageProductWindowsFencedRuntimeOwner,
    state: _binding.CodingPackageProductStateOwners,
    *,
    workspace: _binding.Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    include_capabilities: bool,
    include_worker_candidates: bool,
) -> _binding.CodingPosixLocalWheelProductRuntimeOwner:
    if not isinstance(lifecycle, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_001"])
    if not isinstance(
        epoch_runtime,
        (
            _binding.PackageProductPosixFencedRuntimeOwner,
            _binding.PackageProductWindowsFencedRuntimeOwner,
        ),
    ):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_002"])
    if not isinstance(state, _binding.CodingPackageProductStateOwners):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_017"])
    if (
        not isinstance(workspace, _binding.Path)
        or not workspace.is_absolute()
        or ".." in workspace.parts
        or workspace != workspace.resolve(strict=True)
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_018"])
    scope_id = (
        "workspace:"
        + _binding.sha256(
            _binding._RUNTIME_PROGRAM_BYTES["value_001"]
            + _binding.os.fsencode(str(workspace))
        ).hexdigest()
    )
    if lifecycle.scope_id != scope_id:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_019"])
    if not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_020"])
    if type(runtime_protocol_epoch) is not int or runtime_protocol_epoch < 1:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_021"])
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_003"])
    state_root = epoch_runtime.prepare_product_state_root()
    if (
        state.state_root != state_root
        or state.gc_gate.path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_004"]
        or state.desired_state.path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_005"]
        or state.management.operation_journal_path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_009"]
        or state.management.retirement_intent_journal_path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_026"]
        or state.management.retirement_set_journal_path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_027"]
        or state.gc_bindings.path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_006"]
        or state.worker_opt_in.path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_007"]
        or state.private_data_confirmation.path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_008"]
        or state.private_data_deletion.path
        != state_root / _binding._RUNTIME_PROGRAM_VALUES["value_028"]
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_022"])
    switch = epoch_runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_023"])
    source_root = epoch_runtime.prepare_product_source_root()
    artifact = (
        _binding.prepare_windows_coding_base_product_wheel(source_root)
        if isinstance(epoch_runtime, _binding.PackageProductWindowsFencedRuntimeOwner)
        else _binding.prepare_posix_coding_base_product_wheel(source_root)
    )
    host_inputs = _binding.PosixLocalWheelProductHostInputs.current_host(
        max_transport_bytes=2 * 1024 * 1024
    )
    policy_arguments = dict(
        project_scope_id=scope_id,
        resolution_environment_fingerprint=host_inputs.environment.fingerprint,
        policy_revision=_binding.CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        quota_profile_revision=_binding._RUNTIME_PROGRAM_VALUES["value_024"],
        authority_id=_binding._RUNTIME_PROGRAM_VALUES["value_025"],
    )
    policy = (
        _binding.coding_builtin_product_local_wheel_policy(
            artifact,
            (
                _binding.prepare_windows_coding_capability_product_wheels(source_root)
                if isinstance(
                    epoch_runtime, _binding.PackageProductWindowsFencedRuntimeOwner
                )
                else _binding.prepare_posix_coding_capability_product_wheels(
                    source_root
                )
            ),
            **policy_arguments,
        )
        if include_capabilities
        else _binding.coding_base_product_local_wheel_policy(
            artifact, **policy_arguments
        )
    )

    def read_legacy_acceptance(plugin_id: str):
        if isinstance(epoch_runtime, _binding.PackageProductWindowsFencedRuntimeOwner):
            return None
        return _binding.reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=policy.policy_revision,
        )

    policy = _binding.CodingLegacyLocalBindingCatalog(
        state_root / _binding._RUNTIME_PROGRAM_VALUES["value_031"],
        source_root=source_root,
        store_id=epoch.store_id,
        namespace_id=switch.namespace_id,
        scope_id=scope_id,
        policy_revision=policy.policy_revision,
        acceptance_reader=read_legacy_acceptance,
    ).extend_policy(policy)
    policy = _binding.CodingExternalDataWheelCatalog(
        state_root / _binding._RUNTIME_PROGRAM_VALUES["value_032"],
        source_root=source_root,
        store_id=epoch.store_id,
        namespace_id=switch.namespace_id,
        scope_id=scope_id,
    ).extend_policy(policy)
    if isinstance(epoch_runtime, _binding.PackageProductPosixFencedRuntimeOwner):
        policy = _binding.CodingExternalDependencyWheelCatalog(
            state_root / _binding._RUNTIME_PROGRAM_VALUES["value_033"],
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=scope_id,
        ).extend_policy(policy)
    if include_worker_candidates:
        policy = (
            _binding.CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime,
                state_root=state_root,
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=scope_id,
            ).extend_policy(policy)
            if isinstance(
                epoch_runtime, _binding.PackageProductWindowsFencedRuntimeOwner
            )
            else _binding.CodingExternalWorkerWheelCatalog(
                state_root / _binding._RUNTIME_PROGRAM_VALUES["value_034"],
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=scope_id,
            ).extend_policy(policy)
        )
    session_owner = (
        _binding.WindowsLocalWheelProductSessionOwner(
            workspace=workspace,
            policy=policy,
            host_inputs=host_inputs,
            root_store_identity=f"{_binding._RUNTIME_PROGRAM_VALUES['value_014']}{epoch.store_id}",
            dependency_store_identity=f"{_binding._RUNTIME_PROGRAM_VALUES['value_015']}{epoch.store_id}",
            epoch_runtime=epoch_runtime,
            management=state.management,
            desired_state=state.desired_state,
            gc_bindings=state.gc_bindings,
            gc_gate=state.gc_gate,
            actor_id=_binding._RUNTIME_PROGRAM_VALUES["value_029"],
            desired_policy_revision=_binding._RUNTIME_PROGRAM_VALUES["value_030"],
            recovery_identity=f"{_binding._RUNTIME_PROGRAM_VALUES['value_016']}{epoch.store_id}",
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        )
        if isinstance(epoch_runtime, _binding.PackageProductWindowsFencedRuntimeOwner)
        else _binding.PosixLocalWheelProductSessionOwner(
            workspace=workspace,
            state_root=state.state_root,
            plugin_store_root=epoch.epoch_root(switch.namespace_id),
            policy=policy,
            environment=host_inputs.environment,
            acquisition_budgets=host_inputs.acquisition_budgets,
            inspection_budgets=host_inputs.inspection_budgets,
            closure_budgets=host_inputs.closure_budgets,
            root_store_identity=f"{_binding._RUNTIME_PROGRAM_VALUES['value_014']}{epoch.store_id}",
            dependency_store_identity=f"{_binding._RUNTIME_PROGRAM_VALUES['value_015']}{epoch.store_id}",
            epoch_runtime=epoch_runtime,
            management=state.management,
            desired_state=state.desired_state,
            gc_bindings=state.gc_bindings,
            gc_gate=state.gc_gate,
            actor_id=_binding._RUNTIME_PROGRAM_VALUES["value_029"],
            desired_policy_revision=_binding._RUNTIME_PROGRAM_VALUES["value_030"],
            recovery_identity=f"{_binding._RUNTIME_PROGRAM_VALUES['value_016']}{epoch.store_id}",
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        )
    )
    return _binding.CodingPosixLocalWheelProductRuntimeOwner(
        product_owner=session_owner
    )


@contextmanager
def workspace_selection_scope(
    self: _binding.CodingFencedProductApplicationSelection,
) -> _binding.Iterator[None]:
    with self._lock:
        if self._selection_in_progress:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_035"])
        if self._fenced:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_036"])
        self._selection_in_progress = True
        try:
            yield
        finally:
            self._selection_in_progress = False


def prepare_resume_epoch(
    self: _binding.CodingFencedProductApplicationSelection,
    workspace: _binding.Path,
    *,
    require_current_admission: _binding.Callable[[], None],
    settings_manager: _binding.SettingsManager | None,
) -> str:
    """Select original workspace storage without creating a Session lease.

    This may retain compatible storage or initialize/recover Product state.
    It is an admitted activation step, never a history read or background
    Plan operation.
    Caller authority and effect settlement remain original-owner inputs.
    """

    if not isinstance(workspace, _binding.Path) or not workspace.is_absolute():
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_037"])
    if workspace != workspace.resolve(strict=True):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_037"])
    if not callable(require_current_admission) or _binding.inspect.iscoroutinefunction(
        require_current_admission
    ):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_038"])

    def current() -> None:
        result = cast(_binding.Callable[[], object], require_current_admission)()
        if result is not None:
            if _binding.inspect.iscoroutine(result):
                result.close()
            raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_039"])
        if self._fenced:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_036"])

    with self._workspace_selection_scope():
        current()
        self._select_workspace_unlocked(
            workspace,
            settings_manager=settings_manager,
            require_current_admission=current,
        )
        current()
        return self.resume_epoch_fingerprint(workspace)


def select_workspace(
    self: _binding.CodingFencedProductApplicationSelection,
    workspace: _binding.Path,
    *,
    settings_manager: _binding.SettingsManager | None,
    require_current_admission: _binding.Callable[[], None] | None,
) -> _binding.CodingFencedProductApplicationOwner | None:
    """Use the original selection/recovery path while its lock is held."""

    if self._fenced:
        raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_036"])
    owner = self._owners.get(workspace)
    if owner is None:
        lifecycle = _binding.resolve_coding_plugin_lifecycle_state_layout(workspace)
        epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
        unadmitted_platform = (
            _binding.os.name == "posix"
            and not _binding.sys.platform.startswith("linux")
        ) or (_binding.os.name == "nt" and not self._windows_candidate)
        try:
            (epoch.control_root / _binding._RUNTIME_PROGRAM_VALUES["value_041"]).lstat()
        except FileNotFoundError:
            # Ordinary upgrades retain the existing, fence-aware legacy
            # owner. Never reinterpret existing installations/settings as
            # empty Product input or require users to replace a workspace.
            if unadmitted_platform or _binding.coding_product_inputs_need_compatibility(
                lifecycle,
                workspace=workspace,
                settings_manager=settings_manager,
            ):
                _binding._require_current_coding_product_admission(
                    require_current_admission
                )
                self._legacy_workspaces[workspace] = lifecycle
                return None
            # A Linux fresh workspace enters B before any ordinary
            # Session can prepare a legacy Plugin writer. Native
            # cutover owns the cross-process fence.
            _binding.require_fresh_coding_product_inputs_without_writes(
                lifecycle,
                workspace=workspace,
                settings_manager=settings_manager,
            )
            _binding._initialize_fresh_coding_product_for_session(
                lifecycle,
                workspace=workspace,
                settings_manager=settings_manager,
                windows_candidate=self._windows_candidate,
                require_current_admission=require_current_admission,
            )
        else:
            if unadmitted_platform:
                _binding.PackageEpochFenceJournal(
                    epoch.control_root / _binding._RUNTIME_PROGRAM_VALUES["value_041"],
                    read_only=True,
                ).current(epoch.store_id)
                raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_040"])
            _binding._retry_fresh_coding_product_bootstrap_for_session(
                lifecycle,
                workspace=workspace,
                settings_manager=settings_manager,
                windows_candidate=self._windows_candidate,
                require_current_admission=require_current_admission,
            )
        owner = _binding.open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=_binding.version(
                _binding._RUNTIME_PROGRAM_VALUES["distribution_name"]
            ),
            runtime_protocol_epoch=_binding.CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            worker_candidates=self._worker_candidates,
            windows_candidate=self._windows_candidate,
            require_current_admission=require_current_admission,
        )
        self._owners[workspace] = owner
        self._legacy_workspaces.pop(workspace, None)
    elif not self._external_bindings_current(
        owner,
        lifecycle=_binding.resolve_coding_plugin_lifecycle_state_layout(workspace),
    ):
        lifecycle = _binding.resolve_coding_plugin_lifecycle_state_layout(workspace)
        replacement = _binding.open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=_binding.version(
                _binding._RUNTIME_PROGRAM_VALUES["distribution_name"]
            ),
            runtime_protocol_epoch=_binding.CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            worker_candidates=self._worker_candidates,
            windows_candidate=self._windows_candidate,
            require_current_admission=require_current_admission,
        )
        self._retained_owners.append(owner)
        owner = replacement
        self._owners[workspace] = owner
    return owner


def resume_epoch_fingerprint(
    self: _binding.CodingFencedProductApplicationSelection, workspace: _binding.Path
) -> str:
    """Observe selected native or compatible storage without activating it.

    This is a data dependency, not content proof or effect settlement. An
    unselected workspace remains unavailable rather than opening a factory.
    """

    if not isinstance(workspace, _binding.Path) or not workspace.is_absolute():
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_042"])
    if workspace != workspace.resolve(strict=True):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_042"])
    with self._lock:
        owner = self._owners.get(workspace)
        if self._fenced:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_043"])
        if owner is None:
            lifecycle = self._legacy_workspaces.get(workspace)
            if lifecycle is None:
                raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_043"])
            epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
            try:
                (
                    epoch.control_root / _binding._RUNTIME_PROGRAM_VALUES["value_041"]
                ).lstat()
            except FileNotFoundError:
                pass
            else:
                raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_046"])
            identity = workspace.stat()
            encoded = _binding.json.dumps(
                {
                    "workspace": str(workspace),
                    "workspaceIdentity": [identity.st_dev, identity.st_ino],
                    "storage": "legacy",
                    "stateRoot": str(lifecycle.root),
                    "packageRoot": str(lifecycle.package_root),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            if len(encoded) > 8192:
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_044"])
            return _binding.sha256(
                _binding._RUNTIME_PROGRAM_BYTES["value_002"] + encoded
            ).hexdigest()
        fence = owner.epoch_runtime.observe_current_epoch_fence()
        encoded = _binding.json.dumps(
            {
                "workspace": str(workspace),
                "fence": fence.to_dict(),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > 8192:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_044"])
        if owner.epoch_runtime.observe_current_epoch_fence() != fence:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_045"])
        return _binding.sha256(
            _binding._RUNTIME_PROGRAM_BYTES["value_002"] + encoded
        ).hexdigest()


def product_owner_for_factory(
    self: _binding.CodingFencedProductApplicationSelection,
    factory: _binding.PosixLocalWheelProductRuntimeFactory
    | _binding.WindowsLocalWheelProductRuntimeFactory,
) -> (
    _binding.PosixLocalWheelProductSessionOwner
    | _binding.WindowsLocalWheelProductSessionOwner
):
    """Recover only the Product owner that issued this exact Session factory."""

    if not isinstance(
        factory,
        (
            _binding.PosixLocalWheelProductRuntimeFactory,
            _binding.WindowsLocalWheelProductRuntimeFactory,
        ),
    ):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_047"])
    with self._lock:
        if self._fenced or not self._worker_candidates:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_048"])
        matching: list[
            _binding.PosixLocalWheelProductSessionOwner
            | _binding.WindowsLocalWheelProductSessionOwner
        ] = []
        for application in (*self._owners.values(), *self._retained_owners):
            product = application.runtime_owner.product_owner
            if isinstance(factory, _binding.PosixLocalWheelProductRuntimeFactory):
                if (
                    not isinstance(product, _binding.PosixLocalWheelProductSessionOwner)
                    or factory.state_root != product.state_root
                ):
                    continue
            elif (
                not isinstance(product, _binding.WindowsLocalWheelProductSessionOwner)
                or factory.epoch_runtime is not product.epoch_runtime
                or factory.policy is not product.policy
                or factory.expected_cwd != product.workspace
            ):
                continue
            if (
                factory.management is product.management
                and factory.desired_state is product.desired_state
                and factory.gc_bindings is product.gc_bindings
                and factory.gc_gate is product.gc_gate
                and factory.runtime_lease.registry is application.epoch_runtime.registry
            ):
                matching.append(product)
        if len(matching) != 1:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_049"])
        factory.assert_workspace_current()
        matching[0].assert_root_gc_authority_current()
        return matching[0]


def external_bindings_current(
    owner: _binding.CodingFencedProductApplicationOwner,
    *,
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
) -> bool:
    product = owner.runtime_owner.product_owner
    switch = owner.epoch_runtime.cutover_result.switch_receipt
    if switch is None:
        return False
    catalog = _binding.CodingExternalDataWheelCatalog(
        product.state_root / _binding._RUNTIME_PROGRAM_VALUES["value_032"],
        source_root=product.policy.source_root,
        store_id=owner.epoch_runtime.registry.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
    )
    expected_data = tuple(
        sorted(
            (
                record.policy_binding(catalog.source_root)
                for record in catalog.records()
            ),
            key=lambda item: item.source_identity,
        )
    )
    observed_data = tuple(
        item
        for item in product.policy.bindings
        if item.source_trust_class == "local-data-only"
    )
    legacy_catalog = _binding.CodingLegacyLocalBindingCatalog(
        product.state_root / _binding._RUNTIME_PROGRAM_VALUES["value_031"],
        source_root=product.policy.source_root,
        store_id=owner.epoch_runtime.registry.store_id,
        namespace_id=switch.namespace_id,
        scope_id=lifecycle.scope_id,
        policy_revision=product.policy.policy_revision,
    )
    expected_legacy = tuple(
        sorted(
            (
                record.to_policy_binding(legacy_catalog.source_root)
                for record in legacy_catalog.read_records()
            ),
            key=lambda item: item.source_identity,
        )
    )
    observed_legacy = tuple(
        item
        for item in product.policy.bindings
        if item.source_trust_class in _binding.LEGACY_LOCAL_DATA_TRUST_CLASSES
    )
    return expected_data == observed_data and expected_legacy == observed_legacy


def close_selection(self: _binding.CodingFencedProductApplicationSelection) -> None:
    with self._lock:
        if self._selection_in_progress:
            raise RuntimeError(_binding._RUNTIME_PROGRAM_VALUES["value_035"])
        self._fenced = True
        self._legacy_workspaces.clear()
        failures: list[BaseException] = []
        for workspace, owner in tuple(self._owners.items()):
            try:
                owner.close()
            except BaseException as error:
                failures.append(error)
            else:
                del self._owners[workspace]
        for owner in tuple(self._retained_owners):
            try:
                owner.close()
            except BaseException as error:
                failures.append(error)
            else:
                self._retained_owners.remove(owner)
        if failures:
            raise failures[0]
