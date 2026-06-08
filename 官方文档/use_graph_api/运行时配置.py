from typing import TypedDict

from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime


# ==============================================================================
# 【运行时配置（Runtime Context）】
#
# 核心概念：通过 context_schema 在调用图时传入额外的配置参数，
# 这些参数不存储在 State 中，而是通过 Runtime 对象在节点中访问。
#
# ┌──────────────────────────────────────────────────────────────┐
# │                State vs Runtime Context 区别                  │
# │                                                              │
# │  State（状态）：                                              │
# │    - 图内部的数据流，在节点之间传递和累加                       │
# │    - 每次 invoke 可以传入初始值，节点返回值会更新状态           │
# │    - 适合存储"业务数据"（如消息列表、计数器等）                 │
# │                                                              │
# │  Runtime Context（运行时上下文）：                             │
# │    - 从外部传入的只读配置，不会在节点之间被修改                 │
# │    - 整个执行过程中保持不变                                    │
# │    - 适合存储"控制参数"（如模型选择、用户偏好、模式开关等）      │
# │                                                              │
# │  类比：                                                       │
# │    State = 员工之间传递的工作文档（会被修改）                   │
# │    Context = 公司下发的规章制度（只读，全员可见）               │
# └──────────────────────────────────────────────────────────────┘
#
# 使用步骤：
#   1. 用 TypedDict 定义 ContextSchema（声明有哪些配置参数）
#   2. 创建 StateGraph 时传入 context_schema=ContextSchema
#   3. 节点函数中通过 runtime: Runtime[ContextSchema] 参数访问配置
#   4. 调用 graph.invoke() 时通过 context={"key": "value"} 传入配置
# ==============================================================================


# 第 1 步：定义运行时配置的模式（有哪些配置参数）
class ContextSchema(TypedDict):
    my_runtime_value: str


# 定义图的状态（节点之间传递的业务数据）
class State(TypedDict):
    my_state_value: str


# 第 3 步：节点函数通过 runtime 参数访问运行时配置
# 注意两个参数：
#   - state: 当前图的状态数据（可读写）
#   - runtime: 运行时上下文（只读配置），通过 runtime.context 访问
def node(state: State, runtime: Runtime[ContextSchema]):
    # 根据 runtime context 中的配置值决定不同的行为
    if runtime.context["my_runtime_value"] == "a":
        return {"my_state_value": 1}
    elif runtime.context["my_runtime_value"] == "b":
        return {"my_state_value": 2}
    else:
        raise ValueError("Unknown values.")


# 第 2 步：创建 StateGraph 时指定 context_schema
# 这样 LangGraph 就知道节点可以通过 Runtime 访问哪些配置字段
builder = StateGraph(State, context_schema=ContextSchema)
builder.add_node(node)
builder.add_edge(START, "node")
builder.add_edge("node", END)

graph = builder.compile()

# 第 4 步：调用时通过 context 参数传入运行时配置
# 同一个图，不同的 context 配置可以产生不同的行为
print(graph.invoke({}, context={"my_runtime_value": "a"}))
# 输出: {'my_state_value': 1}  ← context 为 "a" 时走第一个分支

print(graph.invoke({}, context={"my_runtime_value": "b"}))
# 输出: {'my_state_value': 2}  ← context 为 "b" 时走第二个分支
