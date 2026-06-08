import asyncio
from typing import TypedDict

from langgraph.constants import START, END
from langgraph.errors import NodeTimeoutError
from langgraph.graph import StateGraph
class State(TypedDict):
    value: str


async def call_model(state: State) -> State:
    await asyncio.sleep(2)
    return {"value": "done"}


builder = StateGraph(State)
builder.add_node("model", call_model, timeout=1.0)
builder.add_edge(START, "model")
builder.add_edge("model", END)

graph = builder.compile()

if __name__ == "__main__":
    try:
        asyncio.run(graph.ainvoke({"value": "start"}))
    except NodeTimeoutError:
        print("node timeout")
