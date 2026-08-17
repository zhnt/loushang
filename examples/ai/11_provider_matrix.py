"""Curated provider catalog lookup example.

This example does not call any remote API. It only reads the built-in curated
model catalog and prints provider/endpoint/model facts needed before a real
call.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.ai import get_model, list_models


@dataclass(frozen=True)
class ProviderExample:
    provider_id: str
    endpoint_id: str
    model_id: str
    env_vars: tuple[str, ...]


PROVIDER_EXAMPLES = (
    ProviderExample(
        "anthropic",
        "anthropic-messages",
        "claude-sonnet-5",
        ("ANTHROPIC_API_KEY",),
    ),
    ProviderExample(
        "baidu-qianfan",
        "openai-completions-cn",
        "ernie-5.1",
        ("QIANFAN_API_KEY", "BAIDU_QIANFAN_API_KEY"),
    ),
    ProviderExample(
        "dashscope",
        "openai-responses",
        "qwen3.7-plus",
        ("DASHSCOPE_API_KEY",),
    ),
    ProviderExample(
        "deepseek",
        "openai-completions",
        "deepseek-v4-flash",
        ("DEEPSEEK_API_KEY",),
    ),
    ProviderExample(
        "minimax",
        "anthropic-messages",
        "MiniMax-M3",
        ("MINIMAX_API_KEY",),
    ),
    ProviderExample(
        "moonshot",
        "openai-completions",
        "kimi-k2.6",
        ("MOONSHOT_API_KEY",),
    ),
    ProviderExample(
        "openai",
        "openai-responses",
        "gpt-5.4-mini",
        ("OPENAI_API_KEY",),
    ),
    ProviderExample(
        "stepfun",
        "openai-completions",
        "step-3.7-flash",
        ("STEP_API_KEY", "STEPFUN_API_KEY"),
    ),
    ProviderExample(
        "tencent-hunyuan",
        "openai-responses",
        "hy3",
        ("HUNYUAN_API_KEY",),
    ),
    ProviderExample(
        "volcano-ark",
        "openai-completions-cn-beijing",
        "doubao-seed-2-1-turbo-260628",
        ("ARK_API_KEY",),
    ),
    ProviderExample(
        "zai",
        "openai-completions",
        "glm-5.2",
        ("ZAI_API_KEY",),
    ),
)


def _format_model_line(example: ProviderExample) -> str:
    model = get_model(example.provider_id, example.endpoint_id, example.model_id)
    upstream = model.upstream_id
    suffix = f" upstream={upstream}" if isinstance(upstream, str) else ""
    env = ",".join(example.env_vars)
    return (
        f"{model.provider_id}:{model.endpoint_id}:{model.id} "
        f"api={model.api} env={env}{suffix}"
    )


def main() -> None:
    print(f"TOTAL models={len(list_models())}")
    for example in PROVIDER_EXAMPLES:
        print(_format_model_line(example))


if __name__ == "__main__":
    main()
