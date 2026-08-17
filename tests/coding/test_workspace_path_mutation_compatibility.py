from __future__ import annotations


def test_workspace_path_helpers_preserve_configured_input_policy(
    tmp_path, monkeypatch
) -> None:
    from loushang.harness.tools.workspace.path_utils import (
        canonicalize_tool_path,
        expand_path,
        resolve_tool_path,
    )
    from loushang.harness.workspace.paths import canonicalize_workspace_path

    monkeypatch.setenv("HOME", str(tmp_path))

    assert expand_path("@file\u00a0name.txt") == "file name.txt"
    assert (
        resolve_tool_path("~/notes.txt", cwd="/ignored")
        == (tmp_path / "notes.txt").resolve()
    )
    assert canonicalize_tool_path(tmp_path / "todo.txt") == str(
        canonicalize_workspace_path(tmp_path / "todo.txt")
    )


def test_workspace_mutation_queue_preserves_owner_identity() -> None:
    import loushang.harness.workspace.mutation_queue as workspace_queue
    from loushang.harness.workspace import mutation_queue as harness_queue

    assert (
        workspace_queue.with_file_mutation_queue
        is harness_queue.with_file_mutation_queue
    )
    assert (
        workspace_queue.run_with_file_mutation_queue
        is harness_queue.run_with_file_mutation_queue
    )
    assert workspace_queue._mutation_locks is harness_queue._mutation_locks
