"""离线回归 evaluate（Phase 12 / 埋点规范 §9 / 测试 O-6）。**对比行业标准的关键。**

职责：把 A~E 做成 Langfuse Dataset，Experiment 跑基线；改规则重跑；输出前后差异对比报告。

流程（O-6）：
  1. Dataset `claim-regression`：item = E-A~E-E（input=claim_id，expected=预期 route+payable）。
  2. Run 基线：记录各案 route+payable。
  3. 改规则：config.DEDUCTIBLE 10000→15000，重跑一个 Run。
  4. 期望差异：E-A payable 8000→3000（(28000-10000-15000)=3000），其余路由不变。
  5. 断言：报告能列「变更前后 payable/route 差异表」，E-A 差异 -5000，无未预期回归。

（进阶）Annotation Queue：把 HITL adjust 差异案例推入队列，人工标注回流为评测集。

待实现：
  - build_dataset() / run_experiment(tag) / diff_runs(base, new) -> 报告
"""

import _setup  # noqa: F401

# TODO(Phase 12): 用 Langfuse Dataset/Experiment 实现回归对比。
