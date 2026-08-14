"""业务层入口 app · 独立跑通五个样例案件，**完全不依赖 Langfuse**（NFR-6）。

这是纯业务层验收线（路线图 Phase 9 末）：core/ 断掉观测层仍能完成审核。

职责：装配图 → 依次对 CLM-A~CLM-E invoke → 打印最终路由 + 关键 state（payable/route/status）。
     大额/欺诈案件会停在 human_review 的 interrupt，可用 Command(resume=...) 续跑（H 系列）。

期望（E-A~E-E，见测试文档 §L3）：
  A→auto_pay payable=8000  B→human_review payable=120000  C→reject(引条款)
  D→need_more(缺费用清单)   E→human_review(风险=高)

运行：python 综合实战_保险理赔Agent/core/app.py
"""

import pathlib
import sys

# 入口负责路径准备：加「综合实战_保险理赔Agent」根，再由 _bootstrap 补 provider/data/kb/core + load .env
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402,F401  # 副作用：补 sys.path + load_dotenv（不 import langfuse）

# TODO(Phase 3→9): from graph import build_graph；逐案 invoke 并打印结果。
