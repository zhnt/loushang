# S1调用限额与期限控制首切片评审

- Authority: descriptive；基线e1601d059；范围仅为调用限额/时钟控制的提炼和原Coding委托，不覆盖S2普通Session装配。
- 三名独立agent分别按职责/复用、运行/失败、数据/兼容核查源码并复核修正；不读彼此报告，不重复执行模型或相同测试。

| 视角 | 发现与处置 | 当前结论 |
| --- | --- | --- |
| 职责/复用 | 通用wrapper不能将任意delegate升级为prepared_request_conformant；现仅传递delegate原明确声明，Coding旧closure保留可信声明责任 | 原阻塞关闭，代码边界可交付；期限helper依赖原调用owner的一次启动合同，不是新的scheduler |
| 运行/失败 | 同样独立发现transport声明升级；核对await前计数、sticky失败、原committer/cancellation、deadline/closeout与settlement | 修正复核关闭，无剩余S1运行阻塞；原owner继续拥有任务和清理 |
| 数据/兼容 | 原异常/消息/API及旧proof/物理标识不变；初始合成fixture不足以代表真实profile | 已补原版本calculator/repository固定单批样本、公共签名与旧reader9例；本切片无兼容阻塞，仍不声称全writer/全部历史组合已验证 |

## 执行证据

专项38 passed、315 deselected；Ruff、共享两个模块mypy、生成依赖图检查通过。固定原源码reader9例通过；来源校验的独立环境复核与关键fixture15 passed。

广泛检查首次在借用旧editable环境时因源码来源不一致停止（26 passed、1 failed），不能记为产品绿灯或全部环境失败。改为此工作树独立uv.lock环境后，原失败点通过，原变更选择检查重新执行。Coding4165 passed；Harness因runtime依赖放置错误停止后修正，最终6389 passed、121 skipped、36 warnings，Ruff/mypy通过。完整结果见推进记录。

最终放置后精确回归200 passed（290.66秒），包含全部import boundary、通用限额、固定旧profile/API/proof与托管预算；生成依赖图检查通过。Harness unit额外两个examples文件3 passed（3.39秒）。

## 源码切点

| 文件 | SHA256 |
| --- | --- |
| `harness/session/call_allowance.py` | `b4645c6fd56a129a50c22bea35ba4a087e7d17cb71449f2ffda40a184f6601f5` |
| `harness/runtime/execution_deadline.py` | `76fb629a95c9ad5eafb9196f4f4dc72ba67781cfe05ebd0a40cbacb4668fb1d5` |
| `coding/adapters/_goal_planning_limits.py` | `3dab0149a6efb5412771a707a9e4d684093c0256af307f31256925640eb0b74c` |
| `coding/_hosted_goal_work.py` | `a3e7095f4397ccbd2f2efa52f265c3644111960576875497d80b91b3395a260e` |

广泛检查进一步发现runtime子树不能直接依赖AI/Agent：已将调用限额器放入现有Harness Session适配边界，期限helper留在中立runtime。三位评审均复核最终路径及显式marker传递，无剩余阻断，架构allowlist未修改。

原始报告保存在产品树外architecture-analysis/goal-refactor-20261103/s1-review-ownership.md、s1-review-runtime.md、s1-review-data.md；源码核心在修正复核后未继续改动。

## 仍保留的义务

- S2普通Session的联合受理、overlay、单一Work host与owner责任未实施，必须用户接受专项后推进。
- S3前核对每种受影响profile的limits/version选择，补与实际变更相称的writer/旧reader、未知/失败/委派与来源保留证据。
- 通用取消/收敛的资源组合仍沿原GoalInvocation/guard，待S2 owner合同落地继续提炼；不能把本首切片当作整个Goal重构完成。
- 独立代码评审与已有专项绿灯不替代当前广泛检查，也不代替用户的S2接受。
