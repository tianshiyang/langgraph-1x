"""共享启动引导：让本项目任意脚本无论从哪个目录运行，都能正确解析导入并载入 .env。

设计对齐 `Langfuse实战/00_真实业务场景` 的路径约定：
  - 「按文件路径直接运行脚本」，各层模块之间用**裸导入**（`import state` / `from db import ...`）。
  - 本模块把「项目根 + 四个分层目录」加入 sys.path，并加载项目根的 .env。

加入 sys.path 的目录及其原因：
  - 项目根 langgraph-1x  → 为了 `from provider import glm_model, embeddings`
  - data/                → 为了裸导入 db / raw_clauses
  - kb/                  → 为了裸导入 milvus_store / ingest / retriever
  - core/                → 为了裸导入 state / extract / ... / graph
  - obs/                 → 为了裸导入 client / pii / instrumented ...（仅观测层入口需要）

注意：
  - 本模块**只做路径与环境准备，绝不 import langfuse**——保证 core/ 能在完全没有观测层的情况下独立运行。
  - 各层模块基名全局唯一（db/state/extract/.../client/pii...无重名），所以四层同时在 path 上不产生歧义。

用法（仅「被直接运行的入口文件」需要，被 import 的模块不需要）：
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # 综合实战_保险理赔Agent
    import _bootstrap  # noqa: E402  # 副作用：补 sys.path + load_dotenv
"""

import pathlib
import sys

import dotenv

_THIS_DIR = pathlib.Path(__file__).resolve().parent  # 综合实战_保险理赔Agent
_PROJECT_ROOT = _THIS_DIR.parents[0].parent  # langgraph-1x（项目根）

# 项目根 + 四个分层目录，按需加入 sys.path
_PATHS = (
    _PROJECT_ROOT,  # provider 包所在
    _THIS_DIR / "data",  # 业务数据层
    _THIS_DIR / "kb",  # Milvus 知识层
    _THIS_DIR / "core",  # Agent 业务层
    _THIS_DIR / "obs",  # 观测层
)
for _p in _PATHS:
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

# 载入 .env：DB_URI（Postgres）、MILVUS_URI/MILVUS_TOKEN、模型与 LANGFUSE_* key
dotenv.load_dotenv(_PROJECT_ROOT / ".env")
