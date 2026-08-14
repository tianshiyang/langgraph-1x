"""校验 validate · 完整性 + 一致性（Phase 5 / FR-3 / BR-1 / BR-2）。

职责：纯计算判定材料是否齐全、字段是否一致，产出 Validation。缺件/矛盾 → 路由「待补件」。

契约（Agent设计 §4）：读 extracts/policy → 写 validation/events；不调 LLM；纯计算。

判定规则：
  - BR-1 完整性：必需材料 config.REQUIRED_MATERIALS，缺任一 → complete=False，missing 列出缺失类型（AC-3.1）。
  - BR-2 一致性：① 发票 total_amount == 清单 sum_amount（容差 0）
                  ② 发票/诊断日期落在案件就诊区间
                  ③ 证件 name == policy 被保险人 name
    不一致项写入 inconsistencies（AC-3.2）。
  - complete=False 或存在阻断性不一致 → 图路由到 need_more，不进入 policy_check（AC-3.3）。

待实现：def validate(state) -> {"validation": Validation, "events": [...]}
"""

# TODO(Phase 5): 实现 validate。
