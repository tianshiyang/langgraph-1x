"""带 PII 脱敏的 Langfuse 客户端（本目录统一从这里取 client / CallbackHandler）。

要点：`mask` 是客户端级配置，必须在进程内用该 public_key 创建**第一个** client 时传入。
因此本目录**不复用** `Langfuse实战/_bootstrap.py` 的默认单例（那个没带 mask），而是在这里自建。
观测层其余模块一律 `from client import langfuse`，保证全程使用这个带 mask 的实例。
"""

from __future__ import annotations

import _setup  # noqa: F401  # 副作用：准备 sys.path 与 .env

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from pii import mask_pii

# 进程内第一个（也是唯一）Langfuse 客户端，带脱敏钩子与环境标记
langfuse = Langfuse(mask=mask_pii, environment="production")


# 为每轮对话新建一个 LangChain 回调处理器（自动记录 generation 与真实 token/cost）
def make_callback_handler() -> CallbackHandler:
    return CallbackHandler()
