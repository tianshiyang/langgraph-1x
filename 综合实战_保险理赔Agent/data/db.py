"""业务数据层 · Postgres 建表 + 种子 + 查询函数（Phase 1 / FR-1 / SRS §5.1）。

职责：
  1. 定义 clm_* 五张业务表（+可选 clm_fraud_watch），SQLAlchemy 2.0 ORM，风格对齐 provider/ecommerce.py。
  2. 幂等建表 + 灌入 A~E 五个样例案件（见 README §5.3 / SRS BR 造数）。
  3. 对外暴露「返回纯 dict」的查询函数，供 core 节点直接使用（不泄露 ORM 对象）。

设计要点：
  - 幂等：主键存在则跳过（session.get + merge）；建表用 create_all；可反复执行不产生脏数据（NFR-5）。
  - 表：clm_policies / clm_insureds / clm_claims / clm_claim_materials / clm_case_events（+可选 clm_fraud_watch）。
    每个字段加中文注释；金额用 Numeric，日期用 Date/DateTime。
  - 种子必须让下游可复算：Case A 应赔 8000、Case B 应赔 120000、Case C 落在等待期内/既往症、
    Case D 故意缺「费用清单」、Case E 造出「90 天内 3 次 + 关注名单机构 + 命中历史欺诈相似案例」。

待实现（供 Agent设计 §5 的「业务库工具」调用）：
  - get_claim(claim_id) -> dict | None
  - get_policy(policy_id) -> dict | None
  - get_insured(insured_id) -> dict | None
  - list_materials(claim_id) -> list[dict]
  - count_recent_claims(insured_id, before: date, days=90) -> int   # 反欺诈「短期多次」
  - hit_fraud_watch(hospital: str, insured_id: str) -> list[str]     # 名单命中
  - finalize_claim(claim_id, decision, amount, reason) -> None       # 写结论 + 更新 status
  - init_db() / seed() -> None                                       # 幂等建表 + 造数

自测（路线图 Phase 1）：`python data/db.py` 打印各表行数 + 5 个样例概览；手算校验 A/B 应赔金额。
"""

# TODO(Phase 1): 引入 provider 的 engine/Session 约定（参考 provider/ecommerce.py），定义 ORM + 上述函数。
# 入口自测时需要路径准备：
#   import pathlib, sys
#   sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
#   import _bootstrap  # noqa: E402
