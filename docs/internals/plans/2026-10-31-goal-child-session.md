# Goal 批次执行 Session：集成准备与实施检查点

- Authority: descriptive；状态：R3 独立三视角设计评审完成，用户已明确授权实施 R3；实现与离线验证进行中，代码三视角评审待实现后启动。
- 设计：[GMW-KD-SESSION-02 R3](../architecture/goal-method-work/delegated-session-execution.md)；[三视角关闭记录](../architecture/goal-method-work/delegated-session-execution-review.md)。
- 工作分支：feat/goal-child-session；代码 lane：.worktrees/code。未修改有历史脏资料的 Harness lane。

## 已有能力集成核查

2026-10-31 使用 git merge-tree 检查 Harness 修订 `3aac81d8e` 与已完成仓库 Goal 分支 `f024cb734` 的组合；该命令只生成候选 Git 对象，未修改工作树、分支或产品代码。此核查不是运行验证，也不构成新模式实施。

| 接缝 | 核查结果 / 实施时处理 |
| --- | --- |
| 原仓库 Goal profile | 保留 RepositoryTask/Profile、BatchPlanningPolicy、独立验证、可信评审和 detached 读取；不重写第二套仓库 Goal |
| _goal_planning.py | 唯一文本冲突是 prepare 已抽到 _goal_planning_shared.py，而主线后来在原 prepare 加入 Transcript 来源绑定。应将现有绑定逻辑移入原共享 prepare，不能简单选 ours/theirs 或保留重复 prepare |
| CodingGoal.open → _open | 自动文本合并会保留公开 transcript_retained_until 参数，却不传入新 _open，后者仍使用该变量。必须同步参数传递与校验；无文本冲突不代表接口兼容 |
| 规划 executor | 旧共享 prepare 仍使用 SessionTurnExecutor(turn=...)，主线已使用 turns=(turn,)；合并应采用当前合同，并保留 _bind_source |
| 仓库 profile 实施 executor | 同 Session 原路径也须协调现有来源准备；未来 child 委派路径明确不绑定父 Transcript。父规划来源与子实施报告分别验证 |
| 来源冷读 | 按 R3 接入受支持仓库 policy 的窄分支，保留未知 policy、错绑与损坏错误，不把这些情况改成 not_declared |
| 失败批次观察 | 原 delegate 失败时两种成功报告都可能缺失；仅新委派 operation 按 R3 区分局部失败轨迹与成功报告损坏，保护旧历史语义 |

## 授权后的有界实施顺序

1. 已完成：底座以 caaff3945 本地合入 main，并同步此任务分支；源代码修订为三视角复核的 3aac81d8e。Coding 3991、Harness 5959、TUI 单元 1322、render contract 317 项通过；详见[底座交付记录](2026-10-31-child-session-consolidation.md)。
2. 接续并协调原仓库 profile 与同 Session 来源记录，先验证旧公开入口、默认路径、原真实任务合同和冷读。历史 #125 修正不得再次作为新缺陷修复交付。
3. 按已接受 R3 实现 Product 私有委派适配，调用原 Harness/Method/Work；先接 reuse/fresh，验证 A→A→B，再接固定来源 inherit。按 DS-01—10 分别验证多 Session 身份、输入、取消、容量/清理、历史及证据，未启用模式明确拒绝。
4. 对冻结的原始缺陷工作树执行新模式验证；新模式需要自己的真实运行证据，不沿用旧成功结果。没有发生实质调整就如实保留未证明状态。
5. 完成独立评审、现有变更路由和交付记录；不扩 CI 门禁，不以设计完成声称实现完成。

2026-10-31 用户明确要求“请你开发实施R3”，随后补充“开发实施完毕R3后启动三视角评审代码”。已合入原仓库 profile f024cb734，合并提交 f410f10ce；原仓库 Goal 19 项离线测试通过。上述集成事实不代表新模式验收通过。
