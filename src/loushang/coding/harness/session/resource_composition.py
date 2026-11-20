"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.composition import base_product as _binding


def compile_base_selection(
    selected: _binding.PackageProductSelectedPluginManifestV1,
    composition_set: _binding.CodingCompositionSetPlan,
    *,
    installation_key: _binding.PluginInstallationKeyV1,
    session_id: str,
    host_environment: _binding.HostEnvironment,
    evaluated_at: int,
    include_tool_contribution: bool,
    include_tool_claim_prompt: bool,
    include_skill_contribution: bool,
    include_command_contribution: bool,
) -> _binding.CodingBaseProductCompilation:
    """Admit Product-selected declarations without a peer publication handle."""

    plan, tool_id, tool_names = _binding.prepare_coding_base_product_plan(
        selected,
        composition_set,
        installation_key=installation_key,
        session_id=session_id,
        host_environment=host_environment,
        include_tool_contribution=include_tool_contribution,
        include_tool_claim_prompt=include_tool_claim_prompt,
        include_skill_contribution=include_skill_contribution,
        include_command_contribution=include_command_contribution,
    )
    selected_refs = set(plan.selected_contributions)
    pairs = selected.verified_data_only_declarations()
    candidates = tuple(
        _binding._candidate(selected, plan, reservation, declaration)
        for reservation, declaration in pairs
        if _binding.PluginContributionRef(
            _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_003"],
            reservation.contribution_id,
        )
        in selected_refs
    )
    if {
        _binding.PluginContributionRef(item.plugin_id, item.contribution_id)
        for item in candidates
    } != selected_refs:
        raise _binding.CodingBasePluginAssemblyError(
            _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_001"],
            code=_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_002"],
        )
    owners = {item.owner_id for item in candidates}
    owner_bindings = _binding._owner_bindings(
        include_tools="tools.workspace" in owners,
        include_prompt="resources.prompt" in owners,
        include_skill="resources.skill" in owners,
        include_theme="resources.theme" in owners,
        include_command="commands.session" in owners,
    )
    product_composition = _binding._assemble_product_contribution_candidates(
        plan=plan,
        candidates=candidates,
        owner_bindings=owner_bindings,
        mandatory_roots=(_binding.MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
        definitions=(
            _binding.MODEL_INPUT_CAPABILITY_DEFINITION,
            _binding.WORKSPACE_CAPABILITY_DEFINITION,
        ),
        select_optional_requirements=lambda _preview: (),
        evaluated_at=evaluated_at,
    )
    return _binding.CodingBaseProductCompilation(
        plan=plan,
        product_composition=product_composition,
        owner_bindings=owner_bindings,
        host_environment=host_environment,
        selected_manifest=selected,
        tool_contribution_id=tool_id,
        tool_names=tool_names,
        resource_bodies=_binding._resource_bodies(selected, product_composition),
    )


def extend_data_resources(
    base: _binding.CodingBaseProductCompilation,
    external: tuple[_binding.PackageProductSelectedPluginManifestV1, ...],
    *,
    evaluated_at: int,
) -> _binding.CodingBaseProductCompilation:
    """Compile gated external data Resources under one exact owner set."""

    if not external:
        return base
    if base.plan.selected_plugin_ids != (
        _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_003"],
    ):
        raise ValueError(_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_004"])
    if tuple(sorted(item.manifest.name for item in external)) != tuple(
        item.manifest.name for item in external
    ):
        raise ValueError(_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_005"])
    external_owners: set[str] = set()
    for selected in external:
        trust = selected.source_trust_snapshot
        pairs = selected.verified_data_only_declarations()
        if trust is None or _external_selection_rejected(trust, pairs):
            raise ValueError(_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_006"])
        external_owners.add(pairs[0][0].owner)
    original = base.plan
    plan = _binding.PluginSelectionPlanV2(
        context=_binding.PluginPreflightContextV1(
            product_id=original.context.product_id,
            scope_id=original.context.scope_id,
            policy_revision=original.context.policy_revision,
            instance_revision_refs=tuple(
                sorted(
                    (
                        *original.context.instance_revision_refs,
                        *(item.snapshot.instance_revision_ref for item in external),
                    ),
                    key=lambda item: item.plugin_id,
                )
            ),
        ),
        selected_plugin_ids=tuple(
            sorted(
                (
                    _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_003"],
                    *(item.manifest.name for item in external),
                )
            )
        ),
        selected_contributions=tuple(
            sorted(
                (
                    *original.selected_contributions,
                    *(
                        _binding.PluginContributionRef(
                            item.manifest.name, reservation.contribution_id
                        )
                        for item in external
                        for reservation, _ in item.verified_data_only_declarations()
                    ),
                )
            )
        ),
        source_trust_snapshots=tuple(
            sorted(
                (
                    *original.source_trust_snapshots,
                    *(
                        item.source_trust_snapshot
                        for item in external
                        if item.source_trust_snapshot is not None
                    ),
                ),
                key=lambda item: item.plugin_id,
            )
        ),
        effective_configuration_set=_binding.PluginEffectiveConfigurationSetV1(
            entries=tuple(
                sorted(
                    (
                        *original.effective_configuration_set.entries,
                        *(
                            _binding.PluginEffectiveConfigurationEntry(
                                plugin_id=item.manifest.name,
                                contribution_id=reservation.contribution_id,
                                configuration=reservation.configuration,
                            )
                            for item in external
                            for reservation, _ in item.verified_data_only_declarations()
                        ),
                    ),
                    key=lambda item: (item.plugin_id, item.contribution_id),
                )
            )
        ),
        allowed_authority_ceiling=original.allowed_authority_ceiling,
    )
    candidates = tuple(
        _binding._candidate(selected, plan, reservation, declaration)
        for selected in (base.selected_manifest, *external)
        for reservation, declaration in selected.verified_data_only_declarations()
        if _binding.PluginContributionRef(
            selected.manifest.name, reservation.contribution_id
        )
        in plan.selected_contributions
    )
    bindings = list(base.owner_bindings)
    missing_owners = external_owners - {item.owner_key[0] for item in bindings}
    if missing_owners:
        bindings.extend(
            _binding._owner_bindings(
                include_tools=False,
                include_prompt="resources.prompt" in missing_owners,
                include_skill="resources.skill" in missing_owners,
                include_theme="resources.theme" in missing_owners,
                include_command=False,
            )
        )
    owners = tuple(
        sorted(
            (
                _binding.ProductContributionOwnerBinding(
                    authority=_binding.OwnerContributionAuthority(
                        _binding.replace(
                            binding.authority.policy,
                            allowed_source_trust_classes=(
                                (
                                    "host-equivalent-local",
                                    *_binding.EXTERNAL_DATA_TRUST_CLASSES_ORDERED,
                                )
                                if any(
                                    item.plugin_id
                                    == _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES[
                                        "value_003"
                                    ]
                                    and item.owner_id == binding.owner_key[0]
                                    for item in candidates
                                )
                                else (*_binding.EXTERNAL_DATA_TRUST_CLASSES_ORDERED,)
                            ),
                        )
                    ),
                    admission_ttl_seconds=binding.admission_ttl_seconds,
                )
                if binding.owner_key[0] in external_owners
                else binding
                for binding in bindings
            ),
            key=lambda binding: binding.owner_key,
        )
    )
    composition = _binding._assemble_product_contribution_candidates(
        plan=plan,
        candidates=candidates,
        owner_bindings=owners,
        mandatory_roots=(_binding.MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
        definitions=(
            _binding.MODEL_INPUT_CAPABILITY_DEFINITION,
            _binding.WORKSPACE_CAPABILITY_DEFINITION,
        ),
        select_optional_requirements=lambda _preview: (),
        evaluated_at=evaluated_at,
    )
    return _binding.replace(
        base,
        plan=plan,
        product_composition=composition,
        owner_bindings=owners,
        resource_bodies=_binding._resource_bodies(
            base.selected_manifest, composition, external_selected=external
        ),
        selected_external_data_manifests=external,
    )


def capture_resource_bodies(
    selected: _binding.PackageProductSelectedPluginManifestV1 | None,
    compilation: _binding.ProductCompositionCompilation,
    *,
    external_selected: tuple[_binding.PackageProductSelectedPluginManifestV1, ...],
) -> tuple[_binding.CodingBaseProductResourceBody, ...]:
    by_id = {
        item.manifest.name: item
        for item in ((selected,) if selected is not None else ()) + external_selected
    }
    bodies: list[_binding.CodingBaseProductResourceBody] = []
    for admission in compilation.resource_admissions:
        candidate = admission.candidate
        resource = candidate.contribution
        selected_root = by_id[admission.plugin_id]
        snapshot = selected_root.snapshot
        members = dict(snapshot.files)
        root = selected_root.manifest.root_relative_path.as_posix()
        if (
            not isinstance(resource, _binding.ResourceContributionSpec)
            or candidate.package_content_digest
            != snapshot.package_revision.package_content_digest
            or candidate.instance_revision_ref != snapshot.instance_revision_ref
        ):
            raise _binding.CodingBasePluginAssemblyError(
                _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_007"],
                code=_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_009"],
            )
        locator = resource.locator
        if resource.locator_kind == "directory":
            if resource.resource_kind != "skill":
                raise _binding.CodingBasePluginAssemblyError(
                    _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_010"],
                    code=_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_011"],
                )
            locator = f"{locator}/SKILL.md"
        captured_path = locator if root == "." else f"{root}/{locator}"
        body = members.get(captured_path)
        if body is None:
            raise _binding.CodingBasePluginAssemblyError(
                _binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_008"],
                code=_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_011"],
            )
        bodies.append(
            _binding.CodingBaseProductResourceBody(
                admission_fingerprint=admission.fingerprint,
                contribution_id=candidate.contribution_id,
                logical_path=locator,
                content_digest=_binding.sha256(body).hexdigest(),
                body=body,
            )
        )
    return tuple(bodies)


def base_resource_inputs(
    self: _binding.CodingBaseProductCompilation,
) -> tuple[_binding.ProductSelectedResourceInput, ...]:
    """Pair captured bytes with their exact Product owner admissions."""

    by_fingerprint = {item.admission_fingerprint: item for item in self.resource_bodies}
    selected_by_id = {
        item.manifest.name: item
        for item in (
            self.selected_manifest,
            *self.selected_external_data_manifests,
        )
    }
    return tuple(
        _binding.ProductSelectedResourceInput(
            admission=admission,
            selected_manifest=selected_by_id[admission.plugin_id],
            relative_path=by_fingerprint[admission.fingerprint].logical_path,
        )
        for admission in self.product_composition.resource_admissions
    )


def _external_selection_rejected(
    trust: _binding.PluginSourceTrustSnapshotV1,
    declarations: tuple[
        tuple[_binding.PluginContributionReservation, _binding.PluginDeclaration], ...
    ],
) -> bool:
    """Apply the same admission constraints after each path classifies trust."""
    return (
        not trust.trusted
        or trust.source_trust_class not in _binding.EXTERNAL_DATA_TRUST_CLASSES
        or len(declarations) != 1
        or not _binding.permits_external_data_owner(
            trust.source_trust_class, declarations[0][0].owner
        )
        or declarations[0][0].kind != "resource_item"
        or declarations[0][0].owner not in _binding._EXTERNAL_RESOURCE_OWNERS
    )
