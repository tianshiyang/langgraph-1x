"""检索工具：面向业务语义的两个检索函数（Phase 2 / FR-5 / FR-6）。

职责：把 milvus_store.search 封装成「节点能直接用」的业务检索，返回结构化结果。
      工具不含业务判断（判断留给节点/确定性代码）。

待实现（对齐 Agent设计 §5 检索工具契约）：
  - search_clauses(query, product, category=None, top_k=3) -> list[ClauseEvidence]
        # 按险种/类别过滤；返回 {clause_no, category, text, score}
  - search_similar_cases(summary, product, top_k=3) -> list[dict]
        # 反欺诈用；返回 {summary, label, score}

要点：
  - query/summary 先 embed 再 search；expr 拼 product(+category) 过滤（AC-5.1）。
  - 检索为空/超时不抛给上层崩溃——返回 [] 由节点决定降级（AC-5.3 / 容错见 Agent设计 §6）。
  - ClauseEvidence 结构见 SRS §2.2。
"""

# TODO(Phase 2): 依赖 milvus_store + provider.embeddings 实现上述两个函数。
