"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import product_preview as _binding


def open_preview(
    cls: type[_binding.CodingFencedProductReadOnlyPreviewOwner],
    layout: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace_guard: _binding.Callable[[], None] | None,
    worker_candidates: bool,
) -> _binding.CodingFencedProductReadOnlyPreviewOwner:
    if workspace_guard is not None:
        workspace_guard()
    if not isinstance(layout, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_002"])
    epoch = _binding.resolve_coding_package_epoch_layout(layout)
    runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs(), read_only=True
    )
    try:
        if workspace_guard is not None:
            workspace_guard()
        switch = runtime.cutover_result.switch_receipt
        if switch is None:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_003"])
        state_root = runtime.control_root / "product-state"
        source_root = runtime.control_root / "product-sources"
        require_existing_private_directory(state_root)
        base = _binding.inspect_posix_coding_base_product_wheel(source_root)
        capabilities = _binding.inspect_posix_coding_capability_product_wheels(
            source_root
        )
        host = _binding.PosixLocalWheelProductHostInputs.current_host(
            max_transport_bytes=2 * 1024 * 1024
        )
        policy = _binding.coding_builtin_product_local_wheel_policy(
            base,
            capabilities,
            project_scope_id=layout.scope_id,
            resolution_environment_fingerprint=host.environment.fingerprint,
            policy_revision=_binding._RUNTIME_PROGRAM_VALUES["value_004"],
            quota_profile_revision=_binding._RUNTIME_PROGRAM_VALUES["value_005"],
            authority_id=_binding._RUNTIME_PROGRAM_VALUES["value_006"],
        )
        policy = _binding.CodingLegacyLocalBindingCatalog(
            state_root / _binding._RUNTIME_PROGRAM_VALUES["value_010"],
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=layout.scope_id,
            policy_revision=policy.policy_revision,
            acceptance_reader=lambda plugin_id: (
                _binding.reopen_coding_legacy_installed_local_acceptance(
                    layout,
                    runtime,
                    plugin_id=plugin_id,
                    policy_revision=policy.policy_revision,
                )
            ),
        ).read_extend_policy(policy)
        policy = _binding.CodingExternalDataWheelCatalog(
            state_root / _binding._RUNTIME_PROGRAM_VALUES["value_011"],
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=layout.scope_id,
            read_only=True,
        ).extend_policy(policy)
        policy = _binding.CodingExternalDependencyWheelCatalog(
            state_root / _binding._RUNTIME_PROGRAM_VALUES["value_012"],
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=layout.scope_id,
            read_only=True,
        ).extend_policy(policy)
        if worker_candidates:
            policy = _binding.CodingExternalWorkerWheelCatalog(
                state_root / _binding._RUNTIME_PROGRAM_VALUES["value_015"],
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=layout.scope_id,
                read_only=True,
            ).extend_policy(policy)
        strict = _binding.JournalLoadPolicy(partial_tail="raise", create_lock=False)
        desired_binding = _binding.bind_plugin_desired_state(
            state_root / _binding._RUNTIME_PROGRAM_VALUES["value_007"],
            state_root / _binding._RUNTIME_PROGRAM_VALUES["value_008"],
            load_policy=strict,
        )
        settlements = _binding.PackageStoreSettlementJournal(
            state_root / _binding._RUNTIME_PROGRAM_VALUES["value_009"]
        )
        root_reader = _binding.PackageProductSelectedRootReader(
            product_id=policy.product_id,
            scope_id=policy.project_scope_id,
            installation_scope="workspace",
            desired_state=desired_binding.desired,
            bindings=_binding.PluginPackageGcBindingJournal(
                state_root / _binding._RUNTIME_PROGRAM_VALUES["value_013"]
            ),
            committed_sets=_binding.PackageCommittedSetJournal(
                state_root / _binding._RUNTIME_PROGRAM_VALUES["value_014"]
            ),
            root_settlements=settlements,
            root_store=_binding.PosixPackagePluginRootReadOnlyStore(
                epoch.epoch_root(switch.namespace_id),
                store_identity=f"{_binding._RUNTIME_PROGRAM_VALUES['value_001']}{epoch.store_id}",
                settlement_journal=settlements,
            ),
            gc_gate=desired_binding.gc_reservations,
        )
        runtime.assert_current()
        if workspace_guard is not None:
            workspace_guard()
        return cls(
            epoch_runtime=runtime,
            policy=policy,
            selected_manifests=_binding._LocalWheelSelectedManifestReader(
                policy=policy, root_reader=root_reader, read_only=True
            ),
            gc_gate=desired_binding.gc_reservations,
            worker_candidates=worker_candidates,
        )
    except BaseException:
        runtime.close()
        raise


def worker_candidate_evidence(
    self: _binding.CodingFencedProductReadOnlyPreviewOwner, plugin_id: str
) -> _binding.CodingWorkerCandidateReadEvidenceV1:
    """Preserve the Product-selected artifact and native profile identity."""

    if not self.worker_candidates:
        raise PermissionError(_binding._RUNTIME_PROGRAM_VALUES["value_016"])
    self.epoch_runtime.assert_current()
    selected = self.selected_manifests.capture_selected_manifest_for_plugin(
        plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
    )
    matches = tuple(
        binding
        for binding in self.policy.bindings
        if binding.plugin_id == plugin_id
        and binding.source_trust_class == "local-worker-candidate"
        and binding.source_identity
        == selected.snapshot.package_revision.package_source_identity
        and binding.artifact_digest == selected.snapshot.root_ref.artifact_digest
        and binding.worker_admission is not None
    )
    if len(matches) != 1:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_017"])
    admission = matches[0].worker_admission
    assert admission is not None
    candidate = _binding.verify_product_selected_worker_candidate(
        selected,
        contribution_id=admission.contribution_id,
        native_platform=admission.native_platform,
    )
    if candidate.owner_id != admission.owner_id:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_018"])
    self.epoch_runtime.assert_current()
    return _binding.CodingWorkerCandidateReadEvidenceV1(
        candidate=candidate,
        artifact_digest=selected.snapshot.root_ref.artifact_digest,
        native_platform=admission.native_platform,
    )


def require_existing_private_directory(path: _binding.Path) -> None:
    descriptor = _binding.os.open(
        path,
        _binding.os.O_RDONLY
        | _binding.os.O_DIRECTORY
        | _binding.os.O_NOFOLLOW
        | _binding.os.O_CLOEXEC,
    )
    try:
        opened = _binding.os.fstat(descriptor)
        visible = path.lstat()
        if (
            not _binding.stat.S_ISDIR(opened.st_mode)
            or _binding.stat.S_IMODE(opened.st_mode) & 63
            or opened.st_uid != _binding.os.geteuid()
            or ((opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino))
        ):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["private_state_unsafe"])
    finally:
        _binding.os.close(descriptor)
