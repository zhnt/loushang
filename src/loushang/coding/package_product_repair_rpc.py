"""Coding-only RPC binding for exact fenced Product Package repair."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .package_product_repair import (
    CodingPackageRepairActionV1,
    CodingPackageRepairClientV1,
    CodingPackageRepairResultV1,
    open_coding_package_repair_client,
)
from .product_plan import CODING_PRODUCT_ID


@dataclass(frozen=True, slots=True)
class CodingPackageRepairRpcClientV1:
    local: CodingPackageRepairClientV1

    @property
    def product_id(self) -> str:
        return CODING_PRODUCT_ID

    @property
    def scope_id(self) -> str:
        return self.local.layout.scope_id

    async def perform(
        self, action: str, operation_id: str
    ) -> CodingPackageRepairResultV1:
        return await self.local.aperform(
            cast(CodingPackageRepairActionV1, action), operation_id
        )


def bind_coding_package_repair_rpc_client(
    cwd: str | Path,
) -> CodingPackageRepairRpcClientV1:
    return CodingPackageRepairRpcClientV1(
        local=open_coding_package_repair_client(cwd)
    )


__all__ = [
    "CodingPackageRepairRpcClientV1",
    "bind_coding_package_repair_rpc_client",
]
