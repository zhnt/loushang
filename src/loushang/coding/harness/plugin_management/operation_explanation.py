"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import explanation as _binding


def explain_operation(
    self: _binding.CodingPluginOperationExplanationQuery,
    request: _binding.PluginOperationExplanationRequestV1,
) -> _binding.PluginOperationExplanationV1:
    if self.workspace_guard is not None:
        self.workspace_guard()
    if not isinstance(request, _binding.PluginOperationExplanationRequestV1):
        raise TypeError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_001"])
    if (
        request.product_id != _binding.CODING_PRODUCT_ID
        or request.scope_id != self.layout.scope_id
    ):
        raise _binding.CodingPluginOperationExplanationError(
            code=_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_002"]
        )
    if _binding.os.name != "posix":
        raise _binding.CodingPluginOperationExplanationError(
            code=_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_003"]
        )
    if not _binding.coding_fenced_product_exists(self.layout):
        raise _binding.CodingPluginOperationExplanationError(
            code=_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_004"]
        )
    explanation = _binding.explain_coding_fenced_plugin_operation(
        self.layout,
        request.operation_id,
        correlation_id=request.correlation_id,
        workspace_guard=self.workspace_guard,
    )
    if (
        explanation.package.status == "observed"
        and explanation.package.disposition == "committed"
        and explanation.handoff_evidence == "incomplete"
        and explanation.join_status == "same_identity"
    ):
        handoff = _binding.read_coding_fenced_package_handoff(
            self.layout, request.operation_id
        )
        if (
            handoff is not None
            and handoff.receipt_id == explanation.handoff_receipt_id
            and handoff.request.desired_request.operation_id == request.operation_id
            and handoff.request.desired_request.command_id
            == explanation.management_operation_id
            and handoff.request.desired_request.request_fingerprint
            == explanation.package.request_fingerprint
        ):
            commit = _binding.read_coding_fenced_handoff_desired_commit(
                self.layout, handoff
            )
            if commit is not None:
                explanation = _binding.replace(
                    explanation, desired_commit_evidence=commit[2]
                )
    if self.workspace_guard is not None:
        self.workspace_guard()
    guidance = _binding.project_coding_plugin_operation_guidance(explanation.to_dict())
    repair = guidance["repairCommand"]
    assert repair is None or isinstance(repair, str)
    return _binding.replace(explanation, repair_command=repair)
