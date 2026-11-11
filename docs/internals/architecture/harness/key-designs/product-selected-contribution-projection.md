# A113：captured Product声明到owner候选的完整投影

- Authority: accepted implementation design，限本片。
- Design status: accepted；三独立实际视角及实施owner `/root`有界接受。
- Implementation status: implemented；完整P1–P4仍partial。
- Owner: 原Session product_composition_assembly；方法为本地clean archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

原Code `_candidate`四个输入均是已经捕获的Product值。完整程序解析Resource/Tool/
Command声明、核资源成员及owner/authority、连结document/plan/trust、计算两个
GenericProduct hash并构造实际OwnerContributionCandidateEnvelope。现在由原Session
装配组件`prepare_product_selected_contribution_candidate`承接，与原handleless
candidate admission相邻；selected类型仅TYPE_CHECKING导入，静态边仍计入。

legacy `prepare_owner_contribution_candidate`要求真实PluginSelection/已发布handle，
并有不同校验/错误与证据来源，不能drop-in或伪造handle求复用。原Code `_digest`
与Core `_digest_document`的canonical JSON/ASCII domain零字节/SHA公式相同，直接
复用后删旧。其它投影原已被base/external共用一次，不算两个算法去重或IO迁移。

Code保信任矩阵、owner/贡献选择、内容及公开编译接口；原_candidate签名薄委托
只绑定3个诊断标量与纯异常工厂。无新manager、Protocol、profile状态、IO回调、
预验证、排序或缓存。原`_require_product_locator`/`_digest`没有其它已发现生产/测试消费者，旧体退出。

保持原顺序：snapshot/manifest→插件身份→payload→Resource成员→Spec构造→owner/
authority→document索引→证据hash→first matching trust→候选hash→Envelope。
file要求确切成员；directory拒同名file且要求带斜线的子路径前缀。保原KeyError/
StopIteration/codec错误不包裹，保四处Code消息/code和两hash所有字段。其余Code/
Core非import定义AST同；完整body经精确Name内联与政策/hash逆绑定后AST同原。

实际成本Code747→618（−129）、Core1667→1824（+157）、系统+28，含所有类型/绑定/
导入，不称系统净精简。1969源中其余1967及13资源SHA同，Coding112949/系统648164，
较Goal−24806/+13370，距15K97949；Coding专属信任/内容/owner逻辑仍计Code。

原2个真实fenced Product startup/session节点过，新同2节点过；原31固定观察回放
和新31回放均过，持久同31再过，不累加成覆盖数。读取trace、实际typed Spec/
Envelope全record+hash及错误FQN/args/code/cause/context/suppress作完整比较；原输出
经sort_keys归一，不是动态插入序/wire字节、异常identity/notes/pickle或全部构造
故障证明。observer复用真实manifest/declaration parser，但snapshot authority构造
被绕过、部分事实/无效plan被控制、View跟踪getter；不是物理Store/FD授权证明，
不将untrusted/no-membership私有投影成功解读为公开准入放行。

初31为27过/4目录输入setup失败（未执行目标）；仍在旧源上改用已有external目录
输入，补4过后最终31原回放过，原27未重录。两次树外原型静态误替换在安装前
修正；只记录原因/观察到的SHA，旧中间bytes未保留，不冒称运行反例/完整原件。

边界共172过、3项RCP2旧消费者库存失败，与改动前同节点及完整消息相同，未修改
原测试/gate；不称全架构绿。两源限定mypy/Ruff、cold import和依赖图检查通过。
`tests/coding/probe_selected_contribution_projection.py`318行与JSONL32行/54290B无损
保31旧值、2实际模块origin守卫，无capture或未来SHA钉死；350测试行单列且不进入
默认发现。三实际评审、源码/成本帧、初失败/修正及JUnit保存在树外
`coding-convergence-continue/a113-selected-contribution-projection`。

其它Hosting/AI coverage/构造绑定及历史失败仍未关闭；KD003未实施，KD011/A33待
用户且未采用。完整Goal保持active；本片不授权淘汰支持/存量格式或接受A51形状。
