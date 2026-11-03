from __future__ import annotations

import json
from io import StringIO

from loushang.harness.host.rpc.commands.plugin_preview import (
    RpcPluginPreviewCommands,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentPreviewRequestV1,
)


def _result(request: PluginCurrentPreviewRequestV1) -> PluginCurrentCompositionPreviewV1:
    return PluginCurrentCompositionPreviewV1(
        product_id=request.product_id,
        scope_id=request.scope_id,
        composition_set_id=request.composition_set_id,
        observed_at_unix_ns=7,
        desired_inventory_revision=2,
        product_policy_revision="policy:1",
        product_authority_revision="authority:1",
        compiled_plugin_ids=("coding.base",),
        admitted_resources=(),
        catalog_resources=(("skill", "review", "external_package"),),
        catalog_diagnostic_codes=(),
        requires_authorized_preflight=(),
        evidence_gaps=("exact_catalog_generation",),
    )


def test_rpc_preview_projects_exact_typed_result_for_current_workspace() -> None:
    stdout = StringIO()
    observed: list[tuple[str, PluginCurrentPreviewRequestV1]] = []

    class Query:
        def preview_current(
            self, request: PluginCurrentPreviewRequestV1
        ) -> PluginCurrentCompositionPreviewV1:
            observed.append(("/workspace", request))
            return _result(request)

    commands = RpcPluginPreviewCommands(
        get_cwd=lambda: "/workspace",
        bind_query=lambda _cwd: Query(),
        output=RpcOutput(stdout),
    )
    assert [name for name, _handler in commands.bindings()] == [
        "preview_current_plugins"
    ]
    commands.preview_current_plugins("rpc-1", {
        "productId": "coding", "scopeId": "workspace:test",
        "compositionSetId": "coding-standard",
    })

    [response] = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert response["success"] is True
    assert response["id"] == "rpc-1"
    assert response["data"]["correlationId"] == "rpc-1"
    assert response["data"]["snapshotStatus"] == "partial_evidence"
    assert response["data"]["catalogResources"] == [
        {"resourceKind": "skill", "name": "review", "sourceKind": "external_package"}
    ]
    assert observed[0][1].scope_id == "workspace:test"


def test_rpc_preview_rejects_bad_request_and_redacts_owner_failure() -> None:
    stdout = StringIO()

    class UnsafeQuery:
        def preview_current(self, _request: PluginCurrentPreviewRequestV1) -> None:
            raise OSError("/private/owner/secret")

    commands = RpcPluginPreviewCommands(
        get_cwd=lambda: "/workspace",
        bind_query=lambda _cwd: UnsafeQuery(),  # type: ignore[arg-type]
        output=RpcOutput(stdout),
    )
    commands.preview_current_plugins("rpc-1", {"productId": "coding"})
    commands.preview_current_plugins("rpc-2", {
        "productId": "coding", "scopeId": "workspace:test",
        "compositionSetId": "coding-standard",
    })
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [item["errorCode"] for item in responses] == [
        "invalid_request", "plugin_preview_unavailable"
    ]
    assert "/private" not in stdout.getvalue()
