# 现有全部测试与 PR 门禁盘点
- 盘点日期：2026-10-14。
- 源码基线：远端 `main` 的 `ed01d756b0b043cbca2a4352f847118205038adc`；当前控制工作区保留本地合并历史。
- 基线范围：16 个工作流、71 个源 job 定义，包含顶层调用与子汇总；不是某次运行的任务数。平台矩阵、动态模块/分片会展开，不能将源定义数当运行数。
- 当前实现：删除重复的 `package-quality` 及顶层 `packages` 调用，把 AppService 八个历史阶段 job 重组为两个能力 job，删除十个 reusable 内部 `selected-checks` runner，并合并 TUI 与 HarnessTUI 的同环境 job 后，为 15 个工作流、48 个源 job 定义；Agent/Coding/Foundation/AppService/AppServer 离线回归由统一模块工作流唯一执行。PR #746 全选运行 `38563194640` 实际展开 50 个 job，其中 43 个成功、7 个按计划跳过、零失败；该运行早于最近两次 job 合并，源定义数与一次运行展开数继续分开统计。
- 状态：本轮全量历史 job 分析、现有活动门禁重组及 15 分钟验收已完成；当前 15 个 workflow、48 个源 job 已复核。所有顶层测试代码目录均有角色、重复与成本初审记录，其中仍属增量审计或缺少活动执行 owner 的精确 node、平台与夹具归属保留为 AP-01 至 AP-11，未经审批不迁移或补接。
- 综合方案：[重构与优化测试与 PR 门禁](test-and-pr-gate-refactoring-plan.md)。实施 goal 已启动；表格保留基线职责并在已迁移项上标明当前处置。
## 审查规则

每个 job 都分析目的、必要断言、重复覆盖、执行配置、时间、触发、报告消费者及迁移去向。相同文件清单仅是重复候选，须比较最终 node ID、marker、平台、安装形态和运行参数；不同配置的独有断言不可直接删。未实测项注明待测。

当前暂停的六类工作流保留暂停。所有汇总校验也纳入合并审查：root 只看到 reusable workflow 总结果时，不能直接删子汇总。只有新机制可观察并拒绝预期子 job、矩阵或必需用例缺失/跳过时，才允许替代旧 selected-checks。

任何 PR 门禁增加都必须先取得审批方明确批准。增加包括新增 required
check/workflow/job/test route/平台或矩阵，扩大路径触发，恢复暂停门禁，把
schedule/nonblocking 覆盖移入阻塞 PR 路径，以及新增失败条件。一般性的“优化、
重构、加速门禁”授权不能替代本项审批。审批材料至少列出触发范围、唯一断言、
平台、预计墙钟、与现有覆盖的重叠、失败语义和回退方法；批准记录应关联具体
方案或提交。只读盘点和方案编写可继续。覆盖等价的路由调整如果让任何变更类别
多执行任务或新增失败条件，也按门禁增加处理。

当前实现已统一为一个必需的顶层 `quality-gate`。所有 reusable job 都直接绑定选择计划的 `checks` 或 `windows` boolean；CI 合同核对每个 job ID、所属 workflow scope 和 guard，动态模块/E2E 另有专用完整性合同。GitHub 将任一 matrix/job 的失败或取消传播到 reusable caller，顶层 verifier 要求所选 caller success、未选 caller skipped，并拒绝 missing、failed、cancelled 和 unexpected skip。原十个 `selected-checks` 只重复启动 runner 读取 `needs`，现已删除；表格中的同名行保留为基线审计记录。

## 全部工作流与 job

### ai-quality.yml

工作流来源：[ai-quality.yml](../../../.github/workflows/ai-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `install-compatibility` | 依赖安装兼容；Linux/macOS 架构矩阵 | 依赖准备与其他任务部分重复，但架构验证独有 | 拆分并按依赖/打包触发 | 安装专项 |
| `ai-quality` | AI lint、类型、离线回归及覆盖率 | 与 unit_ai 有范围交叉；不得丢现有覆盖率 | 合并唯一模块执行 | AI 模块/合同 |
| `selected-checks` | AI 与安装结果/跳过校验 | 独立 runner 汇总成本 | 校验合入统一结果路径，替代前保留 | 防误绿汇总 |

### apphost-quality.yml

工作流来源：[apphost-quality.yml](../../../.github/workflows/apphost-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `apphost-quality` | Linux AppHost/服务回归与 G8/G9/G10 证据 | 同文件在主回归与证据阶段重跑，跨 AppService 重叠 | 拆分模块/真实服务专项；证据派生 | AppHost 模块、IPC/生命周期 |
| `apphost-windows-native-gate` | Windows 原生/连续性与产品组合 | 混合合同与平台真实链路 | 纯合同归模块；独有原生归平台专项 | Windows 所有权/连续性 |
| `selected-checks` | AppHost 两类执行结果校验 | 独立汇总 runner | 合并校验职责，不能丢 Windows 缺失检查 | 防误绿汇总 |

### appservice-quality.yml

工作流来源：[appservice-quality.yml](../../../.github/workflows/appservice-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `g17-darwin-native` | macOS 真实 CLI/终端观测流程 | 历史阶段 job；与安装、终端族需逐 node 核对 | 删除旧 job；迁移独有断言 | macOS 平台/终端专项 |
| `g17-darwin-primitives` | macOS 原生观测基本操作 | 与高层族使用同一平台准备环境 | 删除旧 job；便宜合同与原生基本操作分归属 | 模块合同或 macOS 平台 |
| `g17-wheel-evidence` | 三平台安装后终端/服务证据族 | 各族重复准备与实际链路可能交叉 | 删除阶段矩阵；一次构建按安装风险选族 | 安装及对应平台专项 |
| `g17-windows-native` | Windows console、故障观测与退出 | 历史阶段 job；与 ConPTY/原生补充需核对 | 删除旧 job；保留唯一 Windows 断言 | Windows 终端/所有权专项 |
| `appservice-quality` | 三平台服务回归；Windows 全量或短场景 | 与 AppHost/模块替代有目录重叠，曾长耗时 | 模块一次执行；真实请求按平台/能力选择 | AppService/AppServer 模块、认证/IPC |
| `g16-native-evidence` | 三平台真实 mux/终端故障场景 | 历史分组与 G17 有能力交叉，不等于全同 | 删除旧 job；按断言归终端/服务/故障 | 原生与故障专项 |
| `g16-wheel-evidence` | 三平台安装后 mux/终端链路 | 安装构建与 G17 wheel 可共享，状态不可共用 | 删除旧 job；复用产物后选必要用例 | 安装及原生专项 |
| `selected-checks` | 所有阶段与矩阵完整性校验 | 旧阶段映射必须迁移 | 删除历史聚合；新结果校验覆盖矩阵缺失 | 防误绿汇总 |

当前实现以 `native-service` 和 `installed-service` 取代上述八个 job。Native 三平台各只安装依赖一次，macOS 在同一 runner 完成 mux、observation 与 primitives；Windows 普通路径只跑两项短冒烟，风险路径保留完整 native manifests。Installed 每个平台只构建一次 wheel，再在隔离环境分别消费现有 mux 与 hosted manifests。复用工作流的两个 job 与 caller 使用相同 `checks.appservice` 条件，结果由唯一顶层 `quality-gate` 聚合；工作流仍在暂停清单中，installed 全族尚未证明 15 分钟预算前不恢复。

离线目录现已进一步按行为拆分：AppServer 22 个测试文件中 17 个 unit/contract 归统一模块 runner，3 个真实 loopback/stdio/子进程文件归 integration，2 个原生文件归 platform；AppService 16 个文件中 14 个 unit/contract 归模块 runner，真实 loopback 部署归 integration，跨进程 continuity 存储归 platform。分类清单要求目录完整，新增文件未登记会失败；integration/platform 文件及其专用夹具不会被 test-only 短路径误认为单元测试。Linux 本地证据为两个模块短路径分别 825 项/13.18 秒、224 项/4.77 秒，专项集合 75 项通过、10 项 Windows 条件跳过/6.47 秒。

被修改的 integration/platform 文件现在由 module workflow 的独立 targeted matrix 直接执行，而不是假设暂停的能力 workflow 会覆盖它。目录为每个 targeted owner 声明受限 runner；夹具变更解析到登记消费者；空矩阵由显式 plan boolean 跳过。报告必须非空、无失败/错误，integration 不允许 skip，platform 允许条件 skip 但至少有一项通过。live 类别保留显式外部验证，不进入 PR 自动调用。

### architecture-quality.yml

工作流来源：[architecture-quality.yml](../../../.github/workflows/architecture-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `source-facts` | 源依赖事实与架构工具检查 | 独立环境准备大于纯静态扫描成本 | 保留必要事实，可合入轻量检查 | 源码静态检查 |

### coding-lsp-compatibility.yml

工作流来源：[coding-lsp-compatibility.yml](../../../.github/workflows/coding-lsp-compatibility.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `pyright-live` | 真实 Pyright LSP 通信 | 通用协议与语言特有行为分离 | 按 Pyright/协议路径选择 | LSP 集成 |
| `typescript-live` | 真实 TypeScript server 通信 | Node 安装准备可与同环境复用 | 按 TS/协议路径选择 | LSP 集成 |
| `gopls-live` | 真实 gopls 通信 | 工具下载/构建准备可缓存 | 按 Go/协议路径选择 | LSP 集成 |
| `rust-analyzer-live` | 真实 rust-analyzer 通信 | 工具链准备可缓存，语言断言独有 | 按 Rust/协议路径选择 | LSP 集成 |
| `selected-checks` | 已选语言任务结果校验 | 独立汇总 runner | 保留语种完整性再合并校验路径 | 防误绿汇总 |

### e2e-smoke-quality.yml

工作流来源：[e2e-smoke-quality.yml](../../../.github/workflows/e2e-smoke-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `resume-turn` | 三平台核心 A/B；macOS 另有两条资源变化 Resume | macOS 补充不自动认为被 A 覆盖；同环境可复用 | 保留 A/B；资源变化用例按能力路径选择 | 核心冒烟及恢复专项 |

### harness-quality.yml

工作流来源：[harness-quality.yml](../../../.github/workflows/harness-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `linux-harness` | Linux 隔离/合同/C5 证据后完整 Harness 回归 | 部分合同/文件再次在主回归执行；组合曾长耗时 | 删除组合历史门禁；模块一次、独有隔离专项 | Harness 模块与 Linux 原生 |
| `macos-exec` | macOS 实际 exec 合同 | 平台断言需与其他 exec 用例核对 | 按执行/平台路径并入对应能力组 | macOS exec 专项 |
| `selected-checks` | Linux 与 macOS 结果校验 | 独立汇总 runner | 完整性职责迁入统一结果路径 | 防误绿汇总 |

### harnesstui-quality.yml

工作流来源：[harnesstui-quality.yml](../../../.github/workflows/harnesstui-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `harnesstui-core` | 共享 UI lint、类型和合同回归 | 与模块/TUI 范围交叉需要 marker/node 核对 | 唯一模块归属，渲染另选 | HarnessTUI 模块 |
| `coding-ui` | Coding UI 适配 lint、类型和回归 | Coding 原回归已有排除所有权，需继续防重 | 保留适配断言并入模块执行 | Coding UI 模块 |
| `selected-checks` | 两个 UI 范围结果校验 | 独立汇总 runner | 校验完整性后合并 | 防误绿汇总 |

当前实现把 `harnesstui-core` 与 `coding-ui` 合并为一个 Ubuntu job，按原有两个
选择 boolean 执行。两项同时选中时使用联合 scope，对去重后的源码/测试并集只启动
一次 Ruff、mypy 和 pytest，并验证、上传联合报告；只选中其中一项时继续执行原 owner
命令与报告。运行实例保持最多 1 个，完整 PR 计划的联合报告计数精确等于原两个报告
并集，测试集合、触发范围和失败语义不变。PR #779 首轮远程 job 为 1 分 32 秒，
较旧双选基线 2 分 24 秒缩短 52 秒。

### host-runtime-quality.yml

工作流来源：[host-runtime-quality.yml](../../../.github/workflows/host-runtime-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `host-runtime-quality` | 跨包 requires_host_runtime 或两条短用例 | 目录收集无清晰能力边界，曾长耗时 | 删除笼统大组，逐用例归具体能力 | 进程/存储/安装专项 |
| `selected-checks` | runtime 执行/跳过校验 | 旧大组映射 | 随旧组迁移，不能遗漏所选专项结果 | 防误绿汇总 |

### hosting-quality.yml

工作流来源：[hosting-quality.yml](../../../.github/workflows/hosting-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `hosting-quality` | 三平台后端/端点/隔离与 Worker 历史合同 | 三平台重复静态检查，跨 Harness 清单相交 | 静态一次；模块一次；原生按后端选择 | Hosting 模块及平台隔离 |
| `worker-p4-ordinary` | Linux 普通 Worker Session；PR 单例或全组 | 安装、会话、fence 混合；与多处 Worker 链路交叉 | 删除阶段组，拆短启动/查询/退出与风险场景 | Worker 原生及专项 |
| `worker-sustained` | 2049 次 Product 查询 | 长循环独有耐久诉求，不必每次 PR 执行 | 移出普通阻塞路径，暂停后审查再安排 | 扩展耐久验证 |
| `selected-checks` | 后端、会话、耐久结果完整性 | 旧组映射 | 能力分组后重建统一校验 | 防误绿汇总 |

### package-quality.yml（已删除）

这是基线中的历史工作流。其四个职责已经迁入统一模块执行与顶层 fail-closed 汇总，当前仓库不再保留该文件。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `agent` | Agent 完整离线回归 | 与 unit_agent 两条执行入口 | 合并唯一模块路径，分离真实集成 | Agent 模块/合同 |
| `coding` | 固定 16 分片完整 Coding 离线集合 | 不是重复分片；集合含真实集成，负载不均 | 删除独立固定分片组；分类后迁统一模块 | Coding 完整单元/合同、按路径集成 |
| `foundation` | Foundation 离线回归 | 与 unit_foundation 两条入口 | 合并唯一模块路径 | Foundation 模块/合同 |
| `selected-checks` | Agent/Coding/Foundation 结果校验 | 矩阵完整性不能仅看回归脚本退出 | 合并时保留分片完整性证明 | 防误绿汇总 |

### package-unit-quality.yml

工作流来源：[package-unit-quality.yml](../../../.github/workflows/package-unit-quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `package` | 动态模块/分片；暂停模块离线替代 | 与多个历史模块工作流范围相交 | 作为统一模块执行基础，分类与静态检查补齐 | 模块回归 |

### quality.yml

工作流来源：[quality.yml](../../../.github/workflows/quality.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `changes` | 选择、文档、CI 合同/语法、main 证据核验 | 多个子任务重复准备，选择输出是权威输入 | 保留统一轻量计划入口 | 选择/轻量检查 |
| `architecture` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | 源码静态检查 |
| `units` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | 模块回归 |
| `e2e` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | 核心冒烟 |
| `ai` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | AI 模块/安装专项 |
| `packages`（已删除） | 调用旧 package-quality | 与 `units` 执行同一 Agent/Coding/Foundation 离线集合 | 删除；选择计划把三类 check 映射到 `units` | 模块回归 |
| `harness` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | Harness 模块/原生专项 |
| `harnesstui` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | UI 模块 |
| `tui` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | TUI 模块/原生专项 |
| `hosting` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | Hosting 模块/原生专项 |
| `apphost` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | AppHost 模块/IPC专项 |
| `appservice` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | AppService 模块/原生/安装专项 |
| `host-runtime` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | 对应能力专项 |
| `windows-shell` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | Windows 平台/风险专项 |
| `worker-reboot` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | 扩展重启验证 |
| `lsp` | 调用对应复用工作流 | 编排入口不是额外测试，保留和子用例的对应关系 | 重组为能力分组入口，不再按历史流程扩展 | LSP 集成 |
| `quality-gate` | 必需汇总和 PR 证据生成 | 职责必要；报告不能与所选全集脱钩 | 保留一个必需入口，证明矩阵/用例完整性 | 最终汇总 |

`changes` 中的路由合同会在同一 Python 进程内生成大量独立变更计划。分类清单的
完整目录核对和 targeted node AST 校验现在对该次不可变 checkout 只执行一次；
临时或其他 root 不缓存，仍支持测试中的增删文件和清单变更验证。该优化不减少
合同断言、路由样本或失败条件。

### tui-render-contract.yml

工作流来源：[tui-render-contract.yml](../../../.github/workflows/tui-render-contract.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `tui-unit` | TUI 离线单元 | 与 unit_tui 入口相交 | 统一模块执行，纯单元全集保留 | TUI 模块 |
| `deterministic-render` | Linux/Windows 渲染与回放 | 共享算法可在模块验证；平台输出差异需独有依据 | 共享一次，平台特有输出按路径验证 | 渲染合同/平台 |
| `terminal-platform-unit` | Linux/Windows 终端平台机制 | 共享部分重复跑，与 native 并非完全同义 | 共享合同一次，平台机制对应平台 | 终端合同/平台 |
| `native-terminal` | POSIX PTY/Windows ConPTY 原生生命周期 | 与 B、G16/G17 有交集但物理恢复独有 | 保留必要短原生集合，逐断言核对去重 | 终端平台冒烟 |
| `tmux-scrollback` | tmux pane/history/scrollback | 独有 tmux 能力，不属于普通 UI 修改 | 仅 tmux/scrollback 路径或专项执行 | tmux 专项 |
| `selected-checks` | 渲染/平台/原生/tmux 所选结果校验 | 多层汇总 runner | 合并时仍拒绝预期平台/用例缺失 | 防误绿汇总 |

当前实现保留 `tui-unit` 和 `deterministic-render`，并把
`terminal-platform-unit`、`native-terminal`、`tmux-scrollback` 合并到按平台展开的
`native-terminal` job。Linux 的 shared/POSIX platform 文件已由必选 `tui-unit` 在
相同环境执行，native job 不再重复 114 个实例，只保留 PTY 与 tmux；Windows 同一
runner 在完整路径执行 shared/Windows 与 ConPTY，普通路径仍只执行原 ConPTY 短冒烟。
活动实例仍为最多 5 个，必要测试身份的执行 owner 唯一化。

### windows-shell-compatibility.yml

工作流来源：[windows-shell-compatibility.yml](../../../.github/workflows/windows-shell-compatibility.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `windows-pr-smoke` | 原生 shell 与普通 Session | 重复 wheel 准备；与终端/服务 smoke 部分交叉 | 拆断言归属；按 shell/普通会话路径选 | Windows 平台冒烟 |
| `windows-worker-pr-query` | 原生 Worker 安装、query、关闭 | 单 query 包装仍调用大型助手，并不短 | 重制小夹具，复用构建，不跳授权校验 | Windows Worker 冒烟 |
| `windows-worker` | 候选 wheel、admission 与原生机制 | 逻辑断言和实际原生混在一起 | 单元/合同归模块；原生归专项 | Worker 模块及平台 |
| `windows-worker-session` | direct/recovery/lifecycle 四个场景组 | direct 含三轮会话；状态与安装重复成本大 | 删除组合矩阵，按失败/生命周期断言重组 | 会话/原生/恢复专项 |
| `windows-worker-gc-normal` | 正常清退、更新与精确 GC | 不同目的串行，曾长耗时 | GC 决策单元，实际删除/更新按风险验证 | GC/更新专项 |
| `windows-worker-gc-crash` | crash 后历史清退与精确 GC | 与 Session crash 恢复需要实际断言核对 | 迁故障专项，合并共有准备保留独有断言 | crash/GC 专项 |
| `windows-shell` | quarantine/journal/manifest/shell/runtime/PowerShell | 多个模块与原生组串行，多处政策断言重叠 | 拆回权限、存储、shell 与平台能力 | 对应模块及 Windows 专项 |
| `selected-checks` | 全量/短场景的所选结果校验 | 旧组合条件复杂 | 重建能力与平台完整性校验再删除旧聚合 | 防误绿汇总 |

### worker-registered-reboot-drill.yml

工作流来源：[worker-registered-reboot-drill.yml](../../../.github/workflows/worker-registered-reboot-drill.yml)。

| 当前 job ID | 验证职责 | 重复与成本关注 | 拟议处置 | 必要覆盖的新归属 |
| --- | --- | --- | --- | --- |
| `isolated-linux-reboot` | QEMU 内真实重启与恢复 | 独有重启诉求，不由进程 crash 替代 | 独立扩展验证，保持暂停直到审查恢复 | 真实重启专项 |
| `selected-checks` | 重启执行结果完整性 | 独立汇总 runner | 扩展验证结果统一报告 | 扩展结果汇总 |

## 全部单元测试的去重范围

工作流去重之外，所有模块的单元与合同用例也逐项审查。以必要行为、输入等价类、错误语义、状态/副作用、平台和生命周期判断重复；允许降低用例数量和重复准备成本，完整执行审查后保留的必要集合。

跨模块共享逻辑由其 owner 保留完整行为测试，消费者保留自己的使用合同。参数化不等于执行去重；不同边界与失败注入阶段仍分别覆盖。维护旧用例到保留集合的映射，未证明可替代的用例先保留。详细规则见综合方案 §3。

## 平台矩阵与执行清单的后续核对

- AI 安装架构、E2E 三平台、TUI 平台/后端、AppService 原生/安装矩阵、Hosting 三平台、Windows Session 四组，逐配置登记，不能在合并后漏掉某个平台。
- units 动态模块、Coding 4 个实测选择分片及 UI 排除、例子、暂停模块替代，核对最终 collection 的并集与交集。
- Makefile 的 source/test 清单、run_checks、专用 runner、报告验证器、历史 evidence manifest，都是消费关系的一部分；工作流层表不是完整用例分类清单。
- 逐项记录“保留、合并、拆分、删除重复、移入专项、继续暂停”的理由及证据，未完成项留在验收缺口中。
- 删除历史 job 和固定 Coding 组时，所有必要断言必须已迁移；删除独立汇总时，所有失败/跳过/缺失约束必须已迁移。

## 当前完成与待完成

已完成：历史基线 16 个工作流、71 个源 job 均有分析条目及拟议新归属；当前实现为
15 个工作流、48 个源 job。重复 `package-quality`、历史 AppService 阶段 job、十个
子汇总、固定 16 个 Coding shard，以及已证明的同平台同配置重复执行已经重组或删除。
全部顶层 pytest 代码目录、显式 typing 合同和根夹具均已进入审计记录。

待审批或继续验证：AP-01 至 AP-11 中的首次执行、route/平台迁移、暂停 workflow
恢复和新增失败条件；增量目录的逐 node 唯一断言与目标平台；暂停原生能力的真实
预算和至少三次有效运行。未经指定审批方批准不实施门禁增加，当前结果也不以工作流
数量变少宣称全仓逐 node 验收已经完成。

本轮终验以方案 R19 为准：现有活动 full 计划在运行 38671220972、38676143469 和
38677731417 分别以 10 分 31 秒、11 分 21 秒和 13 分 35 秒绿色完成；PR #789 最终
head 的必需门禁为 4 分 53 秒。上述待审批项目是未来扩大覆盖面的候选，不阻塞本轮
缩减、去重、重组与时间目标的完成。
