from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.config import get_stream_writer
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

from provider import glm_model

load_dotenv(Path(__file__).parent.parent.parent / ".env")


class QAState(TypedDict):
    question: str
    answer: str


def _answer_node(state: QAState) -> QAState:
    resp = glm_model.invoke(
        [
            SystemMessage("你是简洁的助手，用一两句话回答"),
            HumanMessage(state["question"]),
        ]
    )
    return {"answer": resp.content}


def _build_qa_graph():
    builder = StateGraph(QAState)
    builder.add_node("answer", _answer_node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile()


# ═════════════════════════════════════════════
# 01. messages 逐 token 输出       【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════
def demo_messages():
    graph = _build_qa_graph()
    for chunk, metadata in graph.stream(
        {"question": "用一句话介绍杭州。", "answer": ""},
        stream_mode="messages",
    ):
        # chunk 是 AIMessageChunk；content 可能为 '' (首尾空块)，照打不影响
        print(chunk.content, end="", flush=True)
    print()


def demo_updates():
    class S(TypedDict):
        question: str
        topic: str
        answer: str

    def classify(state: S) -> S:
        return {"topic": "地理"}

    def answer(state: S) -> S:
        resp = glm_model.invoke([HumanMessage(state["question"])])
        return {"answer": resp.content}

    graph = (
        StateGraph(S)
        .add_node("classify", classify)
        .add_node("answer", answer)
        .add_edge(START, "classify")
        .add_edge("classify", "answer")
        .add_edge("answer", END)
        .compile()
    )

    for update in graph.stream(
        {"question": "珠穆朗玛峰有多高", "answer": "", "topic": ""},
        stream_mode="updates",
    ):
        print(update)


# ═════════════════════════════════════════════
# 03. values 完整状态快照          【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════
def demo_values():
    graph = _build_qa_graph()
    last = None
    for snapshot in graph.stream(
        {"question": "Python 之父是谁？", "answer": ""},
        stream_mode="values",
    ):
        # snapshot 是完整 state：第1帧 answer 还为空，最后一帧 answer 已填好
        ans = snapshot.get("answer", "")
        print(f"   快照: question={snapshot['question']!r}, answer={ans[:30]!r}")
        last = snapshot
    print(f"   → 最终 answer: {last['answer']}")


def demo_custom():
    class S(TypedDict):
        result: str

    def heavy_task(state: S) -> S:
        writer = get_stream_writer()
        writer({"type": "progress", "stage": "连接数据库", "percent": 10})
        writer({"type": "progress", "stage": "查询记录", "percent": 50})
        writer({"type": "log", "msg": "命中 3 条记录"})
        writer({"type": "progress", "stage": "汇总结果", "percent": 90})
        return {"result": "完成"}

    graph = (
        StateGraph(S)
        .add_node("heavy_task", heavy_task)
        .add_edge(START, "heavy_task")
        .add_edge("heavy_task", END)
        .compile()
    )

    for event in graph.stream(
        {"result": ""},
        stream_mode="custom",
    ):
        print(event)
        # if event.get("type") == "progress":
        #     print(f"   [{event['percent']:>3}%] {event['stage']}")
        # else:
        #     print(f"   · {event['msg']}")


# ═════════════════════════════════════════════
# 05. 多模式组合 stream_mode=[...]   【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════
def demo_combined():
    class S(TypedDict):
        question: str
        answer: str

    def reply(state: S) -> S:
        writer = get_stream_writer()
        writer({"stage": "思考中"})
        resp = glm_model.invoke(
            [
                SystemMessage("用一句话回答。"),
                HumanMessage(state["question"]),
            ]
        )
        writer({"stage": "回答完毕"})
        return {"answer": resp.content}

    graph = (
        StateGraph(S)
        .add_node("reply", reply)
        .add_edge(START, "reply")
        .add_edge("reply", END)
        .compile()
    )

    for mode, chunk in graph.stream(
        {"question": "世界上最大的海洋是哪个？", "answer": ""},
        stream_mode=["custom", "messages", "updates"],  # ⭐️ 传 list
    ):
        print(mode, chunk)
        if mode == "custom":
            print(f"\n   〔进度〕{chunk['stage']}")
        elif mode == "messages":
            print(chunk[0].content, end="", flush=True)  # 逐 token 打字机
        elif mode == "updates":
            print(f"\n   〔日志〕节点更新: {list(chunk.keys())}")
        print("-" * 30)


# ═════════════════════════════════════════════
# 06. 控制哪些 token 流出去          【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════


def demo_message_metadata():
    pass


if __name__ == "__main__":
    # demo_messages()
    # demo_updates()
    # demo_values()
    # demo_custom()
    # demo_combined()
    demo_message_metadata()
