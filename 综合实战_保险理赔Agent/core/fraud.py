"""反欺诈 fraud · 独立子图（Phase 6 + Phase 9 / FR-6 / BR-7）。

职责：综合「规则信号 + Milvus 相似历史案例 + 长期记忆」输出风险等级与可解释信号。
      **做成独立子图**，作为一个节点挂进主图（复习子图）。

契约（Agent设计 §4）：读 insured/claim/store → 写 fraud/events；不调 LLM；
  副作用 = Milvus + store 读；检索失败 → 降级为「仅规则」。

规则信号（BR-7，写入 FraudResult.signals，每条记 hit + detail 可解释 AC-6.3）：
  ① 90 天内已结案 ≥2 次（依据**长期记忆 store**，非仅当前案件 AC-6.1 → count_recent_claims）
  ② 单次申报 > config.LARGE_AMOUNT
  ③ 机构/被保险人命中名单（hit_fraud_watch）
  ④ 相似欺诈案例 score ≥ config.SIMILAR_FRAUD_THRESHOLD（search_similar_cases）
  等级：命中 ≥2 或命中④ → 高；命中 1 → 中；0 → 低。

子图结构建议：规则信号节点 ∥ 相似案例检索节点 → 汇总节点定级。

待实现：
  - build_fraud_subgraph() -> CompiledGraph      # 内部子图
  - fraud(state, *, store) -> {"fraud": FraudResult, "events": [...]}   # 挂主图的节点

要点：store 长期记忆键 namespace=("insured", insured_id)，累积历史（次数/金额/结论）——Phase 9 接入。
"""

# TODO(Phase 6): 规则+相似案例定级；TODO(Phase 9): 接 store 长期记忆增强「短期多次」。
