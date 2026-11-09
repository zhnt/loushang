# H-COD-KD-004 R2：既有 Task 等待算法的单份实现

- Authority: accepted key design；代码验收另记。
- Design status: accepted；实施 owner 在整体 Coding 收敛授权内接受，三视角 R1 类型阻断已于 R2 关闭。
- Implementation status: implemented；本地有界切片完成回归与三视角代码复核，整体 Coding Goal 未完成。
- Owner: 原 Harness Runtime API；跨 AppHost／Hosting 使用的 stdlib 原语实现归既有 Foundation 内部模块，各生命周期 owner 不变。
- 来源：[整体 Coding 收敛](../coding-convergence-progress.md)；方法为本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 基线：`8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d` 加 A28；本片十四个原模块尚未在此前切片改动。

## 问题与边界

Coding、AppHost、AppService、Hosting 与 Harness 的十五处模块级 Task 等待有重复实现。它们不是十五种生命周期 owner，也不是完全相同的一种取消合同。原 Task、Session、关闭重试和 cleanup-debt 的持有者继续负责真实资源；本片只把每种原算法保留一份，不新增管理器、任务表、后台运行、超时、取消请求或清理回调。

AppHost／Hosting 不为复用而反向依赖 Harness。只有 asyncio/typing 的共同算法放在既有 Foundation 内部 `_owned_tasks`；Harness 原 `await_owned_task` API 和原私有符号薄绑定同一原实现。Foundation 入口不增加顶层公开导出，不改 Harness `__all__`。

## 三种原合同

| 原算法及使用者 | caller 被取消、子任务随后失败 | 多次 caller 取消 | 计数清零后第二次取消与子任务成功交错 |
| --- | --- | --- | --- |
| Hosting 等七处，首取消优先 | 抛首取消，子失败为 cause | 记第一个 | 仍传播首取消 |
| CH-01 及三处，失败优先 | 抛原子失败 | 正常完成后传播最后取消 | 原 `return task.result()` 返回成功值 |
| Coding／AppHost／AppService 四处 | 抛原子失败 | 正常完成后传播最后取消 | 原 `break` 后仍传播先前记录的取消 |

三种算法各有一个具名内部函数，不用模式旗标强合，也不把它们替换成会取消子任务的等待。原十五个 module/function 名字保留为绑定，原 task 的创建、await 调用点、重试、取消请求、清理顺序、错误翻译和持有字段不改。void、deadline、返回取消对象、包含额外副作用或错误映射的其它等待不在本片。

共享函数均为 `Task[T] -> T`，不引用 AppHost 的 Runtime/Report 类型。R1 草案漏留了一个产品类型注解，三位 reviewer 独立发现；R2 只泛化签名、保留 body，修复而不向 Foundation 反向导入产品。

## 兼容与成本

原公开 Harness API、私有 callable 名字和 monkeypatch 入口继续存在；不承诺私有函数的 `__module__`、反射名字、traceback 或新 pickle 的引用位置逐字相同。源码及现有测试未发现将这些反射字段作为持久协议／owner 身份的实际消费者。真实 AppService 的 join monkeypatch seam 保留，不能删原取消交付负例来换绿。

完整外置替换包含十四个原模块的 imports/十五个别名及 Foundation 完整 75 行，实际系统 **−112 行**，其中 Coding 仅 **−11 行**。原定义池 257 行不是净删；本片不能承担 C08 的数量线或完整业务动作验收，也不能以系统削减量冒称 Coding 大幅下降。

## 验证、接受及未完成项

改前按十四个原模块 SHA 固定 150 项实际 asyncio.Task 结果，包含已完成／运行中成功与失败、子任务取消、一次／多次 caller 取消、取消后失败及真实 uncancel 交错。固定结果 SHA256 为 `9a9798c92af3c0d090bb38481df3f7b6d1aba39bc32028208bf31d146dcd3da2`。原代码经 pytest 复放为 **150 passed（3.76s）**。

候选的三个 body 与原组按局部变量／TypeVar 重命名等价；十四模块其它非 import／目标函数 AST 不变。独立进程按精确模块路径映射加载完整外置候选，逐个记录实际 `__file__` 与 Foundation 原语归属，150 项结果与原 fixture 全相等，未重写 expected；这仍不是实际工作树或原业务集成回归。

R2 外置清单 SHA256 `2c4773981c80d0f73906ddd0e82e5a01e316d14664aa6b84b9cbd4afab99b92a`。职责/复用、运行/失败、数据/兼容三份独立增量审查均关闭 R1 类型阻断，允许受控实施和固定行为对照。实施 owner 的接受仅限这份三原语/原 API 薄绑定方案，不替代重要架构工作件用户评审或整体 Goal 验收。

实际工作树的固定结果重放、原 CH-01／Hosting／AppHost／Worker／Continuity 回归、边界检查和三视角代码复核仍需完成。没有新 gate、平台开放或付费模型；本地 Linux 观察不推导原生其它平台验证。


## A29 本地代码接受

冻结清单 SHA256 `3dbf01dd6313deafa3a957ac9f3aae7120e985468716f93a01b0b84ec4525a53`，161 个 source/test/fixture、18 增量路径。实际包路径的九处 import 排版带来额外九行下降；完整代码净减 **121**，其中 Coding **12**，不覆盖 R2 原型 −112 的历史记录。十四模块其它非 import／目标函数 AST 与原体相同，三新 body、泛型和原名绑定有独立复核。

最终冻结范围为 360 passed（97.98s），15 增量源码窄 mypy、138 Python Ruff、161 live hash 通过。三位独立代码 reviewer 均无阻断，实施 owner 在已有授权内接受本片；最终回归终态另补于[评审证据](owned-task-join-convergence-review.md)，不将其静态评审冒称亲自跑过测试。全产品仍净增608，八千行与完整 Goal 未完成。


## A57：额外两个 Coding 等待消费者

这是原 owner 内的有界复用追加，另经三视角候选/实际评审；A29的void排除范围保持历史原样。`apphost_composition._join_failed_construction_cleanup` 仍一次create_task原清理任务，借用已有公开 `await_owned_task`；只删除等待循环。`hosted_continuity._join_void` 保留显式void适配，await原已导入`_join_preserving_cancellation`而不return，成功值仍被丢弃。两真实producer均无有值return，失败/取消顺序仍按各原语；canary值翻译、主动取消、多任务drain和Continuity特殊清理不适用，未改。

不新增Harness/Foundation代码、API、管理器、回调模式、Task、取消请求或重试。字段、锁、业务方法、真正清理及debt所有权AST不变；原私有调用名保留，实际栈位置可变化。完整源码净减22行，结构−21/格式−1，原C08为0；不能把此片记作原8K指标完成。

本片frame SHA256 `0f9c163b4d60dcba083183f71be030bf16923ee16489b5cc393c4c91cb4a4ed0`。固定旧40观察SHA256 `0715efda53b04a1d32bf670bcf7375338b4545836f68759e2fabbb5a99aaeb4e`，实际无overlay重放通过；两个完整原业务文件22 passed（19.08s），实际两显式源silent mypy通过。三视角无本片阻断，实施owner在现有授权内接受，局限及终态详见[评审记录](owned-task-join-convergence-review.md)。未宣称重要架构工作件新增用户接受或整体Goal完成。
