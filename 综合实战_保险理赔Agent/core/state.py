"""图状态与数据契约（Phase 3 / SRS §2）。单一数据源，节点只读需要的字段、只写负责的字段。

职责：定义 ClaimState（TypedDict）及其子结构；给需要合并的 channel 配 reducer。

待定义（完整字段表见 SRS §2.1，子结构见 §2.2）：
  子结构：MaterialInput / MaterialExtract / Validation / PolicyCheck / ClauseEvidence /
          FraudResult / Settlement / Decision / AdjusterAction / Event / ClaimResult
  ClaimState 字段：claim_id / claim / policy / insured / materials / extracts /
          validation / policy_check / clause_evidence / fraud / settlement /
          decision / adjuster_action / result / events

reducer（关键）：
  - extracts：并行抽取结果需合并 → Annotated[list, operator.add]（或自定义去重 merge）。
  - events：全程追加审计事件 → Annotated[list, add]。
  - 其余标量字段默认「后写覆盖」。

要点：PII 只在内存态存明文，脱敏由 obs 层 client 级 mask 统一处理，业务不手动脱敏。
"""

# TODO(Phase 3): 用 TypedDict 定义上述结构；对 extracts/events 配 Annotated + reducer。
