"""
============================================================
LangGraph Map-Reduce 模式与 Send API 示例
============================================================

本示例演示了 LangGraph 中经典的 **Map-Reduce（映射-归约）** 并行执行模式。

核心思路：
  1. 【Map 阶段】  先由一个节点生成一组任务（如：多个主题），
                  然后通过 Send API 为每个任务 **动态创建并行的节点实例**。
  2. 【Reduce 阶段】所有并行实例的结果通过 Annotated[list[str], operator.add]
                  自动汇聚（reduce）到同一个列表中，再交给下游节点统一处理。

整体流程图：
  START → generate_topics → [generate_joke × N (并行)] → best_joke → END
           (生成主题列表)     (每个主题生成一个笑话)       (选出最佳笑话)
"""

import operator

from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict, Annotated


# ============================================================
# 一、定义状态（State）
# ============================================================
# OverallState 是整个图的共享状态。
# 关键点：jokes 字段使用了 Annotated[list[str], operator.add]，
#         这意味着每次有节点返回 {"jokes": [xxx]} 时，
#         新的列表会自动 **追加（reduce）** 到已有列表中，而不是覆盖。
#         这是 Map-Reduce 模式的核心——多个并行节点各自产出结果，
#         然后自动汇总到同一个列表中。
class OverallState(TypedDict):
    topic: str  # 用户输入的主题（如 "animals"）
    subjects: list[str]  # generate_topics 节点产出的子主题列表
    jokes: Annotated[list[str], operator.add]  # 所有并行节点产出的笑话（自动聚合）
    best_selected_joke: str  # 最终选出的最佳笑话对应的主题


# ============================================================
# 二、定义节点函数
# ============================================================


def generate_topics(state: OverallState):
    """
    【Map 阶段 · 第一步：生成子主题列表】
    根据用户输入的 topic，生成一组子主题。
    在真实场景中，这里通常会调用 LLM 来动态生成主题。
    本例为了简化，直接返回硬编码的列表。
    """
    return {"subjects": ["lions", "elephants", "penguins"]}


def generate_joke(state: OverallState):
    """
    【Map 阶段 · 第二步：为每个子主题生成笑话】
    注意：这个函数会被 Send API 为每个 subject 各调用一次（并行执行）。
    每次调用时 state 中只包含当前这一个 subject 的数据。
    返回的 {"jokes": [...]} 会通过 operator.add 自动追加到总列表中。
    """
    joke_map = {
        "lions": "为什么狮子不喜欢快餐？因为它们根本追不上！",
        "elephants": "为什么大象不用电脑？因为它们怕鼠标（mouse）！",
        "penguins": "为什么企鹅不喜欢在派对上和陌生人说话？因为它们觉得破冰太难了。",
    }
    return {"jokes": [joke_map[state["subject"]]]}


def continue_to_jokes(state: OverallState):
    """
    【Map 阶段 · 路由函数：将子主题列表分发给并行节点】

    这里是 Send API 的核心使用场景：
    - 遍历 state["subjects"] 列表中的每个子主题
    - 为每个子主题创建一个 Send("generate_joke", {"subject": s}) 对象
    - LangGraph 会为每个 Send 对象创建一个独立的 "generate_joke" 节点实例
    - 这些实例会 **并行执行**，各自处理自己的 subject

    返回值是一个 Send 对象列表，LangGraph 会自动处理并行调度。
    """
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]


def best_joke(state: OverallState):
    """
    【Reduce 阶段：从所有笑话中选出最佳的】
    此时 state["jokes"] 已经包含了所有并行节点产出的笑话（通过 operator.add 自动聚合）。
    在真实场景中，这里通常会调用 LLM 来评判哪个笑话最好。
    本例直接返回硬编码的结果。
    """
    return {"best_selected_joke": "penguins"}


# ============================================================
# 三、构建图（Graph）
# ============================================================
builder = StateGraph(OverallState)

# 添加节点
builder.add_node("generate_topics", generate_topics)
builder.add_node("generate_joke", generate_joke)
builder.add_node("best_joke", best_joke)

# 添加边
builder.add_edge(START, "generate_topics")

# ----------------------------------------------------------
# 重点讲解：add_conditional_edges 的三个参数
# ----------------------------------------------------------
# builder.add_conditional_edges(
#     source="generate_topics",     # 参数1：源节点名称，条件边从这个节点出发
#     path=continue_to_jokes,        # 参数2：路由函数，返回 Send 对象列表（或目标节点名）
#     path_map=["generate_joke"]     # 参数3：可能的输出目标节点列表（用于图结构声明）
# )
#
# 参数3（path_map）详解：
#   - 类型：list[str] 或 dict[str, str]
#   - 作用：**声明性地告诉 LangGraph 图结构**，条件边的所有可能目标节点是什么。
#   - 为什么需要它？
#     1. 【图结构可视化】：LangGraph 需要提前知道边的连接关系，才能正确绘制流程图
#        （如 print_ascii() 或 LangGraph Studio 中的可视化）。
#     2. 【静态类型检查】：在某些场景下，LangGraph 会验证路由函数返回的目标
#        是否都在 path_map 声明的范围内。
#     3. 【可选但推荐】：如果路由函数只返回字符串节点名（如 return "node_a"），
#        LangGraph 可以自动推断目标，这时参数3可以省略。
#        但当路由函数返回 **Send 对象** 时，由于 Send 的目标是动态的，
#        LangGraph 无法自动推断，因此 **必须** 通过参数3显式声明可能的目标节点。
#   - 什么时候用 list，什么时候用 dict？
#     · list[str]：当路由函数直接返回节点名称字符串时
#       例：["node_a", "node_b"] 表示可能跳转到 node_a 或 node_b
#     · dict[str, str]：当路由函数返回的键名与实际节点名不同时，做映射
#       例：{"a": "node_a", "b": "node_b"} 表示路由函数返回 "a" 时实际跳转到 "node_a"
#
# 在本例中：
#   - continue_to_jokes 返回 Send("generate_joke", ...) 对象列表
#   - Send 的目标是 "generate_joke"，所以 path_map 写 ["generate_joke"]
#   - 这告诉 LangGraph：这个条件边的所有分支都会指向 generate_joke 节点
#
builder.add_conditional_edges("generate_topics", continue_to_jokes, ["generate_joke"])

# 所有并行的 generate_joke 实例完成后，汇聚到 best_joke 节点
# 注意：LangGraph 会自动等待所有 Send 创建的并行实例全部完成后，
#       才会执行下一条边（即 best_joke 节点）。这就是 Reduce 的"等待"机制。
builder.add_edge("generate_joke", "best_joke")
builder.add_edge("best_joke", END)


# ============================================================
# 四、运行图
# ============================================================
if __name__ == "__main__":
    # 编译图
    graph = builder.compile()

    # 打印图的 ASCII 结构
    print("=" * 60)
    print("图的执行结构（ASCII）：")
    print("=" * 60)
    graph.get_graph().print_ascii()

    # 以流式方式运行图，输入主题为 "animals"
    print("\n" + "=" * 60)
    print("开始执行 Map-Reduce 流程，输入主题：animals")
    print("=" * 60)

    for step in graph.stream({"topic": "animals"}):
        # step 是一个字典，key 为节点名，value 为该节点的输出
        for node_name, output in step.items():
            if node_name == "generate_topics":
                print(f"\n📌 [生成子主题] 节点输出：{output}")
            elif node_name == "generate_joke":
                print(f"  😂 [生成笑话（并行）] 节点输出：{output}")
            elif node_name == "best_joke":
                print(f"\n🏆 [选出最佳笑话] 节点输出：{output}")

    print("\n✅ Map-Reduce 流程执行完毕！")


# ============================================================
# 五、扩展讲解：什么时候使用 Send API？
# ============================================================
#
# Send API 是 LangGraph 实现 **动态并行（dynamic fan-out）** 的核心机制。
# 它适用于以下场景：
#
# 【场景1：Map-Reduce 并行处理】（本示例）
#   - 一个节点产生一组数据（如主题列表、文件列表、URL 列表）
#   - 需要对每个数据项执行相同的处理逻辑（如生成笑话、抓取网页、翻译文本）
#   - 最后将所有结果汇总
#   → 使用 Send 为每个数据项创建并行节点实例
#
# 【场景2：运行时才能确定并行数量】
#   - 并行的数量在编译时未知，只有在运行时由上游节点的输出决定
#   - 例如：用户输入一篇文章，LLM 提取出 N 个关键问题，N 是动态的
#   → 用 Send 动态创建 N 个并行节点，无需预先定义固定数量的节点
#
# 【场景3：批处理任务】
#   - 需要处理一批数据（如批量翻译、批量摘要、批量嵌入）
#   - 每个数据项的处理是独立的，可以并行执行
#   → Send + operator.add 实现自动分批 + 自动聚合
#
# 【场景4：多视角分析】
#   - 对同一份数据，从不同角度/维度进行分析
#   - 例如：从安全性、性能、可维护性三个维度并行审查代码
#   → 可以在路由函数中硬编码多个 Send，每个对应不同的分析维度
#
# 【什么时候不用 Send？】
#   1. 固定分支数量 → 直接用 add_conditional_edges + 返回字符串即可
#   2. 串行流程 → 用 add_edge 连接节点
#   3. 每次只走一条路径（不是并行） → 普通条件边就够了
#
# 【Send vs 普通条件边的区别】
#   普通条件边：路由函数返回一个字符串（节点名），走其中一条路径
#   Send 条件边：路由函数返回 Send 对象列表，**同时走多条路径（并行）**
#   Send 最强大的地方在于：并行数量是运行时动态决定的
#
# 【重要注意事项】
#   1. 使用 Send 时，目标节点（如 generate_joke）接收到的 state
#      不是完整的 OverallState，而是 Send 第二个参数传入的字典。
#      在本例中，每个 generate_joke 实例收到的 state 只包含 {"subject": "lions"}
#      而不是完整的 OverallState。
#      但返回值仍然会按 OverallState 的 reducer 规则进行合并。
#
#   2. 必须通过 add_conditional_edges 的第三个参数（path_map）
#      声明 Send 可能指向的目标节点，否则图结构无法正确可视化。
#
#   3. 所有并行实例完成后，LangGraph 才会执行下游节点（Reduce 的汇聚机制）。
#      这个"等待所有"是自动的，无需额外配置。
