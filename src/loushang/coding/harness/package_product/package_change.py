"""Route Product package changes through their existing runtime owner."""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import product_cli as _binding


def change_packages(
    layout: _binding.CodingPluginLifecycleStateLayout,
    *,
    action: Literal["install", "update"],
    workspace: _binding.Path,
    sources: _binding.Sequence[str],
    stdout: _binding.TextIO,
    stderr: _binding.TextIO,
) -> int:

    current_operation_id: str | None = None
    try:
        controlled = tuple(
            _binding.admit_coding_external_data_wheel(layout, source=_binding.Path(raw))
            for raw in sources
        )
        owner = _binding.open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version=_binding.version(_binding._PACKAGE_DISTRIBUTION),
            runtime_protocol_epoch=_binding.CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            for record in controlled:
                operation_id = f"{_binding._PACKAGE_OPERATION_PREFIX}{action}:{_binding.secrets.token_hex(16)}"
                current_operation_id = operation_id
                runtime_id = f"{_binding._PACKAGE_RUNTIME_PREFIX}{_binding.secrets.token_hex(16)}"
                with _binding._product_plugin_runtime(
                    product,
                    product_id=_binding.CODING_PRODUCT_ID,
                    session_id=runtime_id,
                ) as runtime:
                    outcome = runtime.lifecycle.route(
                        _binding.PackageProductLifecycleIntentV1(
                            operation_id=operation_id,
                            action=action,
                            source=str(
                                owner.epoch_runtime.control_root
                                / _binding._PACKAGE_SOURCE_DIRECTORY
                                / record.wheel_filename
                            ),
                            scope=_binding._PACKAGE_SCOPE,
                        ),
                        entrypoint=_binding._PACKAGE_ENTRYPOINT,
                    )
                if not outcome.handled or outcome.record is None:
                    raise RuntimeError(f"Package Product {action} was not handled")
                if outcome.record.lifecycle == "failed":
                    _binding._write_package_failure(
                        layout,
                        workspace=workspace,
                        operation_id=operation_id,
                        error_code=outcome.record.failure_code
                        or "package_operation_failed",
                        stderr=stderr,
                    )
                    return 1
                _binding._write_package_success(stdout, action, record, outcome.record)
            return 0
        finally:
            owner.close()
    except (OSError, RuntimeError, ValueError) as error:
        if current_operation_id is None:
            _binding._write_cli_error(stderr, error)
        else:
            code = getattr(error, "code", None)
            _binding._write_package_failure(
                layout,
                workspace=workspace,
                operation_id=current_operation_id,
                error_code=(
                    code
                    if isinstance(code, str)
                    and _binding.re.fullmatch(r"[a-z][a-z0-9_]{1,127}", code)
                    else "package_operation_incomplete"
                ),
                stderr=stderr,
            )
        return 1


def observe_failed_change(
    layout: _binding.CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> tuple[str, dict[str, object] | None, int | None, str | None, str, str]:
    """Observe recorded progress without retrying or inferring a rollback."""
    stage = "unknown"
    committed_revision: dict[str, object] | None = None
    desired_inventory_revision: int | None = None
    handoff_receipt_id: str | None = None
    try:
        handoff = _binding.read_coding_fenced_package_handoff(layout, operation_id)
        if handoff is not None:
            stage = handoff.state
            handoff_receipt_id = handoff.receipt_id
            desired_commit = _binding.read_coding_fenced_handoff_desired_commit(
                layout, handoff
            )
            if desired_commit is not None:
                desired_inventory_revision, committed_revision, _source = desired_commit
                if handoff.state == "dependency_pinned":
                    stage = "desired_committed"
    except (OSError, RuntimeError, ValueError):
        pass
    try:
        explanation = _binding.explain_coding_fenced_plugin_operation(
            layout,
            operation_id,
            correlation_id=f"cli:failed-package:{operation_id}",
        )
        handoff_evidence: str = explanation.handoff_evidence
        join_status: str = explanation.join_status
    except (OSError, RuntimeError, ValueError):
        handoff_evidence = "not_checked"
        join_status = "not_checked"
    return (
        stage,
        committed_revision,
        desired_inventory_revision,
        handoff_receipt_id,
        handoff_evidence,
        join_status,
    )
