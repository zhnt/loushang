# Loushang GUI 工程启动方案：三视角评审记录

## Status

- ID: `GUI-ENGINEERING-BOOTSTRAP-REVIEW-V1`
- Scope: Loushang proposed graphical client / cross-scope delivery
- Parent: Loushang
- Authority: descriptive — design review evidence; not implementation acceptance
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang architecture / future GUI delivery owner
- Reviewed plan: [GUI 工程启动建设方案](gui-engineering-bootstrap-plan.md)
- Source baseline: `3c06f5b9` on `main`, inspected 2026-09-08
- Review date: 2026-09-08

用户要求编写工程启动方案，并进行三视角评审。本轮仅变更方案、评审记录与
drafts 目录索引；没有建立 GUI 工程、安装工具链或运行桌面验收。

## 1. 评审方式与边界

三位独立评审者读取同一份初稿，并按各自职责查阅仓库源码与正式文档：

| 视角 | 评审者 | 重点 |
| --- | --- | --- |
| 架构与生命周期 | `gui_arch_review` | Product-neutral 边界、G16 语义、跨语言契约、状态恢复、控制权和插件归属 |
| 开发与验证 | `gui_validation_review` | SSH/Linux、原生 driver、GUI playback、确定性、输入路径和性能证据 |
| 交付与维护 | `gui_delivery_review` | 目录/工具链、lane 管理、CI 门禁、里程碑依赖与开发/发布边界 |

初审共发现 9 项：0 项 P0、2 项 P1、7 项 P2。主作者逐项修订后交原评审者
复核。以下严重度指方案实施风险；“关闭”仅表示文档已明确要求，不表示对应
实现已通过测试。首次三平台运行、工具版本组合及性能基线仍需后续取得证据。

## 2. 发现、修订与复核

| 编号 | 严重度 | 初审发现 | 已纳入方案的处理 | 复核状态 |
| --- | --- | --- | --- | --- |
| A1 | P1 | “Ack 与最终 turn 结果分开展示”容易误读为 `start_turn` 接纳即 Ack | §6 明确 Ack 保留执行完成语义；等待期间展示 snapshot/events，断线后未知结果重新核对，不虚构 Ack 或重试 mutation | 关闭 |
| A2 | P1 | 只覆盖断连恢复，未覆盖连接存活时的 lag/cursor 缺口或成员变化 | §6 原子安装 membership 与各 member snapshot/cursor 屏障；缺口冻结受影响增量及相关 mutation，重新取得事实；§7/B2 加入恢复竞态场景 | 关闭 |
| A3 | P2 | 长 turn 等待可能阻塞事件、审批和中断 | §6 明确有界 pending、独立控制容量和持续 reader；B2 验证长 turn 未完成及普通容量耗尽时控制操作仍可达 | 关闭 |
| V1 | P2 | 固定 fixture 与环境记录不足以保证回放确定性 | §7 加入每场景存储/窗口/草稿重置、可控时钟/随机值、字体 ready、动画策略及中间态断言，不依赖固定 sleep | 关闭 |
| V2 | P2 | 真实 Tauri binary 仍可能全程 Mock IPC；脚本输入可能被误算为系统输入证明 | §7/B1 至少一条真实 React→Rust invoke/event canary；B2 真实 transport；证据记录 driver/provider 与输入路径，原生 IME/剪贴板单独验收 | 关闭 |
| V3 | P2 | 100 ms 目标没有清楚区分应用内计时、driver 往返与真实呈现 | §7 区分代理/自动化/呈现指标，固定起终点、时钟域及采样；虚拟/真实桌面分别报告，不用快进测试时钟计算性能 | 关闭 |
| D1 | P2 | 创建 GUI worktree 但未纳入现有 lane 管理入口 | §4/B0 增加根 AGENTS 路由、`EXPECTED_LANES` 与管理文档更新，按脚本真实影响验证 | 关闭 |
| D2 | P2 | 缺条件显示 unavailable 可能弱化必需 CI 交付门禁 | §8/B1 提交必需 case manifest；missing/skipped/零场景/缺证据非零退出并上传诊断与已有产物；探索性 unavailable 不满足里程碑 | 关闭 |
| D3 | P2 | B1/B2 一并要求“同机服务”，与 B1 独立 Mock 建设矛盾 | §9 明确 B1 真实 Tauri+Mock/fixtures，B2 同机 G16+离线 Product，B3 发布 profile | 关闭 |

## 3. 关键核对依据

- G16 的 `start_turn` Ack、接纳后的执行归属、断线未知结果与快照屏障：
  [G16 设计](../appserver/detachable-local-workspace-g16.md)、
  [client_scope.py](../../../../src/loushang/appservice/client_scope.py)。
- 增量缺口门禁、成员/快照恢复与客户端容量：
  [mux reducer](../../../../src/loushang/harnesstui/mux/reducer.py)、
  [mux controller](../../../../src/loushang/harnesstui/mux/controller.py)、
  [remote_client.py](../../../../src/loushang/appserver/remote_client.py)、
  [stdio_profile.py](../../../../src/loushang/appserver/protocol/stdio_profile.py)。
- GUI lane 的现有注册入口与严格 case 验收惯例：
  [lane_status.py](../../../../scripts/dev/lane_status.py)、
  [AppService CI](../../../../.github/workflows/appservice-quality.yml)。
- 继承 TUI playback 的场景意图及逐步证据方法，而非终端驱动：
  [KD-010](../tui/native-terminal-core/key-designs/KD-010-terminal-playback-harness.md)、
  [HarnessTUI](../harnesstui/README.md#conversation-playback-testing)。
- SSH/Xvfb 可执行 Linux Tauri 自动化的官方示例：
  [Tauri WebDriver CI](https://v2.tauri.app/develop/tests/webdriver/ci/)。
- WDIO embedded 路径支持 Windows/Linux/macOS；直接上游 `tauri-driver` 仅
  Windows/Linux，不能混称：
  [Tauri WebDriver](https://v2.tauri.app/develop/tests/webdriver/)、
  [WDIO 平台支持](https://webdriver.io/docs/desktop-testing/tauri/platform-support/)。

## 4. 首次复核结论与文档验证

三位原评审者均已复核通过：A1–A3、V1–V3、D1–D3 全部关闭，未发现新增
P0/P1。方案可以进入 GUI-B0 实施准备；Design status 仍为 proposed，正式 scope
与实施任务在启动阶段建立。

文档验证结果：

- 三份变更文档的仓库相对链接、方案/评审状态字段与空白检查通过；
  `git diff --check` 通过。新增方案与评审未列入既有固定文档集合，因此另行
  完成了这项静态检查。
- `make check-architecture-docs` 的 Ruff 检查通过；随后依赖图 freshness 检查
  导入 `loushang.harness.journal` 时失败，错误为无法导入 `read_journal_file_at`。
  本轮开始前已有暂存的 `src/loushang/harness/journal/jsonl.py` 改动删除了该
  函数，而 `journal/__init__.py` 仍导入它；本轮未修改这两处代码，也未回退
  已有暂存内容。完整 Make gate 未通过，不能报告为全部验证成功。
- 在沙箱外独立运行
  `.venv/bin/python scripts/dev/run_pytest.py tests/architecture/test_architecture_documentation.py -q -k 'not test_generated_current_package_dependencies_are_fresh'`，
  结果为 **4 passed, 1 deselected**。被排除项就是已失败的依赖图 freshness
  检查；其余文档状态、链接与历史权威检查通过，没有排除后宣称完整 gate 通过。
- 未执行 GUI 构建、图形测试或安装验证；本轮没有新增 GUI 源码和工具链。

本轮评审不代替 Rust 客户端实现、OS 本机身份准入、原生 driver 版本组合、真实
输入法与发布构建的后续验证。首次复核后的补充需求与增量复核见下一节。

## 5. R1：三平台同步协作开发

用户补充要求：允许在 macOS 和 Windows 环境同步协作开发。方案据此将
Linux/macOS/Windows 均列为正式开发环境，成员可以在各自平台独立编码、
调试与回放，并从 GUI-B0/B1 开始交付相应入口和证据。

具体修订：

- §4.1 明确每机独立 clone/worktree，Git 同步源码、锁文件与场景，环境按版本
  重建；平台使用独立安装目录、缓存产物、凭据与 Session。
- §4.1/§8 改用跨平台 Node 编排与统一 package scripts；Make 为可选别名，
  Windows 原生开发不以 Bash、WSL 或 GNU Make 为前提，路径与子进程入口按
  平台处理。
- §5 支持三平台同时承担开发任务；§5.1 保持各机 GUI 与本机 G16 接入边界，
  Git 协作不改变运行时的 local-only 合同。
- §7–9 将三平台初始化、原生构建、Mock/真实 bridge 回放分别纳入 B0/B1，
  各机 G16 闭环纳入 B2。三平台必需证据构成共同门禁，未完成的平台保留
  缺口，其他平台可以继续推进。

增量复核：

| 原评审者 | 结论 |
| --- | --- |
| `gui_arch_review` | 通过，无新增实质 P1/P2；共享源码未扩大运行时权限或改变 owner，本机 G16 边界与原 A1–A3 修订保持完整 |
| `gui_validation_review` | 通过，无新增实质 P1/P2；三平台入口、最小真实 bridge 场景、早期门禁与阶段退出条件一致 |
| `gui_delivery_review` | 通过，无新增实质 P1/P2；跨平台命令、环境隔离与同步、B0/B1 开发入口及三平台共同门禁完整，原 D1–D3 修订保持有效 |

三视角增量复核均通过，可以按三平台同步协作方案进入实施准备。R1 的三份
相关文档共 61 个仓库相对链接及状态/空白检查通过，`git diff --check` 通过。
此次仅修订方案与评审记录，没有重跑 Product tests；首次完整 Make gate 的
失败结果仍按 §4 保留，不因本次文档修订而改记为通过。当前没有 GUI 源码或
三平台运行证据。

## 6. 提交前验证更新

此前导致导入失败的 `journal/jsonl.py` 本地改动已按用户指示恢复至远端 `main`
版本。随后在基于 `3c06f5b9` 的独立 GUI 文档交付 worktree 中执行
`env PYTHONPATH=src make check-architecture-docs`：Ruff、依赖图 freshness 检查
以及全部 **5 项文档测试通过**。这更新了当前验证结论，§4 的首次失败记录仍
保留为过程证据。

包含新增需求文档的 4 份交付文件另行完成 70 个仓库相对链接、空白与需求编号
检查；13 项功能需求、12 项非功能需求均具备验收条件与对应阶段。需求仍为
proposed，本文记录的三视角评审范围是工程启动方案，未据此宣称需求已单独
评审或 GUI 已实现。
