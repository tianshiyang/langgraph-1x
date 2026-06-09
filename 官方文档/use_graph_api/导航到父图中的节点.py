"""
LangGraph 导航到父图中的节点 —— 使用 Command 实现跨图路由

核心知识点：
1. Command 类：LangGraph 中用于同时实现"状态更新"和"路由控制"的对象
   - Command(update={"key": value}, goto="目标节点", graph=Command.PARENT)
   - update: 状态更新（等同于普通节点返回的 dict）
   - goto:  指定下一步要去的节点名称
   - graph: 指定路由的目标图层级
     · Command.PARENT → 跳转到父图中的节点（跨图导航）
     · 不设置         → 在当前图内路由

2. 跨图导航的方向性：
   - 子图 → 父图节点：✅ 支持，使用 Command(graph=Command.PARENT, goto="父图节点名")
   - 父图 → 子图内部节点：❌ 不支持，父图只能将子图视为一个整体节点

3. 典型场景：
   子图作为父图的一个节点，子图内部根据逻辑决定退出子图后，
   直接跳转到父图中的某个特定节点（跳过父图中子图之后的默认边）
"""

import operator
import random
from typing import TypedDict, Annotated

from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.types import Command


# 状态定义：foo 使用 operator.add 作为 reducer
# 新值会自动追加到现有字符串后面，而非覆盖
class State(TypedDict):
    foo: Annotated[str, operator.add]


# ============================================================
# 子图定义
# ============================================================
# node_a 是子图内部的节点，它会根据随机值决定跳转到父图中的哪个节点
# 关键：使用 Command(graph=Command.PARENT) 实现从子图到父图的跨图路由
def node_a(state: State):
    print("Called A")
    value = random.choice(["a", "b"])
    if value == "a":
        goto = "node_b"  # 跳转到父图中的 node_b
    else:
        goto = "node_c"  # 跳转到父图中的 node_c

    # Command 同时完成两件事：
    # 1. update={"foo": value} → 更新状态（将 value 追加到 foo，因为有 reducer）
    # 2. goto=goto             → 指定目标节点（node_b 或 node_c）
    # 3. graph=Command.PARENT  → 告诉 LangGraph 目标节点在父图中，不是当前子图
    #    如果不设置 graph=Command.PARENT，LangGraph 会在子图内部寻找目标节点
    return Command(update={"foo": value}, goto=goto, graph=Command.PARENT)


# 子图结构很简单：START → node_a
# node_a 执行后会通过 Command 跳出到父图
subgraph = StateGraph(State).add_node(node_a).add_edge(START, "node_a").compile()


# ============================================================
# 父图定义
# ============================================================

def node_b(state: State):
    print("Called B")
    # 因为 foo 使用了 operator.add reducer，直接返回新值即可
    # reducer 会自动将 "b" 追加到现有的 foo 字符串后面
    return {"foo": "b"}


def node_c(state: State):
    print("Called C")
    return {"foo": "c"}


# 父图结构：
#   START → subgraph → [由子图内部 Command 决定] → node_b 或 node_c
#
# 执行流程：
#   1. 从 START 进入 subgraph（子图作为一个整体节点）
#   2. 子图内部执行 node_a，随机产生 "a" 或 "b"
#   3. node_a 通过 Command(graph=Command.PARENT, goto=...) 跳出到父图
#      - 如果 value="a" → 跳到父图的 node_b
#      - 如果 value="b" → 跳到父图的 node_c
#   4. node_b 或 node_c 执行完毕，图结束
#
# 最终结果示例：
#   {"foo": "ab"}（node_a 追加 "a"，node_b 追加 "b"）
#   {"foo": "bc"}（node_a 追加 "b"，node_c 追加 "c"）
builder = StateGraph(State)
builder.add_edge(START, "subgraph")       # 入口边：START → subgraph（子图节点）
builder.add_node("subgraph", subgraph)    # 将子图注册为父图的一个节点
builder.add_node(node_b)                  # 父图节点：node_b
builder.add_node(node_c)                  # 父图节点：node_c

graph = builder.compile()

if __name__ == "__main__":
    graph.get_graph().print_ascii()
    result = graph.invoke({"foo": ""})
    print(result)
