"""图装配 graph · intake + 出具结论节点 + 组图（Phase 3 起，贯穿 3/5/6/7/8）。

职责：定义 intake 与 出具结论节点，把所有节点组装成 StateGraph 并编译。

本文件承载的节点：
  - intake（FR-1，Phase 3）：读库装载 claim/policy/insured/materials（唯一读库节点）。
        AC-1.1 有效 claim_id → 三快照非空 + materials 数正确；AC-1.2 不存在 → 抛异常 + 记事件。
  - auto_pay / reject / finalize（FR-10，Phase 7/8）：生成结论文书（LLM 写话术）+ 落库 + 记事件。
        AC-10.1 通过含金额+条款依据、拒赔含条款号+通俗解释；AC-10.2 status→已赔付/已拒赔/待补件。
        话术失败 → 模板兜底（金额/决策不受影响，Agent设计 §6）。

图拓扑（Agent设计 §3）：
  intake → extract(Send 并行) → validate
    ├─(缺件/矛盾)→ need_more(END/挂起)
    └─(通过)→ policy_check → [clause_match ∥ fraud] → settle → decide
                 decide ──Command──▶ auto_pay / human_review / reject → finalize → END

分阶段装配：
  - Phase 3：仅 intake + 抽取桩 + END，能 compile/invoke。
  - Phase 5：加 validate 条件边 + policy_check。
  - Phase 6：policy_check 后**并行** clause_match ∥ fraud，join 到 settle。
  - Phase 7：加 settle + decide(Command) + auto_pay/reject。
  - Phase 8：加 human_review，compile(checkpointer=PostgresSaver(...))，thread_id=claim_id。
  - Phase 9：接 store（长期记忆）；用 get_state_history 演示时间旅行。

待实现：
  - intake(state) / auto_pay(state) / reject(state) / finalize(state)
  - build_graph(*, checkpointer=None, store=None) -> CompiledGraph
"""

# TODO(Phase 3→8): 按阶段逐步装配；并行边用两条出边 + join 节点。
