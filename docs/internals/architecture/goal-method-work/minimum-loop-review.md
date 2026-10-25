# Goal 最小业务闭环：设计评审记录

- Authority: descriptive — 固定修订评审、问题处置和用户评审入口。
- Design status: draft；Implementation status: not-started for Goal。
- Owner：Loushang architecture / Coding Product composition。
- 目标：[G-GOAL-MIN-01](../../plans/2026-10-25-goal-minimum-business-loop.md)。
- 源码基线：`372cde4ade0fe026076c8fa5e8b4486774b09cc3`；前置未提交切片 hash 见设计 §12。
- 方法：本地干净 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 用户接受：pending；不把内部评审等同于恢复 Goal 实现。

## 固定评审对象

| 对象 | 修订及 SHA256 |
| --- | --- |
| [架构设计](minimum-loop-architecture.md) R1 | `ce70a42716d9894edd4c26fa3f7f7d9c6eb865b5199f49811f22c3eb0e20ba55` |
| 架构设计 R2 | `b3afb190897116719f2b39ef3d2c3c269f5291e2bc6f4bb55acf34762ee300e5` |
| [系统环境图](context.md) | `8eb9d3c04f56b9a2236d4342cf2a8d2baff47356e579057087f27f6d38e85d6d` |
| 目标与验收范围 | `71544b34206305c9b7628279c1886479cc4d45e0e95d1a6aed7c606c1f620512` |

原文副本、manifest 及三名独立 xhigh agent 的证据化报告保存在产品树外：
`/home/dev/lsspace/architecture-analysis/goal-minimum-business-loop-20261025/`。
R1 为 `review-r1-a/b/c.json`，R2 为 `review-r2-a/b/c.json`。评审者不读取本轮
其他人的报告；作者在初审后综合修订，并分别请求受影响复核。

本轮是架构源码核查和场景走查，未启动 Goal 实现或真实模型调用。旧证据切片的
运行报告只是前置能力证据，不能充当本 Goal 的实现验收。文档规则/链接检查已
通过，证明工作件可访问，不证明架构机制已运行。

前置版本更新：SDK 证据切片已在本地提交 `d1f418de5`，13 个文件组成独立切片，
未包含本 Goal 的组件/状态/场景设计。三个冻结生产源文件及对应回归源的哈希与
原验证记录完全一致，因此没有把版本固定误记为新运行验证。R2 文首“未提交”是
其冻结时的前置状态；当前以前述本地提交定位相同字节，main 集成和完整检查仍
未完成。R2 原文、环境图及目标范围的评审哈希保持不变，用户接受仍为 pending。

## 三视角与处置

| 视角 | R1 发现 | R2 处置及复核范围 |
| --- | --- | --- |
| A 职责与复用 | GA-B1：只读允许改的源码，无法发现其他项目文件违规改动（阻断） | §7.1 完整有界项目基线及修复后/验证前/完成前比较；新增/删改/改名/类型/链接、测试原文异常均由 Product 拒绝，不更新基线抹违规 |
| B 运行与失败 | B-G1：Session 执行 ownership 和关闭移交缺机制（阻断） | §4 内部创建/恢复原 SDK Session，原 writer 取得后才开放 handle，不借入现成 Session；§9 输入时段、无 await 转发及 close→收束→原 dispose→writer-last，失败保留 cleanup owner |
| B 运行与失败 | B-G2：unknown intent 的恢复准入未决定（阻断） | §8 明确原 Work 无足够证据时会话级 execution_unresolved；首版无解除 API，resume/replace/换 Goal/root 不绕过，不以空查询证明没有执行 |
| B 运行与失败 | B-N1：resolver 可能只绑定 executor，丢失原取消能力（非阻断） | §4 显式将修复 executor/cancellation 同时绑定为原 SessionTurnExecutor；验证保留原真实能力与 unsupported 分支 |
| C 数据与兼容 | GC-C1：driver 输入与可信测试结果边界不明确（阻断） | §7.2 选定有限纯函数域、完整 AST/签名/资源准入、固定测试与原 unittest runner；Product 原 reader 核验 bytes→原 SDK stdin→固定 driver；结果不能由受测源码自报 |
| C 数据与兼容 | GC-C2：跨记录不变量、会话 writer authority 和演进规则不全（阻断） | §8 明确序号/要求/epoch/命令/批次/原 operation/决定的引用与唯一性，同会话固定 writer scope 和 root 派生，required_features/未知版本及只读诊断边界 |

R2 三路受影响复核均已完成，R1 的 5 项阻断及 B-N1 澄清在设计层关闭，三路均
未发现新增阻断。作者逐份读取原报告及关闭证据，并核对最终 manifest；不是仅凭
作者修订说明关闭问题。没有重复运行未变化的源码盘点或无关测试矩阵。

| 独立复核 | 最终结论 | 报告 SHA256 |
| --- | --- | --- |
| A | 0 未关闭阻断、0 新非阻断，可提交用户评审 | `b7f00461a9cccd36557ae7221c4d1dc21d3625e90ba2633eb7ad2a36c820933e` |
| B | 原两阻断与取消绑定澄清关闭，无新增问题 | `89b3ac1d6904ae3d1be94a0ed62033a69943c4dc4d58eb09bfce323238b93c35` |
| C | 原两阻断关闭，无新增阻断 | `23b83585752217b842fb1f4db24b814366c09633abb758290f77b7f392da8c3b` |

上述结论只支持固定 R2 进入用户评审；未来仍需真实证明 AST/输入/driver/约束/
owner/reducer 合同及整个多批模型修复路径。项目清单只证明所列检查点的状态，
不能扩张为“任何瞬时越界写入从未发生”的文件监控保证。

## 提交用户评审的重要决定

以下内容都来自候选 R2；此表不是接受记录。

1. **入口与生命周期**：首版 Linux 本地 SDK，内部创建/恢复专用原 Session，只向外
   暴露 Goal handle；同一会话一个活动 Goal，保留历史。不接任意外部执行 owner。
2. **推进与方法**：显式 Method 真实修复，一次 advance 一批原 Work；初始失败验证
   →模型修复→再验证，失败证据进入后续输入。模型自主规划后续共用同一准入合同。
3. **首个真实任务**：单文件整数减法/clamp 项目；固定测试、完整项目约束清单及
   有限纯函数验收策略。超出语法/依赖域明确拒绝，不能把首例推广成通用 Python
   安全执行器；模型仍真实修改实际源码，不用固定补丁。
4. **事实权威**：新增 Goal 要求/控制/关联/完成记录，复用原 journal 与 writer；
   Work、Transcript、Blob 和 usage 仍归原 owner，没有跨库事务或 exactly-once 承诺。
5. **控制与未知**：正常暂停可重核恢复，修订使旧依据失效；无法核实的旧执行结果
   留作会话级 unresolved，首版没有一键解除/自动重放。放弃目标不代表外部效果收尾。
6. **输入与兼容**：普通 SDK 不变；Goal 专用 handle 在修复 running 时转发原同步
   steer/follow-up/text/image，验证/完成窗口拒绝执行输入；目标变更走显式修订命令。

用户可接受上述限定范围或指出需修改的决定/图。环境图、组件图、状态图及交接
时序集中在 R2 §3/4/5/8，其他关键合同在 §7/9。未获接受前继续保持功能实现未启动；
本轮 Goal 仍 active，后续须完成前置集成、实现、真实场景及逐项验收，不能因设计
完成就宣告整个 Goal 完成。

## 本轮进度与剩余工作

前一目标描述 turn 分类为 progress：新增了明确目标与验收文件；本轮分类亦为
progress：核对源码、补齐候选架构、独立评审并修订实质问题。没有将等待评审或
只复述计划记作实现进度。

下一步顺序为：关闭内部设计问题→用户评审接受范围→收束前置证据切片集成与
相关检查→实施并验证原 Goal 全部要求。实现前必须固定真实项目、Method、模型
与权限配置；设计里列出的未来测试不是已执行证据。
