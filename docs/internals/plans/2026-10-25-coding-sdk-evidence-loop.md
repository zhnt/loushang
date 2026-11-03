# G-CSDK-EVIDENCE-01：真实 Coding SDK 验证与证据消费闭环

- Authority: normative — authorized delivery scope, not the full Goal architecture。
- Design status: accepted for this slice；Implementation status: implemented and focused-verified locally，尚未集成 main。
- Owner：Coding Product composition；实现与验证由本任务执行者负责。
- 基线：`372cde4ade0fe026076c8fa5e8b4486774b09cc3`。
- 架构方法：本地干净 `archmethod master`，提交
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；未声明与上游同步。
- 分支：`feat/coding-sdk-evidence-loop`；工作树为长期 Code lane。
- 依据：[HW-KD-002 R2.2](../architecture/harnesswork/key-designs/evidence-handoff.md)，
  SHA256 `113bcaa4f1dba890477177e12a199f55f6a55284eb12431f4aec6547111c5fa0`。
- 用户授权：“确认，请你设计新的goal描述，做一个真实 Coding SDK 证据消费闭环”。
  接受范围只覆盖本切片，不扩大为完整 Goal 状态、规划、自动推进或跨入口合同接受。

## 目标描述

在 Coding SDK 现有执行和持久化能力上，实现一个本地项目验证任务的证据生产、
Work 关联、实际消费和重开闭环。通过真实 Coding Session 的命令执行接口运行
调用方指定的验证命令，复用已留存的输出 Blob，生成私有报告及绑定报告摘要
的验证结果。SDK 调用方按本次 Work 查询并读取证据，重开后仍可核验原内容，能
识别缺失、损坏及尚未解析的旧支持材料。失败不得伪装为验证成功，材料可读不得
自动等同于目标完成。交付复用原 Work、Session、授权、输出捕获和 Blob，不增加
公共证据框架、执行队列或 Goal 运行时。

## 真实任务、调用方与资源边界

首个消费者是本地 SDK 验证调用方：对明确工作区运行已有项目检查，读取该次运行
的报告和验证结果，而不只打印事件。演示调用方通过公共 Coding Session 构造路径
建立真实 Session；命令经 execute_bash/原 command-tool 路径执行，不直接启动替代
subprocess，不调用模型或联网。命令成功与完整输出留存分别核对。

私有实现放在 Coding 的 adapters 下；中立 Work kernel、原端口、公共 root/facade
导出不改。Product 装配显式选择同一逻辑 Session 的 Blob reader/writer 和 Work 日志；
调用方负责单 writer 使用前提及本地日志/metadata 读取权限。默认不绑定远程 Channel。

已有 SessionBlobRef 直接读取/引用，不将相同 stdout/stderr 再转存一遍。新报告和
验证 JSON 是本领域的材料，使用现有 SessionBlobStore 写入；如以后接入临时产物，
只能通过已有 promotion 转存，不能以路径或摘要猜测 authority。
实际 Coding SDK 的短输出不一定生成 Blob；若 SDK 明确未截断、stdio 完整且无 drain
异常，私有适配可首次保存
其完整文本视图，标记 sdk-text-view，不把它说成原始 OS 字节。缺失完整材料、截断
却无足够留存或原 SDK 报留存失败时，不得判验证成功。真实 SDK 存储要求状态域与
Transcript 数据域分离且目录可信，沿用原准入规则，不修改目录权限或存储策略掩盖问题。

实现复核确认原 SDK 结果转换遗漏了工具已有的 `stdio_complete` 和
`stdio_drain_reason`。本切片在原 Harness Session 转换处条件透传这两个诊断：没有原值
就不造默认值，返回字典可能增加对应字段。Product 双侧必须显式核验 bool 完整性；
未截断不替代 stdio 完整，单个已留存流也不替代 stdout/stderr 两个流的完整材料。
此为既有诊断的兼容性补齐，不改变执行、授权、捕获、Work 端口或公共导出。

原步骤/取消/异常仍由 Work 和 Coding Session 拥有。本切片不新增 timeout 或队列，
也不把原协议中的 unknown 结果升级为强收尾。原始命令失败可留下报告及失败验证
材料，但 Work 必须为失败，不能将“记录成功”误说成“命令验证成功”。

## 验收条件

| ID | 完成判据 |
| --- | --- |
| CE-01 | 真正构造 Coding Session，执行真实本地验证子进程；不以 FakePromptSession 或返回固定 output 的 executor 代替闭环 |
| CE-02 | 通过原 Work 执行两个步骤：形成报告、读取已报告材料进行验证；报告引用原输出 Blob，验证结果明确 report sha256 |
| CE-03 | 调用方从 Work 日志重新查询并通过绑定 reader 读取两份材料，不仅依赖 executor 内存中的返回值；Session/Work 重开后关联和内容可核验 |
| CE-04 | 正常、非零退出、必需输出未留存、缺失/篡改、配额与发布失败有具体断言；沿用原错误/生命周期，不补终态后事件、不盲重试或删除共享对象 |
| CE-05 | v1 payload 只含 evidence；版本、authority、字段、浮点/source 全值、日志前缀和旧偏离材料并存按 R2.2 核验；步骤自报不直接用于验收 |
| CE-06 | 原 Coding Work/Method/Session 相关路径通过适当离线验证；不新增或扩大 PR gate，不为 example 脚本另写单元测试 |
| CE-07 | 给出可重复运行的 SDK 消费示例及实际执行证据；限制说明只覆盖本地 SDK，未声称完整 Goal、远程共享或跨 workspace 迁移 |

## 实施顺序与收束

先核实真实 SDK 的现成输出 Blob，再实现最小私有协议与领域适配，用真实 SDK
消费者验证；必要的故障断言围绕生产 helper/adapter，避免为演示建立第二套实现。
完成后做受影响三视角实现复核和组合检查，记录真实结果及限制，不重新开启整套
架构设计。此切片收束后回到 Goal 最小纵向闭环，避免继续扩张通用底座。

## 实施结果与独立复核

Coding Product 私有实现为 `_work_evidence.py` 与 `_verification_work.py`，
可运行消费者为 `examples/coding/26_verification_evidence.py`，使用方法见
[示例说明](../../../examples/coding/README.md#本地验证与证据消费私有集成示例)。
原 Work kernel、日志后端、Blob Store、promotion、端口及 root/facade 导出没有修改。
唯一共享源代码增量是原 SDK 结果转换条件透传已有两项 stdio 诊断。

三名独立 xhigh agent 对固定源码作实现复核：A（职责与复用）、B（运行与失败）、
C（数据与兼容），最终均为 0 未关闭阻断、0 新增非阻断。初审发现的未知完整性默认
成功、单流冒充完整材料、stdio 未完整读完仍可通过三类问题均已修正；原始发现及
关闭证据保留。评审主体为静态源码/测试合同核对，运行结果由主代理执行，未把
agent 阅读日志说成再次独立执行。后续只同步了三条原 SDK 精确字典测试的新增字段
预期，冻结生产源码未变。

| 验收 | 本地实际证据 |
| --- | --- |
| CE-01/02 | 真实 SDK 执行项目 `scripts/ci/check_docs.py`，形成 report/validation 两步；run 为 `verify-2adec19dcfc44587952a1c8ddbb4c27e`，命令 exit 0，Work completed，消费方 verification=true |
| CE-03 | 处置 SDK 后绑定只读 reader 消费；另起 Python 进程 `--reopen` 再读，输出与首次消费逐字一致，没有重执行命令 |
| CE-04/05 | 聚焦组合 684 passed、1 skipped；涵盖错误/配额/发布前后失败、未明完整性、单流、偏离引用、版本/authority/引用精确相等、命令及报告摘要绑定、取消和非 completed 终态 |
| CE-03/04 | 单独真实 SDK 主机测试 1 passed：执行实际 unittest 命令，关闭/冷重开后再读，篡改与缺失输出均不返回通过 |
| CE-06 | 原 Session、工具与 RPC 消费合同补充回归 197 passed；Ruff、三个受影响源模块 mypy、文档检查及包依赖边界检查通过 |
| CE-07 | 可直接运行的消费者及新进程重开示例已提供；保存真实运行日志及三份固定修订评审，范围仍为本地 SDK |

运行与评审原始记录位于产品树外
`/home/dev/lsspace/architecture-analysis/coding-sdk-evidence-loop-20261025/`：
`real-sdk-run.log`、`real-sdk-reopen.log`、`real-sdk-test.log`、
`review-implementation-a.json`、`review-implementation-b.json`、
`review-implementation-c.json`。实际运行的数据在
`/tmp/loushang-csdk-evidence-final-20261025/`，属于本地临时验证材料，不能承诺其
机器清理后的保存寿命。评审所用的 R2.2 设计快照保持原哈希，其文首设计时状态不
取代本记录对已授权实现切片的状态说明。

### 组合检查的环境处置

初次变更范围检查在 Coding 路由出现 18 条 Plugin 来源校验失败及 1 条旧 SDK
精确字典预期失败；取出堆栈后主动中断（当时 316 passed/19 failed），没有声称
整套通过。两条代表 Plugin 失败已用同一虚拟环境在干净 main 复现：共享安装的
editable 来源指向旧工作树。相关 SDK 测试预期已补上条件透传字段；没有为来源校验
修改产品或放宽规则。

随后在 `/tmp` 建立仅供本任务检查的隔离环境，复用原 Python/依赖字节、单独安装当前
工作树的 editable 元数据，不改共享 `.venv`。代表来源与 SDK 路径组合已 5 passed。
离线执行既有 `check_changed.py --pr-fast` 计划，保留所有原 selector，不增加门禁。
该完整计划没有跑完：隔离串行 Coding 已 541 passed 后为消除重复路由主动中断；
尝试现成三分片及独立 Harness 路由后，发现收集/执行开销仍大，遂收束到本切片直接
受影响的合同验证。被中断路由中的局部通过（含 Harness 1794 passed）不计为整套
通过，不累加成一次完整验收。全量 Coding/Harness 及计划中平台检查仍留在集成前，
本记录不声称 `check-changed` 或全部平台已通过。

直接受影响的 `test_agent_session.py`、`test_agent_session_tools.py`、
`test_rpc_contract_matrix.py`、`test_rpc_controls.py`、`test_rpc_mode.py` 最终为
197 passed；结合既有 684 项组合、独立真实 SDK 测试和三视角复核，接受本地切片
CE-01…07 的上述限定证据。接受责任为本任务主代理，范围为 Coding Product 私有
实现及最小 Harness Session 诊断交接；没有将未完成全量回归升级为已通过的集成门禁。
生产源码自最终评审冻结后没有再变，后续材料只补验证结果和范围说明。
