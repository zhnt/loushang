# Goal共享重构最终评审与关闭记录

Authority: descriptive。范围为用户接受的GMW-RF-001 R2 S0–S4a与GMW-KD-RF-002 R2；真实lmux wire、日常菜单、新通用规划器及跨进程自动续跑不在本次范围。

## 固定切点与过程

完整三视角复核固定6f943992e20bda885185f7c6b925daaa83800068，对照e1601d059。审查重新核对全部职责/调用链与数据合同，不只累计窄切片报告。随后合入origin/main 58fd9e230，集成切点bbaa4b59f；上游153文件与我方91文件无文件重叠。上游既有GUI和门禁变更来自已合入main，不是本次新增检查。

最终六文件关闭快照manifest SHA256：cb55fc5c590bd5e3a870e4fb2eee927d1e673a9890da4b34553c1687390d2f80。三位独立agent分别复核职责/复用、运行/失败/权限、数据/兼容/验证，以下源码及指定组合验证问题均关闭。实施负责人据此接受源码集成；选择检查和远程交付仍须实际结果，不由源码评审代替。

原始报告位于产品树外architecture-analysis/goal-refactor-20261103/final-{ownership,runtime,data}-review.md及对应closure.md。方法沿用本地archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e。

## 发现与处置

| 发现 | 处置与关闭证据 |
| --- | --- |
| 应用消息direct可越过保留并污染规划来源区间 | 原ApplicationInputRuntime注入原Session admission。direct与trigger_turn在第一次await前核对current/unbound；普通输入ticket使候选失效并跨原commit与projection持有。已commit/settling执行期间明确拒绝即时输入，不改变delivery_mode或另建队列。调用方可在收敛后显式重试，原application_message_id、耐久committer和幂等投影保持 |
| 撤权×关闭失败×waiter取消未在Goal实际链中组合验证 | 原application-local Goal路径中取消客户端waiter仍保原invocation；scope关闭撤权后原query/retry被拒绝；Goalwriter关闭失败保原Goal与尚未释放的父Session；只由同一server app.close重试。操作/run/取消事实及模型数不变，无新batch。所选writer故障覆盖Goal Scope到父Session链，不泛称所有child/native故障组合 |
| 旧calculator planning_prompt仍留重复模板 | 旧路径薄再导出同一builder，保留planning_instructions原符号及原prompt字节，无第二活动模板 |

即时应用输入拒绝只针对与既有执行冲突的direct/trigger模式。原next_turn、steering、follow_up继续原队列合同；不把即时模式静默改投下一轮。已经受理的direct原耐久操作不由clear回滚，queued/preflight的clear仍沿原generation合同。

## 实际补充验证

- 原Session direct/trigger使候选失效、commit/project进行中不能保留Goal、未streaming但已commit时写入前拒绝、closed/stale拒绝、原身份重试只投影一次，以及公共SDK send_message真实规划来源不混入：8 passed，16.37秒。SDK dict重试可生成新内部ID，同ID幂等证据来自原runtime ApplicationMessage测试。
- 原托管撤权/关闭失败/waiter取消组合：1 passed、15 deselected，9.40秒。
- 原Session runtime、ApplicationInput、extension agent profile、Coding应用输入合同、固定旧API/proof与selector差分：47 passed，4.07秒。范围与前项有交集，不相加。
- 六文件Ruff及三源mypy通过。首次测试等候了错误的事件kind、另一次命令路径写错；已中断/修正测试装配，未改产品事件或放宽检查。

首轮既有check-changed通过docs、architecture、AI937项（90.77% coverage）与Agent167项，因同步新main及补齐问题而主动停止尚未完成的Coding检查。AI/Agent源码、相应测试、protocols、scripts/ai、uv.lock和pyproject在集成前后tree对象一致；不把中断的Coding当作通过。后续其余选择检查的最终结果另行登记，不能把首轮部分结果冒充完整check-changed完成。
