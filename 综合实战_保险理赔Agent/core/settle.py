"""赔付测算 settle · 确定性计算（Phase 7 / FR-7 / BR-6）。**禁用 LLM，每项可复算。**

职责：按公式算 Settlement，各中间项落库供审计手工复算（NFR-3）。这是全系统正确性的地基。

契约（Agent设计 §4）：读 policy_check/extracts → 写 settlement/events；调 LLM：否（禁用）；纯计算，必对。

公式（BR-6，写入 Settlement 见 SRS §2.2）：
    reasonable        = invoice_total - social_paid - excluded
    payable_before_cap = max(0, reasonable - deductible) * rate
    payable            = min(payable_before_cap, remaining_sum)

验收（U-1 必须逐项对）：
    (28000,10000,0,ded=10000,rate=1.0,cap=3000000) -> payable 8000     # Case A
    (180000,50000,0,10000,1.0,3000000)             -> 120000           # Case B
    (12000,10000,0,10000,1.0,3000000)              -> 0                # 免赔额以下
    (28000,0,3000,10000,0.6,3000000)               -> 9000             # 无社保 60%
    (500000,0,0,10000,1.0,300000)                  -> 300000           # 保额封顶

待实现：def settle(state) -> {"settlement": Settlement, "events": [...]}
"""

# TODO(Phase 7): 实现纯函数 settle；先过 U-1 再往下。
