"""条款库 & 历史案例库语料（纯 Python 数据，Phase 2 灌入 Milvus 用 / FR-5 / FR-6）。

职责：只放「数据」，不含任何检索/DB 逻辑。供 kb/ingest.py 读取后 embedding 入库。

两块语料：
  1. CLAUSES：保险条款片段。每条带元数据 —— {clause_no, product, category, text}
     category ∈ {报销比例, 免赔额, 除外责任, 等待期, 保障范围}
     必须覆盖：免赔额 10000、有社保报销比例 100%、等待期 30 天、既往症除外、住院保障范围。
     用途：clause_match 按 product+category 过滤检索，为 decide 提供可引用条款号（FR-5 / AC-8.4）。
  2. FRAUD_CASES：历史案例摘要。每条带 {case_no, product, summary, label}
     label ∈ {正常, 存疑, 欺诈}。必须含一条与 Case E 情节高度相似的「欺诈」案例，
     使 search_similar_cases 能命中 score≥0.8（BR-7 ④ / AC-6.2）。

要点：语料是 Milvus 检索质量的地基；条款文本尽量口语可读，便于 LLM/人工复核时对照。
"""

# TODO(Phase 2): 定义 CLAUSES: list[dict] 与 FRAUD_CASES: list[dict]，字段如上。
CLAUSES: list[dict] = []
FRAUD_CASES: list[dict] = []
