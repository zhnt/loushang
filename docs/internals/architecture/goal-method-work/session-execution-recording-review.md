# GMW-KD-SESSION-01：三视角独立设计评审

- Authority: descriptive — review evidence；Design acceptance: accepted by user (2026-10-30)；Implementation status: in-progress。
- 对象：[Goal 执行上下文与 Work 来源记录](session-execution-recording.md)，最终固定 R2.1。
- R2.1 SHA-256：`685db572c9b771d5f033dc7eb064ff5d5e24948de16be2576ee82d980aa3533e`。
- 源码基线：`2d6ed6d64469abe4e3e65453205be9b56ecf8119`；R1 草案保存于 `41d72625c`，SHA-256 `f10de5d511b3d1ecf447d07a053dcdc981eaa988bcb26e29ccd41f03a89e8221`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。仅本地版本核实，不声明远程同步。
- 评审方式：三个独立、空上下文 xhigh agent，各自读取固定稿和源码，不读取彼此报告；主 agent 汇总、修订，原 reviewer 对固定 R2 / R2.1 复核。

## 范围与依据

用户要求保留三种需求：同一 Session 多批 Work、新鲜上下文子 agent、继承原上下文子 agent，并明确“尽可能复用已有能力，不要重复建设”。本轮只细化同一 Session 的 Coding Goal 记录/来源接入；后续委派方式核实已有机制与限制，不实现子 Work、持久子 Transcript 或新调度器。

评审覆盖职责/复用、运行/失败、数据/兼容，并沿 Coding、HarnessWork、Harness 交互作综合检查。部署只覆盖同机本地 SDK 和 writer 停止后的新进程只读；远程入口、其他平台及在线模型不在本轮验证范围。全部取证为静态源码与场景走查，未运行 pytest、异步探针或产品功能，不将设计闭合当作实现通过。

## Findings 与关闭

| 合并项 | 独立发现 | 修订与关闭依据 |
| --- | --- | --- |
| 准备时期限检查不足 | OWN-01 / RT-01 / D-02：准备与实际 accept 间还有确认、意图落盘，不能宣称时钟与受理原子化 | §5.1 明确准备、两次 confirm、每次 prompt 前的检查 owner 和结果；复用原 source.check；到期不延长、不重执行；R2.1 限定仅有来源合同的候选，静态/验证不被隐含拦截。三视角关闭 |
| 规划 turn/spec 不兼容 | OWN-02 / RT-03 / D-01：现 executor 使用单 turn，spec 却有 planning step，原 _expected_handoffs 会拒绝 | §5.2 规定 turns=(turn,) 与原单步 spec 对齐，保留 planning、0:0、prompt、权限包装及响应证明；不放宽共享检查。三视角关闭 |
| 冷读清理 owner 无交付路径 | RT-02：函数局部 reader 在 finally 关闭失败后，不能仅靠“保留”字样保证调用方可重试 | §5.4 改为调用方持有并注入原 reader，函数只借用；调用方统一关闭、保留错误与依赖、对同一对象重试。无需新隐藏 owner。运行视角关闭，另两视角复核相容 |
| 动态输入与缺组边界 | RT-04：steer/follow 到达时点影响捕获范围，应直接覆盖 | GS-10 覆盖 prompt 内消费、handoff 中到达、残留 pending input；不虚构额外交接组或完整审计。关闭设计提醒，运行验证待实施 |
| 缺合同与缺原 Work 不可混用 | 数据视角补充：missing/conflict/corrupt 不能降级为 not_declared | §5.4 只对有效且关联核实的 Work 使用 not_declared；未提交单列且检查矛盾；复用原关联核对规则。关闭 |
| Runtime 级持久策略 | 数据视角补充：Goal 候选/dispatch 当前不透传逐批 recording_policy | §5.1 明确 Product 只配置原 WorkRuntime 的策略，不改 Goal core 或依赖未透传字段。关闭 |
| 到期结果枚举与正文对齐 | R2 运行/数据视角补充：GS-04 漏列 candidate_outdated | R2.1 补全准备时、准备后 intent 前、intent 期间及执行前/中到期场景，并区分无来源工作；三视角窄复核通过 |

## 综合结论

| Reviewer | 固定 R2.1 结论 |
| --- | --- |
| `/root/goal_session_ownership`，职责与复用 | 无技术阻断；原 Work、Session、Multiagent 的责任和权威保持；可交用户评审 |
| `/root/goal_session_runtime`，运行与失败 | RT-01—04 设计问题关闭；确认、包装、取消、关闭与冷读 owner 可协同；可交用户评审 |
| `/root/goal_session_data`，数据与兼容 | D-01/02 及补充意见关闭；逐 Work 期限、库授权、legacy/缺记录分类及规划证明边界一致；可交用户评审 |

三个 reviewer 都确认：无需第二个 Work 引擎或 SessionWorkRuntime、Goal fork、子 agent 控制树、来源 codec、摘要算法或第二份引用索引。保留子会话 persist=False 的现状；上下文继承与文件隔离、持久记录分别讨论。当前 Goal 领域验收仍独立于消息来源完整性。

实施义务是设计稿 GS-01—GS-10；设计通过不替代其执行证据。优先补既有测试的接入断言，仍遵循项目离线/沙箱外测试规则；无新增 CI workflow、路由或合并门禁。

## 接受边界与交付

主 agent 完成内部技术评审及 findings 收敛后，已按用户“系统环境图等重要工作件需要我评审”的要求提交固定 R2.1、环境图、接口边界及评审结论。用户于 2026-10-30 回复“同意，请继续”，接受并授权实施同 Session 第一切片；该记录基于本次实际回复，不追认此前草案为已接受。

此次接受的具体内容：§3 三种需求与第一切片范围；§4 黑盒环境及组件协作；§5 默认 recording v1、可选显式期限、共享准备接缝和 caller-owned 冷读 reader。两种子 agent Goal 接入仍后排，不默认为已接受的持久执行扩展。上面的 SHA 指用户审阅的固定正文；后续接受/实施状态登记不重写历史评审对象。

文档校验记录：9 项既有文档不变量及变更文档链接检查通过；仅文档变更，产品源码未修改。设计变更保存在本地 `docs/goal-session-recording` 分支，未发布远程。
