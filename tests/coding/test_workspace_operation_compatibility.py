from __future__ import annotations


def test_workspace_operation_protocols_preserve_harness_owner_identity() -> None:
    import loushang.harness.tools.workspace as workspace_tools
    from loushang.harness.tools.workspace import operations as workspace_operations
    from loushang.harness.workspace import operations as harness_operations

    protocol_names = (
        "EditOperations",
        "FindOperations",
        "GrepOperations",
        "LsOperations",
        "ReadOperations",
        "WriteOperations",
    )
    for name in protocol_names:
        harness_protocol = getattr(harness_operations, name)
        assert getattr(workspace_operations, name) is harness_protocol
        assert getattr(workspace_tools, name) is harness_protocol
        assert harness_protocol.__module__ == "loushang.harness.workspace.operations"

    assert (
        workspace_operations.ToolOperations
        is workspace_tools.ToolOperations
        is harness_operations.ToolOperations
    )


def test_workspace_local_backend_preserves_harness_owner_identity() -> None:
    import loushang.harness.tools.workspace as workspace_tools
    from loushang.harness.tools.workspace import operations as workspace_operations
    from loushang.harness.workspace import operations as harness_operations

    assert (
        workspace_operations.LocalToolOperations
        is workspace_tools.LocalToolOperations
        is harness_operations.LocalToolOperations
    )
    assert (
        workspace_operations.LOCAL_TOOL_OPERATIONS
        is workspace_tools.LOCAL_TOOL_OPERATIONS
        is harness_operations.LOCAL_TOOL_OPERATIONS
    )
    assert (
        workspace_operations.resolve_operation is harness_operations.resolve_operation
    )
    assert (
        harness_operations.LocalToolOperations.__module__
        == "loushang.harness.workspace.operations"
    )
