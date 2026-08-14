"""观测层入口 run（Phase 10 起）。带 Langfuse 观测地跑样例案件。

职责：import client（确保带 mask 的 client 在进程内**最先**初始化）→ 调 instrumented.run_claim 跑 A/B/E
     → 打印结果并提示去 Langfuse UI 看 trace。

与 core/app.py 的区别：app.py 纯业务无观测；run.py 叠加 Langfuse（trace/session/score/成本）。

自测：跑 A/B/E 后 UI 看到嵌套 trace（抽取/校验/条款/反欺诈/测算/决策/核赔）；含身份证材料显示脱敏（O-1/O-3）。

运行：python 综合实战_保险理赔Agent/obs/run.py
"""

import _setup  # noqa: F401  # 路径 + .env（obs 层统一入口）

# 顺序要点：client 必须在最前初始化（第一个 client 才带 mask）
# import client  # noqa: E402
# from instrumented import run_claim  # noqa: E402

# TODO(Phase 10→12): 编排跑 A/B/E + 打分 + 回归入口。
