"""保单核对 policy_check · 准入判断 + 读测算参数（Phase 5 / FR-4 / BR-3/4/5）。

职责：判定保单是否可赔（准入），并读出测算所需参数。任一 blocker 非空 → 后续 decide 判拒赔。

契约（Agent设计 §4）：读 claim/policy/extracts → 写 policy_check/events；
  既往症判定可选 LLM（失败降级为关键词匹配）。

判定规则（写入 PolicyCheck，见 SRS §2.2）：
  - BR-3 保单有效：policy.status=="有效" 且 effective_date ≤ incident_date ≤ expiry_date；否则 blockers 含「保单未生效或已失效」（AC-4.1）。
  - BR-4 等待期：incident_date ≥ effective_date + config.WAITING_DAYS，否则 passed_waiting=False + blockers 含「等待期内出险」（AC-4.2）。
  - BR-5 既往症：diagnosis 命中 preexisting_note（关键词或 LLM）→ preexisting_excluded=True + blockers 含「既往症除外」（AC-4.3）。
  - 读出 deductible/rate/remaining_sum，与保单一致（AC-4.4）。

要点：既往症若用 LLM，失败要降级为关键词匹配（Agent设计 §6），不得因 LLM 挂了就误放行。

待实现：def policy_check(state) -> {"policy_check": PolicyCheck, "events": [...]}
"""

# TODO(Phase 5): 实现 policy_check。
