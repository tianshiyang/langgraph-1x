"""
LangGraph 创建分支 — 完整示例
==============================

本文件演示 LangGraph 中三种分支模式：

  1. 并行分支（Fan-out / Fan-in）
     从同一个节点出发，同时执行多个下游节点，再汇聚到一个节点。
     只需对同一个源节点 add_edge 到多个目标即可，无需额外配置。

  2. 延迟执行（defer）
     标记 defer=True 的节点会"按兵不动"，等图中所有其他节点都执行完毕后，
     才在最后一步执行。适合做最终汇总、清理等收尾工作。

  3. 条件分支（add_conditional_edges）
     根据状态动态决定下一个要执行的节点，类似 if/else 或 switch 语句。

此外，LangGraph 还支持 Send 动态扇出（map-reduce），本文件未展示但会在注释中说明。

核心概念 — 超步（Superstep）：
  LangGraph 的执行是按"超步"推进的。每个超步中，所有被触发的节点并行执行。
  一个超步中所有节点完成后，它们的输出被合并到状态中，然后下一个超步开始。
  并行分支中的节点就在同一个超步中执行。
"""

import operator
from typing import Annotated, Literal

from langgraph.constants import START, END
from langgraph.graph import StateGraph
from typing_extensions import TypedDict


# ======================================================================
# 状态定义
# ======================================================================
# aggregate 使用 Annotated[list, operator.add] 作为 reducer：
#   每个节点返回 {"aggregate": ["X"]}，多个节点的返回值会通过 operator.add 合并。
#   例如节点 A 返回 ["A"]，节点 B 返回 ["B"]，最终 aggregate = ["A", "B"]。
#   这在并行分支中尤其重要——多个并行节点的输出会自动合并。
class State(TypedDict):
    aggregate: Annotated[list, operator.add]


# ======================================================================
# 节点定义
# ======================================================================

def a(state: State) -> State:
    print(f"添加A到 {state['aggregate']}")
    return {"aggregate": ["A"]}


def b(state: State) -> State:
    print(f"添加B到{state['aggregate']}")
    return {"aggregate": ["B"]}


def c(state: State) -> State:
    print(f"添加c到{state['aggregate']}")
    return {"aggregate": ["C"]}


def d(state: State) -> State:
    print(f"添加D到{state['aggregate']}")
    return {"aggregate": ["D"]}


def b_2(state: State):
    print(f'Adding "B_2" to {state["aggregate"]}')
    return {"aggregate": ["B_2"]}


builder = StateGraph(State)
builder.add_node(a)
builder.add_node(b)
builder.add_node(c)
builder.add_node(d)

# ==================== defer=True — 延迟执行 ====================
#
# defer 参数的工作原理：
#
#   普通节点（defer=False）：
#     分支通道使用 EphemeralValue —— 上游节点一写入就立即触发下游节点。
#
#   延迟节点（defer=True）：
#     分支通道使用 LastValueAfterFinish —— 即使上游写入了值，节点也不会触发。
#     只有当 runner 检测到"没有任何更多节点可以被触发"时，会对所有通道调用
#     finish()，此时延迟节点的通道才变为可用，节点才执行。
#
# 效果：defer 节点相当于一个"终结器"（finalizer），无论图走了哪条分支，
#       它都会在所有其他节点执行完毕后，作为最后一步运行。
#
# 适用场景：
#   - 最终汇总：收集各分支的结果做统一处理
#   - 清理工作：释放资源、记录日志等
#   - 后置校验：所有分支完成后做一次整体检查
#
# 本例中：b -> b_2 -> d，b_2 是延迟节点。
# 当 a 同时触发 b 和 c 时，c 可能先完成，但 b_2 不会立即执行。
# 它会等到 b 完成（因为 b_2 的上游是 b），但即使 b 完成了，
# b_2 也会等到所有非延迟节点（包括 c、d）相关的超步结算后再执行。
builder.add_node(b_2, defer=True)


# ======================================================================
# 模式 1：并行分支（Fan-out / Fan-in）
# ======================================================================
# 图结构：
#       START → a → b → d → END
#                ↘ c ↗
#
# 当一个节点有多个出边时（a → b 和 a → c），b 和 c 会在同一个超步中并行执行。
# d 是 b 和 c 的汇聚节点（fan-in），只有当 b 和 c 都完成后 d 才会被触发。
#
# 底层机制：
#   - Fan-out：a 完成后，同时写入 branch:to:b 和 branch:to:c 两个通道
#   - Fan-in：创建 join:b+c:d 通道（NamedBarrierValue），
#             b 和 c 各写入自己的名字，只有两者都写入后 d 才触发
#
# aggregate 的变化过程：
#   [] → a → ["A"] → b 和 c 并行 → ["A", "B", "C"] → d → ["A", "B", "C", "D"]
# （b 和 c 的并行执行顺序不确定，但 operator.add 会保证合并）

# builder.add_edge(START, "a")
# builder.add_edge("a", "b")
# builder.add_edge("a", "c")
# builder.add_edge("b", "d")
# builder.add_edge("c", "d")
# builder.add_edge("d", END)


# ======================================================================
# 模式 2：延迟执行（defer=True）
# ======================================================================
# 图结构：
#       START → a → b → b_2(defer) → d → END
#                ↘ c ──────────────→ d ↗
#
# 与模式 1 相比，b → d 之间多了一个 b_2（延迟节点）。
# b_2 标记了 defer=True，所以它的行为是：
#   - b 完成后，b_2 不会立即执行
#   - 等到图中所有非延迟通道都稳定（没有更多节点可触发）时
#   - finish() 被调用，b_2 才执行
#
# aggregate 的变化过程：
#   [] → a → ["A"] → b 和 c 并行 → ["A", "B", "C"]
#   → finish() → b_2 → ["A", "B", "C", "B_2"] → d → ["A", "B", "C", "B_2", "D"]
builder.add_edge(START, "a")
builder.add_edge("a", "b")
builder.add_edge("a", "c")
builder.add_edge("b", "b_2")
builder.add_edge("b_2", "d")
builder.add_edge("c", "d")
builder.add_edge("d", END)

graph = builder.compile()

# print(graph.get_graph().draw_ascii())


# ======================================================================
# 模式 3：条件分支（add_conditional_edges）
# ======================================================================
#
# add_conditional_edges(source, path, path_map=None) 参数说明：
#
#   source:    源节点名称（从哪个节点的出口触发条件判断）
#   path:      路由函数，接收当前状态，返回目标节点名（或列表）
#              - 可以是同步函数、异步函数、或 Runnable
#              - 返回值可以是单个节点名、节点名列表、或 Send 对象
#   path_map:  可选的路由映射表，有三种形式：
#              - None（默认）：path 返回值直接作为节点名
#                如果 path 有 Literal 返回类型注解，会自动提取为映射表
#              - dict：path 返回的 key 映射到实际节点名
#                例：{"yes": "node_b", "no": "node_c"}
#              - list：等价于 {name: name for name in list}
#
# 调用方式示例：
#
#   方式 1 — 返回节点名（最常见）：
#     def route(state) -> Literal["b", "c"]:
#         return state["next"]
#     graph.add_conditional_edges("a", route)
#
#   方式 2 — 使用 path_map 字典：
#     def route(state) -> str:
#         return "yes" if state["ok"] else "no"
#     graph.add_conditional_edges("a", route, {"yes": "node_b", "no": "node_c"})
#
#   方式 3 — 使用 path_map 列表：
#     graph.add_conditional_edges("a", route, ["node_b", "node_c"])
#
#   方式 4 — 返回 Send 对象实现动态扇出（map-reduce）：
#     def continue_to_nodes(state):
#         return [Send("generate", {"topic": t}) for t in state["topics"]]
#     graph.add_conditional_edges(START, continue_to_nodes)
#
#     Send(node, arg) 的参数：
#       - node: 目标节点名
#       - arg:  自定义输入状态（不使用图的共享状态，而是传入这个自定义 arg）
#       - timeout: 可选的超时策略
#
#     Send 的底层流程：
#       1. path 函数返回 N 个 Send 对象
#       2. 所有 Send 被写入 TASKS 通道（Topic 类型，accumulate=False）
#       3. 下一个超步中，每个 Send 生成一个 PUSH 任务
#       4. N 个 PUSH 任务并行执行，各自使用 Send.arg 作为输入
#       5. 所有任务的输出通过 reducer 合并回共享状态
#
#     这就是 map-reduce 模式：动态决定并行数量和每个任务的输入

class StateWhich(TypedDict):
    aggregate: Annotated[list, operator.add]
    # which 字段决定走哪条分支，类型是 Literal，限定只能取这两个值
    # add_conditional_edges 会自动从 Literal 注解中提取合法的目标节点名
    which: Literal["b_w", "c_w"]


def a_w(state: StateWhich) -> StateWhich:
    print(f"添加A到{state['aggregate']}")
    # 同时设置 aggregate 和 which，which 的值决定了后续走哪条分支
    return {"aggregate": ["A"], "which": "c_w"}


def b_w(state: StateWhich):
    print(f"添加B到{state['aggregate']}")
    return {"aggregate": ["B"]}


def c_w(state: StateWhich):
    print(f"添加C到{state['aggregate']}")
    return {"aggregate": ["C"]}


def conditional_edge(state: StateWhich) -> Literal["b_w", "c_w"]:
    """
    条件路由函数。

    读取 state["which"] 的值，返回下一个要执行的节点名。
    返回类型声明为 Literal["b_w", "c_w"]，LangGraph 会自动提取
    这个注解作为合法目标节点列表（等同于传入了 path_map）。
    """
    return state["which"]


builder_which = StateGraph(StateWhich)
builder_which.add_node("a_w", a_w)
builder_which.add_node("b_w", b_w)
builder_which.add_node("c_w", c_w)
builder_which.add_edge(START, "a_w")
builder_which.add_edge("b_w", END)
builder_which.add_edge("c_w", END)

# a_w 执行完后，调用 conditional_edge(state) 决定走 b_w 还是 c_w
# 因为 conditional_edge 的返回类型是 Literal["b_w", "c_w"]，
# LangGraph 自动识别合法目标，无需额外传 path_map
builder_which.add_conditional_edges("a_w", conditional_edge)

graph_which = builder_which.compile()

if __name__ == "__main__":
    # graph.invoke({"aggregate": []}, {"configurable": {"thread_id": "foo"}})
    # 条件分支：a_w 返回 which="c_w"，所以路由到 c_w 节点
    # aggregate 变化：[] → a_w → ["A"] → c_w → ["A", "C"]
    print(graph_which.invoke({"aggregate": []}))
