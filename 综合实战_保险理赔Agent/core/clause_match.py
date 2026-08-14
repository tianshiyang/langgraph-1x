"""条款匹配 clause_match · Milvus 检索适用条款（Phase 6 / FR-5）。

职责：以「险种+诊断+费用类型」检索适用条款，产出 clause_evidence，为 decide 提供可引用条款号。

契约（Agent设计 §4）：读 claim/policy → 写 clause_evidence/events；不调 LLM（仅检索）；
  副作用 = Milvus 检索；空/超时 → [] + 记事件（AC-5.3）。

要点：
  - 用 kb.retriever.search_clauses，按 product 元数据过滤，不返回其他险种条款（AC-5.1）。
  - 至少命中「免赔额」「报销比例」两类条款证据供决策引用（AC-5.2）。
  - 检索失败不静默放行——返回 [] 并记事件，容错策略「转人工」在 decide/图层体现（Agent设计 §6）。

待实现：def clause_match(state) -> {"clause_evidence": [ClauseEvidence], "events": [...]}
"""

# TODO(Phase 6): 实现 clause_match。
