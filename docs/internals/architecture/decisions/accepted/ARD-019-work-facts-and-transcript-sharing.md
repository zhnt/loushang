# ARD-019：Work 事实留存与 Transcript 共享边界

## Status

- Authority: normative — accepted cross-scope design
- Design status: accepted
- Implementation status: not-started
- Revision: R3.1, 2026-10-28
- Owner: Loushang architecture；参与责任：HarnessWork、Harness Transcript/Session、Product composition、Goal 领域消费。
- Current baseline: `5eadeb91ccee4e69618d99cf531f94739c76a453`
- Acceptance: accepted，2026-10-29；用户接受已评审 R3.1 架构语义及所列实施前条件。具体范围见文末接受记录。

## 背景与驱动

用户要求分析 Work 可配置审计、保存、重放，并设计同机共享 Transcript 的方式。
现有 Work 保存生命周期，也接收 Session 桥接的消息正文、流式累计快照、审批与诊断；
Transcript 已拥有消息、模型输入和用量。二者存在内容重复，但不能整体互相替代。

设计需要同时满足：执行事实可解释、完成依据可追溯、权限不因留存选择而改变、
旧历史可用、原存储所有权保持清晰。范围为本地 SDK；无跨库事务或自动恢复执行承诺。

详细事实、需求 FR-01…08 与场景见
[HW-KD-003 R3.1](../../harnesswork/key-designs/fact-retention-replay.md)。
沿用 [Harness owner map](../../harness/current-owner-map.md)、
[HarnessWork owner](../../harnesswork/README.md)、
[Goal 的两个组件](../../harnesswork/goal/README.md)与
[ARD-008 升级兼容](../accepted/ARD-008-workspace-upgrade-compatibility.md)。

## 备选方案

| 方案 | 收益 | 代价与限制 |
| --- | --- | --- |
| A：保持现状，仅继续选择内存/文件后端 | 无新格式与消费者迁移；旧回放不变 | 无法表达只保留必要事实，消息/快照重复继续存在 |
| B：Work 独立复制全部消息和证据正文，增加 audit/save/replay 布尔开关 | 单份 Work 日志表面上容易搬运 | 多份正文权威、留存不一致；三个布尔值不能表达来源不足和耐久性，审批过程也不应随 audit 开关停止 |
| C：HarnessWork 内置默认处理＋Product 配置策略，原文引用 | 通用机制一次实现；普通 Work 无需自写合同，领域只补业务依据 | 需要明确默认行为、允许覆盖范围与兼容激活；引用仍有来源寿命和读取成本 |
| D：建立机器级统一日志服务与事务协调 | 可集中查询与并发协调 | 引入部署、可用性和迁移成本；当前共享单机历史不足以证明必要性 |

选择 C，A 作为兼容默认继续存在。B/D 为比较后未选方案，不提前删除旧复制数据。

## 决定及影响

1. HarnessWork 提供默认记录、投影与通用集成处理；Product 绑定原存储/执行资源并可选配置策略，普通 Work 无需自写合同。每 Work 可在允许范围内提出差异，HarnessWork 合成、校验并冻结有效合同；领域只补业务依据。不预建策略 DSL、模式注册中心或每 Work 后端工厂。
2. 身份、生命周期、已发布的实际结果及必要依据不可关闭；默认保留自定义事实，标准桥接分离已识别的展示更新。Product 配置可选审计/诊断差异，权限和审批照常执行；不自动序列化 executor 任意返回值，也不声称自动具备全部业务审计。
3. Transcript/Blob 保持正文与内容权威。既有 Session→Work 桥接负责已确认来源的交接；不新增保存模型原文的 Goal 账本或常驻共享服务。
4. 同机共享以授权原存储、固定会话/记录来源、单会话单 writer、多只读消费者为边界。日志路径不是授权，稳定文件读取不是跨库事务。
5. 当前 Work 历史事件、状态投影与 Session 上下文恢复保持区分；不承诺重放会再次执行工具或恢复中断任务。
6. 新语义在装配时显式选用，选用后无自定义策略即使用共享默认；未迁移入口保持旧行为。真实 SDK consumer 验证通用能力，不拥有其默认分类/codec。新历史的格式兼容不能靠切回旧默认保证。
7. 区分当前状态、指定事实追溯、完整审计三种读取用途；不新增三个服务。状态观察不冒充 Goal 当前有效性，既有 assess 型查询不被静默弱化。
8. 原 get_run 的活体状态不是追加确认。新合同确认视图在 backend append 抛错后不可确认，以成功 ACK 截点或受控冷读历史为依据；不自动恢复旧 writer 或重做副作用。必要交接在原执行范围内完成，取消沿原控制裁决，通用交接清理归 HarnessWork 集成，不推给 Product。

R2 替换 R1 的候选推荐，未改变已接受架构：撤回新模式默认全量 A 的建议；把多维策略配置收束为两层；先确定读取范围，再按实测决定是否需要缓存或索引。历史事实表继续保留，用于核对必要依据而非自动生成策略系统。

R3 替换 R2 将默认合同交给 Product 的候选分工，落实用户明确要求：HarnessWork 负责开箱可用的通用机制，Product 负责策略选择。现有 owner 表中的 Product policy/default 指产品场景的策略选择，不排斥共享库提供通用缺省行为。该分工及 R3.1 的失败语义现已接受为 Target，尚未实现。

性能取舍：引用减少正文重复，却引入原来源读取与寿命依赖。热状态复用已有状态，单次追溯合并同源读取，完整审计承担所需范围的成本；冷启动单独核算。不以减少写入字节推导端到端高性能，也不允许通过省略验收换取速度。

不调整 HarnessWork/Goal 的归属、Goal 两组件、单 Work 引擎、Method 定义或既有权限 owner。
新来源合同跨越 HarnessWork/Harness/Product，因此在本共同父级记录决定；各 scope
仍维护自己的格式、执行与读取职责。接受后同步 scope 入口与 gap ledger，不把设计接受写成 Current 已交付。

## 验证、再考虑条件与评审

静态源码核查与 EV-01…16 见 HW-KD-003；固定 R3 独立三视角及 R3.1 关闭复核已完成，两项运行语义阻断关闭，数据风险保留实施前条件，详见[评审记录](../../harnesswork/key-designs/fact-retention-replay-review.md)。用户现已接受设计，不是实施验收；本轮未验证并发或性能收益。
默认合同/策略 schema、Product 持久来源绑定、消费者迁移和读取入口映射未冻结，当前不是实施就绪规格。

若出现不依赖原 Session 也必须独立携带全部审计内容的真实需求，应重新比较离线导出/保留快照与方案 B；
若出现跨用户/跨机器共享或多个会话写入者需求，应重新界定部署与信任合同，而不是放宽原 writer lease。

## 接受记录

- 接受者：用户；日期：2026-10-29。上一轮已交付 R3.1 与独立评审结论，并明确保留实施前条件；用户随后回复“可以，需要更新文档吗？”。本次据此登记设计接受，未重新推定运行或发布授权。
- 技术依据：三名独立 xhigh reviewer 对固定 R3 的评审及 R3.1 关闭复核，哈希与逐项处置见评审记录；RT-01/02 在语义层关闭。
- 接受范围：本决定第 1–8 条与 HW-KD-003 R3.1 的架构语义，包括共享默认处理、Product 策略配置、事实归属/留存、三种读取用途、确认失败及交接取消语义、同机单 writer 共享、兼容激活与验证义务。范围仍为本地 Linux SDK、同一 OS 用户与授权存储。
- 保留条件：API/schema、旧 reader/混合历史能力矩阵、持久来源绑定和留存承诺、消费者迁移与读取入口映射须在实施前细化并按原要求验证。该接受不表示这些细节已冻结，不扩大为跨用户/远程共享、自动恢复或性能收益承诺。
- 当前交付：完成接受登记、路径/索引和差异台账同步；Implementation status 仍为 not-started，本轮未启动产品代码开发或新格式激活。
