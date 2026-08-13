
import pathlib
import sys

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langfuse import observe, propagate_attributes
from langfuse.langchain import CallbackHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # 项目根：使绝对导入 Langfuse实战.* 生效
from Langfuse实战._bootstrap import glm_model, langfuse

"""
场景 2 · Session 会话串联
============================================================
目标：把同一个用户的多轮对话，用同一个 session_id 归到一组，
     在 UI 的 Sessions 页面里像看聊天记录一样回放整个会话。

关键 API：propagate_attributes(session_id=..., user_id=...)
  —— 这是官方推荐的方式：在一个上下文里设置 session_id / user_id，
     该上下文内所有 span（包括 LangChain 自动产生的）都会自动带上。

运行：
    python "Langfuse实战/01_可观测性/s2_session会话串联.py"
运行后去 UI 的 Sessions 页面，找到本次 session。
"""

# 每轮对话都用这个回调，把 LangChain 的调用自动上报为 generation
langfuse_handler = CallbackHandler()

# 系统设定：一个带记忆的聊天助手
SYSTEM_PROMPT = "你是一个友好的中文聊天助手，回答尽量简洁。"


# 处理单轮对话：把历史 + 本轮问题一起发给模型
@observe(name="chat-turn")
def chat_turn(history: list, user_text: str) -> str:
    messages = [SystemMessage(SYSTEM_PROMPT), *history, HumanMessage(user_text)]
    # 通过 config.callbacks 让这次调用挂到当前 trace 下
    response = glm_model.invoke(messages, config={"callbacks": [langfuse_handler]})
    return response.content


# 模拟一段 3 轮的连续对话，全部归到同一个 session
def run_conversation(session_id: str, user_id: str) -> None:
    # propagate_attributes：本 with 块内所有 span 自动带上 session_id / user_id
    with propagate_attributes(session_id=session_id, user_id=user_id):
        history: list = []

        turns = [
            "我叫小田，正在学 LangGraph。",
            "帮我用一句话解释什么是 checkpoint。",
            "那你还记得我叫什么名字吗？",  # 验证多轮上下文是否连贯
        ]

        for user_text in turns:
            print(f"\n[用户] {user_text}")
            answer = chat_turn(history, user_text)
            print(f"[助手] {answer}")
            # 维护对话历史，供下一轮使用
            history.append(HumanMessage(user_text))
            history.append(AIMessage(answer))


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    # session_id 由业务自己生成（这里用固定值方便你在 UI 里找）；真实场景用会话/工单 ID
    session_id = "demo-session-xiaotian-001"
    user_id = "user-xiaotian"

    run_conversation(session_id, user_id)

    langfuse.flush()
    print(f"\n已上报。去 UI 的 Sessions 页面搜索 session_id = {session_id}")
    print("你会看到 3 轮对话被归在同一个会话里，可整体回放。")
