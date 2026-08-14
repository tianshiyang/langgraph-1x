"""决策路由 decide · Command(goto, update) 三分支（Phase 7 / FR-8 / BR-8）。

职责：按确定性规则决定路由并一步写入 decision。**不调 LLM。**

契约（Agent设计 §4）：读 settlement/fraud/validation/policy_check → 写 decision（经 Command）；纯规则。

路由规则（BR-8，用 Command(goto=..., update={"decision": Decision})）：
  - policy_check.blockers 非空                      → route="reject"          (AC-8.1)
  - payable ≤ config.AUTO_PAY_LIMIT 且 risk_level=="低" 且 校验全过 → route="auto_pay"  (AC-8.2)
  - 其余                                            → route="human_review"    (AC-8.3)
  - Milvus 检索失败等不确定情形 → 向安全侧降级为 human_review（Agent设计 §6），不得自动直赔。

要点：decision.reason 与 clause_refs 必须非空且能对应实际命中条款（AC-8.4）——把「为什么这么判」写清，合规核心。

待实现：def decide(state) -> Command
"""

# TODO(Phase 7): 实现 decide，返回 Command(goto, update)。
