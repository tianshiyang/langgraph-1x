"""观测叠加 instrumented（Phase 10 / 埋点规范 §2-4 / Agent设计 §9）。

职责：**不改 core 一行**，给 graph.invoke 叠加 trace/session/span + 挂 CallbackHandler。

做法：
  - 每案件一个 root trace `claim-review`；补件多轮用 session_id=claim_id 串联（propagate_attributes）。
  - propagate_attributes(session_id=claim_id, user_id=insured_id, tags=["claim-review", product], prompt=...)。
  - 给 model.invoke 挂 make_callback_handler() → generation/token/cost 自动记录。
  - 检索类（clause-retrieval / similar-case-retrieval）用 @observe(as_type="retriever", capture_output=False)，
    output 只记命中概览 [{clause_no/label, score}]（降噪省成本，埋点规范 §4.1）。
  - settle/decide span 的 output 记明细与依据（可复算可解释，合规核心 §4.2）。
  - 决策后 update_current_trace(tags=[..., decision.route]) 便于按路由统计。

span 命名/类型对照表见埋点规范 §2；验收 O-1~O-4。

待实现：
  - run_claim(claim_id, *, resume=None) -> ClaimResult   # 包一层观测后调用 core 图
"""

import _setup  # noqa: F401

# TODO(Phase 10): 用 propagate_attributes + CallbackHandler + start_as_current_observation 叠加观测。
