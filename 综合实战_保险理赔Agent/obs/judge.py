"""LLM-as-judge 打分 judge（Phase 12 / 埋点规范 §5 / 测试 O-5）。

职责：对结论质量打分并 create_score 写回对应 trace。分数通过 trace_id 关联。

三/五类分数（埋点规范 §5）：
  - amount_correct      BOOLEAN  规则：settlement.payable == 独立复算值
  - has_clause_basis    BOOLEAN  规则：decision.clause_refs 非空
  - materials_complete  BOOLEAN  规则：validation.complete
  - reason_sufficient   NUMERIC(0-1)  LLM-judge：结论理由充分性
  - adjuster_agreement  BOOLEAN  核赔员回流：approve 且未改额→True，adjust→False+记差异

验收 O-5：E-A amount_correct=True（8000 复算一致）；E-C has_clause_basis=True。

待实现：
  - score_rules(trace_id, state) -> None       # 规则分（复算/条款/完整性）
  - score_llm_judge(trace_id, state) -> None   # LLM 裁判 reason_sufficient
"""

import _setup  # noqa: F401

# TODO(Phase 12): 用 langfuse.create_score 实现规则分 + LLM 裁判分。
