#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

ARTIFACT_ROOT_NAME = ".loushang"
BUILTIN_MODEL_CATALOG = Path("src/loushang/ai/model/models.json")


def _detect_repo_root(start: Path) -> Path:
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    while candidate.parent != candidate:
        if (candidate / "src").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Unable to locate repository root (no src/ found).")


def _write_if_missing(path: Path, content: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def _safe_copy(src: Path, dst: Path, *, overwrite: bool) -> None:
    if not src.exists():
        raise FileNotFoundError(f"catalog template not found: {src}")
    if dst.exists() and not overwrite:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _build_default_readme(artifacts_root: Path) -> str:
    return (
        "# Loushang Coding Examples Runtime\n\n"
        "该目录为 `examples/coding` 示例的本地运行时目录（可按需重定向）。\n"
        f"当前路径: `{artifacts_root}`\n\n"
        "## 目录说明\n"
        "- `sessions/`: 会话落盘目录（persist=True 示例）\n"
        "- `extensions/`: 可共享的扩展文件\n"
        "- `models/`: 模型 catalog 目录（放 `*.json` 时自动按文件名顺序加载并合并）\n\n"
        "优先级（run.py）：\n"
        "1. 显式 `--model-catalog`\n"
        "2. `LOUSHANG_EXAMPLES_MODEL_CATALOG`\n"
        "3. `<artifact-root>/models/`（存在 `.json` 文件）\n"
        "4. `<artifact-root>/models.json`\n"
        f"5. 内置 `{BUILTIN_MODEL_CATALOG.as_posix()}`\n"
        "使用 `--copy-model-catalog` 可将内置 catalog 拷贝到 `models/models.json` 作为模板。\n"
    )


def _build_sessions_readme() -> str:
    return (
        "# Sessions\n\n"
        "此目录用于示例会话持久化（JSONL），用于 `resume` 和跨轮次恢复。\n"
    )


def _build_extensions_readme() -> str:
    return "# Extensions\n\n此目录用于共享的示例扩展脚本（extensions）。\n"


def _build_models_readme() -> str:
    return (
        "# Model Catalogs\n\n"
        "此目录用于放置可被自动发现的模型 catalog，文件名建议形如 `models.xx.json`。\n"
        f"格式要求与 `{BUILTIN_MODEL_CATALOG.as_posix()}` 兼容。\n"
    )


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialize examples/coding runtime assets for cross-machine execution."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to detect source/catalog defaults.",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=None,
        help="Optional custom artifact root (default: examples/coding/.loushang).",
    )
    parser.add_argument(
        "--copy-model-catalog",
        action="store_true",
        help=(
            "Copy src/loushang/ai/model/models.json to "
            "<artifacts-root>/models/models.json."
        ),
    )
    parser.add_argument(
        "--skip-session-dir",
        action="store_true",
        help="Do not create the sessions/ directory.",
    )
    parser.add_argument(
        "--skip-extensions-dir",
        action="store_true",
        help="Do not create the extensions/ directory.",
    )
    parser.add_argument(
        "--skip-models-dir",
        action="store_true",
        help="Do not create the models/ directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite generated files if already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions only.",
    )

    args = parser.parse_args(argv)
    repo_root = _detect_repo_root(args.repo_root)
    examples_root = repo_root / "examples" / "coding"
    artifacts_root = (
        args.artifacts_root
        if args.artifacts_root is not None
        else examples_root / ARTIFACT_ROOT_NAME
    )

    sessions_dir = artifacts_root / "sessions"
    extensions_dir = artifacts_root / "extensions"
    models_dir = artifacts_root / "models"

    plan: list[tuple[str, Path]] = []

    def add(action: str, path: Path) -> None:
        plan.append((action, path))

    add("mkdir", artifacts_root)
    if not args.skip_session_dir:
        add("mkdir", sessions_dir)
        add("file ", sessions_dir / "README.md")
    if not args.skip_extensions_dir:
        add("mkdir", extensions_dir)
        add("file ", extensions_dir / "README.md")
    if not args.skip_models_dir:
        add("mkdir", models_dir)
        add("file ", models_dir / "README.md")
    add("file ", artifacts_root / "README.md")
    if args.copy_model_catalog:
        add("copy ", repo_root / BUILTIN_MODEL_CATALOG)
        add("file ", models_dir / "models.json")

    if args.dry_run:
        print(f"Plan for: {artifacts_root}")
        for action, path in plan:
            print(f"- {action} {path}")
        print("Use without --dry-run to apply.")
        return 0

    artifacts_root.mkdir(parents=True, exist_ok=True)
    _write_if_missing(
        artifacts_root / "README.md",
        _build_default_readme(artifacts_root),
        overwrite=args.overwrite,
    )
    if not args.skip_session_dir:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_if_missing(
            sessions_dir / "README.md",
            _build_sessions_readme(),
            overwrite=args.overwrite,
        )
    if not args.skip_extensions_dir:
        extensions_dir.mkdir(parents=True, exist_ok=True)
        _write_if_missing(
            extensions_dir / "README.md",
            _build_extensions_readme(),
            overwrite=args.overwrite,
        )
    if not args.skip_models_dir:
        models_dir.mkdir(parents=True, exist_ok=True)
        _write_if_missing(
            models_dir / "README.md", _build_models_readme(), overwrite=args.overwrite
        )

    if args.copy_model_catalog:
        _safe_copy(
            src=repo_root / BUILTIN_MODEL_CATALOG,
            dst=models_dir / "models.json",
            overwrite=args.overwrite,
        )

    os.environ["LOUSHANG_EXAMPLES_ARTIFACT_ROOT"] = str(artifacts_root)
    if args.copy_model_catalog:
        os.environ["LOUSHANG_EXAMPLES_MODEL_CATALOG"] = str(models_dir)

    print("Initialized examples/coding runtime:")
    print(f"  repo_root: {repo_root}")
    print(f"  artifacts_root: {artifacts_root}")
    if args.copy_model_catalog:
        print(f"  copied catalog: {models_dir / 'models.json'}")
    print()
    print("Recommended next steps:")
    try:
        rel_artifacts = artifacts_root.relative_to(repo_root)
        rel_artifacts = str(rel_artifacts)
    except ValueError:
        rel_artifacts = str(artifacts_root)
    print(f"  export LOUSHANG_EXAMPLES_ARTIFACT_ROOT={rel_artifacts}")
    if args.copy_model_catalog:
        print(f"  export LOUSHANG_EXAMPLES_MODEL_CATALOG={artifacts_root / 'models'}")
    print("  source examples/coding/kimicode.env.example")
    print("  python examples/coding/run.py list --count")
    print("  python examples/coding/run.py run legacy-007")
    print(
        "  python examples/coding/run.py run --artifacts-root <artifacts_root> legacy-001"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
