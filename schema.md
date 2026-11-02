# 账本数据结构（v1.0，已冻结）

本文件定义 `premise-ledger` 的唯一真相。**后续所有代码、测试、数据集都以此为准；冻结后不新增字段，只做向后兼容扩展。**

## 1. 一句话模型

账本是一张**有向无环图**：

- 节点只有两种：`premise`（我假设了什么）、`claim`（我推出了什么）
- 边只有一种含义：`X 依赖 Y`（Y 是 X 的前提）

所有能力都是这张图上的查询：谁支撑你、你倒了谁跟着倒、有没有人绕回来靠我。

## 2. 节点字段

| 字段 | 类型 | 适用于 | 说明 |
|---|---|---|---|
| `id` | string | 全部 | `A1`…前提，`C1`…结论，由内核分配，**永不复用** |
| `kind` | `premise` \| `claim` | 全部 | 节点类型 |
| `text` | string | 全部 | 自然语言陈述，必须能被**单句否定** |
| `symbol` | string | 全部 | 该节点代表的量名（如 `population`），用于自动解析依赖 |
| `value` | number \| null | 全部 | 数值（结构假设可为 null） |
| `unit` | string | 全部 | 单位；无量纲写 `-` |
| `status` | string | premise | `unverified` / `verified` / `refuted` / `retracted` |
| `conf` | 0–1 | 全部 | 置信度。`verified` 前提恒为 1.0 |
| `src` | string | 全部 | 来源：`spec` / `user` / `estimate` / `derived` / `measured` |
| `turn` | int | 全部 | 产生于第几轮对话 |
| `updated_turn` | int | 全部 | 最近一次被改写的轮次 |
| `requires` | string[] | claim | **必需**依赖：任一失效，本结论失效 |
| `alts` | string[] | claim | **替代**支撑组：`requires` 全废时，若这组全活则本结论降级存活 |
| `inputs` | string[] | claim | 本结论消费掉的**符号名**，用于孤儿输入检查 |
| `unresolved` | string[] | claim | 登记时 `inputs` 中解析不到提供者的符号（由内核写入） |
| `exported` | bool | claim | 是否已对外输出 / 进入报告，触发交付门禁 |
| `retracted` | bool | claim | 结论被人为撤销 |
| `evidence` | string[] | premise | 核验证据（来源、链接、文件路径） |

**两类依赖的区别是这个设计的核心：**

- `requires` 表达「缺了它，结论必死」
- `alts` 表达「换一条路还能重建」

只有区分这两者，级联才是**精确**的；否则撤回一条前提就是全图崩塌，账本沦为噪音。

## 3. 状态推导（不做持久化）

结论的状态**不存储**，每次实时推导，因此不可能出现"缓存状态过期"这种病：

```
claim_status(c) =
  active        若 requires 全活，且每条都是强支撑
  degraded      若 requires 全活但存在弱支撑，或 requires 废而 alts 全活
  invalidated   否则
```

- 前提「活」= `unverified` 或 `verified`
- 前提「强」= `verified`
- 结论「强」= 其状态为 `active`

## 4. 三条不变式（脚本强制）

1. **依赖非空**：每条 `claim` 至少有一条依赖（`requires` 或 `alts` 非空）
2. **引用存在**：`requires` / `alts` 中出现的每个 id 必须已登记
3. **图无环**：依赖关系构成 DAG

违反任意一条 → `check` 返回 `ok: false`。

## 5. 六类病 + 一道门禁

| 类型 | 中文 | 严重度 | 判据 |
|---|---|---|---|
| `orphan_claim` | 孤儿结论 | error | claim 的 `requires` 与 `alts` 都为空 |
| `orphan_input` | 孤儿输入 | error | `unresolved` 非空：用了某个量，却没有任何节点提供它（**这是「静默前提」的机器可查形式**） |
| `phantom_ref` | 幽灵引用 | error | `requires`/`alts` 指向不存在的 id |
| `circular` | 循环论证 | error | 依赖图中存在环 |
| `contamination` | 污染传播 | error / warning | 结论的依赖链上存在已废前提。结论仍活 → warning；已死 → error |
| `drift` | 前提漂移 | error | 同一 `symbol` 出现多个取值或陈述不同的节点 |
| `export_gate` | 交付门禁 | error | 标记 `exported` 的结论，其上游存在未核实前提，或自身状态非 `active` |

## 6. ID 规则

- 前提 `A{n}`，结论 `C{n}`，各自独立自增
- 计数持久化在 `data.seq`
- **不复用、不回收**：删掉的编号留空，保证历史引用不会指向新节点

## 7. 存储格式

单个 JSON 文件（默认 `./.ledger.json`）：

```json
{
  "version": "1.0",
  "task": "某市供水规模测算",
  "seq": {"A": 4, "C": 2},
  "nodes": {"A1": {"...": "..."}, "C1": {"...": "..."}},
  "events": [{"t": "retract", "id": "A2", "turn": 9, "reason": "人口口径变更"}]
}
```

`events` 只追加不修改，用于答辩时还原"这个结论是怎么被推翻的"。

## 8. 退出码

| 码 | 含义 |
|---|---|
| 0 | 通过 / 执行成功 |
| 1 | 检查不通过（存在 error 级问题） |
| 2 | 输入非法（未知 id、非法参数、ID 冲突） |

退出码是给外层 agent 判断用的——**agent 不需要读懂 JSON 才能知道该不该放行**。
