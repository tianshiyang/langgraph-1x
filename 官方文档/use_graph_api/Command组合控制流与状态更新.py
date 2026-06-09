import random
from typing import TypedDict, Literal

from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.types import Command


class State(TypedDict):
    foo: str


def node_a(state: State) -> Command[Literal["node_b", "node_c"]]:
    print("Called A")
    value = random.choice(["b", "c"])

    if value == "b":
        goto = "node_b"
    else:
        goto = "node_c"
    return Command(
        update={"foo": value},
        goto=goto,
    )


def node_b(state: State):
    print("Called B")
    return {"foo": state["foo"] + "b"}


def node_c(state: State):
    print("Called C")
    return {"foo": state["foo"] + "c"}


builder = StateGraph(State)

builder.add_node(node_a)
builder.add_node(node_b)
builder.add_node(node_c)

builder.add_edge(START, "node_a")

if __name__ == "__main__":
    graph = builder.compile()
    print(graph.invoke({"foo": ""}))
