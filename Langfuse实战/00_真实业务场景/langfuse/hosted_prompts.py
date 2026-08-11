"""把客服人设托管到 Langfuse，实现「运营在 UI 改 Prompt 就能改线上行为，工程师不介入」。

- seed_support_prompt(): 幂等播种，首次把业务基线人设写成一个 chat 版本并打 production 标签。
- load_support_prompt(): 运行时按 production 标签拉取，带本地缓存与 fallback（拉取失败退回业务基线）。
- get_system_text(): 从拉取到的 Prompt 取出 system 文案，交给业务 build_messages 作为线上人设。

运行时的检索资料仍由业务层动态拼接，托管的只是「可被运营调优的人设/指令」部分。
"""

from __future__ import annotations

import _setup  # noqa: F401  # 副作用：准备 sys.path 与 .env

from langfuse.model import ChatPromptClient

from client import langfuse
from prompts import SUPPORT_SYSTEM_PROMPT  # 业务基线人设，作为播种内容与 fallback

# 托管 Prompt 名称
PROMPT_NAME = "support-客服助手"

# chat 版兜底内容：拉取失败时用业务基线人设
_FALLBACK_CHAT = [{"role": "system", "content": SUPPORT_SYSTEM_PROMPT}]


# 幂等播种：已存在则跳过，避免重复运行狂造版本
def seed_support_prompt() -> None:
    try:
        langfuse.get_prompt(PROMPT_NAME, label="production", type="chat")
        print(f"Prompt「{PROMPT_NAME}」已存在，跳过播种。")
        return
    except Exception:
        langfuse.create_prompt(
            name=PROMPT_NAME,
            prompt=[{"role": "system", "content": SUPPORT_SYSTEM_PROMPT}],
            labels=["production"],
            type="chat",
            commit_message="v1 客服基线人设",
        )
        print(f"已播种 Prompt「{PROMPT_NAME}」并打上 production 标签。")


# 拉取线上人设（带缓存 + fallback），返回 ChatPromptClient
def load_support_prompt() -> ChatPromptClient:
    return langfuse.get_prompt(
        PROMPT_NAME,
        label="production",
        type="chat",
        cache_ttl_seconds=60,
        fallback=_FALLBACK_CHAT,
    )


# 从 Prompt 取出 system 文案（供业务 build_messages 覆盖默认人设）
def get_system_text(prompt: ChatPromptClient) -> str:
    for message in prompt.compile():
        if message.get("role") == "system":
            return message.get("content", SUPPORT_SYSTEM_PROMPT)
    return SUPPORT_SYSTEM_PROMPT
