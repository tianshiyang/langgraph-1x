"""核心：在业务层之上叠加 Langfuse 观测，业务代码零改动。

做法：不改 ../langchain 里的任何代码，只在这里「组合业务原子能力 + 挂回调 + 包观测上下文」：
  - 检索用 @observe(as_type="retriever") 单独成一个可观测节点；
  - 模型调用挂 CallbackHandler → 自动记 generation 与真实 token / cost；
  - 每一轮用 propagate_attributes 归到同一个 user_id / session_id → UI 里聚成一个多轮会话；
  - 关联 Langfuse 托管的线上人设 Prompt。
每轮对话产生一个 trace（root 为 support-turn chain），多轮共享 session_id。
"""

from __future__ import annotations

from typing import TypedDict

import _setup  # noqa: F401  # 副作用：准备 sys.path 与 .env

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langfuse import observe, propagate_attributes

import hosted_prompts
import rag_service
from client import langfuse, make_callback_handler
from knowledge_base import RetrievedDoc
from prompts import build_messages

from provider import glm_model


# 带观测的一轮结果（比业务多一个 trace_id，便于事后在线打分）
class ObservedTurn(TypedDict):
    answer: str  # 回答文本
    docs: list[RetrievedDoc]  # 命中文档
    trace_id: str | None  # 本轮 trace id


# 检索节点：单独记成 retriever 观测，输出命中概览（不 dump 全文，避免噪声）
@observe(as_type="retriever", name="knowledge-retrieval", capture_output=False)
def _observed_retrieve(question: str, top_k: int = 3) -> list[RetrievedDoc]:
    docs = rag_service.retrieve(question, top_k=top_k)
    langfuse.update_current_span(
        output={
            "count": len(docs),
            "hits": [{"title": d["title"], "score": d["score"]} for d in docs],
        }
    )
    return docs


# 带观测的多轮客服会话
class InstrumentedSupportSession:
    def __init__(self, *, user_id: str, session_id: str) -> None:
        self.user_id = user_id  # 用户标识（归入 trace，便于按用户排查）
        self.session_id = session_id  # 会话标识（多轮聚成一个 Session）
        self.history: list[BaseMessage] = []  # 对话历史（不含 system）
        self._prompt = hosted_prompts.load_support_prompt()  # 托管的线上人设，用于关联
        self._system_text = hosted_prompts.get_system_text(self._prompt)  # 线上人设文案

    # 提问一轮：把本轮所有 span 归到同一 user/session 并关联托管 prompt
    def ask(self, question: str) -> ObservedTurn:
        with propagate_attributes(
            user_id=self.user_id,
            session_id=self.session_id,
            tags=["support", "rag"],
            prompt=self._prompt,
        ):
            return self._answer_one_turn(question)

    # 单轮编排：retriever 节点 → 拼消息 → 挂回调调模型（自动记 generation）
    def _answer_one_turn(self, question: str) -> ObservedTurn:
        with langfuse.start_as_current_observation(
            name="support-turn", as_type="chain", input=question
        ):
            docs = _observed_retrieve(question)
            messages = build_messages(
                question, docs, self.history, system_prompt=self._system_text
            )
            handler = make_callback_handler()
            response = glm_model.invoke(messages, config={"callbacks": [handler]})
            answer = response.content

            self.history.append(HumanMessage(question))
            self.history.append(AIMessage(answer))

            trace_id = langfuse.get_current_trace_id()
            langfuse.update_current_span(output=answer)
            return {"answer": answer, "docs": docs, "trace_id": trace_id}
