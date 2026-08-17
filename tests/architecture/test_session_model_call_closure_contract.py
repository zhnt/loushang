from __future__ import annotations

import ast
import re
from pathlib import Path

CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/session-model-call-closure-boundary.md"
)
PLAN_PATH = Path(
    "docs/internals/architecture/harness/capability-runtime-convergence-plan.md"
)
README_PATH = Path("docs/internals/architecture/harness/README.md")

MODEL_CALL_ROOTS = (
    Path("src/loushang/agent"),
    Path("src/loushang/harness"),
    Path("src/loushang/coding"),
)
DIRECT_AI_ENTRYPOINT_MODULES = frozenset({"loushang.ai", "loushang.ai.api"})
DIRECT_AI_ENTRYPOINTS = frozenset({"complete", "stream"})
EXPECTED_DIRECT_AI_IMPORTS = {
    Path("src/loushang/agent/agent.py"): frozenset({"stream"}),
    Path("src/loushang/agent/agent_loop.py"): frozenset({"stream"}),
    Path("src/loushang/harness/transcript/summarization.py"): frozenset(
        {"complete", "stream"}
    ),
}

MODEL_CALL_RUNTIME_PATH = Path("src/loushang/harness/session/model_call.py")


def test_pr8_contract_keeps_complete_model_call_inventory_and_evidence() -> None:
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    rows = re.findall(r"^\| (MC-\d{2}) \|(.+)$", text, re.MULTILINE)

    assert [row_id for row_id, _body in rows] == [
        f"MC-{index:02d}" for index in range(1, 8)
    ]
    for row_id, body in rows:
        references = re.findall(
            r"`(src/[\w./-]+\.py)::([A-Za-z_][\w.]*)`",
            body,
        )
        assert references, f"{row_id} must cite at least one source symbol"
        for raw_path, qualified_name in references:
            path = Path(raw_path)
            assert path.is_file(), f"missing PR8 evidence file: {path}"
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            functions = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            function_name = qualified_name.rsplit(".", maxsplit=1)[-1]
            assert function_name in functions, (
                f"missing PR8 evidence function: {raw_path}::{qualified_name}"
            )


def test_pr8_contract_names_every_sampling_purpose() -> None:
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    required_purposes = {
        "main",
        "tool_continuation",
        "continuation",
        "retry",
        "compaction_history",
        "compaction_turn_prefix",
        "branch_summary",
        "side_question",
    }

    assert all(f"`{purpose}`" in text for purpose in required_purposes)


def test_direct_ai_model_entrypoint_imports_remain_inventoried() -> None:
    actual: dict[Path, frozenset[str]] = {}
    for root in MODEL_CALL_ROOTS:
        for path in root.rglob("*.py"):
            imported: set[str] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module in DIRECT_AI_ENTRYPOINT_MODULES
                ):
                    imported.update(
                        alias.name
                        for alias in node.names
                        if alias.name in DIRECT_AI_ENTRYPOINTS
                    )
                elif isinstance(node, ast.Import):
                    imported.update(
                        "*"
                        for alias in node.names
                        if alias.name in DIRECT_AI_ENTRYPOINT_MODULES
                    )
            if imported:
                actual[path] = frozenset(imported)

    assert actual == EXPECTED_DIRECT_AI_IMPORTS


def test_pr8_contract_is_linked_from_plan_and_harness_catalog() -> None:
    link = "session-model-call-closure-boundary.md"

    assert link in PLAN_PATH.read_text(encoding="utf-8")
    assert link in README_PATH.read_text(encoding="utf-8")


def test_cla2_model_call_runtime_cannot_plan_bind_or_own_the_graph() -> None:
    tree = ast.parse(
        MODEL_CALL_RUNTIME_PATH.read_text(encoding="utf-8"),
        filename=str(MODEL_CALL_RUNTIME_PATH),
    )
    runtime = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SessionModelCallRuntime"
    )
    forbidden = {
        "RuntimeCapabilityGraphBinder",
        "RuntimeCapabilityGraphPlanner",
        "RuntimeCapabilityGraphRuntime",
    }
    referenced = {
        node.id for node in ast.walk(runtime) if isinstance(node, ast.Name)
    }

    assert referenced.isdisjoint(forbidden)
    assert {
        node.name
        for node in runtime.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }.isdisjoint({"bind", "dispose"})
