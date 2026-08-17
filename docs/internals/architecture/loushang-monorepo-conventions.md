# Loushang Monorepo Conventions

## Scope

本文档定义 `loushang` 在 monorepo、Python 源码目录、import namespace 与仓库级开发环境上的约定。

本文档主要回答：

- 仓库顶层目录如何组织
- 子系统代码应如何落到仓库中
- Python import namespace 如何统一
- 子系统之间的代码依赖如何表达
- Cursor / VS Code 如何稳定识别跨子系统依赖
- 当前阶段是否需要 `packages/*`

本文档不讨论：

- 某个具体子系统的内部组件设计
- CI 平台细节
- 发布流水线细节
- Docker / 部署形态

---

## Design Goals

当前 monorepo 规范优先满足以下目标：

1. 保持一个统一仓库，不提前拆多 repo
2. 子系统代码边界清楚，但不过早引入多 package 管理复杂度
3. Python import 路径与架构子系统命名保持一致
4. 在 Cursor / VS Code 中能稳定完成跳转、类型检查、测试与运行
5. 根级开发命令简单直接
6. `agent -> ai` 这类依赖可以自然 import，而不是依赖临时路径技巧

---

## Core Decision

当前阶段建议采用：

- 单一 git monorepo
- 单一根 Python project
- 根 `src/` layout
- 统一 namespace import
- 统一 workspace virtualenv
- 根 `Makefile` 作为主要开发入口

这意味着：

- 当前阶段不采用 `packages/ai`、`packages/agent` 这种多 package 组织
- 当前阶段不要求为每个子系统建立独立 `pyproject.toml`
- 当前阶段不依赖多个 editable install 来连接子系统

---

## Repository Layout

当前建议的仓库结构为：

```text
loushang/
  Makefile
  pyproject.toml
  docs/
  examples/
    ai/
  src/
    loushang/
      ai/
      agent/
      coding/
      method/
      tui/
      work/
      foundation/
        json.py
        observability/
      ontology/
  tests/
    ai/
    agent/
    coding/
    method/
    tui/
    work/
  scripts/
  spikes/
  .venv/
```

约定如下：

- `docs/`
  - 架构、术语、策略、方法、验证文档
- `src/`
  - 当前阶段的统一 Python 源码根
- `examples/`
  - 面向开发者的可运行参考示例，优先展示 public API 的最小用法
- `tests/`
  - 仓库级测试目录，可按子系统分组
- `scripts/`
  - 仓库级辅助脚本，不承担主要示例职责
- `spikes/`
  - 实验代码与验证材料
- `.venv/`
  - 根工作区统一开发虚拟环境

---

## Why Not `packages/*` Right Now

`packages/*` 不是错误方案，但对当前阶段偏重。

当前不采用它，主要因为：

1. 子系统边界虽然已设计清楚，但工程落点仍在快速收敛
2. 现在更需要快速开始实现，而不是先承担多 package 管理复杂度
3. 单一根 project 已足够支持：
   - `loushang.ai`
   - `loushang.agent`
   - `loushang.coding`
   - `loushang.method`
   - `loushang.work`
   - `loushang.tui`
4. 未来若确实需要独立发布或独立依赖管理，仍可再升级到 `packages/*`

因此当前更稳的路线是：

- 先用 `src/loushang/<subsystem>`
- 后续如有必要，再演进到多 package 结构

---

## Naming Rules

需要区分三类名字：

### 1. Architecture Subsystem Name

用于文档与架构讨论：

- `loushang-ai`
- `loushang-agent`
- `loushang-coding`
- `loushang-method`
- `loushang-work`
- `loushang-tui`

`loushang-channel` 是保留的目标架构子系统名；在 `src/loushang/channel/`
落地前，不应把它写成当前源码目录。

### 2. Python Import Namespace

用于 Python import：

- `loushang.ai`
- `loushang.agent`
- `loushang.coding`
- `loushang.method`
- `loushang.work`
- `loushang.tui`

`loushang.channel` 只有在 package-level channel implementation 落地后才进入
当前 import namespace 清单。

即：

- import namespace 使用 `loushang.<subsystem>`

因此不建议采用：

- `loushang_ai`
- `loushang_agent`

因为这会削弱子系统结构与代码导入路径的一致性。

### 3. Future Distribution Name

如果未来需要独立发布，再讨论 distribution name：

- `loushang-ai`
- `loushang-agent`
- `loushang-coding`
- `loushang-method`
- `loushang-work`

但这不是当前阶段必须先冻结的物理边界。

---

## Namespace Rule

当前建议所有 Python 子系统统一挂在 `loushang` namespace 下。

例如：

```text
src/loushang/ai/
src/loushang/agent/
src/loushang/coding/
src/loushang/method/
src/loushang/work/
src/loushang/tui/
```

这样做的价值是：

1. 文档、架构、实现三层命名一致
2. 子系统之间的关系更直观
3. 后续新增子系统时不需要再发明新的顶层 import 名

如果采用这套结构，则子系统代码应支持：

```python
from loushang.ai import stream
from loushang.agent import Agent
```

---

## Single Repo Rule

当前阶段不建议为每个子系统建立独立 git repo。

理由：

1. 子系统边界仍在持续收敛
2. 架构、协议与类型仍在联动演进
3. 跨子系统改动频繁，多 repo 会显著增加协调成本
4. 当前更需要统一设计和统一演进，而不是仓库级隔离

---

## Cross-Subsystem Dependency Rule

当前阶段，子系统之间的依赖首先是源码级依赖，而不是 package-level dependency。

例如：

- `agent` 依赖 `ai`

在代码中直接表现为：

```python
from loushang.ai import complete
from loushang.ai.types import AssistantMessage
```

这类依赖通过以下条件稳定成立：

1. 统一根 `pyproject.toml`
2. 统一根 `src/` layout
3. 编辑器与命令都运行在同一个根 `.venv`

当前阶段不需要：

- 为 `agent` 单独声明对 `loushang-ai` 的 package dependency
- 多个 editable install

---

## Workspace Virtualenv Rule

当前建议在仓库根目录维护一个统一开发环境：

- `/home/dev/workspace/loushang/.venv`

这样做的价值是：

1. Cursor / VS Code 只需选择一个解释器
2. 跨子系统 import 解析更稳定
3. pytest / lint / type checking 不会在不同环境之间漂移

---

## Installation Rule

当前阶段建议：

- 创建根 `.venv`
- 将整个仓库根 project 安装为开发态项目
- 所有子系统都通过同一个安装态和同一个 `src/` 目录被解析

这里不再要求：

- `uv pip install -e packages/ai`
- `uv pip install -e packages/agent`

因为当前没有多个独立 package。

---

## Cursor / VS Code Rule

在 Cursor / VS Code 中，推荐工作方式是：

1. 打开 monorepo 根目录
2. 选择根 `.venv` 作为 Python interpreter
3. 确保根 project 已安装到该环境

这样可以同时保证：

- import resolve
- go-to-definition
- type checking
- pytest 运行
- 本地调试

因此，编辑器可用性的关键在于：

- 根 `src/` layout
- 根 `.venv`
- 统一解释器

而不是：

- 多 repo
- 多 package editable install
- 编辑器私有路径技巧

---

## Makefile Rule

当前阶段建议以根 `Makefile` 为主，不强制每个子系统都有自己的 `Makefile`。

根 `Makefile` 负责：

- `bootstrap`
- `test`
- `lint`
- `fmt`
- `typecheck`
- `test-ai`
- `test-agent`
- `lint-ai`
- `fmt-ai`
- `typecheck-ai`

这样能在不引入多 package 复杂度的前提下，保留按子系统执行命令的便利性。

当前阶段不强制要求：

- `src/loushang/ai/Makefile`
- `src/loushang/agent/Makefile`

如果后续某个子系统内部命令复杂度显著上升，再讨论是否补局部命令入口。

---

## Recommended Initial Commands

后续仓库级命令建议至少统一出这些入口：

- `make bootstrap`
- `make test`
- `make lint`
- `make fmt`
- `make typecheck`
- `make test-ai`
- `make test-agent`
- `make lint-ai`
- `make fmt-ai`
- `make typecheck-ai`

---

## What This Means For Loushang-AI

这份规范对 `loushang-ai` 的直接约束是：

1. `ai` 的代码应落在：
   - `src/loushang/ai/`
2. `ai` 的 import 路径应是：
   - `loushang.ai`
3. `ai` 的测试建议落在：
   - `tests/ai/`
4. `ai` 的开发命令应通过根 `Makefile` 暴露，例如：
   - `make test-ai`
   - `make lint-ai`
5. `agent` 对 `ai` 的引用应直接通过：
   - `from loushang.ai import ...`

因此，`loushang-ai` 的实现计划必须与这份仓库规范对齐，而不能继续假设 `packages/ai` 的物理布局。

---

## Deferred Decisions

本文档暂不冻结以下细节：

- 是否统一使用 `uv`
- 是否统一使用 `ruff`
- 是否统一使用 `mypy`
- 将来是否需要从单一根 project 演进为多 package
- CI 的实际实现方式

这些更适合在 dev workflow / tooling 文档中继续明确。

---

## Takeaway

当前更稳的 `loushang` Python monorepo 组织方式是：

- 一个 git repo
- 一个根 Python project
- `src/` 作为统一源码根
- import namespace 统一为 `loushang.<subsystem>`
- 根 `.venv` 作为本地开发环境
- 根 `Makefile` 作为主要命令入口

这样既能保持子系统边界清楚，又能降低当前实现启动成本。
