from typing import TypedDict

from langgraph.constants import START
from langgraph.graph import StateGraph


# ==============================================================================
# 【私有状态（Private State）】
#
# 核心概念：节点之间可以通过"自定义输入/输出类型"来传递私有数据，
# 这些私有数据只对指定节点可见，其他节点完全看不到。
#
# ┌──────────────────────────────────────────────────────────────────────┐
# │                        原理：TypedDict 类型过滤                      │
# │                                                                      │
# │  LangGraph 根据每个节点函数签名中的 TypedDict 类型注解来过滤数据：      │
# │                                                                      │
# │  def node(state: 输入类型) -> 输出类型:                               │
# │                  ^^^^                   ^^^^                          │
# │                  │                      └── 返回值中声明的字段                       │
# │                  │                          会被合并到运行时状态池中                   │
# │                  └── LangGraph 从状态池中只提取该类型中声明的字段传给节点            │
# │                                                                      │
# │  运行时状态池（实际存储了所有字段）：                                    │
# │    {a: "...", private_data: "..."}                                    │
# │              │                                                        │
# │     ┌────────┼────────┐                                              │
# │     ▼        ▼        ▼                                              │
# │   node_1   node_2   node_3                                            │
# │   输入类型:  输入类型:  输入类型:                                        │
# │   OverallState  Node2Input  OverallState                              │
# │    只有 a    只有 private   只有 a                                     │
# │     │        _data        │                                           │
# │     ▼        ▼           ▼                                            │
# │   看到 a    看到 private  看到 a                                       │
# │   看不到    _data       看不到                                         │
# │   private   看不到 a   private                                         │
# │   _data               _data                                           │
# │                                                                      │
# │  关键：没有任何特殊关键字或装饰器，纯粹靠 TypedDict 的字段声明           │
# │       来控制每个节点能看到哪些数据。                                    │
# │       你的函数参数写了什么类型，LangGraph 就只给你传什么字段。            │
# └──────────────────────────────────────────────────────────────────────┘
#
# 本例流程：
#   node_1 ──(private_data)──► node_2 ──(a)──► node_3
#
#   - node_1 产出 private_data，只能被 node_2 看到
#   - node_3 完全看不到 private_data，它只能看到公共状态字段 a
# ==============================================================================


# 图的整体状态（公共状态，所有使用 OverallState 作为输入类型的节点都能看到）
class OverallState(TypedDict):
    a: str


# node_1 的输出类型：包含一个私有字段 private_data
# 这个字段不在 OverallState 中，所以只有输入类型声明了该字段的节点才能看到
class Node1Output(TypedDict):
    private_data: str


# node_1：输入 OverallState（能看到 a），输出 Node1Output（产出 private_data）
def node_1(state: OverallState) -> Node1Output:
    output = {"private_data": "set by node_1"}
    print(f"Entered node `node_1`:\n\tInput: {state}.\n\tReturned: {output}")
    return output


# node_2 的输入类型：只声明了 private_data
# 这意味着 node_2 只能看到 private_data，连公共字段 a 都看不到
class Node2Input(TypedDict):
    private_data: str


# node_2：输入 Node2Input（只能看到 private_data），输出 OverallState（写回公共状态 a）
def node_2(state: Node2Input) -> OverallState:
    output = {"a": "set by node_2"}
    print(f"Entered node `node_2`:\n\tInput: {state}.\n\tReturned: {output}")
    return output


# node_3：输入和输出都是 OverallState，只能看到公共字段 a
# 注意：node_3 完全看不到 private_data，因为它不存在于 OverallState 中
def node_3(state: OverallState) -> OverallState:
    output = {"a": "set by node_3"}
    print(f"Entered node `node_3`:\n\tInput: {state}.\n\tReturned: {output}")
    return output


# ==============================================================================
# 【add_sequence 语法糖】
#
# add_sequence([node_1, node_2, node_3]) 等价于依次调用：
#   builder.add_node("node_1", node_1)
#   builder.add_node("node_2", node_2)
#   builder.add_node("node_3", node_3)
#   builder.add_edge("node_1", "node_2")
#   builder.add_edge("node_2", "node_3")
#
# 它会自动：
#   1. 用函数名作为节点名称注册每个节点
#   2. 按列表顺序自动在相邻节点之间添加边（线性流水线）
#
# 适用场景：多个节点按固定顺序依次执行，没有条件分支。
# 如果需要条件路由（if/else 分支），则需要用 add_conditional_edges 手动控制。
# ==============================================================================
builder = StateGraph(OverallState).add_sequence([node_1, node_2, node_3])
builder.add_edge(START, "node_1")
graph = builder.compile()

# 调用图，初始状态只有公共字段 a
# 执行流程：
#   1. node_1 收到 {"a": "set at start"}           ← 只能看到 a
#   2. node_2 收到 {"private_data": "set by node_1"} ← 只能看到 private_data
#   3. node_3 收到 {"a": "set by node_2"}            ← private_data 已被过滤，只能看到 a
response = graph.invoke(
    {
        "a": "set at start",
    }
)

print()
print(f"Output of graph invocation: {response}")
