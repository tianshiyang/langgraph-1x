"""集中配置：产品参数与决策阈值（SRS §4「阈值集中管理」）。

职责：把所有「可能被调参/回归」的常量收在一处，evaluate.py 回归时改这里即可（O-6）。
禁止在节点里散落魔法数字。

待定义（值见 SRS §4 / BR-6 / BR-7 / BR-8）：
  - DEDUCTIBLE = 10000          # 免赔额
  - RATE_WITH_SOCIAL = 1.0      # 有社保报销比例
  - WAITING_DAYS = 30           # 等待期天数
  - SUM_INSURED = 3000000       # 保额
  - AUTO_PAY_LIMIT = 10000      # 直赔金额上限
  - LARGE_AMOUNT = 100000       # 大额阈值（单次申报 >10 万计一个欺诈信号）
  - SIMILAR_FRAUD_THRESHOLD = 0.8   # 相似欺诈案例判定阈值
  - SHORT_TERM_WINDOW_DAYS = 90     # 「短期多次」时间窗
  - REQUIRED_MATERIALS = ("发票", "费用清单", "诊断证明")  # BR-1 必需材料
"""

# TODO(Phase 5/7): 按上表定义常量。回归测试（O-6）会把 DEDUCTIBLE 10000→15000。
