"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.composition import external_data as _binding
from loushang.coding.harness.session import resource_composition


def compile_data_selection(
    selected: tuple[_binding.PackageProductSelectedPluginManifestV1, ...],
    *,
    composition_set: _binding.CodingCompositionSetPlan,
    session_id: str,
    evaluated_at: int,
) -> _binding.CodingExternalDataProductCompilation:
    """Admit exact Product Store data roots without a base Plugin dependency."""

    if not selected or tuple(sorted(item.manifest.name for item in selected)) != tuple(
        item.manifest.name for item in selected
    ):
        raise ValueError("Product external data selections must be sorted and nonempty")
    if len({item.manifest.name for item in selected}) != len(selected):
        raise ValueError("Product external data Plugin identity is duplicated")
    if not isinstance(composition_set, _binding.CodingCompositionSetPlan):
        raise TypeError(_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_004"])
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_005"])
    if type(evaluated_at) is not int or evaluated_at < 0:
        raise ValueError(_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_006"])
    owners: set[str] = set()
    trusts: list[_binding.PluginSourceTrustSnapshotV1] = []
    pairs: list[
        tuple[
            _binding.PackageProductSelectedPluginManifestV1,
            _binding.PluginContributionReservation,
            _binding.PluginDeclaration,
        ]
    ] = []
    for item in selected:
        trust = item.source_trust_snapshot
        declarations = item.verified_data_only_declarations()
        if (
            not isinstance(trust, _binding.PluginSourceTrustSnapshotV1)
            or resource_composition._external_selection_rejected(trust, declarations)
            or item.snapshot.installation_key.plugin_id != item.manifest.name
            or item.snapshot.instance_revision_ref.plugin_id != item.manifest.name
        ):
            raise ValueError("Product external data Resource selection changed")
        owners.add(declarations[0][0].owner)
        trusts.append(trust)
        pairs.extend(
            (item, reservation, declaration)
            for reservation, declaration in declarations
        )
    policy_digest = _binding.sha256(
        _binding.canonical_json_bytes(
            [
                {
                    "pluginId": item.manifest.name,
                    "committedSetId": item.snapshot.committed_record.committed_set.set_id,
                    "instanceRevision": item.snapshot.instance_revision_ref.to_dict(),
                }
                for item in selected
            ]
        )
    ).hexdigest()
    plan = _binding.PluginSelectionPlanV2(
        context=_binding.PluginPreflightContextV1(
            product_id=_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES["value_008"],
            scope_id=f"session:{session_id.strip()}",
            policy_revision=(
                f"{_binding._RESOURCE_COMPOSITION_PROGRAM_VALUES['value_001']}{composition_set.set_id}:{composition_set.fingerprint}:{policy_digest}"
            ),
            instance_revision_refs=tuple(
                item.snapshot.instance_revision_ref for item in selected
            ),
        ),
        selected_plugin_ids=tuple(item.manifest.name for item in selected),
        selected_contributions=tuple(
            sorted(
                _binding.PluginContributionRef(
                    item.manifest.name, reservation.contribution_id
                )
                for item, reservation, _ in pairs
            )
        ),
        source_trust_snapshots=tuple(trusts),
        effective_configuration_set=_binding.PluginEffectiveConfigurationSetV1(
            entries=tuple(
                sorted(
                    (
                        _binding.PluginEffectiveConfigurationEntry(
                            plugin_id=item.manifest.name,
                            contribution_id=reservation.contribution_id,
                            configuration=reservation.configuration,
                        )
                        for item, reservation, _ in pairs
                    ),
                    key=lambda entry: (entry.plugin_id, entry.contribution_id),
                )
            )
        ),
        allowed_authority_ceiling=(),
    )
    candidates = tuple(
        _binding._candidate(item, plan, reservation, declaration)
        for item, reservation, declaration in pairs
    )
    owner_bindings = tuple(
        _binding.ProductContributionOwnerBinding(
            authority=_binding.OwnerContributionAuthority(
                _binding.replace(
                    binding.authority.policy,
                    allowed_source_trust_classes=(
                        *_binding.EXTERNAL_DATA_TRUST_CLASSES_ORDERED,
                    ),
                )
            ),
            admission_ttl_seconds=binding.admission_ttl_seconds,
        )
        for binding in _binding._owner_bindings(
            include_tools=False,
            include_prompt="resources.prompt" in owners,
            include_skill="resources.skill" in owners,
            include_theme="resources.theme" in owners,
            include_command=False,
        )
    )
    composition = _binding._assemble_product_contribution_candidates(
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
    return _binding.CodingExternalDataProductCompilation(
        product_composition=composition,
        selected_manifests=selected,
        resource_bodies=_binding._resource_bodies(
            None, composition, external_selected=selected
        ),
    )


def external_resource_inputs(
    self: _binding.CodingExternalDataProductCompilation,
) -> tuple[_binding.ProductSelectedResourceInput, ...]:
    by_id = {item.manifest.name: item for item in self.selected_manifests}
    bodies = {item.admission_fingerprint: item for item in self.resource_bodies}
    if len(bodies) != len(self.resource_bodies):
        raise ValueError("Product data Resource body identity is duplicated")
    return tuple(
        _binding.ProductSelectedResourceInput(
            admission=admission,
            selected_manifest=by_id[admission.plugin_id],
            relative_path=bodies[admission.fingerprint].logical_path,
        )
        for admission in self.product_composition.resource_admissions
    )
