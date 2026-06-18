"""
LangGraph 多智能体 (Multi-Agent) — 企业生产版完整教程
======================================================

⭐️ 承接「agent循环.py」：那篇讲清了【单个】Agent 怎么转（模型↔工具的循环）。
   但一个 Agent 塞 20 个工具、又管订单又管售后又管商品时，它会「选困难症」、
   提示词互相打架、越改越乱。企业的解法是【分工】：拆成多个各管一摊的专职 Agent，
   再加一个「主管」按需调度。这就是多智能体。

⭐️ 本篇用「电商客服中台」贯穿：一个【主管】+ 三个【专员】
      ┌─────────────┐
      │   主管 Sup   │  ← 只负责「这个问题该找谁」，不亲自查库
      └──────┬──────┘
       ┌─────┼─────┐
       ▼     ▼     ▼
   订单专员  商品专员  售后专员
   (查订单/  (搜商品/  (查订单/开
    物流)    查库存)   退换货工单)
   每个专员内部，就是「agent循环.py」里那个 模型↔工具 的循环。

⭐️ 三种主流拓扑（先建立全局认知）：
   ┌──────────┬──────────────────────────────┬─────────────────────────┐
   │ 拓扑      │ 怎么协作                       │ 适合                     │
   ├──────────┼──────────────────────────────┼─────────────────────────┤
   │ Supervisor│ 一个主管居中调度，专员答完回主管 │【最常用】职责清晰、好管控 │
   │ (主管制)  │ 主管再决定下一步或结束          │  客服/工单/审批流         │
   ├──────────┼──────────────────────────────┼─────────────────────────┤
   │ Swarm    │ 专员之间直接「转交」(handoff)， │ 流程像接力、阶段分明      │
   │ (蜂群)   │ 不回主管                       │  如售前→售中→售后        │
   ├──────────┼──────────────────────────────┼─────────────────────────┤
   │ Network  │ 人人可调人人(全连接)            │ 灵活但难管控，生产少用    │
   │ (网状)   │                               │  研究/探索场景            │
   └──────────┴──────────────────────────────┴─────────────────────────┘
   ⭐️ 企业 90% 用 Supervisor。本篇重点讲它（手写 + 现成库两种写法），Swarm 点到为止。

⭐️ 全篇最重要的一个认知——「转交(handoff)的本质就是 Command」：
   一个节点想把控制权交给另一个节点，就 return Command(goto="目标节点", update={...})。
   主管路由、专员交回、专员之间接力，底层【全是 Command(goto=...)】。
   你在 use_graph_api 学过的 Command，就是多智能体的地基。

──────────────────────────────────────────────────────────────────
⭐️ 全篇 API 速记（本机 langgraph==1.2.4 / langchain==1.3.6 /
   langgraph-supervisor==0.0.31，全部实测可跑）：

   子 Agent（专员）：每个就是一个普通 create_agent，记得起 name：
     from langchain.agents import create_agent
     order_agent = create_agent(model=glm_model, tools=[...],
                                system_prompt="...", name="order_agent")

   手写主管（看原理）：StateGraph + 结构化输出路由 + Command(goto=专员/END)
     glm_model.with_structured_output(Route).invoke(...)  # 让主管「选人」
     return Command(goto=下一个)                           # 转交控制权

   现成主管（生产首选）：
     from langgraph_supervisor import create_supervisor
     app = create_supervisor(agents=[...], model=glm_model, prompt="...").compile()
     # 要多轮记忆：.compile(checkpointer=PostgresSaver) + thread_id

──────────────────────────────────────────────────────────────────
⭐️ 重要程度图例（最多 5 颗 ⭐️）：
  ⭐️⭐️⭐️⭐️⭐️ 必懂   ⭐️⭐️⭐️⭐️ 重点   ⭐️⭐️⭐️ 常用   ⭐️⭐️ 了解   ⭐️ 边角

各小节速查（直接运行会从上到下依次演示，会真连 Postgres、真调 GLM）：
  01 为什么要多智能体 + 三种拓扑 .......... ⭐️⭐️⭐️⭐️⭐️  全篇地基认知
  02 造专员：每个专员 = 一个 create_agent . ⭐️⭐️⭐️⭐️⭐️  多智能体的零件
  03 转交的本质 = Command（手写看原理）.... ⭐️⭐️⭐️⭐️    理解机制必看
  04 手写 Supervisor（结构化路由+回主管）.. ⭐️⭐️⭐️⭐️⭐️  讲透主管制原理
  05 create_supervisor：一行生产版 ........ ⭐️⭐️⭐️⭐️⭐️  生产首选写法
  06 真实客服中台：主管+三专员+多轮记忆 ... ⭐️⭐️⭐️⭐️⭐️  完整落地形态
  07 Swarm：专员之间直接接力 handoff ...... ⭐️⭐️⭐️      另一种拓扑认知
  08 生产建议 + 单 vs 多 Agent 选型 ....... ⭐️⭐️⭐️⭐️    选型与认知收口
──────────────────────────────────────────────────────────────────
"""

import sys
import uuid
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from langchain.agents import create_agent  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.checkpoint.postgres import PostgresSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.types import Command  # noqa: E402
from langgraph_supervisor import create_supervisor  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from typing_extensions import Annotated, TypedDict  # noqa: E402

from provider import ecommerce  # noqa: E402
from provider import glm_model  # noqa: E402

import os  # noqa: E402

DB_URI = os.environ["DB_URI"]


def banner(title: str):
    print("\n" + "═" * 64)
    print("▶", title)
    print("═" * 64)


# ═════════════════════════════════════════════════════════════
# 工具（手脚）：按「业务领域」分三组，分别给三个专员用。
# 底层都调 provider/ecommerce.py 查真实 Postgres。
# ═════════════════════════════════════════════════════════════

# —— 订单领域 ——
@tool
def query_order(order_id: str) -> str:
    """根据订单号查订单详情（状态、金额、商品、下单时间）。"""
    o = ecommerce.get_order(order_id)
    return str(o) if o else f"未找到订单 {order_id}，请核对订单号。"


@tool
def query_logistics(order_id: str) -> str:
    """根据订单号查物流轨迹（承运商、运单号、最新位置）。"""
    lg = ecommerce.get_logistics(order_id)
    return str(lg) if lg else f"订单 {order_id} 暂无物流（可能未发货）。"


# —— 商品领域 ——
@tool
def search_product(keyword: str) -> str:
    """按关键词搜索商品（名称、SKU、价格、库存）。"""
    items = ecommerce.search_products(keyword)
    return str(items) if items else f"没搜到包含「{keyword}」的商品。"


@tool
def check_stock(sku: str) -> str:
    """根据 SKU 查某商品库存数量。"""
    p = ecommerce.get_product(sku)
    return f"{p['name']} 库存 {p['stock']} 件" if p else f"未找到商品 {sku}。"


# —— 售后领域（含写操作）——
@tool
def create_ticket(order_id: str, type: str, reason: str) -> str:
    """为订单创建售后工单。type 取值：退货/换货/维修/咨询。reason 是具体原因。
    这是一个会写库的操作，确认用户诉求后再调用。"""
    t = ecommerce.create_ticket(order_id, type, reason)
    return f"已创建售后工单 {t['ticket_id']}（{t['type']}），状态：{t['status']}。"


@tool
def list_tickets(order_id: str) -> str:
    """查某订单已有的售后工单。"""
    ts = ecommerce.list_tickets_by_order(order_id)
    return str(ts) if ts else f"订单 {order_id} 暂无售后工单。"


# ═════════════════════════════════════════════════════════════
# 02. 造专员：每个专员 = 一个 create_agent       【⭐️⭐️⭐️⭐️⭐️ 多智能体的零件】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 关键认知：多智能体不神秘——每个「专员」就是「agent循环.py」里的那种单 Agent，
#    只是【只给它本领域的工具 + 本领域的人设】。职责越窄，它表现越稳。
# ⭐️ name 一定要起：主管就是靠 name 来点名「这事交给 order_agent」。

def build_specialists():
    order_agent = create_agent(
        model=glm_model,
        tools=[query_order, query_logistics],
        system_prompt="你是订单物流专员。只负责查订单状态和物流，必须先查工具再答，简洁回复。",
        name="order_agent",
    )
    product_agent = create_agent(
        model=glm_model,
        tools=[search_product, check_stock],
        system_prompt="你是商品专员。只负责商品搜索和库存查询，必须先查工具再答，简洁回复。",
        name="product_agent",
    )
    aftersales_agent = create_agent(
        model=glm_model,
        tools=[query_order, create_ticket, list_tickets],
        system_prompt=(
            "你是售后专员，负责退货/换货/维修。处理流程：\n"
            "1) 先用 query_order 确认订单存在；\n"
            "2) 确认用户诉求后，【必须调用 create_ticket 工具】来开工单。\n"
            "⭐️ 工单号一律以 create_ticket 工具的返回为准，严禁自己编造工单号。\n"
            "未调用工具就不能声称已开单。简洁回复。"
        ),
        name="aftersales_agent",
    )
    return order_agent, product_agent, aftersales_agent


def demo_one_specialist():
    """先单独验证一个专员能独立干活（它就是个普通单 Agent）。"""
    order_agent, _, _ = build_specialists()
    out = order_agent.invoke({"messages": [("user", "SO20250601001 到哪了？")]})
    print("订单专员单独作答：", out["messages"][-1].content.strip()[:70])


# ═════════════════════════════════════════════════════════════
# 03. 转交的本质 = Command（手写看原理）         【⭐️⭐️⭐️⭐️ 理解机制必看】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 多智能体里「把活交给谁」叫 handoff（转交）。它没有魔法，就是一个节点
#    return Command(goto="另一个节点", update={往共享状态里写点东西})。
# ⭐️ 下面用【不带 LLM】的最小例子把它看死：reception 节点直接转交给 worker 节点。
#    真实主管只是把这里的「写死 goto」换成「让 LLM 决定 goto 谁」（第04节）。

class MiniState(TypedDict):
    messages: Annotated[list, add_messages]


def demo_handoff_essence():
    def reception(state: MiniState) -> Command:
        print("  [前台] 我不处理具体问题，转交给 worker")
        # ⭐️ 这一行就是 handoff：goto 指向下一个节点，update 写入共享状态
        return Command(goto="worker", update={"messages": [AIMessage("（前台转交）")]})

    def worker(state: MiniState) -> Command:
        print("  [worker] 收到转交，开始干活")
        return Command(goto=END, update={"messages": [AIMessage("worker 处理完毕")]})

    b = StateGraph(MiniState)
    b.add_node("reception", reception)
    b.add_node("worker", worker)
    b.add_edge(START, "reception")
    g = b.compile()
    out = g.invoke({"messages": [("user", "随便问个问题")]})
    print("  共享状态里累计消息：", [m.content for m in out["messages"]])
    print("⭐️ 记住这一点：主管路由、专员交回，底层全是 Command(goto=...)。")


# ═════════════════════════════════════════════════════════════
# 04. 手写 Supervisor（结构化路由 + 回主管）      【⭐️⭐️⭐️⭐️⭐️ 讲透主管制】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 主管制 = 一个「主管节点」居中，循环做三件事：
#    1) 看当前对话 →（用结构化输出）决定下一个交给哪个专员，或者 FINISH 结束
#    2) Command(goto=该专员) 把控制权交过去
#    3) 专员干完 Command(goto="supervisor") 把控制权【交回】主管，主管再判断
# ⭐️ 这其实是一个「主管↔专员」的大循环，和单 Agent 的「模型↔工具」循环异曲同工，
#    只是把「工具」换成了「专员」。所以同样需要 recursion_limit 兜底。

class CSState(TypedDict):
    messages: Annotated[list, add_messages]


class Route(BaseModel):
    """主管的路由决策。"""
    next: Literal["order_agent", "product_agent", "aftersales_agent", "FINISH"]


def _make_member_node(agent, name: str):
    """把一个专员包成图节点：跑完把它的最终答复写回共享 messages，再交回主管。"""
    def node(state: CSState) -> Command:
        out = agent.invoke({"messages": state["messages"]})
        answer = out["messages"][-1].content
        print(f"  [{name}] 处理完，交回主管")
        # ⭐️ 用 name 标注这条消息是哪个专员说的；goto 回 supervisor
        return Command(
            goto="supervisor",
            update={"messages": [AIMessage(content=answer, name=name)]},
        )
    return node


def build_handwritten_supervisor():
    order_agent, product_agent, aftersales_agent = build_specialists()

    def supervisor(state: CSState) -> Command:
        sys_prompt = (
            "你是电商客服主管，负责【调度】不亲自答。根据对话把任务分给：\n"
            "- order_agent：订单状态、物流查询\n"
            "- product_agent：商品搜索、库存价格\n"
            "- aftersales_agent：退货、换货、维修、开售后工单\n"
            "如果最近一条已经是专员给出的、能回答用户的答复，就选 FINISH 结束。"
        )
        decision = glm_model.with_structured_output(Route).invoke(
            [("system", sys_prompt)] + state["messages"]
        )
        print(f"  [主管] 决策 → {decision.next}")
        if decision.next == "FINISH":
            return Command(goto=END)
        return Command(goto=decision.next)

    b = StateGraph(CSState)
    b.add_node("supervisor", supervisor)
    b.add_node("order_agent", _make_member_node(order_agent, "order_agent"))
    b.add_node("product_agent", _make_member_node(product_agent, "product_agent"))
    b.add_node("aftersales_agent", _make_member_node(aftersales_agent, "aftersales_agent"))
    b.add_edge(START, "supervisor")           # ⭐️ 入口先到主管；专员节点用 Command 动态回主管
    return b.compile()


def demo_handwritten_supervisor():
    app = build_handwritten_supervisor()
    out = app.invoke(
        {"messages": [("user", "我想看看你们有没有保温杯，多少钱？")]},
        {"recursion_limit": 12},          # ⭐️ 主管↔专员也是循环，必须兜底
    )
    print("最终回答：", out["messages"][-1].content.strip()[:80])


# ═════════════════════════════════════════════════════════════
# 05. create_supervisor：一行生产版              【⭐️⭐️⭐️⭐️⭐️ 生产首选】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 第04节那套「主管节点 + 路由 + 交回」，生产里用 langgraph-supervisor 一行搞定：
#    create_supervisor(agents=[...], model=, prompt=).compile()
#    它内部用「handoff 工具」实现转交（主管把『转给某专员』当成调用一个工具），
#    机制和你手写的等价，但帮你处理好了消息传递、交回、并行等细节。
# ⭐️ 何时手写、何时用库：想完全掌控路由逻辑/加自定义校验 → 手写；常规调度 → 用库。

def build_prebuilt_supervisor(checkpointer=None):
    order_agent, product_agent, aftersales_agent = build_specialists()
    workflow = create_supervisor(
        agents=[order_agent, product_agent, aftersales_agent],
        model=glm_model,
        prompt=(
            "你是电商客服主管，只做调度不亲自答：\n"
            "订单/物流问题 → order_agent；商品/库存/价格 → product_agent；"
            "退换货/维修/开工单 → aftersales_agent。\n"
            "专员答复已能解决用户问题时，直接结束。"
        ),
    )
    return workflow.compile(checkpointer=checkpointer)


def demo_prebuilt_supervisor():
    app = build_prebuilt_supervisor()
    out = app.invoke({"messages": [("user", "订单 SO20250601001 的快递到哪了？")]})
    print("最终回答：", out["messages"][-1].content.strip()[:80])
    print(f"⭐️ 内部经过 主管→order_agent→主管 的转交，共 {len(out['messages'])} 条消息。")


# ═════════════════════════════════════════════════════════════
# 06. 真实客服中台：主管+三专员+多轮记忆         【⭐️⭐️⭐️⭐️⭐️ 完整落地形态】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 把前面的拼成「真实中台」：create_supervisor + PostgresSaver（多轮记忆，见 记忆.py）。
#    同一个 thread_id 下连续问，主管会把不同问题分派给不同专员，且记得上文。
# ⭐️ 演示一个真实对话流：
#    第1轮：查物流（→ order_agent）
#    第2轮：耳机有杂音要退货（→ aftersales_agent，会真的写一条工单进 Postgres）
#    全程同一个 thread，第2轮能接住第1轮提到的订单号。

def demo_real_cs_hub():
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()  # 幂等建表
        app = build_prebuilt_supervisor(checkpointer=checkpointer)
        cfg = {"configurable": {"thread_id": f"cs-{uuid.uuid4()}"},
               "recursion_limit": 20}

        print("【第1轮】用户：我的订单 SO20250601001 快递到哪了？")
        out1 = app.invoke(
            {"messages": [("user", "我的订单 SO20250601001 快递到哪了？")]}, cfg)
        print("  客服：", out1["messages"][-1].content.strip()[:70], "\n")

        print("【第2轮】用户：这个订单买的耳机有杂音，我要退货")
        out2 = app.invoke(
            {"messages": [("user", "这个订单买的耳机有杂音，我要退货")]}, cfg)
        print("  客服：", out2["messages"][-1].content.strip()[:90])

        # 验证售后专员真的把工单写进了 Postgres
        tickets = ecommerce.list_tickets_by_order("SO20250601001")
        if tickets:
            print(f"\n⭐️ 落库验证：订单 SO20250601001 现有 {len(tickets)} 条售后工单"
                  f"（最新：{tickets[0]['type']} / {tickets[0]['status']}）")
            print("⭐️ 第2轮没报订单号也能处理，因为 checkpointer 记得第1轮的上下文。")
        else:
            print("\n⚠️ 本次售后专员未真正调用 create_ticket（模型偶发不调工具/自己编了工单号）。"
                  "\n   这正是真实风险：写操作类工具要在 prompt 里强约束『必须调用工具、"
                  "禁止编造』，必要时再加校验或人工确认。重跑一次通常就正常了。")


# ═════════════════════════════════════════════════════════════
# 07. Swarm：专员之间直接接力 handoff            【⭐️⭐️⭐️ 另一种拓扑】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ Supervisor 是「凡事回主管」；Swarm 是「专员之间直接转交，不回主管」，像接力赛。
#    适合阶段分明的流程。它的转交底层还是 Command(goto=另一个专员)——换汤不换药。
# ⭐️ 这里用手写最小例子演示「售前专员 → 直接转给 → 售后专员」的接力（不经过主管）。
#    （生产可用 langgraph-swarm 库，原理一致，这里重在让你看清『直接 handoff』。）

class SwarmState(TypedDict):
    messages: Annotated[list, add_messages]


def demo_swarm_handoff():
    def presale(state: SwarmState) -> Command:
        print("  [售前] 用户已下单，我直接转交售后跟进，不回主管")
        return Command(goto="aftersale",
                       update={"messages": [AIMessage("（售前→售后 接力）")]})

    def aftersale(state: SwarmState) -> Command:
        print("  [售后] 接到售前转交，继续处理")
        return Command(goto=END,
                       update={"messages": [AIMessage("售后已接手并处理")]})

    b = StateGraph(SwarmState)
    b.add_node("presale", presale)
    b.add_node("aftersale", aftersale)
    b.add_edge(START, "presale")
    g = b.compile()
    out = g.invoke({"messages": [("user", "我刚下单了")]})
    print("  接力链路结果：", [m.content for m in out["messages"] if m.content])
    print("⭐️ 对比第04节：Supervisor 专员干完 goto『supervisor』；Swarm 直接 goto『下一个专员』。")


# ═════════════════════════════════════════════════════════════
# 08. 生产建议 + 单 vs 多 Agent 选型             【⭐️⭐️⭐️⭐️ 认知收口】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 先别急着上多智能体——它更复杂、更慢、更贵。选型判断：
#    ┌────────────────────────────────┬──────────────────────────────┐
#    │ 用【单个】Agent（agent循环.py） │ 用【多】Agent（本篇）          │
#    ├────────────────────────────────┼──────────────────────────────┤
#    │ 工具就几个、职责单一            │ 工具多到模型选困难症           │
#    │ 一个领域的事                   │ 跨多个领域（订单/商品/售后）   │
#    │ 想快、想省 token               │ 各领域 prompt/工具会互相打架   │
#    │                                │ 需要不同领域独立演进/独立团队维护│
#    └────────────────────────────────┴──────────────────────────────┘
#
# ⭐️ 拓扑选型：日常优先 Supervisor（好管控、易追责）；流程像接力才上 Swarm；
#    Network（全连接）生产基本不用。
# ⭐️ 落地清单：
#    1) 专员职责切窄，每个只给本领域工具——这是多智能体稳不稳的关键。
#    2) 主管↔专员是循环，recursion_limit 必设（和单 Agent 一样会失控）。
#    3) 多轮对话 → 编译时挂 checkpointer（PostgresSaver），见 记忆.py。
#    4) 常规调度用 create_supervisor；要定制路由/加校验就手写主管（第04节）。
#    5) 写操作类专员（如开工单）要在 prompt 里明确「确认诉求后再写」，防误触发副作用。

def demo_production_note():
    print("多智能体生产清单：")
    print("  1) 专员职责切窄，只给本领域工具（稳定性关键）")
    print("  2) 主管↔专员是循环 → recursion_limit 必设")
    print("  3) 多轮记忆 → 编译挂 checkpointer（PostgresSaver）")
    print("  4) 常规调度用 create_supervisor；要定制就手写主管")
    print("  5) 能用单 Agent 解决就别上多 Agent（更慢更贵更复杂）")


# ⭐️ 模块级图：供 langgraph.json 注册，可在 langgraph dev / studio 里打开调试。
#    （平台自带持久化，这里不挂 checkpointer。）
supervisor_app = build_prebuilt_supervisor()


# ═════════════════════════════════════════════════════════════
# 主入口：从上到下依次演示（会真连 Postgres、真调 GLM）
#
# 运行前确保业务库已就绪（幂等）：  python provider/ecommerce.py
# 然后：  python 官方文档/多智能体/多智能体.py
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    ecommerce.seed_all()

    banner("02 造专员：单个专员 = 一个普通 create_agent")
    demo_one_specialist()

    banner("03 转交的本质 = Command(goto=...)（不带 LLM 看清原理）")
    demo_handoff_essence()

    banner("04 手写 Supervisor（结构化路由 + 专员交回主管）")
    demo_handwritten_supervisor()

    banner("05 create_supervisor：一行生产版")
    demo_prebuilt_supervisor()

    banner("06 真实客服中台：主管+三专员+多轮记忆（会真写工单进库）")
    demo_real_cs_hub()

    banner("07 Swarm：专员之间直接接力 handoff（不回主管）")
    demo_swarm_handoff()

    banner("08 生产建议 + 单 vs 多 Agent 选型")
    demo_production_note()
