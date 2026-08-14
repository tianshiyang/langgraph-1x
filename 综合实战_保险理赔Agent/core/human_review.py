"""人工核赔 human_review · HITL 中断/恢复（Phase 8 / FR-9 / BR-9）。

职责：转人工案件在此 interrupt 展示证据包，接收核赔员裁决后 resume 并路由。

契约（Agent设计 §4/§7）：读 decision/settlement/clause_evidence/fraud → 写 adjuster_action（resume 注入）；interrupt。

协议：
  - 中断：interrupt(payload)，payload = 证据包（AC-9.1）：应赔额 + Settlement 明细 + clause_evidence
          + fraud.signals + 关键抽取字段。图在此暂停，checkpointer 落盘。
  - 恢复：graph.invoke(Command(resume=AdjusterAction), config={"configurable":{"thread_id": claim_id}})。
  - 四动作（AC-9.2）：
        approve → 按 Agent payable 出具
        adjust  → 按核赔员 amount 出具，且记「差异」事件（回流评估样本）
        reject  → 拒赔（文书含核赔员理由）
        return  → 回 need_more（待补件）
  - AC-9.3：进程重启后凭 claim_id 恢复到中断点继续。

待实现：def human_review(state) -> Command   # 校验 resume 载荷后按 action 路由
"""

# TODO(Phase 8): 实现 interrupt + resume 分派；图在 Phase 8 compile(checkpointer=PostgresSaver)。
