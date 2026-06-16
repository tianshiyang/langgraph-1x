"""
LangGraph 时间旅行 (Time Travel) — 完整教程
================================================

⭐️ 一句话理解：因为持久化（checkpointer）把图执行的【每一步】都拍了快照，
   你就能像看录像一样，「倒带」到任意一步——
     · 倒回去【原样重跑】后面的步骤            → Replay（重放）
     · 倒回去【改一改当时的状态】再往后跑一条新路 → Fork（分支/岔路）

⭐️ 它解决的是企业里非常真实的三类痛点：
   1) 排查：线上 Agent「为什么生成了这么离谱的结果」？倒回出错前一步，
      看当时的 state 到底长啥样，而不是靠猜。
   2) 重试 / 调参：前面有个很贵的步骤（调了大模型、查了一堆库），
      只想换个参数重跑【后半段】——Fork 一下，前面不动，省时省钱。
   3) 探索 / A-B：同一个起点，改不同的 topic / prompt，岔出好几条分支对比效果。

⭐️ 先认清它和「持久化.py」是【同一块地基】：
   时间旅行不是新功能，而是 checkpointer 存下的快照的「另一种用法」。
   没配 checkpointer = 没有录像 = 没法倒带。所以先吃透「持久化.py」再看这篇。

──────────────────────────────────────────────────────────────────
⭐️ 一张图看懂 Replay 与 Fork 的差别（这是全篇的核心）：

   正常执行存下的录像（每步一个 checkpoint）：
     START → [choose_topic] → [write_copy] → END
       c0        c1              c2          c3
                  ▲
                  └── 我想从这里（write_copy 之前）动手

   ┌── Replay 重放 ──────────────────────────────────────┐
   │  invoke(None, c1.config)                            │
   │  → 不动 choose_topic（结果已存），只【重跑 write_copy】 │
   │  → 适合：调试、节点重跑                                │
   └─────────────────────────────────────────────────────┘

   ┌── Fork 分支 ────────────────────────────────────────┐
   │  fork = update_state(c1.config, {改掉的状态})         │
   │  invoke(None, fork)                                  │
   │  → 基于 c1【新建一个分支 checkpoint】，带着改后的状态   │
   │  → 再从这条新路往后跑（write_copy 用新状态重算）        │
   │  → 适合：换参数重试、探索不同走向                       │
   └─────────────────────────────────────────────────────┘

⭐️ 全篇只有三个 API，记住就够：
   graph.get_state_history(config)  → 列出这条 thread 的所有历史快照（倒序）
   graph.get_state(config)          → 看当前（或某 checkpoint 的）单个快照
   graph.update_state(config, vals) → 基于某快照改状态、生成新分支（Fork 靠它）
   重放/继续都用：graph.invoke(None, 某个 checkpoint 的 config)

⭐️ 一个快照(StateSnapshot)身上你只需关心四样东西：
   .values  → 当时的完整状态        .next → 接下来【将要跑】哪个节点
   .config  → 定位它的坐标（含 checkpoint_id）   .metadata → step 等元信息

参考文档（本教程严格对照官网，并基于本机已装版本逐条实测）：
  - https://docs.langchain.com/oss/python/langgraph/use-time-travel
  （本项目 langgraph==1.2.4 / langchain==1.3.6 / Python 3.13，下列 API 全部实测可跑）

──────────────────────────────────────────────────────────────────
⭐️ 企业实战优先级图例：
  ⭐️⭐️⭐️ 企业核心：调试/重试 Agent 几乎必用
  ⭐️⭐️   企业常用：要懂的认知或某类场景
  ⭐️     了解即可：边角 / 高级

各小节速查（直接运行会从上到下依次演示）：
  01 三个核心 API + checkpoint 概念 ...... ⭐️⭐️⭐️  地基
  02 get_state_history：看执行轨迹 ........ ⭐️⭐️⭐️  找回溯点全靠它
  03 Replay 重放（从某点重跑后续） ........ ⭐️⭐️⭐️  调试主力
  04 Fork 分支（改状态走新路） ............ ⭐️⭐️⭐️  重试/调参主力
  05 「重放不是读缓存」的坑（会真重跑） .... ⭐️⭐️    副作用要警惕
  06 as_node：以某节点身份写入状态 ........ ⭐️⭐️    跳步/造初态
  07 时间旅行 + interrupt（回到过去重答） .. ⭐️⭐️    和人机交互联动
  08 子图的时间旅行 ...................... ⭐️       继承 vs 自带 checkpointer
──────────────────────────────────────────────────────────────────
"""

import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

# 加载根目录 .env（与其他教程统一）
load_dotenv(Path(__file__).parent.parent.parent / ".env")


# ═════════════════════════════════════════════════════════════
# 公共示例图：一个最小「内容生成」流水线
#   choose_topic（定卖点）→ write_copy（按卖点写文案）
# 真实项目里这两步可能是调 glm_model；为离线可跑写成确定性函数。
# ═════════════════════════════════════════════════════════════

class CopyState(TypedDict):
    topic: str
    copy: str


def choose_topic(state: CopyState):
    # 真实场景：可能让 LLM 头脑风暴一个卖点。这里写死成「袜子」。
    return {"topic": "袜子"}


def write_copy(state: CopyState):
    # 真实场景：glm_model 按 topic 生成文案。这里用 topic 拼一句。
    return {"copy": f"买它！关于「{state['topic']}」的超值文案~"}


def build_copy_graph():
    builder = StateGraph(CopyState)
    builder.add_node("choose_topic", choose_topic)
    builder.add_node("write_copy", write_copy)
    builder.add_edge(START, "choose_topic")
    builder.add_edge("choose_topic", "write_copy")
    builder.add_edge("write_copy", END)
    # ⭐️ 时间旅行的前提：必须有 checkpointer（开发用内存，生产用 Postgres）
    return builder.compile(checkpointer=InMemorySaver())


def new_config() -> RunnableConfig:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


# ═════════════════════════════════════════════════════════════
# 01 + 02. 核心 API & 看执行轨迹 get_state_history   【⭐️⭐️⭐️ 地基】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ get_state_history(config)：返回这条 thread 的【所有历史快照】，
#    顺序是【倒序】（最新的在最前面）。这是时间旅行的入口——
#    你先用它把「录像目录」列出来，找到想倒回的那一帧，拿到它的 .config。
#
# ⭐️ 怎么找回溯点？看每个快照的 .next（它表示「从这一帧继续，将要跑哪个节点」）：
#    .next == ('write_copy',)  → 这一帧正好停在 write_copy 之前，最适合从这里动手。
#    .next == ()               → 这是终点（跑完了），从这里重放是空操作。

def demo_history():
    """⭐️ 先跑一遍，再把整条执行轨迹打印出来，认识 checkpoint。"""
    graph = build_copy_graph()
    config = new_config()

    result = graph.invoke({"topic": "", "copy": ""}, config)
    print("正常执行结果：", result)

    print("\n执行轨迹（get_state_history，倒序，最新在最上）：")
    for snap in graph.get_state_history(config):
        ckpt = snap.config["configurable"]["checkpoint_id"]
        step = snap.metadata.get("step")  # 第几步（-1 是空初始帧）
        print(f"  step={step:>2} | next={str(snap.next):<18} "
              f"| values={snap.values} | ckpt=…{ckpt[-6:]}")

    # ⭐️ get_state(config)：不带 checkpoint_id 时，取的是【最新】那一帧
    print("\n当前（最新）快照：", dict(graph.get_state(config).values))


# ═════════════════════════════════════════════════════════════
# 03. Replay 重放：从某检查点【原样重跑】后续     【⭐️⭐️⭐️ 调试主力】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 做法两步：
#    1) 在历史里找到 .next == ('write_copy',) 的那一帧（write_copy 之前）
#    2) graph.invoke(None, 那一帧的 config)   ← 注意：输入传 None！
# ⭐️ 效果：choose_topic 不再跑（结果已存在那一帧里），只【重跑 write_copy 及之后】。
#    传 None 是关键信号——告诉图「别从头开始，从这个 checkpoint 接着跑」。

def demo_replay():
    """⭐️ 倒回 write_copy 之前，只重跑 write_copy。"""
    graph = build_copy_graph()
    config = new_config()
    graph.invoke({"topic": "", "copy": ""}, config)

    # 1) 找到 write_copy 之前的那一帧
    history = list(graph.get_state_history(config))
    before_write = next(s for s in history if s.next == ("write_copy",))
    print("回溯到的帧：next=", before_write.next, " values=", before_write.values)

    # 2) 传 None 从该 checkpoint 重放（choose_topic 不重跑，write_copy 重跑）
    replayed = graph.invoke(None, before_write.config)
    print("重放结果：", replayed)
    # topic 还是「袜子」（沿用存档），copy 是重新生成的


# ═════════════════════════════════════════════════════════════
# 04. Fork 分支：改掉过去的状态，岔出一条新路      【⭐️⭐️⭐️ 重试/调参主力】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 和重放只差一步：重放是「原样」往后跑；Fork 是先 update_state 改掉当时的状态，
#    再往后跑——于是后续节点会基于【新状态】重算，得到一条不一样的结果。
# ⭐️ update_state(config, 新值) 会基于那一帧【新建一个分支 checkpoint】，
#    并把这个新分支的 config 返回给你。注意它【不回滚】原历史，原来的录像还在。

def demo_fork():
    """⭐️ 倒回 write_copy 之前，把 topic 从「袜子」改成「机械键盘」，再往后跑。"""
    graph = build_copy_graph()
    config = new_config()
    graph.invoke({"topic": "", "copy": ""}, config)

    history = list(graph.get_state_history(config))
    before_write = next(s for s in history if s.next == ("write_copy",))

    # ⭐️ 关键一步：基于这一帧改状态 → 得到新分支的 config
    fork_config = graph.update_state(before_write.config, {"topic": "机械键盘"})

    # ⭐️ 从新分支继续（同样传 None），write_copy 会用「机械键盘」重写
    forked = graph.invoke(None, fork_config)
    print("Fork 后结果：", forked)  # topic=机械键盘, copy 也跟着变

    # ⭐️ 证明「不回滚」：原来那条「袜子」线并没有被删，它仍然躺在历史里。
    #    （Fork 只是【新增】了一条分支，两条最终文案在历史中【共存】）
    print("历史中共存的两条最终文案：")
    for snap in graph.get_state_history(config):
        if snap.values.get("copy"):  # 只看已生成文案的帧
            print(f"   topic={snap.values['topic']:<5} copy={snap.values['copy']}")


# ═════════════════════════════════════════════════════════════
# 05. 「重放不是读缓存」的坑（会真重跑！）         【⭐️⭐️ 副作用警惕】
# ═════════════════════════════════════════════════════════════
#
# ⭐️⭐️ 重放/Fork 后，被重跑的节点是【真的又执行了一遍】，不是把上次结果拿出来。
#    所以：节点里若有「调大模型、发请求、写库、扣款」等副作用，重放时会【再发生一次】，
#    而且大模型/接口这次的返回可能和上次不一样。
# ⭐️ 这点和「人机交互.py 第09节」同源：凡是不可重复的副作用，要么做成幂等，
#    要么别指望「重放=拿回原值」。下面用计数器让你亲眼看到 write 又跑了一次。

_run_counter = {"count": 0}


class CntState(TypedDict):
    n: int


def step_one(state: CntState):
    return {"n": 1}


def step_two(state: CntState):
    _run_counter["count"] += 1   # 这就是「副作用」，每跑一次 +1
    print(f"   [step_two] 被真实执行了第 {_run_counter['count']} 次")
    return {"n": state["n"] + 100}


def demo_replay_is_not_cache():
    """⭐️ 首次执行 step_two 跑1次；重放后又跑1次 → 计数器=2。"""
    _run_counter["count"] = 0
    builder = StateGraph(CntState)
    builder.add_node("step_one", step_one)
    builder.add_node("step_two", step_two)
    builder.add_edge(START, "step_one")
    builder.add_edge("step_one", "step_two")
    builder.add_edge("step_two", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    config = new_config()
    graph.invoke({"n": 0}, config)  # step_two 跑第1次

    before_two = next(s for s in graph.get_state_history(config)
                      if s.next == ("step_two",))
    graph.invoke(None, before_two.config)  # 重放 → step_two 跑第2次

    print(f"   → 结论：step_two 共执行 {_run_counter['count']} 次（重放是真重跑，不是缓存）")


# ═════════════════════════════════════════════════════════════
# 06. as_node：让更新「以某个节点的身份」写入        【⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ update_state 默认会「猜」这次更新是哪个节点产生的（取最后写状态的节点），
#    据此决定【接下来从哪继续】、以及用谁的 reducer 合并。多数时候不用管。
# ⭐️ 什么时候要手动指定 as_node？
#    - 在一条全新 thread 上【造初始状态】（测试常用）
#    - 并行节点同一步都写了状态，自动推断有歧义
#    - 故意【跳过前面的节点】：把图当作「某个后续节点已经跑完了」，从它的下游继续
#
# 下面演示「跳步」：全新 thread 上，直接以 choose_topic 的身份塞入 topic，
# 让图认为 choose_topic 已完成，于是【直接从 write_copy 开始】跑。

def demo_as_node():
    """⭐️ 用 as_node 跳过 choose_topic，直接喂 topic 从 write_copy 起跑。"""
    graph = build_copy_graph()
    config = new_config()

    # ⭐️ 在空 thread 上，以「choose_topic 已产出」的身份写入 topic
    seeded = graph.update_state(
        config,
        {"topic": "人体工学椅"},
        as_node="choose_topic",   # ← 关键：假装是 choose_topic 写的
    )
    print("注入后 next =", graph.get_state(config).next)  # 应是 ('write_copy',)

    # 从这里继续：choose_topic 被跳过，直接跑 write_copy
    result = graph.invoke(None, seeded)
    print("结果（跳过了 choose_topic）：", result)


# ═════════════════════════════════════════════════════════════
# 07. 时间旅行 + interrupt：回到过去，重新回答        【⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：用户填了表/做了审批，后来反悔想改某一步的答案。
# ⭐️ 关键认知：当你 Replay/Fork 到一个【含 interrupt 的节点】之前，
#    该节点会重跑 → interrupt 会【再次触发】→ 图重新暂停等你给新答案。
#    于是「回到过去重新回答」自然成立。

class AskState(TypedDict):
    name: str
    greeting: str


def ask_name(state: AskState):
    name = interrupt("请输入你的名字")
    return {"name": name}


def make_greeting(state: AskState):
    return {"greeting": f"你好，{state['name']}！"}


def demo_time_travel_with_interrupt():
    """⭐️ 先回答 Alice 跑完；再 Fork 回 ask_name 之前，重新回答 Bob。"""
    builder = StateGraph(AskState)
    builder.add_node("ask_name", ask_name)
    builder.add_node("make_greeting", make_greeting)
    builder.add_edge(START, "ask_name")
    builder.add_edge("ask_name", "make_greeting")
    builder.add_edge("make_greeting", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    config = new_config()
    graph.invoke({"name": "", "greeting": ""}, config)        # 跑到 interrupt 暂停
    first = graph.invoke(Command(resume="Alice"), config)     # 回答 Alice
    print("第一次结果：", first)

    # ⭐️ 回到 ask_name 之前那一帧
    before_ask = next(s for s in graph.get_state_history(config)
                      if s.next == ("ask_name",))
    # 从这里重放：ask_name 重跑 → 又触发 interrupt → 重新暂停
    graph.invoke(None, before_ask.config)
    # ⭐️ 这次回答 Bob。注意：resume 要用【thread 级 config】(只含 thread_id)，
    #    它指向「当前暂停处」。若误用 before_ask.config（带具体 checkpoint_id），
    #    会被当成「再从那一帧重放一次」，你的新答案就生效不了（实测踩过这个坑）。
    second = graph.invoke(Command(resume="Bob"), config)
    print("回到过去重答后：", second)


# ═════════════════════════════════════════════════════════════
# 08. 子图的时间旅行（继承 vs 自带 checkpointer）     【⭐️ 高级】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 默认：子图【继承】父图的 checkpointer，父图把整个子图当作【一步】。
#    → 你只能倒回到「子图之前」，无法精确停在子图内部两个节点之间；
#      重放会把整个子图重跑。
# ⭐️ 若子图编译时写 compile(checkpointer=True)，它就有自己的内部检查点：
#    → 可以倒回到子图【内部】某两步之间；
#      用 graph.get_state(config, subgraphs=True) 才能拿到嵌套的子图快照。
#
# 这里只给一个「默认继承」的最小演示（生产里子图内部时间旅行很少用，了解即可）。

class SubState(TypedDict):
    x: int


def sub_step(state: SubState):
    return {"x": state["x"] + 1}


def build_with_subgraph():
    sub = StateGraph(SubState)
    sub.add_node("sub_step", sub_step)
    sub.add_edge(START, "sub_step")
    sub.add_edge("sub_step", END)
    subgraph = sub.compile()  # 默认：不带自己的 checkpointer，继承父图

    parent = StateGraph(SubState)
    parent.add_node("subgraph", subgraph)   # 整个子图作为父图的一个节点
    parent.add_edge(START, "subgraph")
    parent.add_edge("subgraph", END)
    return parent.compile(checkpointer=InMemorySaver())


def demo_subgraph_time_travel():
    """⭐️ 子图作为父图的「一步」，可倒回到子图之前并整体重跑。"""
    graph = build_with_subgraph()
    config = new_config()
    print("结果：", graph.invoke({"x": 10}, config))

    # 历史里子图只占一帧（父图视角的一步）
    print("父图视角的轨迹：")
    for snap in graph.get_state_history(config):
        print(f"  next={str(snap.next):<14} values={snap.values}")

    # 倒回到子图之前，整体重放
    before_sub = next(s for s in graph.get_state_history(config)
                      if s.next == ("subgraph",))
    print("倒回子图之前重放：", graph.invoke(None, before_sub.config))


# ═════════════════════════════════════════════════════════════
# 主入口：从上到下依次演示（非交互，看输出讲的故事即可）
# ═════════════════════════════════════════════════════════════

def banner(title: str):
    print("\n" + "═" * 60)
    print("▶", title)
    print("═" * 60)


if __name__ == "__main__":
    banner("01+02 执行轨迹 get_state_history")
    demo_history()

    banner("03 Replay 重放（只重跑 write_copy）")
    demo_replay()

    banner("04 Fork 分支（改 topic 走新路）")
    demo_fork()

    banner("05 重放不是读缓存（会真重跑）")
    demo_replay_is_not_cache()

    banner("06 as_node 跳步注入状态")
    demo_as_node()

    banner("07 时间旅行 + interrupt（回到过去重答）")
    demo_time_travel_with_interrupt()

    banner("08 子图的时间旅行")
    demo_subgraph_time_travel()
