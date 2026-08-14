"""Milvus 连接与通用 collection 操作（Phase 2 / FR-5 / FR-6）。

职责：封装 Milvus 客户端与「建库/索引/加载/检索」通用能力，不含业务语义。

待实现：
  - get_client() -> MilvusClient                     # 读 MILVUS_URI / MILVUS_TOKEN
  - ensure_collection(name, dim, fields) -> None      # 幂等建 collection + HNSW 索引 + load
  - upsert(name, rows: list[dict]) -> None            # 批量写入（含向量 + scalar 元数据字段）
  - search(name, query_vec, top_k=3, expr=None) -> list[dict]  # expr 做 metadata 过滤

要点：
  - 维度用 Phase 0 记下的 embedding 维度（provider.embeddings 的输出维度）。
  - 度量统一 COSINE（配合归一化最省心）；索引 HNSW。
  - product/category/clause_no/label 建为 scalar field，检索用 expr 过滤
    （如 `product == "医疗险" and category == "免赔额"`）。
  - 幂等（NFR-5）：ensure_collection 已存在则跳过；ingest 侧按业务主键去重或提供 drop 重建开关。
"""

# TODO(Phase 2): 用 pymilvus 的 MilvusClient 实现上述函数。
