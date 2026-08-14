"""灌库脚本：把 data/raw_clauses.py 的语料 embedding 后写入 Milvus（Phase 2 / FR-5 / FR-6）。

职责：读语料 → provider.embeddings.embed_query 逐条向量化 → 组装带元数据的行 → upsert 两个 collection。

两个 collection：
  - insurance_clauses：条款库（向量 + clause_no/product/category/text）
  - claim_cases_history：历史案例库（向量 + case_no/product/summary/label）

要点：
  - 幂等（NFR-5）：重复灌不产生重复数据（按业务主键去重，或 --recreate 开关先 drop 再建）。
  - embedding 的文本：条款用 text，案例用 summary。

自测（路线图 Phase 2）：灌完后用 kb/retriever 查「住院费用免赔额怎么算」top 命中免赔额条款；
  加 expr 过滤险种后结果收窄；相似案例能命中 Case E 对应的历史欺诈案例。
"""

# TODO(Phase 2): 实现 main() 完成灌库；入口需路径准备：
#   import pathlib, sys
#   sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
#   import _bootstrap  # noqa: E402
