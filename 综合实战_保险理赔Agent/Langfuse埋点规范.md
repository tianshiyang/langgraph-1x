# Langfuse 埋点规范 · 保险理赔智能审核 Agent

> 面向开发。本文规定**每一步埋成什么、trace/span 怎么命名、打哪些分、PII 怎么脱敏、成本怎么配**。
> API 全部对齐你项目现有 v3 写法（`00_真实业务场景/langfuse/`）：`Langfuse(mask=...)` / `start_as_current_observation` / `@observe(as_type="retriever")` / `propagate_attributes` / `create_score` / `CallbackHandler`。
> 原则：**埋点只在 `obs/` 层做，不改 `core/` 业务节点一行代码。**

---

## 1. 分层与客户端

```
obs/client.py     进程内唯一 Langfuse 客户端，client 级 mask（脱敏）+ environment
obs/pii.py        mask 函数（对齐 langfuse.types.MaskFunction：def mask(*, data, **kwargs)）
obs/instrumented.py  给 graph.invoke 挂 CallbackHandler + 包 trace/session/span
obs/prompts.py    托管 prompt（extract / decision_letter …）
obs/judge.py      LLM-as-judge 打分（create_score）
obs/evaluate.py   dataset + experiment 回归
obs/run.py        编排入口
```

```python
# obs/client.py
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from pii import mask_pii

langfuse = Langfuse(mask=mask_pii, environment="production")  # mask 必须在进程内第一个 client 传入

def make_callback_handler() -> CallbackHandler:
    return CallbackHandler()   # 挂到 model.invoke 上自动记 generation + token/cost
```

---

## 2. Trace / Span 命名规范（统一，便于 UI 检索）

| 层级 | 名称 | 类型(as_type) | 说明 |
| --- | --- | --- | --- |
| root | `claim-review` | `chain` | 一个案件一次审核 = 一个 trace |
| span | `intake` | `span` | 立案装载 |
| span | `material-extraction` | `chain` | 抽取总节点（并行子项挂其下） |
| span | `extract:{type}` | `span` | 单份材料抽取（发票/病历…） |
| span | `validate` | `span` | 校验 |
| span | `policy-check` | `span` | 保单核对 |
| span | `clause-retrieval` | **`retriever`** | 条款检索（Milvus） |
| span | `fraud-check` | `chain` | 反欺诈子图 |
| span | `similar-case-retrieval` | **`retriever`** | 相似案例检索（Milvus） |
| span | `settle` | `span` | 赔付测算 |
| span | `decide` | `span` | 决策路由 |
| span | `human-review` | `span` | HITL（记 interrupt/裁决） |
| generation | 自动 | `generation` | 由 `CallbackHandler` 自动生成（抽取/话术/判定的模型调用） |

> **generation 不用手动建**：只要模型 `invoke` 时挂了 `make_callback_handler()`，token/cost 自动记录。

---

## 3. Trace 级属性（每案件）

用 `propagate_attributes` 把整案所有 span 归到同一标识（对齐你现有写法）：

```python
with propagate_attributes(
    session_id=claim_id,               # 补件多轮聚成一个 Session
    user_id=insured_id,                # 按被保险人排查（脱敏后）
    tags=["claim-review", product],    # 如 ["claim-review","医疗险"]
    prompt=decision_prompt,            # 关联托管 prompt（可选）
):
    ...run graph...
```

| 属性 | 取值 | 用途 |
| --- | --- | --- |
| `session_id` | `claim_id` | 同一案件多轮补件串联 |
| `user_id` | `insured_id` | 按被保险人聚合排查 |
| `tags` | `claim-review` + 险种 + 路由结果(`auto_pay`/`human_review`/`reject`) | UI 按结果/险种筛 |
| `metadata` | `{policy_id, risk_level, payable}` | 附加检索维度 |

> 决策完成后可再 `langfuse.update_current_trace(tags=[..., decision.route])`，把最终路由打到 trace 上，方便统计各路由占比。

---

## 4. 两种关键 span 的埋法

### 4.1 检索类（retriever）— 条款 & 相似案例

对齐你 `_observed_retrieve` 的写法：**输出只记命中概览，不 dump 全文**（降噪 + 省成本）。

```python
@observe(as_type="retriever", name="clause-retrieval", capture_output=False)
def observed_search_clauses(query, product, category=None, top_k=3):
    hits = retriever.search_clauses(query, product, category, top_k)
    langfuse.update_current_span(
        input={"query": query, "product": product, "category": category, "top_k": top_k},
        output={"count": len(hits),
                "hits": [{"clause_no": h["clause_no"], "score": h["score"]} for h in hits]},
    )
    return hits
```

`similar-case-retrieval` 同理，output 记 `[{label, score}]`。

### 4.2 决策 span — 把"为什么这么判"落进 trace（合规核心）

```python
with langfuse.start_as_current_observation(name="decide", as_type="span",
        input={"payable": s["payable"], "risk_level": fraud["risk_level"]}):
    decision = decide(state)
    langfuse.update_current_span(output={
        "route": decision["route"],
        "reason": decision["reason"],
        "clause_refs": decision["clause_refs"],
    })
```

> `settle` span 的 output 建议记完整 `Settlement` 明细（脱敏后不含 PII，可安全记录），这样审计能在 UI 直接复算。

---

## 5. Scores（打分）规范 — 对齐 `create_score`

> 分数通过 `trace_id` 关联。三类来源：规则分、用户/核赔员反馈、LLM 裁判。

| score name | data_type | 来源 | 判定 |
| --- | --- | --- | --- |
| `amount_correct` | BOOLEAN | 规则(复算) | `settlement.payable` == 独立复算值 |
| `has_clause_basis` | BOOLEAN | 规则 | `decision.clause_refs` 非空 |
| `materials_complete` | BOOLEAN | 规则 | `validation.complete` |
| `reason_sufficient` | NUMERIC(0-1) | LLM-judge | 结论理由充分性 |
| `adjuster_agreement` | BOOLEAN | 核赔员回流 | 核赔员是否认可 Agent 建议(approve 且未改额) |

```python
langfuse.create_score(name="amount_correct", value=True, data_type="BOOLEAN",
                      trace_id=trace_id, comment="复算一致 payable=8000")
langfuse.create_score(name="reason_sufficient", value=0.9, data_type="NUMERIC",
                      trace_id=trace_id, comment="LLM 裁判：依据充分")
```

> `adjuster_agreement` 由 HITL 裁决回流：`adjust`(改额) → False 且记差异，`approve` → True。这是**评估审核质量最真实的信号**。

---

## 6. PII 脱敏规范（NFR-2，硬要求）

- **client 级 mask**：`Langfuse(mask=mask_pii)`，所有 input/output/metadata 上报前统一走一遍，业务不手动脱敏（避免遗漏）。
- 复用你现成的 `pii.py` 正则集：手机号 `<PHONE>`、身份证 `<ID>`、银行卡 `<CARD>`、邮箱 `<EMAIL>`；替换顺序 身份证/银行卡 先于 手机号（避免长号段误伤）。
- **新增字段**：病历里的诊断可保留（业务需要），但姓名+证件组合、银行卡号必脱敏。
- 验收：任一含 PII 的 span 在 UI 中查不到明文（测试 U-5、O-3）。

---

## 7. Prompt 托管（对齐 hosted_prompts 思路）

| prompt name | 用途 | label |
| --- | --- | --- |
| `claim-extract` | 材料→结构化字段 | production / latest |
| `claim-decision-letter` | 通过/拒赔话术 | production / latest |

- 业务侧 `langfuse.get_prompt(name, label="production")` 拉取；**拉取失败回退本地基线**（保证 `core/` 可独立运行）。
- 关联：`propagate_attributes(prompt=...)` 或 CallbackHandler 会把 generation 关到该 prompt，UI 里能看"这条回答用的哪版 prompt"。
- 灰度：运营在 UI 改 `production` 指向的版本，代码不动即换线上话术（测试：改拒赔话术后 E-C 文书措辞变化）。

---

## 8. 成本配置（否则成本恒为 0）

- Langfuse 成本 = token × 模型单价，靠 generation 上的 **model 字符串**匹配定价表。
- 本项目模型 `glm-*` 内置定价表没有 → 需 **UI → Settings → Models → New model definition**：
  - Match pattern：`(?i)^glm` 或精确 `(?i)^glm-5\.1$`
  - 填 input/output 单价（按实际采购价）
- 只影响配置后新产生的 trace，历史不追溯。

---

## 9. 离线回归埋点（evaluate.py）

- 用 Langfuse **Dataset** 建 `claim-regression`，item = E-A~E-E（input=claim_id，expected=预期 route+payable）。
- 用 **Experiment/Run** 跑基线 → 改阈值（如 `deductible`）→ 再跑一个 run，UI 对比两 run 的 scores。
- 断言见测试 O-6：E-A payable 8000→3000，其余路由不变。
- （进阶）**Annotation Queue**：把 HITL 差异案例（adjust）推入队列，人工标注回流为评测集。

---

## 10. 埋点验收清单（对比行业标准逐条勾）

- [ ] 一案件一 trace，root=`claim-review`，节点全有对应 span
- [ ] 检索是 `retriever` 类型，output 记命中概览+score
- [ ] `settle`/`decide` span 的 output 记明细与依据（可复算、可解释）
- [ ] 补件多轮同 `session_id`
- [ ] generation 自动记 token，且成本非 0（已配定价）
- [ ] 五类 score 齐全，`adjuster_agreement` 从 HITL 回流
- [ ] PII 全脱敏（client 级 mask）
- [ ] prompt 托管 + 本地回退 + label 灰度
- [ ] 回归 dataset + experiment 能跑出变更前后差异
- [ ] 观测代码全在 `obs/`，`core/` 断掉 Langfuse 仍可跑
