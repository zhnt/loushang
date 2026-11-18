# Built-in model catalog and reasoning effort sources

Reviewed on 2026-11-18. The built-in catalog covers the providers and API
routes already supported by Loushang. It keeps the current flagship and
distinct fast, economical, or subscription options. A public preview can be
listed alongside a stable model when the provider documents its hosted API.
Retired IDs, superseded snapshots, and aliases that duplicate a current
offering are dropped from the curated list.

## Provider controls

The table records effective levels for the specific Loushang endpoint.
Providers may accept additional wire values and map them to these levels.
“Off” refers to the provider's control for disabling thinking, where documented.

| Provider and models | Effective levels and provider default | Off and protocol details | Sources |
| --- | --- | --- | --- |
| OpenAI Responses and Codex OAuth, GPT-6.2 Astra and Sol | `low`, `medium`, `high`, `xhigh`, `max`. Start with `medium`. | Responses uses `reasoning.effort`. `none` returns HTTP 400. Codex access depends on the account. | [Migration guide](https://developers.openai.com/api/docs/guides/latest-model), [Astra](https://developers.openai.com/api/docs/models/gpt-6.2-astra), [Sol](https://developers.openai.com/api/docs/models/gpt-6.2-sol), [Codex availability](https://openai.com/index/introducing-gpt-6-2-astra-sol/) |
| OpenAI Responses and Codex OAuth, GPT-6.1 Terra and GPT-6 Luna | `low`, `medium`, `high`, `xhigh`, `max`. Default `medium`. | `reasoning.effort: "none"` turns thinking off. | [Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| Anthropic Messages, Fable 5.2, Opus 5.5, Sonnet 5.5 and Haiku 5.5 | `low`, `medium`, `high`, `xhigh`, `max`. Fable and Sonnet default to `high`, Opus and Haiku to `medium`. | `output_config.effort` with adaptive thinking. Fable and Opus always think. Sonnet uses `thinking.type: "between_tools"` for reduced thinking and rejects `disabled`. Haiku supports reduced thinking via `between_tools` at `high` or below. The current adapter omits `thinking` on Off, which leaves the provider default in effect on Sonnet and Haiku. | [Models](https://platform.claude.com/docs/en/models/overview), [Effort](https://platform.claude.com/docs/en/build-with-claude/effort), [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking) |
| DashScope Responses, Qwen4 Max | `low`, `high`, `xhigh`. Default `high`. | `reasoning.effort` maps `minimal` to `low`, `medium` to `high` and `max` to `xhigh`. | [Qwen4 Max](https://help.aliyun.com/zh/model-studio/qwen4-max), [Responses](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses) |
| DashScope Responses, Qwen3.8 Flash and Qwen3.7 Plus | Flash uses `low`, `medium`, `xhigh` with `xhigh` as the default. Plus is a hybrid thinking model whose exact Responses tiers are unconfirmed. | Flash maps `minimal` to `low` and `high`/`max` to `xhigh`. `reasoning.effort: "none"` requests non-thinking mode. | [Responses](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses), [Current lineup](https://help.aliyun.com/zh/model-studio/what-is-model-studio), [Thinking](https://help.aliyun.com/en/model-studio/deep-thinking) |
| DeepSeek Chat Completions, V4.1 Flash and V4 Pro | `low`, `high`, `max`. Default `high`. | Uses `reasoning_effort` and the separate `thinking.type` toggle. The Loushang `xhigh` choice requests native `max`. DeepSeek itself translates wire `xhigh` to `high`. | [Thinking](https://api-docs.deepseek.com/guides/thinking_mode/), [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing/?model_version=DeepSeek-V4-Pro-0813) |
| MiniMax Anthropic Messages, M3.1 Flash and M3 | M3.1 Flash uses `low`, `medium`, `high`, `xhigh`, `max`. Default `max`. M3 has a thinking toggle, default off, with no documented adjustable effort on this route. | For M3.1 Flash, use `output_config.effort` and keep thinking enabled. M3 uses `thinking.type: "adaptive"` to enable thinking. | [Anthropic-compatible API](https://platform.minimax.io/docs/api-reference/text-anthropic-api), [Pricing](https://platform.minimax.io/docs/pricing/overview) |
| Moonshot Chat Completions, Kimi K3.1 Pro and Pro Highspeed | `low`, `high`, `max`. K3.1 defaults to `max`. | K3.1 uses top-level `reasoning_effort` and always thinks. | [Model IDs and retirement dates](https://platform.kimi.ai/docs/models), [Reasoning effort](https://platform.kimi.ai/docs/guide/use-reasoning-effort) |
| Kimi Code, both compatible routes | K3.1 Pro, Pro Highspeed and K2.8 Preview use `low`, `high`, `max`. The detailed effort table gives `high` for K3.1 and `max` for K2.8. | K3.1 rejects Off. K2.8 retains the `kimi-for-coding` ID. The current K2.8 adapters do not send effort. K3.1's 1M context depends on the membership tier. | [Model configuration](https://www.kimi.com/code/docs/en/kimi-code/models.html), [Third-party endpoints](https://www.kimi.com/code/docs/en/) |
| StepFun Chat Completions, Step 5 Preview and Step 3.7 Flash | `low`, `medium`, `high` through `reasoning_effort`. Loushang uses `medium`. | The model pages document the three active effort values. | [Step 5 API model](https://platform.stepfun.ai/docs/en/guides/models/step-5-preview), [Model overview](https://platform.stepfun.ai/docs/en/guides/models/overview) |
| Tencent TokenHub Responses, Hy4 and Hy4 Flash | `high` is the only documented active level and is the default. | Responses accepts `none` or `no_think` for Off. Tencent's Chat examples use `no_think` for the equivalent mode. | [Deep thinking](https://cloud.tencent.com/document/product/1823/131208), [Responses](https://cloud.tencent.com/document/product/1823/133813), [Models](https://cloud.tencent.com/document/product/1823/130051) |
| Volcano Ark Chat Completions, Doubao Seed Evolving and Seed 2.1 Pro/Lite | `low`, `medium`, `high`. Default `high`. | For these models `reasoning_effort` maps `none` to `minimal` (off) and `xhigh`/`max` to `high`. | [Deep thinking](https://docs.volcengine.com/docs/ark/deep-thinking?lang=zh), [Models](https://docs.volcengine.com/docs/ark/model-list?lang=zh) |
| Z.ai Chat Completions, GLM-5.3, Flash and FlashX | `low`, `high`, `max`. Default `max`. | Uses `reasoning_effort` with thinking enabled by default. Disabling thinking is rejected. | [API reference](https://docs.z.ai/api-reference/llm/chat-completion), [Models](https://docs.z.ai/guides/overview/overview), [Pricing](https://docs.z.ai/guides/overview/pricing) |
| Baidu Qianfan Chat Completions, ERNIE 5.1, 5.5 Flash Preview and Light DT 1.0 | Flash Preview is fixed at `high`. Light DT accepts `low`, `high`, `max` and defaults to `max`. The 5.1 tiers are unconfirmed. | Flash Preview always thinks. Light DT supports `thinking.type` for Off and `reasoning_effort` for depth. | [API reference](https://cloud.baidu.com/doc/qianfan-api/s/wmwbl48n4), [Model list](https://intl.cloud.baidu.com/en/doc/qianfan/s/7m95lyy43-intl-en), [Preview announcement](https://cloud.baidu.com/product/qianfan_home/model_3.html) |

## Implications for the model picker

- Use the effective choices for each model and endpoint. Several requested
  values can lead to the same provider behavior.
- Model Off separately from depth. Hy4 has one active level, Doubao maps
  `minimal` to Off, and GPT-6.2, Kimi K3.1, MiniMax M3.1 Flash and GLM-5.3
  require thinking. Anthropic's `between_tools` has distinct semantics.
- The generic agent vocabulary ends at `xhigh`. Providers with both native
  `xhigh` and native `max` lose a selectable tier in the agent picker.
  Providers with only `max` at the top can project it through generic
  `xhigh`. The catalog preserves the full documented set for a later UI change.
- `capabilities.reasoningEfforts` records effective levels and the endpoint's
  native Off value where applicable. An absent field means the exact set is
  unconfirmed. An empty list means the route offers no adjustable effort.
  Catalog metadata alone does not make an adapter send a provider control.

Static prices are per million tokens. For tiered pricing, the catalog carries a
single documented rate, such as the short-context tier for GPT-6.2 and Claude
Haiku 5.5. DeepSeek Flash uses peak rates. Account eligibility, input length,
time of day, caching and service tier can affect the billed rate.

## Workspaces that select a removed ID

To continue on a current model, select its full reference with `--model` or
the session model picker. For example, the public OpenAI replacement for
`openai:openai-responses:gpt-5.5` is
`openai:openai-responses:gpt-6.2-sol`. For the retired DeepSeek Flash alias, use
`deepseek:openai-completions:deepseek-flash`.

To preserve an exact model reference while its provider still serves it, add
the old model entry to a JSON catalog under `~/.loushang/models/` or the
project's `.loushang/models/`. Use the provider and endpoint metadata from the
current catalog and include only the old model under that endpoint's
`models` object. Use its model-level `adapter` override for any request options
that differ from the current endpoint defaults. This keeps the saved model ID
resolvable, including for sessions with a provider-specific checkpoint.
