"""材料抽取 · Send 并行 Map-Reduce（Phase 4 / FR-2）。

职责：对 materials 中每份材料**并行**调 LLM 抽结构化字段，结果 reduce 回 state.extracts。

契约（Agent设计 §4）：
  fan_out：读 materials，用 Send 对每份材料下发一个 extract_one 子任务。
  extract_one：读 单份 material（Send 载荷）→ 写 extracts(+1)。调 LLM：是（结构化输出）。

待实现：
  - fan_out(state) -> list[Send]                 # Map：Send("extract_one", {material})
  - extract_one(payload) -> {"extracts": [MaterialExtract]}   # 结果经 reducer 合并

要点（行业标准）：
  - 结构化输出：model.with_structured_output(Schema)，**绝不正则抠自由文本拿金额**。各类型 fields schema 见 SRS §2.2。
  - 容错（AC-2.2/2.3 / Agent设计 §6）：单份抽取重试 2 次（指数退避）；仍失败 → status="异常"+error 非空，
    **不阻断其他材料**。Phase 4 先搭雏形，Phase 9 做扎实。
  - 抽取 prompt 走托管（obs/prompts.py）+ 本地回退；temperature=0。
"""

# TODO(Phase 4): 实现 fan_out + extract_one；Phase 9 补重试/降级。
