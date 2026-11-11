# H-COD-KD-002 R2 三视角设计评审记录

- Authority: descriptive review evidence；不代替用户接受架构工作件。
- Design status: accepted；内部设计复核无剩余阻断，用户于 2026-11-06 明确要求“实施R2”。
- Implementation status: implemented；本地交付，有较广既有装配失败限制，详见实施记录。
- Owner: 执行者负责汇总；职责/复用、运行/失败、数据/兼容分别由三个独立 reviewer 核查。
- 设计评审时冻结对象：[专项设计 R2](session-tool-pack-binding-convergence.md)，SHA256 `366f5c698517d38839ecee82fcf88e0f4c3b253ae8e8f854377e0c0bebf2fe61`。
- 方法：本地 clean archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。评审没有获取远程更新。
- 源码基线：`8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d`，设计评审时三个原 Tool owner 文件未修改；其他进行中的源改动固定于 A20。

## 独立结论

| 视角 | R1 判断 | R2 增量复核 |
| --- | --- | --- |
| 职责/复用 | 存在具体桥接缺口，原 Scope/Binding/controller 已提供底座；Base 只共用 Slot 合理 | 无新增阻断；四字段映射、family 和同 scope 保留不产生新权威 |
| 运行/失败 | 原同步投影、注册顺序、回滚与 dispose 重试可由单份连接保持 | 无新增阻断；保留原异常优先级，不能把原 stage report 失败冒称为已有新 debt |
| 数据/兼容 | 方向可行；实施前需补原 RegistrationOwner 精确映射 | DATA-KD2-R1-01 在设计层关闭；实现和原行为冻结尚未验证 |

R1 SHA256 为 `eb1aeb2fd2d69b0fc653cb2e4081b362dd3b0fe2a4b0e69b0796861ef5fe7590`。R2 显式列出 owner_kind、owner_id、runtime_id、generation 原值，说明 family 标记不得参与持久身份或按每次 bind 创建；补充 SourceInfo、同 scope 清理以及迁移前固定原行为的要求。三位 reviewer 分别核对 R2 与当前源码，没有互相采信结论。完整报告和冻结对象保存在产品树外的本任务证据目录。

## 实施前及代码验收须关闭

- 固定原 owner 四字段与 retirement receipt/reference/hash；不能仅检查工具名称相同。
- 固定 SourceInfo 公共投影与值比较，保留公开 Port/Slot/owner 的构造形状和稳定错误 code。
- 验证 LSP/Arch 跨域拒绝及同域不同 owner 的原接受范围；不能用 per-bind token 额外收紧。
- 领域定义投影必须完整发生在第一个注册之前；部分注册失败保留原回滚和原异常。
- 区分 rollback 返回 `report.has_failures` 时添加 note，与 rollback 本身抛错时的异常/context 优先级；不新增未设计的 cleanup-debt 状态机。
- dispose 失败后 Graph 持有同一 generation/scope，原重试凭据不提前释放；retirement 继续沿原 `allow_open=True` 与确切 contribution_ids。
- Base operation_set 的 invalidate 顺序和 Command 专用路径保持；不可为统一三份 Tool owner 丢掉这项清理。
- 所有新类型、适配、错误投影和配置计入真实净量。系统净减 200 行仍是挑战预算，不是本轮已验收成果。

现有原 LSP opt-in、Arch provider 与 Base owner 相关组合基线为 **41 passed（86.06s）**，由原 wrapper 在 sandbox 外、磁盘 runtime、worktree PYTHONPATH、`not live` 执行。该组合不完整覆盖上述 identity/family 矩阵，不能据此称迁移已验证。评审者本轮只做静态核查，没有运行这些测试或修改产品代码。

R2 内部设计审查完成后，用户明确要求“实施R2”。这构成该设计的用户实施接受，不构成实现或数量验收；完整 Coding 收敛与原 Goal 均未完成。


## 代码实施与评审补证

用户明确要求实施 R2 后，本地完成共享桥接、原实现合同固定及三视角代码评审。A21 的提前固定字段问题已在 A22 用三属性只读端口修复，O-A21-01/RT-A21-01 及 fixture 来源记录缺口关闭。Binding 元信息保持 bind 时点，stage 定义完成后读取当前 admission/scope，逐工具读取 mode，receipt 读取当前 contribution id；不增加生命周期驱动或 Product context。

原 41 项相关组合与 39 项固定合同/Graph 组合通过，实际 Coding −308、Harness +176、系统 **−132**，未达到争取 200 行的预算；较广 Session 装配的两项失败在原 owner 对照中同样出现，不能据此宣称所有回归通过。完整源码计数、测试与局限见[全层推进记录](../coding-convergence-progress.md#tool-pack-r2-本地交付a22)。设计评审时的 R2 原指纹绑定产品树外冻结对象；当前文档已更新实施状态并追加本补证，不冒称字节仍与原冻结稿相同。
