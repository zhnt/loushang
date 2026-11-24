"""Coding LSP policy for an independently activated Session capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from loushang.coding.composition.capability_plugins import (
    CodingCapabilityPluginCompositionAssembly,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.lsp._plugin_tool_owner import CodingLspToolOwner
from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CODING_LSP_SESSION_REQUIREMENT,
    CODING_LSP_TOOL_RUNTIME_REQUIREMENT,
    CodingLspSessionCapabilityConsumer,
)
from loushang.coding.lsp.runtime import CodingLspSessionAccess
from loushang.coding.lsp.tools import (
    create_document_outline_tool_definition,
    create_inspect_symbol_tool_definition,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.session.tool_owner_binding import (
    _DeferredSessionCapabilityGeneration,
)
from loushang.harness.tools.core import project_tool_definition


def dormant_lsp_tool_infos() -> list[dict[str, object]]:
    """Product-owned discovery metadata without creating a Provider or Tool lease."""

    runtime = _DormantLspToolRuntime()
    return [
        {
            **project_tool_definition(definition),
            "sourceInfo": {
                "path": f"<coding.lsp.default:{definition.name}>",
                "source": "plugin",
                "scope": "project",
                "origin": "top-level",
                "baseDir": None,
            },
        }
        for definition in (
            create_document_outline_tool_definition(runtime),
            create_inspect_symbol_tool_definition(runtime),
        )
    ]


class _DormantLspToolRuntime:
    async def inspect_symbol(self, **_kwargs: object) -> Never:
        raise RuntimeError("activate the LSP tools before calling them")

    async def document_outline(self, **_kwargs: object) -> Never:
        raise RuntimeError("activate the LSP tools before calling them")


@dataclass(slots=True)
class CodingDeferredLspGeneration(
    _DeferredSessionCapabilityGeneration[
        CodingCapabilityPluginCompositionAssembly, CodingLspSessionAccess
    ]
):
    _product_id = CODING_PRODUCT_ID
    _plugin_id = "coding.lsp.default"
    _label = "LSP"
    _runtime_claim_prefix = "coding-session-runtime"
    _child_runtime_prefix = "coding-lsp"
    _capability = CODING_LSP_CAPABILITY_DEFINITION
    _tool_requirement = CODING_LSP_TOOL_RUNTIME_REQUIREMENT
    _session_requirement = CODING_LSP_SESSION_REQUIREMENT
    _tool_owner_type = CodingLspToolOwner

    def _access_from(self, capture: CapabilityFacetSet) -> CodingLspSessionAccess:
        return CodingLspSessionCapabilityConsumer(capture).access
