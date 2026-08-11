"""观测层统一的路径与环境准备（被本目录各模块以 `import _setup` 的副作用方式调用）。

为什么需要它：本目录名为 `langfuse`、业务目录名为 `langchain`，与三方包同名。
只要遵守「按文件路径直接运行脚本、绝不把父目录 00_真实业务场景 加进 sys.path」，
`import langfuse` / `import langchain` 就仍从 site-packages 解析（这两个目录里都没有同名子模块）。
本模块负责把三处目录按需加入 sys.path，并加载 .env：
  - 项目根：为了 `from provider import glm_model`
  - 业务层 ../langchain：为了裸导入 knowledge_base / prompts / rag_service（业务模块内部也用裸导入）
  - 本目录：为了裸导入 client / hosted_prompts / instrumented / feedback

注意：业务层的 prompts.py 与本目录模块基名无重叠（本目录用 hosted_prompts.py），
因此两目录同时在 path 上也不会产生 `import prompts` 歧义。
"""

import pathlib
import sys

import dotenv

_THIS_DIR = pathlib.Path(__file__).resolve().parent  # .../00_真实业务场景/langfuse
_BUSINESS_DIR = _THIS_DIR.parent / "langchain"  # 业务实现层目录
_PROJECT_ROOT = _THIS_DIR.parents[2]  # 项目根 langgraph-1x

for _p in (str(_PROJECT_ROOT), str(_BUSINESS_DIR), str(_THIS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

dotenv.load_dotenv(_PROJECT_ROOT / ".env")  # 载入 LANGFUSE_* 与模型 API key
