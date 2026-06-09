from operator import add

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from typing_extensions import TypedDict, Annotated


class State(TypedDict):
    foo: str
    bar: Annotated[list[str], add]


def node_a(state: State):
    return {"foo": "a", "bar": ["a"]}


def node_b(state: State):
    return {"foo": "b", "bar": ["b"]}


workflow = StateGraph(State)
workflow.add_node(node_a)
workflow.add_node(node_b)

workflow.add_edge(START, "node_a")
workflow.add_edge("node_a", "node_b")
workflow.add_edge("node_b", END)

# 模块级 graph：不带 checkpointer，供 LangGraph API 服务器加载
# LangGraph API 平台会自动处理持久化，不需要自定义 checkpointer
graph = workflow.compile()

if __name__ == "__main__":
    # 本地运行时使用 InMemorySaver 来演示持久化功能
    checkpointer = InMemorySaver()
    graph_with_checkpoint = workflow.compile(checkpointer=checkpointer)

    config: RunnableConfig = {"configurable": {"thread_id": "1"}}
    print(graph_with_checkpoint.invoke({"foo": "", "bar": []}, config=config))
