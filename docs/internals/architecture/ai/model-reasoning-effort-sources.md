# Model reasoning effort catalog sources

Checked on 2026-10-24; Terra and DeepSeek Flash checked on 2026-10-27.
`models.json` records native effort values in
`capabilities.reasoningEfforts`. It omits the field when the provider's available
levels were not established from its own documentation. An empty list records a
confirmed lack of adjustable effort; it does not mean the model cannot reason.
This catalog is static and must be reviewed when a provider changes a model ID,
alias, or protocol behavior.

| Catalog models | Provider evidence |
| --- | --- |
| OpenAI `gpt-5.5`, `gpt-5.4-mini` | [GPT-5.5](https://developers.openai.com/api/docs/models/gpt-5.5), [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) |
| OpenAI `gpt-6-sol`, `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-luna` | [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol), [GPT-6 deployment checklist](https://developers.openai.com/api/docs/guides/deployment-checklist) |
| OpenAI `gpt-6.1-terra` | [GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra) |
| DeepSeek `deepseek-flash`, legacy `deepseek-v4-flash`, and `deepseek-v4-pro` | [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/), [models response](https://api-docs.deepseek.com/api/list-models/), [vision](https://api-docs.deepseek.com/guides/vision/) |
| Kimi Code `kimi-for-coding` and `k3` | [Model configuration](https://www.kimi.com/code/docs/en/kimi-code/models) |
| Kimi Code `k3.1-pro` and `k3.1-pro-highspeed` | [Model configuration](https://www.kimi.com/code/docs/en/kimi-code/models) |
| Kimi API `kimi-k3` | [Model selection](https://www.kimi.ai/help/kimi-api/api-model-selection) |
| Kimi API `kimi-k3.1-pro` and `kimi-k3.1-pro-highspeed` | [Model list](https://platform.kimi.ai/docs/models), [reasoning effort](https://platform.kimi.ai/docs/guide/use-reasoning-effort) |
| Claude Fable 5, Opus 5, Sonnet 5, Haiku 4.5 | [Effort compatibility](https://platform.claude.com/docs/en/build-with-claude/effort), [Haiku 4.5](https://platform.claude.com/docs/en/models/haiku-4-5/overview) |
| Step 3.7 Flash | [Model overview](https://platform.stepfun.ai/docs/en/guides/models/overview) |
| Tencent Hy3 | [TokenHub reasoning controls](https://cloud.tencent.com/document/product/1823/131905), [Responses effort field](https://intl.cloud.tencent.com/zh/document/product/1300/82346); `medium` maps to the effective `low` tier |

These entries describe provider capabilities, not the levels currently accepted
by `ReasoningOptions` or sent by every adapter. Kimi Code's `kimi-for-coding`
route and the Kimi API `kimi-k3` route still suppress effort in their adapter
settings. A later `/model` implementation must reconcile those routes and the
application-level effort vocabulary before exposing a selection as runnable.

DeepSeek Flash prices in `models.json` use the provider's peak rates because
the catalog supports one static rate per token type. Actual off-peak billing is
lower; see [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/).
