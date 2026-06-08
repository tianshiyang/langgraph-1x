from typing import TypedDict

from langgraph.constants import START, END
from langgraph.graph import StateGraph


# 给input定义schema
class InputSchema(TypedDict):
    question: str


# 给output定义schema
class OutputSchema(TypedDict):
    answer: str


# 定义整体 schema，将输入和输出结合起来。
class OverallState(InputSchema, OutputSchema):
    pass


# 定义处理输入并生成答案的节点
def answer_node(state: InputSchema):
    return {"answer": "bye", "question": state["question"]}


builder = StateGraph(OverallState, input_schema=InputSchema, output_schema=OutputSchema)
builder.add_node("answer_node", answer_node)

builder.add_edge(START, "answer_node")
builder.add_edge("answer_node", END)

graph = builder.compile()

result = graph.invoke({"question": "这是一个问题"})
print(result)
