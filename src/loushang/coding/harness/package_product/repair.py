"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import product_repair as _binding


async def perform_repair(
    client: _binding.CodingPackageRepairClientV1,
    action: _binding.CodingPackageRepairActionV1,
    operation_id: str,
    *,
    owner_factory: _binding._OwnerFactory,
) -> _binding.CodingPackageRepairResultV1:
    if not isinstance(client, _binding.CodingPackageRepairClientV1):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_001"])
    if action not in _binding._ACTIONS:
        raise _binding.CodingPackageRepairError(
            _binding._RUNTIME_PROGRAM_VALUES["value_002"]
        )
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or operation_id != operation_id.strip()
    ):
        raise _binding.CodingPackageRepairError(
            _binding._RUNTIME_PROGRAM_VALUES["value_003"]
        )
    _binding._require_workspace_identity(client)
    owner = owner_factory(
        client.layout,
        workspace=client.workspace,
        runtime_version=client.runtime_version,
        runtime_protocol_epoch=_binding.CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        _binding._require_workspace_identity(client)
        product = owner.runtime_owner.product_owner
        session_id = f"package-repair:{_binding.uuid4().hex}"
        runtime = product.factory_for_session(
            session_id=session_id,
            cwd=client.workspace,
            runtime_id=session_id,
        ).create(
            _binding.PackageProductRuntimeRequestV1(
                product_id=_binding._RUNTIME_PROGRAM_VALUES["value_004"],
                session_id=session_id,
                cwd=str(client.workspace),
            )
        )
        return await _binding._perform_package_repair(
            runtime,
            action,
            operation_id,
            max_bytes=_binding._MAX_SOURCE_BYTES,
            result_factory=lambda **fields: _binding.CodingPackageRepairResultV1(
                **fields
            ),
        )
    finally:
        owner.close()
