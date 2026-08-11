"""RAG 客服核心：检索 → 拼上下文 → 调模型生成带引用的回答，并支持多轮追问。

说明：本模块是「库」，不做 sys.path 处理，依赖调用方（app.py / 观测层入口）预先把
项目根目录与本目录加入 sys.path，因此这里可直接 `from provider import glm_model`
以及裸导入同目录的 knowledge_base / prompts（与项目现有脚本约定一致）。
本模块完全不 import langfuse。
"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

import knowledge_base
from knowledge_base import RetrievedDoc
from prompts import build_messages

from provider import glm_model


# 一轮问答的结果
class AnswerResult(TypedDict):
    answer: str  # 模型生成的回答文本
    docs: list[RetrievedDoc]  # 本轮检索命中的文档


# 检索知识库（薄封装，便于观测层单独包一层 retriever 观测）
def retrieve(query: str, top_k: int = 3) -> list[RetrievedDoc]:
    return knowledge_base.search(query, top_k=top_k)


# 单轮问答：检索 → 拼消息 → 调模型。config 透传给 LangChain（业务不关心里面装了什么回调）
def answer(
    question: str,
    history: list[BaseMessage] | None = None,
    *,
    config: RunnableConfig | None = None,
    top_k: int = 3,
) -> AnswerResult:
    docs = retrieve(question, top_k=top_k)
    messages = build_messages(question, docs, history)
    response = glm_model.invoke(messages, config=config)
    return {"answer": response.content, "docs": docs}


# 多轮客服会话：维护对话历史，支持基于上文的追问
class SupportSession:
    def __init__(self) -> None:
        self.history: list[BaseMessage] = []  # 累积的历史消息（不含 system）

    # 提问一轮：内部检索+生成，并把本轮 Q/A 追加进历史。config 原样透传给模型调用
    def ask(self, question: str, *, config: RunnableConfig | None = None) -> AnswerResult:
        result = answer(question, self.history, config=config)
        self.history.append(HumanMessage(question))
        self.history.append(AIMessage(result["answer"]))
        return result
