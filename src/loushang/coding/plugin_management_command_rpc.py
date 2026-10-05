"""Coding Product command binding for the optional JSONL management RPC route."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.plugin_management.application import (
    PluginManagementApplicationResultV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandAuthorityV1,
    PluginDesiredCommandRequestV1,
    PluginDesiredRepairResultV1,
    resume_plugin_desired_operation,
    submit_plugin_desired_command,
)

from .plugin_management_command_sdk import (
    CodingPluginManagementCommandClientV1,
    open_coding_plugin_management_command_client,
)
from .product_plan import CODING_PRODUCT_ID


@dataclass(frozen=True, slots=True)
class CodingPluginDesiredRpcClientV1:
    """Share the Product owner route while recording RPC as the caller."""

    local: CodingPluginManagementCommandClientV1

    @property
    def product_id(self) -> str:
        return CODING_PRODUCT_ID

    @property
    def installation_scope(self) -> Literal["workspace"]:
        return "workspace"

    @property
    def scope_id(self) -> str:
        return self.local.layout.scope_id

    def submit_desired(
        self, request: PluginDesiredCommandRequestV1
    ) -> PluginManagementApplicationResultV1:
        return submit_plugin_desired_command(
            self.local._ports(),
            self._authority(),
            request,
        )

    def repair(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginDesiredRepairResultV1:
        return resume_plugin_desired_operation(
            self.local._ports(),
            self._authority(),
            operation_id=operation_id,
            correlation_id=correlation_id,
        )

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None:
        return self.local._ports().commands.operation(
            operation_id, correlation_id=correlation_id
        )

    def _authority(self) -> PluginDesiredCommandAuthorityV1:
        return PluginDesiredCommandAuthorityV1(
            product_id=CODING_PRODUCT_ID,
            installation_scope="workspace",
            scope_id=self.scope_id,
            actor_id="coding:rpc",
            policy_revision="coding-plugin-management-rpc-v1",
        )


def bind_coding_plugin_desired_rpc_client(
    cwd: str | Path,
) -> CodingPluginDesiredRpcClientV1:
    return CodingPluginDesiredRpcClientV1(
        local=open_coding_plugin_management_command_client(cwd)
    )


__all__ = [
    "CodingPluginDesiredRpcClientV1",
    "bind_coding_plugin_desired_rpc_client",
]
