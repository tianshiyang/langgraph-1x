"""
场景 6 · Prompt 变量、消息占位符与客户端缓存
============================================================
目标：
  1) chat 类型 prompt 的多消息模板（system / 历史占位 / user）
  2) {{变量}} 用 compile 填充；历史消息用「占位符 placeholder」注入
  3) 客户端缓存 cache_ttl_seconds：拉取一次后本地缓存，零额外延迟

关键点：
  - 创建 chat prompt 时，一条「占位符消息」写成 {"type": "placeholder", "name": "history"}
  - compile 时传 history=[{"role": "...", "content": "..."}, ...] 注入历史
  - compile 返回的是「消息字典列表」，用 convert_to_messages 转成 LangChain 消息

运行：
    python "Langfuse实战/02_Prompt管理/s6_prompt变量与缓存.py"
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from langchain_core.messages import convert_to_messages

from Langfuse实战._bootstrap import glm_model, langfuse

PROMPT_NAME = "tutorial-客服助手"


# 首次运行时播种一个带变量 + 占位符的 chat prompt
def seed_prompt_once() -> None:
    try:
        langfuse.get_prompt(PROMPT_NAME, label="production", type="chat")
        print(f"Prompt「{PROMPT_NAME}」已存在，跳过播种。")
        return
    except Exception:
        pass

    langfuse.create_prompt(
        name=PROMPT_NAME,
        type="chat",
        prompt=[
            # system：用 {{brand}} / {{tone}} 两个变量
            {
                "role": "system",
                "content": "你是「{{brand}}」的在线客服，语气{{tone}}。",
            },
            # 占位符：运行时注入多轮历史消息
            {"type": "placeholder", "name": "history"},
            # 本轮用户问题
            {"role": "user", "content": "{{question}}"},
        ],
        labels=["production"],
        commit_message="v1 客服 chat 模板（变量+历史占位符）",
    )
    print(f"已播种 chat Prompt「{PROMPT_NAME}」")


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    seed_prompt_once()

    # 拉取时开启客户端缓存：60 秒内再次 get_prompt 直接命中本地缓存，不走网络
    prompt = langfuse.get_prompt(
        PROMPT_NAME, label="production", type="chat", cache_ttl_seconds=60
    )
    print(f"拉到第 {prompt.version} 版，变量列表：{prompt.variables}")

    # 模拟已有两轮历史对话
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "您好，很高兴为您服务～"},
    ]

    # compile：同时填充变量 + 注入历史占位符
    compiled = prompt.compile(
        brand="Acme 商城",
        tone="亲切耐心",
        question="我上周买的鞋子想退货，怎么操作？",
        history=history,  # 注入到 placeholder(name="history")
    )
    print("\ncompile 后的消息列表：")
    for m in compiled:
        print("  ", m)

    # 转成 LangChain 消息后调用模型
    messages = convert_to_messages(compiled)
    response = glm_model.invoke(messages)
    print("\n[客服回答]\n", response.content)

    # 演示缓存命中：第二次拉取不会再发网络请求（同一进程内）
    prompt_again = langfuse.get_prompt(
        PROMPT_NAME, label="production", type="chat", cache_ttl_seconds=60
    )
    print(f"\n第二次拉取命中缓存（版本仍为 {prompt_again.version}），零额外延迟。")

    langfuse.flush()
