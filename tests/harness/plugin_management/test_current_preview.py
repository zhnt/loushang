from __future__ import annotations

import pytest

from loushang.harness.cli.plugin_preview import format_plugin_current_preview
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentPreviewRequestV1,
)


def test_cli_preview_refuses_untyped_product_document() -> None:
    request = PluginCurrentPreviewRequestV1(
        correlation_id="test:preview", product_id="coding",
        scope_id="workspace:test", composition_set_id="coding-standard",
    )

    class ForgedQuery:
        def preview_current(self, _request: object) -> object:
            class ForgedResult:
                product_id = "coding"
                scope_id = "workspace:test"
                composition_set_id = "coding-standard"

                def to_dict(self) -> dict[str, object]:
                    return {"sourcePath": "/private/secret"}

            return ForgedResult()

    with pytest.raises(TypeError, match="typed Product result"):
        format_plugin_current_preview(ForgedQuery(), request)  # type: ignore[arg-type]


def test_partial_preview_cannot_claim_projected_and_blocked_together() -> None:
    with pytest.raises(ValueError, match="cannot claim a blocker"):
        PluginCurrentCompositionPreviewV1(
            product_id="coding", scope_id="workspace:test",
            composition_set_id="coding-standard", observed_at_unix_ns=1,
            desired_inventory_revision=1, product_policy_revision="policy:1",
            product_authority_revision="authority:1", compiled_plugin_ids=(),
            admitted_resources=(), catalog_resources=(), catalog_diagnostic_codes=(),
            requires_authorized_preflight=(), evidence_gaps=(),
            blocking_owner="product_composition", blocking_code="blocked",
        )
