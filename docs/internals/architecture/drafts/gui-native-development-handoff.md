# GUI 原生开发交接：Windows / macOS

## Status

- ID: `GUI-NATIVE-HANDOFF-V1`
- Authority: descriptive — implementation handoff for proposed GUI design
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang GUI delivery owner
- Baseline: main `9bc69361`, checked 2026-09-09
- Delivery branch: `docs/gui-native-handoff`

本分支提供可通过 GitHub 获取的 GUI 需求、黑盒设计和工程启动方案。尚无 GUI
工程、Rust/Node 锁文件或已验证的原生 playback 命令；接手机器负责完成后续
组件设计、工程初始化和原生实现。主开发机器选择 Windows 或 macOS，Linux
继续保留支持与验证范围。设计状态仍为 proposed，不能把交接当作运行验收。

## 1. 获取与阅读顺序

新机器可使用 GitHub 上的仓库地址克隆，以下命令可逐行在 PowerShell 或 macOS
终端运行；已有 checkout 应先保存改动，不覆盖既有同名本地分支。

```text
git clone https://github.com/zhnt/loushang.git
cd loushang
git fetch origin docs/gui-native-handoff
git switch --track origin/docs/gui-native-handoff
```

如分支已经合入 main，获取包含该交付的最新 main 即可。开始实施时从选定设计
基线创建具名任务分支；记录实际 commit，后续平台报告引用同一构建来源。

按以下顺序阅读，不依赖其他机器未提交的笔记或文件：

1. 仓库根 [AGENTS.md](../../../../AGENTS.md) 与
   [已提交架构方法](../../architecture-method/README.md)。lane 的物理路径适配
   本机 checkout；不要把文档中的 Linux 开发者绝对路径当作 Windows/macOS 路径。
2. [GUI 需求](gui-requirements.md)：首期需求、质量约束、后续候选和待定项。
3. [系统上下文与边界合同](gui-system-context-and-boundary-contract.md)：权限、状态、
   服务接口与执行寿命；§8 是验收设计，尚无对应 GUI 测试实现。
4. [工程启动方案](gui-engineering-bootstrap-plan.md)：§2.1 的服务端就绪复核、
   §4.2 的原生主开发安排、B0/B1/C1/B2/B3 的阶段退出条件。
5. [工程方案评审](gui-engineering-bootstrap-review.md)：只作为启动方案评审证据，
   不代表后续补充需求、边界或实现已通过独立评审。

## 2. 可以依赖的服务端基线

| 能力 | 交接时状态 | 接手规则 |
| --- | --- | --- |
| G16 同机认证连接、会话快照/事件、审批、中断、可分离运行 | 已在 main | 可按现有 `local-detachable/v1` 做真实接入；`start_turn` 正常完成后返回 Ack，期间事件/控制仍须并行 |
| G17 有界 cwd/home 会话候选发现 | 已在 main；[验收记录](../apphost/hosted-session-workflow-g17-acceptance-record.md) | 可选能力，须显式采用 discovery profile；C1 接入设计先更新对应约束，不在旧 profile 上猜测支持 |
| execution ID、提交去重、执行查询的新服务合同 | [#576](https://github.com/zhnt/loushang/issues/576) 仅完成底层可选 Product 合同增量，整体尚未交付 | 不要求接手机器获取该本地分支，不以未来 API 阻塞 Mock GUI；真实启用须等待已合并、可验证的服务交付 |
| 完整富产物、轮次/条目关联、行级反馈 | 后续候选 | 允许明确标记的展示样例，不能宣称真实协议接通 |

本文是时间点交接记录；真实接入前复核 main、服务 capability/profile 与当前 CI。
既有服务器原生验收不证明 GUI WebView、Rust IPC 或输入法已经可用。

## 3. 接手机器的第一项交付

先记录主开发 OS/版本/CPU、图形会话和 checkout；按架构方法完成候选功能→
候选组件→映射→收敛，再确定前端状态与 Rust 接口。首期播放器面板、系统基线
和容量指标按 GUI-OQ-001/002/003 明确决策，不把未知项默认为已验收。

工程初始化放在真实 Windows/macOS 桌面上，从最小切片建立持续回放：

1. 初始化独立 Tauri/Rust + React/TypeScript 工程，固定工具与依赖版本，提交
   对应锁文件；提供 Windows 原生可用的跨平台入口。
2. 无 Python 服务也能启动有明确样例标识的原生 GUI；不请求真实模型。
3. 建立一条“输入→流式输出→中断→文档阅读”的可重复场景，逐步断言状态，
   输出失败步骤与截图。至少一条 canary 实际经过 Rust IPC，不能全部替换为
   浏览器 Mock。具体 driver 在所选机器验证后固定。
4. 双会话草稿、未读/待回答、文档阅读位置与断线状态加入后续回放切片；IME、
   系统剪贴板、焦点与缩放做真实桌面检查，不能用 DOM 注入代替。
5. C1 固定跨语言值合同及行为向量后，GUI 连接本机 Python 服务；先验收已交付
   能力，新 execution 接口按其后续交付单独接入。

这份首轮清单用于安排切片，不取代需求文档中的全部阶段验收。另一个桌面平台
和 Linux 仍按 B0–B3 提供各自证据。源码、fixtures 和锁文件经 GitHub 同步；
凭据、Session 数据、虚拟环境、node_modules、target 和测试运行产物留在本机。

## 4. 变更与验证范围

普通文档只做轻量文档检查；GUI 工程建立时补充 GUI 的 change-aware 选路，
避免新目录落入 unknown-path 全量门禁。GUI 状态/布局改动运行对应 GUI 检查；
跨语言协议改动才增加相应服务契约检查。必需原生场景缺环境、跳过或零场景都
不能计为通过，但不为一次 GUI 迭代重复运行无关 Python 包。

当前交付没有安装、启动或远程连接接手机器，也不包含服务端未完成增量。
本分支可直接用于阅读、设计和建立后续实施任务，无需等待执行 ID 服务完成。
