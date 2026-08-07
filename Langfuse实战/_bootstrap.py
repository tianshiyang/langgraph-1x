"""
共享启动引导：让 Langfuse实战 下的脚本无论从哪个目录运行，都能：
1. 把项目根目录加入 sys.path，从而能 `from provider import glm_model`
2. 加载 .env 里的 LANGFUSE_* 环境变量

用法：在每个脚本顶部写
    from _bootstrap import langfuse, glm_model
或
    import _bootstrap  # 只为副作用（加 sys.path + load_dotenv）
"""

import pathlib
import sys

import dotenv

# 项目根目录（Langfuse实战 的上一级）
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 加载 .env（LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL 等）
dotenv.load_dotenv(_PROJECT_ROOT / ".env")

from langfuse import get_client  # noqa: E402

from provider import glm_model  # noqa: E402

# 全局单例客户端：读取环境变量完成鉴权
langfuse = get_client()

__all__ = ["langfuse", "glm_model", "get_client"]
