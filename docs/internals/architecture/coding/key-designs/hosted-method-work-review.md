# 托管 Method → Work 三视角评审

## 评审框架

- 对象：[COD-KD-HMW-001](hosted-method-work.md)，#824 的应用内 SDK 第一切片。
- Authority: descriptive — design review evidence；Design status: reviewed；Implementation status: 见交付记录。下文 R1/R2 结论保留设计评审时点。
- 源码基线：`914cf3ac84935c8bbd2855e660505b3b31eba2ef`，任务分支 `design/hosted-method-work-824`。
- 方法：archmethod 本地干净 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，README / key-designs / architecture-review。
- R1 SHA256：`8e9fa3002408c0a3e4b86d4e00937d031b8cee3c12259f14ce70b7db462282de`。
- R2 SHA256：`e16f06967f98b72f3369d29675944683ae511b4c7bcd7d37d4f2e2aa7aa70b99`。
- 日期：2026-11-01。

用户要求先设计一个托管入口的 Method → Work 执行和查询，再三视角评审。用户此前明确“系统环境图等重要工作件需要我评审”，因此本记录只作内部技术评审，不代表用户接受、不授权实现。

三个独立 xhigh agent 分别从空白上下文读取同一 R1、适用规则及源码，不互读报告。主评提供了 Work.wait 取消桥的源码纠正提示，并在收集发现后说明 R2 修订方向；修订后由原三人复核。不能将协调后的复核伪称为完全隔离的第二次独立发现。

| 评审者 | 视角 | 主要场景 |
| --- | --- | --- |
| `/root/hosted_method_ownership` | 职责与复用 | 原 Session/Work 装配、普通配置、legacy旁路、SDK/member/owner 生命周期 |
| `/root/hosted_method_runtime` | 运行与失败 | submit_plan 受理/等待、中断时序、步骤失败、清理重试、完成与晚到中断 |
| `/root/hosted_method_data` | 数据、权限与兼容 | text-only去重、跨实例/Session/owner查询、存在性、DTO及记录确认、关闭释放 |

## R1 发现与 R2 处置

R1 共五条原始阻断发现，归并为三类问题；不是五个相互独立的产品缺陷。另有七条非阻断发现，其中存在跨视角重复。所有结论来自静态源码和场景推演。

| 原始 ID | 级别 | 事实与影响 | R2 处置及关闭条件 |
| --- | --- | --- | --- |
| O-1、D-B1 | 阻断 | SDK attachment、registry binding、Product owner 寿命不同；旧 member 关闭后 `_resolve` 已拒绝，无法承诺旧 Work 历史查询 | §5 明确定义唯一 owner，scope 只借用；第二执行 owner 拒绝；close_member(false) 保留 Session 事实。§6 收窄到当前受权 member/owner，以观察锚防替换，关闭后沿原权限错误；V7 覆盖 |
| B1 | 阻断 | `submit_plan` 包含整批 wait；若先 join 后 cancel，会放任后续步骤继续 | §7 指定 latch→cancel 原 submit task→复用 wait/cancel→join→完整 Session settlement；before_turn/prompt 都检查取消；不重提。V6 覆盖三处交接 |
| B2、D-B2 | 阻断 | registry/guard 进入前中断或 start 失败可终态且零 Work；原 presence 无合法表达 | §6 新增 unknown，明确未提交只来自原 invocation 的保留证明；不能从 terminal+无run推导。V6/V8 覆盖旧 invocation 被覆盖后的未知 |
| O-2 | 非阻断 | AppService legacy入口可能直接 registry.start_legacy，覆写 Product.start_turn 不足 | §5 在 scoped/unscoped 实际 admission 前拒绝 legacy及fallback，默认配置不变；V4 验证三层无副作用 |
| O-3 | 非阻断 | WorkRuntime.wait 已在收到取消时调用 cancel | E6 改正 Current；新增适配只处理额外 shield/保留 submit task 的接缝 |
| O-4、N1、D-N1 | 非阻断 | dispose 抑制异常且不清历史，不能证明清理或释放 | §6/7 先确认原 execution/Session settlement；成功关闭再撤销查询、订阅及强引用；失败保留凭据。V7 覆盖外层已关闭对象仍被持有 |
| N2 | 非阻断 | guard 候选结果形成后，晚到 interrupt 不推翻它 | §7 继承既有规则；V8 验证 settlement失败重试仍保留原候选 outcome |
| D-N2 | 非阻断 | 原 plan metadata 可含路径/异常；recording与cancel有各自水位；Method ID 可含冒号 | §6 显式白名单、独立观察字段、不同ID grammar和准入长度/步骤上限；V8 验证不泄露、不假确认 |

关键源码依据：

- `src/loushang/harnesswork/integrations/session.py:605` 受理后继续 wait；`harnesswork/runtime.py:261` wait 的取消桥、`:467` dispose 的真实行为。
- `src/loushang/appservice/execution_registry.py:287` pre-Product 中断；`execution_guard.py:185` pre-entry 中断、`:145` 候选结果形成后的取消规则。
- `src/loushang/appservice/execution_service.py:93` scope解析；`runtime.py:1157` member关闭、`:1184` unscoped legacy；`client_scope.py:492` scoped legacy。
- `src/loushang/apphost/runtime.py:306` 多 attachment；`coding/hosted_application.py:533` execution wrapper装配。
- `src/loushang/harnesswork/recording.py:30` 确认模型；`harnesswork/types.py:98` cancellation观察；`method/loader.py:135` 描述符metadata与ID。

## 组合走查

主评将两条主要路径合起来复核：

1. **正常两步**：受权 SDK → 原 registry 去重/受理 → 原 hosted guard → 固定 Method 准备 → 原 SessionWorkRuntime/Session → Work 记录确认 → Session settlement → execution 终态。查询只在当前 scope/owner 上投影原事实；不把 Work完成认作Goal完成。
2. **第一步中断**：guard中断原 invocation → latch阻止下一步 → 原 submit task收到取消 → Work.wait驱动原cancel → join与完整Session清理。清理失败保留依赖；重试只清理。客户端断开不等于应用关闭；最终关闭才释放Work记录。
3. **零 Work 与关闭**：在Product进入前中断可有终态execution而无Work，负证据不足时unknown；下一次invocation不能补造旧事实。member关闭后旧scope拒绝访问，registry内部保留不能升级成历史读取授权。

这些走查不证明异步实现已满足合同；V1–V8 是未来实施验证要求。

## 修订复核与结论

三位原评审者均核验上述 R2 SHA256，并给出逐项设计层关闭结论：

| 视角 | R2 复核结果 | 保留的实施验证责任 |
| --- | --- | --- |
| 职责与复用 | O-1～O-4 关闭，无新增阻断 | 第二 owner 拒绝不得误关闭原 owner；默认入口不变、旁路无副作用；scope重连复用原Work runtime |
| 运行与失败 | B1/B2/N1/N2 关闭，无新增阻断 | 真实异步取消交接、步骤结果、settlement重试、晚到中断与资源释放 |
| 数据、权限与兼容 | D-B1/D-B2/D-N1/D-N2 关闭，无新增阻断 | 受权查询复核、观察锚、未知存在性、DTO白名单/水位和引用释放 |

R2评审时的结论：五条原始阻断（归并三类）及七条非阻断意见均已在设计层处理、经原视角复核关闭，可提交用户审阅。该结论本身不是架构用户接受，也不是实现验收。

后续接受记录：2026-11-01 用户在审阅 R2 汇报后回复“同意，继续推进”。因此本切片现已获得用户接受及实施授权；原R2 SHA记录仍指向评审时的冻结正文，当前设计页仅更新接受/交付状态。实现与代码复核另见[交付记录](../../../plans/2026-11-01-hosted-method-work.md)。

R1/R2 冻结副本及三份完整独立报告（含复核）归档在产品树外的
`/home/dev/lsspace/architecture-analysis/hosted-method-work-824-20261101/`；本文件是仓库内的发现、处置及复核摘要。

## 验证与后续责任

- 文档轻量检查：最终 R2、评审记录及两个索引文件的 `make check-docs-light` 九项检查通过；四个文件的仓库内链接及 `git diff --check` 通过。
- 未运行 Product 测试、异步实验、真实模型、付费试验或远程托管验证；未修改产品代码或CI gate。
- AppService/Coding 实施负责人应在用户接受后实现 V1–V8，尤其是取消任务交接、入口旁路、查询权限及强引用释放。实现后必须按源码差异再评审，设计通过不能代替代码评审。
- 首切片之外：动态选Method、Goal托管推进、远程协议/证据、进程恢复、跨服务/多profile共享执行owner；均为未接受扩展，不记为本轮已接受Target的实现欠账。
