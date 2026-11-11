# H-COD-KD-004：三视角审查与代码证据

- Authority: descriptive review evidence。
- Design status: R2 accepted for bounded implementation。
- Implementation status: implemented；本地冻结切片的验证与三视角代码复核完成，非整个 Goal 完成。
- Owner: 原 Harness Runtime API／Foundation 内部共同原语，各资源 owner 不变。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- [方案](owned-task-join-convergence.md)关联原整体 Coding 收敛；不是新任务队列、清理引擎或完整 Goal 接受。

三位独立 reviewer 分别对职责／复用、运行／失败、数据／兼容进行静态核查，未读彼此报告、修改产品或运行 async。R1 外置完整替换清单 SHA256 为 `8987d04addd3867861f7e40865a37c822d6741ffea0da8af012734fd6aaae08d`，有一致阻断：Foundation 第三函数残留未定义 AppHost Runtime 类型。future annotations 仅延迟解析，不使该依赖合法。

R2 独立清单 SHA256 为 `2c4773981c80d0f73906ddd0e82e5a01e316d14664aa6b84b9cbd4afab99b92a`，只将其签名改为同模块 `Task[T] -> T`；三 body 与其它十四个候选模块均未改。三位 reviewer 独立关闭该阻断，允许实际替换及原行为对照。没有反向导入 AppHost 或用 Any 避开错误。

原 150 个 Task 观察在旧十四模块 SHA 守卫后生成，fixture SHA256 为 `9a9798c92af3c0d090bb38481df3f7b6d1aba39bc32028208bf31d146dcd3da2`；原 pytest 150 passed（3.76s）。另独立进程映射完整外置 R2，记录十四个真实 `__file__` 与十五个 callable 的 Foundation 归属，150 项结果相等，未重写 expected。这是候选运行证据，不代替实际工作树验证。

实际替换后首组为 195 passed（9.60s）。最终工作树按真实 package 路径整理九处 imports，三算法及其余非 import／目标函数 AST 不变；实际源码少 121 行，其中九行是 import 布局成本差异，不能全部描述为算法净删。原 AppHost／Hosting／Worker／Coding 关闭启动组合另有 337 passed（115.96s），该进程在末次 import 排序前启动，只作相同算法的调用链证据，不冒称完全匹配最终字节。

A29 冻结清单含 161 个 source/test/fixture、18 个增量路径，SHA256 `3dbf01dd6313deafa3a957ac9f3aae7120e985468716f93a01b0b84ec4525a53`。最终冻结范围的重放／边界、三视角代码复核及最终计数另补，不据上述设计审查提前宣称代码接受或整体 Goal 完成。


## 最终代码复核与终态补证

三位 reviewer 独立核 A29 的 161 文件指纹、18 个增量、实际十五个绑定及三组 body：职责／复用、运行／失败、数据／兼容均无本增量阻断。实际源码与 R2 只有九处 imports／空行差异；原 receiver 与 caller 其余 AST、私有 seam、fixture 字节未变。数据 reviewer 另独立逐文件重算原 C08 及全产品数量，吻合当前账目。

三份报告写作时最后回归尚在运行，保留其当时待回收说明。本节由实施 owner 补记真实终态：最终冻结源码 360 passed（97.98s），15 个增量源码 `mypy --follow-imports=silent` 通过，138 个冻结 Python Ruff、161 live hash 通过。没有将排序前337项当作最终字节证明，也没有合并重叠测试数来夸大覆盖。

实施 owner 接受此有界片：原三种语义及 Task／retry／cleanup-debt owner 不变、重复原体退出、计全部成本。系统仍净增608，原C08仅减2,346；CodeGoal继续active，未提交、推送或开放平台。


## A57 有界追加：候选与实际三视角及运行终态

本片清单SHA256 `0f9c163b4d60dcba083183f71be030bf16923ee16489b5cc393c4c91cb4a4ed0` 固定两个Coding模块。三个独立视角分别核对before/source及actual，实际源码逐字等于候选；原两个producer无有值return、取消政策各归原原语、void显式discard、真正资源/Task/retry/debt归原owner。职责/复用、运行/失败、数据/兼容均无本片阻断；不继承A29对void的接受，另作此处消费适配判断。

评审报告写作时实际测试仍pending，原报告保持不变。以下为实施owner补记终态：

| 验证 | 范围与结果 |
| --- | --- |
| 原路径旧结果复放 | 98606，1 passed/2.37s，原source SHA/规范module路径、40固定观察 |
| 双模块候选 | 78850，1 passed/5.95s；81513，2显式源shadow silent mypy通过 |
| 实际普通路径无overlay | 68855，1 passed/8.34s；原expected未改，两actual SHA/规范路径 |
| 原业务回归 | 88167，完整`test_apphost_composition.py`与`test_hosted_application.py`，22 passed/19.08s |
| 实际窄类型 | 60495，2显式源silent mypy通过，非完整依赖图 |
| 静态与计数 | 两源Ruff/format、diff、其余AST和245累计源/测试/fixture指纹通过；独立git原对象与全活树计数 |

首次freeze终态输出因上下文截断不可用，虽然完整expected存在也不据此记成功；后来原代码复放的可追溯终态单列。40项只覆盖有限事件调度，未穷尽uncancel清零、完成/取消同到和进入helper前取消；cause只记录类型，惰性close端口不证明资源权限，原业务测试另列不与观察数累加。源码逐分支对应、限定真实None producer及显式void适配与这些证据共同支持本片接受，不推导全调度或原生平台证明。

实际全成本879→857，Coding/系统−22，Harness/Foundation0，结构−21/格式−1。原C08不变、缺口3,464；全生产仍+937。A42广依赖237错误/8文件与A55已归因原main的skill断言失败保持未修复，不以本片通过关闭。实施owner接受此有界代码追加，无新增gate/平台/付费模型/远程发布；整体Goal仍active/partial。
