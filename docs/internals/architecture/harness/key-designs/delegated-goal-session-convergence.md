# A81：Goal 委派 Work 与原子 Session 轮次交接

- Authority: COD-RESP-GOAL-002 的指定路径交付记录；不接受整个 C12 或 P3/P4。
- Design status: 三个独立实际代码视角获本片有界接受，无剩余具体设计阻断。
- Implementation status: R4 四源已接入并获本片有界技术接受；完整 Goal 保持 partial。
- Owner: 原 Harness Session / HarnessWork Session 集成；Coding 保产品政策。
- 起点：A80 `a442f3c7ac10e425b2a65d850bacbe9e86607bff`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；未声称远端同步。

## 问题与完整路径

原 `coding.adapters._goal_delegation` 已实际调用共享 MultiAgent runtime，
但 Work 到子 Session 的选择修订、创建 Task、轮次交接、取消等待、失败保留和
清理重试仍在 Coding。原 `_goal_execution_context` 还通过图片水合读取 Blob。
这两段操作不能只改目录或作为完整 IO 回调借回 Coding。

本片将 prepare/confirm、fresh/inherit/reuse、创建/交付/完成、报告发布、失败
interrupt、取消/idle 等待及 release/close 的完整协调交给原 HarnessWork Session
集成。固定 watermark 的历史取得与图片水合由原 Harness Session 集成执行。
Coding 的仓库任务、测试验收、工具准入、历史选择和证据政策保持。

## 原组件复用与保留边界

| 原 owner / 程序 | 本片职责 | Coding 保留 |
| --- | --- | --- |
| `WorkRuntime` / `SessionGoalCoordinator` | 原 Work 事实、准入及 Goal 关联；直接复用 | 业务动作与验收 |
| `SessionMultiAgentRuntime` / `MultiAgentControl` | 原 child identity/incarnation、round、creation/interrupt/close 与清理权威 | 产品角色、工具及原 factory 装配 |
| HarnessWork `integrations.delegation` | 完整 Work-to-round Task 和关联寿命，不另建 runtime/registry | 真实兼容类、纯冻结/报告/evidence 字段 |
| Harness Session `multiagent` | 原 Transcript Profile 回放、图片水合及 `SubagentContextFactory` 计划 | strict pairing、empty fallback、digest 和 mapper 标识 |
| `TranscriptSourceReader` / `SessionBlobStore` | 直接读取原 source、put/readback 与 Work publish | Blob 标签及纯 fact 编码/验证 |
| `ModelCallAllowance` | 原 enter/leave/fence/call 限额；直接复用 | phase/限额政策 |
| `SessionExecutionScope` | 原 Goal 关闭及父资源结清顺序；未改造 | 原 scope ports，未重复计收益 |

新 `integrations/delegation.py` 是现有 HarnessWork Session 集成的实现模块，
没有第二个执行器、child registry、Work 事实存储或恢复引擎。其状态是原有的
selection、当前 Work、Task/creation 和未结清引用，不镜像原 child round 权威。

Code 保真实 `SessionChoice`、`SessionExecutionPolicy`、`ExecutionContextView`、
`_ChildRuntime` 和兼容 `DelegatedWork`/`DelegatedSessions` 类。三个 DTO 的
12 个自有字段和 FQN 保持；原 `_ChildRuntime` 整类 AST 保持。构造器与 `_build`
仍是产品 factory/SDK 政策接缝，不冒称纯 codec。

14 个私有 policy 属性、5 个纯值方法及两个薄属性完整计成本：选择/view/Work
类型、ref/message codec、工具/角色/phase/operation/blob 词汇，binding/context/
freeze/report/fact 编码。它们不接管 Task、Transcript、Blob 或 round 操作。
不为动态原合同增加 ABC/反射校验或改变构造失败时点。

私有 class policy 值取自原产品声明，不声称任意运行时 monkeypatch 模块常量的兼容；
原公开类/入口/签名和真实消费者合同由固定观察及原测试核对。
Code 的 `build_context` 和 `_HistorySource` 保原签名及真实兼容入口，操作体调用
现有 Session bridge。Core 直接执行历史读取、回放和图片水合，Code 仅提供原
canonical/AI codec 的纯 detach 值操作及纯政策。Harness 没有新增 Goal/Work 导入。

## 失败、取消与清理合同

- prepare 与 inherit 实际执行时的第二次 history/currentness 核对保持，未缓存或合并。
- Work 调用 shield 原有 Task；creation 独立保留，cancel port 仍取消创建或中断准确 child round 并等待原 Work。
- `active` 赋值在 allowance.enter 前；模型失败、轮次不符、报告 put/read/publish 失败仍走原 interrupt 与清理。
- child.wait_for_idle 失败会 fence，并跳过原 finally 后续 policy reset、allowance.leave 和 active 清除；本片保原行为，不顺带修语义。
- 普通创建失败与携带 owner 的创建失败保持不同；后者准确引用保留在 cleanup_pending。
- release 在原 shielded close 前记 debt；调用者取消不等于资源已退役，重试仍以 registry 为权威。
- Goal 关闭继续先结清 child，再释放 source/parent/Goal writer；失败保留原对象供重试。

## 全量成本与来源

| 生产源码 | 起点行 | 实际行 | 增删 |
| --- | ---: | ---: | ---: |
| Code `_goal_delegation.py` | 520 | 225 | −295 |
| Code `_goal_execution_context.py` | 179 | 147 | −32 |
| 原 Session `multiagent.py` | 1,031 | 1,119 | +88 |
| HarnessWork `integrations/delegation.py` | 0 | 389 | +389 |
| 合计 | 1,730 | 1,880 | +150 |

Code −327，接收侧 +477，系统 +150；是职责迁移，不称系统去重。
包括兼容类、policy 属性、pure codecs、imports、绑定及正常格式成本。
当前 Coding430文件114179行、系统1967源647780行；距15K仍99179行。
其余1963份原生产源码 SHA 和13份原包资源字节相同。原 Session22个已有
顶层定义 AST 保持，Code六个 DTO/helper 定义 AST 保持。

完整旧1966源及13资源、before-frame、各候选与失败、源码 origin 守卫、冻结观察、
实际结果保留在产品树外 `a81-goal-execution` 证据目录。before-frame SHA：
`72e2a4bcaaa1683f9f4bfae0c56552989244abe15b9a2e01fbe26da81ec9672b`。

## 验证与评审记录

迁前四原 consumer 模块83项通过（595.92s）；R2原 delegated/inherit/release
12项通过（214.00s，57原 selector 排除）。实际 R4 同四原模块83项通过（1083.99s）；原共享
Session MultiAgent、context、RunHandle 及 import boundaries 共209项通过（351.83s）。

兼容视角独立捕获原28值/API/wire观察并冻结，再以原固定28+source guard验证29项
通过（4.73s）。原 fixture SHA `25c66871f162a94a72f16f8805fe6f6c9c437ab4030f1b8beb208a9510e64c1a`。
首轮27过1失败是观察程序误判换行 reason 应拒绝；原代码允许非空字符串中的换行，
仅修观察分类，同旧节点1过，原失败与两次 raw 来源保留。不改原政策。

R1未安装：其拟议 JSON detach 没有完整保留旧 canonical 验证，R2改为注入原纯值
codec。R2初始三 import-style 失败、R3外置静态命令漏显式项目 config 及新增区空行
失败均保留；最终R4显式项目 config 的四源 Ruff/format通过。R2四源 basic mypy
通过，不称所有动态 policy 接口已经静态验证。

运行视角独立捕获38完整场景（215.02s），原固定重播38过（206.22s），实际R4
同38过（214.86s）；没有重捕实际期望、hook重定位或trace归一。真实Task、Lock、
shield/cancel、原MultiAgent control/runtime/RunHandle、原context codecs与Allowance
实际执行，parent/SDK/factory/driver、reader、Work lookup和Blob端口受控。原SDK
消费者另有其自身验证，不把端口受控观察外推为真实Provider/Store全链。
put/read/authority-validation/publish四失败均在实际Core程序命中，原idle覆盖主错
和跳过leave/active reset的完整异常链、状态与顺序保持。每个场景前后完整源和
loaded-module origin守卫通过；两个fixed进程共享末次诊断文件，最终actual993个
loaded origin单独归档，不冒称另有独立original最终loaded列表。

原完整runtime JSON667310字节无损gzip为17165字节；解压SHA
`7d2b4278cd7dcd3e54ef5b6d859da51107ab89534e30774b54e9e0470a8c6952`，gzip SHA
`bc03f25456034b17458fb58eaefa2e6ef959bfa5fc0f944a7e260bc8679a4620`。
portable稿实际完整38过（17.35s）；实际Product路径两份显式探针共67过（12.01s）。
value探针内六报告观察直接调用新Core publisher并禁旧helper，原fixture整字节保留；
其portable迁后30项（含external source guard）也通过。格式与import排序后的完整
非import observer AST保持，不改输入、断言和原期望。

职责/复用、运行/失败、数据/兼容三个独立实际视角分别记录有界接受。实际四源
basic mypy通过；显式本地probe不加入默认发现/PR gate。

检查计划因整分支与未分类集成路径选择广泛验证，AI检查亦执行：lint、79源mypy、
catalog/import检查通过，935测试过/2原skip/7原selector排除，但覆盖率89.87%及
runtime-core89.63%未达原90%阈值。冻结A80源同失败目标935过/2skip/7排除（29.54s），
全部79源逐文件逐行hit map和汇总8465/9419与实际完全相同，coverage数据库测量
路径均指向冻结旧源。确认为原阈值基线失败，未改阈值，不称整条check-ai通过。
第一次外置AI对照遗漏examples资产，出现31缺文件失败/904过；保留原失败后从A80
恢复139份原examples资产，再执行上述完整同目标。不是生产修复，也不合成首轮全绿。
计划中的其他全量产品/原生平台路线没有据此宣称执行。

原共享209、原consumer83和落盘显式probe67均实际通过；它们不是完整产品全套验证。
四实际源basic mypy、六source/probe的Ruff/format、文档9项及source graph freshness
通过。Root以受委派的跨组件实现/技术接受角色核定三独立评审、实物、原对照与全成本，
接受本片指定路径；AI原覆盖率失败与未运行的平台/全产品路线继续明确保留。

显式回归入口：[值/API/wire](../../../../../tests/coding/probe_goal_delegation_values.py)
及[完整运行/取消/清理](../../../../../tests/coding/probe_goal_delegation_runtime.py)。

## 剩余义务

本片不接受整个 Goal/Work/仓库评审领域组，不重开原 PlanningWork/GoalCoordinator/
ExecutionScope，不消除 calculator/repository 的真实用户能力。普通 Worker、P2
启动/Plugin/Session、其余托管/Continuity与P4入口/存量职责继续。
KD003仍未实施；KD011/A33仍待用户且不采用。完整P1–P4/≤15K Goal保持partial。
