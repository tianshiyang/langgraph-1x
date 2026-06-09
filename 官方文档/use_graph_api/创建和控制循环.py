"""
LangGraph 创建和控制循环 —— 条件边（Conditional Edges）实现循环控制

核心知识点：
1. add_conditional_edges(source, path_func, path_map=None)
   - source:    起始节点名称（字符串）
   - path_func: 路由函数，接收 state 作为参数，返回目标节点名称（字符串或列表）
   - path_map:  可选，dict 或 list，用于映射函数返回值到实际节点名
                · dict: {函数返回值: 目标节点名}，适合函数返回非字符串值（如数字、枚举）
                · list: 显式声明所有可能的目标节点，用于图结构验证

2. 条件边的路由函数决定了循环的终止条件：
   - 返回具体节点名 → 继续执行该节点
   - 返回 END       → 结束整个图执行

3. 防止无限循环的手段：
   - recursion_limit 参数：限制图的最大步数（默认 25），超出抛出 GraphRecursionError
   - 在路由函数中设置终止条件：如本例中 len(state["aggregate"]) >= 7 时返回 END
"""

import operator

from langgraph.constants import END, START
from langgraph.errors import GraphRecursionError
from langgraph.graph import StateGraph
from typing_extensions import TypedDict, Annotated, Literal


# 状态定义：aggregate 使用 operator.add 作为 reducer
# 意味着每次节点返回新的列表时，会自动与现有列表合并（而非覆盖）
# 例如：原状态 ["A"] + 节点返回 ["B"] → 新状态 ["A", "B"]
class State(TypedDict):
    aggregate: Annotated[list, operator.add]


# 节点A：向 aggregate 追加 "A"
def a(state: State):
    print(f"节点A看到{state['aggregate']}")
    return {"aggregate": ["A"]}


# 节点B：向 aggregate 追加 "B"
def b(state: State):
    print(f"节点B看到{state['aggregate']}")
    return {"aggregate": ["B"]}


# 路由函数：根据当前状态决定下一步走向
# 返回类型用 Literal 声明所有可能的目标，便于类型检查和图结构验证
# - 当 aggregate 长度 < 7 → 走节点 "b"（继续循环）
# - 当 aggregate 长度 >= 7 → 走 END（结束执行）
def route(state: State) -> Literal["b", END]:
    if len(state["aggregate"]) < 7:
        return "b"
    else:
        return END


# 构建图
builder = StateGraph(State)
builder.add_node(a)
builder.add_node(b)

# 边的定义，形成如下循环结构：
#   START → a → [条件判断] → b → a → [条件判断] → b → ... → END
#                 ↓                              ↓
#               (继续)                        (aggregate >= 7 则结束)
builder.add_edge(START, "a")  # 入口边：START → a
builder.add_conditional_edges("a", route)  # 条件边：a 根据 route 函数决定去 b 还是 END
# 注意：此处省略了第三个参数 path_map，
# 因为 route 直接返回节点名字符串，LangGraph 能自动识别
builder.add_edge("b", "a")  # 普通边：b → a（形成循环）


if __name__ == "__main__":
    graph = builder.compile()
    graph.get_graph().print_ascii()

    #################################
    # 普通的控制循环
    #################################
    # 路由函数 route 会在 aggregate 长度达到 7 时自动终止
    # 执行路径：a → b → a → b → a → b → a → END
    # 最终结果：{"aggregate": ["A", "B", "A", "B", "A", "B", "A"]}（共 7 个元素）
    # result = graph.invoke({"aggregate": []})

    #################################
    # 增加递归限制
    #################################
    # recursion_limit 限制图执行的最大步数（每经过一个节点算一步）
    # 默认值为 25，这里设为 4，意味着最多经过 4 个节点
    # 由于 a → b → a → b 需要 4 步，第 5 步时会触发 GraphRecursionError
    try:
        result = graph.invoke({"aggregate": []}, {"recursion_limit": 4})
        print(result)
    except GraphRecursionError:
        print("递归出错")
