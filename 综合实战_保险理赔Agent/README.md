# 综合实战 · 保险理赔智能审核 Agent（"慧赔"中台）需求文档 (PRD)

> 一个尽量贴近真实企业的**毕业级综合案例**：把你学过的 **LangGraph + Milvus + Langfuse** 全部串进同一条业务链路。
> 本文是**需求文档**；分阶段怎么落地见同目录 [`路线图.md`](./路线图.md)。业务代码由你按路线图逐步实现。

---

## 一、背景与目标

某财产/健康险公司，理赔量大、人工审核慢、审核口径不统一、且**监管要求每一步可审计留痕**。
现有痛点：

- 材料靠人工肉眼核对，缺件/金额矛盾/日期矛盾发现晚；
- 条款理解依赖个人经验，赔付比例、免赔额、除外责任容易算错；
- 反欺诈全靠事后抽查，短期多次理赔、异常金额难实时预警；
- 合规审计要"能说清每一分钱是依据哪一条条款赔的"，人工审核留痕不全。

**目标**：构建一个**人机协同**的智能理赔审核中台。Agent 自动完成 材料抽取 → 校验 → 保单核对 → 条款匹配 → 反欺诈初筛 → 赔付测算 → 建议结论；
**低额+低风险+材料齐全的案件自动直赔**，**中高额/高风险/存疑案件转人工核赔（HITL）**，**明确不符的拒赔并附条款依据**。
全链路经 Langfuse 留痕，满足合规审计与持续评估。

**险种范围**（先聚焦，避免范围过大）：**健康险 - 住院医疗费用报销（"百万医疗"型产品）** 为主线。
它天然需要"发票金额测算 + 条款匹配 + 反欺诈"，是最能覆盖复习点的险种。后续可扩展意外医疗。

---

## 二、角色与用户故事

| 角色 | 说明 | 关键诉求 |
| --- | --- | --- |
| 被保险人 | 报案、上传理赔材料 | 快速赔付、清楚知道为什么赔/拒 |
| 智能审核 Agent | 自动审核流水线 | 准确、可解释、能自动结案低风险案件 |
| 人工核赔员 | 审批中高额/存疑案件 | 看到 Agent 的建议+完整证据，一键 通过/驳回/改额/退补 |
| 理赔主管 | 质检、看 dashboard、调规则/prompt | 上线新规则前先回归，不能让通过率/一致率退化 |
| 合规/审计 | 事后追溯 | 每案件每一步都能在 Langfuse 里查到依据与操作人 |

**核心用户故事**

- 作为被保险人，我上传发票和病历后，希望**几分钟内**拿到小额住院费用的赔付结论。
- 作为核赔员，当案件金额较大或存疑时，我希望系统**停下来等我审批**，并把 Agent 算出的应赔金额、引用的条款、反欺诈信号都摆在我面前。
- 作为主管，当我要把"免赔额"从 1 万调成 1.5 万时，我希望**先用历史案件跑一遍回归**，确认赔付结论的变化符合预期再上线。
- 作为审计，我希望对任意一个已赔付案件，能还原出**它当时是从哪一步、依据哪条条款、由谁最终拍板**的。

---

## 三、核心业务流程（一条理赔案件的生命周期）

```
报案立案
   │
   ▼
材料结构化抽取 ──(多材料并行)  发票→金额/日期  病历→诊断  清单→明细  证件→身份信息
   │
   ▼
完整性/一致性校验 ──[缺件/矛盾]──▶ 待补件（通知补材料，等待后重入）
   │ 材料齐
   ▼
保单核对（是否在保 / 等待期 / 免赔额 / 保额余额 / 既往症除外）
   │
   ├───────────────┬───────────────┐
   ▼               ▼               │(并行)
条款匹配          反欺诈初筛         │
(Milvus 条款库)   (Milvus 相似案例 + 规则)
   └───────┬───────┘
           ▼
       赔付测算（按条款算应赔金额）
           ▼
       结论决策 + 路由
     ┌────────┼─────────────┐
     ▼        ▼             ▼
 自动直赔   人工核赔(HITL)   拒赔(带条款依据)
     │        │(通过/驳回/改额/退补)
     └────────┴────► 出具结论（赔付通知 / 拒赔说明）→ 落库 + Langfuse 留痕
```

**赔付测算公式（教学简化版，实际以条款为准）**

```
合理医疗费用 = 发票总额 − 社保已报销 − 条款除外项目(如社保外用药、特需/国际部)
应赔金额     = max(0, 合理医疗费用 − 年度免赔额) × 报销比例
应赔金额     = min(应赔金额, 保额余额)
```

---

## 四、功能需求

### F1 材料结构化抽取
- 输入：一个案件的 N 份材料（发票/病历/费用清单/诊断证明/身份证/银行卡）。
- 用 LLM 从每份材料抽取结构化字段（金额、就诊日期、医院、诊断、票据类型…）。
- **多材料需并行抽取**（对应 LangGraph `Send` / Map-Reduce）。
- 抽取失败可**重试/降级**（对应容错）。

### F2 完整性 / 一致性校验
- 必需材料齐全性（住院报销至少：发票 + 费用清单 + 出院/诊断证明）。
- 一致性：发票日期 vs 就诊日期、发票金额 vs 清单合计、被保险人姓名 vs 保单。
- 不通过 → 生成待补件清单，案件转"待补件"，补件后重新进入流程（循环/重入）。

### F3 保单核对
- 保单是否有效、被保险人是否匹配、出险日期是否在保障期且**过等待期**。
- 读取免赔额、报销比例、保额余额、既往症除外说明。

### F4 条款匹配（Milvus）
- 依据"险种 + 诊断 + 费用类型"到 **条款库 collection** 检索适用条款（报销比例/免赔额/除外责任/等待期）。
- 支持按**险种 metadata 过滤**的向量检索，返回带条款号的证据片段。

### F5 反欺诈初筛（Milvus + 规则，做成子图）
- 规则信号：同一被保险人短期内多次理赔、单次金额显著异常、就诊机构在关注名单。
- 相似案例：到 **历史案例库 collection** 检索相似历史案件，命中标记为欺诈/存疑的案例则升高风险分。
- 输出风险等级（低/中/高）+ 命中理由。

### F6 赔付测算
- 按 F3/F4 的参数与上面的公式计算应赔金额，产出可解释的计算过程（每一项扣减都要能说清）。

### F7 结论决策与路由
- 决策规则（可配置阈值，教学默认）：
  - 应赔额 ≤ 1 万 **且** 风险=低 **且** 材料齐全一致 → **自动直赔**；
  - 应赔额 > 1 万 **或** 风险≥中 **或** 材料存疑 → **转人工核赔(HITL)**；
  - 保单不符（未过等待期/既往症/不在保障范围）→ **拒赔**（附条款依据）。
- 路由用 `Command(goto=..., update=...)` 同时完成"跳转 + 写状态"。

### F8 人工核赔（HITL）
- 转人工的案件在核赔节点 **中断(interrupt)**，向核赔员展示：应赔金额、计算明细、引用条款、反欺诈信号、原始抽取结果。
- 核赔员动作：`通过 / 驳回 / 调整金额 / 退回补件`；系统按裁决恢复(resume)执行。
- 案件跨天，需 **持久化(checkpointer)** 支持随时恢复；线程键 = `claim_id`。

### F9 出具结论与留痕
- 通过 → 赔付通知（金额、账户脱敏、条款依据）；拒赔 → 拒赔说明（引用条款）。
- 落库到业务表，并把关键事件写入案件事件流（含 Langfuse `trace_id`）。

### F10 长期记忆 / 时间旅行 / 审计（跨案件）
- **长期记忆(store)**：以被保险人为键，累积其历史理赔（供反欺诈与核赔参考）。
- **时间旅行**：审计可从"条款匹配"这一步回看/重跑；核赔驳回后可回到指定步骤重来。

### F11 可观测与评估（Langfuse）
- 每案件一个 trace，节点=span，模型调用=generation，检索=retriever span；补件多轮用 `session_id=claim_id` 串联。
- **Prompt 托管**：抽取 prompt、决策 prompt、拒赔话术 prompt，运营在 UI 改即改线上。
- **成本/token**：真实调用 `provider.glm_model`，记录用量与成本。
- **LLM-as-judge**：对审核结论打分（是否有条款依据 / 金额是否算对 / 拒赔理由是否充分）。
- **离线回归(dataset + experiment)**：历史案件做回归集，改规则/改 prompt 上线前跑，看通过率/一致率是否退化。
- **PII 脱敏**：身份证、银行卡、手机号、病历敏感信息上报前打码（合规硬要求）。
- **标注队列**：核赔员的人工裁决回流为标注，用于质检与评测集扩充。

---

## 五、数据设计（全新造，前缀 `clm_` = claim）

> 业务库沿用你项目里的 Postgres/Neon + SQLAlchemy 2.0 约定；向量数据进 Milvus。
> 种子数据要求**幂等**（可反复灌），且刻意覆盖全部决策分支（见"样例案件"）。

### 5.1 Postgres 业务表

**clm_policies 保单**

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| policy_id | str PK | 保单号 |
| product | str | 险种（如 医疗险） |
| plan | str | 计划名（如 百万医疗2025） |
| insured_id | str FK | 被保险人 |
| sum_insured | Numeric | 保额（如 3000000） |
| deductible | Numeric | 年度免赔额（如 10000） |
| reimburse_rate | Numeric | 报销比例（0~1，如 1.00 有社保） |
| waiting_days | int | 等待期天数（如 30） |
| effective_date | date | 保单生效日 |
| expiry_date | date | 保单到期日 |
| used_amount | Numeric | 保额已用（算余额用） |
| preexisting_note | str | 既往症除外说明 |
| status | str | 有效/失效 |

**clm_insureds 被保险人**（含 PII）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| insured_id | str PK | 被保险人 ID |
| name | str | 姓名 |
| id_no | str | 身份证号（PII，脱敏） |
| phone | str | 手机号（PII，脱敏） |
| bank_card | str | 银行卡号（PII，脱敏） |
| risk_flag | str \| None | 反欺诈标记（关注/黑名单/空） |

**clm_claims 理赔案件**

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| claim_id | str PK | 理赔案件号 |
| policy_id | str FK | 关联保单 |
| insured_id | str FK | 被保险人 |
| incident_type | str | 出险类型（疾病/意外） |
| diagnosis | str | 诊断（如 急性阑尾炎） |
| hospital | str | 就诊机构 |
| incident_date | date | 出险/就诊日期 |
| report_date | date | 报案日期 |
| total_claimed | Numeric | 申报金额（发票总额） |
| social_paid | Numeric | 社保已报销金额 |
| approved_amount | Numeric \| None | 核定赔付金额 |
| decision | str \| None | 结论：通过/部分通过/拒赔 |
| decision_reason | str \| None | 结论依据（引用条款号） |
| risk_level | str \| None | 反欺诈风险：低/中/高 |
| adjuster_id | str \| None | 核赔员（HITL 时） |
| status | str | 立案/待补件/审核中/待核赔/已赔付/已拒赔 |
| created_at | datetime | 立案时间 |

**clm_claim_materials 理赔材料**

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| material_id | str PK | 材料 ID |
| claim_id | str FK | 所属案件 |
| type | str | 发票/病历/费用清单/诊断证明/身份证/银行卡 |
| file_uri | str | 文件地址（mock） |
| ocr_json | str \| None | 结构化抽取结果（JSON 文本） |
| status | str | 待抽取/已抽取/异常 |

**clm_case_events 案件事件流（审计留痕）**

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| event_id | str PK | 事件 ID |
| claim_id | str FK | 所属案件 |
| step | str | 步骤（抽取/校验/条款匹配/决策/核赔…） |
| actor | str | 执行方（agent / 核赔员ID） |
| action | str | 动作（通过/驳回/改额…） |
| detail | str | 详情 |
| trace_id | str \| None | 关联 Langfuse trace |
| created_at | datetime | 时间 |

**clm_fraud_watch 反欺诈关注名单**（可选）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | str PK | 记录 ID |
| kind | str | 类型：机构/被保险人 |
| value | str | 命中值（机构名/insured_id） |
| note | str | 说明 |

### 5.2 Milvus Collections

**insurance_clauses 条款库**

| 字段 | 说明 |
| --- | --- |
| id | 主键 |
| vector | 条款切片 embedding（DashScope 千问，维度按模型） |
| text | 条款原文切片 |
| product | 险种（元数据过滤用：医疗险/意外险） |
| clause_no | 条款号（如 3.2 责任免除） |
| category | 类别：报销比例 / 免赔额 / 除外责任 / 等待期 / 保障范围 |

**claim_cases_history 历史案例库（反欺诈相似检索）**

| 字段 | 说明 |
| --- | --- |
| id | 主键 |
| vector | 案情摘要 embedding |
| summary | 案情摘要文本（诊断+金额+机构+处理结果） |
| label | 正常 / 存疑 / 欺诈 |
| product | 险种 |
| payout | 历史赔付金额（参考） |

> 索引建议：`HNSW`（教学量级足够快）；度量 `COSINE` 或 `IP`（与 embedding 归一化一致即可）。
> 进阶可加 `medical_kb`（诊断-项目对照/常见拒赔诊断）演示多 collection + 混合检索。

### 5.3 样例案件（刻意覆盖全部分支，同时就是回归数据集）

| 案件 | 情形 | 期望走向 | 复习点 |
| --- | --- | --- | --- |
| Case A | 住院 2.8 万，社保报 1 万，免赔 1 万，比例 100%，材料齐、非既往症、已过等待期 | 应赔 =(2.8−1−1)=**0.8 万** → 低额低风险 → **自动直赔** | 正常主流程 |
| Case B | 住院 18 万，社保报 5 万，免赔 1 万 | 应赔 =(18−5−1)=**12 万** → 大额 → **转人工核赔(HITL)** | HITL / 持久化 |
| Case C | 出险日在等待期内（或既往症并发症） | **拒赔**，引用"等待期/既往症除外"条款 | 拒赔分支 / 条款匹配 |
| Case D | 缺"费用清单"材料 | 无法核对明细 → **待补件**，补件后重入 | 循环重入 / 条件边 |
| Case E | 同一被保险人 90 天内第 3 次住院理赔 + 就诊机构在关注名单 + 命中历史欺诈相似案例 | 风险=高 → **反欺诈 + 转人工** | 反欺诈子图 / Milvus 相似检索 / 长期记忆 |

---

## 六、技术架构（延续"业务实现层 / 观测层分离"）

```
综合实战_保险理赔Agent/
├─ README.md              需求文档(本文)
├─ 路线图.md              分阶段实现路线图
├─ data/                  【业务数据层】全新造，零 LangGraph/Langfuse
│  ├─ db.py                  clm_* 建表 + 幂等种子（5 个样例案件）
│  └─ raw_clauses.py         条款/历史案例 原始素材（喂给 Milvus 的语料）
├─ kb/                    【知识层 / Milvus】
│  ├─ milvus_store.py        连接 / 建 collection / 建索引 / 通用检索封装
│  ├─ ingest.py              条款&案例 embedding 后灌入（幂等）
│  └─ retriever.py           条款检索 / 相似案例检索（带 metadata 过滤）
├─ core/                  【业务实现层】纯 LangGraph，零 Langfuse，可独立运行
│  ├─ state.py               ClaimState 状态定义
│  ├─ extract.py             材料抽取（Send 并行）
│  ├─ validate.py            完整性/一致性校验
│  ├─ policy_check.py        保单核对
│  ├─ clause_match.py        条款匹配（调 kb/retriever）
│  ├─ fraud.py               反欺诈（独立子图）
│  ├─ settle.py              赔付测算
│  ├─ decide.py              决策路由（Command）
│  ├─ human_review.py        HITL 核赔（interrupt）
│  ├─ graph.py               组装主图（checkpointer + store）
│  └─ app.py                 可独立运行 demo（不 import langfuse）
├─ obs/                   【观测层】import core，叠加 Langfuse，不改业务
│  ├─ _setup.py              sys.path / .env 准备
│  ├─ pii.py                 PII 脱敏
│  ├─ client.py              带 mask 的 langfuse client
│  ├─ prompts.py             托管 prompt（抽取/决策/拒赔话术）
│  ├─ instrumented.py        给图挂 CallbackHandler + trace
│  ├─ judge.py               LLM-as-judge 打分
│  ├─ evaluate.py            dataset + experiment 回归
│  └─ run.py                 编排入口：跑完整案件 + 全套观测
└─ (复用项目 provider/)   glm_model（GLM）/ embeddings（千问 DashScope）
```

**依赖新增**：`pymilvus`（Milvus 客户端）；`.env` 增 `MILVUS_URI` / `MILVUS_TOKEN`（或本地 docker 无鉴权）。
**分层意义**：`data/`+`kb/`+`core/` 只依赖 LangChain/LangGraph/Milvus 与项目 `provider`，可独立跑独立测；
所有 Langfuse 相关都在 `obs/`，通过"组合业务原子能力 + 挂回调 + 包观测上下文"叠加，**不改业务一行代码**。

---

## 七、非功能需求

- **合规留痕**：每步都有 trace/事件，能还原"依据哪条条款、谁最终拍板"。
- **PII 脱敏**：身份证/银行卡/手机号/病历敏感字段上报 Langfuse 前必须打码。
- **可回溯**：checkpointer 支持案件跨天恢复；时间旅行支持从中间步骤重跑。
- **幂等**：建表/灌数据/灌向量都可反复执行不产生脏数据。
- **可离线回归**：不接外部依赖也能用历史样例案件跑通评估。
- **成本可见**：generation 记录真实 token；需在 Langfuse 配 `glm-*` 定价（否则成本显示 0）。
- **可独立分层运行**：`core/app.py` 不依赖 Langfuse 即可跑完整审核。

---

## 八、验收标准（Definition of Done）

1. `data/db.py` 建表+灌入 5 个样例案件，幂等，打印各表行数校验。
2. `kb/ingest.py` 把条款&历史案例灌入 Milvus；`retriever` 能按险种过滤检索，"住院免赔额"命中免赔条款。
3. `core/app.py` 能独立跑通 5 个样例案件，各自走对分支：A 自动直赔、B 转人工、C 拒赔、D 待补件、E 反欺诈转人工。
4. B 案件在核赔节点 interrupt，注入 `通过/驳回/改额` 后能 resume 结案；进程重启后凭 `claim_id` 可恢复。
5. `obs/run.py` 跑完后 Langfuse UI 能看到：每案件一个嵌套 trace、补件多轮同 session、检索/生成 span、PII 已脱敏、成本非 0。
6. `obs/evaluate.py` 能对 5 个样例跑回归；把免赔额从 1 万调到 1.5 万后重跑，Case A 的赔付结论按预期变化，且回归报告能反映差异。
7. LLM-as-judge 能对结论产出三维分数并写回对应 trace。

---

## 九、复习点覆盖对照（这个案例到底复习了什么）

| 能力域 | 复习点 | 落在哪 |
| --- | --- | --- |
| LangGraph | StateGraph / reducer | `core/state.py`、`graph.py` |
| | Send / Map-Reduce（多材料并行抽取） | `core/extract.py` |
| | 条件边 + `Command(goto,update)` | `core/decide.py` |
| | 子图（反欺诈可复用/可单独观测） | `core/fraud.py` |
| | HITL `interrupt` / resume | `core/human_review.py` |
| | 持久化 checkpointer（Postgres） | `core/graph.py` |
| | 长期记忆 store（跨案件） | `core/graph.py`、`fraud.py` |
| | 时间旅行 `get_state_history` | 演示脚本 |
| | 容错 / 重试（抽取降级） | `core/extract.py` |
| | 多智能体 supervisor（进阶） | 进阶阶段重构 |
| | 流式（审核进度） | 进阶阶段 |
| Milvus | collection / schema / 索引(HNSW) | `kb/milvus_store.py` |
| | 插入 / 幂等灌库 | `kb/ingest.py` |
| | metadata 过滤检索 / top_k | `kb/retriever.py` |
| | 多 collection / 混合检索（进阶） | `medical_kb`（进阶） |
| Langfuse | trace/span/generation/retriever | `obs/instrumented.py` |
| | session 串多轮补件 | `obs/instrumented.py` |
| | Prompt 托管 + label 灰度 | `obs/prompts.py` |
| | 成本 / token | `provider.glm_model` + UI 定价 |
| | LLM-as-judge | `obs/judge.py` |
| | dataset + experiment 回归 | `obs/evaluate.py` |
| | PII 脱敏 | `obs/pii.py`、`client.py` |
| | 标注队列 | `obs/evaluate.py`（进阶） |

---

具体每个阶段先做什么、产出什么、怎么自测、对应复习哪个点 —— 见 [`路线图.md`](./路线图.md)。
