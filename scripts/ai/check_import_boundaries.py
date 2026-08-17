from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SRC = REPO_ROOT / "src/loushang/ai"
TOP_LEVEL_AUTH_SRC = REPO_ROOT / "src/loushang/auth"
TOP_LEVEL_EXAMPLES = REPO_ROOT / "examples/ai"
AUTH_EXAMPLES = REPO_ROOT / "examples/auth"
DISALLOWED_AI_RUNTIME_IMPORTS = ("loushang.agent", "loushang.coding")
ALLOWED_TOP_LEVEL_EXAMPLE_IMPORTS = {
    "loushang.ai",
    "loushang.ai.tool",
    "loushang.ai.auth",
}
DISALLOWED_CORE_PROVIDER_MODULES = {
    "azure_openai_responses.py",
    "bedrock_converse.py",
    "codex_responses.py",
    "openai_coding_responses.py",
    "openai_codex_responses.py",
    "openai_codex_runtime_config.py",
}


def main() -> int:
    offenders = check_import_boundaries()
    if offenders:
        for offender in offenders:
            print(f"ERROR {offender}", file=sys.stderr)
        return 1
    print("OK import boundaries")
    return 0


def check_import_boundaries() -> list[str]:
    offenders: list[str] = []
    if TOP_LEVEL_AUTH_SRC.exists():
        offenders.append(
            "src/loushang/auth must not exist; authentication is owned by loushang.ai.auth"
        )
    for path in sorted(AI_SRC.rglob("*.py")):
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        for module in _imported_modules(tree):
            if module.startswith(DISALLOWED_AI_RUNTIME_IMPORTS):
                offenders.append(f"{relative_path} imports {module}")

    provider_modules = {path.name for path in (AI_SRC / "providers").glob("*.py")}
    forbidden_modules = sorted(provider_modules & DISALLOWED_CORE_PROVIDER_MODULES)
    if forbidden_modules:
        offenders.append(
            f"core providers contain non-core adapters: {forbidden_modules}"
        )

    public_examples = set(TOP_LEVEL_EXAMPLES.glob("[0-9][0-9]_*.py"))
    codex_live_example = AUTH_EXAMPLES / "openai_codex_live_example.py"
    if codex_live_example.is_file():
        public_examples.add(codex_live_example)

    for path in sorted(public_examples):
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        for module in _imported_modules(tree):
            if not module.startswith("loushang."):
                continue
            if module not in ALLOWED_TOP_LEVEL_EXAMPLE_IMPORTS:
                offenders.append(f"{relative_path} imports non-stable module {module}")
    return offenders


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


if __name__ == "__main__":
    raise SystemExit(main())
