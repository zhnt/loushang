"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import lifecycle as _binding


def normalize_owner_contributions(
    values: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(values, tuple):
        raise TypeError(_binding._MEMBERSHIP_PROGRAM_VALUES["value_001"])
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for owner_reference, contribution_ids in values:
        owner = _binding._nonempty(owner_reference, name="Owner reference")
        if (
            not isinstance(contribution_ids, tuple)
            or not contribution_ids
            or any(
                not isinstance(item, str) or not item or item.strip() != item
                for item in contribution_ids
            )
        ):
            raise ValueError(_binding._MEMBERSHIP_PROGRAM_VALUES["value_003"])
        canonical_ids = tuple(sorted(set(contribution_ids)))
        normalized.append((owner, canonical_ids))
    canonical = tuple(sorted(normalized))
    if len({owner for owner, _items in canonical}) != len(canonical):
        raise ValueError(_binding._MEMBERSHIP_PROGRAM_VALUES["value_002"])
    return canonical


def encode_holder_reference(
    *,
    session_id: str,
    lease_attempt_id: str,
    owner_contributions: tuple[tuple[str, tuple[str, ...]], ...],
    startup_id: str,
) -> str:
    payload = {
        "leaseAttemptId": _binding._nonempty(lease_attempt_id, name="Lease attempt id"),
        "owners": [
            {
                "contributionIds": list(contribution_ids),
                "ownerReference": owner_reference,
            }
            for owner_reference, contribution_ids in owner_contributions
        ],
        "sessionId": _binding._nonempty(session_id, name="Session id"),
        "startupId": _binding._nonempty(startup_id, name="Startup id"),
    }
    return _binding._SESSION_HOLDER_PREFIX + _binding.json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_holder_evidence(
    holder_reference: str,
) -> _binding._CodingSessionHolderEvidence | None:
    if not holder_reference.startswith(_binding._SESSION_HOLDER_PREFIX):
        # V1 and foreign holder references contain no process epoch.  Preserve
        # them fail-closed because inactivity cannot be proven.
        return None
    try:
        payload = _binding.json.loads(
            holder_reference[len(_binding._SESSION_HOLDER_PREFIX) :]
        )
        if not isinstance(payload, dict) or set(payload) != {
            "leaseAttemptId",
            "owners",
            "sessionId",
            "startupId",
        }:
            raise ValueError(_binding._MEMBERSHIP_PROGRAM_VALUES["value_004"])
        _binding._nonempty(payload["leaseAttemptId"], name="Lease attempt id")
        _binding._nonempty(payload["sessionId"], name="Session id")
        startup_id = _binding._nonempty(payload["startupId"], name="Startup id")
        owners = payload["owners"]
        if not isinstance(owners, list):
            raise ValueError(_binding._MEMBERSHIP_PROGRAM_VALUES["value_005"])
        values = tuple(
            (
                item["ownerReference"],
                tuple(item["contributionIds"]),
            )
            for item in owners
            if isinstance(item, dict)
            and set(item) == {"contributionIds", "ownerReference"}
            and isinstance(item["contributionIds"], list)
        )
        if len(values) != len(owners):
            raise ValueError(_binding._MEMBERSHIP_PROGRAM_VALUES["value_006"])
        return _binding._CodingSessionHolderEvidence(
            startup_id=startup_id,
            owner_contributions=_binding._normalize_owner_contributions(values),
        )
    except (TypeError, ValueError, _binding.json.JSONDecodeError) as exc:
        raise _binding.CodingPluginLifecycleError(
            _binding._MEMBERSHIP_PROGRAM_VALUES["value_007"],
            code=_binding._MEMBERSHIP_PROGRAM_VALUES["value_008"],
        ) from exc


def project_enablement_compatibility(
    layout: _binding.CodingPluginLifecycleStateLayout,
    *,
    _capture: _binding._CodingPluginEnablementStateCapture | None,
) -> tuple[_binding.PluginEnablementCompatibilityProjectionV1, frozenset[str]]:
    """Read Coding's derived downgrade view without exposing owner stores."""

    if not isinstance(layout, _binding.CodingPluginLifecycleStateLayout):
        raise TypeError(_binding._MEMBERSHIP_PROGRAM_VALUES["value_009"])
    if _capture is None:
        with _binding._capture_existing_plugin_enablement_state(layout) as captured:
            if captured is None:
                return _binding._empty_plugin_enablement_compatibility_projection()
            return _binding.project_coding_plugin_enablement_compatibility(
                layout,
                _capture=captured,
            )
    desired = _binding.decode_plugin_desired_state_snapshot(
        _capture.desired_raw,
        path=layout.desired_state,
        gc_gate=_binding.PluginPackageGcReservationJournal(
            layout.package_gc_reservations
        ),
    )
    migrations = tuple(
        item
        for item in _binding.decode_plugin_enablement_migration_snapshots(
            _capture.migration_raw,
            path=layout.enablement_migration,
        )
        if item.request.installation_key.product_id == _binding.CODING_PRODUCT_ID
        and item.request.installation_key.installation_scope
        == _binding._MEMBERSHIP_PROGRAM_VALUES["installation_scope"]
        and item.request.installation_key.scope_id == layout.scope_id
        and item.phase in {"compatibility_window", "finalized"}
    )
    migrated = frozenset(item.request.installation_key.plugin_id for item in migrations)
    disabled = tuple(
        sorted(
            item.request.installation_key.plugin_id
            for item in migrations
            if desired.installation(
                item.request.installation_key
            ).selection.desired_state
            != "installed_enabled"
        )
    )
    projection = _binding.PluginEnablementCompatibilityProjectionV1(
        desired_inventory_revision=desired.inventory_revision,
        migration_journal_revision=max(
            (item.journal_revision for item in migrations),
            default=0,
        ),
        disabled_plugin_ids=disabled,
    )
    return projection, migrated
