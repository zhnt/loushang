from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.ai import Context, UserMessage, complete, get_model
from loushang.ai.model import (
    Model,
    load_model_registry_from_directory,
    load_model_registry_from_file,
)
from loushang.ai.model.registry import ModelRegistry

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - py311 fallback
    import tomli as tomllib  # type: ignore[import-not-found]


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "example-manifest.toml"
DEFAULT_ARTIFACT_ROOT = ROOT / ".loushang"
ENV_EXAMPLES_ARTIFACT_ROOT = "LOUSHANG_EXAMPLES_ARTIFACT_ROOT"
ENV_EXAMPLES_EXTENSIONS_DIR = "LOUSHANG_EXAMPLES_EXTENSIONS_DIR"
ENV_EXAMPLES_MODEL_CATALOG = "LOUSHANG_EXAMPLES_MODEL_CATALOG"
ENV_EXAMPLES_SESSION_DIR = "LOUSHANG_EXAMPLES_SESSION_DIR"
_MODEL_REGISTRY_OVERRIDE: ModelRegistry | None = None


@dataclass(frozen=True)
class Profile:
    provider: str
    endpoint: str
    model: str


@dataclass(frozen=True)
class Example:
    id: str
    slug: str
    title: str
    category: str
    description: str
    runtime: str
    model_profile: str | None
    requires_api_key: bool
    tags: list[str]
    entrypoint: str | None
    generated: bool
    prompt_template: str | None = None
    compact_reserve_tokens: int | None = None
    compact_keep_recent_tokens: int | None = None
    args: list[str] | None = None

    def matches(self, *, category: str | None, tag: str | None, query: str | None) -> bool:
        if category and self.category != category:
            return False
        if tag and tag not in self.tags:
            return False
        if query:
            needle = query.lower()
            haystack = f"{self.id} {self.slug} {self.title} {self.description} {' '.join(self.tags)}".lower()
            if needle not in haystack:
                return False
        return True


def _provider_default_key_envs(provider: str) -> list[str]:
    if provider in {"moonshot", "kimi", "dashscope", "openai", "google", "azure"}:
        key_name = {
            "moonshot": ["KIMI_AUTH_TOKEN", "MOONSHOT_API_KEY", "KIMI_API_KEY"],
            "kimi": "MOONSHOT_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
            "azure": "AZURE_API_KEY",
        }.get(provider)
        if key_name is None:
            return []
        return [key_name] if isinstance(key_name, str) else key_name
    if provider == "kimi-code":
        return ["KIMI_CODE_API_KEY"]
    return []


def _load_manifest() -> tuple[dict[str, Profile], list[Example]]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"manifest not found: {MANIFEST_PATH}")

    data = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    profiles: dict[str, Profile] = {}
    for name, raw in data.get("profiles", {}).items():
        profiles[name] = Profile(
            provider=raw["provider"],
            endpoint=raw["endpoint"],
            model=raw["model"],
        )

    examples: list[Example] = []
    for raw in data.get("example", []):
        examples.append(
            _coerce_example(
                raw,
                id=raw["id"],
                slug=raw["slug"],
                generated=False,
            )
        )

    for series in data.get("series", []):
        examples.extend(_expand_series(series, meta=data.get("meta", {})))
    return profiles, _dedupe_examples(examples)


def _coerce_example(
    raw: dict[str, Any],
    *,
    id: str,
    slug: str | None = None,
    generated: bool,
) -> Example:
    return Example(
        id=str(id),
        slug=slug or str(id),
        title=str(raw["title"]),
        category=str(raw["category"]),
        description=str(raw.get("description", "")),
        runtime=str(raw["runtime"]),
        model_profile=raw.get("model_profile"),
        requires_api_key=bool(raw.get("requires_api_key", False)),
        tags=[str(tag) for tag in raw.get("tags", [])],
        entrypoint=raw.get("entrypoint"),
        generated=generated,
        prompt_template=raw.get("prompt_template"),
        compact_reserve_tokens=raw.get("compact_reserve_tokens"),
        compact_keep_recent_tokens=raw.get("compact_keep_recent_tokens"),
        args=raw.get("args"),
    )


def _expand_series(raw: dict[str, Any], *, meta: dict[str, Any]) -> list[Example]:
    count = int(raw["count"])
    topics = list(raw.get("topics", []))
    if count > len(topics):
        raise ValueError(f"series {raw['id_prefix']} requires at least {count} topics, got {len(topics)}")

    defaults = {
        "compact_reserve_tokens": raw.get("compact_reserve_tokens", meta.get("default_compaction_reserve_tokens")),
        "compact_keep_recent_tokens": raw.get(
            "compact_keep_recent_tokens", meta.get("default_compaction_keep_recent_tokens")
        ),
    }
    model_profile = raw.get("model_profile")
    category = str(raw["category"])
    prompt_template = str(raw.get("prompt_template", "请给出 {topic} 的最小示例和步骤。"))
    title_template = str(raw.get("title_template", "{topic}"))
    description_template = str(raw.get("description_template", "Generated example for {topic}"))

    entries: list[Example] = []
    for index in range(1, count + 1):
        topic = topics[index - 1]
        example_id = f"{raw['id_prefix']}-{index:02d}"
        slug = f"{raw['id_prefix']}-{index:02d}"
        entries.append(
            Example(
                id=example_id,
                slug=slug,
                title=title_template.format(topic=topic, index=index),
                category=category,
                description=description_template.format(topic=topic, index=index),
                runtime=str(raw["runtime"]),
                model_profile=model_profile,
                requires_api_key=bool(raw.get("requires_api_key", False)),
                tags=[str(tag) for tag in raw.get("tags", [])],
                entrypoint=None,
                generated=True,
                prompt_template=prompt_template.format(topic=topic, index=index),
                compact_reserve_tokens=defaults["compact_reserve_tokens"],
                compact_keep_recent_tokens=defaults["compact_keep_recent_tokens"],
                args=None,
            )
        )
    return entries


def _dedupe_examples(raw: list[Example]) -> list[Example]:
    seen: set[str] = set()
    out: list[Example] = []
    for example in raw:
        if example.id in seen:
            continue
        seen.add(example.id)
        out.append(example)
    out.sort(key=lambda item: item.id)
    return out


def _resolve_model(profile_name: str | None, profiles: dict[str, Profile]) -> Model:
    if not profile_name:
        profile_name = "coding_primary"
    profile = profiles[profile_name]
    catalog_path = os.environ.get(ENV_EXAMPLES_MODEL_CATALOG, "").strip()
    if catalog_path:
        global _MODEL_REGISTRY_OVERRIDE
        if _MODEL_REGISTRY_OVERRIDE is None:
            try:
                path = Path(catalog_path)
                loader = (
                    load_model_registry_from_directory
                    if path.is_dir()
                    else load_model_registry_from_file
                )
                _MODEL_REGISTRY_OVERRIDE = loader(path)
            except FileNotFoundError as exc:
                raise RuntimeError(f"model catalog not found: {catalog_path}") from exc
            except Exception as exc:
                raise RuntimeError(
                    f"resolve model from custom catalog failed: {catalog_path}"
                ) from exc
        return _MODEL_REGISTRY_OVERRIDE.get_model(
            profile.provider,
            profile.endpoint,
            profile.model,
        )
    return get_model(profile.provider, profile.endpoint, profile.model)


def _resolve_artifact_paths(args: argparse.Namespace) -> dict[str, str]:
    artifact_root = Path(
        getattr(args, "artifacts_root", None)
        or os.environ.get(ENV_EXAMPLES_ARTIFACT_ROOT, str(DEFAULT_ARTIFACT_ROOT))
    ).expanduser().resolve()
    extensions_dir = Path(
        getattr(args, "extensions_dir", None)
        or os.environ.get(ENV_EXAMPLES_EXTENSIONS_DIR, str(artifact_root / "extensions"))
    ).expanduser().resolve()
    session_dir = Path(
        getattr(args, "session_dir", None)
        or os.environ.get(ENV_EXAMPLES_SESSION_DIR, str(artifact_root / "sessions"))
    ).expanduser().resolve()
    model_catalog = str(getattr(args, "model_catalog", "") or "")
    if model_catalog:
        model_catalog = str(Path(model_catalog).expanduser())
    else:
        model_catalog = os.environ.get(ENV_EXAMPLES_MODEL_CATALOG, "").strip()
        if not model_catalog:
            candidate_dir = artifact_root / "models"
            candidate_file = artifact_root / "models.json"
            has_model_file = any(candidate_dir.glob("*.json")) if candidate_dir.is_dir() else False
            if candidate_dir.is_dir() and has_model_file:
                model_catalog = str(candidate_dir)
            elif candidate_file.is_file():
                model_catalog = str(candidate_file)

    return {
        "artifact_root": str(artifact_root),
        "extensions_dir": str(extensions_dir),
        "session_dir": str(session_dir),
        "model_catalog": model_catalog,
    }


def _prepare_runtime_paths(paths: dict[str, str]) -> None:
    for key in ("artifact_root", "extensions_dir", "session_dir"):
        Path(paths[key]).mkdir(parents=True, exist_ok=True)


def _format_examples(entries: list[Example], *, show_count_only: bool = False) -> str:
    if show_count_only:
        return f"total_examples: {len(entries)}"

    headers = ("ID", "分类", "运行时", "标题", "标签", "入口", "入口类型")
    rows = [headers]
    for ex in entries:
        entry_type = "script" if ex.entrypoint else "generated"
        path = ex.entrypoint or "internal"
        rows.append(
            (
                ex.id,
                ex.category,
                ex.runtime,
                ex.title,
                ",".join(ex.tags[:3]),
                path,
                entry_type,
            )
        )

    widths = [max(len(str(row[i])) for row in rows) for i in range(len(headers))]
    lines = []
    header = "  ".join(str(value).ljust(widths[i]) for i, value in enumerate(rows[0]))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    lines.append(header)
    lines.append(sep)
    for row in rows[1:]:
        lines.append("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
    return "\n".join(lines)


def _resolve_example(entries: list[Example], selector: str) -> Example:
    for ex in entries:
        if ex.id == selector or ex.slug == selector:
            return ex
    raise KeyError(f"not found example '{selector}'")


def _check_api_key(profile: Profile) -> bool:
    env_names = _provider_default_key_envs(profile.provider)
    if not env_names:
        return True
    return any(__import__("os").environ.get(name) for name in env_names)


def _run_existing_script(
    example: Example,
    extra_args: list[str],
    args: argparse.Namespace,
) -> int:
    script = ROOT / example.entrypoint
    if not script.exists():
        print(f"[warning] script missing: {script}", file=sys.stderr)
        return 127

    paths = _resolve_artifact_paths(args)
    _prepare_runtime_paths(paths)
    example_args = example.args or []
    command = [sys.executable, str(script), *example_args, *extra_args]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([str(SRC_ROOT), existing]) if existing else str(SRC_ROOT)
    env[ENV_EXAMPLES_ARTIFACT_ROOT] = paths["artifact_root"]
    env[ENV_EXAMPLES_EXTENSIONS_DIR] = paths["extensions_dir"]
    env[ENV_EXAMPLES_SESSION_DIR] = paths["session_dir"]
    if paths["model_catalog"]:
        env[ENV_EXAMPLES_MODEL_CATALOG] = paths["model_catalog"]
    result = subprocess.run(command, cwd=ROOT, env=env)
    return result.returncode


async def _run_online_probe(example: Example, profiles: dict[str, Profile], topic: str) -> int:
    if example.model_profile is None:
        print("[warning] no model profile configured for this example", file=sys.stderr)
        return 2

    profile = profiles[example.model_profile]
    if example.requires_api_key and not _check_api_key(profile):
        print(f"[missing env] {profile.provider} examples require API key", file=sys.stderr)
        return 2

    print(f"Runtime model: {profile.provider}:{profile.endpoint}:{profile.model}")
    prompt = example.prompt_template or "请给出本例子的最小执行说明。"
    prompt = prompt.format(topic=topic)

    try:
        context = Context(
            system_prompt="You are a concise coding assistant.",
            messages=[UserMessage(role="user", content=prompt, timestamp=time.time())],
        )
        model = _resolve_model(example.model_profile, profiles)
        response = await complete(model, context)
        content = "".join(part.text for part in response.content if getattr(part, "type", None) == "text")
        print(textwrap.fill(content or "[no text output]", width=100))
        return 0
    except Exception as exc:
        print(f"[error] call model failed: {exc}", file=sys.stderr)
        return 1


def _run_offline_compaction(example: Example, topic: str) -> int:
    reserve = example.compact_reserve_tokens or 256
    keep = example.compact_keep_recent_tokens or 128
    print("Compaction settings (short):")
    print(f"  reserve_tokens = {reserve}")
    print(f"  keep_recent_tokens = {keep}")
    print()
    print(f"Scenario: {topic}")
    print("  1) 先计算上下文窗口")
    print("  2) 当超过 reserve_tokens 阈值时触发 compact")
    print("  3) 保留最近 keep_recent_tokens 以内的消息")
    print("  4) 为后续模型会话生成摘要")
    return 0


def _run_offline_step_by_step(example: Example, topic: str) -> int:
    print("Step-by-step (no rendering) scaffold:")
    prompt = example.prompt_template or "请给出 5 步操作步骤。"
    prompt = prompt.format(topic=topic)
    print(textwrap.fill(prompt, width=100))
    print()
    print("Implementation plan:")
    for step in (
        "mkdir /tmp/loushang-demo",
        "create file scaffold.py",
        "append one function",
        "run a lightweight validation command",
        "show file diff summary",
    ):
        print(f"  - {step}")
    return 0


async def _run_generated(example: Example, extra_args: list[str], profiles: dict[str, Profile]) -> int:
    del extra_args
    topic = example.description
    if example.category == "compaction":
        return _run_offline_compaction(example, topic)
    if example.category == "step_by_step_coding":
        return _run_offline_step_by_step(example, topic)

    if example.runtime == "online":
        return await _run_online_probe(example, profiles, topic)

    print("Generated offline example:")
    print(textwrap.fill(topic, width=100))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run examples from examples/coding via manifest.")

    def _add_runtime_options(target_parser: argparse.ArgumentParser) -> None:
        target_parser.add_argument(
            "--artifacts-root",
            dest="artifacts_root",
            type=Path,
            default=None,
            help="Root directory for example artifacts (session/model/extension files).",
        )
        target_parser.add_argument(
            "--extensions-dir",
            dest="extensions_dir",
            type=Path,
            default=None,
            help="Directory to place reusable extension files for examples.",
        )
        target_parser.add_argument(
            "--session-dir",
            dest="session_dir",
            type=Path,
            default=None,
            help="Directory for session persistence used by examples that persist runtime state.",
        )
        target_parser.add_argument(
            "--model-catalog",
            dest="model_catalog",
            type=Path,
            default=None,
            help="Optional model catalog file or directory to use with examples.",
        )

    parser.add_argument(
        "--version", action="version", version="run.py 0.1.0"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cmd = subparsers.add_parser("list", help="List available examples.")
    list_cmd.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    _add_runtime_options(list_cmd)
    list_cmd.add_argument("--category")
    list_cmd.add_argument("--tag")
    list_cmd.add_argument("--query")
    list_cmd.add_argument("--count", action="store_true")
    list_cmd.add_argument("--json", action="store_true")

    run_cmd = subparsers.add_parser("run", help="Run an example by id or slug.")
    run_cmd.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    _add_runtime_options(run_cmd)
    run_cmd.add_argument("selector")
    run_cmd.add_argument("args", nargs="*", help="Extra args forwarded to script examples.")
    run_cmd.add_argument("--dry-run", action="store_true", help="Show execution plan only.")

    return parser.parse_args()


def _list_examples() -> int:
    args = _parse_args()
    global MANIFEST_PATH
    if args.manifest:
        MANIFEST_PATH = args.manifest

    profiles, examples = _load_manifest()
    del profiles
    filtered = [
        example
        for example in examples
        if example.matches(category=args.category, tag=args.tag, query=args.query)
    ]
    if args.count:
        print(f"{len(filtered)}")
        return 0
    if args.json:
        import json
        payload = [
            {
                "id": example.id,
                "slug": example.slug,
                "title": example.title,
                "category": example.category,
                "runtime": example.runtime,
                "tags": example.tags,
                "requires_api_key": example.requires_api_key,
                "entrypoint": example.entrypoint,
                "generated": example.generated,
            }
            for example in filtered
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(_format_examples(filtered))
    return 0


async def _run_examples() -> int:
    args = _parse_args()
    global MANIFEST_PATH
    if args.manifest:
        MANIFEST_PATH = args.manifest

    profiles, examples = _load_manifest()
    try:
        example = _resolve_example(examples, args.selector)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run:")
        print(f"  id={example.id}")
        print(f"  title={example.title}")
        print(f"  category={example.category}")
        print(f"  runtime={example.runtime}")
        print(f"  entrypoint={example.entrypoint or '<generated>'}")
        return 0

    if example.entrypoint:
        return _run_existing_script(example, args.args, args)
    return await _run_generated(example, args.args, profiles)


def main() -> int:
    if len(sys.argv) <= 1:
        print("Usage: python run.py <list|run> ...")
        return 1
    namespace = sys.argv[1]
    if namespace == "list":
        return _list_examples()
    if namespace == "run":
        return asyncio.run(_run_examples())
    print(f"unknown command: {namespace}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
