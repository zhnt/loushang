# Loushang

[English](./README.md) | 中文

Loushang 是一个把复杂工作变成可运行流程的智能工作系统。

当前重点是 `loushang code`：面向软件研发的 CLI 与终端工作台，支持模型路由、持久会话、工具执行、扩展机制和方法化交付。

## 为什么需要 Loushang

现代 AI Agent 已经能够规划和执行，但复杂工作真正困难的地方往往不是“模型不够聪明”，而是上下文容易丢失、执行过程难以恢复、工具调用缺少治理、结果缺少验收与交付闭环。

Loushang 将方法、阶段、角色、工具、会话和工作产物作为可运行对象来组织。它的目标不是只让 Agent 更聪明，而是让复杂工作更可靠、可恢复、可审计、可验证、可交付。

Loushang 以 method 为工作契约、以 work 为运行事实、以 agent 为运行内核、以 ai 为模型接入、以 harness 为跨产品 substrate、以 coding 为 V1 产品形态、以 tui 为终端呈现、以 channel 为边界协议，最终把复杂知识工作组织成可运行、可恢复、可验证、可演化的系统。

## 现在可以使用什么

- `loushang code`：面向软件研发的 CLI 与终端工作台。
- `loushang.ai`：支持 provider、模型注册、流式输出、工具调用和成本估算的 AI SDK。
- 会话：支持持久化、恢复、分叉、导出和诊断的 coding session。
- 工具：内置 coding 工具与可配置工具面。
- 扩展：支持项目级 extension hooks、自定义工具、动态资源、命令和 flags。
- 方法与技能：支持方法引导的 coding turn 和可复用工作流资产。

## 快速开始

Loushang 目前处于早期开发阶段。推荐从源码运行。

首次在线运行前，请配置所选模型的凭证；[快速开始](./docs/zh-CN/getting-started/#配置-provider-凭证)说明了 API key 环境变量和 OAuth 路线。

```bash
git clone https://github.com/zhnt/loushang.git
cd loushang

uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

loushang --help
loushang --list-models
loushang --list-commands
loushang -p "Inspect this repository and summarize what it does."
```

也可以运行 `make bootstrap`；它会用 `uv` 创建 `.venv/` 并以 editable development mode 安装项目。当前 Makefile 没有 `make install` 目标；本地开发使用 `make bootstrap`，本地二进制安装使用 `make install-binary`。

在本仓库做本地开发时，请使用项目虚拟环境 `.venv/`。

## 核心概念

- 方法：面向一类工作的结构化工作契约，定义角色、阶段、流程、约束、工作产物与验收预期。
- 会话：可恢复、可分叉、可导出、可检查的 coding 对话与执行记录。
- 工具：在策略约束下提供给 agent 的可执行能力。
- 扩展：项目级 Python 代码，可贡献 hooks、工具、资源、命令和 flags。
- 模型 provider：通过模型 catalog 解析的具体 AI provider endpoint 与模型。

## 文档

- [文档首页](./docs/zh-CN/)
- [快速开始](./docs/zh-CN/getting-started/)
- [使用手册](./docs/zh-CN/user-guide/)
- [核心概念](./docs/zh-CN/concepts/)
- [AI SDK](./docs/zh-CN/sdk/)
- [示例](./docs/zh-CN/examples/)
- [参考手册](./docs/zh-CN/reference/)

## 示例

- [Coding 示例](./examples/coding/) 展示 CLI、session、tool、extension 等场景。
- [AI SDK 示例](./examples/ai/) 展示模型查询、完整返回、流式输出、工具调用和显式类型上下文。

## 路线图

- V1：以 `loushang code` 作为软件研发工作的主产品面。
- V2：以 `loushang work` 作为个人复杂工作工作台，`code`、`research`、`ppt` 作为专业执行流。
- V3：daemon、方法市场与模型网关基础设施。
- V4：团队工作流、共享 runs、审批、预算与审计。
- V5：面向方法绑定复杂工作的 managed runtime。

## 项目状态

Loushang 目前处于早期活跃开发阶段。

当前稳定建设重点是 `loushang code` 以及底层 `loushang.ai` SDK。更广义的 `loushang work`、`loushang research`、`loushang ppt` 属于路线图中的产品方向，应视为持续演进中的能力。

## 联系

Loushang 由周恒发起；周恒长期从事低代码、工作流、数据库、模型驱动、DSL、架构方法、系统工程与人工智能相关工作，致力于将本体论与方法论运行化，构建面向复杂工作交付的基础设施。

问题反馈、交流合作或加入交流群，可以联系：zhnt@foxmail.com。

## 致谢

Loushang 借鉴了 OpenAI Codex、pi、python-prompt-toolkit、browser-use、Kimi CLI、superpowers、gstack、openclaw、hermes-agent 等项目公开的设计与工程经验。这些项目是参考与灵感来源；除 `THIRD_PARTY_NOTICES.md` 中列出的依赖外，本仓库不包含或再分发其代码。

## 许可证

Loushang 默认遵循 Apache License 2.0，除非文件中另有说明。

再分发源码、二进制包、文档或修改版本时，请保留 `LICENSE` 与 `NOTICE`，并在产品文档、About/Credits 页面或同等第三方声明位置保留归属信息。

第三方依赖信息见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。
