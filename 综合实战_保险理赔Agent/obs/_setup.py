"""观测层路径/环境准备（Phase 10）。被 obs/ 各模块以 `import _setup` 副作用调用。

职责：复用根级 _bootstrap 完成 sys.path + .env 准备（obs 是唯一 import langfuse 的层）。
      单独留此文件是为对齐 00_真实业务场景/langfuse/_setup.py 的分层习惯，且给 obs 一个统一入口点。

注意：core/ 不会 import 本模块，也不 import 任何 langfuse——保证业务层可独立运行（NFR-6）。
"""

import pathlib
import sys

# 先把「综合实战_保险理赔Agent」根加入 path，才能 import 根级 _bootstrap
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402,F401  # 副作用：补 provider/data/kb/core/obs 到 path + load_dotenv
