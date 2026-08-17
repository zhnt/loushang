from __future__ import annotations

import re
from pathlib import Path

from loushang.ai.model import load_builtin_model_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_DOC_PATHS = [
    REPO_ROOT / "docs/en/sdk/README.md",
    REPO_ROOT / "docs/zh-CN/sdk/README.md",
]


def test_provider_docs_cover_new_provider_configuration() -> None:
    docs = Path("examples/ai/README.md").read_text(encoding="utf-8")
    registry = load_builtin_model_registry()

    for provider_id in [
        "anthropic",
        "baidu-qianfan",
        "dashscope",
        "deepseek",
        "minimax",
        "moonshot",
        "openai",
        "stepfun",
        "tencent-hunyuan",
        "volcano-ark",
        "zai",
    ]:
        assert registry.get_provider(provider_id) is not None
        assert f"`{provider_id}`" in docs or f"- `{provider_id}`" in docs

    for env_name in [
        "ANTHROPIC_API_KEY",
        "QIANFAN_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "STEPFUN_API_KEY",
    ]:
        assert env_name in docs


def test_ai_readme_documents_curated_builtin_catalog_and_archive() -> None:
    docs = Path("src/loushang/ai/README.md").read_text(encoding="utf-8")

    assert "models.json" in docs
    assert "backup/ai/models-legacy-full.json.gz" in docs
    assert "model.upstream_id" in docs
    assert "ProviderRequest.upstream_model_id" not in docs
    assert "kimi-k2.6" in docs


def test_stable_sdk_guides_cover_public_ai_paths_and_examples() -> None:
    required_terms = [
        "CallOptions",
        "ReasoningOptions",
        "StructuredOutputOptions",
        "ImagePart",
        "AIError",
        "RetryOptions",
        "Usage",
        "models.json",
        "11_provider_matrix.py",
        "12_provider_smoke.py",
        "custom_model_file.py",
        "advanced/custom_catalog.py",
        "upstreamId",
        "adapter",
    ]

    for path in SDK_DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for term in required_terms:
            assert term in text, (path, term)
        for target in re.findall(r"\]\((../../../examples/ai/[^)]+)\)", text):
            assert (path.parent / target).resolve().exists(), (path, target)
