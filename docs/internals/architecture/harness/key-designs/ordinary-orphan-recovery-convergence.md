# A103：普通 Session 孤儿租约恢复归原 Product owner

- Authority: accepted bounded implementation record；完整 Goal 仍 partial。
- Design status: accepted；Implementation status: implemented for the existing ordinary path。
- Owner: 原 PackageProduct runtime；Coding 保领域资格政策与兼容入口。
- Method: 本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 职责与复用

原 Coding 两个私有函数直接执行普通孤儿恢复的 GC、根目录描述符检查、Worker
证据拒绝、epoch 资格及 registry repair。原 PackageProduct 已拥有实际 Product、
GC gate、epoch 和 lease registry，但没有整条普通恢复资格程序。本次先复用这些
既有 owner/锁/repair，再在原 product_local_wheel_runtime 模块增加两个私有操作，
完整退出 Coding 的物理程序。没有新 manager、Protocol、状态表、异步任务或 IO 回调。

Coding 保留 `coding-session:` 范围、`Coding` 诊断标签、两原私有兼容签名、平台分派
及原错误。真实调用者仍是原 factory 的拒绝→恢复→重试一次路径；其 AST 不变。
两个 scalar 参数只绑定政策，不回借产品 IO。没有宣称两平台算法去重。

## 失败、资源与兼容

POSIX 保 GC→当前性→open/fstat/路径身份→listdir→finally close→policy→registry/fence
的顺序；即使无孤儿也检查根及 Worker。Windows 保 registry 锁中 expected lease
比较→GC→原 root borrow→证据/资格检查→repair commit→当前性校验的词法区域；
无孤儿不额外借根/GC。原 outer epoch 的 assert 与 product epoch 的 registry/borrow
仍分别取自原引用，不因合法构造要求两者相同而合并读取点。

仅原 lease-absent 错误可忽略；其他错误及清理 context/cause 链保持。逐笔部分提交
不是原子批事务。Code 只提前传递实际 frozen owner 的 epoch 字段引用，不提前读取
registry/fence。持久格式、公开 API/导出、DTO 与正常 Session 工厂协调均未更改。

## 实际成本

| 范围 | 原物理行 | 当前物理行 | 增删 |
| --- | ---: | ---: | ---: |
| Coding package_product_runtime | 1820 | 1743 | −77 |
| 原 Harness Product runtime | 2277 | 2398 | +121 |
| 全系统 | 647934 | 647978 | +44 |

Coding 兼容薄入口及所有 import/类型/格式成本均包含。全 Coding 430 源113503行，
相对 Goal 起点−24252；系统1968源647978行，相对起点+13184；距15K尚98503行。
其余1966生产源及13声明/资源 SHA 不变。本批是完整 IO 职责归位，精简收益不能写成
全系统净减。两原 body 反向绑定后 AST 相同，其余完整模块 AST 保持。

## 验证与接受范围

原真实 Linux 普通孤儿 consumer 在改前通过1项。先冻结旧源28组基础及153组逐事件
故障观察，再比较候选181项：POSIX93/受控 Windows88。比较完整 trace、错误类型/
文本/code/context/cause 及残留 lease，含空集合差异、Worker 拒绝、外域/错 epoch/
错根、expected 改变、lease-absent、未知 registry 错误、根替换、FD 失败和关闭
掩盖原错、第一笔提交后失败。两个对平台无效的基础输入也保留，不计额外覆盖。

初次旧 capture 没有进程内 source guard；之后临时恢复精确旧源，以实际模块路径及
SHA 守卫重放全部181项通过，未重写 oracle；恢复候选后同守卫再过181项。仓库保留
显式 probe_ordinary_orphan_ordering.py 与 frozen JSONL（不进默认 PR route），验证
代码及数据成本另计。受控 FD71、GC/registry 模型不能证明真实平台锁、ACL、journal
或异常 identity/notes/errno；尤其不冒充原生 Windows 验证。

最终原4模块消费者35通过、48原平台跳过、7安全选择排除，含候选真实 Linux 孤儿
拒绝 Worker→修复→工厂重试路径。两生产源 Ruff、限定 mypy follow-imports=silent
通过；不是全库类型验证。原导入边界165项、文档9项及当前依赖图检查通过。
显式 probe232行、冻结JSONL181行另计。未改旧断言、阈值、工作流或新增 PR gate。
三独立职责/运行/兼容评审与 Root 有界接受及源码全帧证据保存在树外 A103；本片
不关闭整个 C10、P1–P4、五项 Hosting、AI coverage 或更早部分构造/绑定欠账。

## 后续退出条件

C10 其余兼容输入、产品内容与政策仍逐场景区分；不得将单消费者 proof 方法换目录
算成精简。优先继续核完整资源程序与已存在 owner 的接入，避免新增通用框架。
KD003 未实施，KD011/A33 待用户且未采用；完整 Goal 保持 active/partial。
