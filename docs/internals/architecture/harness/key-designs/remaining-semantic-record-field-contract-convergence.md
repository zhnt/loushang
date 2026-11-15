# 四类剩余semantic record字段契约去重

状态：A197实际有界接受，2026-11-15；完整Coding职责Goal仍开放。
沿用原字段契约决定，不新增组件或公开协议。方法咨询为本地archmethod master
0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e，非上游同步声明。

## 职责与选择

Checkpoint、Windows history join、activation base V2与provisioning retained attempt
共44个有效字段由Code与既有Core方法基类重复声明。Core保唯一中性字段契约，Code保
7个实际peer名义类型覆写、原FQN/profile/schema/验证及codec。使用标准dataclass
(frozen=True, init=False, repr=False, eq=False)，原Core __slots__=()不变；Code原
frozen/slots dataclass继续生成原物理槽与构造/比较/hash/repr。没有新存储、反射注入、
字段DSL或影子槽。直接Core slots=True会改变Code ownslots，不采用。

四类当前默认值已相同，不迁改默认。provisioning Code保`_Record as _Record`真实
运行时导入，以便Code生成构造函数在自身globals解析继承的字符串注解。
共享模块的A196另外两完整定义逐字不动，不重复计益。

## 合同与代价

Code ownannotations缩减，继承__dataclass_fields__增加8个ClassVar pseudo-fields；
Core成为dataclass并有frozen setter。fields()/wire schema排除pseudo-fields，不能
声称所有原始反射信息相同。浅frozen身份字典的原语义不变。

| 完整来源对 | Code原→现 | Core原→现 |
| --- | ---: | ---: |
| Checkpoint | 303→288 | 292→294 |
| Windows history join | 100→93 | 276→278 |
| Activation base V2 | 40→32 | 193→195 |
| Provisioning retained及同模块保留类 | 115→106 | 312→313 |
| 合计 | 558→519（−39） | 1073→1080（+7） |

raw与统一格式相同，系统净−32，含全部import/typing/profile成本；37中性重复声明
及声明间空行退出。该批是字段去重，不是完整Worker authority或C07完成。

## 验证与接受

三个独立视角核职责/运行/兼容，冻结八源接入；同10个原模块原1138项改动前149.06s、
实际161.84s全过，0fail/error/skip，原观察和12份fixture逐SHA不变。
939原public-values含21个固定ownannotations类，另171受控reader、12原wire/旧
protocol4 pickle及其余16项；不改原期待，不扩大为nativeWindows或所有pickle协议证明。
八源实际project mypy与Ruff通过。无新test/probe/oracle/fixture或PR gate。

父进程10模块路径/SHA及19递归code字段守卫，54源码声明callable、每阶段1138nodes/
2276前后checks；不覆盖生成dataclass函数或子进程。四个构造函数的get_type_hints
是另进程有限API检查，解析JSON相同，原命令/PYTHONPATH/退出码另记；其输出未内建
模块路径/SHA，不能借pytest守卫冒称同进程来源固定。

2059源仅八源变，434份Coding现110202行，距15K95202。源码指纹、运行日志、原/新
节点及三视角报告保留产品树外。当前计量见[清单](../coding-responsibility-inventory.md)，
后续优先级见[队列](../coding-responsibility-priority.md)。P1–P4/KD003/KD011仍开放。
