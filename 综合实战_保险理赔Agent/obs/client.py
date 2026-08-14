"""Langfuse 客户端 client（Phase 10 / 埋点规范 §1）。进程内唯一 client，带 client 级 mask + environment。

职责：初始化全局 Langfuse 客户端（第一个 client 必须传 mask）；提供 CallbackHandler 工厂。

参考实现（埋点规范 §1，对齐 v3 写法）：
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler
    from pii import mask_pii
    langfuse = Langfuse(mask=mask_pii, environment="production")
    def make_callback_handler() -> CallbackHandler: return CallbackHandler()

注意：mask 必须在「进程内第一个 client」传入才生效——所以 obs/run.py 要先 import client 再干别的。

待实现：langfuse 单例 + make_callback_handler()
"""

import _setup  # noqa: F401  # 副作用：路径 + .env

# TODO(Phase 10): 初始化带 mask 的 Langfuse 单例 + CallbackHandler 工厂。
