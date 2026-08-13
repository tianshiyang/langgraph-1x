# Agent 设计 · 保险理赔智能审核 Agent（对标行业标准）

> 面向开发。本文讲**为什么这样设计、图长什么样、每个节点的契约、HITL/记忆/容错/可观测怎么落**。
> 数据契约与规则见 [`需求规格说明书.md`](./需求规格说明书.md)。

---

## 1. 架构选型：为什么是「受控工作流图」而不是「自主 ReAct Agent」

业界把 LLM 应用大致分两类（Anthropic《Building Effective Agents》口径）：

- **Workflow（编排式）**：流程由**代码预先定义**，LLM 只在固定环节被调用。可预测、可测试、可审计。
- **Agent（自主式）**：LLM **自己决定**下一步调什么工具、循环几次。灵活但不可预测。

**理赔是强监管、涉及金额、要审计留痕的场景 → 必须选 Workflow 编排式。**
核心原则（行业标准，务必记住）：

> **The LLM proposes, deterministic code disposes.**
> LLM 只做两件事：① 从材料里**抽结构化字段**；② 把最终结论**写成话术**。
> **金额测算、准入判断、路由决策全部由确定性代码完成**——因为它们必须可复算、可回归、可对审计解释。

这条线划清楚了，后面的可观测/评估/合规才立得住。多智能体（supervisor）是 Phase 13 的**可选重构**，不是主线——不要一上来就上多 agent，那是常见的过度设计。

---

## 2. 状态设计（单一数据源 + 显式 channel）

- 用一个 `ClaimState`（TypedDict）贯穿全图，节点只读它需要的字段、只写它负责的字段（字段 → 写入节点映射见 SRS §2.1）。
- **需要合并的 channel 配 reducer**：
  - `extracts`：并行抽取的结果要合并 → 配 `operator.add`（或自定义去重 merge）。
  - `events`：全程追加审计事件 → 配 `add`。
  - 其余标量字段默认「后写覆盖」。
- **PII 只在内存态存在明文**，落 Langfuse 由 client 级 `mask` 统一脱敏（见埋点规范），业务代码不手动脱敏，避免遗漏。

---

## 3. 图拓扑

```
                         ┌─────────┐
                         │ intake  │ 立案装载(读库)
                         └────┬────┘
                              ▼
                     ┌────────────────┐
              Send   │  extract (fan) │  按材料 fan-out
          ┌──────────┼────────────────┼──────────┐
          ▼          ▼                ▼           ▼
     extract_one  extract_one     extract_one  extract_one   并行抽取
          └──────────┴───────┬────────┴───────────┘
                             ▼ (reduce 到 extracts)
                        ┌──────────┐
                        │ validate │ 完整性/一致性
                        └────┬─────┘
                   complete? │
              ┌──────────────┴───────────────┐
              ▼(缺件/矛盾)                     ▼(通过)
        ┌───────────┐                   ┌──────────────┐
        │ need_more │ 待补件(挂起/END)    │ policy_check │ 保单核对
        └───────────┘                   └──────┬───────┘
                                               ▼
                                    ┌──────────┴──────────┐
                                    ▼(并行)                ▼(并行)
                             ┌────────────┐         ┌──────────────┐
                             │clause_match│         │ fraud (子图) │
                             │  (Milvus)  │         │ (Milvus+规则) │
                             └──────┬─────┘         └──────┬───────┘
                                    └────────┬─────────────┘
                                             ▼ (join)
                                        ┌─────────┐
                                        │ settle  │ 赔付测算(确定性)
                                        └────┬────┘
                                             ▼
                                        ┌─────────┐
                                        │ decide  │ Command(goto,update)
                                        └────┬────┘
                          ┌──────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                    ┌──────────┐       ┌──────────────┐     ┌────────┐
                    │ auto_pay │       │ human_review │     │ reject │
                    └────┬─────┘       │  interrupt   │     └───┬────┘
                         │             └──────┬───────┘         │
                         │       approve/adjust│reject/return   │
                         │        ┌────────────┼───────────┐    │
                         │        ▼            ▼           ▼    │
                         │   (出具通过)    (出具拒赔)   (回 need_more) │
                         └────────────────┬───────────────┬─────┘
                                          ▼               ▼
                                       ┌──────────────────────┐
                                       │ finalize 落库+文书+事件 │
                                       └──────────────────────┘
                                                  ▼
                                                 END
```

**并行**：`policy_check` 后同时进 `clause_match` 与 `fraud`，两者无数据依赖，join 到 `settle`。
**条件路由**：`validate` 后用条件边；`decide` 用 `Command(goto=..., update=...)` 一步完成"路由+写决策"。

---

## 4. 节点契约（开发按此实现，逐个可单测）

| 节点 | 读(state) | 写(state) | 是否调 LLM | 副作用 | 失败处理 |
| --- | --- | --- | --- | --- | --- |
| `intake` | claim_id | claim/policy/insured/materials/events | 否 | 读库 | 案件不存在→抛异常+记事件 |
| `extract_one` | 单份 material（Send 载荷） | extracts(+1) | **是**(结构化输出) | 无 | 重试→异常兜底 |
| `validate` | extracts/policy | validation/events | 否 | 无 | 纯计算 |
| `policy_check` | claim/policy/extracts | policy_check/events | 既往症判定可选 LLM | 无 | LLM 失败降级为关键词判定 |
| `clause_match` | claim/policy | clause_evidence/events | 否(仅检索) | Milvus 检索 | 空/超时→[]+记事件 |
| `fraud`(子图) | insured/claim/store | fraud/events | 否 | Milvus + store 读 | 检索失败→降级为仅规则 |
| `settle` | policy_check/extracts | settlement/events | **否(禁用 LLM)** | 无 | 纯计算，必对 |
| `decide` | settlement/fraud/validation/policy_check | decision(Command) | 否 | 无 | 纯规则 |
| `human_review` | decision/settlement/clause/fraud | adjuster_action(resume) | 否 | interrupt | resume 载荷校验 |
| `auto_pay`/`reject`/`finalize` | decision/adjuster_action | result/events | **是**(仅写话术) | 写库 | 话术失败→模板兜底 |

**共同约定（行业标准）**：
- **幂等**：节点重复执行结果一致（配合 checkpointer 重放）。
- **副作用集中**：只有 `intake`(读) 和 `finalize`(写) 碰业务库；其余节点纯函数式，便于测试与重放。
- **结构化输出**：`extract_one` 用 `model.with_structured_output(Schema)`，**绝不解析自由文本拿金额**。
- **决策温度**：涉及判断的 LLM 调用 `temperature=0`。

---

## 5. 工具与检索层契约

> 工具 = 对 DAO / 检索的**薄类型封装**。节点调工具，工具不含业务判断。

```python
# 业务库工具（data 层）
get_claim(claim_id) -> dict | None
get_policy(policy_id) -> dict | None
get_insured(insured_id) -> dict | None
list_materials(claim_id) -> list[dict]
count_recent_claims(insured_id, before: date, days=90) -> int   # 反欺诈"短期多次"
hit_fraud_watch(hospital: str, insured_id: str) -> list[str]     # 名单命中
finalize_claim(claim_id, decision, amount, reason) -> None       # 写结论

# 检索工具（kb 层，Milvus）
search_clauses(query, product, category=None, top_k=3) -> list[ClauseEvidence]
search_similar_cases(summary, product, top_k=3) -> list[dict]    # {summary,label,score}
```

---

## 6. 容错与降级（行业标准）

| 环节 | 策略 |
| --- | --- |
| `extract_one` LLM 调用 | 重试 2 次（指数退避）；仍失败 → `status="异常"` 兜底，**不阻断其他材料** |
| 既往症 LLM 判定 | 失败 → 降级为 `preexisting_note` 关键词匹配 |
| Milvus 检索 | 超时/异常 → 返回空 + 记事件 + **强制转人工**（不静默通过，安全优先） |
| 结论话术生成 | 失败 → 用模板拼接兜底（金额/决策已定，话术不影响正确性） |

原则：**任何 LLM/外部依赖失败都不能改变金额与准入结论**；不确定时"向安全侧降级"（转人工而非自动赔）。

---

## 7. HITL 协议（人工核赔）

- **中断**：`human_review` 调 `interrupt(payload)`，`payload` = 证据包（SRS AC-9.1）。图在此暂停，checkpointer 落盘。
- **恢复**：核赔员决策后，用 `graph.invoke(Command(resume=AdjusterAction), config={"configurable":{"thread_id": claim_id}})` 续跑。
- **动作语义**：approve/adjust/reject/return（SRS FR-9）。`adjust` 与 Agent 建议不一致时记差异事件 → 回流为评估样本（judge/annotation）。

---

## 8. 持久化与记忆

| 机制 | 用途 | 键 |
| --- | --- | --- |
| **checkpointer**（PostgresSaver） | 案件跨天恢复、HITL 挂起、时间旅行 | `thread_id = claim_id` |
| **store**（长期记忆） | 跨案件累积被保险人历史（次数/金额/结论），反欺诈"短期多次"用 | `namespace = ("insured", insured_id)` |

- **时间旅行**：`get_state_history(config)` 找到 `clause_match` 前的检查点，改条款/阈值后从该点重跑，对比结论 → 审计与回归两用。

---

## 9. 可观测与业务解耦（关键分层）

- `core/`（本设计的全部节点）**零 Langfuse**，可独立 `app.py` 跑通。
- `obs/` 通过给 `graph.invoke` 挂 `CallbackHandler` + 包 `start_as_current_observation`/`propagate_attributes` 叠加观测，**不改节点一行**。
- 埋点映射（哪个节点→哪种 span）见 [`Langfuse埋点规范.md`](./Langfuse埋点规范.md)。

---

## 10. Prompt 策略

| Prompt | 职责 | 托管 | 温度 |
| --- | --- | --- | --- |
| `extract` | 材料→结构化字段 | Langfuse 托管，带本地回退 | 0 |
| `preexisting`（可选） | 判定诊断是否属既往症 | 托管 | 0 |
| `decision_letter` | 通过/拒赔话术 | 托管（运营可改措辞） | 0.3 |

- 托管 prompt 支持 `production`/`latest` label 灰度；业务拉取失败回退本地基线，保证可独立运行。

---

## 11. 与"行业标准"的自检清单（你对比时可逐条打勾）

- [ ] 金额与准入**不经过 LLM**（LLM propose, code dispose）
- [ ] 抽取用**结构化输出**，不正则抠自由文本
- [ ] 状态是**单一数据源**，并行 channel 配 reducer
- [ ] 副作用（写库）集中在少数节点，其余幂等纯函数
- [ ] 外部依赖失败**向安全侧降级**（转人工），不静默放行
- [ ] HITL 有**类型化的中断载荷与恢复契约**
- [ ] 持久化 thread = 业务实体 id；长期记忆有 namespace
- [ ] 观测与业务**分层解耦**，可独立运行
- [ ] 决策阈值/规则参数**集中可配**，支持离线回归
- [ ] 每步**审计留痕**，结论可复算、可解释、可追溯
- [ ] 多智能体是**按需重构**而非默认（避免过度设计）
